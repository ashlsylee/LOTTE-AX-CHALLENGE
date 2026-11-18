"""시나리오(진열대+컨셉)를 패널에게 돌려 응답 CSV를 만든다.

예시:
    python -m vm.simulate --scenario config/scenario_example.json --n 100 --mock
    python -m vm.simulate --scenario config/scenario_example.json --n 100        # 실제 API
"""
import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd

from .agent import ask_persona
from .config import OUT_DIR
from .llm import LLM
from .personas import load_pool, sample_panel

SEGMENT_COLS = ["uuid", "sex", "age", "age_group", "is_capital", "province", "occupation", "family_type"]


def load_scenario(path) -> dict:
    sc = json.loads(open(path, encoding="utf-8").read())
    ids = [p["id"] for p in sc["products"]]
    assert sc["concept_id"] in ids, "concept_id가 products에 없습니다."
    assert len(set(ids)) == len(ids), "제품 id가 중복됩니다."
    return sc


def run(scenario: dict, panel: pd.DataFrame, llm: LLM, seed: int = 42,
        tag: str = "", workers: int = 8, progress=None) -> pd.DataFrame:
    """패널 전원에게 묻고 한 사람당 한 행인 DataFrame을 돌려준다."""
    products, concept = scenario["products"], scenario["concept_id"]
    records = panel.to_dict("records")
    rows = [None] * len(records)

    def one(i):
        p = records[i]
        base = {c: p[c] for c in SEGMENT_COLS}
        try:
            r = ask_persona(llm, p, products, scenario["situation"], seed, tag)
        except Exception as e:  # 형식 오류·API 오류는 버리지 않고 기록
            return i, {**base, "error": f"{type(e).__name__}: {e}"[:300]}
        row = {**base, "choice": r["choice"], "reason": r["reason"],
               "concept_position": r["shelf_order"].index(concept) + 1,
               "shelf_order": ",".join(r["shelf_order"]), "error": ""}
        for pid in r["intent"]:
            row[f"intent_{pid}"] = r["intent"][pid]
            row[f"max_price_{pid}"] = r["max_price"][pid]
        return i, row

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for fut in as_completed([ex.submit(one, i) for i in range(len(records))]):
            i, row = fut.result()
            rows[i] = row
            done += 1
            if progress:
                progress(done, len(records))
    return pd.DataFrame(rows)


def quick_summary(df: pd.DataFrame, scenario: dict) -> str:
    ok = df[df["error"] == ""]
    c = scenario["concept_id"]
    names = {p["id"]: p["name"] for p in scenario["products"]}
    names["NONE"] = "구매 안 함"
    price = next(p["price"] for p in scenario["products"] if p["id"] == c)
    share = ok["choice"].map(names).value_counts(normalize=True).mul(100).round(1)
    lines = [f"응답 {len(ok)}/{len(df)}명 (실패 {len(df) - len(ok)}명)", "", "[선택 비율 %]", share.to_string(), ""]
    lines.append(f"[신제품] 구매의향 평균 {ok[f'intent_{c}'].mean():.2f}/5, "
                 f"상위2(4~5점) {ok[f'intent_{c}'].ge(4).mean() * 100:.1f}%")
    wtp = ok[f"max_price_{c}"]
    lines.append(f"[신제품] 지불의사가격 중앙값 {wtp.median():,.0f}원 (판매가 {price:,}원), "
                 f"판매가 이상 지불 의향 {wtp.ge(price).mean() * 100:.1f}%")
    lines.append("")
    lines.append("[연령대별 신제품 선택률 %]")
    lines.append(ok.groupby("age_group", observed=True)["choice"].apply(lambda s: (s == c).mean() * 100)
                 .round(1).to_string())
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="config/scenario_example.json")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--age-min", type=int)
    ap.add_argument("--age-max", type=int)
    ap.add_argument("--mock", action="store_true", help="API 없이 가짜 응답으로 파이프라인만 시험")
    ap.add_argument("--model")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    scenario = load_scenario(a.scenario)
    panel = sample_panel(load_pool(), a.n, a.seed, a.age_min, a.age_max)
    llm = LLM(a.model, mock=a.mock)
    t0 = time.time()
    df = run(scenario, panel, llm, a.seed, workers=a.workers,
             progress=lambda d, n: print(f"진행 {d}/{n}", flush=True) if d % 20 == 0 or d == n else None)
    print()

    run_dir = OUT_DIR / f"run_{datetime.now():%Y%m%d_%H%M%S_%f}{'_mock' if a.mock else ''}"
    run_dir.mkdir(parents=True)
    df.to_csv(run_dir / "responses.csv", index=False, encoding="utf-8-sig")
    meta = {"scenario": scenario, "n": a.n, "seed": a.seed, "model": "mock" if a.mock else llm.model,
            "age_min": a.age_min, "age_max": a.age_max, "api_calls": llm.api_calls,
            "cache_hits": llm.cache_hits, "seconds": round(time.time() - t0, 1)}
    (run_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = quick_summary(df, scenario)
    (run_dir / "summary.txt").write_text(summary, encoding="utf-8")
    print(summary)
    print(f"\n새 응답 {llm.api_calls}개, 캐시 재사용 {llm.cache_hits}개, {meta['seconds']}초")
    print(f"저장: {run_dir}")


if __name__ == "__main__":
    main()
