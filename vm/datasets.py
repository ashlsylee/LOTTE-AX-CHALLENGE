"""Import versioned challenge workbooks and build evaluation inputs."""
from collections import Counter, defaultdict
from datetime import date
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import sqlite3

from openpyxl import load_workbook

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "challenge"
DB = DATA_DIR.parent.parent / "outputs" / "challenge_data.sqlite3"
SCHEMAS = json.loads((DATA_DIR / "schema.json").read_text(encoding="utf8"))
BEHAVIOR = {
    "커피음료_월구매횟수": "월 커피 구매횟수", "탄산_월구매횟수": "월 탄산 구매횟수",
    "주스_월구매횟수": "월 주스 구매횟수", "주이용채널": "주이용채널",
    "신제품시도성향": "신제품 시도성향(5점)", "건강관심도": "건강관심도(5점)",
    "가격민감도": "가격민감도(5점)",
}
UNITS = {"EA": 1, "BOX(24)": 24}


def read_book(kind, raw):
    workbook = load_workbook(BytesIO(raw), read_only=True, data_only=True)
    result = {}
    try:
        for name, columns in SCHEMAS[kind].items():
            if name not in workbook:
                raise ValueError(f"{kind}에 {name} 시트가 없습니다.")
            rows = workbook[name].values
            header = next(rows, ())
            if set(columns)-set(header) or any(header.count(c)!=1 for c in columns):
                raise ValueError(f"{kind} {name}의 필수 열을 확인해 주세요.")
            indexes = [header.index(c) for c in columns]
            result[name] = [
                (i, {c: r[j] for c,j in zip(columns,indexes)})
                for i,r in enumerate(rows,2) if any(r[j] is not None for j in indexes)
            ]
            if not result[name]:
                raise ValueError(f"{name}에 데이터 행이 없습니다.")
    finally:
        workbook.close()
    return result


def display(value):
    return "자료 없음" if value is None or value == "" else value


def snapshot(books):
    internal, panel, journey = (
        {sheet:[r for _,r in rows] for sheet,rows in books[kind].items()} for kind in SCHEMAS
    )
    assets = []
    for r in internal["4_제품자산DB"]:
        mapping = dict(코드="SKU코드",제품="제품명",상태="상태",분류="카테고리",규격="용기·용량",
                       컨셉="컨셉요약",사유="단종·중단사유",비고="비고")
        assets.append({k:display(r[v]) for k,v in mapping.items()})
    sales = internal["1_POS_판매"]
    by_month = defaultdict(lambda:[0,0,0])
    seen = set()
    for r in sales:
        date.fromisoformat(str(r["기준월"])+"-01")
        unit = UNITS.get(r["수량단위"])
        if not unit:
            raise ValueError(f"알 수 없는 POS 수량 단위 {r['수량단위']!r}")
        if any(not isinstance(r[k],(int,float)) or not math.isfinite(r[k]) for k in ("판매수량","판매금액")):
            raise ValueError("POS 수량과 금액은 숫자여야 합니다.")
        signature = tuple(r.values())
        if signature in seen:
            continue
        seen.add(signature)
        if r["제품코드"] == "TEST001":
            continue
        total = by_month[(r["기준월"],r["판매채널"],r["제품코드"])]
        total[0] += r["판매수량"]*unit
        total[1] += r["판매금액"]
        total[2] += 1
    months = sorted({month for month,_,_ in by_month})[-12:]
    pos = defaultdict(lambda:[0,0,0])
    for (month,channel,code), values in by_month.items():
        if month in months:
            total = pos[f"{channel}|{code}"]
            for i,value in enumerate(values):
                total[i] += value
    if not months:
        raise ValueError("사용 가능한 POS 실적이 없습니다.")

    donor_groups = defaultdict(list)
    contact_keys, ids = set(), set()
    rows = sorted(panel["1_응답자정보"],key=lambda r:str(r["응답일시"] or ""))
    for r in rows:
        respondent = r["응답자ID"]
        key = r["휴대폰해시"] or respondent
        if not respondent or not key:
            raise ValueError("패널 응답자 ID를 확인해 주세요.")
        if key in contact_keys or respondent in ids:
            continue
        contact_keys.add(key)
        ids.add(respondent)
        age = int(str(r["연령대"]).split("~")[0])
        sex = str(r["성별"])[0]
        if age not in (19,30,40,50) or sex not in ("남","여"):
            raise ValueError("패널 연령대·성별 값이 기준 형식과 다릅니다.")
        approximate_age = int(str(r["응답일시"])[:4])-int(r["출생연도"])
        donor_groups[age,sex].append({
            "age":max(age,min(29 if age==19 else age+9,approximate_age)),
            "behavior":" · ".join(f"{label} {display(r[column])}" for column,label in BEHAVIOR.items())
        })
    profiles = [
        {"age":age,"sex":sex,"donors":donors,"age_counts":dict(Counter(d["age"] for d in donors))}
        for (age,sex),donors in sorted(donor_groups.items())
    ]

    references = defaultdict(list)
    for r in panel["2_컨셉평가"]:
        if r["응답자ID"] in ids and isinstance(r["구매의향"],(int,float)):
            references[r["컨셉"]].append(r)
    references = {name:{"n":len(rows),"top2":sum(r["구매의향"]>=4 for r in rows),
                        "prices":sorted({r["제시가격"] for r in rows if isinstance(r["제시가격"],(int,float))})}
                  for name,rows in references.items()}
    online = defaultdict(set)
    for r in journey["2_구매여정_온라인로그"]:
        if r["세션ID"] is not None:
            online[(r["세션ID"],r["제품코드"])].add(r["이벤트"])
    funnel = defaultdict(lambda:[0,0,0])
    for (_,sku),events in online.items():
        if sku and "노출" in events:
            count = funnel[sku]
            count[0]+=1
            count[1]+="클릭" in events
            count[2]+="구매" in events

    trends = defaultdict(list)
    for r in journey["3_검색트렌드지수"]:
        month = r["기준월"]
        date.fromisoformat(str(month)+"-01")
        for word,value in r.items():
            if word != "기준월" and isinstance(value,(int,float)) and 0 <= value <= 100:
                trends[word].append([month,value])
    sns = {}
    for r in sorted(journey["5_SNS언급량"],key=lambda r:str(r["기준월"])):
        sns[r["키워드"]] = {k:r[k] for k in ("기준월","SNS언급량(건)","광고·협찬 비중")}
    related = defaultdict(list)
    for r in journey["6_연관검색어"]:
        related[r["키워드"]].append((r["연관검색어"],r["비중(최근 12개월)"]))
    return dict(assets=assets,pos=pos,pos_period=f"{months[0]}~{months[-1]}",profiles=profiles,
                trends=trends,sns=sns,related=related,references=references,funnel=funnel,channels=internal["5_유통채널_인프라"],
                journeys=[{k:r[k] for k in ("관찰ID","점포(유형)","방문목적","선택제품","구매결과")}
                          for r in journey["1_구매여정_오프라인"]])


