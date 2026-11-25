"""가상 소비자 설문: 실제 패널조사와 같은 문항을 신제품과 비교 제품(자사·경쟁)에 똑같이 묻는다.

- 모든 제품을 같은 문장·같은 가격 표시(정가)로 보여 준다(실제 설문의 유도 질문·앵커 가격을 반복하지 않음).
- '비슷한 사람 100명' 분포로 묻는다(대표 답 쏠림 완화, KREI 재현에서 채택한 방식).
- 문항: 이해도·호감도·차별성·구매의향·가격수용도(각 4~5점 인원), 구매의향 1~5점 분포, 최대 지불가격, 예상 월 구매횟수,
  예상 만족도(마셔 본 뒤 만족할 인원)·예상 평점(1~5) — 출시 전이므로 '예상'으로만 표시,
  그리고 과거 실패 사유 등 '우려'마다 구매를 망설일 인원.
- 실제 설문이 있는 제품은 같은 항목끼리 나란히 비교한다(원자료 / 품질 의심 제외 / 모집단 가중).
"""
from __future__ import annotations

import hashlib
import random
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from .agent import LETTERS, persona_profile

ITEMS = {"이해도": "컨셉이해도", "호감도": "호감도", "차별성": "차별성", "구매의향": "구매의향", "가격수용도": "가격수용도"}
SYSTEM = ("당신은 소비자 조사 응답을 추정하는 분석가입니다. 프로필의 생활·식습관·경제 사정에 근거해 현실적으로 추정하세요. "
          "새로움이나 광고 문구에 쉽게 끌리지 말고, 관심 없는 사람이 많을 수 있다는 점을 반영하세요.")


def _card(letter, p):
    return f"[{letter}] {p['name']} | {p.get('volume_ml', '')}mL | {int(p['price']):,}원 | {p.get('description', '')}"


def _prompt(profile, situation, products, concerns):
    cs = "\n".join(f"  ({i + 1}) {c}" for i, c in enumerate(concerns)) or "  (없음)"
    return (f"[프로필]\n{profile}\n\n이 프로필과 나이·성별·생활이 비슷한 사람 100명이 아래 제품 카드를 하나씩 봅니다. "
            f"상황: {situation}\n\n[제품 카드]\n" + "\n".join(_card(l, p) for l, p in zip(LETTERS, products)) +
            "\n\n제품마다 100명 중 몇 명인지 추정하세요.\n"
            "- 이해도/호감도/차별성/구매의향/가격수용도: 각각 5점 척도에서 4~5점을 줄 사람 수\n"
            "- 구매의향 분포: 1점~5점을 줄 사람 수(합 100)\n"
            "- 최대 지불가격 중간값(원), 출시 후 한 달 평균 구매 횟수(구매할 사람 기준이 아니라 100명 평균)\n"
            "- 예상 만족: 한 번 마셔 본 사람 중 만족할 비율(%) / 예상 평점(1.0~5.0)\n"
            f"- 우려 점검(신제품 [A]에만): 아래 각 우려 때문에 사지 않을 사람 수\n{cs}\n"
            "- 사는 이유와 망설이는 이유를 한두 문장으로")


def _schema(n, k):
    letters = list(LETTERS[:n])
    per = {"type": "object", "additionalProperties": False,
           "required": [*ITEMS, "intent_dist", "max_price", "monthly", "satisfaction", "rating"],
           "properties": {**{i: {"type": "integer"} for i in ITEMS},
                          "intent_dist": {"type": "array", "items": {"type": "integer"}},
                          "max_price": {"type": "integer"}, "monthly": {"type": "number"},
                          "satisfaction": {"type": "integer"}, "rating": {"type": "number"}}}
    return {"type": "object", "additionalProperties": False, "required": ["products", "concerns", "reason"],
            "properties": {"products": {"type": "object", "additionalProperties": False, "required": letters,
                                        "properties": {l: per for l in letters}},
                           "concerns": {"type": "array", "items": {"type": "integer"}},
                           "reason": {"type": "string"}}}


