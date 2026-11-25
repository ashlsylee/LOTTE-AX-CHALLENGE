"""시장 검증 에이전트(오케스트레이터).

마케터의 자연어 요청을 받아 LLM이 스스로 계획을 세우고, 아래 도구를 골라 호출하며,
결과를 보고 다음 행동을 정한 뒤 근거가 붙은 리포트를 쓴다(OpenAI tool calling).

도구
- check_reliability   : 설문 재현 검증(KREI 실제 설문 대비) 결과로 이 패널을 어디까지 믿을 수 있는지 확인
- run_shelf_simulation: 가상 진열대 시뮬레이션(100명 분포 응답) — 타깃 연령·가격·문구를 바꿔 실행
- compare_prices      : 같은 패널로 신제품 가격만 바꿔 비교(가격 대조실험)
- compare_concepts    : 같은 패널로 컨셉 문구 A/B 비교
- get_reasons         : 시뮬레이션의 구매·비구매 이유 표본 보기
- run_fgi             : 가상 좌담회(페르소나 4~6명이 라운드별로 대화, 입장 변화 추적)
- suggest_improvements: 비구매 이유를 근거로 개선 컨셉 제안 → compare_concepts로 재검증
- data_warnings       : 등록 자료의 품질·설계 경고(빠른 응답, 표본 치우침, 유도 질문, 광고성 트렌드, 봇 로그 등)
- analyze_concept     : 비슷한 과거 사례·중단 사유(가상 소비자로 확인 가능한지 구분)·트렌드 단계·출시 타이밍·다시 해볼 가치·환산계수
- run_virtual_survey  : 실제 설문과 같은 문항을 신제품과 비교 제품(자사·경쟁)에 같은 방식으로 묻고, 과거 실패 사유를 우려로 점검
- check_cannibalization: 우리 기존 제품을 진열대에 넣고, 신제품이 있을 때와 없을 때 기존 제품 몫이 얼마나 줄어드는지(자사 잠식)
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

from . import datasets
from .config import OUT_DIR, result_files
from .llm import LLM
from .personas import load_pool, sample_panel
from .concept import suggest_improvements
from .fgi import ROUNDS as FGI_ROUNDS
from .fgi import compact as fgi_compact
from .fgi import run_fgi
from .simulate import load_scenario, run, shares_of
from .workflow import panel_sample

MAX_PANEL = 100

AGENT_SYSTEM = """당신은 롯데칠성음료 신제품 기획팀을 돕는 '시장 검증 에이전트'입니다.
AI 페르소나 가상 소비자 패널 도구를 써서 마케터의 질문에 답합니다.

일하는 방식
1. check_reliability와 data_warnings로 패널과 등록 자료를 어디까지 믿을 수 있는지 먼저 확인하세요.
2. analyze_concept으로 비슷한 과거 제품이 있었는지, 왜 단종·중단됐는지, 지금 트렌드 단계와 출시 타이밍은 어떤지 보세요.
   - 중단 사유가 수요·가격·맛처럼 소비자 쪽이면 run_virtual_survey의 concerns에 넣어 지금도 같은 우려가 있는지 확인하세요.
   - 유통·보관·사업성 사유는 가상 소비자로 확인할 수 없습니다. 인프라·내부 확인 과제로 리포트에 남기세요.
   - 사유가 비어 있으면 '사유 미상'으로 쓰고 담당자 확인 질문을 남기세요.
3. run_virtual_survey로 신제품과 비교 제품을 같은 문항으로 평가하세요(competitors를 비우면 판매 자료에서 같은 카테고리 제품을 씁니다).
4. 요청의 핵심 질문(가격·문구·타깃)에 맞는 진열대 실험(run_shelf_simulation, compare_prices, compare_concepts)을 하세요.
   기본 인원은 50명, 예산을 먼저 나눠 계획하세요. 같은 조건을 반복하지 마세요. 예산 부족이면 인원을 줄여 핵심 실험을 다시 시도하세요.
