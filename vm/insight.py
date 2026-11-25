"""새 컨셉을 들고 왔을 때: 비슷한 과거 사례 → 왜 멈췄나 → 지금 트렌드·타이밍 → 다시 해볼 가치.

모든 판단은 등록된 자료(store)에서 계산한 수치와 규칙으로 하고, 근거와 함께 돌려준다.
가상 소비자로 확인할 수 있는 이유(수요·가격·맛·이해도)와 없는 이유(유통·보관·사업성)를 나눈다.
"""
from __future__ import annotations

import re

import pandas as pd

from . import store
from .audit import view as _view
from .audit import num, unit_size
from .challenge import ALIASES, terms

REASON_TYPES = [  # (유형, 단어, 가상 소비자로 확인 가능?, 다시 볼 때 확인할 것) — 위에서부터 먼저 맞는 것
    ("유통·보관 문제", r"냉장|냉동|폐기|취급|유통|회전|분리|보관|소비기한|물류|진열", "아니오", "지금 유통 인프라·보관 조건이 달라졌는지"),
    ("계획된 종료(시즌·한정)", r"시즌|계획된", "부분", "같은 시즌·같은 채널에서의 판매 흐름"),
    ("수요·가격 문제", r"수요|부진|가격|프리미엄|비싸|맛|선호", "예", "같은 우려가 지금 소비자에게도 있는지(가상 소비자 확인)"),
    ("사업성·전략", r"사업성|손익|포트폴리오|라인업|정리|전략", "부분", "원가·포트폴리오 조건 변화(내부 확인) + 수요 크기"),
]
SEASONAL = r"시즌|여름|한정|겨울"


def classify_reason(text) -> dict:
    t = "" if text is None or (isinstance(text, float) and pd.isna(text)) else str(text)
    for kind, pat, testable, check in REASON_TYPES:
        if re.search(pat, t):
            return {"유형": kind, "가상 소비자 확인": testable, "확인할 것": check}
    return {"유형": "사유 미상", "가상 소비자 확인": "부분",
            "확인할 것": "담당자에게 중단 사유 확인 필요. 그 전까지는 소비자 측 우려(맛·가격·필요성)만 가상으로 점검"}


def _pos_ea():
    pos = _view("pos")
    if pos.empty:
        return pos
    p = pos.copy()
    p["ea"] = num(p["판매수량"]) * p.get("수량단위", pd.Series("EA", index=p.index)).map(unit_size)
    p["promo"] = p.get("행사구분", pd.Series("없음", index=p.index)).astype(str).ne("없음")
    p["valid"] = (p["ea"] > 0) & ~p["제품코드"].astype(str).str.contains("TEST", case=False) \
        & ~p.drop(columns=[c for c in p if c.startswith("_")] + ["ea", "promo"]).duplicated()
    p["unit_price"] = num(p.get("판매금액")) / p["ea"]
    return p


def sales_profile(code: str, p: pd.DataFrame | None = None) -> dict | None:
    p = _pos_ea() if p is None else p
    if p.empty:
        return None
    d = p[(p["제품코드"].astype(str) == str(code)) & p["valid"]]
    if d.empty:
        return None
    monthly = d.groupby("기준월")["ea"].sum()
    base = d[~d["promo"]].groupby("기준월")["ea"].sum()
    return {"판매 개월": int(monthly.size), "월평균(EA)": int(monthly.mean()), "최고 월": str(monthly.idxmax()),
            "행사 비중": round(float(d.loc[d["promo"], "ea"].sum() / d["ea"].sum()), 2),
            "행사 없는 월평균(EA)": int(base.mean()) if len(base) else None,
            "행사 없는 평균 단가(원)": int(d.loc[~d["promo"], "unit_price"].median()) if (~d["promo"]).any() else None}


