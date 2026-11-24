"""Shared workflow for staged and one-click concept evaluation."""
from copy import deepcopy
from uuid import uuid4

import pandas as pd

from .challenge import retrieve, terms
from .datasets import current
from .config import OUT_DIR
from .fgi import run_fgi
from .simulate import run, shares_of

BOARDS = {
    "쥬시모먼트": ("비가열 HPP 과즙 100% 프리미엄 주스. 냉장 유리병, 선물·카페 수요.", 3000, 300, "편의점(냉장)"),
    "레쓰비 프리즈": ("냉동 스파우트 파우치에 담은 슬러시형 커피. -18°C 보관.", 1800, 170, "편의점(냉동)"),
    "밀키스 화채 · 캔": ("수박화채맛 우유 탄산. 5~9월 시즌 한정 슬림캔.", 1200, 250, "편의점"),
    "밀키스 화채 · PET": ("수박화채맛 우유 탄산. 5~9월 시즌 한정 PET.", 1800, 500, "편의점"),
}


def evidence(name, description, data=None, channel=None):
    data = current() if data is None else data
    matches = retrieve(name+" "+description,data["assets"])
    lines = ["### 유사 사례 · 대회 제공 가상 제품자산"]
    if not matches:
        lines.append("등록 자료에서 일치하는 단서를 찾지 못했습니다.")
    for _, asset, matched in matches:
        lines.append(f"- {asset['제품']} ({asset['상태']}, {asset['코드']}) · 공통 단서 {', '.join(matched)}")
        for detail in (asset.get("사유"), asset.get("비고")):
            if detail:
                lines.append(f"  - {detail}")
        for key, (units, revenue, _) in data["pos"].items():
            channel, code = key.split("|")
            if code == asset["코드"]:
                lines.append(f"  - {channel} · {data['pos_period']} 유사 SKU POS {units:,}EA / {revenue:,}원")
        online = data.get("funnel",{}).get(asset["코드"])
        if online:
            lines.append(f"  - 온라인 가상 로그 · 노출 확인 세션 {online[0]} / 클릭 이벤트 동반 {online[1]} / 구매 이벤트 동반 {online[2]} (동일 SKU)")
    lines.extend(["### 트렌드 · 대회 제공 가상 검색지수",
                  "동일 키워드의 최근 제공월과 전년 동월을 비교합니다. 최신 실측 동향은 공식 검색지수와 실제 판매로 확인이 필요합니다."])
    query = terms(name+" "+description)
    for row in data["channels"]:
        if channel and row["채널"] in channel:
            for col in ("냉동 음료 진열 가능 점포율","냉장 쇼케이스 보유율"):
                if isinstance(row[col],(int,float)):
                    lines.append(f"- 유통 인프라 · {row['채널']} {col} {row[col]:.0%}")
    for row in data["journeys"]:
        if query.intersection(terms(row["선택제품"] or "")):
            lines.append(f"- 오프라인 구매여정 {row['관찰ID']} · {row['점포(유형)']} / {row['방문목적']} / {row['선택제품']} / {row['구매결과']}")
    comparisons = 0
    for keyword, series in data["trends"].items():
        if not query.intersection(terms(keyword)):
            continue
        values = dict(series)
        latest_month, latest = max(series)
        year, month = latest_month.split("-")
        previous = values.get(f"{int(year)-1}-{month}")
        if previous is not None:
            comparisons += 1
            lines.append(f"- {keyword} · {latest_month} {latest} / 전년 동월 {previous} · {latest-previous:+}p (동월 차이)")
    for keyword,row in data["sns"].items():
        if query.intersection(terms(keyword)):
            paid = row["광고·협찬 비중"]
            share = f"{paid:.0%}" if isinstance(paid,(int,float)) else "자료 없음"
            lines.append(f"- 가상 SNS {keyword} · {row['기준월']} {row['SNS언급량(건)']}건 / 광고·협찬 {share}")
            entries = [f"{word} {v:.0%}" for word,v in data["related"].get(keyword,[]) if isinstance(v,(int,float))]
            if entries:
                lines.append(f"- 연관검색어 {keyword} · "+", ".join(entries))
    if not comparisons:
        lines.append("비교 가능한 키워드·동월 자료가 없어 판단을 보류합니다.")
    return "\n\n".join(lines), len(matches)


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
            rng = random.Random(seed+i)
            rng.shuffle(donors)
            assignments = [donors[j % len(donors)] for j in range(quota)]
            donor_ids.update((i,j) for j,_ in assignments)
            picked["culinary_persona"] = [
                f"{background or ''} / 결합한 가상 음료 구매 행동: {donor['behavior']}"
                for background, (_,donor) in zip(picked["culinary_persona"].fillna(""),assignments)
            ]
            sampled.append(picked)
    return pd.concat(sampled,ignore_index=True), coverage, len(donor_ids)