5. 근거에 우리 회사의 비슷한 판매 제품이 있으면 check_cannibalization으로 자사 잠식을 확인하세요(가격은 근거의 실제 단가).
6. 정성적 이유가 필요하면 run_fgi, 개선이 필요하면 suggest_improvements → compare_concepts로 재검증하세요.
7. 타깃에 성별·지역(수도권/비수도권)·1인 가구 조건이 있으면 sex/region/single_only를 쓰세요.
8. 마지막에 반드시 write_report로 한국어 마크다운 리포트를 제출하세요.

리포트 규칙
- 숫자는 반드시 도구 결과에 있는 값만 인용하세요. 추측한 숫자를 만들지 마세요.
- concept_buy_ci95_%는 페르소나들 사이의 의견 일치 범위일 뿐, 실제 시장의 오차 범위가 아닙니다.
  실제와의 오차는 check_reliability의 four_rate_mae(약 2%p)·fav_mae(약 3%p) 수준이므로,
  두 조건의 차이가 [판단 기준]의 값(기본 3%p)보다 작으면 "차이가 뚜렷하지 않다"고 쓰고 단정하지 마세요.
- 연령 표현: '30대'는 30~39세입니다. '20~30대'면 age_min 20, age_max 39.
- FGI 발언은 소수 참여자의 정성적 의견이므로 수치처럼 일반화하지 마세요.
- 구성: 요약(결론 2~3줄) / 과거 사례와 다시 해볼 가치·타이밍 / 가상 설문·진열대 결과(비교 제품 포함) / 타깃·가격·문구 제안 /
  데이터 경고와 신뢰도 / 다음 단계(실제 조사·내부 확인 과제)
- 실제 설문 수치를 인용할 때는 data_warnings의 관련 경고(품질 의심 응답, 표본 치우침, 유도 질문·앵커 가격)를 함께 쓰고,
  원자료와 보정 수치(품질 의심 제외·모집단 가중)를 나란히 적으세요. 자료를 임의로 버렸다고 쓰지 마세요.