def similar_history(name: str, description: str = "", k: int = 6) -> list[dict]:
    """제품자산·과거 컨셉테스트·추가 자료에서 비슷한 사례. 공통 단서 수로 순위."""
    q = terms(f"{name} {description}")
    assets, hist = _view("assets"), _view("concept_history")
    p = _pos_ea()
    out = []
    for _, r in assets.iterrows():
        text = " ".join(str(r.get(c, "")) for c in ("제품명", "카테고리", "컨셉요약", "용기·용량", "브랜드", "비고"))
        common = q & terms(text)
        if not common or (len(common) == 1 and not (q & terms(str(r.get("카테고리", ""))))):
            continue
        status = str(r.get("상태", ""))
        if re.search("단종|중단", status):
            reason = classify_reason(r.get("단종·중단사유"))
        elif re.search("운영|판매", status):
            reason = {"유형": "판매 중(자사 잠식 확인 대상)", "가상 소비자 확인": "예", "확인할 것": "신제품이 이 제품 수요를 가져가는지(자사 잠식)"}
        else:
            reason = {"유형": f"{status or '상태 미상'}(진행 중 검토안)", "가상 소비자 확인": "-", "확인할 것": "중복 검토 여부 확인"}
        item = {"제품": r.get("제품명"), "코드": r.get("SKU코드"), "상태": r.get("상태"), "카테고리": r.get("카테고리"),
                "기간": f"{r.get('출시일') if pd.notna(r.get('출시일')) else '?'} ~ {r.get('폐지(중단)일') if pd.notna(r.get('폐지(중단)일')) else '현재'}"
                        + (" ⚠날짜 순서 확인" if pd.notna(pd.to_datetime(r.get("출시일"), errors="coerce")) and pd.notna(pd.to_datetime(r.get("폐지(중단)일"), errors="coerce"))
                           and pd.to_datetime(r.get("출시일"), errors="coerce") > pd.to_datetime(r.get("폐지(중단)일"), errors="coerce") else ""),
                "중단 사유": r.get("단종·중단사유") if pd.notna(r.get("단종·중단사유")) else "자료 없음",
                **{f"사유 {k}": v for k, v in reason.items()}, "공통 단서": ", ".join(sorted(common)), "_score": len(common),
                "출처": f"{r.get('_file', '')} {r.get('_sheet', '')} {r.get('_row', '')}행"}
        if pd.notna(r.get("최고연매출(억원)")):
            item["최고 연매출(억원)"] = r.get("최고연매출(억원)")
        code_dup = (assets["SKU코드"].astype(str) == str(r.get("SKU코드"))).sum() > 1
        sp = sales_profile(r.get("SKU코드"), p) if pd.notna(r.get("SKU코드")) and not code_dup else None  # 코드가 겹치면 실적을 붙이지 않음
        if sp:
            item["판매 실적"] = sp
        generic = ({"캔", "pet", "ml", "병", "유리병", "시즌한정", "한정", "프리미엄"} | set(ALIASES)
                   | {str(b).lower() for b in assets.get("브랜드", pd.Series(dtype=str)).dropna()})
        distinct = lambda a, b: (terms(a) & terms(b)) - generic  # noqa: E731  브랜드·용기 말고 제품 고유 단어가 겹쳐야 같은 제품
        match = hist[hist["제품"].astype(str).map(lambda x: bool(distinct(x, str(r.get("제품명"))))
                                                   and str(r.get("제품명")) in _best_assets(x, assets))] if not hist.empty else hist
        if len(match):
            h = match.loc[match["제품"].astype(str).map(lambda x: len(distinct(x, str(r.get("제품명"))))).idxmax()]
            item["과거 컨셉테스트"] = {"구매의향 TOP2": h.get("컨셉테스트_구매의향TOP2"), "12개월 실제 구매경험률": h.get("출시12개월_실제구매경험률"),
                                "취급점포율": h.get("출시6개월_취급점포율"), "비고": h.get("비고")}
        out.append(item)
    from .archive_records import records  # 화면에서 추가한 옛 자료
    for r in records():
        common = q & terms(" ".join(str(r.get(c, "")) for c in ("제품", "분류", "컨셉", "규격")))
        if common:
            out.append({"제품": r.get("제품"), "상태": r.get("상태"), "카테고리": r.get("분류"), "중단 사유": r.get("사유"),
                        **{f"사유 {k}": v for k, v in classify_reason(r.get("사유")).items()},
                        "공통 단서": ", ".join(sorted(common)), "_score": len(common), "출처": f"{r['file']} {r['location']}"})
    out.sort(key=lambda x: -x["_score"])
    return out[:k]


