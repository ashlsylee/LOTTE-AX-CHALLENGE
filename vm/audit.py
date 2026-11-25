"""데이터 진단: 자료를 고치거나 버리지 않고, 결론을 틀리게 만들 수 있는 점을 찾아 경고로 남긴다.

- 모든 검사는 시트 이름이 아니라 역할(store.table(role))과 표준 열로 동작한다 → 다른 자료에도 그대로 적용.
- 수치는 '원자료 그대로'와 '경고 반영(품질 의심 응답 제외·모집단 가중)'을 나란히 계산해 보여 준다.
  어느 쪽을 쓸지는 사람이 판단하고, 리포트에는 둘 다 남긴다.
- 기준값(빠른 응답 등)은 아래 THRESHOLDS에 모아 두었다(결과를 보기 전에 정한 값).
"""
from __future__ import annotations

import re

import pandas as pd

from . import store

THRESHOLDS = {
    "speed_ratio": 1 / 3,        # 응답시간이 중앙값의 1/3 미만이면 '빠른 응답'
    "order_effect": 0.10,        # 같은 컨셉의 1번째 제시와 마지막 제시 TOP2 차이가 10%p 이상이면 순서 효과
    "skew": 1.5,                 # 표본 비중 / 모집단 비중이 1.5배 이상(또는 1/1.5 이하)이면 치우침
    "ad_spike": 2.0,             # 광고·협찬 비중이 키워드 중앙값의 2배 이상인 달
    "trend_spike": 1.8,          # 검색 지수가 전년 같은 달의 1.8배 이상
    "sellin_ratio": 1.5,         # 출고/판매 1.5배 이상이면 밀어내기 의심
    "freetext_unique": 0.2,      # 자유응답 고유 문장 비율이 20% 미만이면 반복 문장
}
SEV = {"높음": 0, "중간": 1, "참고": 2}


def W(area, level, text, evidence="", handling=""):
    return {"영역": area, "심각도": level, "내용": text, "근거": evidence, "분석 반영": handling}


def num(s):
    return pd.to_numeric(s, errors="coerce")


# ---------------- 설문 ----------------
def survey_flags(resp: pd.DataFrame, evals: pd.DataFrame) -> pd.DataFrame:
    """응답자별 품질 표시(제외하지 않고 표시만)."""
    f = pd.DataFrame({"응답자ID": resp["응답자ID"]})
    if "응답시간(초)" in resp:
        t = num(resp["응답시간(초)"])
        f["빠른 응답"] = (t < t.median() * THRESHOLDS["speed_ratio"]).values
    if not evals.empty:
        items = [c for c in ["컨셉이해도", "호감도", "차별성", "구매의향", "가격수용도"] if c in evals]
        same = evals.groupby("응답자ID")[items].apply(lambda d: d.apply(num).nunique().max() == 1)
        f["같은 점수 반복"] = f["응답자ID"].map(same).fillna(False).astype(bool)
    if "휴대폰해시" in resp:
        f["중복 응답자(나중 응답)"] = resp["휴대폰해시"].duplicated(keep="first").values & resp["휴대폰해시"].notna().values
    if {"출생연도", "연령대"} <= set(resp.columns):
        year = num(resp.get("응답일시", pd.Series(dtype=str)).astype(str).str[:4]).fillna(pd.Timestamp.now().year)
        age = year.values - num(resp["출생연도"]).values
        lo = num(resp["연령대"].astype(str).str.extract(r"(\d+)")[0]).values
        hi = num(resp["연령대"].astype(str).str.extract(r"~\s*(\d+)")[0]).fillna(pd.Series(lo) + 9).values
        f["나이-연령대 불일치"] = ~((age >= lo - 1) & (age <= hi + 1))
    f["품질 의심"] = f.drop(columns="응답자ID").any(axis=1)
    return f


