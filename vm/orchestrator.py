"""시장 검증 에이전트(오케스트레이터).

마케터의 자연어 요청을 받아 LLM이 스스로 계획을 세우고, 아래 도구를 골라 호출하며,
결과를 보고 다음 행동을 정한 뒤 근거가 붙은 리포트를 쓴다(OpenAI tool calling).

도구
- check_reliability   : 설문 재현 검증(KREI 실제 설문 대비) 결과로 이 패널을 어디까지 믿을 수 있는지 확인
- run_shelf_simulation: 가상 진열대 시뮬레이션(100명 분포 응답) — 타깃 연령·가격·문구를 바꿔 실행
- compare_prices      : 같은 패널로 신제품 가격만 바꿔 비교(가격 대조실험)
- compare_concepts    : 같은 패널로 컨셉 문구 A/B 비교
- get_reasons         : 시뮬레이션의 구매·비구매 이유 표본 보기
- write_report        : 최종 리포트 제출(종료)

안전장치
- 페르소나 호출 예산(--budget) 초과 시 도구가 실행을 거부하고, 에이전트는 남은 정보로 리포트를 쓴다.
- 최대 단계 수(--max-steps), 패널 크기 상한(100명).
- 리포트의 숫자는 도구 결과에서만 인용하도록 지시하고, 모든 도구 호출·결과를 trace.json에 남긴다.

예시:
    python -m vm.orchestrator "20~30대 대상 제주 청귤 제로 스파클링, 1,900원이 적당한지 검토해줘"
    python -m vm.orchestrator "..." --mock      # API 없이 정해진 순서로 도구만 시험
"""
import argparse
import copy
import glob
import json
import os
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

from .config import OUT_DIR
from .llm import LLM
from .personas import load_pool, sample_panel
from .simulate import load_scenario, run, shares_of

MAX_PANEL = 100

AGENT_SYSTEM = """당신은 롯데칠성음료 신제품 기획팀을 돕는 '시장 검증 에이전트'입니다.
AI 페르소나 가상 소비자 패널 도구를 써서 마케터의 질문에 답합니다.

일하는 방식
1. 먼저 check_reliability로 이 패널을 어디까지 믿을 수 있는지 확인하세요.
2. 질문에 맞게 계획을 세우고 필요한 도구만 호출하세요. 타깃 연령이 있으면 age_min/age_max를 쓰세요.
3. 결과에 쏠림이나 이상한 점이 보이면 get_reasons로 이유를 확인하거나 비교 실험을 추가하세요.
4. 예산(남은 페르소나 호출 수)을 확인하며 효율적으로 쓰세요.
5. 마지막에 반드시 write_report로 한국어 마크다운 리포트를 제출하세요.

리포트 규칙
- 숫자는 반드시 도구 결과에 있는 값만 인용하세요. 추측한 숫자를 만들지 마세요.
- 구성: 요약(결론 2~3줄) / 근거(실행한 실험과 수치) / 타깃·가격·문구 제안 / 신뢰도와 한계 / 다음 단계(실제 조사로 확인할 것)
- 신뢰도: check_reliability 결과를 근거로, 어느 부분은 믿을 만하고 어느 부분은 조심해야 하는지 쓰세요.
- 이 결과는 실제 소비자 조사를 대신하지 않는 '앞단 필터'임을 명시하세요."""

