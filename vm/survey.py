"""설문 재현 검증: KREI 식품소비행태조사와 같은 질문을 페르소나에게 묻고 실제 분포와 비교한다.

평가 규칙 (실행 전에 고정 — 결과를 보고 바꾸지 않는다)
- 설정 선택 지표(주): fav_mae = 연령대별 '가장 좋아하는 음료 1순위' 분포 MAE(%p)의 연령대 평균
    → 가장 작은 조건을 기본 설정으로 채택. 차이가 0.3%p 미만이면 four_rate_mae가 작은 쪽.
- 보조 지표: four_rate_mae = 연령대별 '탄산·이온 4종을 1순위로 꼽은 비율' MAE(%p)
             four_age_corr = 그 비율의 연령 방향(실제와의 상관계수)
- 검증 지표(설정 선택에 쓰지 않음): zero_mae = 연령대별 제로 음료 섭취 빈도 분포 MAE(%p), 2025년 기준
- 참고선: 실제 조사끼리 연도를 바꿔 비교한 fav_mae (1.2~1.8%p) — 조사 자체의 흔들림

예시:
    python -m vm.survey --n-per-age 10 --mock
    python -m vm.survey --n-per-age 10                    # 5개 연령대 × 10명 × 조건 5개
    python -m vm.survey --n-per-age 20 --only base balanced
"""
import argparse
import hashlib
import json
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd

from .agent import SYSTEM, persona_profile, persona_profile_full
from .config import OUT_DIR
from .experiments import SYSTEM_BALANCED, SYSTEM_NO_ANTIBIAS, make_habit_profile
from .llm import LLM
from .personas import load_pool
from .reference import AGE_BUCKETS, FAV_GROUPS, FOUR, ZERO_LEVELS, fav_group, load_reference, mae

# KREI 2025 성인가구원 설문 A15 보기 (문구 그대로)
FAV_OPTIONS = [
    "100% 과일 주스(델몬트 오렌지, 콜드 등)", "저과즙음료(피크닉, 미닛메이드, 카프리썬, 코코팜 등)", "흰우유",
    "가공우유(초콜릿맛, 바나나맛 우유 등)", "발효유(불가리스, 야쿠르트, 요플레 등)", "두유, 아몬드유(베지밀, 순두유 등)",
    "가당 탄산음료(콜라, 사이다, 써니텐 류)", "무가당·대체당 탄산음료(제로콜라, 제로사이다 등)",
    "이온음료(게토레이, 포카리스웨트 등)", "녹차, 곡물차(녹차티백, 녹차잎차, 보리차, 옥수수차, 콤부차 등)",
    "기능성 음료(비타500, 컨디션, 핫식스, 단백질 음료 등)", "탄산수", "인스턴트 커피(원두, 캔커피, 캡슐커피 등)",
    "커피전문점 커피(카페, 베이커리 등에서 판매하는 커피)", "음료전문점 제조 음료(버블티, 과일주스, 에이드 등)",
    "기타", "물 이외의 음료는 마시지 않음",
]
OPT_NUMS = [str(i) for i in range(1, len(FAV_OPTIONS) + 1)]

SURVEY_TEXT = (
    "[설문]\n아래는 식품 소비에 관한 설문입니다. 이 사람으로서 평소 생활대로 답하세요.\n\n"
    "Q1. 평소 가장 좋아하는 음료를 1순위부터 3순위까지 번호로 고르세요. "
    "(물 이외의 음료를 마시지 않으면 1순위에 17번, 2·3순위는 0)\n"
    + "\n".join(f"  {i}. {o}" for i, o in enumerate(FAV_OPTIONS, 1)) +
    "\n\nQ2. 제로 음료(제로콜라, 제로사이다 등 설탕 대신 대체당을 쓴 음료)를 얼마나 자주 드십니까?\n"
    + "\n".join(f"  - {z}" for z in ZERO_LEVELS)
)

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["fav1", "fav2", "fav3", "zero_drink"],
    "properties": {
        "fav1": {"type": "string", "enum": OPT_NUMS},
        "fav2": {"type": "string", "enum": OPT_NUMS + ["0"]},
        "fav3": {"type": "string", "enum": OPT_NUMS + ["0"]},
        "zero_drink": {"type": "string", "enum": ZERO_LEVELS},
    },
}