def weights(resp: pd.DataFrame, pop: pd.DataFrame) -> pd.Series | None:
    """연령×성별 모집단 구성비로 사후 가중. 셀 이름은 '연령대 성별' 글자로 맞춘다."""
    if pop.empty or not {"연령대", "성별"} <= set(resp.columns):
        return None
    targets = {}
    for _, r in pop.iterrows():
        label = str(r.get("항목", ""))
        m = re.match(r"(\d+)\D+(\d+)?\D*(여|남)", label.replace(" ", ""))
        if m:
            targets[(m.group(1), m.group(3))] = float(r["모집단 비중(추정)"])
    if not targets:
        return None
    key = list(zip(resp["연령대"].astype(str).str.extract(r"(\d+)")[0], resp["성별"].astype(str).str[0]))
    share = pd.Series(key).value_counts(normalize=True)
    w = pd.Series([targets.get(k, 0) / share[k] if k in share and targets.get(k) else 1.0 for k in key], index=resp.index)
    return w * len(w) / w.sum()


def survey_metrics(resp=None, evals=None, pop=None) -> pd.DataFrame:
    """컨셉별 TOP2(4~5점) 비율: 원자료 / 품질 의심 제외 / 제외+모집단 가중. 항목별로."""
    resp = store.table("respondents") if resp is None else resp
    evals = store.table("concept_eval") if evals is None else evals
    pop = store.table("population") if pop is None else pop
    if evals.empty:
        return pd.DataFrame()
    flags = survey_flags(resp, evals) if not resp.empty else pd.DataFrame({"응답자ID": evals["응답자ID"].unique(), "품질 의심": False})
    w = weights(resp, pop) if not resp.empty else None
    wmap = dict(zip(resp["응답자ID"], w)) if w is not None else {}
    bad = set(flags.loc[flags["품질 의심"], "응답자ID"])
    rows = []
    items = [c for c in ["구매의향", "호감도", "컨셉이해도", "차별성", "가격수용도"] if c in evals]
    for concept, d in evals.groupby("컨셉"):
        for item in items:
            top = num(d[item]) >= 4
            clean = ~d["응답자ID"].isin(bad)
            ww = d["응답자ID"].map(wmap).fillna(1.0)
            rows.append({"컨셉": concept, "항목": item, "원자료 TOP2(%)": round(top.mean() * 100, 1),
                         "품질 의심 제외(%)": round(top[clean].mean() * 100, 1),
                         "제외+모집단 가중(%)": round((top[clean] * ww[clean]).sum() / ww[clean].sum() * 100, 1) if wmap else None,
                         "평균 점수": round(num(d[item]).mean(), 2), "응답 수": int(len(d)), "제외 후": int(clean.sum())})
        if "최대지불의향가격" in d:
            wtp = num(d["최대지불의향가격"])
            rows.append({"컨셉": concept, "항목": "최대지불의향가격(중앙값)", "원자료 TOP2(%)": None,
                         "평균 점수": wtp.median(), "응답 수": int(wtp.notna().sum()), "제외 후": int(wtp[~d["응답자ID"].isin(bad)].notna().sum())})
    return pd.DataFrame(rows)


