"""자료 저장소: 어떤 형식의 파일이든 원본 그대로 보관하고, 표마다 '무슨 자료인지(역할)'를 붙인다.

원칙
- 원본을 고치거나 버리지 않는다. 행·열을 그대로 저장하고(파일 해시·시트·행 번호 포함), 분석할 때 경고를 붙인다.
- 역할은 시트 이름이 아니라 열 구성(config/roles.json의 열 이름·별칭)으로 알아본다. 그래서 다른 회사·다른 해의
  비슷한 자료도 열 이름만 비슷하면 그대로 쓰인다.
- 알아보지 못한 표는 '미분류'로 저장해 두고, 화면에서 역할과 열을 짝지어 주면(또는 AI 제안을 확인하면)
  같은 머리글을 가진 다음 파일부터는 자동으로 적용된다(머리글 서명별 매핑 저장).
- Word·PowerPoint·텍스트는 문서로 저장한다. Word 안의 표는 표로도 저장해 역할을 찾는다.
- 저장 위치: outputs/data_store.sqlite3 (저장소에는 올리지 않음)
"""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import CONFIG_DIR, OUT_DIR

DB = OUT_DIR / "data_store.sqlite3"
ROLES = json.loads((CONFIG_DIR / "roles.json").read_text(encoding="utf-8"))


def _connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB)
    db.execute("CREATE TABLE IF NOT EXISTS files(file_id TEXT PRIMARY KEY, name TEXT, sha256 TEXT, added TEXT, active INTEGER DEFAULT 1)")
    cols = [r[1] for r in db.execute("PRAGMA table_info(files)")]
    if "dataset" not in cols:  # 예전 저장소 → 기본 묶음으로
        db.execute("ALTER TABLE files ADD COLUMN dataset TEXT DEFAULT '기본 자료'")
    if "source" not in cols:
        db.execute("ALTER TABLE files ADD COLUMN source TEXT DEFAULT '파일'")
    db.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS tables(table_id TEXT PRIMARY KEY, file_id TEXT, sheet TEXT, header TEXT, signature TEXT, "
               "role TEXT, mapping TEXT, rows TEXT, how TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS documents(doc_id TEXT PRIMARY KEY, file_id TEXT, name TEXT, text TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS mappings(signature TEXT PRIMARY KEY, role TEXT, mapping TEXT, saved TEXT)")
    return db


# ---------- 자료 묶음(데이터셋)과 설정 ----------
def get_setting(key, default=None):
    row = _connect().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_setting(key, value):
    db = _connect()
    with db:
        db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, json.dumps(value, ensure_ascii=False)))


def datasets() -> list[str]:
    names = {n for n, in _connect().execute("SELECT DISTINCT dataset FROM files")} | set(get_setting("dataset_names", []))
    return sorted(names)


def create_dataset(name: str) -> str | None:
    """새 묶음. 이름이 비었거나 이미 있으면 이유를 돌려준다(None이면 성공)."""
    name = name.strip()
    if not name:
        return "이름을 입력하세요."
    if name.casefold() in {n.casefold() for n in datasets()}:
        return f"'{name}' 묶음이 이미 있습니다. 다른 이름을 쓰세요."
    set_setting("dataset_names", sorted({*get_setting("dataset_names", []), name}))
    set_active_dataset(name)
    chosen = get_setting("analysis_datasets")
    if chosen is not None:  # 새 묶음은 분석 선택에도 넣어 둔다(나중에 빼도 됨)
        set_analysis_datasets([*chosen, name])
    return None


def rename_dataset(old: str, new: str) -> str | None:
    new = new.strip()
    if not new:
        return "이름을 입력하세요."
    if new.casefold() in {n.casefold() for n in datasets() if n != old}:
        return f"'{new}' 묶음이 이미 있습니다."
    db = _connect()
    with db:
        db.execute("UPDATE files SET dataset=? WHERE dataset=?", (new, old))
        for key, value in list(db.execute("SELECT key, value FROM settings")):
            if key.endswith("::" + old):
                db.execute("UPDATE settings SET key=? WHERE key=?", (key[: -len(old)] + new, key))
    names = [new if n == old else n for n in get_setting("dataset_names", [])]
    set_setting("dataset_names", sorted(set(names) | {new}))
    for k in ("trend_jobs", "db_links"):
        d = get_setting(k, {})
        if old in d:
            d[new] = d.pop(old)
            set_setting(k, d)
    if active_dataset() == old:
        set_active_dataset(new)
    chosen = get_setting("analysis_datasets")
    if chosen is not None:
        set_analysis_datasets([new if n == old else n for n in chosen])
    return None