def register(files):
    """Validate all three workbooks before activating a new snapshot in one transaction."""
    if set(files) != set(SCHEMAS):
        raise ValueError("표준 엑셀 3종을 모두 선택해 주세요.")
    books = {kind:read_book(kind,files[kind][1]) for kind in SCHEMAS}
    data = snapshot(books)
    hashes = {k:sha256(raw).hexdigest() for k,(_,raw) in files.items()}
    version = sha256("".join(hashes[k] for k in sorted(hashes)).encode()).hexdigest()[:16]
    data["version"] = version
    DB.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(DB) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS imports(version TEXT PRIMARY KEY, manifest TEXT NOT NULL, snapshot TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS workbook_rows(version TEXT, dataset TEXT, sheet TEXT, row_no INTEGER, body TEXT, PRIMARY KEY(version,dataset,sheet,row_no))")
        db.execute("CREATE TABLE IF NOT EXISTS active_dataset(id INTEGER PRIMARY KEY CHECK(id=1), version TEXT NOT NULL)")
        exists = db.execute("SELECT 1 FROM imports WHERE version=?",(version,)).fetchone()
        if not exists:
            manifest = {k:{"file":files[k][0],"sha256":hashes[k],"sheets":{s:len(rows) for s,rows in books[k].items()}} for k in SCHEMAS}
            db.execute("INSERT INTO imports VALUES(?,?,?)",(version,json.dumps(manifest,ensure_ascii=False),json.dumps(data,ensure_ascii=False,default=str)))
            db.executemany("INSERT INTO workbook_rows VALUES(?,?,?,?,?)",(
                (version,k,s,i,json.dumps(row,ensure_ascii=False,default=str))
                for k,book in books.items() for s,rows in book.items() for i,row in rows))
        db.execute("INSERT INTO active_dataset VALUES(1,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version",(version,))
    return data


def current():
    if DB.is_file():
        with sqlite3.connect(DB) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='active_dataset'").fetchone():
                row = db.execute("SELECT snapshot FROM imports JOIN active_dataset USING(version) WHERE id=1").fetchone()
                if row:
                    return json.loads(row[0])
    return json.loads((DATA_DIR / "standard_demo.json").read_text(encoding="utf8"))