def _mock(p, products, k):
    rng = random.Random(hashlib.sha1(f"vs|{p['uuid']}|{len(products)}".encode()).hexdigest())
    out = {}
    for l, prod in zip(LETTERS, products):
        base = rng.randint(15, 60)
        dist = [rng.randint(5, 30) for _ in range(5)]
        dist = [round(x * 100 / sum(dist)) for x in dist]
        out[l] = {**{i: max(0, min(100, base + rng.randint(-15, 15))) for i in ITEMS}, "intent_dist": dist,
                  "max_price": int(prod["price"] * rng.uniform(0.7, 1.2) // 100 * 100), "monthly": round(rng.uniform(0, 3), 1),
                  "satisfaction": rng.randint(40, 80), "rating": round(rng.uniform(2.8, 4.3), 1)}
    return {"products": out, "concerns": [rng.randint(5, 40) for _ in range(k)], "reason": "(mock 응답)"}


def run_survey(llm, panel: pd.DataFrame, products: list[dict], situation: str, concerns: list[str] | None = None,
               workers: int | None = None, progress=None) -> dict:
    """products[0]이 신제품. 제품은 최대 5개. 순서는 사람마다 섞어 순서 효과를 줄인다."""
    concerns = (concerns or [])[:5]
    products = products[:5]
    recs = panel.to_dict("records")

    def one(p):
        order = list(range(len(products)))
        random.Random(f"{p['uuid']}|vs").shuffle(order)  # 사람마다 제시 순서를 섞는다(같은 사람은 항상 같은 순서)
        shown = [products[i] for i in order]
        new_letter = LETTERS[order.index(0)]
        prompt = _prompt(persona_profile(p), situation, shown, concerns).replace("신제품 [A]", f"신제품 [{new_letter}]")
        try:
            r = llm.ask_json(SYSTEM, prompt, _schema(len(shown), len(concerns)), lambda: _mock(p, shown, len(concerns)), tag="vsurvey-v1")
        except Exception as e:  # 실패는 기록만
            return {"error": str(e)[:200]}
        rows = []
        for letter, i in zip(LETTERS, order):
            v = r["products"][letter]
            dist = (v["intent_dist"] + [0] * 5)[:5]
            tot = sum(dist) or 1
            rows.append({"uuid": p["uuid"], "age": p["age"], "sex": p["sex"], "product": products[i]["name"], "idx": i,
                         **{k: min(max(v[k], 0), 100) for k in ITEMS}, "intent_mean": sum((j + 1) * d for j, d in enumerate(dist)) / tot,
                         "max_price": v["max_price"], "monthly": v["monthly"], "satisfaction": v["satisfaction"], "rating": v["rating"]})
        return {"rows": rows, "concerns": r["concerns"][:len(concerns)], "reason": r["reason"], "age": p["age"], "sex": p["sex"]}

    results = []
    with ThreadPoolExecutor(max_workers=workers or int(__import__("os").getenv("VM_WORKERS", "16"))) as ex:
        for k, res in enumerate(ex.map(one, recs), 1):
            results.append(res)
            if progress:
                progress(k, len(recs))
    ok = [r for r in results if "rows" in r]
    df = pd.DataFrame([row for r in ok for row in r["rows"]])
    summary = pd.DataFrame()
    if not df.empty:
        g = df.groupby(["idx", "product"])
        summary = pd.concat([g[list(ITEMS)].mean().round(1).add_suffix(" TOP2(%)"),
                             g["intent_mean"].mean().round(2).rename("구매의향 평균(1~5)"),
                             g["max_price"].median().rename("지불가격 중앙값(원)"),
                             g["monthly"].mean().round(2).rename("예상 월 구매(회)"),
                             g["satisfaction"].mean().round(1).rename("예상 만족(%)"),
                             g["rating"].mean().round(2).rename("예상 평점")], axis=1).reset_index().drop(columns="idx").rename(columns={"product": "제품"})
        summary.insert(1, "가격(원)", [int(products[i]["price"]) for i in sorted(df["idx"].unique())])
    conc = []
    if concerns and ok:
        for j, c in enumerate(concerns):
            vals = [r["concerns"][j] for r in ok if len(r["concerns"]) > j]
            conc.append({"우려": c, "망설일 사람(100명 중 평균)": round(sum(vals) / len(vals), 1) if vals else None})
    reasons = [f"[{r['age']}세 {r['sex']}] {r['reason']}" for r in ok][:12]
    return {"n": len(recs), "n_ok": len(ok), "summary": summary, "by_age": _by_age(df), "concerns": pd.DataFrame(conc),
            "reasons": reasons, "raw": df}


def _by_age(df):
    if df.empty:
        return pd.DataFrame()
    d = df.assign(연령대=(df["age"].astype(int) // 10 * 10).astype(str) + "대")
    return d.pivot_table(index="연령대", columns="product", values="구매의향", aggfunc="mean").round(1)


def compare_with_survey(summary: pd.DataFrame, survey: pd.DataFrame) -> pd.DataFrame:
    """가상 TOP2와 실제 설문 TOP2(원자료/품질 의심 제외/가중)를 같은 항목끼리."""
    if summary.empty or survey.empty:
        return pd.DataFrame()
    rows = []
    for _, r in summary.iterrows():
        for short, col in ITEMS.items():
            m = survey[(survey["컨셉"].astype(str) == r["제품"]) & (survey["항목"] == col)]
            if m.empty:
                continue
            s = m.iloc[0]
            rows.append({"제품": r["제품"], "항목": short, "가상(%)": r[f"{short} TOP2(%)"], "설문 원자료(%)": s["원자료 TOP2(%)"],
                         "설문 품질 의심 제외(%)": s["품질 의심 제외(%)"], "설문 제외+가중(%)": s["제외+모집단 가중(%)"],
                         "차이(가상−가중, %p)": round(r[f"{short} TOP2(%)"] - (s["제외+모집단 가중(%)"] if pd.notna(s["제외+모집단 가중(%)"]) else s["품질 의심 제외(%)"]), 1)})
    return pd.DataFrame(rows)