def _best_assets(test_name: str, assets: pd.DataFrame) -> set[str]:
    """과거 컨셉테스트 한 건이 가리키는 제품: 이름 단어가 가장 많이 겹치는 제품자산(동점이면 모두).
    예) '델몬트 프리미엄 포도' → '델몬트 프리미엄 포도 400mL'(3개 겹침)만, '델몬트 포도 400mL PET'(2개)는 아님."""
    noise = {"캔", "pet", "ml", "병"}
    t = {w for w in terms(test_name) if w not in noise and not re.fullmatch(r"\d+(ml|l)?", w)}
    scores = {str(n): len(t & terms(str(n))) for n in assets["제품명"].dropna()}
    top = max(scores.values(), default=0)
    return {n for n, v in scores.items() if v == top and v > 0}


def _fmt(v):
    return f"{v:.1f}" if abs(v) < 10 else f"{v:.0f}"  # 네이버처럼 작은 상대값도 보이게


def trend_timing(name: str, description: str = "", launch: str | None = None) -> list[dict]:
    """관련 검색 키워드별: 전년 대비, 계절성, 광고성 급등, 출시 시점과의 관계."""
    trend, sns = _view("search_trend"), _view("sns")
    if trend.empty:
        return []
    q = terms(f"{name} {description}")
    out = []
    for kw in [c for c in trend.columns if c != "기준월" and not c.startswith("_")]:
        if not (q & terms(kw)):
            continue
        raw = pd.Series(num(trend[kw]).values, index=trend["기준월"].astype(str))
        raw = raw.groupby(level=0).mean().sort_index()  # 같은 달이 여러 표에 있으면 평균(같은 자료가 두 번 들어간 경우 등)
        have = raw.dropna()
        if have.empty:
            continue
        # 이 키워드에 값이 있는 기간만(다른 자료가 더 최근 달까지 있어도 비교 구간이 밀리지 않게), 달력은 빠짐없이
        span = [str(p) for p in pd.period_range(have.index.min(), have.index.max(), freq="M")]
        raw = raw.reindex(span)
        s = raw.where(raw.between(0, 100))  # 범위 밖 값은 비워 두되 달력 위치는 유지
        if s.notna().sum() < 13:
            out.append({"키워드": kw, "단계": "자료 부족", "근거": f"{int(s.notna().sum())}개월"})
            continue
        last, prev = s.iloc[-12:], s.iloc[-24:-12]  # 달력 기준 최근 12개월 vs 그 전 12개월
        growth = last.mean() / prev.mean() - 1 if prev.mean() else None
        yoy = []
        for m, v in last.dropna().items():
            y, mm = m.split("-")
            p = s.get(f"{int(y) - 1}-{mm}")
            if p is not None and p > 0:
                yoy.append((m, v, p))
        peak_last = last.max() if last.notna().any() else None
        peak_prev = prev.max() if prev.notna().any() else None
        peak_months = sorted({m[-2:] for m in s.dropna().nlargest(3).index})
        seasonal = len(prev) >= 12 and pd.Series(last.values).corr(pd.Series(prev.values[-len(last):])) > 0.7
        ad = {}
        if not sns.empty:
            d = sns[sns["키워드"].astype(str) == kw]
            ad = num(d["광고·협찬 비중"]).groupby(d["기준월"].astype(str).values).mean().to_dict()
        ad_med = pd.Series(ad).median() if ad else None
        spikes = [(m, v, p) for m, v, p in yoy if v >= p * 1.8 and v >= 50]
        ad_spikes = [m for m, _, _ in spikes if ad_med is not None and ad.get(m, 0) >= max(ad_med * 2, 0.4)]
        if spikes and len(ad_spikes) >= len(spikes) / 2:
            stage = "광고성 급등(자연 수요 확인 필요)"
        elif peak_prev and peak_last is not None and peak_last < peak_prev * 0.7 and seasonal is False:
            stage = "성수기 관심 감소"
        elif growth is not None and growth > 0.15:
            stage = "계절 반복 + 성장" if seasonal else "성장"
        elif growth is not None and growth < -0.15:
            stage = "하락"
        elif seasonal:
            stage = "계절 반복(정체)"
        else:
            stage = "정체"
        row = {"키워드": kw, "단계": stage, "최근 12개월 평균 대비 전년": f"{growth:+.0%}" if growth is not None else "-",
               "최고 시기(월)": ", ".join(peak_months), "최근 값": f"{s.dropna().index[-1]} {_fmt(s.dropna().iloc[-1])}",
               "성수기 최고치(전년→최근)": f"{_fmt(peak_prev)} → {_fmt(peak_last)}" if peak_prev is not None and peak_last is not None else "-",
               "광고성 급등 월": ", ".join(ad_spikes) or "없음"}
        if s.max() < 20:  # 네이버처럼 함께 받은 키워드 중 최대=100 기준이면, 작은 값의 증감은 흔들림이 큼
            row["단계"] = f"{stage}(검색량 적음·참고)"
            row["_참고"] = True
        if launch:
            lm, pk = launch[-2:], row["최고 시기(월)"]
            if lm < peak_months[0]:
                row["출시 시점"] = f"{launch} 출시 → 최고 시기({pk}) 전 진입"
            elif lm <= peak_months[-1]:
                row["출시 시점"] = (f"{launch} 출시 → 최고 시기({pk}) 중 진입" + (" · 마지막 최고 달이라 늦을 수 있음"
                                                                     if lm == peak_months[-1] and len(peak_months) > 1 else ""))
            else:
                row["출시 시점"] = f"{launch} 출시 → 올해 최고 시기 이후 진입(늦음)"
        out.append(row)
    return out