def make_conditions(llm) -> dict:
    """설문에는 진열대가 없으므로 지시문과 프로필 범위만 바꾼다."""
    return {
        "base": {"system": SYSTEM, "profile_fn": persona_profile},
        "no_antibias": {"system": SYSTEM_NO_ANTIBIAS, "profile_fn": persona_profile},
        "balanced": {"system": SYSTEM_BALANCED, "profile_fn": persona_profile},
        "full_persona": {"system": SYSTEM, "profile_fn": persona_profile_full},
        "habit_first": {"system": SYSTEM_BALANCED, "profile_fn": make_habit_profile(llm)},
    }


def stratified_panel(pool: pd.DataFrame, n_per_age: int, seed: int) -> pd.DataFrame:
    """연령대마다 같은 인원을 뽑는다(비교는 연령대 안에서 하므로)."""
    parts = []
    for age in AGE_BUCKETS:
        g = pool[pool["age_group"] == age]
        parts.append(g.sample(n=n_per_age, random_state=seed))
    return pd.concat(parts, ignore_index=True)


def mock_answer(p: dict) -> dict:
    rng = random.Random(hashlib.sha1(f"survey|{p['uuid']}".encode()).hexdigest())
    picks = rng.sample(OPT_NUMS[:16], 3)
    return {"fav1": picks[0], "fav2": picks[1], "fav3": picks[2], "zero_drink": rng.choice(ZERO_LEVELS)}


def ask_all(llm, panel: pd.DataFrame, system: str, profile_fn, tag: str, workers: int = 8) -> pd.DataFrame:
    recs = panel.to_dict("records")
    rows = [None] * len(recs)

    def one(i):
        p = recs[i]
        base = {"uuid": p["uuid"], "age": p["age"], "age_group": p["age_group"], "sex": p["sex"]}
        try:
            user = f"[나의 프로필]\n{profile_fn(p)}\n\n{SURVEY_TEXT}"
            out = llm.ask_json(system, user, SCHEMA, mock_fn=lambda: mock_answer(p), tag=f"survey|{tag}")
        except Exception as e:
            return i, {**base, "error": f"{type(e).__name__}: {e}"[:300]}
        fav1 = FAV_OPTIONS[int(out["fav1"]) - 1]
        return i, {**base, "fav1": fav1, "fav1_group": fav_group(fav1),
                   "fav2": out["fav2"], "fav3": out["fav3"], "zero_drink": out["zero_drink"], "error": ""}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for done, fut in enumerate(as_completed([ex.submit(one, i) for i in range(len(recs))]), 1):
            i, row = fut.result()
            rows[i] = row
            if done % 25 == 0 or done == len(recs):
                print(f"진행 {done}/{len(recs)}", flush=True)
    return pd.DataFrame(rows)


def sim_dist(df: pd.DataFrame, col: str, levels: list) -> dict:
    ok = df[df["error"] == ""]
    out = {}
    for age in AGE_BUCKETS:
        s = ok[ok["age_group"] == age][col].value_counts(normalize=True)
        out[age] = {lv: float(s.get(lv, 0)) for lv in levels}
    return out


