"""컨셉 정리 에이전트 + 개선 컨셉 제안.

- parse_concept: 마케터가 자유롭게 쓴 설명을 컨셉 카드(이름·설명·가격·용량)로 정리 (기획서 에이전트 1)
- suggest_improvements: 시뮬레이션의 비구매 이유를 근거로 개선안 2~3개를 제안 (기획서 4) 개선 컨셉 재검증 루프)
"""
CARD_SCHEMA = {"type": "object", "additionalProperties": False,
               "required": ["name", "description", "price", "volume_ml", "missing"],
               "properties": {"name": {"type": "string"}, "description": {"type": "string"},
                              "price": {"type": "integer"}, "volume_ml": {"type": "integer"},
                              "missing": {"type": "array", "items": {"type": "string"}}}}

IMPROVE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["variants"],
                  "properties": {"variants": {"type": "array", "items": {
                      "type": "object", "additionalProperties": False,
                      "required": ["label", "name", "description", "price", "rationale"],
                      "properties": {"label": {"type": "string"}, "name": {"type": "string"},
                                     "description": {"type": "string"}, "price": {"type": "integer"},
                                     "rationale": {"type": "string"}}}}}}


def parse_concept(llm, free_text: str, default_price: int = 1900, default_volume: int = 500) -> dict:
    out = llm.ask_json(
        "당신은 음료 신제품 기획 담당자입니다. 마케터의 자유 메모를 진열대에 놓을 컨셉 카드로 정리하세요.\n"
        "- name: 짧은 제품명, description: 진열대에 쓸 한 줄 설명(성분·맛·특징, 과장 없이)\n"
        f"- 가격·용량이 메모에 없으면 각각 {default_price}, {default_volume}로 두고 missing에 '가격', '용량'처럼 적으세요.\n"
        "- 메모에 없는 효능이나 수치를 지어내지 마세요.",
        free_text, CARD_SCHEMA, tag="concept_card",
        mock_fn=lambda: {"name": "(mock) 제품명", "description": free_text[:40], "price": default_price,
                         "volume_ml": default_volume, "missing": ["가격", "용량"]})
    return out


def suggest_improvements(llm, concept: dict, reasons: list[str], n: int = 3) -> list[dict]:
    out = llm.ask_json(
        "당신은 음료 신제품 기획 담당자입니다. 소비자 반응(구매·비구매 이유)만 근거로 개선 컨셉을 제안하세요.\n"
        "- 각 안은 한 가지 요소(이름, 설명 문구, 가격 중 하나 이상)를 분명히 바꾸고, 어떤 반응 때문인지 rationale에 쓰세요.\n"
        "- 반응에 없는 근거를 만들지 마세요. 원래 제품의 정체성(맛·카테고리)은 유지하세요.",
        f"[현재 컨셉] {concept['name']} | {concept['price']}원 | {concept['description']}\n\n[소비자 반응]\n"
        + "\n".join(f"- {r}" for r in reasons[:20]) + f"\n\n개선안 {n}개를 label을 '개선1'~'개선{n}'으로 제안하세요.",
        IMPROVE_SCHEMA, tag="improve",
        mock_fn=lambda: {"variants": [{"label": f"개선{i}", "name": f"{concept['name']} {i}", "description": concept["description"],
                                       "price": concept["price"] - 100 * i, "rationale": "(mock)"} for i in range(1, n + 1)]})
    return out["variants"][:n]
