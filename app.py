"""칠성 버추얼 마켓(가칭) — AI 페르소나 신제품 가상시장 검증 데모.

실행:  streamlit run app.py
배포(Streamlit Community Cloud): Secrets에 OPENAI_API_KEY, APP_PASSWORD 를 넣으면
       비밀번호를 아는 사람만 실제 실행(비용 발생)을 할 수 있고, 나머지는 저장된 결과만 봅니다.
"""
import copy
import glob
import json
import os
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from vm.config import OUT_DIR, PERSONA_PATH

st.set_page_config(page_title="칠성 버추얼 마켓", page_icon="🥤", layout="wide")

# ------------------------------------------------------------------ 배포 설정
try:  # Streamlit Cloud의 Secrets → 환경변수 (로컬에서는 .env 사용)
    for k in ("OPENAI_API_KEY", "VM_MODEL", "VM_AGENT_MODEL"):
        if k in st.secrets and not os.getenv(k):
            os.environ[k] = st.secrets[k]
    APP_PASSWORD = st.secrets.get("APP_PASSWORD", "")
except Exception:
    APP_PASSWORD = ""

from vm.llm import LLM  # noqa: E402  (환경변수 설정 뒤에 불러온다)
from vm.orchestrator import run_agent  # noqa: E402
from vm.personas import download_pool, load_pool, sample_panel  # noqa: E402
from vm.simulate import load_scenario, run, shares_of  # noqa: E402