- 신뢰도: check_reliability 결과를 근거로, 어느 부분은 믿을 만하고 어느 부분은 조심해야 하는지 쓰세요.
- 트렌드는 근거의 수치(전년 동월 대비 등)만 인용하고, 반짝 유행인지 지속 흐름인지는 근거가 부족하면 보류하세요.
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
            "age_min": {"type": "integer", "description": "만 나이. 예: '20~30대'면 20"},
            "age_max": {"type": "integer", "description": "만 나이. 예: '20~30대'면 39 (30대 = 30~39세)"},
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
                                                                   "description": {"type": "string"},
                                                                   "price": {"type": "integer", "description": "선택. 가격도 바꿀 때"}}}},
            "n": {"type": "integer"}, "age_min": {"type": "integer"}, "age_max": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "get_reasons",
        "description": "가장 최근 시뮬레이션의 구매·비구매 이유 표본을 돌려준다. 비용 없음.",
        "parameters": {"type": "object", "additionalProperties": False, "properties": {
            "limit": {"type": "integer", "description": "최대 개수(기본 15)"}}}}},
    {"type": "function", "function": {
        "name": "run_fgi",
        "description": "가상 좌담회(FGI). 타깃 패널에서 성별·연령이 섞인 k명(기본 5)이 3라운드 동안 서로의 말을 듣고 이야기한다. "
                       "핵심 반응·우려·개선 아이디어·입장 변화(설득 장면) 요약을 돌려준다. 비용 약 k×3+1.",
        "parameters": {"type": "object", "additionalProperties": False, "properties": {
            "k": {"type": "integer", "description": "참여자 수(4~6)"},
            "age_min": {"type": "integer"}, "age_max": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "suggest_improvements",
        "description": "가장 최근 시뮬레이션의 구매·비구매 이유를 근거로 개선 컨셉 2~3안(이름·설명·가격)을 제안한다. 비용 1. "
                       "결과를 compare_concepts에 넣어 재검증할 수 있다.",
        "parameters": {"type": "object", "additionalProperties": False, "properties": {
            "n": {"type": "integer", "description": "개선안 수(2~3)"}}}}},
    {"type": "function", "function": {
        "name": "data_warnings",
        "description": "등록 자료의 품질·설계 경고 목록(심각도 순). 비용 없음.",
        "parameters": {"type": "object", "additionalProperties": False, "properties": {}}}},
    {"type": "function", "function": {
        "name": "analyze_concept",
        "description": "비슷한 과거 사례(판매·단종·개발중단)와 중단 사유 유형, 과거 컨셉테스트 결과, 트렌드 단계·출시 타이밍, "
                       "다시 해볼 가치 판단, 설문→실제 구매경험률 환산계수. 비용 없음.",
        "parameters": {"type": "object", "additionalProperties": False, "properties": {
            "launch": {"type": "string", "description": "출시 예정 월 YYYY-MM(알면)"},
            "storage": {"type": "string", "enum": ["상온", "냉장", "냉동"], "description": "보관 조건"},
            "channels": {"type": "string", "description": "판매 채널(쉼표로)"},
            "keywords": {"type": "string", "description": "추가 검색어(선택)"}}}}},
    {"type": "function", "function": {
        "name": "run_virtual_survey",
        "description": "실제 패널조사와 같은 문항(이해도·호감도·차별성·구매의향·가격수용도, 지불가격, 월 구매, 예상 만족·평점)을 "
                       "신제품과 비교 제품에 같은 방식으로 묻고, concerns(과거 실패 사유 등)마다 망설일 사람 수를 본다. 실제 설문과 같은 항목 비교 포함. 비용 = 인원.",
        "parameters": {"type": "object", "additionalProperties": False, "properties": {
            "competitors": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                       "required": ["name", "price", "description"],
                                                       "properties": {"name": {"type": "string"}, "price": {"type": "integer"},
                                                                      "volume_ml": {"type": "integer"}, "description": {"type": "string"}}},
                            "description": "비교 제품 최대 4개. 비우면 판매 자료의 같은 카테고리 제품"},
            "concerns": {"type": "array", "items": {"type": "string"}, "description": "점검할 우려(최대 5개)"},
            "n": {"type": "integer"}, "age_min": {"type": "integer"}, "age_max": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "check_cannibalization",
        "description": "우리 기존 제품(1~3개)을 진열대에 추가하고, 신제품이 없을 때와 있을 때 같은 패널의 선택을 비교해 "
                       "기존 제품 몫이 얼마나 신제품으로 옮겨 가는지(자사 잠식) 본다. 비용 = 인원 × 2.",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["own_products"], "properties": {
            "own_products": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                        "required": ["name", "price", "description"],
                                                        "properties": {"name": {"type": "string"}, "price": {"type": "integer"},
                                                                       "volume_ml": {"type": "integer"},
                                                                       "description": {"type": "string"}}}},
            "n": {"type": "integer"}, "age_min": {"type": "integer"}, "age_max": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "write_report",
        "description": "최종 리포트(한국어 마크다운)를 제출하고 작업을 끝낸다.",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["markdown"], "properties": {
            "markdown": {"type": "string"}}}}},
]


SEGMENT_PROPS = {
    "sex": {"type": "string", "enum": ["남자", "여자"], "description": "성별 타깃(없으면 생략)"},
    "region": {"type": "string", "enum": ["수도권", "비수도권"], "description": "지역 타깃(없으면 생략)"},
    "single_only": {"type": "boolean", "description": "1인 가구만"},
}
for _t in TOOLS:
    if _t["function"]["name"] in ("run_shelf_simulation", "compare_prices", "compare_concepts", "run_fgi",
                                  "check_cannibalization"):
        _t["function"]["parameters"]["properties"].update(SEGMENT_PROPS)


def _bootstrap_ci(values: pd.Series, n_boot: int = 1000) -> list:
    import numpy as np
    rng = np.random.default_rng(0)
    arr = values.to_numpy()
    means = [rng.choice(arr, size=len(arr), replace=True).mean() for _ in range(n_boot)]
    return [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]


