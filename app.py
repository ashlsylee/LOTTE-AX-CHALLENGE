"""프리셸프(PreShelf) — AI 페르소나 신제품 가상시장 검증 데모.

실행:  streamlit run app.py
배포(Streamlit Community Cloud): Secrets에 OPENAI_API_KEY, APP_PASSWORD 를 넣으면
       비밀번호를 아는 사람만 실제 실행(비용 발생)을 할 수 있고, 나머지는 저장된 결과만 봅니다.
"""
import copy
import glob
import json
import re
import os
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from vm.config import OUT_DIR, PERSONA_PATH

# ---- 서비스 이름: 여기 두 줄만 바꾸면 화면 전체(탭 제목, 상단 제목)에 반영된다
APP_NAME = "프리셸프 PreShelf"
APP_TAGLINE = "진열대에 오르기 전에, AI 소비자 패널로 신제품 컨셉을 미리 걸러내고 그 결과를 실제 설문으로 검증해 함께 보여줍니다."
st.set_page_config(page_title=APP_NAME, page_icon="🥤", layout="wide")

# ------------------------------------------------------------------ 배포 설정
from dotenv import load_dotenv  # noqa: E402
load_dotenv()
try:  # Streamlit Cloud의 Secrets → 환경변수 (로컬에서는 .env 사용)
    for k in ("OPENAI_API_KEY", "VM_MODEL", "VM_AGENT_MODEL", "APP_PASSWORD"):
        if k in st.secrets and not os.getenv(k):
            os.environ[k] = st.secrets[k]
except Exception:
    pass
# 서버에 설정된 내 API 키는 이 비밀번호를 아는 사람만 쓸 수 있다(.env 또는 Secrets의 APP_PASSWORD).
# 자기 API 키를 입력한 사람은 비밀번호 없이 실행할 수 있다.
APP_PASSWORD = os.getenv("APP_PASSWORD", "")

from vm.llm import LLM  # noqa: E402  (환경변수 설정 뒤에 불러온다)
from vm.orchestrator import run_agent  # noqa: E402
from vm.personas import download_pool, load_pool, sample_panel  # noqa: E402
from vm.simulate import load_scenario, run, shares_of  # noqa: E402

# ------------------------------------------------------------------ 디자인
# 색·글씨 크기는 여기서만 바꾸면 화면 전체에 적용된다. (rem = 본문 글씨 크기 배수, 1rem ≈ 16px)
# 라이트/다크는 화면 왼쪽 위 버튼으로 바꾼다. Streamlit 기본 테마는 라이트로 고정하고, 다크는 아래 CSS가 덮어쓴다.
RED, RED_DARK = "#E4002B", "#7A0016"
st.session_state.setdefault("theme", "dark")  # 기본은 다크. 왼쪽 위 버튼으로 전환(새로고침 없음)
DARK = st.session_state["theme"] == "dark"
T = dict(  # 테마별 색
    bg="#0A0A0C" if DARK else "#F7F7F8", panel="#141418" if DARK else "#FFFFFF",
    side="#0F0F13" if DARK else "#FFFFFF", border="rgba(255,255,255,0.08)" if DARK else "rgba(0,0,0,0.08)",
    text="#FFFFFF" if DARK else "#18181B", sub="#FFFFFF" if DARK else "#3F3F46", muted="#F4F4F5" if DARK else "#71717A",
    card_top="#1A1014" if DARK else "#FFF5F6", hero_end="#141418" if DARK else "#FFFFFF",
    hero_start="#1A0A0F" if DARK else "#FFE8EC", chip_text="#FCA5B1" if DARK else "#B3001F",
    grid="#27272A" if DARK else "#E4E4E7", node_fill="#18181B" if DARK else "#FFFFFF",
    node_line="#3F3F46" if DARK else "#D4D4D8", shadow="none" if DARK else "0 6px 24px rgba(0,0,0,0.06)",
)
BG, PANEL, BORDER, MUTED = T["bg"], T["panel"], T["border"], T["muted"]
FIELD = "#1C1C22"
DARK_WIDGETS = f"""
[data-testid="stAppViewContainer"], [data-testid="stSidebar"], [data-testid="stHeader"] {{ color: #FFFFFF; }}
[data-testid="stAppViewContainer"] p, [data-testid="stAppViewContainer"] li, [data-testid="stAppViewContainer"] label,
[data-testid="stSidebar"] p, [data-testid="stSidebar"] label, [data-testid="stSidebar"] span,
h1, h2, h3, h4, h5, h6, [data-testid="stCaptionContainer"], .stCaption,
[data-testid="stWidgetLabel"] *, [data-testid="stMarkdownContainer"] {{ color: #FFFFFF !important; }}
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="textarea"], [data-baseweb="select"] > div,
[data-testid="stNumberInput"] > div > div {{ background: {FIELD} !important; border-color: #3F3F46 !important; }}
input, textarea {{ color: #FFFFFF !important; -webkit-text-fill-color: #FFFFFF !important; background: {FIELD} !important; }}
input::placeholder, textarea::placeholder {{ color: #A1A1AA !important; -webkit-text-fill-color: #A1A1AA !important; }}
[data-testid="stNumberInputStepDown"], [data-testid="stNumberInputStepUp"] {{ background: {FIELD} !important; color: #FFFFFF !important; }}
[data-testid="stBaseButton-secondary"] {{ background: {FIELD} !important; color: #FFFFFF !important; border-color: #3F3F46 !important; }}
[data-testid="stExpander"] details, [data-testid="stExpander"] summary {{ background: transparent !important; color: #FFFFFF !important; }}
[data-testid="stExpander"] summary:hover {{ color: {RED} !important; }}
[data-baseweb="popover"] ul, [data-baseweb="menu"], [data-baseweb="popover"] li {{ background: {FIELD} !important; color: #FFFFFF !important; }}
[data-baseweb="tab"] p {{ color: #FFFFFF !important; }}
[data-testid="stSliderTickBarMin"], [data-testid="stSliderTickBarMax"], [data-testid="stSliderThumbValue"] {{ color: #FFFFFF !important; }}
[data-testid="stJson"] {{ background: {FIELD} !important; }}
code {{ background: {FIELD} !important; color: #FFFFFF !important; }}
/* 표(캔버스로 그려져 CSS가 안 먹음)는 색을 반전해 어둡게 */
[data-testid="stDataFrame"], [data-testid="stDataEditor"] {{ filter: invert(0.92) hue-rotate(180deg); border-radius: 10px; }}
[data-testid="stStatusWidget"], [data-testid="stStatus"] {{ color: #FFFFFF !important; }}
[data-testid="stAlertContainer"] {{ background: rgba(255,255,255,0.06) !important; border: 1px solid #3F3F46 !important; }}
[data-testid="stAlertContentSuccess"] ~ *, [data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) {{ border-color: #22C55E !important; }}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) {{ border-color: #F59E0B !important; }}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) {{ border-color: {RED} !important; }}
"""
CSS = f"""
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;900&display=swap" rel="stylesheet">
<style>
html, body, [class*="css"], .stMarkdown, .stText, button, input, textarea {{ font-family: 'Noto Sans KR', sans-serif !important; }}
[data-testid="stAppViewContainer"] {{ background:
    radial-gradient(1200px 500px at 50% -200px, rgba(228,0,43,{0.18 if DARK else 0.08}), transparent 70%), {BG}; }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stSidebar"] {{ background: {T["side"]}; border-right: 1px solid {BORDER}; }}
.block-container {{ padding-top: 2.2rem; max-width: 1200px; }}
h1 {{ font-size: 1.55rem !important; font-weight: 800 !important; letter-spacing: -0.02em; }}
h2 {{ font-size: 1.3rem !important; font-weight: 700 !important; letter-spacing: -0.01em; }}
h3 {{ font-size: 1.12rem !important; font-weight: 700 !important; }}
h4, h5 {{ font-size: 1.0rem !important; }}
p, li {{ line-height: 1.7; }}
/* 히어로 */
.hero {{ padding: 2.2rem 2.4rem; border-radius: 22px; margin-bottom: 1.4rem; border: 1px solid {BORDER}; box-shadow: {T["shadow"]};
         background: radial-gradient(600px 260px at 15% 0%, rgba(228,0,43,{0.35 if DARK else 0.14}), transparent 70%),
                     linear-gradient(135deg, {T["hero_start"]} 0%, {T["hero_end"]} 60%); }}
.eyebrow {{ color: {RED}; font-weight: 700; letter-spacing: 0.14em; font-size: 0.78rem; text-transform: uppercase; }}
.hero h1 {{ font-size: 2.1rem !important; margin: 0.35rem 0 0.5rem 0; font-weight: 900 !important; color: {T["text"]}; }}
.hero p {{ color: {T["sub"]}; margin: 0; font-size: 1.0rem; }}
.chip {{ display:inline-block; padding: 0.22rem 0.7rem; margin: 0.9rem 0.4rem 0 0; border-radius: 999px;
         border: 1px solid rgba(228,0,43,0.45); color:{T["chip_text"]}; font-size: 0.8rem; background: rgba(228,0,43,0.08); }}
/* 카드 */
.card {{ background: linear-gradient(180deg, {T["card_top"]} 0%, {PANEL} 100%); border: 1px solid {BORDER}; box-shadow: {T["shadow"]};
         border-radius: 18px; padding: 1.2rem 1.3rem; height: 100%; }}
.card .num {{ font-size: 1.9rem; font-weight: 900; color: {T["text"]}; letter-spacing: -0.02em; }}
.card .lbl {{ color: {MUTED}; font-size: 0.85rem; margin-bottom: 0.2rem; }}
.card .sub {{ color: {T["chip_text"]}; font-size: 0.8rem; margin-top: 0.15rem; }}
.card h4 {{ margin: 0.2rem 0 0.4rem 0; color: {T["text"]}; }}
.card p {{ color: {T["sub"]}; font-size: 0.9rem; margin: 0; }}
.fi-icon {{ width: 42px; height: 42px; border-radius: 50%; display:flex; align-items:center; justify-content:center;
         background: radial-gradient(circle, rgba(228,0,43,0.45), rgba(228,0,43,0.08)); font-size: 1.2rem; margin-bottom: .6rem; }}
.step {{ border-left: 2px solid {RED}; padding: 0.35rem 0 0.35rem 0.9rem; margin: 0.2rem 0 0.2rem 0.3rem; }}
.step b {{ color: {T["text"]}; }} .step span {{ color: {MUTED}; font-size: 0.85rem; }}
.section-title {{ font-size: 1.25rem; font-weight: 800; margin: 0.6rem 0 0.2rem 0; }}
.muted {{ color: {MUTED}; font-size: 0.88rem; }}
/* FGI 말풍선 */
.bubble {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 14px; padding: 0.7rem 0.9rem; margin: 0.35rem 0; box-shadow: {T["shadow"]}; }}
.bubble .who {{ font-weight: 700; font-size: 0.85rem; color: {T["text"]}; }}
.bubble .txt {{ color: {T["sub"]}; font-size: 0.93rem; margin-top: 0.2rem; }}
.badge {{ display:inline-block; padding: 0.05rem 0.5rem; border-radius: 999px; font-size: 0.72rem; margin-left: 0.4rem; font-weight: 700; }}
.b-buy {{ background: {RED}; color: #fff; }} .b-mid {{ background: rgba(228,0,43,0.15); color: {T["chip_text"]}; }}
.b-no {{ background: {T["grid"]}; color: {T["sub"]}; }}
/* 탭·버튼·지표 */
.stTabs [data-baseweb="tab-list"] {{ gap: 0.3rem; border-bottom: 1px solid {BORDER}; }}
.stTabs [data-baseweb="tab"] {{ padding: 0.6rem 1rem; border-radius: 10px 10px 0 0; font-weight: 600; }}
.stTabs [aria-selected="true"] {{ background: rgba(228,0,43,{0.12 if DARK else 0.07}); }}
[data-testid="stBaseButton-primary"], .stButton button[kind="primary"] {{ background: {RED}; color: #fff; border: none; font-weight: 700; border-radius: 10px; }}
[data-testid="stMetric"] {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 16px; padding: 0.9rem 1rem; }}
[data-testid="stMetricValue"] {{ font-size: 1.6rem !important; font-weight: 800; }}
[data-testid="stExpander"] {{ border: 1px solid {BORDER}; border-radius: 14px; }}
{DARK_WIDGETS if DARK else ""}
/* 한 줄의 카드들은 같은 높이(가장 큰 카드에 맞춤) */
.grid {{ display: grid; gap: 1rem; margin: 0.2rem 0 1rem 0; align-items: stretch; }}
.grid .card {{ height: 100%; box-sizing: border-box; }}
.g2 {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} .g3 {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
.g4 {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }} .g6 {{ grid-template-columns: repeat(6, minmax(0, 1fr)); gap: .5rem; }}
@media (max-width: 900px) {{ .g3, .g4 {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} .g6 {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }} }}
@media (max-width: 600px) {{ .g2, .g3, .g4 {{ grid-template-columns: 1fr; }} }}
.sources {{ margin-top: 1rem; font-size: 0.82rem; color: {T["sub"]}; line-height: 1.8; }}
.sources a {{ color: {T["chip_text"]}; text-decoration: none; border-bottom: 1px solid rgba(228,0,43,0.4); }}
</style>
"""
CSS = "\n".join(line for line in CSS.splitlines() if line.strip())  # 빈 줄이 있으면 스타일 블록이 끊겨 글자로 보인다
st.markdown(CSS, unsafe_allow_html=True)