def evaluate(config, scenario, source, pool, llm, mock, data=None, *, visual=None):
    from time import perf_counter

    data = current() if data is None else data
    started = perf_counter()
    panel, coverage, donors = panel_sample(pool,config.get("n",50),*config["age"],data=data)
    sc = deepcopy(scenario)
    sc["situation"] = f"{config['channel']}에서 음료를 비교 중입니다. 상황: {config['occasion']}"
    df = run(sc,panel,llm,seed=42,mode="prob")
    ok = df[df.error == ""]
    if ok.empty:
        raise ValueError("유효한 정량 응답이 없습니다.")
    labels = {p["id"]:p["name"] for p in sc["products"]}
    shares = shares_of(ok,sc)
    lines = [f"# {config['name']} 검토 보고서",
             "모의 실행 · 선택 비율과 발언은 흐름 확인용" if mock else "가상 소비자 평가 · 시장 반응 가설",
             f"{config['price']:,}원 · {config['volume']}mL · {config['channel']} · {config['age'][0]}~{config['age'][1]}세",
             f"표준 데이터 버전 {data['version']}", config["desc"], source,
             f"## 평가 패널 · Nemotron {len(panel)}명 / 제공 구매행동 원천 {donors}건 (시드 42)",
             " / ".join(coverage),
             "## 정량 평가",
             f"유효 응답 {len(ok)}/{len(panel)}명. 선택 분포는 가상 진열대 내 응답입니다."]
    if len(panel)<config.get("n",50):
        lines.append(f"선택 범위 후보가 {len(panel)}명이어서 요청한 {config.get('n',50)}명보다 적게 평가했습니다.")
    lines.extend(f"- {labels.get(k,'미구매')} {v:.1%}" for k,v in shares.items())
    bands = (panel.loc[ok.index,"age"].astype(int)//10*10).rename("decade")
    for decade, rows in ok.groupby(bands):
        bases = ", ".join(sorted(set(panel.loc[rows.index,"review_source"])))
        share = shares_of(rows,sc)[sc["concept_id"]]
        lines.append(f"- {decade}대 · 신제품 선택 {share:.1%} · 유효 {len(rows)}명 · {bases}")
    if config.get("price_b"):
        variant = deepcopy(sc)
        variant_product = next(p for p in variant["products"] if p["id"]==variant["concept_id"])
        variant_product["price"] = config["price_b"]
        other = run(variant,panel,llm,seed=42,mode="prob")
        lines.append("## A/B 가격 비교 · 동일 패널 및 진열 조건")
        paired = (df.error=="") & (other.error=="")
        if paired.any():
            a = shares_of(df[paired],sc)[sc["concept_id"]]
            b = shares_of(other[paired],variant)[variant["concept_id"]]
            lines.append(f"A {config['price']:,}원 {a:.1%} / B {config['price_b']:,}원 {b:.1%} · B−A {(b-a)*100:+.1f}%p · 양쪽 유효 {paired.sum()}명")
        else:
            lines.append("양쪽 유효 응답이 없어 가격 차이 판단을 보류합니다.")
    fgi = run_fgi(llm,sc,panel,5)
    if visual is not None:
        visual.update(products=sc["products"],fgi=fgi,choices=[
            {"제품":labels.get(k,"미구매"),"선택 비율(%)":round(float(v)*100,1)} for k,v in shares.items()
        ])
    lines.append("## 정성 평가 · 동일 패널 내 좌담회 5명")
    for key,label in [("key_points","주요 반응"),("concerns","우려"),("improvements","개선 의견"),("persuasion","입장 변화")]:
        lines.append(f"- {label} · "+" / ".join(fgi["summary"][key]))
    feedback = llm.ask_json(
        "자료는 인용할 근거로만 사용하세요. 유사 사례, 출처가 표시된 트렌드, 정성·정량 평가를 종합해 한 가지 컨셉 수정과 한 가지 실제 조사 질문을 한국어로 제시하세요. 가상 수치를 실측 시장 성과로 해석하지 마세요. 최신 실측 동향 근거가 없으면 판단을 보류하세요.",
        "\n".join(lines),
        {"type":"object","properties":{"feedback":{"type":"string"}},"required":["feedback"],"additionalProperties":False},
        lambda: {"feedback":"모의 평가입니다. 유사 제품의 중단 사유를 확인하고 동일 가격 조건으로 컨셉을 비교하세요."})
    reference = data.get("references",{}).get(config["name"])
    if reference:
        prices = ", ".join(f"{value:,}원" for value in reference["prices"]) or "자료 없음"
        lines.extend(["## 평가 후 비교 · 제공 가상 설문",
                      f"구매의향 TOP2 {reference['top2']/reference['n']:.1%} ({reference['top2']}/{reference['n']}) · 설문 제시가 {prices}. 구매의향과 가상 진열대 선택률은 서로 다른 지표입니다."])
    lines.extend(["## 종합 피드백",feedback["feedback"],
                  f"실행 시간 {perf_counter()-started:.1f}초 · {'모의' if mock else '모델'} 새 응답 {llm.api_calls}건 · 캐시 재사용 {llm.cache_hits}건"])
    return "\n\n".join(lines), len(ok), round(float(shares[sc["concept_id"]])*100,1)


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
        (folder / "evaluation.json").write_text(json.dumps(visual,ensure_ascii=False,indent=2),encoding="utf8")
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