def check_survey(resp, evals, quest, pop):
    out = []
    if resp.empty and evals.empty:
        return out
    flags = survey_flags(resp, evals) if not resp.empty else pd.DataFrame()
    n = len(resp)
    if not flags.empty:
        for col, why in [("빠른 응답", f"응답시간이 중앙값의 {THRESHOLDS['speed_ratio']:.0%} 미만"), ("같은 점수 반복", "모든 문항·컨셉에 같은 점수"),
                         ("중복 응답자(나중 응답)", "휴대폰해시가 같은 응답자"), ("나이-연령대 불일치", "출생연도로 계산한 나이와 연령대가 다름")]:
            if col in flags and flags[col].sum():
                ids = ", ".join(flags.loc[flags[col], "응답자ID"].astype(str).head(6))
                out.append(W("설문 응답 품질", "높음" if col in ("빠른 응답", "같은 점수 반복") else "중간",
                             f"{col} {int(flags[col].sum())}명 ({flags[col].mean():.0%})", f"{why} · 예: {ids}",
                             "원자료와 '품질 의심 제외' 수치를 나란히 표시"))
        both = flags.get("빠른 응답", pd.Series(False)) & flags.get("같은 점수 반복", pd.Series(False))
        if both.sum():
            out.append(W("설문 응답 품질", "높음", f"빠른 응답과 같은 점수 반복이 겹치는 응답자 {int(both.sum())}명", "성의 없는 응답일 가능성이 큼"))
    if not pop.empty and not resp.empty:
        for col, keyword in [("연령대", "연령"), ("거주권역", "권역"), ("성별", "연령")]:
            if col not in resp:
                continue
            sample = resp[col].astype(str).value_counts(normalize=True)
            for _, r in pop.iterrows():
                if keyword not in str(r.get("구분", "")):
                    continue
                label = str(r["항목"])
                target = float(r["모집단 비중(추정)"])
                if col == "연령대":
                    m = re.match(r"(\d+)", label)
                    keys = [k for k in sample.index if m and k.startswith(m.group(1))]
                    s = sample[keys].sum() if m else 0
                    label = keys[0] if keys else label
                    target = pop[pop["항목"].astype(str).str.startswith(m.group(1))]["모집단 비중(추정)"].sum() if m else target
                elif col == "성별":
                    continue
                else:
                    s = sample.get(label, 0)
                ratio = s / target if target else 0
                if ratio >= THRESHOLDS["skew"] or (0 < ratio <= 1 / THRESHOLDS["skew"]):
                    out.append(W("설문 표본 구성", "높음" if ratio >= 2 or ratio <= 0.5 else "중간",
                                 f"{col} '{label}' 표본 {s:.0%} vs 모집단 {target:.0%} ({ratio:.1f}배)",
                                 "4_모집단구성비 대비", "'제외+모집단 가중' 수치로 보정해 함께 표시"))
        out = list({(x["내용"]): x for x in out}.values())
        if "성별" in resp:
            fem = resp["성별"].astype(str).str.startswith("여").mean()
            if abs(fem - 0.5) > 0.1:
                out.append(W("설문 표본 구성", "중간", f"여성 비중 {fem:.0%} (모집단 약 50%)", "", "모집단 가중으로 보정"))
    if not evals.empty:
        if "제시순서" in evals:
            for concept, d in evals.groupby("컨셉"):
                by = d.groupby(num(d["제시순서"]))["구매의향"].apply(lambda s: (num(s) >= 4).mean())
                if len(by) >= 2 and by.iloc[0] - by.iloc[-1] >= THRESHOLDS["order_effect"]:
                    out.append(W("설문 설계", "중간", f"'{concept}' 먼저 볼수록 구매의향이 높음 (첫 번째 {by.iloc[0]:.0%} → 마지막 {by.iloc[-1]:.0%})",
                                 "제시 순서별 TOP2", "순서가 고르게 섞였는지 확인. 컨셉 비교는 순서별로도 확인"))
        if "가격제시방식" in evals:
            ways = evals.groupby("컨셉")["가격제시방식"].agg(lambda s: s.mode().iat[0] if len(s.mode()) else "")
            odd = [f"{c}: {w}" for c, w in ways.items() if any(k in str(w) for k in ("→", "기념", "할인", "정가 "))
                   and str(w) != "정가 표기"]
            if odd and ways.nunique() > 1:
                out.append(W("설문 설계", "높음", "컨셉마다 가격 표시 방식이 다름(앵커 가격)", " / ".join(odd),
                             "해당 컨셉의 구매의향·가격수용도는 높게 나왔을 수 있음. 가상 설문은 모든 제품을 같은 방식으로 표시"))
        if "자유응답" in evals:
            for concept, d in evals.groupby("컨셉"):
                txt = d["자유응답"].dropna().astype(str)
                if len(txt) >= 20 and txt.nunique() / len(txt) < THRESHOLDS["freetext_unique"]:
                    pos = (num(d["구매의향"]) >= 4).mean()
                    out.append(W("설문 자유응답", "중간", f"'{concept}' 자유응답이 같은 문장 {txt.nunique()}개의 반복 ({len(txt)}건)",
                                 f"구매의향 TOP2 {pos:.0%}와 자유응답 분위기를 함께 확인", "자유응답은 이유 표본으로만 쓰고 수치 판단에 쓰지 않음"))
        if "최대지불의향가격" in evals:
            miss = num(evals["최대지불의향가격"]).isna().mean()
            if miss > 0.3:
                out.append(W("설문 응답 품질", "참고", f"최대지불의향가격 미응답 {miss:.0%}", "선택 문항", "응답자만으로 중앙값 계산"))
    if not quest.empty and "문항 내용" in quest:
        q = quest["문항 내용"].astype(str)
        lead = q[q.str.contains("정성|건강한|프리미엄|좋은|맛있는") & q.str.contains("\\[")]
        for text in lead:
            out.append(W("설문 설계", "높음", "특정 컨셉에만 긍정 수식어가 붙은 구매의향 문항(유도 질문)", text[:90],
                         "해당 컨셉의 구매의향은 다른 컨셉과 직접 비교하지 않음. 가상 설문은 같은 문장으로 질문"))
    return out