def active_dataset() -> str:
    return get_setting("active_dataset") or (datasets()[0] if datasets() else "기본 자료")


def set_active_dataset(name: str):
    """자료를 넣을 묶음(등록 대상)."""
    set_setting("active_dataset", name)


def analysis_datasets() -> list[str]:
    """분석에 쓰는 묶음들. 저장된 선택이 없으면 전체."""
    names = datasets()
    chosen = get_setting("analysis_datasets")
    if chosen is None:
        return names
    return [n for n in chosen if n in names]


def set_analysis_datasets(names: list[str]):
    set_setting("analysis_datasets", list(names))


def scope_key() -> str:
    return "|".join(sorted(analysis_datasets())) or "-"


def _in(names):
    return "(" + ",".join("?" * len(names)) + ")" if names else "(NULL)"


def norm(s) -> str:
    return "".join(str(s).lower().split()).replace("_", "").replace("·", "").replace("(", "").replace(")", "")


def signature(header: list) -> str:
    return hashlib.sha1("|".join(sorted(norm(h) for h in header)).encode()).hexdigest()[:16]


# ---------- 역할 찾기 ----------
def match_columns(header: list, role: str) -> dict:
    """역할의 표준 열 → 실제 열 이름. 정확히 같거나 별칭과 같으면 우선, 아니면 포함 관계로."""
    spec = ROLES[role]
    cols = {norm(h): h for h in header if h is not None and str(h).strip()}
    out = {}
    for canon, aliases in spec["columns"].items():
        names = [norm(canon), *(norm(a) for a in aliases)]
        hit = next((cols[n] for n in names if n in cols), None)
        if hit is None:
            hit = next((orig for key, orig in cols.items() for n in names if len(n) >= 3 and (n in key or key in n)), None)
        if hit is not None and hit not in out.values():
            out[canon] = hit
    return out


def detect_role(header: list, frame: pd.DataFrame | None = None) -> tuple[str | None, dict, float]:
    """가장 잘 맞는 역할. 필수 열이 모두 있어야 후보. 점수 = 맞은 열 비율."""
    best = (None, {}, 0.0)
    for role, spec in ROLES.items():
        if spec.get("detect") == "wide_numeric":
            continue
        m = match_columns(header, role)
        if not all(r in m for r in spec["required"]):
            continue
        score = len(m) / len(spec["columns"]) + len(spec["required"]) * 0.05
        if score > best[2]:
            best = (role, m, score)
    if best[0] is None and frame is not None:  # 기준월 + 숫자 열 여러 개 → 넓은 형태의 트렌드 지수
        month = match_columns(header, "search_trend").get("기준월")
        numeric = [c for c in frame.columns if c != month and pd.to_numeric(frame[c], errors="coerce").notna().mean() > 0.8]
        if month and len(numeric) >= 2:
            best = ("search_trend", {"기준월": month}, 0.5)
    return best


# ---------- 파일 읽기 ----------
def _frames_from_excel(raw: bytes) -> dict[str, pd.DataFrame]:
    out = {}
    for sheet, df in pd.read_excel(io.BytesIO(raw), sheet_name=None, header=None).items():
        df = df.dropna(how="all").dropna(axis=1, how="all")
        if df.empty:
            continue
        # 머리글 행 찾기: 앞 10행 중 글자 칸이 가장 많은 행
        head = max(range(min(10, len(df))), key=lambda i: df.iloc[i].map(lambda v: isinstance(v, str)).sum())
        body = df.iloc[head + 1:].copy()
        body.columns = [str(c).strip() if pd.notna(c) else f"열{i + 1}" for i, c in enumerate(df.iloc[head])]
        body["_row"] = body.index + 1
        out[sheet] = body.reset_index(drop=True)
    return out