class Toolbox:
    """에이전트가 호출하는 도구. 기존 시뮬레이션 모듈을 그대로 감싼다."""

    def __init__(self, scenario: dict, llm: LLM, budget: int, seed: int = 42, data: dict | None = None,
                 pool: pd.DataFrame | None = None, channel: str = ""):
        self.base_scenario, self.llm, self.seed = scenario, llm, seed
        self.budget_left = budget
        self.pool = load_pool() if pool is None else pool
        self.data = datasets.current() if data is None else data
        self.channel, self.storage, self.launch = channel, "", None
        self.last_df, self.last_scenario = None, scenario
        self.runs = []
        self.quota = None

    # ---------- 공통 ----------
    def _panel(self, n, age_min, age_max, sex=None, region=None, single_only=False):
        n = max(10, min(int(n or 50), MAX_PANEL))
        if self.quota and not any([age_min, age_max, sex, region, single_only]):
            from .connect import quota_panel  # 받은 데이터의 고객 구성대로 패널을 뽑는다
            return quota_panel(self.pool, n, self.quota, self.seed)
        if self.data.get("profiles") and not any([sex, region, single_only]) and (age_min or 19) <= 59:
            # 등록 자료가 있으면 제공 패널의 구매 행동을 붙인 결합 패널을 쓴다(신제품 검토 화면과 같은 방식)
            panel, _, _ = panel_sample(self.pool, n, age_min or 19, age_max or 99, self.seed, self.data)
            return panel
        return sample_panel(self.pool, n, self.seed, age_min, age_max, sex=sex, region=region,
                            single_only=bool(single_only))

    def _charge(self, n_calls: int):
        if n_calls > self.budget_left:
            raise RuntimeError(f"예산 부족: 필요 {n_calls}회, 남은 {self.budget_left}회. 남은 정보로 리포트를 작성하세요.")

    def _simulate(self, scenario, panel, label):
        new_before = self.llm.api_calls
        df = run(scenario, panel, self.llm, self.seed, tag="", mode="prob")
        used = self.llm.api_calls - new_before
        self.budget_left -= used
        self.last_df, self.last_scenario = df, scenario
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
            # 페르소나 단위 부트스트랩 95% 구간(추가 API 비용 없음). 페르소나 간 일치 범위이며 실제 시장 오차가 아니다.
            "concept_buy_ci95_%": [round(v * 100, 1) for v in _bootstrap_ci(ok[f"p_{c}"])],
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
        files = result_files("survey_*/comparison.csv")
        files = [f for f in files if "_mock" not in f]
        if not files:
            return {"status": "검증 결과 없음", "note": "python -m vm.survey 를 먼저 실행해야 신뢰도를 말할 수 있다."}
        t = pd.read_csv(files[-1], index_col=0)
        keep = [r for r in ["prob", "base", "무작위 기준선", "실제(KREI)"] if r in t.index]
        extra = []  # ⑤ 데이터 연결에서 받은 데이터로 한 추가 검증
        for f in result_files("connect_*/result.json")[-3:]:
            r = json.loads(open(f, encoding="utf-8").read())
            if not r.get("mock"):
                extra.append({k: r.get(k) for k in ["question", "mae", "random_mae", "n_ok", "source"]})
        holdout = [json.loads(open(f, encoding="utf-8").read()) for f in result_files("validation_*/result.json")
                   if "_mock" not in f][-1:]
        return {
            "제공 설문 대조(컨셉별 구매의향)": {k: holdout[0][k] for k in ("time", "n", "mae", "baseline_mae", "within_rule",
                                                                    "intent_gap_rule")} if holdout else "아직 실행 안 함",
            "제공 설문 대조 읽는 법": "mae=가상 '사 볼 의향'과 설문 TOP2 차이 평균(%p), baseline_mae=모든 컨셉에 설문 평균 하나만 쓸 때 오차. "
                                 "mae가 baseline보다 작아야 컨셉 간 차이를 구분한다고 볼 수 있다.",
            "추가 검증(받은 데이터)": extra or "없음",
            "source": "KREI 식품소비행태조사 2023~2025 성인(가중), 같은 질문을 페르소나에게 물어 비교",
            "채택 방식": "prob(100명 분포 응답)" if "prob" in t.index else "base",
            "table": t.loc[keep].round(2).where(t.loc[keep].notna(), None).to_dict(orient="index"),
            "읽는 법": "fav_mae=1순위 음료 분포 오차(%p, 실제 조사끼리 연도 비교 시 1.2~1.8), "
                      "four_rate_mae=탄산·이온 4종 선호 비율 오차, four_age_corr=연령 방향 일치도, zero_mae=검증 문항 오차",
        }

    def run_shelf_simulation(self, n=60, age_min=None, age_max=None, concept_price=None,
                             concept_name=None, concept_description=None, **seg):
        panel = self._panel(n, age_min, age_max, **seg)
        self._charge(len(panel))
        sc = self._scenario_with(concept_price, concept_name, concept_description)
        return self._simulate(sc, panel, f"simulation(age {age_min}~{age_max}, price {concept_price})")

    def compare_prices(self, prices, n=60, age_min=None, age_max=None, **seg):
        panel = self._panel(n, age_min, age_max, **seg)
        self._charge(len(panel) * len(prices))
        return {"same_panel": True, "results": [self._simulate(self._scenario_with(price=p), panel, f"price {p}")
                                                for p in prices]}

    def compare_concepts(self, variants, n=60, age_min=None, age_max=None, **seg):
        panel = self._panel(n, age_min, age_max, **seg)
        self._charge(len(panel) * len(variants))
        return {"same_panel": True, "results": [
            self._simulate(self._scenario_with(price=v.get("price"), name=v["name"], description=v["description"]),
                           panel, v["label"])
            for v in variants]}

    def run_fgi(self, k=5, age_min=None, age_max=None, **seg):
        k = max(3, min(int(k or 5), 6))
        self._charge(k * len(FGI_ROUNDS) + 1)
        before = self.llm.api_calls
        res = run_fgi(self.llm, self.base_scenario, self._panel(60, age_min, age_max, **seg), k, self.seed)
        self.budget_left -= self.llm.api_calls - before
        self.last_fgi = res
        return {**fgi_compact(res), "budget_left": self.budget_left}

    def suggest_improvements(self, n=3):
        if self.last_df is None:
            return {"status": "먼저 시뮬레이션을 실행해야 이유를 근거로 개선안을 만들 수 있다"}
        self._charge(1)
        ok = self.last_df[self.last_df["error"] == ""]
        sc = self.base_scenario  # 원래 컨셉을 기준으로 개선안을 만든다(이유는 가장 최근 실행에서)
        concept = next(p for p in sc["products"] if p["id"] == sc["concept_id"])
        before = self.llm.api_calls
        variants = suggest_improvements(self.llm, concept, ok["reason"].astype(str).tolist(), max(2, min(int(n or 3), 3)))
        self.budget_left -= self.llm.api_calls - before
        return {"base": {"name": concept["name"], "price": concept["price"], "description": concept["description"]},
                "variants": variants, "next": "compare_concepts에 base와 variants를 함께 넣어 같은 패널로 비교하세요."}

    def _concept(self):
        return next(p for p in self.base_scenario["products"] if p["id"] == self.base_scenario["concept_id"])

    def data_warnings(self):
        from . import audit
        ws = audit.run_all()
        return {"count": len(ws), "warnings": [{k: w[k] for k in ("영역", "심각도", "내용", "분석 반영")} for w in ws if w["심각도"] != "참고"][:20]}

    def analyze_concept(self, launch=None, storage="", channels="", keywords=""):
        from .workflow import analyze
        c = self._concept()
        self.storage = storage or self.storage
        a = analyze(c["name"], f"{c['description']} {keywords}", launch or self.launch, self.storage, channels or self.channel)
        self.last_analysis = a
        slim = lambda h: {k: v for k, v in h.items() if not k.startswith("_") and k not in ("출처",)}  # noqa: E731
        return {"verdict": a["verdict"], "history": [slim(h) for h in a["history"]], "timing": a["timing"],
                "conversion": a["conversion"]}

    def run_virtual_survey(self, competitors=None, concerns=None, n=40, age_min=None, age_max=None, **seg):
        from . import audit, insight
        from .vsurvey import compare_with_survey, run_survey
        c = self._concept()
        if not competitors:
            competitors = [r for r in insight.competitors(c["name"], c["description"]) if r["price"]][:3] or \
                [p for p in self.base_scenario["products"] if p["id"] != self.base_scenario["concept_id"]][:3]
        products = [c, *[{"name": x["name"], "price": int(x["price"]), "volume_ml": int(x.get("volume_ml") or 500),
                          "description": x.get("description", "")} for x in competitors[:4]]]
        if concerns is None and getattr(self, "last_analysis", None):
            concerns = self.last_analysis["verdict"].get("가상 소비자로 확인할 질문", [])
        panel = self._panel(n, age_min, age_max, **seg)
        self._charge(len(panel))
        before = self.llm.api_calls
        res = run_survey(self.llm, panel, products, self.base_scenario["situation"], concerns or [])
        self.budget_left -= self.llm.api_calls - before
        table = res["summary"]
        cmp = compare_with_survey(table, audit.survey_metrics())
        top2 = float(table.iloc[0]["구매의향 TOP2(%)"]) if not table.empty else None
        conv = insight.conversion(getattr(self, "storage", ""), self.channel)
        return {"n_ok": res["n_ok"], "summary": table.to_dict("records"), "concerns": res["concerns"].to_dict("records"),
                "vs_real_survey": cmp.to_dict("records") if not cmp.empty else "실제 설문에 같은 제품 없음",
                "trial_estimate": insight.estimate_trial(top2, conv) if top2 is not None and conv else None,
                "reasons": res["reasons"][:8], "budget_left": self.budget_left}

    def check_cannibalization(self, own_products, n=50, age_min=None, age_max=None, **seg):
        own = [{"id": f"OWN{i}", "name": p["name"], "price": int(p["price"]), "volume_ml": int(p.get("volume_ml") or 500),
                "description": p["description"]} for i, p in enumerate(own_products[:3], 1)]
        panel = self._panel(n, age_min, age_max, **seg)
        self._charge(len(panel) * 2)
        with_new = copy.deepcopy(self.base_scenario)
        with_new["products"] += own
        without = copy.deepcopy(with_new)
        without["products"] = [p for p in without["products"] if p["id"] != without["concept_id"]]
        without["concept_id"] = own[0]["id"]  # 신제품이 없는 진열대(기준)
        before = self.llm.api_calls
        a = run(without, panel, self.llm, self.seed, mode="prob")
        b = run(with_new, panel, self.llm, self.seed, mode="prob")
        self.budget_left -= self.llm.api_calls - before
        both = (a.error == "") & (b.error == "")
        sa, sb = shares_of(a[both], without), shares_of(b[both], with_new)
        own_ids = [p["id"] for p in own]
        own_before, own_after = float(sa[own_ids].sum() * 100), float(sb[own_ids].sum() * 100)
        new_share = float(sb[with_new["concept_id"]] * 100)
        return {"same_panel": True, "n_ok": int(both.sum()),
                "own_share_without_new_%": round(own_before, 1), "own_share_with_new_%": round(own_after, 1),
                "new_product_share_%": round(new_share, 1),
                "cannibalization_%p": round(own_before - own_after, 1),
                "from_own_ratio_%": round((own_before - own_after) / new_share * 100, 1) if new_share else None,
                "none_share_change_%p": round(float(sb["NONE"] - sa["NONE"]) * 100, 1),
                "읽는 법": "from_own_ratio=신제품 선택 중 우리 기존 제품에서 옮겨 온 비율. 높을수록 잠식이 크다.",
                "budget_left": self.budget_left}

    def get_reasons(self, limit=15):
        if self.last_df is None:
            return {"status": "아직 실행한 시뮬레이션이 없다"}
        ok = self.last_df[self.last_df["error"] == ""]
        sample = ok.sample(n=min(int(limit or 15), len(ok)), random_state=self.seed)
        return {"reasons": [f"[{r.age_group} {r.sex}] {r.reason}" for r in sample.itertuples()]}