# ---------------- 문서(정성조사 등) ----------------
def check_documents(docs, fgi):
    out = []
    for d in docs:
        t = d["text"]
        if re.search(r"검수 전|초안|draft", t, re.I):
            out.append(W("문서 신뢰도", "중간", f"'{d['name']}'은 검수 전 초안으로 표시됨", "", "주장은 원자료 표와 맞춰 본 뒤에만 인용"))
        if re.search(r"우선 모집|주 ?\d회 이상", t):
            m = re.search(r"[^.\n]*(우선 모집|주 ?\d회 이상)[^.\n]*", t)
            out.append(W("정성조사 표본", "높음", "참석자 모집 조건이 특정 구매자에 치우침", m.group(0).strip()[:120],
                         "정성조사 결론을 전체 소비자로 일반화하지 않음"))
        if not fgi.empty:
            concepts = [c for c in fgi.columns if c not in ("ID", "연령대", "성별", "직업") and not c.startswith("_") and "구매" not in c
                        and pd.to_numeric(fgi[c], errors="coerce").between(1, 5).all()]
            for c in concepts:
                hi = int((num(fgi[c]) >= 4).sum())
                for m in re.finditer(rf"(\d+)\s*명\s*/\s*(\d+)\s*명[^.\n]*{re.escape(c)}|{re.escape(c)}[^.\n]*?(\d+)\s*명\s*/\s*(\d+)\s*명", t):
                    claim, total = [int(x) for x in m.groups() if x][:2]
                    if total == len(fgi) and abs(claim - hi) >= 2:
                        out.append(W("문서-자료 불일치", "높음", f"'{c}' 호의적 {claim}/{total}명이라는 요약과 달리 점수표의 4점 이상은 {hi}명",
                                     m.group(0)[:100], "요약문 대신 점수표 수치를 사용"))
    rtd = [c for c in fgi.columns if ("구매" in c or "(회)" in c) and not str(c).startswith("_")]  # 구매 횟수 열(컨셉 점수 열 제외)
    if not fgi.empty and rtd:
        heavy = (num(fgi[rtd[0]]) >= 3).mean()
        out.append(W("정성조사 표본", "참고", f"FGI 참석자 중 {rtd[0]} 3회 이상 {heavy:.0%}", "", "커피 컨셉 반응이 높게 나올 수 있음"))
    return out