def _read(name: str, raw: bytes):
    """(표 dict, 문서 텍스트)"""
    ext = Path(name).suffix.lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        frames = _frames_from_excel(raw)
        docs = []
        for sheet, df in list(frames.items()):
            role, _, _ = detect_role(list(df.columns), df)
            if role is None and len(df.columns) <= 4:  # 안내 시트 등은 문서로도 남긴다
                docs.append(f"[{sheet}]\n" + "\n".join(" | ".join(str(v) for v in r if pd.notna(v)) for r in df.drop(columns="_row").values))
        return frames, "\n\n".join(docs)
    if ext == ".csv":
        for enc in ("utf-8-sig", "cp949"):
            try:
                df = pd.read_csv(io.BytesIO(raw), encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        df["_row"] = df.index + 2
        return {"CSV": df}, ""
    if ext == ".docx":
        import docx
        d = docx.Document(io.BytesIO(raw))
        frames, lines = {}, [p.text for p in d.paragraphs if p.text.strip()]
        for i, t in enumerate(d.tables, 1):
            rows = [[c.text.strip() for c in r.cells] for r in t.rows]
            lines.append("\n".join(" | ".join(r) for r in rows))
            if len(rows) > 2:
                df = pd.DataFrame(rows[1:], columns=[c or f"열{j + 1}" for j, c in enumerate(rows[0])])
                for col in df.columns:  # 숫자로 읽히는 열만 숫자로
                    num = pd.to_numeric(df[col], errors="coerce")
                    if num.notna().all():
                        df[col] = num
                df["_row"] = range(2, len(df) + 2)
                frames[f"표{i}"] = df
        return frames, "\n".join(lines)
    if ext == ".pptx":
        from pptx import Presentation
        p = Presentation(io.BytesIO(raw))
        lines = []
        for i, s in enumerate(p.slides, 1):
            texts = [sh.text_frame.text for sh in s.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
            lines.append(f"[슬라이드 {i}] " + " / ".join(t.replace("\n", " ") for t in texts))
        return {}, "\n".join(lines)
    return {}, raw.decode("utf-8-sig", errors="replace")


def add_file(name: str, raw: bytes, dataset: str | None = None, source: str = "파일") -> dict:
    """파일 하나를 원본 그대로 저장하고 표마다 역할을 붙인다. 같은 묶음 안에 같은 내용 파일은 다시 저장하지 않는다."""
    dataset = dataset or active_dataset()
    sha = hashlib.sha256(raw).hexdigest()
    frames, text = _read(name, raw)
    return _save(name, sha, frames, text, dataset, source)


def _save(name, sha, frames, text, dataset, source):
    db = _connect()
    with db:
        if db.execute("SELECT 1 FROM files WHERE sha256=? AND dataset=?", (sha, dataset)).fetchone():
            db.execute("UPDATE files SET active=1 WHERE sha256=? AND dataset=?", (sha, dataset))
            return {"file": name, "status": "이 묶음에 이미 같은 내용이 있음", "tables": []}
        fid = hashlib.sha1(f"{dataset}|{sha}".encode()).hexdigest()[:12]
        db.execute("INSERT INTO files(file_id, name, sha256, added, active, dataset, source) VALUES(?,?,?,?,1,?,?)",
                   (fid, name, sha, datetime.now().strftime("%Y-%m-%d %H:%M"), dataset, source))
        saved_maps = {s: (r, json.loads(m)) for s, r, m in db.execute("SELECT signature, role, mapping FROM mappings")}
        report = []
        for sheet, df in frames.items():
            header = [c for c in df.columns if c != "_row"]
            sig = signature(header)
            if sig in saved_maps:
                role, mapping = saved_maps[sig]
                how = "저장된 매핑"
            else:
                role, mapping, _ = detect_role(header, df)
                how = "자동 인식" if role else ("안내(문서로 저장)" if len(header) <= 4 and text.strip() else "미분류")
            db.execute("INSERT INTO tables VALUES(?,?,?,?,?,?,?,?,?)",
                       (f"{fid}:{sheet}", fid, sheet, json.dumps(header, ensure_ascii=False), sig, role,
                        json.dumps(mapping, ensure_ascii=False), df.to_json(orient="records", force_ascii=False, date_format="iso"), how))
            report.append({"시트": sheet, "행": len(df), "역할": ROLES[role]["label"] if role else how, "방식": how})
        if text.strip():
            db.execute("INSERT INTO documents VALUES(?,?,?,?)", (f"{fid}:doc", fid, name, text))
    return {"file": name, "status": "등록", "tables": report, "has_text": bool(text.strip())}


def set_mapping(table_id: str, role: str | None, mapping: dict, remember: bool = True):
    db = _connect()
    with db:
        sig = db.execute("SELECT signature FROM tables WHERE table_id=?", (table_id,)).fetchone()[0]
        db.execute("UPDATE tables SET role=?, mapping=?, how=? WHERE table_id=?",
                   (role, json.dumps(mapping, ensure_ascii=False), "직접 지정", table_id))
        if remember and role:
            db.execute("INSERT OR REPLACE INTO mappings VALUES(?,?,?,?)",
                       (sig, role, json.dumps(mapping, ensure_ascii=False), datetime.now().strftime("%Y-%m-%d %H:%M")))
            db.execute("UPDATE tables SET role=?, mapping=?, how=? WHERE signature=? AND how='미분류'",
                       (role, json.dumps(mapping, ensure_ascii=False), "저장된 매핑", sig))


def suggest_mapping(table_id: str, llm) -> dict:
    """AI가 머리글과 앞 3행을 보고 역할·열 짝을 제안(사람이 확인 후 저장)."""
    db = _connect()
    header, rows = db.execute("SELECT header, rows FROM tables WHERE table_id=?", (table_id,)).fetchone()
    header, sample = json.loads(header), json.loads(rows)[:3]
    roles = {k: {"설명": v["label"], "열": list(v["columns"])} for k, v in ROLES.items()}
    schema = {"type": "object", "additionalProperties": False, "required": ["role", "pairs"],
              "properties": {"role": {"type": "string", "enum": [*ROLES, "none"]},
                             "pairs": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                                  "required": ["standard", "actual"],
                                                                  "properties": {"standard": {"type": "string"},
                                                                                 "actual": {"type": "string", "enum": header}}}}}}
    res = llm.ask_json("음료 회사 데이터 담당자입니다. 표의 머리글과 예시 행을 보고 가장 맞는 자료 역할과 표준 열 짝을 고르세요. "
                       "맞는 역할이 없으면 none. 확실하지 않은 열은 짝짓지 마세요.",
                       json.dumps({"역할 목록": roles, "머리글": header, "예시 행": sample}, ensure_ascii=False, default=str),
                       schema, lambda: {"role": "none", "pairs": []}, tag="map-v1")
    role = None if res["role"] == "none" else res["role"]
    valid = ROLES.get(role, {}).get("columns", {})
    return {"role": role, "mapping": {p["standard"]: p["actual"] for p in res["pairs"] if p["standard"] in valid}}


