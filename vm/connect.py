"""데이터 연결: 받은 표(CSV/엑셀)를 열만 지정해 바로 쓰게 한다.

1) 설문 문항 검증: 응답자별 데이터(나이·응답·[성별]·[가중치]) → 같은 질문을 페르소나에게 '100명 분포'로 묻고
   연령대별 실제 분포와 비교(MAE, 무작위 기준선). KREI로 했던 검증을 어떤 설문에든 적용하는 일반형.
2) 패널 구성 맞추기: 실제 고객의 연령(·성별) 구성 → 페르소나 패널을 그 비율대로 뽑는다(할당 추출).

원칙: LLM은 판단만, 분포는 실데이터로. 개인 단위 데이터는 외부(LLM)로 보내지 않고 집계 분포만 쓴다.
"""
import hashlib
import json
import random
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import pandas as pd

from .agent import persona_profile
from .config import OUT_DIR

AGE_BUCKETS = ["20대 이하", "30대", "40대", "50대", "60대 이상"]
MAX_OPTIONS = 20


# ------------------------------------------------------------------ 읽기·정리
def load_table(file) -> pd.DataFrame:
    """CSV(utf-8/cp949) 또는 엑셀 첫 시트. file은 경로나 업로드 객체."""
    name = getattr(file, "name", str(file)).lower()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(file)
    raw = file.read() if hasattr(file, "read") else Path(file).read_bytes()
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            from io import BytesIO
            return pd.read_csv(BytesIO(raw), encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("파일 인코딩을 읽을 수 없습니다(utf-8 또는 cp949로 저장해 주세요).")


def to_age_bucket(v) -> str | None:
    """나이 숫자(34), '30대', '만 30~39세', '30-39' 등을 연령대로."""
    if pd.isna(v):
        return None
    m = re.search(r"(\d{1,3})", str(v))
    if not m:
        return None
    age = int(m.group(1))
    if age < 30:
        return "20대 이하"
    if age >= 60:
        return "60대 이상"
    return f"{age // 10 * 10}대"


def to_sex(v) -> str | None:
    t = str(v)
    if any(k in t for k in ["남", "M", "m", "1"]) and "여" not in t:
        return "남자"
    if any(k in t for k in ["여", "F", "f", "2"]):
        return "여자"
    return None


def answer_options(df: pd.DataFrame, col: str, top: int = MAX_OPTIONS) -> list[str]:
    vc = df[col].dropna().astype(str).str.strip().value_counts()
    return list(vc.index[:top])


def reference_dist(df: pd.DataFrame, age_col: str, answer_col: str, options: list[str],
                   weight_col: str | None = None) -> dict:
    """연령대별 실제 응답 분포 {연령대: {보기: 비율}} 와 연령대 표본 수."""
    d = pd.DataFrame({"age": df[age_col].map(to_age_bucket), "ans": df[answer_col].astype(str).str.strip(),
                      "w": pd.to_numeric(df[weight_col], errors="coerce") if weight_col else 1.0}).dropna()
    d = d[d["ans"].isin(options)]
    dist, n = {}, {}
    for a in AGE_BUCKETS:
        g = d[d["age"] == a]
        n[a] = int(len(g))
        s = g.groupby("ans")["w"].sum()
        dist[a] = {o: float(s.get(o, 0) / s.sum()) if s.sum() > 0 else 0.0 for o in options}
    return {"dist": dist, "n": n}


def composition(df: pd.DataFrame, age_col: str, sex_col: str | None = None, weight_col: str | None = None) -> dict:
    """실제 고객 구성 {('30대','여자'): 비율} — 패널 할당 추출용."""
    d = pd.DataFrame({"age": df[age_col].map(to_age_bucket),
                      "sex": df[sex_col].map(to_sex) if sex_col else "전체",
                      "w": pd.to_numeric(df[weight_col], errors="coerce") if weight_col else 1.0}).dropna()
    s = d.groupby(["age", "sex"])["w"].sum()
    return {f"{a}|{x}": float(v / s.sum()) for (a, x), v in s.items()}


def quota_panel(pool: pd.DataFrame, n: int, comp: dict, seed: int = 42) -> pd.DataFrame:
    """구성 비율대로 페르소나를 뽑는다(반올림 오차는 큰 칸부터 보정)."""
    want = {k: v * n for k, v in comp.items()}
    take = {k: int(v) for k, v in want.items()}
    for k in sorted(want, key=lambda k: want[k] - take[k], reverse=True)[: n - sum(take.values())]:
        take[k] += 1
    parts = []
    for k, m in take.items():
        if m <= 0:
            continue
        age, sex = k.split("|")
        g = pool[pool["age_group"] == age]
        if sex != "전체":
            g = g[g["sex"] == sex]
        parts.append(g.sample(n=min(m, len(g)), random_state=seed))
    return pd.concat(parts, ignore_index=True) if parts else pool.sample(n=n, random_state=seed)


# ------------------------------------------------------------------ 페르소나에게 같은 질문
def _schema(k):
    keys = [str(i) for i in range(1, k + 1)]
    return {"type": "object", "additionalProperties": False, "required": ["counts"],
            "properties": {"counts": {"type": "object", "additionalProperties": False, "required": keys,
                                      "properties": {x: {"type": "integer"} for x in keys}}}}


SYSTEM = """당신은 아래 프로필을 가진 실제 한국 소비자입니다. 이 사람의 생활·식습관·가격 감각에 근거해 판단하세요.
- 새롭거나 바람직해 보이는 답으로 쏠리지 말고, 나이·성별 고정관념이 아니라 프로필의 구체적인 생활에 근거하세요."""


def ask_question(llm, panel: pd.DataFrame, question: str, options: list[str], workers: int = 8, progress=None) -> pd.DataFrame:
    """각 페르소나에게 '비슷한 사람 100명이 어떻게 답할지'를 묻는다(설문 재현 검증에서 채택한 방식)."""
    k = len(options)
    text = (f"이 프로필과 나이·성별·생활이 비슷한 사람 100명이 아래 설문에 답한다고 생각하세요. "
            f"같은 조건이어도 사람마다 다릅니다. 100명이 각 보기를 고를 인원을 현실적으로 추정하세요(합계 100).\n\n"
            f"[질문] {question}\n" + "\n".join(f"  {i}. {o}" for i, o in enumerate(options, 1)))
    recs = panel.to_dict("records")
    rows = [None] * len(recs)

    def one(i):
        p = recs[i]
        rng = random.Random(hashlib.sha1(f"connect|{p['uuid']}".encode()).hexdigest())
        try:
            out = llm.ask_json(SYSTEM, f"[프로필]\n{persona_profile(p)}\n\n{text}", _schema(k), tag="connect",
                               mock_fn=lambda: {"counts": {str(j): rng.randint(0, 30) for j in range(1, k + 1)}})
            c = {o: max(0, int(out["counts"].get(str(j), 0))) for j, o in enumerate(options, 1)}
            tot = sum(c.values()) or 1
            return i, {"uuid": p["uuid"], "age_group": p["age_group"], "sex": p["sex"], "error": "",
                       **{f"p|{o}": v / tot for o, v in c.items()}}
        except Exception as e:
            return i, {"uuid": p["uuid"], "age_group": p["age_group"], "sex": p["sex"], "error": f"{type(e).__name__}: {e}"[:200]}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for done, fut in enumerate(as_completed([ex.submit(one, i) for i in range(len(recs))]), 1):
            i, row = fut.result()
            rows[i] = row
            if progress:
                progress(done, len(recs))
    return pd.DataFrame(rows)


def compare(sim: pd.DataFrame, ref: dict, options: list[str]) -> dict:
    ok = sim[sim["error"] == ""]
    sdist = {a: {o: float(ok[ok["age_group"] == a][f"p|{o}"].mean()) if (ok["age_group"] == a).any() else float("nan")
                 for o in options} for a in AGE_BUCKETS}
    ages = [a for a in AGE_BUCKETS if ref["n"][a] > 0 and not pd.isna(next(iter(sdist[a].values())))]
    mae = lambda d: sum(sum(abs(d[a][o] - ref["dist"][a][o]) for o in options) / len(options) * 100 for a in ages) / max(len(ages), 1)
    uniform = {a: {o: 1 / len(options) for o in options} for a in AGE_BUCKETS}
    table = pd.DataFrame([{"연령대": a, "보기": o, "실제(%)": round(ref["dist"][a][o] * 100, 1),
                           "페르소나(%)": round(sdist[a][o] * 100, 1)} for a in ages for o in options])
    return {"mae": round(mae(sdist), 2), "random_mae": round(mae(uniform), 2), "ages": ages,
            "n_ok": int(len(ok)), "table": table}


def save_result(question: str, options: list[str], res: dict, meta: dict) -> Path:
    out = OUT_DIR / f"connect_{datetime.now():%Y%m%d_%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    res["table"].to_csv(out / "comparison_by_age.csv", index=False, encoding="utf-8-sig")
    (out / "result.json").write_text(json.dumps({"question": question, "options": options, "mae": res["mae"],
                                                 "random_mae": res["random_mae"], "ages": res["ages"], "n_ok": res["n_ok"],
                                                 **meta}, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