def _jsonable(o):
    """numpy 숫자 등 JSON이 모르는 값."""
    try:
        return o.item()
    except AttributeError:
        return str(o)


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
        if name in ("data_warnings", "analyze_concept", "run_virtual_survey"):
            return getattr(tb, name)(**args)
        if name == "check_cannibalization":
            return tb.check_cannibalization(**args)
        if name == "run_fgi":
            return tb.run_fgi(**args)
        if name == "suggest_improvements":
            return tb.suggest_improvements(**args)
        return {"error": f"알 수 없는 도구: {name}"}
    except Exception as e:  # 도구 오류는 에이전트에게 돌려줘 스스로 대응하게 한다
        return {"error": f"{type(e).__name__}: {e}"}


def scripted_plan(request: str):
    """--mock: API 없이 도구 연결만 시험하기 위한 고정 계획."""
    yield "check_reliability", {}
    yield "data_warnings", {}
    yield "analyze_concept", {}
    yield "run_virtual_survey", {"n": 10}
    yield "run_shelf_simulation", {"n": 30, "age_min": 20, "age_max": 39}
    yield "get_reasons", {"limit": 5}
    yield "compare_prices", {"prices": [1700, 1900, 2100], "n": 30, "age_min": 20, "age_max": 39}
    yield "run_fgi", {"k": 4, "age_min": 20, "age_max": 39}
    yield "suggest_improvements", {"n": 2}
    yield "check_cannibalization", {"own_products": [{"name": "우리 기존 제품(가정)", "price": 1800,
                                                     "description": "비교용 기존 제품"}], "n": 20}