def style_chart(ch):
    return ch.configure(background="transparent").configure_view(strokeWidth=0).configure_axis(labelColor=T["sub"], titleColor=MUTED, gridColor=T["grid"]
                                                           ).configure_legend(labelColor=T["sub"])


def card(label, value, sub=""):
    return f'<div class="card"><div class="lbl">{label}</div><div class="num">{value}</div><div class="sub">{sub}</div></div>'


def bold(text: str) -> str:
    """**굵게**를 <strong>으로 바꾼다. 마크다운은 '**16.8%**였고'처럼 닫는 ** 앞이 문장부호이고
    뒤에 글자가 붙으면 굵게로 인식하지 못해 **가 그대로 보이기 때문(한국어 조사에서 자주 발생)."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", str(text or ""))
    # '20~45세 … 10.0~10.2%'처럼 ~가 두 번 나오면 마크다운이 사이를 취소선으로 처리하므로 일반 문자로 바꾼다
    return text.replace("~", "&#126;")


def cond_label(c: dict) -> str:
    seg_txt = " · ".join(x for x in [c.get("sex"), c.get("region"), "1인 가구" if c.get("single") else None] if x)
    return f"{c['name']} · {c['price']:,}원 · {c['age'][0]}~{c['age'][1]}세" + (f" · {seg_txt}" if seg_txt else "")


def show_cond(saved: dict | None, current: dict):
    """결과가 어떤 조건에서 나왔는지 보여주고, 왼쪽 입력이 바뀌었으면 다시 실행하라고 알린다."""
    if not saved:
        return
    st.markdown(f'<p class="muted">이 결과의 조건 · <b>{cond_label(saved)}</b></p>', unsafe_allow_html=True)
    if saved != current:
        st.warning(f"왼쪽 입력이 바뀌었어요. 지금 보이는 결과는 이전 조건({saved['name']} · {saved['price']:,}원) 결과예요. "
                   "새 조건으로 보려면 다시 실행하세요.", icon="⚠️")


def grid(items, n=None):
    """카드 여러 개를 한 줄에 같은 높이로 놓는다."""
    n = n or len(items)
    st.markdown(f'<div class="grid g{n}">' + "".join(items) + "</div>", unsafe_allow_html=True)


def feature(icon, title, text):
    return f'<div class="card"><div class="fi-icon">{icon}</div><h4>{title}</h4><p>{text}</p></div>'


# ------------------------------------------------------------------ 데이터
BASE = load_scenario("config/scenario_example.json")
CONCEPT_ID = BASE["concept_id"]
TOOL_LABEL = {"check_reliability": "신뢰도 확인", "run_shelf_simulation": "진열대 시뮬레이션",
              "run_fgi": "가상 FGI(좌담회)", "suggest_improvements": "개선안 제안",
              "compare_prices": "가격 비교 실험", "compare_concepts": "문구 A/B 비교",
              "get_reasons": "구매·비구매 이유 확인", "write_report": "리포트 작성"}


@st.cache_resource(show_spinner="페르소나 풀 준비 중… (처음 한 번, 약 1분)")
def pool():
    if not PERSONA_PATH.exists():  # 배포 환경에서는 처음 실행 때 내려받는다
        # 배포 서버는 메모리가 작아 일부(기본 3만 명)만 받는다. VM_POOL_ROWS 로 조절.
        from vm.personas import download_pool_light
        download_pool_light(int(os.getenv("VM_POOL_ROWS", "30000")))
    return load_pool()


def scenario_with(name, desc, price, volume, competitors=None):
    sc = copy.deepcopy(BASE)
    if competitors:  # 화면에서 편집한 경쟁 진열대
        sc["products"] = [p for p in sc["products"] if p["id"] == CONCEPT_ID] + competitors
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
    """실제 실행(비용 발생) 권한: 로컬이거나, 자기 API 키를 넣었거나, 배포에서 비밀번호를 맞힌 경우."""
    if mock or not APP_PASSWORD or st.session_state.get("user_key"):
        return True
    return st.session_state.get("pw_ok", False)


# ------------------------------------------------------------------ 사이드바
with st.sidebar:
    t1, t2 = st.columns(2)
    if t1.button("🌙 다크", width="stretch", type="primary" if DARK else "secondary"):
        st.session_state["theme"] = "dark"
        st.rerun()
    if t2.button("☀️ 라이트", width="stretch", type="secondary" if DARK else "primary"):
        st.session_state["theme"] = "light"
        st.rerun()
    from vm import project as PJ
    st.markdown('<div class="eyebrow">Project</div>', unsafe_allow_html=True)
    _projs = PJ.list_projects()
    _labels = {p["id"]: p["name"] for p in _projs}
    _opts = ["(프로젝트 없이 사용)"] + [p["id"] for p in _projs] + ["+ 새 프로젝트"]
    _cur = st.session_state.get("project_id")
    _sel = st.selectbox("프로젝트", _opts, index=_opts.index(_cur) if _cur in _opts else 0,
                        format_func=lambda x: _labels.get(x, x),
                        help="프로젝트를 고르면 실행 결과가 컨셉 버전별로 기록되고 ⓪ 프로젝트 탭에서 단계·결정을 관리합니다.")
    if _sel == "+ 새 프로젝트":
        _pn = st.text_input("프로젝트 이름", placeholder="예) 제주 청귤 제로 2027 S/S")
        _goal = st.text_input("목표(선택)", placeholder="예) 20~30대 1인 가구용 제로 탄산 가격 결정")
        if st.button("프로젝트 만들기", type="primary", disabled=not _pn):
            st.session_state["project_id"] = PJ.create(_pn, _goal)["id"]
            st.rerun()
    else:
        st.session_state["project_id"] = None if _sel.startswith("(") else _sel
    st.markdown('<div class="eyebrow">Concept Card</div>', unsafe_allow_html=True)
    st.markdown("### 신제품 컨셉")
    c = next(p for p in BASE["products"] if p["id"] == CONCEPT_ID)
    for k, v in {"c_name": c["name"], "c_desc": c["description"], "c_price": c["price"], "c_vol": c["volume_ml"]}.items():
        st.session_state.setdefault(k, v)
    if "pending_card" in st.session_state:  # ① 탭에서 '요청 문장으로 카드 바꾸기'를 누른 경우
        st.session_state.update(st.session_state.pop("pending_card"))
    with st.expander("✍️ 메모로 컨셉 채우기 (컨셉 정리 에이전트)"):
        memo = st.text_area("자유 메모", placeholder="예) 20대 여성 타깃, 제주 한라봉 넣은 제로 탄산, 500ml 2000원 정도, 상큼하고 칼로리 걱정 없는 느낌",
                            height=90, label_visibility="collapsed")
        if st.button("컨셉 카드로 정리", disabled=not memo or not can_run(st.session_state.get("mock_flag", False))):
            try:
                from vm.concept import parse_concept
                card_ = parse_concept(LLM(mock=st.session_state.get("mock_flag", False),
                                          api_key=st.session_state.get("user_key") or None), memo,
                                      st.session_state["c_price"], st.session_state["c_vol"])
                st.session_state.update({"c_name": card_["name"], "c_desc": card_["description"],
                                         "c_price": int(card_["price"]), "c_vol": int(card_["volume_ml"]),
                                         "c_missing": card_["missing"]})
                st.rerun()
            except Exception as e:
                st.error(f"{type(e).__name__}: {e}")
        if st.session_state.get("c_missing"):
            st.caption("메모에 없어 기존 값을 유지한 항목: " + ", ".join(st.session_state["c_missing"]))
    name = st.text_input("제품명", key="c_name")
    desc = st.text_area("설명·문구", key="c_desc", height=80)
    col1, col2 = st.columns(2)
    price = col1.number_input("가격(원)", 500, 10000, step=100, key="c_price")
    volume = col2.number_input("용량(ml)", 100, 2000, step=50, key="c_vol")
    st.markdown("### 타깃 패널")
    age = st.slider("연령(만)", 19, 80, (20, 39))
    sex = st.radio("성별", ["전체", "남자", "여자"], horizontal=True)
    region = st.radio("지역", ["전체", "수도권", "비수도권"], horizontal=True)
    single = st.checkbox("1인 가구만")
    st.markdown("### 경쟁 진열대")
    with st.expander("🛒 제품 추가·수정", expanded=False):
        st.caption("맨 아래 빈 행에 입력하면 제품이 추가되고, 행을 선택해 삭제할 수 있어요. 실제 브랜드명을 쓰면 AI가 알고 있는 "
                   "브랜드 인지도가 반영됩니다. 브랜드 영향 없이 비교하려면 'A사 제로 콜라'처럼 쓰세요.")
        comp_df = st.data_editor(
            pd.DataFrame([{"제품명": p["name"], "용량(ml)": p["volume_ml"], "가격(원)": p["price"], "설명": p["description"]}
                          for p in BASE["products"] if p["id"] != CONCEPT_ID]),
            num_rows="dynamic", hide_index=True, key="comp_editor", width="stretch",
            column_config={"용량(ml)": st.column_config.NumberColumn(min_value=50, max_value=3000, step=50),
                           "가격(원)": st.column_config.NumberColumn(min_value=100, max_value=20000, step=100)})
    competitors = []
    for i, r in comp_df.iterrows():
        nm = str(r.get("제품명") or "").strip()
        if nm and nm.lower() != "nan" and pd.notna(r.get("가격(원)")):
            competitors.append({"id": f"C{len(competitors) + 1}", "name": nm,
                                "volume_ml": int(r["용량(ml)"]) if pd.notna(r.get("용량(ml)")) else 500,
                                "price": int(r["가격(원)"]),
                                "description": "" if pd.isna(r.get("설명")) else str(r["설명"])})
    competitors = competitors[:8]
    st.caption(f"진열대: 신제품 + 경쟁 {len(competitors)}개" + (" (최대 8개)" if len(competitors) == 8 else ""))
    if st.session_state.get("quota"):
        st.info("👥 패널 구성: ⑤ 데이터 연결에서 적용한 실제 고객 구성대로 뽑는 중(위 연령·성별 선택보다 우선)", icon=None)
        if st.button("데이터 구성 해제"):
            st.session_state.pop("quota")
            st.rerun()
    st.divider()
    mock = st.toggle("API 없이 시험(mock)", value=False, help="가짜 응답으로 화면과 흐름만 확인합니다. 수치는 의미 없음.")
    st.session_state["mock_flag"] = mock
    st.text_input("OpenAI API 키 (선택)", type="password", placeholder="sk-...", key="user_key",
                  help="다른 사람이 자기 키로 실행할 때 입력합니다. 이번 접속 동안 이 화면에서만 쓰고 저장하지 않으며, "
                       "비용은 키 주인 계정에 청구됩니다. 비워 두면 서버에 설정된 키(.env 또는 Secrets)를 씁니다.")
    USER_KEY = st.session_state.get("user_key") or None
    if APP_PASSWORD and not mock and not USER_KEY:
        pw = st.text_input("실행 비밀번호", type="password",
                           help="서버에 설정된 API 키는 비밀번호를 아는 사람만 쓸 수 있습니다. 자기 키를 위 칸에 넣으면 비밀번호 없이 실행됩니다.")
        st.session_state["pw_ok"] = bool(pw) and pw == APP_PASSWORD
        if not st.session_state["pw_ok"]:
            st.caption("🔒 실행하려면 비밀번호 또는 본인 API 키가 필요합니다. 저장된 결과는 그대로 볼 수 있어요.")
    scenario = scenario_with(name, desc, price, volume, competitors)
    COND = {"name": name, "price": int(price), "desc": desc, "volume": int(volume), "age": list(age),
            "sex": None if sex == "전체" else sex, "region": None if region == "전체" else region, "single": single,
            "shelf": [(p["name"], p["price"]) for p in competitors], "quota": bool(st.session_state.get("quota"))}
    seg = {"sex": None if sex == "전체" else sex, "region": None if region == "전체" else region, "single_only": single}

def plog(kind: str, summary: dict, path: str = ""):
    """프로젝트를 고른 상태면 실행을 지금 컨셉 버전에 기록한다(카드가 바뀌었으면 새 버전 자동 생성)."""
    pid = st.session_state.get("project_id")
    if not pid:
        return
    from vm import project as PJ
    p = PJ.load(pid)
    v_before = len(p["versions"])
    PJ.log_run(p, COND, kind, {**summary, **({"mock": "예"} if mock else {})}, path)
    if len(p["versions"]) > v_before:
        st.toast(f"컨셉이 바뀌어 새 버전 {p['versions'][-1]['id']}로 저장했어요.")


def make_panel(n: int):
    """패널 추출: ⑤ 데이터 연결에서 고객 구성을 적용했으면 그 비율대로, 아니면 왼쪽 타깃 조건대로."""
    if st.session_state.get("quota"):
        from vm.connect import quota_panel
        return quota_panel(pool(), n, st.session_state["quota"])
    return sample_panel(pool(), n, 42, age[0], age[1], **seg)


# ------------------------------------------------------------------ 히어로
st.markdown(f"""
<div class="hero">
  <div class="eyebrow">LOTTE AX Challenge 2026 · 과제 1 · AI 페르소나 기반 신제품 시장 검증</div>
  <h1>{APP_NAME}</h1>
  <p>{APP_TAGLINE}</p>
  <div class="sources">
    페르소나 · <a href="https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea" target="_blank">NVIDIA Nemotron-Personas-Korea</a> (국가통계 분포 기반 합성 100만 명, CC BY 4.0)<br>
    검증 데이터 · <a href="https://krei.re.kr/foodSurvey/page/460" target="_blank">한국농촌경제연구원 식품소비행태조사</a> 2023~2025 성인 원자료
  </div>
