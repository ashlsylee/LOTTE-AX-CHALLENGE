"""대조실험: 같은 패널(같은 seed)에 조건 하나씩만 바꿔 묻고 결과를 비교한다.

첫 실행에서 레몬 탄산수 79% 쏠림이 나와 원인 가설을 하나씩 분리하기 위해 만들었다.
    base           : 현재 설정 (기준)
    no_antibias    : 반편향 지시문 제거             → 가설① 지시문 과잉 교정
    neutral_desc   : 제품 설명을 맛·종류만 남김     → 가설② '무가당·제로' 같은 건강 단어
    equal_price    : 모든 제품 같은 가격            → 가격 효과 분리
    neutral_situ   : 상황을 중립적으로             → 가설③ "목이 조금 마름" 유도
    full_persona   : 페르소나 서술 전체 사용        → 가설④ 페르소나 정보 부족

예시:
    python -m vm.experiments --n 100                       # 전체 조건
    python -m vm.experiments --n 30 --only base full_persona   # 일부만, 적은 인원
    python -m vm.experiments --n 100 --mock                # API 없이 시험

2차 후보 (30명 결과를 보고 추가):
    balanced          : 가격·새로움 어느 쪽으로도 치우치지 않게 다시 쓴 지시문
    balanced_neutral  : balanced + 중립 상황
    habit_first       : balanced_neutral + 프로필에서 음료 습관을 먼저 추정해 붙임(2단계)
    python -m vm.experiments --n 30 --only base balanced balanced_neutral habit_first
"""
import argparse
import copy
import json
import math
import re
from datetime import datetime

import pandas as pd

import hashlib
import random

from .agent import SYSTEM, persona_profile, persona_profile_full
from .config import OUT_DIR
from .llm import LLM
from .personas import load_pool, sample_panel
from .simulate import load_scenario, run, shares_of

SYSTEM_NO_ANTIBIAS = """당신은 아래 프로필을 가진 실제 한국 소비자입니다. 이 사람으로서 판단하세요.
- 답은 이 사람의 말투로, 짧고 구체적으로 쓰세요."""

# 30명 실험 결과: 반편향 지시문을 빼면 신제품 선택이 0%→47%로 튀고(새것 선호 편향),
# 넣으면 가장 싼 제품으로 쏠렸다. 가격·새로움 어느 쪽으로도 치우치지 않게 다시 쓴 지시문.
SYSTEM_BALANCED = """당신은 아래 프로필을 가진 실제 한국 소비자입니다. 이 사람의 생활, 식습관, 취향을 바탕으로 판단하세요.
- 새로운 제품이라는 이유만으로 더 좋게도, 더 나쁘게도 보지 마세요.
- 가격은 이 사람의 형편과 습관에 맞게 고려하되, 몇백 원 차이를 과하게 따지지는 마세요.
- 아무것도 사지 않는 것도 정상적인 선택입니다.
- 이유에는 이 사람의 생활에서 나온 구체적인 근거를 넣으세요.
- 답은 이 사람의 말투로, 짧게 쓰세요."""

NEUTRAL_SITUATION = "편의점에서 마실 음료를 하나 고르려고 합니다. 사지 않고 그냥 나가도 됩니다."

# 제품 설명에서 맛·종류만 남긴 버전 (건강·평가 단어 제거). 시나리오 파일에 neutral_description이 있으면 그것을 쓴다.
NEUTRAL_DESC_DEFAULT = {
    "NEW": "청귤맛 탄산음료",
    "COMP_COLA": "콜라",
    "COMP_WATER": "레몬향 탄산수",
    "COMP_ION": "이온음료",
}


HABIT_SYSTEM = """아래 프로필을 읽고, 이 사람의 평소 음료 습관을 추정하세요.
프로필에 근거가 있으면 그것을 따르고, 근거가 없으면 극단적으로 추측하지 말고 보통(3) 근처로 두세요."""

HABIT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["usual_drinks", "carbonated", "sweet", "price_sensitivity", "evidence"],
    "properties": {
        "usual_drinks": {"type": "string"},
        "carbonated": {"type": "integer"},
        "sweet": {"type": "integer"},
        "price_sensitivity": {"type": "integer"},
        "evidence": {"type": "string"},
    },
}