TOOLS = [
    {"type": "function", "function": {
        "name": "check_reliability",
        "description": "가장 최근 설문 재현 검증 결과(실제 정부 설문 KREI 대비 오차, 연령대별 탄산·이온 음료 선호 비교)를 돌려준다. 비용 없음.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "run_shelf_simulation",
        "description": "가상 편의점 진열대 시뮬레이션. 신제품의 가격·이름·설명을 바꿔 실행할 수 있다. 구매 비율, 사 볼 의향, 지불의사가격, 연령대별 결과를 돌려준다.",
        "parameters": {"type": "object", "additionalProperties": False, "properties": {
            "n": {"type": "integer", "description": f"패널 인원(최대 {MAX_PANEL})"},
            "age_min": {"type": "integer"}, "age_max": {"type": "integer"},
            "concept_price": {"type": "integer"}, "concept_name": {"type": "string"},
            "concept_description": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "compare_prices",
        "description": "같은 패널에 신제품 가격만 바꿔 여러 번 실행해 비교한다(가격 대조실험). 가격 개수만큼 비용이 든다.",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["prices"], "properties": {
            "prices": {"type": "array", "items": {"type": "integer"}},
            "n": {"type": "integer"}, "age_min": {"type": "integer"}, "age_max": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "compare_concepts",
        "description": "같은 패널에 신제품 이름·설명만 바꾼 여러 안을 비교한다(A/B). 안 개수만큼 비용이 든다.",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["variants"], "properties": {
            "variants": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                    "required": ["label", "name", "description"],
                                                    "properties": {"label": {"type": "string"}, "name": {"type": "string"},
                                                                   "description": {"type": "string"}}}},
            "n": {"type": "integer"}, "age_min": {"type": "integer"}, "age_max": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "get_reasons",
        "description": "가장 최근 시뮬레이션의 구매·비구매 이유 표본을 돌려준다. 비용 없음.",
        "parameters": {"type": "object", "additionalProperties": False, "properties": {
            "limit": {"type": "integer", "description": "최대 개수(기본 15)"}}}}},
    {"type": "function", "function": {
        "name": "write_report",
        "description": "최종 리포트(한국어 마크다운)를 제출하고 작업을 끝낸다.",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["markdown"], "properties": {
            "markdown": {"type": "string"}}}}},
]


class Toolbox:
    """에이전트가 호출하는 도구. 기존 시뮬레이션 모듈을 그대로 감싼다."""

    def __init__(self, scenario: dict, llm: LLM, budget: int, seed: int = 42):
        self.base_scenario, self.llm, self.seed = scenario, llm, seed
        self.budget_left = budget
        self.pool = load_pool()
        self.last_df = None
        self.runs = []

    # ---------- 공통 ----------
    def _panel(self, n, age_min, age_max):
        n = max(10, min(int(n or 60), MAX_PANEL))
        return sample_panel(self.pool, n, self.seed, age_min, age_max)

    def _charge(self, n_calls: int):
        if n_calls > self.budget_left:
            raise RuntimeError(f"예산 부족: 필요 {n_calls}회, 남은 {self.budget_left}회. 남은 정보로 리포트를 작성하세요.")

    def _simulate(self, scenario, panel, label):
        new_before = self.llm.api_calls
        df = run(scenario, panel, self.llm, self.seed, tag="", mode="prob")
        used = self.llm.api_calls - new_before
        self.budget_left -= used
        self.last_df = df
        ok = df[df["error"] == ""]
        c = scenario["concept_id"]
        names = {p["id"]: p["name"] for p in scenario["products"]}
        names["NONE"] = "구매 안 함"
        price = next(p["price"] for p in scenario["products"] if p["id"] == c)
        res = {
            "label": label, "n_ok": len(ok), "n_fail": int(len(df) - len(ok)),
            "concept_price": price,
            "buy_share_%": {names[k]: round(v * 100, 1) for k, v in shares_of(ok, scenario).items()},
            "concept_try_%": round(ok[f"try_{c}"].mean() * 100, 1),
            "concept_wtp_median": int(ok[f"max_price_{c}"].median()),
            "concept_buy_by_age_%": ok.groupby("age_group", observed=True)[f"p_{c}"].mean().mul(100).round(1).to_dict(),
            "new_persona_calls": used, "budget_left": self.budget_left,
        }
        self.runs.append(res)
        return res

    def _scenario_with(self, price=None, name=None, description=None):
        sc = copy.deepcopy(self.base_scenario)
        for p in sc["products"]:
            if p["id"] == sc["concept_id"]:
                if price: p["price"] = int(price)
                if name: p["name"] = name
                if description: p["description"] = description
        return sc

    # ---------- 도구 ----------
    def check_reliability(self):
        files = sorted(glob.glob(str(OUT_DIR / "survey_*" / "comparison.csv")))
        files = [f for f in files if "_mock" not in f]
        if not files:
            return {"status": "검증 결과 없음", "note": "python -m vm.survey 를 먼저 실행해야 신뢰도를 말할 수 있다."}
        t = pd.read_csv(files[-1], index_col=0)
        keep = [r for r in ["prob", "base", "무작위 기준선", "실제(KREI)"] if r in t.index]
        return {
            "source": "KREI 식품소비행태조사 2023~2025 성인(가중), 같은 질문을 페르소나에게 물어 비교",
            "채택 방식": "prob(100명 분포 응답)" if "prob" in t.index else "base",
            "table": t.loc[keep].round(2).where(t.loc[keep].notna(), None).to_dict(orient="index"),
            "읽는 법": "fav_mae=1순위 음료 분포 오차(%p, 실제 조사끼리 연도 비교 시 1.2~1.8), "
                      "four_rate_mae=탄산·이온 4종 선호 비율 오차, four_age_corr=연령 방향 일치도, zero_mae=검증 문항 오차",
        }

    def run_shelf_simulation(self, n=60, age_min=None, age_max=None, concept_price=None,
                             concept_name=None, concept_description=None):
        panel = self._panel(n, age_min, age_max)
        self._charge(len(panel))
        sc = self._scenario_with(concept_price, concept_name, concept_description)
        return self._simulate(sc, panel, f"simulation(age {age_min}~{age_max}, price {concept_price})")

    def compare_prices(self, prices, n=60, age_min=None, age_max=None):
        panel = self._panel(n, age_min, age_max)
        self._charge(len(panel) * len(prices))
        return {"same_panel": True, "results": [self._simulate(self._scenario_with(price=p), panel, f"price {p}")
                                                for p in prices]}

    def compare_concepts(self, variants, n=60, age_min=None, age_max=None):
        panel = self._panel(n, age_min, age_max)
        self._charge(len(panel) * len(variants))
        return {"same_panel": True, "results": [
            self._simulate(self._scenario_with(name=v["name"], description=v["description"]), panel, v["label"])
            for v in variants]}

    def get_reasons(self, limit=15):
        if self.last_df is None:
            return {"status": "아직 실행한 시뮬레이션이 없다"}
        ok = self.last_df[self.last_df["error"] == ""]
        sample = ok.sample(n=min(int(limit or 15), len(ok)), random_state=self.seed)
        return {"reasons": [f"[{r.age_group} {r.sex}] {r.reason}" for r in sample.itertuples()]}


def call_tool(tb: Toolbox, name: str, args: dict):
    try:
        if name == "check_reliability":
            return tb.check_reliability()
        if name == "run_shelf_simulation":
            return tb.run_shelf_simulation(**args)
        if name == "compare_prices":
            return tb.compare_prices(**args)
        if name == "compare_concepts":
            return tb.compare_concepts(**args)
        if name == "get_reasons":
            return tb.get_reasons(**args)
        return {"error": f"알 수 없는 도구: {name}"}
    except Exception as e:  # 도구 오류는 에이전트에게 돌려줘 스스로 대응하게 한다
        return {"error": f"{type(e).__name__}: {e}"}


def scripted_plan(request: str):
    """--mock: API 없이 도구 연결만 시험하기 위한 고정 계획."""
    yield "check_reliability", {}
    yield "run_shelf_simulation", {"n": 30, "age_min": 20, "age_max": 39}
    yield "get_reasons", {"limit": 5}
    yield "compare_prices", {"prices": [1700, 1900, 2100], "n": 30, "age_min": 20, "age_max": 39}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("request", help="마케터의 요청(자연어)")
    ap.add_argument("--scenario", default="config/scenario_example.json")
    ap.add_argument("--budget", type=int, default=400, help="페르소나 호출 예산(새 응답 수)")
    ap.add_argument("--max-steps", type=int, default=10)
    ap.add_argument("--model", help="페르소나 모델(기본 .env의 VM_MODEL)")
    ap.add_argument("--agent-model", help="에이전트(계획·리포트) 모델(기본: 페르소나 모델과 같음)")
    ap.add_argument("--mock", action="store_true")
    a = ap.parse_args()

    load_dotenv()
    llm = LLM(a.model, mock=a.mock)
    tb = Toolbox(load_scenario(a.scenario), llm, a.budget)
    out_dir = OUT_DIR / f"agent_{datetime.now():%Y%m%d_%H%M%S}{'_mock' if a.mock else ''}"
    out_dir.mkdir(parents=True)
    trace, report = [], None

    def log(step, name, args, result):
        trace.append({"step": step, "tool": name, "args": args, "result": result})
        short = json.dumps(result, ensure_ascii=False)
        print(f"\n[{step}] {name}({json.dumps(args, ensure_ascii=False)})\n    → {short[:400]}{'…' if len(short) > 400 else ''}")

    if a.mock:
        for step, (name, args) in enumerate(scripted_plan(a.request), 1):
            log(step, name, args, call_tool(tb, name, args))
        report = "# (mock) 리포트\n\n도구 연결 시험용 실행입니다. 실제 리포트는 API로 실행하세요.\n"
    else:
        from openai import OpenAI
        client = OpenAI()
        agent_model = a.agent_model or os.getenv("VM_AGENT_MODEL") or llm.model
        sc = tb.base_scenario
        context = (f"[요청]\n{a.request}\n\n[기본 시나리오]\n{json.dumps(sc, ensure_ascii=False)}\n\n"
                   f"[예산] 페르소나 호출 {a.budget}회, 최대 {a.max_steps}단계")
        messages = [{"role": "system", "content": AGENT_SYSTEM}, {"role": "user", "content": context}]
        for step in range(1, a.max_steps + 1):
            force = step == a.max_steps  # 마지막 단계에서는 리포트를 강제
            resp = client.chat.completions.create(
                model=agent_model, messages=messages, tools=TOOLS,
                tool_choice={"type": "function", "function": {"name": "write_report"}} if force else "auto")
            msg = resp.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))
            if not msg.tool_calls:
                messages.append({"role": "user", "content": "도구를 호출하거나 write_report로 리포트를 제출하세요."})
                continue
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                if tc.function.name == "write_report":
                    report = args.get("markdown", "")
                    log(step, "write_report", {}, {"chars": len(report)})
                    result = {"ok": True}
                else:
                    result = call_tool(tb, tc.function.name, args)
                    log(step, tc.function.name, args, result)
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(result, ensure_ascii=False)})
            if report is not None:
                break

    (out_dir / "trace.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(report or "(리포트 없음)", encoding="utf-8")
    print(f"\n\n===== 리포트 =====\n{report}\n")
    print(f"페르소나 새 응답 {llm.api_calls}개 (예산 {a.budget}, 남음 {tb.budget_left})\n저장: {out_dir}")


if __name__ == "__main__":
    main()