def deactivate(file_id: str):
    db = _connect()
    with db:
        db.execute("UPDATE files SET active=0 WHERE file_id=?", (file_id,))


# ---------- 꺼내 쓰기 ----------
def catalog() -> pd.DataFrame:
    db = _connect()
    names = analysis_datasets()
    q = ("SELECT f.file_id, f.dataset, f.name, f.added, f.active, f.source, t.table_id, t.sheet, t.role, t.how, t.header "
         f"FROM files f LEFT JOIN tables t USING(file_id) WHERE f.dataset IN {_in(names)} ORDER BY f.added DESC")
    return pd.read_sql(q, db, params=tuple(names))


def table(role: str) -> pd.DataFrame:
    """역할이 같은 표를 모두 합쳐 표준 열 이름으로 돌려준다(원본 값 그대로). 출처 열 _file, _sheet, _row 포함."""
    db = _connect()
    parts = []
    for fname, sheet, mapping, rows, ds in db.execute(
            "SELECT f.name, t.sheet, t.mapping, t.rows, f.dataset FROM tables t JOIN files f USING(file_id) "
            f"WHERE t.role=? AND f.active=1 AND f.dataset IN {_in(analysis_datasets())} ORDER BY f.added", (role, *analysis_datasets())):
        df = pd.read_json(io.StringIO(rows), orient="records", dtype=False)
        mapping = json.loads(mapping or "{}")
        df = df.rename(columns={v: k for k, v in mapping.items()})
        df["_file"], df["_sheet"], df["_dataset"] = fname, sheet, ds
        parts.append(df)
    out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if not out.empty:  # 짝짓지 못한 표준 열은 빈 열로 채워, 열이 없어서 멈추는 일이 없게 한다
        for canon in ROLES[role]["columns"]:
            if canon not in out:
                out[canon] = None
    return out