# ------------------------------------------------------------------ 디자인
# 색·글씨 크기는 여기서만 바꾸면 화면 전체에 적용된다. (rem = 본문 글씨 크기 배수, 1rem ≈ 16px)
RED, RED_DARK, BG, PANEL, BORDER, MUTED = "#E4002B", "#7A0016", "#0A0A0C", "#141418", "rgba(255,255,255,0.08)", "#A1A1AA"
CSS = f"""
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;900&display=swap" rel="stylesheet">
<style>
html, body, [class*="css"], .stMarkdown, .stText, button, input, textarea {{ font-family: 'Noto Sans KR', sans-serif !important; }}
[data-testid="stAppViewContainer"] {{ background:
    radial-gradient(1200px 500px at 50% -200px, rgba(228,0,43,0.18), transparent 70%), {BG}; }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stSidebar"] {{ background: #0F0F13; border-right: 1px solid {BORDER}; }}
.block-container {{ padding-top: 2.2rem; max-width: 1200px; }}
h1 {{ font-size: 1.55rem !important; font-weight: 800 !important; letter-spacing: -0.02em; }}
h2 {{ font-size: 1.3rem !important; font-weight: 700 !important; letter-spacing: -0.01em; }}
h3 {{ font-size: 1.12rem !important; font-weight: 700 !important; }}
h4, h5 {{ font-size: 1.0rem !important; }}
p, li {{ line-height: 1.7; }}
/* 히어로 */
.hero {{ padding: 2.2rem 2.4rem; border-radius: 22px; margin-bottom: 1.4rem; border: 1px solid {BORDER};
         background: radial-gradient(600px 260px at 15% 0%, rgba(228,0,43,0.35), transparent 70%),
                     linear-gradient(135deg, #1A0A0F 0%, {PANEL} 60%); }}
.eyebrow {{ color: {RED}; font-weight: 700; letter-spacing: 0.14em; font-size: 0.78rem; text-transform: uppercase; }}
.hero h1 {{ font-size: 2.1rem !important; margin: 0.35rem 0 0.5rem 0; font-weight: 900 !important; }}
.hero p {{ color: #D4D4D8; margin: 0; font-size: 1.0rem; }}
.chip {{ display:inline-block; padding: 0.22rem 0.7rem; margin: 0.9rem 0.4rem 0 0; border-radius: 999px;
         border: 1px solid rgba(228,0,43,0.45); color:#FCA5B1; font-size: 0.8rem; background: rgba(228,0,43,0.08); }}
/* 카드 */
.card {{ background: linear-gradient(180deg, #1A1014 0%, {PANEL} 100%); border: 1px solid {BORDER};
         border-radius: 18px; padding: 1.2rem 1.3rem; height: 100%; }}
.card .num {{ font-size: 1.9rem; font-weight: 900; color: #fff; letter-spacing: -0.02em; }}
.card .lbl {{ color: {MUTED}; font-size: 0.85rem; margin-bottom: 0.2rem; }}
.card .sub {{ color: #FCA5B1; font-size: 0.8rem; margin-top: 0.15rem; }}
.card h4 {{ margin: 0.2rem 0 0.4rem 0; }}
.card p {{ color: #C4C4CC; font-size: 0.9rem; margin: 0; }}
.icon {{ width: 42px; height: 42px; border-radius: 50%; display:flex; align-items:center; justify-content:center;
         background: radial-gradient(circle, rgba(228,0,43,0.45), rgba(228,0,43,0.08)); font-size: 1.2rem; margin-bottom: .6rem; }}
.step {{ border-left: 2px solid {RED}; padding: 0.35rem 0 0.35rem 0.9rem; margin: 0.2rem 0 0.2rem 0.3rem; }}
.step b {{ color: #fff; }} .step span {{ color: {MUTED}; font-size: 0.85rem; }}
.section-title {{ font-size: 1.25rem; font-weight: 800; margin: 0.6rem 0 0.2rem 0; }}
.muted {{ color: {MUTED}; font-size: 0.88rem; }}
/* 탭·버튼·지표 */
.stTabs [data-baseweb="tab-list"] {{ gap: 0.3rem; border-bottom: 1px solid {BORDER}; }}
.stTabs [data-baseweb="tab"] {{ padding: 0.6rem 1rem; border-radius: 10px 10px 0 0; font-weight: 600; }}
.stTabs [aria-selected="true"] {{ background: rgba(228,0,43,0.12); }}
[data-testid="stBaseButton-primary"], .stButton button[kind="primary"] {{ background: {RED}; border: none; font-weight: 700; border-radius: 10px; }}
[data-testid="stMetric"] {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 16px; padding: 0.9rem 1rem; }}
[data-testid="stMetricValue"] {{ font-size: 1.6rem !important; font-weight: 800; }}
[data-testid="stExpander"] {{ border: 1px solid {BORDER}; border-radius: 14px; }}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def card(label, value, sub=""):
    return f'<div class="card"><div class="lbl">{label}</div><div class="num">{value}</div><div class="sub">{sub}</div></div>'


def feature(icon, title, text):
    return f'<div class="card"><div class="icon">{icon}</div><h4>{title}</h4><p>{text}</p></div>'


# ------------------------------------------------------------------ 데이터
BASE = load_scenario("config/scenario_example.json")
CONCEPT_ID = BASE["concept_id"]
TOOL_LABEL = {"check_reliability": "신뢰도 확인", "run_shelf_simulation": "진열대 시뮬레이션",
              "compare_prices": "가격 비교 실험", "compare_concepts": "문구 A/B 비교",
              "get_reasons": "구매·비구매 이유 확인", "write_report": "리포트 작성"}


@st.cache_resource(show_spinner="페르소나 풀 준비 중… (처음 한 번, 약 1분)")
def pool():
    if not PERSONA_PATH.exists():  # 배포 환경에서는 처음 실행 때 내려받는다
        download_pool(1)
    return load_pool()


def scenario_with(name, desc, price, volume):
    sc = copy.deepcopy(BASE)
    for p in sc["products"]:
        if p["id"] == CONCEPT_ID:
            p.update({"name": name, "description": desc, "price": int(price), "volume_ml": int(volume)})
    return sc


def run_label(path: str) -> str:
    """저장된 실행을 '날짜 시각 · 요청 요약'으로 보여준다."""
    p = Path(path)
    stamp = p.name.replace("agent_", "").replace("_mock", "")
    when = f"{stamp[4:6]}/{stamp[6:8]} {stamp[9:11]}:{stamp[11:13]}" if len(stamp) >= 13 else p.name
    title = ""
    if (p / "request.json").exists():
        title = json.loads((p / "request.json").read_text(encoding="utf-8")).get("request", "")
    elif (p / "report.md").exists():
        first = (p / "report.md").read_text(encoding="utf-8").strip().splitlines()[:1]
        title = first[0].lstrip("# ").strip() if first else ""
    title = title if len(title) <= 40 else title[:40] + "…"
    return f"{when} · {title or '(제목 없음)'}" + (" [mock]" if p.name.endswith("_mock") else "")


def latest(pattern):
    files = sorted(f for f in glob.glob(str(OUT_DIR / pattern)) if "_mock" not in f)
    return files[-1] if files else None


def can_run(mock: bool) -> bool:
    """실제 실행(비용 발생) 권한: 로컬이거나, 배포에서 비밀번호를 맞힌 경우."""
    if mock or not APP_PASSWORD:
        return True
    return st.session_state.get("pw_ok", False)


# ------------------------------------------------------------------ 사이드바
with st.sidebar:
    st.markdown('<div class="eyebrow">Concept Card</div>', unsafe_allow_html=True)
    st.markdown("### 신제품 컨셉")
    c = next(p for p in BASE["products"] if p["id"] == CONCEPT_ID)
    name = st.text_input("제품명", c["name"])
    desc = st.text_area("설명·문구", c["description"], height=80)
    col1, col2 = st.columns(2)
    price = col1.number_input("가격(원)", 500, 10000, c["price"], step=100)
    volume = col2.number_input("용량(ml)", 100, 2000, c["volume_ml"], step=50)
    st.markdown("### 타깃 패널")
    age = st.slider("연령(만)", 19, 80, (20, 39))
    sex = st.radio("성별", ["전체", "남자", "여자"], horizontal=True)
    region = st.radio("지역", ["전체", "수도권", "비수도권"], horizontal=True)
    single = st.checkbox("1인 가구만")
    st.caption("경쟁 진열대: " + " · ".join(f"{p['name']} {p['price']:,}원"
                                          for p in BASE["products"] if p["id"] != CONCEPT_ID))
    st.divider()
    mock = st.toggle("API 없이 시험(mock)", value=False, help="가짜 응답으로 화면과 흐름만 확인합니다. 수치는 의미 없음.")
    if APP_PASSWORD and not mock:
        pw = st.text_input("실행 비밀번호", type="password", help="공개 데모에서는 저장된 결과만 볼 수 있습니다.")
        st.session_state["pw_ok"] = (pw == APP_PASSWORD)
    scenario = scenario_with(name, desc, price, volume)
    seg = {"sex": None if sex == "전체" else sex, "region": None if region == "전체" else region, "single_only": single}

# ------------------------------------------------------------------ 히어로
st.markdown(f"""
<div class="hero">
  <div class="eyebrow">LOTTE AX Challenge 2026 · 과제 1 · AI 페르소나 기반 신제품 시장 검증</div>
  <h1>칠성 버추얼 마켓</h1>
  <p>실제 인구 분포를 따르는 AI 소비자 패널이 신제품 컨셉에 반응하고, 그 결과를 <b>어디까지 믿을 수 있는지</b> 실제 정부 설문으로 검증해 함께 보여줍니다.</p>
  <span class="chip">합성 페르소나 100만 명 풀</span><span class="chip">실제 설문 1.7만 명으로 검증</span>
  <span class="chip">AI 에이전트 자동 실험·리포트</span><span class="chip">실제 조사 앞단 필터</span>