# ---------------- 판매·자산 ----------------
def check_sales(pos, sellin, assets, infra, hist):
    out = []
    if not pos.empty:
        dup = pos.drop(columns=[c for c in pos if c.startswith("_")]).duplicated()
        if "_dataset" in pos and pos["_dataset"].nunique() > 1:  # 서로 다른 묶음 사이에서만 겹치는 행
            body = [c for c in pos if not c.startswith("_")]
            cross = pos.groupby(body, dropna=False)["_dataset"].transform("nunique") > 1
            if cross.sum():
                out.append(W("묶음 합치기", "높음", f"여러 묶음을 함께 쓰는 중 — 묶음 사이에 같은 POS 행 {int(cross.sum())}개",
                             ", ".join(sorted(pos.loc[cross, "_dataset"].unique())), "같은 자료가 두 묶음에 들어 있으면 한쪽 묶음 선택을 빼세요"))
        if dup.sum():
            out.append(W("POS", "중간", f"완전히 같은 행 {int(dup.sum())}개", "", "정상 판매 집계에서 한 번만 셈(원자료 합계도 함께 표시)"))
        q = num(pos["판매수량"])
        if (q <= 0).sum():
            out.append(W("POS", "중간", f"판매수량 0 이하(반품·취소 추정) {int((q <= 0).sum())}행", "", "정상 판매 집계에서 따로 표시"))
        test = pos["제품코드"].astype(str).str.contains("TEST|테스트", case=False) | pos.get("제품명", pd.Series("", index=pos.index)).astype(str).str.contains("테스트|삭제")
        if test.sum():
            out.append(W("POS", "중간", f"테스트·삭제 예정 상품 {int(test.sum())}행", ", ".join(pos.loc[test, "제품코드"].astype(str).unique()[:3]), "분석에서 제외 표시"))
        if "수량단위" in pos and pos["수량단위"].nunique() > 1:
            out.append(W("POS", "높음", "수량 단위가 섞여 있음: " + ", ".join(pos["수량단위"].astype(str).unique()),
                         "BOX 단위 행은 낱개로 환산해야 함", "BOX(n)은 n개로 환산"))
        if "행사구분" in pos:
            promo = pos["행사구분"].astype(str).ne("없음") & pos["행사구분"].notna()
            ea = q * pos.get("수량단위", pd.Series("EA", index=pos.index)).map(unit_size)
            share = ea[promo].sum() / ea.sum()
            lift = (ea[pos["행사구분"].astype(str).str.contains(r"\+")].mean() / ea[~promo].mean()) if (~promo).sum() else None
            out.append(W("POS", "높음" if share > 0.4 else "중간" if share > 0.3 else "참고", f"행사 기간 판매가 전체 수량의 {share:.0%}",
                         f"1+1·2+1 행 평균은 행사 없는 행의 {lift:.1f}배" if lift else "", "기본 수요는 행사 없는 달로 따로 계산"))
        if assets is not None and not assets.empty and assets["SKU코드"].notna().any():
            unknown = set(pos["제품코드"].astype(str)) - set(assets["SKU코드"].astype(str))
            comp = {c for c in unknown if re.match(r"X|PB|경쟁", c) or "경쟁" in str(pos.loc[pos["제품코드"] == c, "제품명"].iloc[0])}
            if unknown - comp - {c for c in unknown if "TEST" in c.upper()}:
                out.append(W("POS", "참고", "제품자산에 없는 코드: " + ", ".join(sorted(unknown - comp)[:6]), "", "경쟁·기타 제품으로 취급"))
    if not sellin.empty and not pos.empty:
        p = pos.assign(ea=num(pos["판매수량"]) * pos.get("수량단위", pd.Series("EA", index=pos.index)).map(unit_size))
        keys = [k for k in ["기준월", "판매채널", "제품코드"] if k in p and k in sellin]
        j = p.groupby(keys)["ea"].sum().to_frame().join(sellin.groupby(keys)["출고수량"].apply(lambda s: num(s).sum()), how="inner")
        j = j[j["ea"] > 0]
        r = j["출고수량"] / j["ea"]
        hi = r[r >= THRESHOLDS["sellin_ratio"]]
        if len(hi):
            ex = "; ".join(f"{'/'.join(map(str, k))} {v:.2f}배" for k, v in hi.sort_values(ascending=False).head(3).items())
            out.append(W("출고 vs 판매", "높음", f"출고가 판매의 {THRESHOLDS['sellin_ratio']}배 이상인 경우 {len(hi)}건(유통 재고 밀어내기·반품 위험)", ex,
                         "성과 판단은 출고가 아니라 POS 기준"))
    if assets is not None and not assets.empty:
        if "SKU코드" in assets:
            raw = assets["SKU코드"]
            d = raw.astype(str)
            dup = d[raw.notna() & d.duplicated(keep=False)]
            if len(dup):
                out.append(W("제품자산", "중간", "같은 코드가 여러 제품에 쓰임: " + ", ".join(sorted(set(dup))),
                             " / ".join(assets.loc[dup.index, "제품명"].astype(str)), "제품명으로 구분해 표시"))
        if {"출시일", "폐지(중단)일"} <= set(assets.columns):
            a, b = pd.to_datetime(assets["출시일"], errors="coerce"), pd.to_datetime(assets["폐지(중단)일"], errors="coerce")
            bad = assets[(a > b)]
            if len(bad):
                out.append(W("제품자산", "중간", "출시일이 중단일보다 늦음: " + ", ".join(bad["제품명"].astype(str)), "", "날짜는 확인 필요로 표시"))
        if "단종·중단사유" in assets:
            stopped = assets["상태"].astype(str).str.contains("단종|중단")
            miss = assets[stopped & assets["단종·중단사유"].isna()]
            if len(miss):
                out.append(W("제품자산", "높음", f"단종·중단 사유가 비어 있음 {len(miss)}건: " + ", ".join(miss["제품명"].astype(str)),
                             "", "유사 사례 판단에서 '사유 미상'으로 표시, 담당자 확인 질문 생성"))
    if infra is not None and not infra.empty:
        miss = infra[infra.drop(columns=[c for c in infra if c.startswith("_") or c == "비고"]).isna().any(axis=1)]
        if len(miss):
            out.append(W("유통 인프라", "참고", "빈 값이 있는 채널: " + ", ".join(miss["채널"].astype(str)), "", "해당 값은 계산에서 제외"))
        note = infra.get("비고", pd.Series(dtype=str)).astype(str)
        for _, r in infra[note.str.contains("불가|혼합")].iterrows():
            out.append(W("유통 인프라", "중간", f"{r['채널']}: {r['비고']}", "", "냉동·냉장 제품의 취급 가능 점포 계산에 반영"))
    if hist is not None and not hist.empty:
        out.append(W("보정 기준", "참고", f"과거 컨셉테스트 {len(hist)}건: 설문 TOP2 → 출시 12개월 실제 구매경험률 환산계수 "
                                         f"{num(hist['환산계수(실제/의향)']).min():.2f}~{num(hist['환산계수(실제/의향)']).max():.2f}",
                     "취급점포율이 낮은 제품일수록 계수가 낮음", "가상·설문 구매의향을 실제 구매경험률 범위로 환산할 때 사용"))
    return out