def retry_verdict(history: list[dict], timing: list[dict]) -> dict:
    """규칙 기반 판단(근거 포함). 결정은 사람이 한다."""
    if store.version() == "자료 없음":
        return {"판단": "판단 불가 — 등록된 자료 없음", "이유": ["'① 자료 준비'에서 파일을 올리거나 기존 DB를 연결하고 분석 묶음을 고르면 과거 사례·트렌드를 찾습니다."],
                "확인할 것": [], "가상 소비자로 확인할 질문": [], "트렌드 단계": "자료 없음"}
    if not history:
        base = (f"지금 분석 묶음({', '.join(store.analysis_datasets())})의 자료에는 비슷한 제품이 없음 — 다른 묶음을 고르거나, "
                "새 카테고리라면 가상 소비자로 이해도·필요성부터 확인")
        return {"판단": "근거 부족", "이유": [base], "가상 소비자로 확인할 질문": ["이 제품이 무엇인지 이해되나", "어떤 상황에 사겠나"]}
    reasons, checks, questions = [], [], []
    kinds = {h["사유 유형"] for h in history if h.get("상태") and re.search("단종|중단", str(h["상태"]))}
    main = [t for t in timing if not t.get("_참고")]  # 검색량이 적은 키워드는 표에는 보이되 판단에는 쓰지 않음
    stages = {t["단계"] for t in main}
    late = any("늦음" in t.get("출시 시점", "") for t in main)
    for h in history:
        if re.search("단종|중단", str(h.get("상태", ""))):
            reasons.append(f"{h['제품']} — {h['중단 사유']} ({h['사유 유형']})")
            checks.append(h["사유 확인할 것"])
            if h["사유 가상 소비자 확인"] == "예":
                questions.append(f"비슷한 과거 제품 '{h['제품']}'은 '{h['중단 사유']}'로 중단됨 — 이 제품도 같은 이유로 사지 않을 것 같다")
            elif h["사유 유형"] == "사유 미상":
                questions.append(f"비슷한 과거 제품 '{h['제품']}'이 중단됨(사유 미상) — 이 제품도 한두 번 사고 말 것 같다")
    if any("광고성" in s for s in stages):
        verdict = "보류 — 트렌드가 광고로 만든 신호일 수 있음"
    elif "하락" in stages or late:
        verdict = "타이밍 늦음 가능성 — 시점·차별점 재검토"
    elif "유통·보관 문제" in kinds:
        verdict = "조건부 — 과거 실패 원인이 유통·보관이면 인프라가 바뀌었는지 먼저 확인"
    elif "수요·가격 문제" in kinds or "사유 미상" in kinds:
        verdict = "조건부 — 같은 우려가 지금도 있는지 가상 소비자로 확인"
    elif stages & {"성장", "계절 반복 + 성장"}:
        verdict = "재시도 가치 있음 — 관련 관심이 커지는 중"
    else:
        verdict = "중립 — 선례는 있으나 뚜렷한 장애·기회 신호 없음"
    return {"판단": verdict, "이유": reasons or ["운영 중인 유사 제품만 있음(잠식 가능성 확인)"],
            "확인할 것": list(dict.fromkeys(checks)), "가상 소비자로 확인할 질문": list(dict.fromkeys(questions))[:4],
            "트렌드 단계": ", ".join(f"{t['키워드']}: {t['단계']}" for t in timing) or "관련 키워드 없음"}


