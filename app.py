"""칠성 버추얼 마켓(가칭) 데모 화면.

실행:  streamlit run app.py
- API 없이 화면만 보려면 왼쪽의 'API 없이 시험(mock)'을 켜거나, '저장된 결과 보기'로 이전 실행을 불러온다.
"""
import copy
import glob
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from vm.config import OUT_DIR
from vm.llm import LLM
from vm.orchestrator import run_agent
from vm.personas import load_pool, sample_panel
from vm.simulate import load_scenario, run, shares_of

st.set_page_config(page_title="칠성 버추얼 마켓", page_icon="🥤", layout="wide")
BASE = load_scenario("config/scenario_example.json")
CONCEPT_ID = BASE["concept_id"]
TOOL_LABEL = {"check_reliability": "신뢰도 확인", "run_shelf_simulation": "진열대 시뮬레이션",
              "compare_prices": "가격 비교 실험", "compare_concepts": "문구 A/B 비교",
              "get_reasons": "구매·비구매 이유 확인", "write_report": "리포트 작성"}


@st.cache_resource(show_spinner="페르소나 풀 불러오는 중…")
def pool():
    return load_pool()


def scenario_with(name, desc, price, volume):
    sc = copy.deepcopy(BASE)
    for p in sc["products"]:
        if p["id"] == CONCEPT_ID:
            p.update({"name": name, "description": desc, "price": int(price), "volume_ml": int(volume)})
    return sc


def latest(pattern):
    files = sorted(f for f in glob.glob(str(OUT_DIR / pattern)) if "_mock" not in f)
    return files[-1] if files else None


# ---------------- 사이드바 ----------------
with st.sidebar:
    st.header("🥤 칠성 버추얼 마켓")
    st.caption("AI 페르소나 가상 소비자 패널로 신제품 컨셉을 빠르게 걸러내는 앞단 검증 도구 (프로토타입)")
    mock = st.toggle("API 없이 시험(mock)", value=False, help="가짜 응답으로 화면과 흐름만 확인합니다. 결과 수치는 의미 없음.")
    st.divider()
    st.subheader("신제품 컨셉")
    c = next(p for p in BASE["products"] if p["id"] == CONCEPT_ID)
    name = st.text_input("제품명", c["name"])
    desc = st.text_area("설명·문구", c["description"], height=80)
    col1, col2 = st.columns(2)
    price = col1.number_input("가격(원)", 500, 10000, c["price"], step=100)
    volume = col2.number_input("용량(ml)", 100, 2000, c["volume_ml"], step=50)
    age = st.slider("타깃 연령(만)", 19, 80, (20, 39))
    st.caption("경쟁 진열대: " + ", ".join(f"{p['name']} {p['price']:,}원"
                                         for p in BASE["products"] if p["id"] != CONCEPT_ID))
    scenario = scenario_with(name, desc, price, volume)

tab1, tab2, tab3, tab4 = st.tabs(["① 컨셉 검증 (AI 에이전트)", "② 진열대 시뮬레이션", "③ 신뢰도 검증", "④ 한계와 로드맵"])

# ---------------- ① 에이전트 ----------------
with tab1:
    st.subheader("시장 검증 에이전트")
    st.caption("질문을 받으면 에이전트가 스스로 계획 → 도구 실행 → 결과 확인 → 추가 실험 → 리포트 작성까지 진행합니다.")
    default_q = f"{age[0]}~{age[1]}세 대상 '{name}', {price:,}원이 적당한지 검토해줘"
    question = st.text_area("요청", default_q, height=70)
    cb1, cb2 = st.columns([1, 3])
    budget = cb1.number_input("예산(페르소나 호출 수)", 50, 600, 150, step=50)
    cb2.caption("예산 = 이번 실행에서 새로 물어볼 수 있는 페르소나 응답 수(= API 호출 수). 이미 물어본 응답은 캐시로 재사용합니다.")

    if st.button("에이전트 실행", type="primary"):
        pool()  # 미리 로드
        with st.status("에이전트 실행 중…", expanded=True) as status:
            def on_step(step, tool, args, result):
                label = TOOL_LABEL.get(tool, tool)
                if "error" in result:
                    st.warning(f"[{step}] {label} → {result['error']}")
                else:
                    brief = {k: result[k] for k in ("concept_price", "buy_share_%", "concept_buy_ci95_%")
                             if k in result} if tool == "run_shelf_simulation" else ""
                    st.write(f"**[{step}] {label}**", json.dumps(args, ensure_ascii=False) if args else "", brief or "")
            try:
                res = run_agent(question, scenario, budget=int(budget), mock=mock, on_step=on_step)
                status.update(label=f"완료 · 새 페르소나 응답 {res['api_calls']}개 (예산 {res['budget']})", state="complete")
                st.session_state["agent_result"] = res
            except Exception as e:
                status.update(label="실패", state="error")
                st.error(f"{type(e).__name__}: {e}")

    with st.expander("저장된 결과 보기 (API 없이 시연할 때)"):
        runs = sorted(glob.glob(str(OUT_DIR / "agent_*")), reverse=True)
        pick = st.selectbox("이전 실행", runs, format_func=lambda p: Path(p).name) if runs else None
        if pick and st.button("불러오기"):
            st.session_state["agent_result"] = {
                "report": Path(pick, "report.md").read_text(encoding="utf-8"),
                "trace": json.loads(Path(pick, "trace.json").read_text(encoding="utf-8")), "out_dir": pick}

    res = st.session_state.get("agent_result")
    if res:
        st.divider()
        st.markdown(res["report"] or "(리포트 없음)")
        with st.expander("에이전트가 실행한 단계 (trace)"):
            for t in res["trace"]:
                st.markdown(f"**[{t['step']}] {TOOL_LABEL.get(t['tool'], t['tool'])}** `{json.dumps(t['args'], ensure_ascii=False)}`")
                st.json(t["result"], expanded=False)
        st.caption(f"저장 위치: {res['out_dir']}")