def unit_size(u) -> int:
    m = re.search(r"\((\d+)\)", str(u))
    return int(m.group(1)) if m else 1


# ---------------- 트렌드·로그 ----------------
def check_trends(trend, sns, related, volume, log):
    out = []
    if not trend.empty:
        kw = [c for c in trend.columns if c != "기준월" and not c.startswith("_")]
        vals = trend[kw].apply(num)
        bad = ((vals < 0) | (vals > 100)).sum()
        if bad.sum():
            out.append(W("검색 트렌드", "중간", "0~100 범위를 벗어난 지수: " + ", ".join(f"{k} {v}개" for k, v in bad.items() if v), "", "해당 값은 계산에서 제외"))
        out.append(W("검색 트렌드", "참고", "검색 지수는 키워드마다 따로 0~100으로 환산한 값이라 키워드끼리 크기를 비교할 수 없음",
                     f"실제 검색량 환산 자료: {', '.join(volume['키워드'].astype(str)) if not volume.empty else '없음'}", "같은 키워드의 시점 비교만 사용"))
    if not sns.empty and "광고·협찬 비중" in sns:
        s = sns.assign(ad=num(sns["광고·협찬 비중"]), n=num(sns["SNS언급량(건)"]))
        if (s["n"] < 0).sum():
            out.append(W("SNS", "중간", f"언급량이 음수인 달 {int((s['n'] < 0).sum())}개", "", "계산에서 제외"))
        for k, d in s.groupby("키워드"):
            med = d["ad"].median()
            spikes = d[d["ad"] >= max(med * THRESHOLDS["ad_spike"], 0.4)]
            if len(spikes):
                out.append(W("트렌드 해석", "높음", f"'{k}' 언급 급증 시기의 광고·협찬 비중 {spikes['ad'].max():.0%} (평소 {med:.0%})",
                             ", ".join(spikes["기준월"].astype(str)), "광고로 만든 관심일 수 있어 자연 수요 신호로 쓰지 않음"))
    if not related.empty:
        for k, d in related.groupby("키워드"):
            recipe = d[d["연관검색어"].astype(str).str.contains("만드는|레시피|맛집|효능|기계|착즙기")]
            share = num(recipe["비중(최근 12개월)"]).sum()
            if share >= 0.4:
                out.append(W("트렌드 해석", "중간", f"'{k}' 연관검색어의 {share:.0%}가 음료 구매가 아닌 관심(레시피·기계 등)",
                             ", ".join(recipe["연관검색어"].astype(str)), "검색 관심을 구매 수요로 바로 해석하지 않음"))
    if not log.empty:
        g = log.assign(d=num(log.get("체류시간(초)")))
        if "쿠키ID" in g:
            per = g.groupby("쿠키ID").agg(n=("이벤트", "size"), ev=("이벤트", "nunique"), dwell=("d", "median"))
            bots = per[(per["ev"] == 1) & (per["dwell"] == 0) & (per["n"] >= 5)]
            if len(bots):
                out.append(W("온라인 로그", "높음", f"봇 의심 쿠키 {len(bots)}개(한 가지 이벤트만 반복·체류 0초) · 이벤트 {int(bots['n'].sum())}건",
                             ", ".join(bots.index[:5]), "퍼널 계산에서 따로 표시"))
        ev = g["이벤트"].value_counts()
        if ev.get("클릭", 0) > ev.get("노출", 0):
            out.append(W("온라인 로그", "중간", f"클릭 {ev.get('클릭', 0)}건이 노출 {ev.get('노출', 0)}건보다 많음", "봇·중복 기록 가능성"))
        if "시간대" in g and g["시간대"].nunique() > 1:
            out.append(W("온라인 로그", "중간", "시간대가 섞여 있음: " + ", ".join(g["시간대"].astype(str).value_counts().index), "", "시간대별 분석 전 통일 필요"))
        if {"세션ID", "IP그룹"} <= set(g.columns):
            share = (g.groupby("세션ID")["IP그룹"].nunique() > 1).mean()
            if share > 0.2:
                out.append(W("온라인 로그", "참고", f"세션 중 IP가 바뀌는 비율 {share:.0%}", "", "세션 단위 해석 주의"))
    return out