def make_habit_profile(llm):
    """2단계 프로필: 먼저 프로필에서 음료 습관을 추정(1회 호출, 캐시됨)한 뒤 그 결과를 프로필에 붙인다."""
    def mock(p):
        rng = random.Random(hashlib.sha1(p["uuid"].encode()).hexdigest())
        return {"usual_drinks": "물, 커피", "carbonated": rng.randint(1, 5), "sweet": rng.randint(1, 5),
                "price_sensitivity": rng.randint(1, 5), "evidence": "(mock)"}

    def profile(p):
        h = llm.ask_json(HABIT_SYSTEM, persona_profile_full(p), HABIT_SCHEMA, mock_fn=lambda: mock(p), tag="habit")
        clip = lambda v: min(5, max(1, int(v)))
        return (persona_profile(p) + "\n"
                f"- 평소 음료 습관(프로필 기반 추정): 자주 마시는 것 {h['usual_drinks']}, "
                f"탄산 선호 {clip(h['carbonated'])}/5, 단맛 선호 {clip(h['sweet'])}/5, "
                f"가격 민감도 {clip(h['price_sensitivity'])}/5")
    return profile


def make_conditions(scenario: dict, llm=None) -> dict:
    """조건 이름 → (시나리오, agent 옵션). 단일 변경 조건은 base와 한 가지씩만 다르다."""
    base_kw = {"system": SYSTEM, "profile_fn": persona_profile}
    conds = {"base": (scenario, base_kw)}

    conds["no_antibias"] = (scenario, {**base_kw, "system": SYSTEM_NO_ANTIBIAS})

    sc = copy.deepcopy(scenario)
    for prod in sc["products"]:
        prod["description"] = prod.get("neutral_description") or NEUTRAL_DESC_DEFAULT.get(prod["id"], prod["description"])
    conds["neutral_desc"] = (sc, base_kw)

    sc = copy.deepcopy(scenario)
    avg = round(sum(p["price"] for p in sc["products"]) / len(sc["products"]) / 100) * 100
    for prod in sc["products"]:
        prod["price"] = avg
    conds["equal_price"] = (sc, base_kw)

    sc = copy.deepcopy(scenario)
    sc["situation"] = NEUTRAL_SITUATION
    conds["neutral_situ"] = (sc, base_kw)

    conds["full_persona"] = (scenario, {**base_kw, "profile_fn": persona_profile_full})

    # --- 2차 후보 (여러 요소를 함께 바꾼 개선안) ---
    conds["balanced"] = (scenario, {**base_kw, "system": SYSTEM_BALANCED})
    sc = copy.deepcopy(scenario)
    sc["situation"] = NEUTRAL_SITUATION
    conds["balanced_neutral"] = (sc, {**base_kw, "system": SYSTEM_BALANCED})
    # 응답 방식: '100명 분포'(설문 재현 검증에서 채택). base와 다른 것은 응답 방식뿐.
    conds["prob"] = (scenario, {**base_kw, "mode": "prob"})
    if llm is not None:
        conds["habit_first"] = (sc, {"system": SYSTEM_BALANCED, "profile_fn": make_habit_profile(llm)})
    return conds


FIRST_ROUND = ["base", "no_antibias", "neutral_desc", "equal_price", "neutral_situ", "full_persona"]


def entropy(shares: pd.Series) -> float:
    """선택 분포의 다양성(0=한 제품 독식, 1=완전 균등). 쏠림 지표."""
    p = shares[shares > 0]
    return float(-(p * p.apply(math.log)).sum() / math.log(len(shares))) if len(shares) > 1 else 0.0