def competitors(name: str, description: str = "", k: int = 4) -> list[dict]:
    """POS에서 같은 카테고리의 판매 제품(자사·경쟁)과 행사 없는 실제 평균 단가. 비교 설문·진열대에 바로 쓴다."""
    p = _pos_ea()
    if p.empty:
        return []
    assets = _view("assets")
    stopped = set(assets.loc[assets["상태"].astype(str).str.contains("단종|중단"), "제품명"].astype(str)) if not assets.empty else set()
    p = p[~p["제품명"].astype(str).isin(stopped)]  # 이미 단종된 제품은 비교 대상에서 뺀다
    q = terms(f"{name} {description}")
    rows = []
    for (code, pname, cat), d in p[p["valid"]].groupby(["제품코드", "제품명", "카테고리"]):
        common = q & (terms(str(cat)) | terms(str(pname)))
        if not common:
            continue
        base = d[~d["promo"]]
        vol = re.search(r"(\d+)\s*mL", str(pname), re.I)
        rows.append({"id": f"P_{code}", "name": str(pname), "price": int(round(base["unit_price"].median() / 100) * 100) if len(base) else 0,
                     "volume_ml": int(vol.group(1)) if vol else 500, "description": f"{cat} · 실제 판매 제품(POS 행사 없는 평균 단가)",
                     "자사": not str(code).startswith("X"), "월평균(EA)": int(d.groupby("기준월")["ea"].sum().mean()), "_score": len(common)})
    rows.sort(key=lambda r: (-r["_score"], -r["월평균(EA)"]))
    return rows[:k]


def _pct(v):
    v = pd.to_numeric(v, errors="coerce")
    return "-" if pd.isna(v) else f"{v * 100:.0f}%" if v <= 1 else f"{v:.0f}%"