_CACHE = {}


def run_all() -> list[dict]:
    key = store.version()
    if key in _CACHE:
        return _CACHE[key]
    _CACHE.clear()
    _CACHE[key] = ws = _run_all()
    return ws


def _run_all() -> list[dict]:
    t = store.table
    ws = []
    ws += check_survey(t("respondents"), t("concept_eval"), t("questionnaire"), t("population"))
    ws += check_documents(store.documents(), t("fgi_scores"))
    ws += check_sales(t("pos"), t("sellin"), t("assets"), t("infra"), t("concept_history"))
    ws += check_trends(t("search_trend"), t("sns"), t("related_search"), t("search_volume_ref"), t("online_log"))
    return sorted(ws, key=lambda x: SEV[x["심각도"]])


def as_markdown(ws: list[dict], limit: int = 30) -> str:
    if not ws:
        return "데이터 경고 없음."
    icon = {"높음": "🔴", "중간": "🟠", "참고": "⚪"}
    lines = [f"- {icon[w['심각도']]} **[{w['영역']}]** {w['내용']}" + (f" — {w['근거']}" if w["근거"] else "")
             + (f" → {w['분석 반영']}" if w["분석 반영"] else "") for w in ws[:limit]]
    return "\n".join(lines)



# ---------------- 위험 행(오염도)과 '위험 데이터 제외' 보기 ----------------
_MASKS = {}


