"""Import versioned challenge workbooks and build evaluation inputs.

원칙
- 시트·필수 열이 없으면 등록을 멈춘다(형식 자체가 다름).
- 행 단위 문제(알 수 없는 단위, 숫자가 아닌 값, 형식이 다른 연령대·성별, 중복 응답자 등)는
  등록을 멈추지 않고 그 행만 빼서 `issues`에 사유와 함께 남긴다. 화면에서 확인한다.
- 소비자 패널 응답자는 ID 해시로 둘로 나눈다. 절반(panel)은 가상 소비자에 붙일 구매 행동 원천,
  나머지 절반(holdout)은 가상 결과를 맞춰 보는 검증용 설문이다. 같은 사람이 양쪽에 쓰이지 않는다.
- 대회 자료(schema.json, standard_demo.json)는 저장소에 없고 로컬 data/challenge/ 에만 둔다.
"""
from collections import Counter, defaultdict
from datetime import date
from hashlib import sha256
from io import BytesIO
import json
import math
import re
import sqlite3

from .challenge import CHALLENGE_DIR, local_json
from .config import OUT_DIR

DATA_DIR = CHALLENGE_DIR
DB = OUT_DIR / "challenge_data.sqlite3"
KINDS = ("3-1", "3-2", "3-3")  # POS·제품자산 / 소비자 조사 / 구매여정·트렌드
BEHAVIOR = {
    "커피음료_월구매횟수": "월 커피 구매횟수", "탄산_월구매횟수": "월 탄산 구매횟수",
    "주스_월구매횟수": "월 주스 구매횟수", "주이용채널": "주이용채널",
    "신제품시도성향": "신제품 시도성향(5점)", "건강관심도": "건강관심도(5점)",
    "가격민감도": "가격민감도(5점)",
}
UNITS = {"EA": 1, "BOX(24)": 24}
EMPTY = dict(version="데이터 미등록", assets=[], pos={}, pos_period="-", profiles=[], trends={}, sns={},
             related={}, references={}, funnel={}, channels=[], journeys=[], issues=[], split={})


def schemas():
    return local_json("schema.json", {})


def read_book(kind, raw, schema=None):
    from openpyxl import load_workbook

    schema = schemas() if schema is None else schema
    if kind not in schema:
        raise ValueError("data/challenge/schema.json 이 없거나 이 파일 종류가 정의되어 있지 않습니다.")
    workbook = load_workbook(BytesIO(raw), read_only=True, data_only=True)
    result = {}
    try:
        for name, columns in schema[kind].items():
            if name not in workbook:
                raise ValueError(f"{kind}에 {name} 시트가 없습니다.")
            rows = workbook[name].values
            header = next(rows, ())
            missing = [c for c in columns if c not in header]
            if missing or any(header.count(c) != 1 for c in columns):
                raise ValueError(f"{kind} {name}의 필수 열을 확인해 주세요. 없는 열: {', '.join(missing) or '중복된 열'}")
            indexes = [header.index(c) for c in columns]
            result[name] = [
                (i, {c: r[j] for c, j in zip(columns, indexes)})
                for i, r in enumerate(rows, 2) if any(r[j] is not None for j in indexes)
            ]
            if not result[name]:
                raise ValueError(f"{name}에 데이터 행이 없습니다.")
    finally:
        workbook.close()
    return result


def display(value):
    return "자료 없음" if value is None or value == "" else value


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def valid_month(v):
    try:
        date.fromisoformat(str(v) + "-01")
        return True
    except ValueError:
        return False


def holdout_of(respondent) -> bool:
    """응답자 ID 해시로 고정 분할. True면 검증용(holdout)."""
    return int(sha256(str(respondent).encode()).hexdigest(), 16) % 2 == 1


def age_start(value):
    """'19~29세', '30대', '60대 이상', 34 → 연령대 시작(19, 30, 40, …). 읽을 수 없으면 None."""
    m = re.search(r"\d+", str(value))
    if not m:
        return None
    n = int(m.group())
    if n < 19 or n > 120:
        return None
    return 19 if n < 30 else n // 10 * 10