def conversion(storage: str = "", channels: str = "") -> dict:
    """과거 컨셉테스트의 설문 TOP2 → 실제 12개월 구매경험률 환산계수와, 유통 제약이 있을 때의 범위."""
    hist, infra = _view("concept_history"), _view("infra")
    if hist.empty:
        return {}
    h = hist.assign(f=num(hist["환산계수(실제/의향)"]), dist=num(hist.get("출시6개월_취급점포율")))
    normal = h[h["dist"] >= 0.7]["f"]
    limited = h[h["dist"] < 0.7]["f"]
    out = {"정상 유통 환산계수": [round(float(normal.min()), 3), round(float(normal.max()), 3)] if len(normal) else None,
           "제한 유통 환산계수": [round(float(limited.min()), 3), round(float(limited.max()), 3)] if len(limited) else None,
           "근거": "; ".join(f"{r['제품']} 구매의향 TOP2 {_pct(r['컨셉테스트_구매의향TOP2'])} → 실제 구매경험률 {_pct(r['출시12개월_실제구매경험률'])}"
                           f" (취급 점포 {_pct(r.get('출시6개월_취급점포율'))})" for _, r in hist.iterrows())}
    if not infra.empty and storage:
        col = "냉동 음료 진열 가능 점포율" if "냉동" in storage else "냉장 쇼케이스 보유율" if "냉장" in storage else None
        if col and col in infra:
            want = [re.sub(r"\(.*?\)", "", x).strip() for x in re.split(r"[,·/]+", channels) if x.strip()]
            base = lambda t: re.sub(r"\(.*?\)", "", str(t)).strip()  # noqa: E731  괄호 설명은 떼고 비교
            sel = infra[infra["채널"].map(lambda c: not want or any(w and (w in base(c) or base(c) in w) for w in want))]
            out["취급 가능 점포 비율"] = {str(r["채널"]): r[col] for _, r in sel.iterrows() if pd.notna(r[col])}
            vals = list(out["취급 가능 점포 비율"].values())
            low = [v for v in vals if v < 0.7]
            out["적용"] = ("제한 유통 계수 사용(보관 조건 때문에 주요 채널 취급 점포가 제한됨)" if vals and len(low) >= len(vals) / 2
                          else "정상 유통 계수 사용" + (f"(일부 채널 제한: {len(low)}곳)" if low else ""))
    out["제한 유통 사례 수"] = int(len(limited))
    return out


def estimate_trial(top2_pct: float, conv: dict) -> dict | None:
    key = "제한 유통 환산계수" if conv.get("적용", "").startswith("제한") and conv.get("제한 유통 환산계수") else "정상 유통 환산계수"
    f = conv.get(key)
    if not f:
        return None
    return {"구매의향 TOP2(%)": round(float(top2_pct), 1), "사용 계수": key, "예상 12개월 구매경험률(%)":
            [round(float(top2_pct * f[0]), 1), round(float(top2_pct * f[1]), 1)],
            "주의": ("제한 유통 과거 사례가 1건뿐이라 참고용" if key.startswith("제한") and conv.get("제한 유통 사례 수", 2) < 2
                   else "과거 컨셉테스트 5건 기준 범위")}


BASE_CHANNELS = ["편의점", "대형마트", "SSM", "온라인", "자판기·기타", "백화점", "카페", "온라인(새벽배송)", "드럭스토어", "창고형 할인점"]


def channel_options() -> list[str]:
    """선택지: 등록 자료(POS 판매채널·유통 인프라)에 있는 채널 + 기본 목록."""
    seen = []
    for df, col in ((_view("pos"), "판매채널"), (_view("infra"), "채널")):
        if not df.empty and col in df:
            seen += [str(c) for c in df[col].dropna().unique()]
    return list(dict.fromkeys(seen + BASE_CHANNELS))