# ---------------- ② 진열대 ----------------
with tab2:
    st.subheader("가상 진열대 시뮬레이션")
    st.caption("각 페르소나에게 '이 프로필과 비슷한 100명이 이 진열대 앞에서 어떻게 나뉠지'를 묻고 평균합니다(대표 답 쏠림을 줄이는 방식).")
    n = st.slider("패널 인원", 10, 100, 50, step=10)
    if st.button("시뮬레이션 실행"):
        try:
            panel = sample_panel(pool(), n, 42, age[0], age[1])
            llm = LLM(mock=mock)
            with st.spinner(f"{n}명에게 묻는 중…"):
                df = run(scenario, panel, llm, 42, mode="prob")
            st.session_state["sim"] = (df, scenario, llm.api_calls)
        except Exception as e:
            st.error(f"{type(e).__name__}: {e}")
    if "sim" in st.session_state:
        df, sc, calls = st.session_state["sim"]
        ok = df[df["error"] == ""]
        names = {p["id"]: p["name"] for p in sc["products"]} | {"NONE": "구매 안 함"}
        share = shares_of(ok, sc).rename(index=names).mul(100).round(1)
        m1, m2, m3 = st.columns(3)
        m1.metric("신제품 구매 비율", f"{share[names[CONCEPT_ID]]:.1f}%")
        m2.metric("앞으로 사 볼 의향", f"{ok[f'try_{CONCEPT_ID}'].mean() * 100:.1f}%")
        m3.metric("지불의사가격(중앙값)", f"{int(ok[f'max_price_{CONCEPT_ID}'].median()):,}원",
                  delta=f"{int(ok[f'max_price_{CONCEPT_ID}'].median()) - price:+,}원 vs 판매가", delta_color="off")
        st.bar_chart(share, horizontal=True, y_label="", x_label="구매 비율(%)")
        st.markdown("**연령대별 신제품 구매 비율(%)**")
        st.dataframe(ok.groupby("age_group", observed=True)[f"p_{CONCEPT_ID}"].mean().mul(100).round(1)
                     .rename("구매 비율(%)").to_frame().T, hide_index=True)
        with st.expander("구매·비구매 이유 표본"):
            for r in ok.sample(min(8, len(ok)), random_state=0).itertuples():
                st.markdown(f"- **{r.age_group} {r.sex}** · {r.reason}")
        st.caption(f"응답 {len(ok)}/{len(df)}명 · 새 API 호출 {calls}회")

