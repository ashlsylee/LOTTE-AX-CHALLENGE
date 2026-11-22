"""페르소나 에이전트: 가상 진열대 앞에서 한 명의 소비자로 판단한다.

편향을 줄이기 위한 설계 (캡스톤 실험에서 얻은 교훈 반영)
- 블라인드: 신제품에 '신제품' 표시를 하지 않고 경쟁 제품과 똑같이 보여준다.
- 진열 순서: 페르소나마다 무작위로 섞고, 신제품이 몇 번째였는지 기록한다(위치 편향 점검용).
- 비구매 선택지: "아무것도 사지 않음"을 정상적인 선택으로 명시한다.
- 반편향 지시: 광고 문구에 쉽게 넘어가지 말고 평소 습관대로 판단하게 한다.
"""
import hashlib
import random
import string

LETTERS = string.ascii_uppercase


def persona_profile(p: dict) -> str:
    def cut(text, n=400):
        text = str(text or "").strip()
        return text if len(text) <= n else text[:n] + "…"
    return (
        f"- 나이/성별: {p['age']}세 {p['sex']}\n"
        f"- 거주지: {p['province']} {str(p['district']).split('-')[-1]}\n"
        f"- 직업: {p['occupation']}\n"
        f"- 혼인/가구: {p['marital_status']}, {p['family_type']}, {p['housing_type']}\n"
        f"- 성격과 생활: {cut(p['persona'])}\n"
        f"- 음식·식생활: {cut(p['culinary_persona'])}\n"
        f"- 취미와 관심사: {cut(p['hobbies_and_interests'], 200)}"
    )


FULL_FIELDS = [
    ("직업 생활", "professional_persona"), ("운동", "sports_persona"), ("문화·예술", "arts_persona"),
    ("여행", "travel_persona"), ("가족", "family_persona"), ("자라온 배경", "cultural_background"),
    ("잘하는 것", "skills_and_expertise"), ("앞으로의 목표", "career_goals_and_ambitions"),
]


def persona_profile_full(p: dict) -> str:
    """Nemotron 데이터셋의 서술형 항목을 모두 넣은 프로필 (대조실험용)."""
    def cut(text, n=300):
        text = str(text or "").strip()
        return text if len(text) <= n else text[:n] + "…"
    lines = [persona_profile(p), f"- 학력: {p.get('education_level', '')} {p.get('bachelors_field') or ''}".rstrip()]
    for label, col in FULL_FIELDS:
        if p.get(col):
            lines.append(f"- {label}: {cut(p[col])}")
    return "\n".join(lines)


def shuffled_shelf(products: list[dict], uuid: str, seed: int) -> list[dict]:
    """페르소나마다 다르지만, 같은 (uuid, seed)면 항상 같은 순서."""
    rng = random.Random(f"{uuid}|{seed}")
    shelf = products[:]
    rng.shuffle(shelf)
    return shelf


def shelf_text(shelf: list[dict]) -> str:
    lines = []
    for letter, prod in zip(LETTERS, shelf):
        lines.append(f"[{letter}] {prod['name']} | {prod['volume_ml']}ml | {prod['price']:,}원 | {prod['description']}")
    return "\n".join(lines)


SYSTEM = """당신은 아래 프로필을 가진 실제 한국 소비자입니다. 이 사람의 나이, 생활, 식습관, 경제 사정을 바탕으로 현실적으로 판단하세요.
- 광고 문구나 새로움에 쉽게 넘어가지 마세요. 평소 소비 습관과 가격 감각대로 판단하세요.
- 아무것도 사지 않는 것도 아주 흔하고 정상적인 선택입니다.
- 나이나 성별에 대한 고정관념이 아니라, 프로필에 적힌 이 사람의 구체적인 생활에 근거하세요.
- 답은 이 사람의 말투로, 짧고 구체적으로 쓰세요."""


def build_user_prompt(profile: str, situation: str, shelf: list[dict]) -> str:
    return (
        f"[나의 프로필]\n{profile}\n\n"
        f"[상황]\n{situation}\n\n"
        f"[진열대]\n{shelf_text(shelf)}\n\n"
        "1) 지금 이 중에서 하나를 산다면 무엇을 사겠습니까? 사지 않는다면 NONE.\n"
        "2) 각 제품을 앞으로 사 볼 의향을 1(전혀 없음)~5(매우 있음)로 매기세요.\n"
        "3) 각 제품에 낼 수 있는 최대 가격(원)을 적으세요. 전혀 안 살 제품은 0.\n"
        "4) 고른 이유(또는 사지 않은 이유)를 한두 문장으로 말하세요."
    )


def response_schema(n: int) -> dict:
    letters = list(LETTERS[:n])
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["choice", "intent", "max_price", "reason"],
        "properties": {
            "choice": {"type": "string", "enum": letters + ["NONE"]},
            "intent": {"type": "object", "additionalProperties": False, "required": letters,
                       "properties": {l: {"type": "integer"} for l in letters}},
            "max_price": {"type": "object", "additionalProperties": False, "required": letters,
                          "properties": {l: {"type": "integer"} for l in letters}},
            "reason": {"type": "string"},
        },
    }