def risk_masks() -> dict:
    key = store.version()
    if key not in _MASKS:
        _MASKS.clear()
        _MASKS[key] = _risk_masks()
    return _MASKS[key]


def _risk_masks() -> dict:
    """역할별로 위험 행 표시(True=위험). 원본은 그대로 두고 표시만."""
    t = store.table
    out = {}
    resp, evals = t("respondents"), t("concept_eval")
    if not resp.empty:
        f = survey_flags(resp, evals)
        why = f.drop(columns=["응답자ID", "품질 의심"]).apply(lambda r: ", ".join(c for c, v in r.items() if v), axis=1)
        out["respondents"] = (f["품질 의심"].values, why.values)
        if not evals.empty:
            bad = dict(zip(f["응답자ID"], why))
            m = evals["응답자ID"].map(lambda x: bool(bad.get(x)))
            out["concept_eval"] = (m.values, evals["응답자ID"].map(lambda x: bad.get(x, "")).values)
    pos = t("pos")
    if not pos.empty:
        dup = pos.drop(columns=[c for c in pos if c.startswith("_")]).duplicated().values
        neg = (num(pos["판매수량"]) <= 0).values
        test = pos["제품코드"].astype(str).str.contains("TEST|테스트", case=False).values
        why = [", ".join(n for n, v in (("중복 행", a), ("수량 0 이하", b), ("테스트 상품", c)) if v) for a, b, c in zip(dup, neg, test)]
        out["pos"] = (dup | neg | test, why)
    log = t("online_log")
    if not log.empty and log["쿠키ID"].notna().any():
        g = log.assign(d=num(log["체류시간(초)"]))
        per = g.groupby("쿠키ID").agg(n=("이벤트", "size"), ev=("이벤트", "nunique"), dwell=("d", "median"))
        bots = set(per[(per["ev"] == 1) & (per["dwell"] == 0) & (per["n"] >= 5)].index)
        m = log["쿠키ID"].isin(bots).values
        out["online_log"] = (m, ["봇 의심" if x else "" for x in m])
    return out


def contamination() -> list[dict]:
    rows = []
    for role, (mask, why) in risk_masks().items():
        n, k = len(mask), int(mask.sum())
        reasons = pd.Series([w for w in why if w]).str.split(", ").explode().value_counts()
        rows.append({"자료": store.ROLES[role]["label"], "전체 행": n, "위험 행": k, "오염도(%)": round(k / n * 100, 1) if n else 0,
                     "등급": "높음" if k / max(n, 1) >= 0.1 else "중간" if k / max(n, 1) >= 0.03 else "낮음",
                     "주요 사유": ", ".join(f"{i} {v}" for i, v in reasons.items())})
    return rows


def risk_reasons() -> list[str]:
    """이 묶음에서 실제로 나온 위험 사유 목록(제외 선택지)."""
    out = set()
    for _, why in risk_masks().values():
        for w in why:
            out |= {x for x in str(w).split(", ") if x}
    return sorted(out)


def excluded_reasons() -> list[str]:
    return store.get_setting(f"exclude_reasons::{store.scope_key()}", [])


def exclude_risky() -> bool:
    return bool(excluded_reasons())


def view(role: str) -> pd.DataFrame:
    """분석용 표. 담당자가 고른 위험 사유에 해당하는 행만 빼고, 아니면 원자료 그대로."""
    df = store.table(role)
    chosen = set(excluded_reasons())
    if df.empty or not chosen:
        return df
    m = risk_masks().get(role)
    if m is None:
        return df
    drop = [bool(set(str(w).split(", ")) & chosen) for w in m[1]]
    return df[[not d for d in drop]].reset_index(drop=True)
