"""가상 FGI: 타깃 패널에서 고른 페르소나 4~6명이 신제품을 두고 라운드별로 이야기한다.

기획서 2) "페르소나끼리 대화하는 가상 FGI로 누가 누구를 설득하는지까지 관찰"을 구현.
캡스톤 2주차 경험 반영: 매 라운드 같은 질문을 반복하면 답이 비슷해져서, 라운드마다 질문을 바꾼다.
각 발언은 앞사람들의 발언을 보고 하며, 매 라운드 구매 입장(살 것/고민/안 살 것)을 기록해 입장 변화를 추적한다.
"""
import hashlib
import json
import random

import pandas as pd

from .agent import persona_profile, shelf_text

ROUNDS = [
    "진열대에서 이 신제품을 처음 봤을 때 느낌은 어떤가요? 지금 사겠습니까?",
    "가격·이름·맛 설명 중에서 마음에 드는 점과 걸리는 점은 무엇인가요? 다른 분 의견에 동의하거나 반박해도 됩니다.",
    "무엇이 바뀌면 사겠습니까(또는 더 자주 사겠습니까)? 최종 입장을 말해 주세요.",
]
STANCES = ["살 것", "고민", "안 살 것"]

SYSTEM = """당신은 소비자 좌담회(FGI)에 참여한 실제 한국 소비자입니다. 아래 프로필의 사람으로서 말하세요.
- 평소 생활·식습관·가격 감각에 근거해 솔직하게 말하세요. 진행자에게 맞춰 주려고 좋게 말하지 마세요.
- 다른 참여자의 말을 듣고 동의·반박·설득될 수 있지만, 근거 없이 입장을 바꾸지는 마세요.
- 한두 문장, 이 사람의 말투로 짧게."""

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["utterance", "stance", "reply_to"],
          "properties": {"utterance": {"type": "string"},
                         "stance": {"type": "string", "enum": STANCES},
                         "reply_to": {"type": "string", "description": "특정 참여자에게 하는 말이면 그 이름, 아니면 빈 문자열"}}}

SUMMARY_SCHEMA = {"type": "object", "additionalProperties": False,
                  "required": ["key_points", "concerns", "improvements", "persuasion"],
                  "properties": {k: {"type": "array", "items": {"type": "string"}}
                                 for k in ["key_points", "concerns", "improvements", "persuasion"]}}


def pick_participants(panel: pd.DataFrame, k: int, seed: int) -> pd.DataFrame:
    """성별·연령이 섞이도록 고른다."""
    df = panel.sample(frac=1, random_state=seed)
    out = df.groupby("sex", group_keys=False).head((k + 1) // 2).head(k)
    if len(out) < k:
        out = pd.concat([out,df.loc[~df.index.isin(out.index)].head(k-len(out))])
    return out.sort_values("age").reset_index(drop=True)


def label(p: dict) -> str:
    return f"P{p['_no']}({p['age']}세 {p['sex']}, {str(p['occupation'])[:10]})"


def run_fgi(llm, scenario: dict, panel: pd.DataFrame, k: int = 5, seed: int = 42, tag: str = "fgi") -> dict:
    concept = next(p for p in scenario["products"] if p["id"] == scenario["concept_id"])
    people = pick_participants(panel, k, seed).to_dict("records")
    for i, p in enumerate(people, 1):
        p["_no"] = i
    names = [label(p) for p in people]
    intro = (f"[상황]\n{scenario['situation']}\n\n[진열대]\n{shelf_text(scenario['products'])}\n\n"
             f"[오늘 이야기할 신제품] {concept['name']} | {concept['volume_ml']}ml | {concept['price']:,}원 | {concept['description']}\n"
             f"[참여자] {', '.join(names)}")
    transcript, turns = [], []
    for r, question in enumerate(ROUNDS, 1):
        for p, nm in zip(people, names):
            history = "\n".join(transcript[-12:]) or "(아직 발언 없음)"
            user = (f"[나의 프로필 — 나는 {nm}]\n{persona_profile(p)}\n\n{intro}\n\n[지금까지 대화]\n{history}\n\n"
                    f"[진행자 질문 · {r}라운드] {question}")
            rng = random.Random(hashlib.sha1(f"{p['uuid']}|{r}".encode()).hexdigest())
            out = llm.ask_json(SYSTEM, user, SCHEMA, tag=f"{tag}|{r}",
                               mock_fn=lambda: {"utterance": "(mock 발언)", "stance": rng.choice(STANCES), "reply_to": ""})
            stance = out["stance"] if out["stance"] in STANCES else "고민"
            turns.append({"round": r, "speaker": nm, "age": p["age"], "sex": p["sex"],
                          "utterance": out["utterance"], "stance": stance, "reply_to": out.get("reply_to", "")})
            transcript.append(f"{nm}: {out['utterance']} [입장: {stance}]")
    t = pd.DataFrame(turns)
    stance_table = t.pivot(index="speaker", columns="round", values="stance")
    changed = [s for s, row in stance_table.iterrows() if row.iloc[0] != row.iloc[-1]]
    summary = llm.ask_json(
        "당신은 FGI 진행자입니다. 대화 기록에 있는 내용만으로 요약하세요. 없는 내용을 만들지 마세요.",
        f"[신제품] {concept['name']} {concept['price']:,}원\n\n[대화 기록]\n" + "\n".join(transcript) +
        "\n\n핵심 반응, 우려, 개선 아이디어, 입장이 바뀐 사람과 그 계기(설득 장면)를 각각 2~4개 bullet로.",
        SUMMARY_SCHEMA, tag=f"{tag}|summary",
        mock_fn=lambda: {k: ["(mock)"] for k in ["key_points", "concerns", "improvements", "persuasion"]})
    final = t[t["round"] == len(ROUNDS)]["stance"].value_counts().reindex(STANCES, fill_value=0).to_dict()
    return {"participants": names, "turns": turns, "final_stance": final,
            "stance_changed": changed, "summary": summary}


def compact(result: dict) -> dict:
    """에이전트에게 돌려줄 짧은 형태."""
    return {"participants": result["participants"], "final_stance": result["final_stance"],
            "stance_changed": result["stance_changed"], "summary": result["summary"],
            "quotes": [f"[{t['round']}R] {t['speaker']}: {t['utterance']}" for t in result["turns"][-len(result["participants"]):]]}


if __name__ == "__main__":
    import argparse
    from .llm import LLM
    from .personas import load_pool, sample_panel
    from .simulate import load_scenario
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="config/scenario_example.json")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--age-min", type=int, default=20)
    ap.add_argument("--age-max", type=int, default=39)
    ap.add_argument("--mock", action="store_true")
    a = ap.parse_args()
    res = run_fgi(LLM(mock=a.mock), load_scenario(a.scenario),
                  sample_panel(load_pool(), 60, 42, a.age_min, a.age_max), a.k)
    for t in res["turns"]:
        print(f"[{t['round']}R] {t['speaker']} ({t['stance']}): {t['utterance']}")
    print(json.dumps({k: res[k] for k in ["final_stance", "stance_changed", "summary"]}, ensure_ascii=False, indent=1))