def suggest_channels(name: str, description: str = "", storage: str = "", k: int = 3) -> dict:
    """비슷한 카테고리 제품이 실제로 많이 팔린 채널(POS 행사 없는 판매 기준)을 추천. 보관 조건으로 못 파는 채널은 뺀다."""
    p = _pos_ea()
    rows = competitors(name, description, k=6)
    codes = {r["id"].replace("P_", "") for r in rows}
    out, why = [], ""
    if not p.empty and codes:
        d = p[p["valid"] & p["제품코드"].astype(str).isin(codes)]
        share = d.groupby("판매채널")["ea"].sum().sort_values(ascending=False)
        share = share / share.sum()
        out = [str(c) for c in share.index[:k]]
        why = "비슷한 제품 판매 비중: " + ", ".join(f"{c} {v:.0%}" for c, v in share.head(k).items())
    infra = _view("infra")
    if storage and not infra.empty:
        col = "냉동 음료 진열 가능 점포율" if "냉동" in storage else "냉장 쇼케이스 보유율" if "냉장" in storage else None
        if col and col in infra:
            ok = {str(r["채널"]) for _, r in infra.iterrows() if pd.notna(r[col]) and r[col] >= 0.3}
            blocked = [c for c in out if not any(c in o or o in c for o in ok)]
            out = [c for c in out if c not in blocked] or [str(r["채널"]) for _, r in infra.sort_values(col, ascending=False).head(2).iterrows()]
            if blocked:
                why += f" · {storage} 진열이 어려운 채널 제외: {', '.join(blocked)}"
    if not out:
        out, why = ["편의점", "대형마트"], "등록 자료에 비슷한 제품이 없어 기본값"
    return {"channels": out, "why": why}


# ---------------- 매출·절감 (화면 계산 · API 없음, 저장된 결과로 다시 계산) ----------------
# 과제 설명 자료(롯데칠성음료) 6~7장의 조사 비용·기간. 바뀌면 .env 로 덮어쓴다.
SURVEY_COST = [  # (이름, 인원·기간, 비용 만원)
    ("정성조사(FGI)", "15명 · 6주", 1200),
    ("정량조사", "300명 · 2~3주", 150),
    ("정성 + 정량", "15명 + 300명", 2000),
]


def survey_costs() -> list[tuple]:
    import os
    full = os.getenv("VM_SURVEY_COST_MANWON")
    rows = list(SURVEY_COST)
    if full:
        rows[-1] = (rows[-1][0], rows[-1][1], int(float(full)))
    return rows


def _ci95(p: float, n: int) -> tuple[float, float]:
    """선택 비율 p(0~1), 인원 n의 95% 범위(정규 근사)."""
    import math
    if not n:
        return p, p
    half = 1.96 * math.sqrt(max(p * (1 - p), 1e-9) / n)
    return max(p - half, 0.0), p + half