</div>""", unsafe_allow_html=True)

tabs = st.tabs(["① 컨셉 검증 · AI 에이전트", "② 진열대 시뮬레이션", "③ 신뢰도 검증", "④ 서비스 구조·운영", "⑤ 한계와 로드맵"])

# ------------------------------------------------------------------ ① 에이전트
with tabs[0]:
    st.markdown('<div class="section-title">시장 검증 에이전트</div>', unsafe_allow_html=True)
    st.markdown('<p class="muted">질문을 받으면 에이전트가 스스로 계획 → 도구 실행 → 결과 확인 → 추가 실험 → 리포트 작성까지 진행합니다.</p>',
                unsafe_allow_html=True)
    default_q = f"{age[0]}~{age[1]}세 대상 '{name}', {price:,}원이 적당한지 검토해줘"
    question = st.text_area("요청", default_q, height=70)
    cb1, cb2 = st.columns([1, 3])
    budget = cb1.number_input("예산(페르소나 호출 수)", 50, 600, 150, step=50)
    cb2.caption("예산 = 이번 실행에서 새로 물어볼 수 있는 페르소나 응답 수(= API 호출 수). 이미 물어본 응답은 캐시로 재사용합니다.")

    if st.button("에이전트 실행", type="primary", disabled=not can_run(mock)):
        pool()
        with st.status("에이전트 실행 중…", expanded=True) as status:
            def on_step(step, tool, args, result):
                label = TOOL_LABEL.get(tool, tool)
                if "error" in result:
                    st.markdown(f'<div class="step"><b>[{step}] {label}</b><br><span>⚠ {result["error"]}</span></div>',
                                unsafe_allow_html=True)
                else:
                    detail = ""
                    if "buy_share_%" in result:
                        detail = f"신제품 구매 {result['buy_share_%'].get(name, '-')}% · 지불의사 {result.get('concept_wtp_median', '-'):,}원"
                    elif "results" in result:
                        detail = " / ".join(f"{r['label']}: {list(r['buy_share_%'].values())[0]}%" for r in result["results"])
                    st.markdown(f'<div class="step"><b>[{step}] {label}</b><br><span>{json.dumps(args, ensure_ascii=False) if args else ""} {detail}</span></div>',
                                unsafe_allow_html=True)
            try:
                res = run_agent(question, scenario, budget=int(budget), mock=mock, on_step=on_step)
                status.update(label=f"완료 · 새 페르소나 응답 {res['api_calls']}개 (예산 {res['budget']})", state="complete")
                st.session_state["agent_result"] = res
            except Exception as e:
                status.update(label="실패", state="error")
                st.error(f"{type(e).__name__}: {e}")
    if not can_run(mock):
        st.caption("🔒 공개 데모에서는 실행이 잠겨 있습니다. 아래 '저장된 결과 보기'로 이전 실행을 확인하세요.")

    with st.expander("저장된 결과 보기 (API 없이 시연할 때)"):
        runs = sorted(glob.glob(str(OUT_DIR / "agent_*")), reverse=True)
        pick = st.selectbox("이전 실행", runs, format_func=run_label) if runs else None
        if pick and st.button("불러오기"):
            st.session_state["agent_result"] = {
                "report": Path(pick, "report.md").read_text(encoding="utf-8"),
                "trace": json.loads(Path(pick, "trace.json").read_text(encoding="utf-8")), "out_dir": pick}
        if not runs:
            st.caption("아직 저장된 실행이 없습니다.")

    res = st.session_state.get("agent_result")
    if res:
        st.markdown("---")
        with st.container(border=True):
            st.markdown(res["report"] or "(리포트 없음)")
        with st.expander("에이전트가 실행한 단계 (trace)"):
            for t in res["trace"]:
                st.markdown(f"**[{t['step']}] {TOOL_LABEL.get(t['tool'], t['tool'])}** `{json.dumps(t['args'], ensure_ascii=False)}`")
                st.json(t["result"], expanded=False)
        st.caption(f"저장 위치: {res['out_dir']}")

# ------------------------------------------------------------------ ② 진열대
with tabs[1]:
    st.markdown('<div class="section-title">가상 진열대 시뮬레이션</div>', unsafe_allow_html=True)
    st.markdown('<p class="muted">각 페르소나에게 "이 프로필과 비슷한 100명이 이 진열대 앞에서 어떻게 나뉠지"를 묻고 평균합니다. '
                '한 사람에게 답 하나를 받으면 대표 답으로 쏠리는 문제가 있어 이 방식을 채택했습니다(③ 참고).</p>', unsafe_allow_html=True)
    n = st.slider("패널 인원", 10, 100, 50, step=10)
    if st.button("시뮬레이션 실행", type="primary", disabled=not can_run(mock)):
        try:
            panel = sample_panel(pool(), n, 42, age[0], age[1], **seg)
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
        cname = names[CONCEPT_ID]
        share = shares_of(ok, sc).rename(index=names).mul(100).round(1)
        wtp = int(ok[f"max_price_{CONCEPT_ID}"].median())
        cprice = next(p["price"] for p in sc["products"] if p["id"] == CONCEPT_ID)
        k1, k2, k3 = st.columns(3)
        k1.markdown(card("신제품 구매 비율", f"{share[cname]:.1f}%", f"1위 {share.idxmax()} {share.max():.1f}%"), unsafe_allow_html=True)
        k2.markdown(card("앞으로 사 볼 의향", f"{ok[f'try_{CONCEPT_ID}'].mean() * 100:.1f}%", "제품을 한 번이라도 사 볼 사람 비율"), unsafe_allow_html=True)
        k3.markdown(card("지불의사가격(중앙값)", f"{wtp:,}원", f"판매가 {cprice:,}원 대비 {wtp - cprice:+,}원"), unsafe_allow_html=True)
        st.write("")
        bars = share.reset_index().rename(columns={"index": "제품", 0: "비율"})
        bars.columns = ["제품", "비율"]
        bars["구분"] = bars["제품"].map(lambda x: "신제품" if x == cname else ("구매 안 함" if x == "구매 안 함" else "경쟁 제품"))
        chart = alt.Chart(bars).mark_bar(cornerRadiusEnd=6, height=26).encode(
            x=alt.X("비율:Q", title="구매 비율(%)"), y=alt.Y("제품:N", sort="-x", title=None),
            color=alt.Color("구분:N", scale=alt.Scale(domain=["신제품", "경쟁 제품", "구매 안 함"],
                                                     range=[RED, "#52525B", "#27272A"]), legend=None),
            tooltip=["제품", "비율"]).properties(height=230)
        st.altair_chart(chart.configure_view(strokeWidth=0).configure_axis(labelColor="#D4D4D8", titleColor=MUTED,
                                                                            gridColor="#27272A"), width="stretch")
        st.markdown("**연령대별 신제품 구매 비율(%)**")
        st.dataframe(ok.groupby("age_group", observed=True)[f"p_{CONCEPT_ID}"].mean().mul(100).round(1)
                     .rename("구매 비율(%)").to_frame().T, hide_index=True)
        with st.expander("구매·비구매 이유 표본"):
            for r in ok.sample(min(8, len(ok)), random_state=0).itertuples():
                st.markdown(f"- **{r.age_group} {r.sex}** · {r.reason}")
        st.caption(f"응답 {len(ok)}/{len(df)}명 · 새 API 호출 {calls}회")

# ------------------------------------------------------------------ ③ 신뢰도
with tabs[2]:
    st.markdown('<div class="section-title">이 패널을 어디까지 믿을 수 있나</div>', unsafe_allow_html=True)
    st.markdown('<p class="muted">공개된 실제 정부 설문(한국농촌경제연구원 식품소비행태조사 2023~2025, 성인 약 1.7만 명)과 '
                '같은 질문을 페르소나에게 묻고 비교했습니다. 평가 규칙은 실행 전에 정해 두었습니다.</p>', unsafe_allow_html=True)
    f = latest("survey_*/comparison.csv")
    if not f:
        st.info("설문 재현 결과가 없습니다. 터미널에서 `python -m vm.survey --n-per-age 30` 을 실행하세요.")
    else:
        t = pd.read_csv(f, index_col=0)
        if "prob" in t.index and "base" in t.index:
            k1, k2, k3, k4 = st.columns(4)
            k1.markdown(card("탄산·이온 선호 오차", f"{t.loc['prob', 'four_rate_mae']:.1f}%p",
                             f"기본 방식 {t.loc['base', 'four_rate_mae']:.1f}%p"), unsafe_allow_html=True)
            k2.markdown(card("연령 방향 일치도", f"{t.loc['prob', 'four_age_corr']:.2f}",
                             f"기본 방식 {t.loc['base', 'four_age_corr']:.2f}"), unsafe_allow_html=True)
            k3.markdown(card("1순위 음료 분포 오차", f"{t.loc['prob', 'fav_mae']:.1f}%p",
                             f"무작위 {t.loc['무작위 기준선', 'fav_mae']:.1f} · 실제끼리 1.2~1.8"), unsafe_allow_html=True)
            k4.markdown(card("검증 문항 오차", f"{t.loc['prob', 'zero_mae(검증)']:.1f}%p",
                             f"설정 선택에 미사용 · 기본 {t.loc['base', 'zero_mae(검증)']:.1f}"), unsafe_allow_html=True)
        ages = ["20대 이하", "30대", "40대", "50대", "60대 이상"]
        rows = [(r, lbl) for r, lbl in [("실제(KREI)", "실제 설문"), ("prob", "100명 분포 응답(채택)"), ("base", "기본 방식")] if r in t.index]
        long = pd.DataFrame([{"연령": a, "구분": lbl, "비율": t.loc[r, f"four_{a}"]} for r, lbl in rows for a in ages])
        line = alt.Chart(long).mark_line(point=alt.OverlayMarkDef(size=70), strokeWidth=3).encode(
            x=alt.X("연령:N", sort=ages, title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("비율:Q", title="탄산·이온 음료 1순위 비율(%)"),
            color=alt.Color("구분:N", scale=alt.Scale(domain=[l for _, l in rows],
                                                     range=["#F4F4F5", RED, "#71717A"][:len(rows)]),
                            legend=alt.Legend(orient="top", title=None, labelColor="#D4D4D8")),
            strokeDash=alt.condition(alt.datum.구분 == "기본 방식", alt.value([5, 4]), alt.value([0])),
            tooltip=["연령", "구분", "비율"]).properties(height=320)
        st.write("")
        st.altair_chart(line.configure_view(strokeWidth=0).configure_axis(labelColor="#D4D4D8", titleColor=MUTED,
                                                                           gridColor="#27272A"), width="stretch")
        c1, c2 = st.columns(2)
        c1.markdown(feature("🎯", "무엇을 발견했나",
                            "한 사람에게 답 하나를 받으면 '가장 그럴듯한 답'으로 쏠려 커피·녹차가 과다하고 우유류는 0명이었습니다. "
                            "실제 설문과의 오차가 무작위로 찍은 것보다 컸습니다."), unsafe_allow_html=True)
        c2.markdown(feature("🛠", "어떻게 고쳤나",
                            "'비슷한 사람 100명이 어떻게 나뉠지'를 묻는 방식으로 바꾸자 탄산·이온 음료 선호가 연령별로 실제와 1~4%p 안에 들어왔고, "
                            "설정 선택에 쓰지 않은 검증 문항에서도 개선됐습니다."), unsafe_allow_html=True)
        with st.expander("전체 비교표"):
            st.dataframe(t)
        st.caption(f"결과 파일: {f}")

# ------------------------------------------------------------------ ④ 서비스 구조
with tabs[3]:
    st.markdown('<div class="section-title">서비스 아키텍처</div>', unsafe_allow_html=True)
    st.graphviz_chart(f"""
