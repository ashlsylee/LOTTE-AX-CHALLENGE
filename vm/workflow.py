"""Shared workflow for staged and one-click concept evaluation."""
from copy import deepcopy
from uuid import uuid4

import pandas as pd

from .challenge import boards, retrieve, terms
from .datasets import current
from .config import OUT_DIR
from .fgi import run_fgi
from .simulate import run, shares_of

BOARDS = boards()  # 로컬 data/challenge/boards.json (저장소에 올리지 않음)
INTENT_GAP = 10.0  # 가상 '사 볼 의향'과 설문 구매의향 TOP2 차이 허용폭(%p). 결과를 보기 전에 정한 기준


def md_table(rows, cols=None):
    if not rows:
        return "(없음)"
    cols = cols or [c for c in rows[0] if not str(c).startswith("_")]
    fmt = lambda v: "-" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).replace("|", "/").replace("\n", " ")  # noqa: E731
    return "\n".join(["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)] + ["| " + " | ".join(fmt(r.get(c)) for c in cols) + " |" for r in rows])


def analyze(name, description, launch=None, storage="", channels=""):
    """과거 사례·트렌드 타이밍·재시도 판단·환산계수·데이터 경고를 한 번에(비용 없음)."""
    from . import audit, insight
    hist = insight.similar_history(name, description)
    timing = insight.trend_timing(name, description, launch)
    return {"history": hist, "timing": timing, "verdict": insight.retry_verdict(hist, timing),
            "conversion": insight.conversion(storage, channels), "warnings": audit.run_all()}


def evidence(name, description, data=None, channel=None, *, launch=None, storage="", analysis=None):
    """사람이 읽는 근거(마크다운). (텍스트, 유사 사례 수)"""
    from . import audit
    a = analysis or analyze(name, description, launch, storage, channel or "")
    v = a["verdict"]
    lines = [f"### 다시 해볼 가치 · {v['판단']}", "\n".join(f"- {x}" for x in v["이유"]),
             f"트렌드: {v.get('트렌드 단계', '-')}"]
    if v.get("확인할 것"):
        lines.append("확인할 것: " + " / ".join(v["확인할 것"]))
    lines.append("### 비슷한 과거 사례")
    lines.append(md_table([{**h, "판매 실적": (f"월평균 {h['판매 실적']['월평균(EA)']:,}EA · 행사 비중 {h['판매 실적']['행사 비중']:.0%}"
                                             if h.get("판매 실적") else "-"),
                           "과거 컨셉테스트": (f"TOP2 {h['과거 컨셉테스트']['구매의향 TOP2']:.0%} → 실제 {h['과거 컨셉테스트']['12개월 실제 구매경험률']:.0%}"
                                          if h.get("과거 컨셉테스트") else "-")} for h in a["history"]],
                          ["제품", "상태", "기간", "중단 사유", "사유 유형", "사유 가상 소비자 확인", "판매 실적", "과거 컨셉테스트"]))
    lines.append("### 트렌드·출시 타이밍")
    lines.append(md_table(a["timing"]) if a["timing"] else "관련 검색 키워드가 없어 판단을 보류합니다.")
    conv = a["conversion"]
    if conv:
        lines.append("### 유통 조건과 환산 기준")
        if conv.get("취급 가능 점포 비율"):
            lines.append("취급 가능 점포 비율: " + ", ".join(f"{k} {v:.0%}" for k, v in conv["취급 가능 점포 비율"].items()) + f" → {conv.get('적용', '')}")
        lines.append(f"과거 근거: {conv.get('근거', '-')}")
    data = current() if data is None else data
    query = terms(name + " " + description)
    seen = [r for r in data.get("journeys", []) if query & terms(str(r.get("선택제품") or ""))]
    if seen:
        lines.append("### 오프라인 구매여정 관찰")
        lines.append("\n".join(f"- {r['관찰ID']} · {r['점포(유형)']} / {r['방문목적']} / {r['선택제품']} / {r['구매결과']}" for r in seen))
    lines.append("### 데이터 경고")
    lines.append(audit.as_markdown([w for w in a["warnings"] if w["심각도"] != "참고"], limit=30))
    return "\n\n".join(lines), len(a["history"])


def panel_sample(pool, n, age_min, age_max, seed=42, data=None):
    """제공 조사 구성에 비례 배정하고 각 연령×성별 셀에서 비복원 추출."""
    import random

    data = current() if data is None else data
    pool = pool.drop_duplicates("uuid").reset_index(drop=True)
    donor_ids = set()
    age = pd.to_numeric(pool["age"], errors="coerce")
    groups = []
    for group in data["profiles"]:
        start = group["age"]
        end = 29 if start == 19 else start+9
        lo, hi = max(age_min,start), min(age_max,end)
        if lo > hi:
            continue
        count = sum(lo <= donor["age"] <= hi for donor in group["donors"])
        if count:
            rows = pool[age.between(lo,hi) & pool["sex"].astype(str).str.startswith(group["sex"])]
            groups.append((group, rows, count))
    reference = sum(count for _,_,count in groups)
    # For mixed targets use the candidate pool to allocate between covered and
    # exploration ages, and the survey distribution within the covered ages.
    covered = sum(len(rows) for _,rows,_ in groups)
    assigned = set().union(*(set(rows.index) for _,rows,_ in groups))
    unmatched = pool[age.between(age_min,age_max) & ~pool.index.isin(assigned)].copy()
    unmatched["_decade"] = age.loc[unmatched.index].astype(int)//10*10
    for decade, rows in unmatched.groupby("_decade"):
        weight = len(rows)*(reference/covered if covered else 1)
        groups.append(({"age":int(decade),"sex":"","donors":[]},rows,weight))
    reference = sum(weight for _,_,weight in groups)
    n = min(n,sum(len(rows) for _,rows,_ in groups))
    if n < 5:
        raise ValueError("선택한 타깃의 후보가 5명 미만입니다. 연령 범위를 넓혀 주세요.")
    quotas = [int(bool(len(rows))) for _,rows,_ in groups]
    if sum(quotas)>n:
        quotas = [0]*len(groups)
    for _ in range(n-sum(quotas)):
        i = max((i for i,(_,rows,_) in enumerate(groups) if quotas[i] < len(rows)),
                key=lambda i: n*groups[i][2]/reference-quotas[i])
        quotas[i] += 1
    sampled, coverage = [], []
    for i,((group,rows,count),quota) in enumerate(zip(groups,quotas)):
        if group["donors"]:
            coverage.append(f"{group['age']}세 시작 연령군·{group['sex']}성 {quota}명(제공 패널 {count}명)")
        else:
            coverage.append(f"{group['age']}대 {quota}명(제공 음료 패널 근거 없음 · 탐색)")

        if quota:
            picked = rows.sample(quota,random_state=seed+i).copy()
            donors = [(j,d) for j,d in enumerate(group["donors"]) if age_min <= d["age"] <= age_max]
            picked["review_source"] = "결합 패널" if donors else "Nemotron 탐색"
            if not donors:
                sampled.append(picked)
                continue
            # 나이가 가까운 사람끼리 짝짓는다(같은 연령대·성별 안에서). 부족하면 순환 재사용하고 고유 원천 수를 보고한다.
            rng = random.Random(seed+i)
            rng.shuffle(donors)
            donors.sort(key=lambda x: x[1]["age"])
            picked = picked.assign(_age=pd.to_numeric(picked["age"],errors="coerce")).sort_values("_age").drop(columns="_age")
            assignments = [donors[(j*len(donors))//quota if quota <= len(donors) else j % len(donors)] for j in range(quota)]
            donor_ids.update((i,j) for j,_ in assignments)
            picked["culinary_persona"] = [
                f"{background or ''} / 결합한 음료 구매 행동(생활 배경과 어긋나면 이 구매 행동을 우선): {donor['behavior']}"
                for background, (_,donor) in zip(picked["culinary_persona"].fillna(""),assignments)
            ]
            sampled.append(picked)
    return pd.concat(sampled,ignore_index=True), coverage, len(donor_ids)


def intent_check(sim_try, reference, min_gap=INTENT_GAP):
    """가상 '사 볼 의향'(%)과 설문 구매의향 TOP2(%) 비교. 사전 규칙: 차이가 min_gap 이하면 '비슷함'."""
    if not reference or not reference.get("n"):
        return None
    actual = reference["top2"] / reference["n"] * 100
    gap = sim_try - actual
    holdout = reference.get("source") == "검증용 응답자(holdout)"
    verdict = "비슷함" if abs(gap) <= min_gap else ("가상 응답이 높음" if gap > 0 else "가상 응답이 낮음")
    return {"사 볼 의향(가상, %)": round(sim_try, 1), "구매의향 TOP2(설문, %)": round(actual, 1),
            "차이(%p)": round(gap, 1), "설문 인원": reference["n"], "판정": verdict,
            "보정 계수": round(actual / sim_try, 2) if sim_try else None,
            "기준 설문": "검증용 응답자(패널과 겹치지 않음)" if holdout else "전체 응답자(패널과 겹칠 수 있음 · 자료를 다시 등록하세요)",
            "다음 단계": ("가상 결과를 그대로 참고" if verdict == "비슷함" else
                       "차이를 보정 계수로 표시하고, 이 컨셉은 실제 조사로 우선 확인")}


def evaluate(config, scenario, source, pool, llm, mock, data=None, *, visual=None):
    """정량(진열대·B안) → (선택) 좌담회 → 설문 대조 → 종합 피드백. 화면은 visual['sections']를 그대로 쓴다."""
    from time import perf_counter

    data = current() if data is None else data
    started, calls_before, hits_before = perf_counter(), llm.api_calls, llm.cache_hits
    panel, coverage, donors = panel_sample(pool,config.get("n",50),*config["age"],data=data)
    sc = deepcopy(scenario)
    sc["situation"] = f"{config['channel']}에서 음료를 비교 중입니다. 상황: {config['occasion']}"
    df = run(sc,panel,llm,seed=42,mode="prob")
    ok = df[df.error == ""]
    if ok.empty:
        first = str(df.error.iloc[0]) if len(df) else ""
        hint = ("API 키를 확인하세요." if "401" in first or "api_key" in first.lower() else
                "크레딧(잔액)이나 호출 한도를 확인하세요." if "429" in first or "quota" in first.lower() else
                "모델 이름(.env의 VM_MODEL)을 확인하세요." if "model" in first.lower() else "")
        raise ValueError(f"유효한 정량 응답이 없습니다. 첫 오류: {first[:200]} {hint}")
    cid = sc["concept_id"]
    labels = {p["id"]:p["name"] for p in sc["products"]}
    shares = shares_of(ok,sc)
    S = {}
    S["header"] = [f"# {config['name']} 검토 보고서",
                   "모의 실행 · 선택 비율과 발언은 흐름 확인용" if mock else "가상 소비자 평가 · 시장 반응 가설",
                   f"{config['price']:,}원 · {config['volume']}mL · {config['channel']} · {config['age'][0]}~{config['age'][1]}세",
                   f"표준 데이터 버전 {data['version']}", config["desc"]]
    S["evidence"] = [source]
    S["panel"] = [f"## 평가 패널 · Nemotron {len(panel)}명 / 제공 구매행동 원천 {donors}건 (시드 42)", " / ".join(coverage)]
    quant = ["## 정량 평가", f"유효 응답 {len(ok)}/{len(panel)}명. 선택 분포는 가상 진열대 내 응답입니다."]
    if len(ok) < len(df):
        quant.append(f"⚠️ 응답 실패 {len(df) - len(ok)}명 · 예: {str(df.loc[df.error != '', 'error'].iloc[0])[:120]}")
    if len(panel)<config.get("n",50):
        quant.append(f"선택 범위 후보가 {len(panel)}명이어서 요청한 {config.get('n',50)}명보다 적게 평가했습니다.")
    quant.extend(f"- {labels.get(k,'미구매')} {v:.1%}" for k,v in shares.items())
    # 근거 있는 패널(결합)과 탐색 인원을 섞지 않고 따로 보여 준다
    sources = panel.loc[ok.index,"review_source"]
    if sources.nunique() > 1:
        for name in ("결합 패널","Nemotron 탐색"):
            part = ok[sources == name]
            if len(part):
                quant.append(f"- {name}만 · 신제품 선택 {shares_of(part,sc)[cid]:.1%} · 유효 {len(part)}명")
        quant.append("※ 판단은 '결합 패널' 수치를 기준으로 하고, 탐색 인원 결과는 참고로만 보세요.")
    bands = (panel.loc[ok.index,"age"].astype(int).clip(lower=20)//10*10).rename("decade")  # 19세는 20대에 포함
    for decade, rows in ok.groupby(bands):
        bases = ", ".join(sorted(set(panel.loc[rows.index,"review_source"])))
        quant.append(f"- {decade}대 · 신제품 선택 {shares_of(rows,sc)[cid]:.1%} · 유효 {len(rows)}명 · {bases}")
    S["quant"] = quant
    if config.get("price_b"):
        variant = deepcopy(sc)
        next(p for p in variant["products"] if p["id"]==cid)["price"] = config["price_b"]
        other = run(variant,panel,llm,seed=42,mode="prob")
        ab = ["## A/B 가격 비교 · 동일 패널 및 진열 조건"]
        paired = (df.error=="") & (other.error=="")
        if paired.any():
            a = shares_of(df[paired],sc)[cid]
            b = shares_of(other[paired],variant)[cid]
            diff = (b-a)*100
            ab.append(f"A {config['price']:,}원 {a:.1%} / B {config['price_b']:,}원 {b:.1%} · B−A {diff:+.1f}%p · 양쪽 유효 {paired.sum()}명")
            if abs(diff) < config.get("min_diff",3.0):
                ab.append(f"차이가 {config.get('min_diff',3.0)}%p 미만이라 뚜렷한 차이로 보지 않습니다.")
        else:
            ab.append("양쪽 유효 응답이 없어 가격 차이 판단을 보류합니다.")
        S["ab"] = ab
    survey = None
    if config.get("survey", True):
        from . import audit, insight
        from .vsurvey import compare_with_survey, run_survey
        products = [next(p for p in sc["products"] if p["id"]==cid), *[p for p in sc["products"] if p["id"]!=cid]]
        concerns = config.get("concerns") or []
        survey = run_survey(llm, panel, products, sc["situation"], concerns)
        if not survey["summary"].empty:
            table = survey["summary"]
            S["survey"] = ["## 가상 소비자 설문 · 같은 문항·같은 가격 표시로 신제품과 비교 제품 평가",
                           f"응답 {survey['n_ok']}/{survey['n']}명(100명 분포 추정의 평균). 만족도·평점은 출시 전 '예상'입니다.",
                           md_table(table.to_dict("records"))]
            cmp = compare_with_survey(table, audit.survey_metrics())
            if not cmp.empty:
                S["survey"] += ["### 실제 설문과 같은 항목 비교", md_table(cmp.to_dict("records")),
                                "※ 실제 설문의 품질 의심 응답·표본 치우침·설계 문제는 '데이터 경고'를 함께 보세요."]
            if not survey["concerns"].empty:
                S["survey"] += ["### 과거 실패 사유·우려 점검(가상 소비자)", md_table(survey["concerns"].to_dict("records"))]
            conv = insight.conversion(config.get("storage",""), config.get("channel",""))
            top2 = float(table.iloc[0]["구매의향 TOP2(%)"])
            trial = insight.estimate_trial(top2, conv) if conv else None
            if trial:
                S["survey"] += ["### 실제 구매경험률로 환산(과거 컨셉테스트 기준)",
                                f"가상 구매의향 TOP2 {top2:.1f}% × {trial['사용 계수']} → 예상 12개월 구매경험률 " +
                                (f"약 {trial['예상 12개월 구매경험률(%)'][0]}%" if trial['예상 12개월 구매경험률(%)'][0] == trial['예상 12개월 구매경험률(%)'][1]
                                 else f"{trial['예상 12개월 구매경험률(%)'][0]}~{trial['예상 12개월 구매경험률(%)'][1]}%") + f" {trial['주의']}"]
            if survey["reasons"]:
                S["survey"] += ["이유 표본: " + " / ".join(survey["reasons"][:5])]
    fgi = None
    if config.get("fgi"):
        fgi = run_fgi(llm,sc,panel,5)
        S["fgi"] = ["## 정성 평가 · 동일 패널 내 좌담회 5명"]+[
            f"- {label} · "+" / ".join(fgi["summary"][key])
            for key,label in [("key_points","주요 반응"),("concerns","우려"),("improvements","개선 의견"),("persuasion","입장 변화")]]
    sim_try = float(ok[f"try_{cid}"].mean()*100) if f"try_{cid}" in ok else None
    check = intent_check(sim_try, data.get("references",{}).get(config["name"])) if sim_try is not None else None
    if check:
        S["validation"] = ["## 참고 대조 · 진열대 '사 볼 의향' vs 검증용 응답자 원자료",
                           "※ 기본 비교는 위 '실제 설문과 같은 항목 비교'(같은 문항·품질 의심 제외·모집단 가중)입니다. "
                           "여기는 다른 질문(진열대에서 '한 번 사 보겠다')과, 패널 만들 때 쓰지 않은 응답자의 원자료를 맞춘 "
                           "과적합 점검용이라 숫자가 다릅니다.",
                           " · ".join(f"{k} {v}" for k,v in check.items() if k not in ("다음 단계",)),
                           f"규칙: 차이 {INTENT_GAP:.0f}%p 이내면 비슷함. 다음 단계 → {check['다음 단계']}"]
    summary_for_llm = "\n".join(line for key in ("header","evidence","panel","quant","ab","survey","fgi","validation")
                                for line in S.get(key,[]))
    # 가격·마진: 컨셉보드 출고가와 소비자가, 경쟁 제품 실제 단가, 가상 지불가격
    price_lines = ["## 가격·마진 점검"]
    if config.get("cost_price"):
        m = (config["price"] - config["cost_price"]) / config["price"]
        price_lines.append(f"소비자가 {config['price']:,}원 · 출고가 {config['cost_price']:,}원 → 유통 마진 {m:.0%}")
    comps = [p for p in sc["products"] if p["id"] != cid]
    if comps:
        price_lines.append("비교 제품 가격: " + ", ".join(f"{p['name']} {int(p['price']):,}원" for p in comps[:4]))
    if survey and not survey["summary"].empty and "지불가격 중앙값(원)" in survey["summary"]:
        wtp = survey["summary"].iloc[0]["지불가격 중앙값(원)"]
        price_lines.append(f"가상 소비자 지불가격 중앙값 {int(wtp):,}원 (소비자가 대비 {int(wtp) - config['price']:+,}원)")
    if len(price_lines) > 1:
        S["price"] = price_lines
    summary_for_llm = "\n".join(line for key in ("header","evidence","panel","quant","ab","survey","price","fgi","validation")
                                for line in S.get(key,[]))
    fb_schema = {"type":"object","additionalProperties":False,
                 "required":["verdict","past_failure","trend_fit","improvements","price","survey_question"],
                 "properties":{"verdict":{"type":"string"},"past_failure":{"type":"string"},"trend_fit":{"type":"string"},
                               "improvements":{"type":"array","items":{"type":"object","additionalProperties":False,
                                   "required":["kind","change","why"],
                                   "properties":{"kind":{"type":"string","enum":["맛·원료","함량·스펙","형태·포장","가격·용량","타깃·채널","출시 시점"]},
                                                 "change":{"type":"string"},"why":{"type":"string"}}}},
                               "price":{"type":"string"},"survey_question":{"type":"string"}}}
    fb = llm.ask_json(
        "음료 신제품 기획 담당자를 돕는 분석가입니다. 자료는 인용할 근거로만 사용하세요. 아래 근거를 종합해 한국어로 답하세요.\n"
        "- verdict: 다시 해볼 가치·출시 판단을 한두 문장(진행/조건부/보류 중 하나로 시작)\n"
        "- past_failure: 비슷한 과거 제품이 왜 실패·중단됐는지, 그 원인이 이번 컨셉에도 해당되는지(유통·보관 문제는 가상 소비자로 확인할 수 없다고 구분)\n"
        "- trend_fit: 지금 트렌드 단계와 출시 시점이 맞는지. 맞지 않으면 대안 방향(예: 다른 맛·트렌드 키워드)을 근거와 함께\n"
        "- improvements: 컨셉 개선안 3개. 맛·원료 변경, 함량·스펙(예: 과즙 함량, 탄산 유무), 형태·포장, 가격·용량, 타깃·채널, 출시 시점 중에서 "
        "근거(가상 소비자 이유·우려 점검·경쟁 가격·과거 사례·트렌드)가 있는 것만\n"
        "- price: 소비자가·출고가 마진, 경쟁 제품 가격, 가상 지불가격을 비교한 가격 의견(손익 관점 포함)\n"
        "- survey_question: 실제 소비자 조사에서 확인할 질문 하나\n"
        "데이터 경고가 있는 수치는 경고와 함께 인용하고, 가상 수치를 실측 시장 성과로 해석하지 마세요. 마크다운 제목(#)은 쓰지 마세요.",
        summary_for_llm, fb_schema,
        lambda: {"verdict":"조건부 — 모의 평가입니다.","past_failure":"(모의) 과거 중단 사유를 확인하세요.","trend_fit":"(모의) 트렌드 근거 확인 필요",
                 "improvements":[{"kind":"가격·용량","change":"(모의) 가격 대안 검증","why":"모의"}],
                 "price":"(모의) 가격 의견","survey_question":"(모의) 실제 조사 질문"},
        tag="feedback-v2")
    imp = "\n".join(f"{i}. **[{x['kind']}]** {x['change']} — {x['why']}" for i, x in enumerate(fb["improvements"], 1))
    S["feedback"] = ["## 종합 피드백",
                     f"**판단** · {fb['verdict']}",
                     f"**과거에 왜 안 됐나** · {fb['past_failure']}",
                     f"**트렌드·타이밍** · {fb['trend_fit']}",
                     "**개선안**\n\n" + imp,
                     f"**가격·손익** · {fb['price']}",
                     f"**실제 조사로 확인할 질문** · {fb['survey_question']}"]
    S["feedback"] = [x.replace("\n#", "\n") for x in S["feedback"]]
    S["improvements"] = fb["improvements"]
    new_calls = llm.api_calls - calls_before
    unit = float(__import__("os").getenv("VM_COST_PER_CALL", "0.02"))
    S["footer"] = [f"실행 시간 {perf_counter()-started:.1f}초 · {'모의' if mock else '모델'} 새 응답 {new_calls}건 · "
                   f"캐시 재사용 {llm.cache_hits-hits_before}건 · 예상 비용 약 ${new_calls * unit:.2f}(1건 ${unit} 가정, .env VM_COST_PER_CALL)"]
    if visual is not None:
        from . import audit, insight
        from .vsurvey import compare_with_survey
        kpi = {"concept":config["name"],"price":config["price"],"shelf":round(float(shares[cid])*100,1),"n_ok":len(ok),
               "seconds":round(perf_counter()-started,1),"new_calls":new_calls,"cost":round(new_calls*unit,2)}
        if survey and not survey["summary"].empty:
            first = survey["summary"].iloc[0]
            kpi.update(top2=float(first["구매의향 TOP2(%)"]), wtp=float(first["지불가격 중앙값(원)"]))
            cmp_df = compare_with_survey(survey["summary"], audit.survey_metrics())
            if not cmp_df.empty:
                visual["survey_cmp"] = cmp_df.to_dict("records")
                row = cmp_df[cmp_df["항목"] == "구매의향"]
                if len(row):
                    kpi["survey_top2"] = float(row.iloc[0]["설문 제외+가중(%)"] if pd.notna(row.iloc[0]["설문 제외+가중(%)"]) else row.iloc[0]["설문 품질 의심 제외(%)"])
            conv = insight.conversion(config.get("storage",""), config.get("channel",""))
            tr = insight.estimate_trial(kpi["top2"], conv) if conv else None
            if tr:
                kpi["trial"] = tr["예상 12개월 구매경험률(%)"]
        visual.update(products=sc["products"],fgi=fgi,validation=check,feedback=fb,kpi=kpi,
                      survey={k:(v.to_dict("records") if hasattr(v,"to_dict") else v) for k,v in (survey or {}).items() if k!="raw"},
                      sections={k:"\n\n".join(v) for k,v in S.items() if k != "improvements"},
                      choices=[{"제품":labels.get(k,"미구매"),"선택 비율(%)":round(float(v)*100,1)} for k,v in shares.items()])
    report = "\n\n".join("\n\n".join(S[k]) for k in ("header","feedback","evidence","panel","quant","ab","survey","price","fgi","validation","footer") if k in S)
    return report, len(ok), round(float(shares[cid])*100,1)


def save_report(report, decision, note, config=None, *, visual=None):
    folder = OUT_DIR / ("challenge_"+uuid4().hex)
    folder.mkdir(parents=True)
    path = folder / "report.md"
    path.write_text(report+f"\n\n## 검토 판단\n\n{decision}\n\n{note}\n",encoding="utf8")
    if config is not None:
        import json
        from datetime import datetime
        (folder / "config.json").write_text(json.dumps(
            {"config":config,"saved_at":datetime.now().isoformat(timespec="seconds"),
             "decision":decision},ensure_ascii=False,indent=2),encoding="utf8")
    if visual:
        import json
        (folder / "evaluation.json").write_text(json.dumps(visual,ensure_ascii=False,indent=2,default=lambda o: o.item() if hasattr(o,"item") else str(o)),encoding="utf8")
    return path


def official_trend(raw):
    """Compare the two latest four-week windows from a single-term Google Trends export."""
    import csv
    import io
    from datetime import date, datetime, timedelta, timezone

    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    header = next((i for i,row in enumerate(rows)
                   if len(row)==2 and row[0].strip().lower() in {"week","주","주별"}), None)
    if header is None:
        raise ValueError("검색어 1개의 주간 관심도 CSV가 필요합니다.")
    title = rows[header][1].strip()
    if not (title.endswith("대한민국)") or title.endswith("South Korea)")):
        raise ValueError("지역을 대한민국으로 선택한 CSV가 필요합니다.")
    points = {}
    for row in rows[header+1:]:
        if len(row) != 2:
            continue
        if "^" in row[1] or "partial" in row[1].lower():
            continue
        try:
            day = date.fromisoformat(row[0])
            value = float(row[1])
        except ValueError:
            continue
        if 0 <= value <= 100:
            points[day] = value
    today = datetime.now(timezone(timedelta(hours=9))).date()
    complete = sorted((day,value) for day,value in points.items() if (today-day).days>=7)
    latest = complete[-8:]
    if len(latest)<8 or any((b[0]-a[0]).days!=7 for a,b in zip(latest,latest[1:])):
        raise ValueError("연속된 완료 주 8개가 필요합니다. 조회 기간을 최근 12개월로 설정해 보세요.")
    if (today-latest[-1][0]).days>21:
        raise ValueError("최근 완료 주가 오래되어 최신 동향 판단을 보류합니다.")
    prev = sum(v for _,v in latest[:4])/4
    current = sum(v for _,v in latest[4:])/4
    return (f"### 최근 실측 · Google Trends 대한민국 (사용자 제공 CSV)\n\n"
            f"{title} · 최근 4주 평균 {current:.1f} / 직전 4주 {prev:.1f} · {current-prev:+.1f}p\n\n"
            f"대상 기간 {latest[0][0]}~{latest[-1][0]+timedelta(days=6)} · 동일 조회에서 반환한 상대 검색 관심도입니다. "
            "단기 검색 변화의 원인은 POS와 별도로 확인이 필요합니다.")


def validate_concepts(pool, llm, base_scenario, data=None, n=30, seed=42, project=None):
    """제공 설문(검증용 응답자)의 컨셉별 구매의향 TOP2와 가상 패널의 '사 볼 의향'을 컨셉마다 비교한다.

    비교 기준선: 모든 컨셉에 설문 평균 TOP2 하나만 쓴다고 했을 때의 오차(평균 기준선).
    가상 패널 오차가 이보다 작아야 컨셉 간 차이를 구분한다고 말할 수 있다.
    """
    import json
    from datetime import datetime

    data = current() if data is None else data
    refs = {k: v for k, v in data.get("references", {}).items() if v.get("n")}
    if not refs:
        raise ValueError("비교할 설문 구매의향 자료가 없습니다. 표준 엑셀 3종을 등록해 주세요.")
    ages = [g["age"] for g in data.get("profiles", [])] or [19]
    age_range = (min(ages), max(29 if a == 19 else a + 9 for a in ages))
    panel, _, _ = panel_sample(pool, n, *age_range, seed=seed, data=data)
    local_boards = boards()
    rows = []
    for name, ref in refs.items():
        sc = deepcopy(base_scenario)
        product = next(p for p in sc["products"] if p["id"] == sc["concept_id"])
        board = local_boards.get(name) or next((v for k, v in local_boards.items() if k.split(" · ")[0] == name), None)
        desc, price, volume, *_ = board or (name, product["price"], product["volume_ml"], "")  # 설문 컨셉 이름 = 컨셉보드 이름(· 뒤는 용기 구분)
        price = ref["prices"][len(ref["prices"]) // 2] if ref["prices"] else price
        product.update(name=name, description=desc, price=int(price), volume_ml=int(volume))
        df = run(sc, panel, llm, seed=seed, mode="prob")
        ok = df[df.error == ""]
        if ok.empty:
            continue
        rows.append({"컨셉": name, "제시가격": int(price),
                     **intent_check(float(ok[f"try_{sc['concept_id']}"].mean() * 100), ref)})
    if not rows:
        raise ValueError("유효한 가상 응답이 없습니다.")
    actual = [r["구매의향 TOP2(설문, %)"] for r in rows]
    mean_actual = sum(actual) / len(actual)
    result = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"), "data_version": data["version"], "n": len(panel), "project": project,
        "mock": bool(llm.mock), "intent_gap_rule": INTENT_GAP, "rows": rows,
        "mae": round(sum(abs(r["차이(%p)"]) for r in rows) / len(rows), 1),
        "baseline_mae": round(sum(abs(a - mean_actual) for a in actual) / len(actual), 1),
        "within_rule": sum(r["판정"] == "비슷함" for r in rows),
    }
    out = OUT_DIR / f"validation_{datetime.now():%Y%m%d_%H%M%S}{'_mock' if llm.mock else ''}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf8")
    return result