def mock_response(p: dict, shelf: list[dict], tag: str) -> dict:
    """API 없이 파이프라인을 시험하기 위한 가짜 응답(분석 결과로 쓰면 안 됨)."""
    rng = random.Random(hashlib.sha1(f"{p['uuid']}|{tag}".encode()).hexdigest())
    letters = list(LETTERS[:len(shelf)])
    price_sensitive = p["age"] >= 60 or rng.random() < 0.3
    weights = [1 / (prod["price"] ** (2 if price_sensitive else 0.5)) for prod in shelf]
    choice = "NONE" if rng.random() < 0.25 else rng.choices(letters, weights=weights)[0]
    intent = {l: rng.randint(1, 5) for l in letters}
    if choice != "NONE":
        intent[choice] = max(intent[choice], 4)
    max_price = {l: int(prod["price"] * rng.uniform(0.6, 1.3) // 100 * 100) for l, prod in zip(letters, shelf)}
    return {"choice": choice, "intent": intent, "max_price": max_price, "reason": "(mock 응답)"}


def build_prob_prompt(profile: str, situation: str, shelf: list[dict]) -> str:
    """'100명 분포 응답': 대표 답 하나로 쏠리는 문제를 줄이기 위해(설문 재현 검증에서 효과 확인) 분포로 묻는다."""
    return (
        f"[프로필]\n{profile}\n\n"
        "이 프로필과 나이·성별·생활이 비슷한 사람 100명이 아래 상황에 있다고 생각하세요. "
        "같은 조건이어도 사람마다 취향·습관·가격 감각은 다릅니다. 실제로 어떻게 나뉠지 현실적으로 추정하세요.\n\n"
        f"[상황]\n{situation}\n\n[진열대]\n{shelf_text(shelf)}\n\n"
        "1) 100명 중 지금 각 제품을 살 사람과 아무것도 사지 않을 사람(NONE)은 몇 명입니까? (합계 100)\n"
        "2) 100명 중 각 제품을 앞으로 한 번이라도 사 볼 의향이 있는 사람은 몇 명입니까? (제품마다 0~100, 합계 제한 없음)\n"
        "3) 이 100명이 각 제품에 낼 수 있는 최대 가격의 중간값(원)은 얼마입니까?\n"
        "4) 사는 사람과 사지 않는 사람의 주된 이유를 한두 문장으로 요약하세요."
    )


def prob_schema(n: int) -> dict:
    letters = list(LETTERS[:n])
    obj = lambda keys: {"type": "object", "additionalProperties": False, "required": keys,
                        "properties": {k: {"type": "integer"} for k in keys}}
    return {"type": "object", "additionalProperties": False,
            "required": ["buy_counts", "try_counts", "median_max_price", "reason"],
            "properties": {"buy_counts": obj(letters + ["NONE"]), "try_counts": obj(letters),
                           "median_max_price": obj(letters), "reason": {"type": "string"}}}


def mock_prob_response(p: dict, shelf: list[dict], tag: str) -> dict:
    rng = random.Random(hashlib.sha1(f"prob|{p['uuid']}|{tag}".encode()).hexdigest())
    letters = list(LETTERS[:len(shelf)])
    return {"buy_counts": {l: rng.randint(5, 40) for l in letters + ["NONE"]},
            "try_counts": {l: rng.randint(10, 70) for l in letters},
            "median_max_price": {l: int(prod["price"] * rng.uniform(0.7, 1.2) // 100 * 100) for l, prod in zip(letters, shelf)},
            "reason": "(mock 응답)"}


def ask_persona(llm, p: dict, products: list[dict], situation: str, seed: int, tag: str = "",
                system: str = SYSTEM, profile_fn=persona_profile, mode: str = "single") -> dict:
    """한 페르소나에게 묻고, 진열대 글자(A,B..)를 제품 id로 되돌린 결과를 반환.
    system/profile_fn 을 바꾸면 대조실험(지시문 유무, 프로필 범위)을 할 수 있다."""
    shelf = shuffled_shelf(products, p["uuid"], seed)
    letters = LETTERS[:len(shelf)]
    letter_to_id = {l: prod["id"] for l, prod in zip(letters, shelf)}
    if mode == "prob":
        out = llm.ask_json(system, build_prob_prompt(profile_fn(p), situation, shelf), prob_schema(len(shelf)),
                           mock_fn=lambda: mock_prob_response(p, shelf, tag), tag=f"prob|{tag}")
        buy = {k: max(0, int(v)) for k, v in out["buy_counts"].items()}
        total = sum(buy.values())
        if total <= 0:
            raise ValueError("구매 인원 합계가 0입니다")
        share = {letter_to_id.get(k, "NONE"): v / total for k, v in buy.items()}
        return {
            "share": share,                                   # 제품별(+NONE) 구매 비율, 합 1
            "choice": max(share, key=share.get),              # 가장 많은 쪽(비교용)
            "try_rate": {letter_to_id[l]: min(100, max(0, int(v))) / 100 for l, v in out["try_counts"].items()},
            "max_price": {letter_to_id[l]: max(0, int(v)) for l, v in out["median_max_price"].items()},
            "reason": out["reason"],
            "shelf_order": [prod["id"] for prod in shelf],
        }
    out = llm.ask_json(
        system,
        build_user_prompt(profile_fn(p), situation, shelf),
        response_schema(len(shelf)),
        mock_fn=lambda: mock_response(p, shelf, tag),
        tag=tag,
    )
    return {
        "choice": letter_to_id.get(out["choice"], "NONE"),
        # 스키마에서 범위를 강제하지 않으므로(모델 호환성) 여기서 범위를 보정한다
        "intent": {letter_to_id[l]: min(5, max(1, int(v))) for l, v in out["intent"].items()},
        "max_price": {letter_to_id[l]: max(0, int(v)) for l, v in out["max_price"].items()},
        "reason": out["reason"],
        "shelf_order": [prod["id"] for prod in shelf],
    }