# ---------------- ③ 신뢰도 ----------------
with tab3:
    st.subheader("이 패널을 어디까지 믿을 수 있나")
    st.caption("공개된 실제 정부 설문(한국농촌경제연구원 식품소비행태조사 2023~2025, 성인 약 1.7만 명)과 같은 질문을 페르소나에게 묻고 비교했습니다.")
    f = latest("survey_*/comparison.csv")
    if not f:
        st.info("설문 재현 결과가 없습니다. 터미널에서 `python -m vm.survey --n-per-age 30` 을 실행하세요.")
    else:
        t = pd.read_csv(f, index_col=0)
        rows = [r for r in ["base", "prob", "무작위 기준선"] if r in t.index]
        a1, a2, a3 = st.columns(3)
        if "prob" in t.index and "base" in t.index:
            a1.metric("1순위 음료 분포 오차", f"{t.loc['prob', 'fav_mae']:.2f}%p",
                      delta=f"{t.loc['prob', 'fav_mae'] - t.loc['base', 'fav_mae']:+.2f}%p vs 기본 방식", delta_color="inverse")
            a2.metric("탄산·이온 선호 비율 오차", f"{t.loc['prob', 'four_rate_mae']:.2f}%p",
                      delta=f"{t.loc['prob', 'four_rate_mae'] - t.loc['base', 'four_rate_mae']:+.2f}%p", delta_color="inverse")
            a3.metric("연령 방향 일치도", f"{t.loc['prob', 'four_age_corr']:.2f}")
        ages = ["20대 이하", "30대", "40대", "50대", "60대 이상"]
        chart = pd.DataFrame({lbl: [t.loc[r, f"four_{a}"] for a in ages] for r, lbl in
                              [("실제(KREI)", "실제 설문"), ("prob", "100명 분포 응답(채택)"), ("base", "기본 방식")]
                              if r in t.index}, index=ages)
        st.markdown("**탄산·이온 음료를 가장 좋아한다고 답한 비율(%) — 연령별**")
        st.line_chart(chart)
        st.dataframe(t.loc[rows + ["실제(KREI)"], ["fav_mae", "four_rate_mae", "four_age_corr", "zero_mae(검증)"]]
                     .rename(columns={"fav_mae": "1순위 분포 오차", "four_rate_mae": "탄산·이온 비율 오차",
                                      "four_age_corr": "연령 방향 일치도", "zero_mae(검증)": "검증 문항 오차"}))
        st.markdown("""
- **기본 방식**(한 사람에게 답 하나)은 대표 답으로 쏠려 무작위보다도 오차가 컸습니다(커피·녹차 과다, 우유류 0명).
- **100명 분포 응답**으로 바꾸자 탄산·이온 음료 선호가 연령별로 실제와 1~4%p 안에 들어왔고, 설정 선택에 쓰지 않은 **검증 문항(제로 음료 빈도)** 에서도 개선됐습니다.
- 참고선: 실제 설문끼리 연도를 바꿔 비교해도 1순위 분포 오차는 1.2~1.8%p 입니다.
""")
        st.caption(f"결과 파일: {f}")

# ---------------- ④ 한계 ----------------
with tab4:
    st.subheader("한계와 로드맵")
    st.markdown("""
**지금 알 수 있는 것**
- 연령대별 음료 선호의 **방향과 대략적인 크기**(탄산·이온 선호는 실제 설문과 연령별 1~4%p)
- 같은 패널에서 **가격·문구를 바꿨을 때의 상대적 반응 차이**

**아직 조심해야 할 것**
- 전체 음료 분포 오차(약 3.4%p)는 실제 설문끼리의 차이(1.2~1.8%p)의 약 2배입니다.
- 3%p 미만의 차이는 단정하지 않습니다. 페르소나 간 신뢰구간은 실제 시장의 오차 범위가 아닙니다.
- 검증 기준은 '좋아하는 음료' 설문입니다. 진열대 앞 실제 구매와는 다를 수 있습니다.
- 기반 페르소나(Nemotron-Personas-Korea)는 국가통계 분포로 만든 합성 데이터라 음료 습관·소득·브랜드 충성도 정보가 없습니다.

**발견한 LLM 편향과 대응** (같은 성향을 세 번 확인)
| 실험 | 나타난 편향 | 대응 |
|---|---|---|
| 진열대(첫 실행) | 무가당 탄산수 79% 쏠림, 5점 응답 0건 | 대조실험으로 원인 분리 → 100명 분포 응답 |
| 설문 재현 | 녹차·커피 과다, 우유류 0명, '먹어본 적 없음' 실종 | 100명 분포 응답 + 실제 설문으로 검증 |
| 캡스톤 연구 | 상권 방문 토요일 74%(실제 11.7%) | 시간·요일은 실데이터로 고정 |

**로드맵**
1. **롯데칠성 데이터 연결**: 판매·소비자조사 데이터로 패널 비율 조정과 결과 보정(설문 재현 모듈에 그대로 연결)
2. **사후 검증**: 과거 출시 제품을 시뮬레이션해 실제 성과 순위와 비교
3. **보안**: 사내 데이터는 사내 배포형 모델로 교체(모델 교체 가능한 구조)
4. **확산**: 같은 구조로 다른 식품·유통 계열사 신제품 검증
""")