digraph G {{
  rankdir=LR; bgcolor="transparent"; nodesep=0.35; ranksep=0.5;
  node [shape=box style="rounded,filled" fontname="Noto Sans KR" fontsize=13 color="#3F3F46" fillcolor="#18181B" fontcolor="#F4F4F5"];
  edge [color="#71717A" fontname="Noto Sans KR" fontsize=9 fontcolor="#A1A1AA"];
  user [label="마케터\\n컨셉·질문 입력" fillcolor="{RED_DARK}" color="{RED}"];
  agent [label="시장 검증 에이전트\\n계획 · 도구 선택 · 리포트" fillcolor="#2A0A12" color="{RED}"];
  subgraph cluster_tools {{ label="도구" fontcolor="#A1A1AA" color="#27272A" style="rounded";
    tools [label="진열대 시뮬레이션\\n가격 비교 · 문구 A/B\\n이유 분석"]; rel [label="신뢰도 확인"]; }}
  engine [label="페르소나 시뮬레이션 엔진\\n100명 분포 응답 · 블라인드 진열"];
  llm [label="LLM\\n(사내 모델로 교체 가능)"]; cache [label="응답 캐시 · 실행 기록\\n재현성 · 비용 절감"];
  subgraph cluster_data {{ label="데이터" fontcolor="#A1A1AA" color="#27272A" style="rounded";
    persona [label="합성 페르소나 풀\\nNemotron-Personas-Korea"]; krei [label="실제 설문\\nKREI 식품소비행태조사"];
    lotte [label="롯데칠성 판매·조사\\n(연결 예정)" style="rounded,dashed" fontcolor="#A1A1AA"]; }}
  report [label="리포트\\n수치 · 신뢰도 · 한계" fillcolor="{RED_DARK}" color="{RED}"];
  user -> agent -> tools -> engine -> llm -> cache;
  agent -> rel; persona -> engine; krei -> rel; lotte -> rel [style=dashed label="보정"];
  agent -> report;
}}""", width="stretch")
    st.markdown('<div class="section-title">운영 프로세스</div>', unsafe_allow_html=True)
    steps = [("1", "📝", "컨셉 입력", "제품명·맛·가격·문구를 컨셉 카드로 입력"),
             ("2", "👥", "타깃 패널", "연령·성별·지역·가구로 패널 구성"),
             ("3", "🤖", "에이전트 실험", "시뮬레이션·가격·문구 비교를 자동 실행"),
             ("4", "📊", "리포트·신뢰도", "수치와 함께 '어디까지 믿을지' 확인"),
             ("5", "✅", "상위안만 실제 조사", "걸러진 1~2안만 FGI·설문으로"),
             ("6", "🔁", "결과로 보정", "실제 조사 결과를 다시 검증 데이터로")]
    for row in (steps[:3], steps[3:]):
        cols = st.columns(3)
        for col, (no, icon, title, text) in zip(cols, row):
            col.markdown(feature(icon, f"{no}. {title}", text), unsafe_allow_html=True)
        st.write("")
    st.write("")
    st.markdown('<div class="section-title">롯데칠성음료에서 쓰일 곳</div>', unsafe_allow_html=True)
    u = st.columns(3)
    u[0].markdown(feature("🧪", "컨셉 스크리닝", "수십 개 컨셉 후보를 하루 안에 걸러 FGI·설문 대상 수를 줄임"), unsafe_allow_html=True)
    u[1].markdown(feature("💰", "가격대 탐색", "같은 패널로 가격만 바꿔 구매 비율·지불의사가격 변화를 비교"), unsafe_allow_html=True)
    u[2].markdown(feature("✍️", "네이밍·카피 A/B", "이름·문구만 바꾼 안을 같은 패널에 비교해 방향을 좁힘"), unsafe_allow_html=True)
    u = st.columns(3)
    u[0].markdown(feature("🎯", "타깃 탐색", "연령·성별·지역·1인 가구별로 어디서 반응이 좋은지 확인"), unsafe_allow_html=True)
    u[1].markdown(feature("🔄", "자사 제품 잠식 확인", "진열대에 자사 기존 제품을 함께 두고 신제품이 어디서 점유를 가져오는지 확인"), unsafe_allow_html=True)
    u[2].markdown(feature("🧓", "모으기 어려운 집단", "FGI로 모으기 어려운 고령층·지방 거주자 반응을 미리 점검"), unsafe_allow_html=True)

# ------------------------------------------------------------------ ⑤ 한계
with tabs[4]:
    st.markdown('<div class="section-title">한계와 로드맵</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    c1.markdown(feature("✅", "지금 알 수 있는 것",
                        "연령대별 음료 선호의 방향과 대략적인 크기(탄산·이온 선호는 실제 설문과 연령별 1~4%p), "
                        "같은 패널에서 가격·문구를 바꿨을 때의 상대적 반응 차이"), unsafe_allow_html=True)
    c2.markdown(feature("⚠️", "조심해야 할 것",
                        "전체 음료 분포 오차(약 3.4%p)는 실제 설문끼리 차이(1.2~1.8%p)의 약 2배입니다. "
                        "3%p 미만 차이는 단정하지 않습니다. 검증 기준은 '좋아하는 음료' 설문이라 실제 구매와 다를 수 있고, "
                        "합성 페르소나에는 음료 습관·소득·브랜드 충성도 정보가 없습니다."), unsafe_allow_html=True)
    st.write("")
    st.markdown("**발견한 LLM 편향과 대응** — 같은 성향을 세 번 확인했습니다")
    st.dataframe(pd.DataFrame([
        ["진열대(첫 실행)", "무가당 탄산수 79% 쏠림, 5점 응답 0건", "대조실험으로 원인 분리 → 100명 분포 응답"],
        ["설문 재현", "녹차·커피 과다, 우유류 0명, '먹어본 적 없음' 실종", "100명 분포 응답 + 실제 설문으로 검증"],
        ["캡스톤 연구", "상권 방문 토요일 74%(실제 11.7%)", "시간·요일은 실데이터로 고정"],
    ], columns=["실험", "나타난 편향", "대응"]), hide_index=True, width="stretch")
    st.markdown("**로드맵**")
    r = st.columns(4)
    r[0].markdown(feature("1", "롯데칠성 데이터 연결", "판매·조사 데이터로 패널 비율 조정과 결과 보정"), unsafe_allow_html=True)
    r[1].markdown(feature("2", "사후 검증", "과거 출시 제품을 시뮬레이션해 실제 성과 순위와 비교"), unsafe_allow_html=True)
    r[2].markdown(feature("3", "보안", "사내 데이터는 사내 배포형 모델로 교체(구조상 교체 가능)"), unsafe_allow_html=True)
    r[3].markdown(feature("4", "확산", "같은 구조로 다른 식품·유통 계열사 신제품 검증"), unsafe_allow_html=True)