</div>""", unsafe_allow_html=True)

tabs = st.tabs(["⓪ 프로젝트", "① 컨셉 검증 · AI 에이전트", "② 진열대 시뮬레이션", "③ 가상 FGI", "④ 신뢰도 검증",
                "⑤ 데이터 연결", "⑥ 서비스 구조·운영", "⑦ 한계와 로드맵"])

# ------------------------------------------------------------------ ⓪ 프로젝트
with tabs[0]:
    from vm import project as PJ
    pid = st.session_state.get("project_id")
    if not pid:
        st.markdown('<div class="section-title">프로젝트</div>', unsafe_allow_html=True)
        st.markdown('<p class="muted">신제품 하나의 검증 과정을 컨셉 버전·실행 기록·단계 결정·실제 결과로 묶어 관리합니다. '
                    '왼쪽 위 <b>프로젝트 → + 새 프로젝트</b>로 시작하세요. 프로젝트 없이도 다른 탭은 그대로 쓸 수 있어요.</p>',
                    unsafe_allow_html=True)
        grid([feature("📁", "버전 관리", "컨셉 카드가 바뀌면 v1, v2…로 자동 저장되고 실행 결과가 버전별로 쌓여요"),
              feature("🚦", "단계 게이트", "운영 6단계 중 어디까지 왔는지, 어떤 근거로 진행·보류·중단했는지 기록해요"),
              feature("🎯", "사후 검증", "실제 조사 결과를 넣으면 AI 예측과 나란히 비교해 이 도구의 정확도를 쌓아요")])
    else:
        proj = PJ.load(pid)
        st.markdown(f'<div class="section-title">{proj["name"]}</div>', unsafe_allow_html=True)
        st.markdown(f'<p class="muted">목표 · {proj.get("goal") or "-"} &nbsp;|&nbsp; 생성 {proj["created"]} · 수정 {proj.get("updated", "")}</p>',
                    unsafe_allow_html=True)
        cur_v = PJ.current_version(proj, COND)
        # 지금 카드 상태
        c1, c2 = st.columns([3, 1])
        if cur_v:
            c1.success(f"지금 왼쪽 카드 = **{cur_v['id']}** ({cur_v['card']['name']} · {cur_v['card']['price']:,}원)")
        else:
            c1.info(f"지금 왼쪽 카드({name} · {price:,}원)는 아직 저장되지 않은 새 컨셉이에요. 실행하면 자동으로 새 버전이 됩니다.")
            if c2.button("새 버전으로 저장", type="primary"):
                PJ.ensure_version(proj, COND, "수동 저장")
                st.rerun()
        # 단계 게이트
        if proj["versions"]:
            vsel = st.selectbox("버전", [v["id"] for v in proj["versions"]],
                                index=[v["id"] for v in proj["versions"]].index(cur_v["id"]) if cur_v else len(proj["versions"]) - 1,
                                format_func=lambda vid: next(f"{v['id']} · {v['card']['name']} · {v['card']['price']:,}원"
                                                             for v in proj["versions"] if v["id"] == vid))
            v = next(x for x in proj["versions"] if x["id"] == vsel)
            stg = v.get("stage", 1)
            steps_html = "".join(
                f'<div class="card" style="padding:.8rem 1rem;{"border-color:" + RED + ";background:rgba(228,0,43,.12);" if i <= stg else "opacity:.55;"}">'
                f'<div class="lbl">{i}단계</div><h4 style="margin:0">{nm}</h4></div>'
                for i, nm in enumerate(PJ.STAGES, 1))
            st.markdown(f'<div class="grid g6">{steps_html}</div>',
                        unsafe_allow_html=True)
            pred = PJ.latest_prediction(proj, vsel)
            info = [card("현재 단계", f"{stg}. {PJ.STAGES[stg - 1]}", v.get("decision", "결정 전") + (" · 실제 조사 대상" if v.get("to_survey") else "")),
                    card("최근 신제품 구매 비율", f"{pred.get('신제품 구매 비율(%)', '-')}%", "가장 최근 시뮬레이션 기준"),
                    card("실행 기록", f"{sum(r['version'] == vsel for r in proj['runs'])}건", "이 버전에서 돌린 실험 수")]
            grid(info)
            if st.button(f"{vsel} 카드를 왼쪽에 불러오기"):
                cd = v["card"]
                st.session_state["pending_card"] = {"c_name": cd["name"], "c_price": cd["price"], "c_desc": cd["desc"], "c_vol": cd["volume"]}
                st.rerun()

            with st.expander("🚦 단계 결정 기록하기 (진행·보류·중단)"):
                dc = st.radio("결정", PJ.DECISIONS, horizontal=True, key="pj_dec")
                note = st.text_area("근거", placeholder="예) 2,400원은 구매 비율이 1,900원보다 5%p 낮아 1,900원안으로 진행", key="pj_note")
                to_s = st.checkbox("이 버전을 실제 조사(FGI·설문) 대상으로 선정", key="pj_tosurvey")
                if st.button("결정 저장", type="primary", disabled=not note):
                    PJ.decide(proj, vsel, dc, note, to_s)
                    st.rerun()

            with st.expander("🎯 실제 조사 결과 입력 (AI 예측과 비교)"):
                st.caption("실제 설문·판매 결과를 넣으면 같은 지표의 AI 예측과 나란히 기록합니다. 쌓일수록 이 도구가 얼마나 맞는지 알 수 있어요.")
                mt = st.selectbox("지표", ["신제품 구매 비율(%)", "앞으로 사 볼 의향(%)", "직접 입력"], key="pj_metric")
                if mt == "직접 입력":
                    mt = st.text_input("지표 이름", key="pj_metric_free")
                a1, a2, a3 = st.columns(3)
                av = a1.number_input("실제 값(%)", 0.0, 100.0, 0.0, 0.1, key="pj_actual")
                an = a2.number_input("표본 수", 0, 1000000, 0, key="pj_n")
                asrc = a3.text_input("출처", placeholder="예) 2026-12 소비자 설문", key="pj_src")
                pv = pred.get(mt) if isinstance(pred.get(mt), (int, float)) else None
                st.caption(f"비교할 AI 예측값: {pv if pv is not None else '없음(이 지표의 시뮬레이션 기록 없음)'}")
                if st.button("실제 결과 저장", disabled=not (mt and asrc)):
                    PJ.add_actual(proj, vsel, mt, float(av), pv, int(an) or None, asrc)
                    st.rerun()

        if proj["runs"]:
            st.markdown("**실행 기록**")
            st.dataframe(pd.DataFrame([{"시간": r["time"], "버전": r["version"], "종류": r["kind"], "조건": r["target"],
                                        "주요 결과": ", ".join(f"{k} {v_}" for k, v_ in r["summary"].items())}
                                       for r in reversed(proj["runs"])]), hide_index=True, width="stretch")
        if proj["decisions"]:
            st.markdown("**결정 기록**")
            st.dataframe(pd.DataFrame([{"시간": d["time"], "버전": d["version"], "결정": d["decision"],
                                        "실제 조사": "선정" if d["to_survey"] else "", "근거": d["note"]}
                                       for d in reversed(proj["decisions"])]), hide_index=True, width="stretch")
        if proj["actuals"]:
            st.markdown("**실제 결과 vs AI 예측 (사후 검증)**")
            st.dataframe(pd.DataFrame([{"버전": a["version"], "지표": a["metric"], "실제": a["actual"], "AI 예측": a["predicted"],
                                        "차이(%p)": None if a["predicted"] is None else round(a["predicted"] - a["actual"], 1),
                                        "표본": a["n"], "출처": a["source"]} for a in proj["actuals"]]),
                         hide_index=True, width="stretch")
        st.download_button("📄 프로젝트 보고서 내려받기 (Markdown)", PJ.export_markdown(proj),
                           file_name=f"{proj['name']}_보고서.md", mime="text/markdown")

# ------------------------------------------------------------------ ① 에이전트
with tabs[1]:
    st.markdown('<div class="section-title">시장 검증 에이전트</div>', unsafe_allow_html=True)
    st.markdown('<p class="muted">질문을 받으면 에이전트가 스스로 계획 → 도구 실행 → 결과 확인 → 추가 실험 → 리포트 작성까지 진행합니다.</p>',
                unsafe_allow_html=True)
    st.markdown(f'<p class="muted">검증할 컨셉(왼쪽 카드) · <b>{cond_label(COND)}</b> — 실행은 항상 이 카드 기준입니다.</p>',
                unsafe_allow_html=True)
    default_q = f"{age[0]}~{age[1]}세 대상 '{name}', {price:,}원이 적당한지 검토해줘"
    question = st.text_area("요청", default_q, height=70)
    # 요청 문장에 다른 제품·가격을 쓰면 왼쪽 카드와 어긋난다 → 알려주고, 한 번에 카드를 맞출 수 있게 한다
    prices_in_q = {int(x.replace(",", "")) for x in re.findall(r"(\d{1,2},?\d{3})\s*원", question)}
    if (name not in question) or (prices_in_q and int(price) not in prices_in_q):
        st.warning("요청 문장의 제품명이나 가격이 왼쪽 컨셉 카드와 달라요. 실행은 왼쪽 카드 기준으로 되므로 결과가 섞일 수 있어요.",
                   icon="⚠️")
        if st.button("요청 문장 내용으로 왼쪽 카드 바꾸기", disabled=not can_run(mock)):
            from vm.concept import parse_concept
            try:
                card_ = parse_concept(LLM(mock=mock, api_key=USER_KEY), question, int(price), int(volume))
                upd = {"c_name": card_["name"], "c_price": int(card_["price"]), "c_vol": int(card_["volume_ml"])}
                if "설명" not in " ".join(card_.get("missing", [])) and card_.get("description"):
                    upd["c_desc"] = card_["description"]
                st.session_state["pending_card"] = upd  # 사이드바 입력칸은 이미 그려졌으므로 다음 실행 시작 때 반영
                st.rerun()
            except Exception as e:
                st.error(f"{type(e).__name__}: {e}")
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
                res = run_agent(question, scenario, budget=int(budget), mock=mock, on_step=on_step, api_key=USER_KEY,
                                quota=st.session_state.get("quota"))
                status.update(label=f"완료 · 새 페르소나 응답 {res['api_calls']}개 (예산 {res['budget']})", state="complete")
                st.session_state["agent_result"] = {**res, "cond": dict(COND)}
                _sims = [t["result"] for t in res["trace"] if t["tool"] == "run_shelf_simulation" and "buy_share_%" in t["result"]]
                plog("에이전트", {"요청": question[:40]} | ({"신제품 구매 비율(%)": _sims[-1]["buy_share_%"].get(name),
                                                          "앞으로 사 볼 의향(%)": _sims[-1].get("concept_try_%")} if _sims else {}),
                     res["out_dir"])
            except Exception as e:
                status.update(label="실패", state="error")
                st.error(f"{type(e).__name__}: {e}")
    if not can_run(mock):
        st.caption("🔒 실행하려면 왼쪽에 비밀번호 또는 본인 API 키를 넣으세요. 아래 '저장된 결과 보기'는 그대로 볼 수 있어요.")

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
        show_cond(res.get("cond"), COND)
        st.markdown("---")
        with st.container(border=True):
            st.markdown(bold(res["report"]) or "(리포트 없음)", unsafe_allow_html=True)
        with st.expander("에이전트가 실행한 단계 (trace)"):
            for t in res["trace"]:
                st.markdown(f"**[{t['step']}] {TOOL_LABEL.get(t['tool'], t['tool'])}** `{json.dumps(t['args'], ensure_ascii=False)}`")
                st.json(t["result"], expanded=False)
        st.caption(f"저장 위치: {res['out_dir']}")

# ------------------------------------------------------------------ ② 진열대
with tabs[2]:
    st.markdown('<div class="section-title">가상 진열대 시뮬레이션</div>', unsafe_allow_html=True)
    st.markdown('<p class="muted">각 페르소나에게 "이 프로필과 비슷한 100명이 이 진열대 앞에서 어떻게 나뉠지"를 묻고 평균합니다. '
                '한 사람에게 답 하나를 받으면 대표 답으로 쏠리는 문제가 있어 이 방식을 채택했습니다(③ 참고).</p>', unsafe_allow_html=True)
    n = st.slider("패널 인원", 10, 100, 50, step=10)
    if st.button("시뮬레이션 실행", type="primary", disabled=not can_run(mock)):
        try:
            panel = make_panel(n)
            llm = LLM(mock=mock, api_key=USER_KEY)
            with st.spinner(f"{n}명에게 묻는 중…"):
                df = run(scenario, panel, llm, 42, mode="prob")
            st.session_state["sim"] = (df, scenario, llm.api_calls)
            st.session_state["sim_cond"] = dict(COND)
            _ok = df[df["error"] == ""]
            plog("진열대", {"신제품 구매 비율(%)": round(_ok[f"p_{CONCEPT_ID}"].mean() * 100, 1),
                          "앞으로 사 볼 의향(%)": round(_ok[f"try_{CONCEPT_ID}"].mean() * 100, 1),
                          "지불의사(원)": int(_ok[f"max_price_{CONCEPT_ID}"].median()), "인원": len(_ok)})
            st.session_state["sim_panel"] = panel
            st.session_state.pop("improve", None)
        except Exception as e:
            st.error(f"{type(e).__name__}: {e}")
    if "sim" in st.session_state:
        show_cond(st.session_state.get("sim_cond"), COND)
        df, sc, calls = st.session_state["sim"]
        ok = df[df["error"] == ""]
        names = {p["id"]: p["name"] for p in sc["products"]} | {"NONE": "구매 안 함"}
        cname = names[CONCEPT_ID]
        share = shares_of(ok, sc).rename(index=names).mul(100).round(1)
        wtp = int(ok[f"max_price_{CONCEPT_ID}"].median())
        cprice = next(p["price"] for p in sc["products"] if p["id"] == CONCEPT_ID)
        grid([card("신제품 구매 비율", f"{share[cname]:.1f}%", f"1위 {share.idxmax()} {share.max():.1f}%"),
              card("앞으로 사 볼 의향", f"{ok[f'try_{CONCEPT_ID}'].mean() * 100:.1f}%", "제품을 한 번이라도 사 볼 사람 비율"),
              card("지불의사가격(중앙값)", f"{wtp:,}원", f"판매가 {cprice:,}원 대비 {wtp - cprice:+,}원")])
        st.write("")
        bars = share.reset_index().rename(columns={"index": "제품", 0: "비율"})
        bars.columns = ["제품", "비율"]
        bars["구분"] = bars["제품"].map(lambda x: "신제품" if x == cname else ("구매 안 함" if x == "구매 안 함" else "경쟁 제품"))
        chart = alt.Chart(bars).mark_bar(cornerRadiusEnd=6, height=26).encode(
            x=alt.X("비율:Q", title="구매 비율(%)"), y=alt.Y("제품:N", sort="-x", title=None),
            color=alt.Color("구분:N", scale=alt.Scale(domain=["신제품", "경쟁 제품", "구매 안 함"],
                                                     range=[RED, "#71717A", T["grid"]]), legend=None),
            tooltip=["제품", "비율"]).properties(height=230)
        st.altair_chart(style_chart(chart), width="stretch")
        st.markdown("**연령대별 신제품 구매 비율(%)**")
        st.dataframe(ok.groupby("age_group", observed=True)[f"p_{CONCEPT_ID}"].mean().mul(100).round(1)
                     .rename("구매 비율(%)").to_frame().T, hide_index=True)
        with st.expander("구매·비구매 이유 표본"):
            for r in ok.sample(min(8, len(ok)), random_state=0).itertuples():
                st.markdown(f"- **{r.age_group} {r.sex}** · {r.reason}")
        st.caption(f"응답 {len(ok)}/{len(df)}명 · 새 API 호출 {calls}회")

        # ---- 개선 컨셉 루프: 이유 → 개선안 → 같은 패널로 재검증 (기획서 4)
        st.markdown("---")
        st.markdown('<div class="section-title">개선 컨셉 루프</div>', unsafe_allow_html=True)
        st.markdown('<p class="muted">위 구매·비구매 이유만 근거로 개선안을 만들고, 같은 패널에서 원안과 나란히 다시 검증합니다.</p>',
                    unsafe_allow_html=True)
        i1, i2 = st.columns(2)
        if i1.button("① 개선안 받기", disabled=not can_run(mock)):
            from vm.concept import suggest_improvements
            concept = next(p for p in sc["products"] if p["id"] == CONCEPT_ID)
            with st.spinner("개선안 만드는 중…"):
                st.session_state["improve"] = {"variants": suggest_improvements(LLM(mock=mock, api_key=USER_KEY), concept,
                                                                               ok["reason"].astype(str).tolist(), 3)}
        imp = st.session_state.get("improve")
        if imp:
            grid([feature("💡", f"{v['label']} · {v['name']}",
                          f"{v['description']}<br><b>{v['price']:,}원</b><br><span class='muted'>근거: {bold(v['rationale'])}</span>")
                  for v in imp["variants"]])
            if i2.button("② 같은 패널로 재검증", type="primary", disabled=not can_run(mock)):
                rows, llm2 = [], LLM(mock=mock, api_key=USER_KEY)
                cands = [{"label": "원안", "name": name, "description": desc, "price": price}] + imp["variants"]
                with st.spinner(f"{len(cands)}개 안 × {len(st.session_state['sim_panel'])}명 검증 중…"):
                    for v in cands:
                        sc2 = scenario_with(v["name"], v["description"], v["price"], volume, competitors)
                        d2 = run(sc2, st.session_state["sim_panel"], llm2, 42, mode="prob")
                        o2 = d2[d2["error"] == ""]
                        rows.append({"안": f"{v['label']} · {v['name']}", "구매 비율(%)": round(o2[f"p_{CONCEPT_ID}"].mean() * 100, 1),
                                     "사 볼 의향(%)": round(o2[f"try_{CONCEPT_ID}"].mean() * 100, 1),
                                     "지불의사(원)": int(o2[f"max_price_{CONCEPT_ID}"].median()), "가격(원)": v["price"]})
                imp["result"] = pd.DataFrame(rows)
                _best = imp["result"].sort_values("구매 비율(%)", ascending=False).iloc[0]
                plog("개선 비교", {"1위 안": _best["안"], "1위 구매 비율(%)": float(_best["구매 비율(%)"]),
                                  "원안 구매 비율(%)": float(imp["result"].iloc[0]["구매 비율(%)"])})
            if "result" in imp:
                r = imp["result"]
                ch = alt.Chart(r).mark_bar(cornerRadiusEnd=6, height=24).encode(
                    x=alt.X("구매 비율(%):Q"), y=alt.Y("안:N", sort="-x", title=None),
                    color=alt.condition(alt.datum.안 == r.iloc[0]["안"], alt.value("#A1A1AA"), alt.value(RED)),
                    tooltip=list(r.columns)).properties(height=40 * len(r) + 20)
                st.altair_chart(style_chart(ch), width="stretch")
                st.dataframe(r, hide_index=True, width="stretch")
                st.caption("차이가 3%p 미만이면 뚜렷한 차이로 보지 않습니다(③ 신뢰도 검증의 실제 대비 오차 수준).")

# ------------------------------------------------------------------ ③ 가상 FGI
with tabs[3]:
    st.markdown('<div class="section-title">가상 FGI (좌담회)</div>', unsafe_allow_html=True)
    st.markdown('<p class="muted">타깃 패널에서 성별·연령이 섞인 참여자들이 3라운드 동안 서로의 말을 듣고 이야기합니다. '
                '라운드마다 질문을 바꾸고(첫인상 → 걸리는 점 → 무엇이 바뀌면 살지), 매 라운드 구매 입장을 기록해 '
                '<b>누가 누구에게 설득되는지</b> 추적합니다. 소수 의견이므로 수치처럼 일반화하지 않습니다.</p>', unsafe_allow_html=True)
    k = st.slider("참여자 수", 3, 6, 5)
    if st.button("좌담회 시작", type="primary", disabled=not can_run(mock)):
        from vm.fgi import run_fgi
        try:
            fp = make_panel(60)
            with st.spinner(f"{k}명 × 3라운드 진행 중… (약 {k * 3 + 1}회 호출)"):
                fres = run_fgi(LLM(mock=mock, api_key=USER_KEY), scenario, fp, k)
            out = OUT_DIR / f"fgi_{pd.Timestamp.now():%Y%m%d_%H%M%S}{'_mock' if mock else ''}"
            out.mkdir(parents=True, exist_ok=True)
            (out / "fgi.json").write_text(json.dumps({"concept": name, "price": price, "cond": COND, **fres}, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
            st.session_state["fgi"] = {**fres, "cond": dict(COND)}
            plog("FGI", {"최종 입장": " / ".join(f"{k} {v}" for k, v in fres["final_stance"].items()),
                         "입장 바뀐 사람": len(fres["stance_changed"])}, str(out))
        except Exception as e:
            st.error(f"{type(e).__name__}: {e}")
    saved = sorted(glob.glob(str(OUT_DIR / "fgi_*" / "fgi.json")), reverse=True)
    if saved:
        with st.expander("저장된 좌담회 보기"):
            def _fl(f):
                d = json.loads(Path(f).read_text(encoding="utf-8"))
                stamp = Path(f).parent.name.replace("fgi_", "")
                return f"{stamp[4:6]}/{stamp[6:8]} {stamp[9:11]}:{stamp[11:13]} · {d.get('concept', '')} {d.get('price', 0):,}원"
            pickf = st.selectbox("이전 좌담회", saved, format_func=_fl)
            if st.button("불러오기", key="load_fgi"):
                st.session_state["fgi"] = json.loads(Path(pickf).read_text(encoding="utf-8"))
    fres = st.session_state.get("fgi")
    if fres:
        show_cond(fres.get("cond"), COND)
        BADGE = {"살 것": "b-buy", "고민": "b-mid", "안 살 것": "b-no"}
        fs = fres["final_stance"]
        grid([card("최종: 살 것", f"{fs.get('살 것', 0)}명"), card("최종: 고민", f"{fs.get('고민', 0)}명"),
              card("최종: 안 살 것", f"{fs.get('안 살 것', 0)}명", f"입장 바뀐 사람 {len(fres['stance_changed'])}명")])
        st.write("")
        left, right = st.columns([3, 2])
        with left:
            from vm.fgi import ROUNDS
            for rnd, q in enumerate(ROUNDS, 1):
                st.markdown(f"**{rnd}라운드 · {q}**")
                for t in [t for t in fres["turns"] if t["round"] == rnd]:
                    to = f" → {t['reply_to']}" if t.get("reply_to") else ""
                    st.markdown(f'<div class="bubble"><div class="who">{t["speaker"]}{to}'
                                f'<span class="badge {BADGE.get(t["stance"], "b-mid")}">{t["stance"]}</span></div>'
                                f'<div class="txt">{bold(t["utterance"])}</div></div>', unsafe_allow_html=True)
        with right:
            sm = fres["summary"]
            for title, key_, icon in [("핵심 반응", "key_points", "🗣"), ("우려", "concerns", "⚠️"),
                                      ("개선 아이디어", "improvements", "💡"), ("설득 장면", "persuasion", "🔁")]:
                st.markdown(feature(icon, title, "<br>".join(f"· {bold(x)}" for x in sm.get(key_, [])) or "-"),
                            unsafe_allow_html=True)
                st.write("")
            tt = pd.DataFrame(fres["turns"]).pivot(index="speaker", columns="round", values="stance")
            tt.columns = [f"{c}R" for c in tt.columns]
            st.markdown("**라운드별 입장 변화**")
            st.dataframe(tt, width="stretch")

# ------------------------------------------------------------------ ④ 신뢰도
with tabs[4]:
    st.markdown('<div class="section-title">이 패널을 어디까지 믿을 수 있나</div>', unsafe_allow_html=True)
    st.markdown('<p class="muted">공개된 실제 정부 설문(한국농촌경제연구원 식품소비행태조사 2023~2025, 성인 약 1.7만 명)과 '
                '같은 질문을 페르소나에게 묻고 비교했습니다. 평가 규칙은 실행 전에 정해 두었습니다.</p>', unsafe_allow_html=True)
    f = latest("survey_*/comparison.csv")
    if not f:
        st.info("설문 재현 결과가 없습니다. 터미널에서 `python -m vm.survey --n-per-age 30` 을 실행하세요.")
    else:
        t = pd.read_csv(f, index_col=0)
        if "prob" in t.index and "base" in t.index:
            grid([card("탄산·이온 선호 오차", f"{t.loc['prob', 'four_rate_mae']:.1f}%p", f"기본 방식 {t.loc['base', 'four_rate_mae']:.1f}%p"),
                  card("연령 방향 일치도", f"{t.loc['prob', 'four_age_corr']:.2f}", f"기본 방식 {t.loc['base', 'four_age_corr']:.2f}"),
                  card("1순위 음료 분포 오차", f"{t.loc['prob', 'fav_mae']:.1f}%p",
                       f"무작위 {t.loc['무작위 기준선', 'fav_mae']:.1f} · 실제끼리 1.2~1.8"),
                  card("검증 문항 오차", f"{t.loc['prob', 'zero_mae(검증)']:.1f}%p",
                       f"설정 선택에 미사용 · 기본 {t.loc['base', 'zero_mae(검증)']:.1f}")])
        ages = ["20대 이하", "30대", "40대", "50대", "60대 이상"]
        rows = [(r, lbl) for r, lbl in [("실제(KREI)", "실제 설문"), ("prob", "100명 분포 응답(채택)"), ("base", "기본 방식")] if r in t.index]
        long = pd.DataFrame([{"연령": a, "구분": lbl, "비율": t.loc[r, f"four_{a}"]} for r, lbl in rows for a in ages])
        line = alt.Chart(long).mark_line(point=alt.OverlayMarkDef(size=70), strokeWidth=3).encode(
            x=alt.X("연령:N", sort=ages, title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("비율:Q", title="탄산·이온 음료 1순위 비율(%)"),
            color=alt.Color("구분:N", scale=alt.Scale(domain=[l for _, l in rows],
                                                     range=[T["text"], RED, "#A1A1AA"][:len(rows)]),
                            legend=alt.Legend(orient="top", title=None)),
            strokeDash=alt.condition(alt.datum.구분 == "기본 방식", alt.value([5, 4]), alt.value([0])),
            tooltip=["연령", "구분", "비율"]).properties(height=320)
        st.write("")
        st.altair_chart(style_chart(line), width="stretch")
        grid([feature("🎯", "무엇을 발견했나",
                      "한 사람에게 답 하나를 받으면 '가장 그럴듯한 답'으로 쏠려 커피·녹차가 과다하고 우유류는 0명이었습니다. "
                      "실제 설문과의 오차가 무작위로 찍은 것보다 컸습니다."),
              feature("🛠", "어떻게 고쳤나",
                      "'비슷한 사람 100명이 어떻게 나뉠지'를 묻는 방식으로 바꾸자 탄산·이온 음료 선호가 연령별로 실제와 1~4%p 안에 들어왔고, "
                      "설정 선택에 쓰지 않은 검증 문항에서도 개선됐습니다.")])
        with st.expander("전체 비교표"):
            st.dataframe(t)
        conn = sorted(glob.glob(str(OUT_DIR / "connect_*" / "result.json")), reverse=True)
        if conn:
            with st.expander(f"받은 데이터로 한 추가 검증 ({len(conn)}건) — ⑤ 데이터 연결"):
                st.dataframe(pd.DataFrame([{k: d.get(k) for k in ["question", "mae", "random_mae", "n_ok", "source", "mock"]}
                                           for d in (json.loads(Path(f).read_text(encoding="utf-8")) for f in conn)])
                             .rename(columns={"question": "질문", "mae": "오차(%p)", "random_mae": "무작위(%p)", "n_ok": "응답",
                                              "source": "데이터", "mock": "mock"}), hide_index=True, width="stretch")
        st.caption(f"결과 파일: {f}")

# ------------------------------------------------------------------ ⑤ 데이터 연결
with tabs[5]:
    from vm.connect import (answer_options, ask_question, compare, composition, load_table, reference_dist,
                            save_result, to_age_bucket)
    st.markdown('<div class="section-title">데이터 연결</div>', unsafe_allow_html=True)
    st.markdown('<p class="muted">받은 표(CSV·엑셀)에서 열만 고르면 바로 씁니다. ① 같은 설문 문항을 페르소나에게 물어 실제 응답과 비교(검증)하고, '
                '② 실제 고객 구성대로 페르소나 패널을 뽑습니다. 개인 단위 데이터는 AI에 보내지 않고 집계 분포만 씁니다.</p>',
                unsafe_allow_html=True)
    up = st.file_uploader("파일 올리기", type=["csv", "xlsx", "xls"])
    use_sample = st.checkbox("예시 파일로 해 보기 (KREI 공개 집계값으로 만든 가짜 응답자 1,200명)", value=up is None)
    src = up if up is not None else (Path("data/sample/sample_consumer_survey.csv") if use_sample else None)
    if src is None:
        st.info("파일을 올리거나 예시 파일을 선택하세요.")
    else:
        try:
            df_in = load_table(src)
        except Exception as e:
            st.error(f"파일을 읽지 못했어요: {e}")
            df_in = None
        if df_in is not None:
            st.caption(f"{len(df_in):,}행 · {len(df_in.columns)}열")
            st.dataframe(df_in.head(5), hide_index=True, width="stretch")
            cols = list(df_in.columns)
            guess = lambda keys: next((c for c in cols if any(k in str(c) for k in keys)), None)
            m1, m2, m3 = st.columns(3)
            age_col = m1.selectbox("나이(연령대) 열 *", cols, index=cols.index(guess(["연령", "나이", "age"])) if guess(["연령", "나이", "age"]) else 0)
            sex_col = m2.selectbox("성별 열", ["(없음)"] + cols, index=(cols.index(guess(["성별", "sex", "gender"])) + 1) if guess(["성별", "sex", "gender"]) else 0)
            w_col = m3.selectbox("가중치 열", ["(없음)"] + cols, index=(cols.index(guess(["가중", "weight", "wt"])) + 1) if guess(["가중", "weight", "wt"]) else 0)
            sex_col = None if sex_col == "(없음)" else sex_col
            w_col = None if w_col == "(없음)" else w_col
            bad_age = df_in[age_col].map(to_age_bucket).isna().mean()
            if bad_age > 0.2:
                st.warning(f"나이 열에서 연령대를 못 읽은 행이 {bad_age:.0%}예요. 나이 숫자나 '30대'·'만 30~39세' 같은 값이 있는 열을 고르세요.")

            st.markdown("---")
            st.markdown("**① 설문 문항 검증**: 같은 질문을 페르소나에게 묻고 실제 응답과 비교")
            # 응답 열 후보: ID처럼 값이 거의 다 다른 열은 빼고, 보기 수가 2~30개인 열을 앞에 둔다
            rest = [c for c in cols if c not in (age_col, sex_col, w_col)]
            good = [c for c in rest if 2 <= df_in[c].nunique() <= 30]
            ans_col = st.selectbox("응답 열", good + [c for c in rest if c not in good],
                                   help="보기 수가 2~30개인 열이 앞에 나옵니다. ID처럼 값이 모두 다른 열은 비교할 수 없어요.")
            if df_in[ans_col].nunique() > 30:
                st.warning("이 열은 값 종류가 너무 많아요(ID나 주관식일 수 있어요). 보기가 정해진 객관식 응답 열을 고르세요.")
            opts_all = answer_options(df_in, ans_col)
            q = st.text_input("질문 문구(설문지 그대로 쓰면 가장 정확해요)", value=str(ans_col))
            opts = st.multiselect(f"비교할 보기(많이 나온 순, 최대 {len(opts_all)}개)", opts_all, default=opts_all)
            npa = st.slider("연령대별 인원", 5, 30, 10, help="5개 연령대 × 인원 = API 호출 수. 판단용은 30 권장(설문 재현 검증 기준).")
            if st.button("검증 실행", type="primary", disabled=not can_run(mock) or len(opts) < 2):
                ref = reference_dist(df_in, age_col, ans_col, opts, w_col)
                from vm.survey import stratified_panel
                pnl = stratified_panel(pool(), npa, 42)
                with st.spinner(f"{len(pnl)}명에게 묻는 중…"):
                    sim = ask_question(LLM(mock=mock, api_key=USER_KEY), pnl, q, opts)
                r = compare(sim, ref, opts)
                out = save_result(q, opts, r, {"source": getattr(src, "name", str(src)), "n_per_age": npa, "mock": mock})
                st.session_state["connect_res"] = (q, opts, r, ref, str(out))
                plog("데이터 검증", {"질문": q[:30], "오차(%p)": r["mae"], "무작위(%p)": r["random_mae"]}, str(out))
            if "connect_res" in st.session_state:
                q_, opts_, r, ref, out = st.session_state["connect_res"]
                grid([card("페르소나 vs 실제 오차", f"{r['mae']:.1f}%p", "연령대별 분포 MAE"),
                      card("무작위 기준선", f"{r['random_mae']:.1f}%p", "보기를 균등하게 찍었을 때"),
                      card("판정", "무작위보다 나음" if r["mae"] < r["random_mae"] - 0.3 else "무작위 수준",
                           f"응답 {r['n_ok']}명 · 연령대당 인원이 적으면 우연 오차가 큼")])
                pick_age = st.radio("연령대", r["ages"], horizontal=True)
                t_ = r["table"][r["table"]["연령대"] == pick_age].melt(id_vars=["연령대", "보기"], var_name="구분", value_name="비율")
                ch = alt.Chart(t_).mark_bar(cornerRadiusEnd=4).encode(
                    y=alt.Y("보기:N", sort="-x", title=None), x=alt.X("비율:Q", title="%"),
                    color=alt.Color("구분:N", scale=alt.Scale(domain=["실제(%)", "페르소나(%)"], range=["#A1A1AA", RED]),
                                    legend=alt.Legend(orient="top", title=None)),
                    yOffset="구분:N", tooltip=["보기", "구분", "비율"]).properties(height=max(220, 34 * len(opts_)))
                st.altair_chart(style_chart(ch), width="stretch")
                st.caption(f"저장: {out}")

            st.markdown("---")
            st.markdown("**② 패널 구성 맞추기**: 이 데이터의 연령·성별 구성대로 페르소나를 뽑기")
            comp = composition(df_in, age_col, sex_col, w_col)
            cdf = pd.DataFrame([{"연령대": k.split("|")[0], "성별": k.split("|")[1], "비율(%)": round(v * 100, 1)}
                                for k, v in comp.items()])
            st.dataframe(cdf.pivot(index="연령대", columns="성별", values="비율(%)").reindex(
                ["20대 이하", "30대", "40대", "50대", "60대 이상"]), width="stretch")
            if st.button("이 구성으로 패널 뽑기 적용", type="primary"):
                st.session_state["quota"] = comp
                st.rerun()
            if st.session_state.get("quota"):
                st.success("적용됨: 진열대·FGI·에이전트가 이 구성대로 패널을 뽑습니다. 해제는 왼쪽 사이드바에서.")

# ------------------------------------------------------------------ ⑥ 서비스 구조
with tabs[6]:
    st.markdown('<div class="section-title">서비스 아키텍처</div>', unsafe_allow_html=True)
    st.graphviz_chart(f"""