def snapshot(books):
    """books: {"3-1": {시트: [(행번호, 행)]}, "3-2": …, "3-3": …}"""
    issues = []

    def issue(sheet, row_no, reason):
        issues.append({"시트": sheet, "행": row_no, "사유": reason})

    internal, panel, journey = (books[k] for k in KINDS)
    plain = lambda rows: [r for _, r in rows]  # noqa: E731

    assets = []
    mapping = dict(코드="SKU코드", 제품="제품명", 상태="상태", 분류="카테고리", 규격="용기·용량",
                   컨셉="컨셉요약", 사유="단종·중단사유", 비고="비고")
    for r in plain(internal["4_제품자산DB"]):
        assets.append({k: display(r[v]) for k, v in mapping.items()})
    known_codes = {a["코드"] for a in assets}

    by_month = defaultdict(lambda: [0, 0, 0])
    seen = set()
    for row_no, r in internal["1_POS_판매"]:
        if not valid_month(r["기준월"]):
            issue("1_POS_판매", row_no, f"기준월 형식 확인 필요: {r['기준월']!r}")
            continue
        unit = UNITS.get(r["수량단위"])
        if not unit:
            issue("1_POS_판매", row_no, f"알 수 없는 수량 단위: {r['수량단위']!r}")
            continue
        if not (is_number(r["판매수량"]) and is_number(r["판매금액"])):
            issue("1_POS_판매", row_no, "판매수량·판매금액이 숫자가 아님")
            continue
        signature = tuple(r.values())
        if signature in seen:
            issue("1_POS_판매", row_no, "완전히 같은 행이 이미 있음(중복 제외)")
            continue
        seen.add(signature)
        if r["제품코드"] not in known_codes:
            issue("1_POS_판매", row_no, f"제품자산DB에 없는 제품코드: {r['제품코드']!r}")
            continue
        total = by_month[(r["기준월"], r["판매채널"], r["제품코드"])]
        total[0] += r["판매수량"] * unit
        total[1] += r["판매금액"]
        total[2] += 1
    months = sorted({month for month, _, _ in by_month})[-12:]
    pos = defaultdict(lambda: [0, 0, 0])
    for (month, channel, code), values in by_month.items():
        if month in months:
            total = pos[f"{channel}|{code}"]
            for i, value in enumerate(values):
                total[i] += value

    donor_groups = defaultdict(list)
    contact_keys, ids, holdout_ids = set(), set(), set()
    rows = sorted(panel["1_응답자정보"], key=lambda x: str(x[1]["응답일시"] or ""))
    for row_no, r in rows:
        respondent = r["응답자ID"]
        key = r["휴대폰해시"] or respondent
        if not respondent:
            issue("1_응답자정보", row_no, "응답자ID 없음")
            continue
        if key in contact_keys or respondent in ids or respondent in holdout_ids:
            issue("1_응답자정보", row_no, "중복 응답자(먼저 응답한 기록만 사용)")
            continue
        contact_keys.add(key)
        start = age_start(r["연령대"])
        sex = str(r["성별"] or "")[:1]
        if start is None or sex not in ("남", "여"):
            issue("1_응답자정보", row_no, f"연령대·성별 형식 확인 필요: {r['연령대']!r} / {r['성별']!r}")
            continue
        if holdout_of(respondent):
            holdout_ids.add(respondent)
            continue
        ids.add(respondent)
        end = 29 if start == 19 else start + 9
        try:
            approximate_age = int(str(r["응답일시"])[:4]) - int(r["출생연도"])
        except (TypeError, ValueError):
            approximate_age = start
        donor_groups[start, sex].append({
            "age": max(start, min(end, approximate_age)),
            "behavior": " · ".join(f"{label} {display(r[column])}" for column, label in BEHAVIOR.items()),
        })
    profiles = [
        {"age": age, "sex": sex, "donors": donors, "age_counts": dict(Counter(d["age"] for d in donors))}
        for (age, sex), donors in sorted(donor_groups.items())
    ]

    # 구매의향 기준값은 검증용(holdout) 응답자만으로 만든다 → 패널에 붙인 사람과 겹치지 않음
    references = defaultdict(list)
    for row_no, r in panel["2_컨셉평가"]:
        if r["응답자ID"] in holdout_ids:
            if is_number(r["구매의향"]):
                references[r["컨셉"]].append(r)
            else:
                issue("2_컨셉평가", row_no, "구매의향이 숫자가 아님")
    references = {name: {"n": len(rs), "top2": sum(x["구매의향"] >= 4 for x in rs), "source": "검증용 응답자(holdout)",
                         "prices": sorted({x["제시가격"] for x in rs if is_number(x["제시가격"])})}
                  for name, rs in references.items()}

    online = defaultdict(set)
    for r in plain(journey["2_구매여정_온라인로그"]):
        if r["세션ID"] is not None:
            online[(r["세션ID"], r["제품코드"])].add(r["이벤트"])
    funnel = defaultdict(lambda: [0, 0, 0])
    for (_, sku), events in online.items():
        if sku and "노출" in events:
            count = funnel[sku]
            count[0] += 1
            count[1] += "클릭" in events
            count[2] += "구매" in events

    trends = defaultdict(list)
    for row_no, r in journey["3_검색트렌드지수"]:
        month = r["기준월"]
        if not valid_month(month):
            issue("3_검색트렌드지수", row_no, f"기준월 형식 확인 필요: {month!r}")
            continue
        for word, value in r.items():
            if word != "기준월" and is_number(value) and 0 <= value <= 100:
                trends[word].append([month, value])
    sns = {}
    for r in sorted(plain(journey["5_SNS언급량"]), key=lambda x: str(x["기준월"])):
        sns[r["키워드"]] = {k: r[k] for k in ("기준월", "SNS언급량(건)", "광고·협찬 비중")}
    related = defaultdict(list)
    for r in plain(journey["6_연관검색어"]):
        related[r["키워드"]].append((r["연관검색어"], r["비중(최근 12개월)"]))

    if not months:
        raise ValueError("사용 가능한 POS 실적이 없습니다. 아래 제외 사유를 확인해 주세요: "
                         + "; ".join(f"{x['시트']} {x['행']}행 {x['사유']}" for x in issues[:5]))
    if not profiles:
        raise ValueError("사용 가능한 소비자 패널 응답자가 없습니다.")
    return dict(assets=assets, pos=pos, pos_period=f"{months[0]}~{months[-1]}", profiles=profiles,
                trends=trends, sns=sns, related=related, references=references, funnel=funnel,
                channels=plain(internal["5_유통채널_인프라"]),
                journeys=[{k: r[k] for k in ("관찰ID", "점포(유형)", "방문목적", "선택제품", "구매결과")}
                          for r in plain(journey["1_구매여정_오프라인"])],
                issues=issues, split={"panel": len(ids), "holdout": len(holdout_ids)})