def evaluate(df: pd.DataFrame, ref: dict) -> dict:
    fav = sim_dist(df, "fav1_group", FAV_GROUPS)
    zero = sim_dist(df, "zero_drink", ZERO_LEVELS)
    real_four = [sum(ref["fav1_by_age"][a][g] for g in FOUR) * 100 for a in AGE_BUCKETS]
    sim_four = [sum(fav[a][g] for g in FOUR) * 100 for a in AGE_BUCKETS]
    corr = pd.Series(sim_four).corr(pd.Series(real_four)) if pd.Series(sim_four).std() > 0 else float("nan")
    return {
        "n_ok": int((df["error"] == "").sum()),
        "fav_mae": round(mae(fav, ref["fav1_by_age"]), 2),
        "four_rate_mae": round(sum(abs(s - r) for s, r in zip(sim_four, real_four)) / len(AGE_BUCKETS), 2),
        "four_age_corr": round(float(corr), 2),
        "zero_mae(검증)": round(mae(zero, ref["zero_drink_by_age_2025"]), 2) if ref.get("zero_drink_by_age_2025") else None,
        **{f"four_{a}": round(v, 1) for a, v in zip(AGE_BUCKETS, sim_four)},
        "coffee_share": round(sum(fav[a]["커피"] * ref["age_share"][a] for a in AGE_BUCKETS) * 100, 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-per-age", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--model")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    ref = load_reference()
    panel = stratified_panel(load_pool(), a.n_per_age, a.seed)
    llm = LLM(a.model, mock=a.mock)
    conds = make_conditions(llm)
    names = a.only or list(conds)
    out_dir = OUT_DIR / f"survey_{datetime.now():%Y%m%d_%H%M%S}{'_mock' if a.mock else ''}"
    out_dir.mkdir(parents=True)

    rows = []
    for name in names:
        print(f"\n=== {name} ===")
        df = ask_all(llm, panel, tag=name, workers=a.workers, **conds[name])
        df.to_csv(out_dir / f"responses_{name}.csv", index=False, encoding="utf-8-sig")
        rows.append({"condition": name, **evaluate(df, ref)})

    real = {"condition": "실제(KREI)", "fav_mae": 0.0, "four_rate_mae": 0.0, "four_age_corr": 1.0,
            **{f"four_{a}": round(sum(ref["fav1_by_age"][a][g] for g in FOUR) * 100, 1) for a in AGE_BUCKETS},
            "coffee_share": round(sum(ref["fav1_by_age"][a]["커피"] * ref["age_share"][a] for a in AGE_BUCKETS) * 100, 1)}
    # 무작위 기준선: 17개 보기(물만 제외 16개)를 균등하게 고른다고 가정했을 때의 오차
    uni_fav = {g: 0.0 for g in FAV_GROUPS}
    for o in FAV_OPTIONS[:16]:
        uni_fav[fav_group(o)] += 1 / 16
    uni = {a: dict(uni_fav) for a in AGE_BUCKETS}
    uni_four = sum(uni_fav[g] for g in FOUR) * 100
    rand = {"condition": "무작위 기준선", "fav_mae": round(mae(uni, ref["fav1_by_age"]), 2),
            "four_rate_mae": round(sum(abs(uni_four - sum(ref["fav1_by_age"][a][g] for g in FOUR) * 100)
                                       for a in AGE_BUCKETS) / len(AGE_BUCKETS), 2),
            "zero_mae(검증)": round(mae({a: {z: 1 / len(ZERO_LEVELS) for z in ZERO_LEVELS} for a in AGE_BUCKETS},
                                      ref["zero_drink_by_age_2025"]), 2)}
    table = pd.DataFrame(rows + [rand, real]).set_index("condition")
    table.to_csv(out_dir / "comparison.csv", encoding="utf-8-sig")
    (out_dir / "meta.json").write_text(json.dumps(
        {"n_per_age": a.n_per_age, "seed": a.seed, "model": "mock" if a.mock else llm.model, "conditions": names,
         "reference_year_to_year_fav_mae": ref["year_to_year_fav1_mae"]}, ensure_ascii=False, indent=2), encoding="utf-8")

    pd.set_option("display.width", 200)
    print("\n\n[설문 재현 비교]  fav_mae/four_rate_mae/zero_mae: 실제와의 오차(%p, 작을수록 좋음)")
    print(table.T.to_string())
    print(f"\n참고선(실제 조사끼리 연도 비교 fav_mae): {ref['year_to_year_fav1_mae']}")
    best = table.drop(index=["실제(KREI)", "무작위 기준선"]).sort_values(["fav_mae", "four_rate_mae"]).index[0]
    print(f"사전 규칙에 따른 선택(fav_mae 최소): {best}")
    print(f"새 응답 {llm.api_calls}개, 캐시 재사용 {llm.cache_hits}개\n저장: {out_dir}")


if __name__ == "__main__":
    main()