def _loop_chat(client, agent_model, context, max_steps, tb, log):
    """Chat Completions 방식 도구 호출 루프."""
    report = None
    messages = [{"role": "system", "content": AGENT_SYSTEM}, {"role": "user", "content": context}]
    for step in range(1, max_steps + 1):
        force = step == max_steps  # 마지막 단계에서는 리포트를 강제
        resp = client.chat.completions.create(
            model=agent_model, messages=messages, tools=TOOLS,
            tool_choice={"type": "function", "function": {"name": "write_report"}} if force else "auto")
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            messages.append({"role": "user", "content": "도구를 호출하거나 write_report로 리포트를 제출하세요."})
            continue
        for k, tc in enumerate(msg.tool_calls, 1):
            args = json.loads(tc.function.arguments or "{}")
            if tc.function.name == "write_report":
                report = args.get("markdown", "")
                log(f"{step}-{k}", "write_report", {}, {"chars": len(report)})
                result = {"ok": True}
            else:
                result = call_tool(tb, tc.function.name, args)
                log(f"{step}-{k}", tc.function.name, args, result)
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result, ensure_ascii=False, default=_jsonable)})
        if report is not None:
            break
    return report


RESPONSES_TOOLS = [{"type": "function", "name": t["function"]["name"], "description": t["function"]["description"],
                    "parameters": t["function"]["parameters"]} for t in TOOLS]