def register(files):
    """Validate all three workbooks before activating a new snapshot in one transaction."""
    schema = schemas()
    if not schema:
        raise ValueError("data/challenge/schema.json 이 없습니다. 대회 자료 폴더를 로컬에 두세요(저장소에는 올리지 않음).")
    if set(files) != set(KINDS):
        raise ValueError("표준 엑셀 3종을 모두 선택해 주세요.")
    books = {kind: read_book(kind, files[kind][1], schema) for kind in KINDS}
    data = snapshot(books)
    hashes = {k: sha256(raw).hexdigest() for k, (_, raw) in files.items()}
    version = sha256("".join(hashes[k] for k in sorted(hashes)).encode()).hexdigest()[:16]
    data["version"] = version
    DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS imports(version TEXT PRIMARY KEY, manifest TEXT NOT NULL, snapshot TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS workbook_rows(version TEXT, dataset TEXT, sheet TEXT, row_no INTEGER, body TEXT, PRIMARY KEY(version,dataset,sheet,row_no))")
        db.execute("CREATE TABLE IF NOT EXISTS active_dataset(id INTEGER PRIMARY KEY CHECK(id=1), version TEXT NOT NULL)")
        snap = json.dumps(data, ensure_ascii=False, default=str)
        exists = db.execute("SELECT 1 FROM imports WHERE version=?", (version,)).fetchone()
        if exists:  # 같은 파일이라도 처리 규칙이 바뀌었을 수 있으니 스냅숏은 새로 쓴다
            db.execute("UPDATE imports SET snapshot=? WHERE version=?", (snap, version))
        else:
            manifest = {k: {"file": files[k][0], "sha256": hashes[k], "sheets": {s: len(rows) for s, rows in books[k].items()}} for k in KINDS}
            db.execute("INSERT INTO imports VALUES(?,?,?)", (version, json.dumps(manifest, ensure_ascii=False), snap))
            db.executemany("INSERT INTO workbook_rows VALUES(?,?,?,?,?)", (
                (version, k, s, i, json.dumps(row, ensure_ascii=False, default=str))
                for k, book in books.items() for s, rows in book.items() for i, row in rows))
        db.execute("INSERT INTO active_dataset VALUES(1,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version", (version,))
    return data


def current():
    stored = from_store()  # 새 자료 저장소에 등록된 자료가 있으면 그것을 쓴다
    if stored:
        return {**EMPTY, **stored}
    if DB.is_file():
        with sqlite3.connect(DB) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='active_dataset'").fetchone():
                row = db.execute("SELECT snapshot FROM imports JOIN active_dataset USING(version) WHERE id=1").fetchone()
                if row:
                    return {**EMPTY, **json.loads(row[0])}
    return {**EMPTY, **local_json("standard_demo.json", {})}


def from_store() -> dict | None:
    """자료 저장소(vm.store)에 등록된 표로 평가용 묶음을 만든다. 원자료는 그대로 두고, 집계에 쓴 규칙을 함께 남긴다.

    - POS 집계: BOX(n)은 n개로 환산, 0 이하·완전 중복·TEST 코드는 집계에서 빼되 경고로 남김(원자료는 저장소에 그대로).
    - 소비자 패널: 응답자 ID 해시로 반씩 나눠 구매 행동 원천(panel)과 대조용(holdout)으로 사용. 품질 의심 응답도 빼지 않고
      경고와 '품질 의심 제외' 수치를 따로 보여 준다.
    """
    from . import store
    from .audit import num, unit_size, view
    if store.version() == "자료 없음":
        return None
    t = view
    assets_t, pos_t, resp, evals = t("assets"), t("pos"), t("respondents"), t("concept_eval")
    mapping = dict(코드="SKU코드", 제품="제품명", 상태="상태", 분류="카테고리", 규격="용기·용량",
                   컨셉="컨셉요약", 사유="단종·중단사유", 비고="비고")
    assets = [{k: display(r.get(v) if pd_notna(r.get(v)) else None) for k, v in mapping.items()} for r in assets_t.to_dict("records")]
    pos = {}
    months = []
    if not pos_t.empty:
        p = pos_t.copy()
        p["ea"] = num(p["판매수량"]) * p.get("수량단위", "EA").map(unit_size) if "수량단위" in p else num(p["판매수량"])
        keep = (p["ea"] > 0) & ~p["제품코드"].astype(str).str.contains("TEST", case=False) \
            & ~p.drop(columns=[c for c in p if c.startswith("_")] + ["ea"]).duplicated()
        p = p[keep]
        months = sorted(p["기준월"].astype(str).unique())[-12:]
        g = p[p["기준월"].astype(str).isin(months)].groupby([p.get("판매채널", "전체"), "제품코드"])
        for (ch, code), d in g:
            pos[f"{ch}|{code}"] = [int(d["ea"].sum()), int(num(d.get("판매금액", 0)).sum()), len(d)]
    donor_groups, holdout_ids = defaultdict(list), set()
    for r in resp.to_dict("records"):
        start, sex = age_start(r.get("연령대")), str(r.get("성별") or "")[:1]
        if start is None or sex not in ("남", "여"):
            continue
        if holdout_of(r["응답자ID"]):
            holdout_ids.add(r["응답자ID"])
            continue
        donor_groups[start, sex].append({
            "age": start, "behavior": " · ".join(f"{label} {display(r.get(col))}" for col, label in BEHAVIOR.items() if col in r)})
    profiles = [{"age": a, "sex": s, "donors": d, "age_counts": {a: len(d)}} for (a, s), d in sorted(donor_groups.items())]
    references = {}
    if not evals.empty:
        h = evals[evals["응답자ID"].isin(holdout_ids)]
        for name, d in h.groupby("컨셉"):
            v = num(d["구매의향"])
            references[str(name)] = {"n": int(v.notna().sum()), "top2": int((v >= 4).sum()), "source": "검증용 응답자(holdout)",
                                     "prices": sorted({int(x) for x in num(d.get("제시가격", pd_series())).dropna()})}
    trends, sns, related = defaultdict(list), {}, defaultdict(list)
    tr = t("search_trend")
    for r in tr.to_dict("records"):
        for k, v in r.items():
            if k != "기준월" and not str(k).startswith("_") and is_number(v) and 0 <= v <= 100:
                trends[k].append([str(r["기준월"]), v])
    for r in sorted(t("sns").to_dict("records"), key=lambda x: str(x.get("기준월"))):
        sns[r["키워드"]] = {k: r.get(k) for k in ("기준월", "SNS언급량(건)", "광고·협찬 비중")}
    for r in t("related_search").to_dict("records"):
        related[r["키워드"]].append((r["연관검색어"], r.get("비중(최근 12개월)")))
    funnel = defaultdict(lambda: [0, 0, 0])
    log = t("online_log")
    if not log.empty:
        for (_, sku), d in log.groupby(["세션ID", "제품코드"]):
            ev = set(d["이벤트"].astype(str))
            if "노출" in ev:
                f = funnel[sku]
                f[0] += 1
                f[1] += "클릭" in ev
                f[2] += "구매" in ev
    journeys = [{k: r.get(k) for k in ("관찰ID", "점포(유형)", "방문목적", "선택제품", "구매결과")} for r in t("offline_journey").to_dict("records")]
    from .audit import excluded_reasons
    ex = excluded_reasons()
    return dict(version=f"{', '.join(store.analysis_datasets())} · {store.version()}" + (f" · 제외: {', '.join(ex)}" if ex else ""), assets=assets, pos=pos, pos_period=f"{months[0]}~{months[-1]}" if months else "-",
                profiles=profiles, trends=trends, sns=sns, related=related, references=references, funnel=funnel,
                channels=[{k: v for k, v in r.items() if not str(k).startswith("_")} for r in t("infra").to_dict("records")],
                journeys=journeys, issues=[], split={"panel": sum(len(g["donors"]) for g in profiles), "holdout": len(holdout_ids)})


def pd_notna(v):
    import pandas as pd
    return v is not None and not (isinstance(v, float) and pd.isna(v))


def pd_series():
    import pandas as pd
    return pd.Series(dtype=float)