def revenue_estimate(visual: dict, cfg: dict | None = None) -> dict | None:
    """진열대 선택 비율 × 같은 진열대 비교 제품의 실제 월 판매량(POS) → 신제품 예상 월 판매량·매출과 자사 잠식.

    가정: 같은 진열대에 놓이면 '선택 비율 1%p'가 같은 판매량을 뜻한다(비교 제품들의 POS 월평균으로 환산).
    신제품 구매자는 기존 선택(비교 제품·미구매)에서 지금 비율대로 옮겨 온다고 보고 자사 잠식을 나눈다.
    보관 조건 때문에 취급 점포가 제한되면 그 비율만큼 줄인다.
    """
    cfg = cfg or {}
    choices = visual.get("choices") or []
    kpi = visual.get("kpi") or {}
    concept = kpi.get("concept")
    if not choices or not concept:
        return None
    share = {c["제품"]: float(c["선택 비율(%)"]) / 100 for c in choices}
    p_new = share.get(concept)
    if p_new is None:
        return None
    p = _pos_ea()
    if p.empty:
        return None
    rows, matched = [], []
    for name, s in share.items():
        if name in (concept, "미구매"):
            continue
        d = p[(p["제품명"].astype(str) == name) & p["valid"]]
        if d.empty:
            rows.append({"제품": name, "선택(%)": round(s * 100, 1), "월평균 판매(EA)": None, "자사": None})
            continue
        monthly = d.groupby("기준월")["ea"].sum()
        own = not str(d["제품코드"].iloc[0]).upper().startswith("X")
        rows.append({"제품": name, "선택(%)": round(s * 100, 1), "월평균 판매(EA)": int(monthly.mean()), "자사": own,
                     "기간": f"{monthly.index.min()} ~ {monthly.index.max()}", "판매 개월": int(monthly.size)})
        matched.append((s, monthly.mean(), own))
    if not matched or sum(s for s, _, _ in matched) <= 0:
        return {"rows": rows, "error": "진열대 비교 제품을 POS에서 찾지 못해 판매량으로 환산할 수 없습니다."}
    per_point = sum(m for _, m, _ in matched) / sum(s for s, _, _ in matched)  # 선택 비율 1(=100%)당 월 판매량
    n = int(kpi.get("n_ok") or 0)
    lo, hi = _ci95(p_new, n)
    conv = conversion(cfg.get("storage", ""), cfg.get("channel", "")) if cfg.get("storage") else {}
    cover = conv.get("취급 가능 점포 비율") or {}
    coverage = sum(cover.values()) / len(cover) if cover else 1.0
    price = int(kpi.get("price") or cfg.get("price") or 0)
    cost_price = int(cfg.get("cost_price") or 0)
    units = [x * per_point * coverage for x in (lo, p_new, hi)]
    others = {k: v for k, v in share.items() if k != concept}
    base_total = sum(others.values()) or 1
    own_names = {r["제품"] for r in rows if r.get("자사")}
    own_frac = sum(v for k, v in others.items() if k in own_names) / base_total
    rival_frac = sum(v for k, v in others.items() if k not in own_names and k != "미구매") / base_total
    new_frac = others.get("미구매", 0) / base_total
    return {
        "rows": rows, "per_point": per_point, "coverage": round(coverage, 2), "cover_detail": cover,
        "n": n, "share": [round(x * 100, 1) for x in (lo, p_new, hi)],
        "units": [int(u) for u in units],
        "sales": [int(u * price) for u in units],  # 소비자가 기준 판매액(원/월)
        "revenue": [int(u * cost_price) for u in units] if cost_price else None,  # 출고가 기준 자사 매출(원/월)
        "price": price, "cost_price": cost_price,
        "cannibal": {"자사 제품에서 이동": round(own_frac * 100), "경쟁 제품에서 이동": round(rival_frac * 100),
                     "새 수요(미구매에서)": round(new_frac * 100)},
        "own_products": sorted(own_names),
    }


def savings(kpi: dict, cfg: dict | None = None) -> dict:
    """이번 가상 검토(처음 실행 기준 추정 비용·시간) vs 과제 설명 자료의 실제 조사 비용·기간."""
    import os
    cfg = cfg or {}
    unit = float(os.getenv("VM_COST_PER_CALL", "0.02"))
    krw = float(os.getenv("VM_KRW_PER_USD", "1400"))
    n = int(kpi.get("n_ok") or cfg.get("n") or 0)
    calls = n * (1 + bool(kpi.get("top2") is not None) + bool(cfg.get("price_b"))) + (16 if cfg.get("fgi") else 0) + 1
    usd = calls * unit
    return {"n": n, "calls": calls, "usd": round(usd, 1), "krw": int(usd * krw), "krw_rate": krw,
            "seconds": kpi.get("seconds"), "surveys": survey_costs()}


def fmt_won(v: float) -> str:
    """원 → '1.2억 원' / '3,400만 원' / '8,400원'."""
    v = float(v)
    if abs(v) >= 1e8:
        return f"{v / 1e8:.1f}억 원"
    if abs(v) >= 1e4:
        return f"{v / 1e4:,.0f}만 원"
    return f"{v:,.0f}원"