def documents() -> list[dict]:
    db = _connect()
    return [{"name": n, "text": t} for n, t in db.execute(
        f"SELECT d.name, d.text FROM documents d JOIN files f USING(file_id) WHERE f.active=1 AND f.dataset IN {_in(analysis_datasets())}",
        tuple(analysis_datasets()))]


def version() -> str:
    db = _connect()
    names = analysis_datasets()
    shas = [s for s, in db.execute(f"SELECT sha256 FROM files WHERE active=1 AND dataset IN {_in(names)} ORDER BY sha256", tuple(names))]
    rows = db.execute("SELECT GROUP_CONCAT(role || ':' || IFNULL(mapping,'')) FROM tables JOIN files USING(file_id) "
                      f"WHERE active=1 AND dataset IN {_in(names)}", tuple(names)).fetchone()[0] or ""
    return hashlib.sha256(("".join(shas) + rows).encode()).hexdigest()[:12] if shas else "자료 없음"


# ---------- 기존 DB 연결 ----------
def db_tables(url: str) -> list[str]:
    """연결 문자열의 표 목록. sqlite:///경로 는 기본 기능, 그 밖(PostgreSQL·MySQL·SQL Server 등)은 SQLAlchemy+드라이버 필요."""
    if url.startswith("sqlite:///"):
        with sqlite3.connect(url[len("sqlite:///"):]) as con:
            return [n for n, in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') ORDER BY name")]
    from sqlalchemy import create_engine, inspect
    insp = inspect(create_engine(url))
    return insp.get_table_names() + insp.get_view_names()


def _read_db(url: str, table_name: str, limit: int | None = None) -> pd.DataFrame:
    q = f'SELECT * FROM "{table_name}"' + (f" LIMIT {int(limit)}" if limit else "")
    if url.startswith("sqlite:///"):
        with sqlite3.connect(url[len("sqlite:///"):]) as con:
            return pd.read_sql(q, con)
    from sqlalchemy import create_engine, text
    with create_engine(url).connect() as con:
        return pd.read_sql(text(q), con)


def mask_url(url: str) -> str:
    import re
    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:****@", url)


def add_db(url: str, tables: list[str], dataset: str | None = None) -> list[dict]:
    """DB 표를 읽어 지금 시점 사본으로 저장(원본 DB는 건드리지 않음). 같은 표를 다시 가져오면 새 사본으로 바꾼다."""
    dataset = dataset or active_dataset()
    out = []
    for name in tables:
        df = _read_db(url, name)
        df["_row"] = range(1, len(df) + 1)
        sha = hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()
        label = f"DB {mask_url(url)} › {name}"
        db = _connect()
        with db:  # 같은 표의 이전 사본은 분석에서 제외(보관)
            db.execute("UPDATE files SET active=0 WHERE name=? AND dataset=? AND source='DB'", (label, dataset))
        out.append(_save(label, sha, {name: df}, "", dataset, "DB"))
    remember = get_setting("db_links", {})
    remember.setdefault(dataset, {})[mask_url(url)] = sorted(set(remember.get(dataset, {}).get(mask_url(url), [])) | set(tables))
    set_setting("db_links", remember)
    return out


# ---------- 묶음 내용 요약(파일·시트 대신 '무엇이 들어 있나') ----------
def summary() -> list[dict]:
    rows = []
    for role, spec in ROLES.items():
        df = table(role)
        if df.empty:
            continue
        files = ", ".join(sorted(df["_file"].astype(str).unique()))[:80]
        if "_dataset" in df and df["_dataset"].nunique() > 1:
            files = "묶음 " + ", ".join(sorted(df["_dataset"].unique())) + " · " + files
        info = f"{len(df):,}행"
        months = None
        for col in ("기준월", "응답일시", "일시", "촬영일"):
            if col in df and df[col].notna().any():
                v = df[col].dropna().astype(str).str[:7]
                months = f"{v.min()} ~ {v.max()}"
                break
        extra = []
        if role == "pos":
            extra.append(f"제품 {df['제품코드'].nunique()}개 · 채널 {df['판매채널'].nunique()}개")
        elif role == "respondents":
            extra.append(f"응답자 {df['응답자ID'].nunique()}명")
        elif role == "concept_eval":
            extra.append("컨셉: " + ", ".join(df["컨셉"].astype(str).unique()[:5]))
        elif role == "assets":
            st = df["상태"].astype(str).value_counts()
            extra.append(" · ".join(f"{k} {v}" for k, v in st.items()))
        elif role == "search_trend":
            extra.append("키워드: " + ", ".join(c for c in df.columns if c != "기준월" and not str(c).startswith("_") and df[c].notna().any())[:60])
        elif role in ("sns", "related_search"):
            extra.append("키워드: " + ", ".join(df["키워드"].astype(str).unique()[:6]))
        elif role == "concept_history":
            extra.append("제품: " + ", ".join(df["제품"].astype(str).unique()[:5]))
        rows.append({"자료": spec["label"], "규모": info, "기간": months or "-", "내용": " / ".join(extra) or "-", "출처": files})
    docs = documents()
    if docs:
        rows.append({"자료": "문서(텍스트)", "규모": f"{len(docs)}개", "기간": "-", "내용": ", ".join(d["name"] for d in docs)[:80], "출처": "-"})
    return rows


# ---------- 짝짓기 도우미: 열 이름 + 값 모양으로 추측 ----------
def sample(table_id: str, n: int = 200) -> pd.DataFrame:
    rows = _connect().execute("SELECT rows FROM tables WHERE table_id=?", (table_id,)).fetchone()[0]
    return pd.read_json(io.StringIO(rows), orient="records", dtype=False).head(n)


def guess_mapping(df: pd.DataFrame, role: str) -> dict:
    """표준 열 → 실제 열. 1) 열 이름 2) 값 모양(월 형식·코드·숫자 크기) 순서로 채운다."""
    import re
    cols = [c for c in df.columns if c != "_row"]
    m = match_columns(cols, role)
    used = set(m.values())
    canon = list(ROLES[role]["columns"])
    left = [c for c in cols if c not in used]

    def kind(c):
        s = df[c].dropna().astype(str).head(50)
        if s.empty:
            return "empty"
        if s.str.match(r"^(19|20)\d{2}([-/.](0[1-9]|1[0-2])|(0[1-9]|1[0-2])$)").mean() > 0.8:  # 2024-10, 2024/10, 202410
            return "month"
        num = pd.to_numeric(df[c], errors="coerce")
        if num.notna().mean() > 0.8:
            return "number"
        if s.str.match(r"^[A-Za-z]{1,4}[-_]?\d{1,6}$").mean() > 0.8:
            return "code"
        return "text"

    # 열 이름으로 짝지은 것 중 값 모양이 안 맞는 것은 버린다(예: 숫자 열 'units'를 '수량단위'로)
    def expects(k):
        if re.search("단위|구분|명$|채널|권역|상태|사유", k):  # '수량단위'처럼 글자 항목을 먼저 본다
            return "text"
        if re.search("수량|금액|매출|가격|횟수|비중|율|점수|기온|시간\\(초\\)|TOP2|계수", k):
            return "number"
        return None
    for k, c in list(m.items()):
        e, got = expects(k), kind(c)
        if (e == "number" and got not in ("number", "empty")) or (e == "text" and got == "number"):
            del m[k]
    left = [c for c in cols if c not in set(m.values())]
    kinds = {c: kind(c) for c in left}
    want = [k for k in canon if k not in m]
    for c in [c for c in left if kinds[c] == "month"]:
        t = next((k for k in want if re.search("월|일|기간", k)), None)
        if t:
            m[t] = c; want.remove(t)
    for c in [c for c in left if kinds[c] == "code"]:
        t = next((k for k in want if re.search("코드|ID", k)), None)
        if t:
            m[t] = c; want.remove(t)
    nums = sorted([c for c in left if kinds[c] == "number"], key=lambda c: -pd.to_numeric(df[c], errors="coerce").median())
    money = [k for k in want if re.search("금액|매출|가격|비용", k)]
    qty = [k for k in want if re.search("수량|량|횟수|건", k)]
    for c in nums:
        if money:
            m[money.pop(0)] = c
        elif qty:
            m[qty.pop(0)] = c
    return m


def guess_role(df: pd.DataFrame) -> str | None:
    """필수 열이 모두 채워지는 역할 중 가장 많이 채워지는 것."""
    best, score = None, 0
    for role, spec in ROLES.items():
        if spec.get("detect") == "wide_numeric":
            continue
        m = guess_mapping(df, role)
        if all(r in m for r in spec["required"]) and len(m) > score:
            best, score = role, len(m)
    return best