digraph G {{
  rankdir=LR; bgcolor="transparent"; nodesep=0.35; ranksep=0.5;
  node [shape=box style="rounded,filled" fontname="Noto Sans KR" fontsize=13 color="{T['node_line']}" fillcolor="{T['node_fill']}" fontcolor="{T['text']}"];
  edge [color="#71717A" fontname="Noto Sans KR" fontsize=9 fontcolor="#A1A1AA"];
  user [label="마케터\\n컨셉·질문 입력" fillcolor="{RED}" color="{RED}" fontcolor="#FFFFFF"];
  agent [label="시장 검증 에이전트\\n계획 · 도구 선택 · 리포트" fillcolor="{RED_DARK if DARK else '#FFE8EC'}" color="{RED}"];
  subgraph cluster_tools {{ label="도구" fontcolor="#A1A1AA" color="#27272A" style="rounded";
    tools [label="진열대 시뮬레이션 · 가격 비교\\n문구 A/B · 가상 FGI\\n개선안 제안 · 이유 분석"]; rel [label="신뢰도 확인"]; }}
  parse [label="컨셉 정리\\n메모 → 컨셉 카드"];
  engine [label="페르소나 시뮬레이션 엔진\\n100명 분포 응답 · 블라인드 진열"];
  llm [label="LLM\\n(사내 모델로 교체 가능)"]; cache [label="응답 캐시 · 실행 기록\\n재현성 · 비용 절감"];
  subgraph cluster_data {{ label="데이터" fontcolor="#A1A1AA" color="#27272A" style="rounded";
    persona [label="합성 페르소나 풀\\nNemotron-Personas-Korea"]; krei [label="실제 설문\\nKREI 식품소비행태조사"];
    lotte [label="롯데칠성 판매·조사\\n(연결 예정)" style="rounded,dashed" fontcolor="#A1A1AA"]; }}
  report [label="리포트\\n수치 · 신뢰도 · 한계" fillcolor="{RED}" color="{RED}" fontcolor="#FFFFFF"];
  user -> parse -> agent -> tools -> engine -> llm -> cache;
  agent -> rel; persona -> engine; krei -> rel; lotte -> rel [style=dashed label="보정"];
  agent -> report;
}}""", width="stretch")
    st.markdown('<div class="section-title">운영 프로세스</div>', unsafe_allow_html=True)
    steps = [("1", "📝", "컨셉 입력", "제품명·맛·가격·문구를 컨셉 카드로 입력"),
             ("2", "👥", "타깃 패널", "연령·성별·지역·가구로 패널 구성"),
             ("3", "🤖", "에이전트 실험", "시뮬레이션·가격·문구 비교·가상 FGI를 자동 실행"),
             ("4", "📊", "리포트·개선 루프", "수치·신뢰도 확인 후 개선안을 같은 패널로 재검증"),
             ("5", "✅", "상위안만 실제 조사", "걸러진 1~2안만 FGI·설문으로"),
             ("6", "🔁", "결과로 보정", "실제 조사 결과를 다시 검증 데이터로")]
    grid([feature(icon, f"{no}. {title}", text) for no, icon, title, text in steps], 3)
    st.write("")
    st.markdown('<div class="section-title">롯데칠성음료에서 쓰일 곳</div>', unsafe_allow_html=True)
    grid([feature("🧪", "컨셉 스크리닝", "수십 개 컨셉 후보를 하루 안에 걸러 FGI·설문 대상 수를 줄임"),
          feature("💰", "가격대 탐색", "같은 패널로 가격만 바꿔 구매 비율·지불의사가격 변화를 비교"),
          feature("✍️", "네이밍·카피 A/B", "이름·문구만 바꾼 안을 같은 패널에 비교해 방향을 좁힘"),
          feature("🎯", "타깃 탐색", "연령·성별·지역·1인 가구별로 어디서 반응이 좋은지 확인"),
          feature("🔄", "자사 제품 잠식 확인", "진열대에 자사 기존 제품을 함께 두고 신제품이 어디서 점유를 가져오는지 확인"),
          feature("🧓", "모으기 어려운 집단", "FGI로 모으기 어려운 고령층·지방 거주자 반응을 미리 점검")], 3)

# ------------------------------------------------------------------ ⑦ 한계
with tabs[7]:
    st.markdown('<div class="section-title">한계와 로드맵</div>', unsafe_allow_html=True)
    grid([feature("✅", "지금 알 수 있는 것",
                  "연령대별 음료 선호의 방향과 대략적인 크기(탄산·이온 선호는 실제 설문과 연령별 1~4%p), "
                  "같은 패널에서 가격·문구를 바꿨을 때의 상대적 반응 차이"),
          feature("⚠️", "조심해야 할 것",
                  "전체 음료 분포 오차(약 3.4%p)는 실제 설문끼리 차이(1.2~1.8%p)의 약 2배입니다. "
                  "3%p 미만 차이는 단정하지 않습니다. 검증 기준은 '좋아하는 음료' 설문이라 실제 구매와 다를 수 있고, "
                  "합성 페르소나에는 음료 습관·소득·브랜드 충성도 정보가 없습니다.")])
    st.write("")
    st.markdown("**발견한 LLM 편향과 대응** — 같은 성향을 세 번 확인했습니다")
    st.dataframe(pd.DataFrame([
        ["진열대(첫 실행)", "무가당 탄산수 79% 쏠림, 5점 응답 0건", "대조실험으로 원인 분리 → 100명 분포 응답"],
        ["설문 재현", "녹차·커피 과다, 우유류 0명, '먹어본 적 없음' 실종", "100명 분포 응답 + 실제 설문으로 검증"],
        ["캡스톤 연구", "상권 방문 토요일 74%(실제 11.7%)", "시간·요일은 실데이터로 고정"],
    ], columns=["실험", "나타난 편향", "대응"]), hide_index=True, width="stretch")
    st.markdown("**로드맵**")
    grid([feature("1", "롯데칠성 데이터 연결", "판매·조사 데이터로 패널 비율 조정과 결과 보정"),
          feature("2", "사후 검증", "과거 출시 제품을 시뮬레이션해 실제 성과 순위와 비교"),
          feature("3", "보안", "사내 데이터는 사내 배포형 모델로 교체(구조상 교체 가능)"),
          feature("4", "확산", "같은 구조로 다른 식품·유통 계열사 신제품 검증")])