def _loop_responses(client, agent_model, context, max_steps, tb, log):
    """Responses API 방식 도구 호출 루프(대회 게이트웨이 기본)."""
    report = None
    items = [{"role": "user", "content": context}]
    for step in range(1, max_steps + 1):
        force = step == max_steps
        resp = client.responses.create(
            model=agent_model, instructions=AGENT_SYSTEM, input=items, tools=RESPONSES_TOOLS,
            tool_choice={"type": "function", "name": "write_report"} if force else "auto")
        calls = [o for o in resp.output if getattr(o, "type", "") == "function_call"]
        items += [o.model_dump(exclude_none=True) if hasattr(o, "model_dump") else o for o in resp.output]
        if not calls:
            items.append({"role": "user", "content": "도구를 호출하거나 write_report로 리포트를 제출하세요."})
            continue
        for k, c in enumerate(calls, 1):
            args = json.loads(c.arguments or "{}")
            if c.name == "write_report":
                report = args.get("markdown", "")
                log(f"{step}-{k}", "write_report", {}, {"chars": len(report)})
                result = {"ok": True}
            else:
                result = call_tool(tb, c.name, args)
                log(f"{step}-{k}", c.name, args, result)
            items.append({"type": "function_call_output", "call_id": c.call_id,
                          "output": json.dumps(result, ensure_ascii=False, default=_jsonable)})
        if report is not None:
            break
    return report