def persona_grounding(df: pd.DataFrame, panel: pd.DataFrame) -> float:
    """이유에 그 사람의 직업·취미·식생활 단어가 등장하는 비율(대략적인 페르소나 반영도)."""
    info = panel.set_index("uuid")
    hits = 0
    for _, r in df.iterrows():
        p = info.loc[r["uuid"]]
        words = set()
        for col in ["occupation", "hobbies_and_interests", "culinary_persona", "sports_persona"]:
            if col in p and isinstance(p[col], str):
                words |= {w for w in re.findall(r"[가-힣]{2,}", p[col]) if len(w) >= 2}
        stop = {"편의점", "음료", "가격", "마시", "있는", "하는", "좋아", "때문", "정도", "그냥", "지금"}
        words -= stop
        if any(w in str(r["reason"]) for w in words):
            hits += 1
    return hits / max(len(df), 1)


def summarize(name: str, df: pd.DataFrame, scenario: dict, panel: pd.DataFrame) -> dict:
    ok = df[df["error"] == ""]
    ids = [p["id"] for p in scenario["products"]] + ["NONE"]
    shares = shares_of(ok, scenario)
    c = scenario["concept_id"]
    is_prob = f"p_{c}" in ok
    row = {"condition": name, "n_ok": len(ok)}
    for pid in ids:
        row[f"share_{pid}"] = round(shares[pid] * 100, 1)
    row["top_share"] = round(shares.max() * 100, 1)
    row["diversity"] = round(entropy(shares), 3)
    if is_prob:  # 100명 분포 응답에는 1~5점 구매의향이 없다
        row["concept_try%"] = round(ok[f"try_{c}"].mean() * 100, 1)
    else:
        row["concept_intent"] = round(ok[f"intent_{c}"].mean(), 2)
        row["concept_intent_sd"] = round(ok[f"intent_{c}"].std(), 2)
        row["intent5_any"] = round((ok[[f"intent_{p['id']}" for p in scenario["products"]]] == 5).any(axis=1).mean() * 100, 1)
    row["persona_grounding"] = round(persona_grounding(ok, panel) * 100, 1)
    row["mentions_thirst"] = round(ok["reason"].str.contains("목|축이|갈증").mean() * 100, 1)
    row["mentions_price"] = round(ok["reason"].str.contains(r"원|가격|싼|비싸|아깝").mean() * 100, 1)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="config/scenario_example.json")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--only", nargs="*", help="돌릴 조건 이름들 (기본: 1차 단일 변경 6개)")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--model")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    scenario = load_scenario(a.scenario)
    panel = sample_panel(load_pool(), a.n, a.seed)
    llm = LLM(a.model, mock=a.mock)
    conds = make_conditions(scenario, llm)
    names = a.only or FIRST_ROUND

    exp_dir = OUT_DIR / f"exp_{datetime.now():%Y%m%d_%H%M%S}{'_mock' if a.mock else ''}"
    exp_dir.mkdir(parents=True)
    rows = []
    for name in names:
        sc, kw = conds[name]
        print(f"\n=== {name} ===")
        tag = "" if name == "base" else name  # base는 simulate.py 실행 결과(캐시)를 그대로 재사용
        df = run(sc, panel, llm, a.seed, tag=tag, workers=a.workers,
                 progress=lambda d, n: print(f"진행 {d}/{n}", flush=True) if d % 25 == 0 or d == n else None, **kw)
        df.to_csv(exp_dir / f"responses_{name}.csv", index=False, encoding="utf-8-sig")
        rows.append(summarize(name, df, sc, panel))

    table = pd.DataFrame(rows).set_index("condition")
    table.to_csv(exp_dir / "comparison.csv", encoding="utf-8-sig")
    (exp_dir / "meta.json").write_text(json.dumps(
        {"n": a.n, "seed": a.seed, "model": "mock" if a.mock else llm.model, "conditions": names,
         "api_calls": llm.api_calls, "cache_hits": llm.cache_hits}, ensure_ascii=False, indent=2), encoding="utf-8")

    pd.set_option("display.width", 200)
    print("\n\n[조건별 비교]  (share_* = 선택 비율%, diversity = 0 독식~1 균등, persona_grounding = 이유에 본인 정보 등장%)")
    print(table.T.to_string())
    print(f"\n새 응답 {llm.api_calls}개, 캐시 재사용 {llm.cache_hits}개")
    print(f"저장: {exp_dir}")


if __name__ == "__main__":
    main()