def run_agent(request: str, scenario: dict, budget: int = 400, max_steps: int = 10, model: str | None = None,
              agent_model: str | None = None, mock: bool = False, on_step=None, api_key: str | None = None,
              quota: dict | None = None, min_diff: float = 3.0, data: dict | None = None,
              pool: pd.DataFrame | None = None, channel: str = "", launch: str | None = None, storage: str = "") -> dict:
    """에이전트 1회 실행. CLI와 화면(app.py)이 같이 쓴다. on_step(step, tool, args, result)로 진행을 알린다."""
    from .config import load_env
    load_env()
    llm = LLM(model, mock=mock, api_key=api_key)
    tb = Toolbox(scenario, llm, budget, data=data, pool=pool, channel=channel)
    tb.launch, tb.storage = launch, storage
    tb.quota = quota
    out_dir = OUT_DIR / f"agent_{datetime.now():%Y%m%d_%H%M%S}{'_mock' if mock else ''}"
    out_dir.mkdir(parents=True)
    trace, report = [], None

    def log(step, name, args, result):
        trace.append({"step": step, "tool": name, "args": args, "result": result})
        if on_step:
            on_step(step, name, args, result)

    if mock:
        for step, (name, args) in enumerate(scripted_plan(request), 1):
            log(f"{step}-1", name, args, call_tool(tb, name, args))
        report = "# (mock) 리포트\n\n도구 연결 시험용 실행입니다. 실제 리포트는 API로 실행하세요.\n"
    else:
        from .llm import make_client
        client = make_client(api_key)
        use_responses = os.getenv("VM_API", "responses").lower() != "chat"
        agent_model = agent_model or os.getenv("VM_AGENT_MODEL") or llm.model
        context = (f"[요청]\n{request}\n\n[기본 시나리오]\n{json.dumps(scenario, ensure_ascii=False)}\n"
                   "※ 검증 대상은 기본 시나리오의 신제품(concept_id)입니다. 요청 문장의 제품명·가격이 시나리오와 다르면 "
                   "리포트 맨 앞에 그 차이를 밝히고, 시나리오 기준으로 진행하세요.\n"
                   f"[판단 기준] 두 조건의 차이가 {min_diff}%p 미만이면 뚜렷한 차이로 보지 않습니다.\n\n"
                   f"[예산] 페르소나 호출 {budget}회, 최대 {max_steps}단계\n"
                   f"[등록 자료] 버전 {tb.data.get('version')} · 판매 채널 {channel or '미지정'} · 출시 예정 {launch or '미정'} · 보관 {storage or '미지정'}")
        if use_responses:
            report = _loop_responses(client, agent_model, context, max_steps, tb, log)
        else:
            report = _loop_chat(client, agent_model, context, max_steps, tb, log)

    (out_dir / "trace.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2, default=_jsonable), encoding="utf-8")
    (out_dir / "report.md").write_text(report or "(리포트 없음)", encoding="utf-8")
    (out_dir / "request.json").write_text(json.dumps({"request": request, "scenario": scenario, "budget": budget},
                                                     ensure_ascii=False, indent=2), encoding="utf-8")
    return {"report": report, "trace": trace, "out_dir": str(out_dir),
            "api_calls": llm.api_calls, "budget_left": tb.budget_left, "budget": budget}


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

    def show(step, name, args, result):
        short = json.dumps(result, ensure_ascii=False, default=_jsonable)
        print(f"\n[{step}] {name}({json.dumps(args, ensure_ascii=False)})\n    → {short[:400]}{'…' if len(short) > 400 else ''}")

    r = run_agent(a.request, load_scenario(a.scenario), a.budget, a.max_steps, a.model, a.agent_model, a.mock, show)
    print(f"\n\n===== 리포트 =====\n{r['report']}\n")
    print(f"페르소나 새 응답 {r['api_calls']}개 (예산 {r['budget']}, 남음 {r['budget_left']})\n저장: {r['out_dir']}")


if __name__ == "__main__":
    main()
