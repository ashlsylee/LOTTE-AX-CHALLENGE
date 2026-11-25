"""Light presentation and explanations shared by PreShelf's review screens."""
from html import escape
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from .config import DEMO_DIR, result_files
from .fgi import ROUNDS

LIGHT_STYLE = """
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;800&display=swap" rel="stylesheet">
<style>
html, body, [class*="css"], .stMarkdown, button, input, textarea {font-family:'Noto Sans KR',sans-serif !important;}
h1 {font-size:1.55rem !important; font-weight:800 !important; letter-spacing:-.02em;}
h2 {font-size:1.3rem !important; font-weight:700 !important; letter-spacing:-.01em;}
h3 {font-size:1.1rem !important; font-weight:700 !important;}
.preshelf-hero {margin-bottom:1.6rem;}
[data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"] {display:flex; align-items:center;}
[data-testid="stSidebarCollapsedControl"]::after, [data-testid="stExpandSidebarButton"]::after {
  content:"실행 설정 · API 키 · 분석 묶음"; font-size:.78rem; color:#71717a; margin-left:.35rem; white-space:nowrap;}
/* 맨 위 메뉴(라디오를 탭처럼). 동그라미는 숨기고 선택된 항목에 빨간 밑줄 */
div.st-key-nav [role="radiogroup"] {gap:.3rem; flex-wrap:wrap;}
div.st-key-nav [role="radiogroup"] label {padding:.6rem 1.05rem; border-radius:10px 10px 0 0; font-weight:600; margin:0 !important; cursor:pointer;}
div.st-key-nav [role="radiogroup"] label:hover {background:rgba(228,0,43,.05);}
div.st-key-nav [role="radiogroup"] label[data-selected="true"], div.st-key-nav [role="radiogroup"] label:has(input:checked)
  {background:rgba(228,0,43,.08); box-shadow:inset 0 -2px 0 #E4002B;}
div.st-key-nav [role="radiogroup"] label[data-selected="true"] p, div.st-key-nav [role="radiogroup"] label:has(input:checked) p {color:#b3001f;}
div.st-key-nav [data-testid="stRadioOption"] > div > div:first-child,
div.st-key-nav [role="radiogroup"] label > div:first-child:not([data-testid]) {display:none;}
.nav-line {border-bottom:1px solid #e4e4e7; margin:-.6rem 0 1.2rem;}
.stTabs [role="tablist"] {gap:.3rem; border-bottom:1px solid #e4e4e7; margin-bottom:1rem;}
.stTabs [role="tab"] {padding:.7rem 1.1rem !important; border-radius:10px 10px 0 0; font-weight:600;}
.stTabs [role="tab"]:hover {background:rgba(228,0,43,.05);}
.stTabs [role="tab"][aria-selected="true"] {background:rgba(228,0,43,.08);}
.stTabs .stTabs [role="tab"] {padding:.45rem .8rem !important;}
[data-testid="stAppViewContainer"] {
  background: radial-gradient(1200px 500px at 50% -200px, rgba(228,0,43,.08), transparent 70%), #F7F7F8;
}
[data-testid="stHeader"] {background: transparent;}
[data-testid="stSidebar"] {background:#fff; border-right:1px solid #e4e4e7;}
.block-container {max-width:1200px; padding-top:3.6rem;}
.preshelf-hero {
  padding:1.6rem 2rem; border-radius:22px; border:1px solid #f2d7dd;
  background:radial-gradient(600px 260px at 15% 0%, rgba(228,0,43,.14), transparent 70%),
             linear-gradient(135deg,#FFE8EC,#fff 65%);
  box-shadow:0 6px 24px rgba(0,0,0,.06);
}
.preshelf-hero .eyebrow {color:#b3001f; font-size:.78rem; font-weight:700; letter-spacing:.08em;}
.preshelf-hero h1 {font-size:2rem !important; line-height:1.2; margin:.45rem 0; color:#18181b;}
.preshelf-hero p {margin:0; color:#3f3f46;}
.preshelf-cards {display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:.8rem; margin:.5rem 0 1rem;}
.preshelf-card {
  background:linear-gradient(180deg,#fff5f6,#fff); border:1px solid #f2d7dd;
  border-radius:16px; padding:1rem; box-shadow:0 6px 24px rgba(0,0,0,.04);
}
.preshelf-card strong {display:block; color:#18181b; margin-bottom:.35rem;}
.preshelf-card span {display:block; color:#3f3f46; font-size:.92rem;}
.preshelf-bubble {background:#fff; border:1px solid #e4e4e7; border-radius:14px; padding:.65rem .9rem; margin:.45rem 0;}
.preshelf-bubble span {color:#a30021; margin-left:.6rem; font-size:.85rem; font-weight:600;}
.preshelf-bubble p {margin:.35rem 0 0; color:#3f3f46; white-space:pre-wrap;}
[data-testid="stMetric"] {background:#fff; border:1px solid #e4e4e7; border-radius:16px; padding:.9rem 1rem;}
[data-testid="stExpander"] {border-color:#e4e4e7; border-radius:14px;}

/* ---------- 결과 화면 ---------- */
.verdict {border-radius:18px; padding:1.3rem 1.6rem; margin:.4rem 0 1rem; border:1px solid; display:flex; gap:1.2rem; align-items:flex-start;}
.verdict .badge {font-weight:800; font-size:.95rem; padding:.35rem .8rem; border-radius:99px; white-space:nowrap; color:#fff;}
.verdict h3 {margin:0 0 .35rem; font-size:1.25rem !important;}
.verdict p {margin:0; color:#3f3f46; line-height:1.6;}
.v-go {background:#f0fdf4; border-color:#bbf7d0;} .v-go .badge {background:#16a34a;}
.v-mid {background:#fffbeb; border-color:#fde68a;} .v-mid .badge {background:#d97706;}
.v-stop {background:#fff1f2; border-color:#fecdd3;} .v-stop .badge {background:#E4002B;}
.kpis {display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:.7rem; margin:.3rem 0 1.4rem;}
.kpi {background:#fff; border:1px solid #e4e4e7; border-radius:16px; padding:.9rem 1rem; box-shadow:0 4px 16px rgba(0,0,0,.04);}
.kpi .l {font-size:.8rem; color:#71717a; font-weight:600;}
.kpi .v {font-size:1.7rem; font-weight:800; color:#18181b; line-height:1.25; margin-top:.15rem;}
.kpi .v.red {color:#E4002B;}
.kpi .s {font-size:.8rem; color:#52525b; margin-top:.2rem;}
.fb {background:#fff; border:1px solid #e4e4e7; border-radius:16px; padding:1rem 1.15rem; height:100%;}
.fb .t {font-size:.8rem; font-weight:700; color:#b3001f; letter-spacing:.04em; margin-bottom:.35rem;}
.fb p {margin:0; color:#27272a; line-height:1.65; font-size:.95rem;}
.fbgrid {display:grid; grid-template-columns:1fr 1fr; gap:.8rem; margin-bottom:.8rem;}
.imps {display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:.8rem; margin-bottom:.8rem;}
.imp {background:linear-gradient(180deg,#fff5f6,#fff); border:1px solid #f2d7dd; border-radius:16px; padding:1rem 1.1rem;}
.imp .k {display:inline-block; font-size:.75rem; font-weight:800; color:#fff; background:#E4002B; border-radius:99px; padding:.15rem .6rem; margin-bottom:.45rem;}
.imp b {display:block; color:#18181b; margin-bottom:.3rem; line-height:1.45;}
.imp span {font-size:.88rem; color:#52525b; line-height:1.55;}
.ask {background:#18181b; color:#fff; border-radius:16px; padding:1rem 1.2rem; margin-bottom:.8rem;}
.ask .t {font-size:.8rem; font-weight:700; color:#fda4af;}
.ask p {margin:.3rem 0 0; color:#fafafa; font-size:1.02rem;}
.cases {display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:.7rem; margin-bottom:1.6rem;}
.case {background:#fff; border:1px solid #e4e4e7; border-radius:14px; padding:.85rem 1rem;}
.case .pill {display:inline-block; font-size:.72rem; font-weight:800; border-radius:99px; padding:.1rem .55rem; margin-right:.3rem;}
.p-stop {background:#fee2e2; color:#b91c1c;} .p-run {background:#dcfce7; color:#15803d;} .p-etc {background:#f4f4f5; color:#52525b;}
.case b {display:block; margin:.35rem 0 .25rem; color:#18181b;}
.case span {font-size:.85rem; color:#52525b; line-height:1.5;}
.flowbar {display:flex; gap:.35rem; flex-wrap:wrap; margin:.2rem 0 1rem;}
.flowbar div {font-size:.8rem; font-weight:700; padding:.35rem .75rem; border-radius:99px; background:#f4f4f5; color:#71717a;}
.flowbar div.on {background:#E4002B; color:#fff;}
.vals {display:grid; grid-template-columns:1fr 1fr; gap:.8rem; margin:.2rem 0 .6rem;}
.val {border-radius:18px; padding:1.1rem 1.3rem; border:1px solid #f2d7dd; background:linear-gradient(135deg,#fff1f3,#fff 70%); box-shadow:0 6px 20px rgba(0,0,0,.05);}
.val.g {border-color:#bbf7d0; background:linear-gradient(135deg,#ecfdf5,#fff 70%);}
.val .l {font-size:.82rem; font-weight:700; color:#b3001f; letter-spacing:.03em;}
.val.g .l {color:#15803d;}
.val .v {font-size:2rem; font-weight:800; color:#18181b; line-height:1.2; margin:.2rem 0 .3rem;}
.val .v small {font-size:1rem; font-weight:600; color:#52525b;}
.val .s {font-size:.88rem; color:#3f3f46; line-height:1.6;}
.val .chips {margin-top:.45rem;}
.val .chip {display:inline-block; font-size:.75rem; font-weight:700; border-radius:99px; padding:.15rem .6rem; margin:.15rem .25rem 0 0; background:#fff; border:1px solid #e4e4e7; color:#3f3f46;}
.persona-head {border-radius:20px; padding:1.2rem 1.4rem; margin:.6rem 0 .8rem; color:#fff;
  background:linear-gradient(120deg,#18181b,#3f0a14 60%,#7f1d1d); box-shadow:0 8px 28px rgba(0,0,0,.12);}
.persona-head .e {font-size:.78rem; font-weight:700; letter-spacing:.08em; color:#fda4af;}
.persona-head h3 {color:#fff; margin:.3rem 0 .4rem; font-size:1.3rem !important;}
.persona-head p {margin:0; color:#e4e4e7; line-height:1.6;}
.persona-stats {display:flex; gap:.6rem; flex-wrap:wrap; margin-top:.8rem;}
.persona-stats div {background:rgba(255,255,255,.1); border:1px solid rgba(255,255,255,.18); border-radius:12px; padding:.45rem .8rem;}
.persona-stats b {display:block; font-size:1.15rem; color:#fff;} .persona-stats span {font-size:.75rem; color:#d4d4d8;}
.personas {display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:.7rem; margin-bottom:1.2rem;}
.pcard {background:#fff; border:1px solid #e4e4e7; border-radius:16px; padding:.9rem 1rem;}
.pcard .who {display:flex; gap:.6rem; align-items:center; margin-bottom:.45rem;}
.pcard .av {width:38px; height:38px; border-radius:99px; background:#FFE8EC; display:flex; align-items:center; justify-content:center; font-size:1.2rem;}
.pcard b {color:#18181b;} .pcard .meta {font-size:.78rem; color:#71717a;}
.pcard p {margin:.25rem 0 0; font-size:.86rem; color:#3f3f46; line-height:1.55;}
.pcard .buy {margin-top:.45rem; font-size:.8rem; color:#7f1d1d; background:#fff5f6; border-radius:10px; padding:.4rem .6rem; line-height:1.5;}
.vhead {border-radius:18px; padding:1.1rem 1.4rem; margin:.4rem 0 .9rem; background:#fff; border:1px solid #e4e4e7;}
.vhead h3 {margin:0 0 .3rem;} .vhead p {margin:0; color:#3f3f46; line-height:1.6;}
@media(max-width:900px){.vals,.personas{grid-template-columns:1fr}}
@media(max-width:900px){.kpis{grid-template-columns:repeat(2,1fr)} .fbgrid,.imps,.cases{grid-template-columns:1fr}}
@media(max-width:660px) {
  .preshelf-hero {padding:1.4rem;}
  .preshelf-cards {grid-template-columns:1fr;}
}
</style>
"""


def hero():
    st.markdown(
        LIGHT_STYLE + """
<div class="preshelf-hero">
  <div class="eyebrow">LOTTE AX Challenge · 음료 신제품 시장 검증</div>
  <h1>프리셸프 PreShelf</h1>
  <p>출시 전에 과거 사례와 가상 소비자 반응을 확인해, 다음에 검증할 음료 아이디어를 고릅니다.</p>
</div>
""",
        unsafe_allow_html=True,
    )


def cards(items):
    body = "".join(
        f'<div class="preshelf-card"><strong>{escape(title)}</strong><span>{escape(description)}</span></div>'
        for title,description in items
    )
    st.markdown(f'<div class="preshelf-cards">{body}</div>',unsafe_allow_html=True)


def introduction():
    cards([
        ("과거 사례와 트렌드", "비슷한 판매 제품과 중단 아이디어, POS·유통 조건을 확인합니다."),
        ("가상 소비자 평가", "진열대 선택 분포와 좌담회에서 나온 구매·외면 이유를 함께 봅니다."),
        ("다음 검증 결정", "개선안과 실제 조사 질문을 고르고, 근거와 판단을 기록합니다."),
    ])
    with st.expander("프로그램 설명 · 작동 방식과 데이터"):
        st.markdown(
            "**컨셉 입력 → 근거 조회 → 정량·정성 평가 → 수정안과 실제 조사 선정**\n\n"
            "- **근거 조회**는 대회 제공 가상 제품자산·판매·구매여정·트렌드와 검토한 과거 자료를 사용합니다.\n"
            "- **진열대 시뮬레이션**은 신제품·경쟁품·미구매 선택을 비교합니다. B안 가격을 넣으면 동일 패널에서 가격 조건을 비교합니다.\n"
            "- **가상 FGI**는 같은 패널에서 뽑은 참여자의 첫인상, 걸림돌, 개선 조건을 세 라운드로 정리합니다.\n"
            "- **패널 구성**은 Nemotron 생활 배경과 제공 음료 구매 행동을 결합합니다. 60세 이상은 탐색 평가로 표시합니다.\n"
            "- **결과 사용**은 수정할 가설과 후속 실제 조사를 고르는 데 초점을 둡니다. 저장된 KREI 비교는 일반 음료 선호 설문을 재현한 실험입니다."
        )
        st.markdown("[Nemotron 페르소나 출처](https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea) · "
                    "[KREI 식품소비행태조사](https://www.krei.re.kr/foodSurvey/page/460)")


def example_results():
    with st.expander("저장된 시연 예시 · 복숭아 제로 스파클링과 설문 검증"):
        st.caption("이전 실행에서 저장한 시연 결과입니다. 가상 선택률로 가격 비교를 읽는 예시입니다.")
        for report in sorted(DEMO_DIR.glob("agent_*/report.md"),reverse=True)[:1]:
            st.markdown(report.read_text(encoding="utf-8"))
        for compare in sorted(DEMO_DIR.glob("survey_*/comparison.csv"),reverse=True)[:1]:
            st.markdown("**KREI 음료 선호 설문 재현 예시**")
            data = pd.read_csv(compare)
            columns = ["condition","fav_mae","zero_mae(검증)"]
            st.dataframe(data[columns].rename(columns={
                "condition":"조건","fav_mae":"1순위 선호 평균절대오차(%p)",
                "zero_mae(검증)":"제로음료 섭취 빈도 오차(%p)"}),hide_index=True)


def show_shelf(details):
    products = pd.DataFrame(details.get("products",[]))
    if not products.empty:
        st.dataframe(products[["name","price","volume_ml","description"]].rename(columns={
            "name":"제품","price":"가격(원)","volume_ml":"용량(mL)","description":"설명"}),hide_index=True)
    if details.get("choices"):
        frame = pd.DataFrame(details["choices"]).set_index("제품")
        st.bar_chart(frame,horizontal=True,x_label="선택 비율(%)")


def show_fgi(result):
    if not result or not result.get("turns"):
        return
    stance = result.get("final_stance",{})
    cards([(f"{label} · {stance.get(label,0)}명",description) for label,description in
           [("살 것","구매 의사"),("고민","구매를 망설임"),("안 살 것","구매 의사 없음")]])
    for round_no,question in enumerate(ROUNDS,1):
        st.markdown(f"**{round_no}라운드 · {question}**")
        for turn in result["turns"]:
            if turn["round"]!=round_no:
                continue
            speaker = escape(turn["speaker"])
            reply = escape(turn.get("reply_to") or "")
            to = f" → {reply}" if reply else ""
            st.markdown(f'<div class="preshelf-bubble"><strong>{speaker}{to}</strong>'
                        f'<span>{escape(turn["stance"])}</span><p>{escape(turn["utterance"])}</p></div>',
                        unsafe_allow_html=True)


def agent_design_page():
    st.header("에이전트 설계")
    st.write("상품기획자가 입력한 컨셉을 자료와 대조하고, 가상 소비자 반응을 분석해 다음에 검증할 질문을 제안합니다.")
    cards([
        ("근거 조회", "과거 컨셉·유사 SKU·POS·진열 인프라·트렌드를 찾아 컨셉의 강점과 제약을 점검합니다."),
        ("정량·정성 평가", "같은 타깃으로 진열대 선택을 집계하고, 좌담회에서 구매 이유와 걸림돌을 확인합니다."),
        ("보고서와 판단", "AI가 수정안과 다음 조사 질문을 제안하면 담당자가 판단을 기록합니다."),
    ])
    st.subheader("데이터와 처리 방식")
    st.table(pd.DataFrame([
        ["자료 등록", "표준 엑셀은 필수 시트·열·단위를 검사해 SQLite에 등록합니다. 옛 자료는 AI가 분류 초안을 만들고 담당자가 확인합니다."],
        ["평가 패널", "Nemotron 생활 배경에 제공 패널의 음료 구매 행동을 붙입니다. 시드, 표집 인원과 행동 원천 수를 보고서에 표시합니다."],
        ["가격 비교", "A/B는 같은 페르소나와 진열 순서를 사용합니다. 양쪽에서 유효한 응답으로 가격 차이를 비교하며 미구매도 집계합니다."],
        ["피드백과 재검토", "AI가 자료와 평가를 해석하고, 담당자가 수정·실제 조사·보류를 결정합니다. 사용한 데이터 버전과 결과를 저장합니다."],
    ],columns=["단계","현재 동작"]))
    st.caption("‘근거 먼저 보기’에서는 평가 시점을 사용자가 결정합니다. ‘평가까지 한 번에’에서는 조회와 평가가 이어집니다. 동일한 모델 요청은 캐시를 재사용합니다.")
    st.subheader("현업 적용 예시")
    st.markdown(
        "- **시즌 음료 선별** · 유사 제품 판매 이력과 시즌 신호로 실제 검증할 컨셉을 좁힙니다.\n"
        "- **가격 탐색** · 같은 진열대에서 가격만 바꿔 가상 선택 분포가 어떻게 움직이는지 확인합니다.\n"
        "- **유통 제약 검토** · 냉동 파우치에 호의적인 반응이 있어도, 실제로 진열할 수 있는 채널과 점포를 별도로 확인합니다."
    )
    traces = sorted(DEMO_DIR.glob("agent_*/trace.json"),reverse=True)
    if traces:
        labels = {"check_reliability":"기준 설문 검증 확인","compare_prices":"동일 패널 가격 비교",
                  "get_reasons":"구매·외면 이유 확인","write_report":"검토 보고서 작성"}
        with st.expander("저장된 에이전트 실행 예시 · 복숭아 제로 스파클링"):
            trace = json.loads(traces[0].read_text(encoding="utf8"))
            st.caption("이전 에이전트 실행 기록입니다. 신제품 검토 화면에서는 두 가지 실행 경로로 통합했습니다.")
            st.table(pd.DataFrame([{"순서":r["step"],"실행":labels.get(r["tool"],r["tool"])}
                                   for r in trace]))


def limits_page():
    st.header("한계와 로드맵")
    st.write("가상 평가로 다음 조사에서 검증할 가설을 좁힙니다. 출시 판단에는 실제 소비자 조사와 매장 파일럿 근거를 함께 사용합니다.")
    cards([
        ("표본과 연령", "가상 평가 수와 제공 행동 원천 수를 구분합니다. 60세 이상은 제공 음료 패널 근거가 없는 탐색 결과입니다."),
        ("A/B와 좌담회", "작은 선택률 차이는 반복 평가로 확인합니다. 좌담회는 이유와 개선안 탐색에 쓰입니다."),
        ("트렌드 해석", "대회 검색지수는 가상 자료입니다. Google Trends를 추가할 경우 상대 검색 관심도를 POS·유통 근거와 함께 해석합니다."),
    ])
    st.caption("검증 수치는 '신뢰도 검증' 메뉴에서 봅니다.")
    st.subheader("다음 검증")
    st.table(pd.DataFrame([
        ["시뮬레이션 재현성", "표집 시드를 바꿔 가격·컨셉 판단이 같은 방향인지 확인합니다."],
        ["실제 소비자 확인", "소규모 설문과 매장 파일럿에서 구매의향·선택·판매를 각각 비교합니다."],
        ["현업 데이터 연결", "실제 POS·입점·회전 자료의 접근 권한과 출처 기록을 정한 뒤 연동합니다."],
    ],columns=["과제","확인할 내용"]))


RULES = [
    ["주 지표 (KREI)", "연령대별 '좋아하는 음료 1순위' 분포 오차(fav_mae)", "가장 작은 응답 방식을 기본으로 채택 → 100명 분포 응답"],
    ["검증 지표 (KREI)", "제로 음료 섭취 빈도 오차", "설정 선택에 쓰지 않음(과적합 점검)"],
    ["참고선 (KREI)", "실제 설문끼리 연도 비교 1.2~1.8%p · 무작위 응답", "오차 수준 해석"],
    ["컨셉 대조 (제공 설문)", "가상 '사 볼 의향' vs 구매의향 TOP2(4~5점)", "차이 10%p 이내면 '비슷함', 넘으면 보정 계수 표시 + 실제 조사 우선"],
    ["컨셉 대조 참고선", "모든 컨셉에 설문 평균 하나만 쓸 때 오차", "가상 오차가 이보다 작아야 컨셉 간 차이를 구분한다고 봄"],
    ["분할", "제공 설문 응답자를 ID 해시로 반씩 나눔", "절반은 패널 구매 행동, 절반은 대조용 → 같은 사람을 두 번 쓰지 않음"],
    ["조건 차이", "가격·문구 두 조건의 선택률 차이", "3%p 미만이면 '뚜렷하지 않음'"],
]


def show_validation(check):
    st.dataframe(pd.DataFrame({"항목":list(check),"값":[str(v) for v in check.values()]}),hide_index=True,width="stretch")


def reliability_page(data):
    st.header("이 패널을 어디까지 믿을 수 있나")
    st.write("두 가지로 확인합니다. ① 공개 정부 설문(KREI)과 같은 질문을 페르소나에게 묻는 일반 검증, "
             "② 제공된 소비자 조사의 컨셉별 구매의향과 가상 응답을 맞춰 보는 컨셉 검증.")
    vals = [f for f in result_files("validation_*/result.json")][::-1]
    st.subheader("② 제공 설문과 컨셉별 대조")
    if vals:
        loaded = {}
        for f in vals:
            try:
                loaded[f] = json.loads(Path(f).read_text(encoding="utf8"))
            except Exception:
                continue

        def label(f):
            r = loaded[f]
            return " · ".join(x for x in [r.get("project") or "전체 컨셉", str(r.get("time", ""))[5:], f"컨셉당 {r.get('n')}명",
                                          "모의" if r.get("mock") else ""] if x)
        pick = st.selectbox("대조 결과", list(loaded), format_func=label)
        validation_view(loaded[pick])
    else:
        st.info("아직 실행한 컨셉 대조가 없습니다. 아래에서 실행하세요.")
    st.subheader("① KREI 일반 음료 선호 설문 재현")
    comps = [f for f in result_files("survey_*/comparison.csv") if "_mock" not in f]
    if comps:
        t = pd.read_csv(comps[-1]).set_index("condition")
        names = {"prob":"100명 분포 응답(채택)","prob(argmax)":"분포 중 가장 큰 답만","base":"한 사람 응답","무작위 기준선":"무작위 응답"}
        st.dataframe(pd.DataFrame([{"응답 방식":label,"1순위 분포 오차(%p)":t.at[k,"fav_mae"],
                                    "탄산·이온 4종 오차(%p)":t.at[k,"four_rate_mae"],"제로 섭취 오차(검증, %p)":t.at[k,"zero_mae(검증)"]}
                                   for k,label in names.items() if k in t.index]),hide_index=True,width="stretch")
        st.caption("실제 설문끼리 연도를 바꿔 비교해도 1.2~1.8%p 차이가 납니다. 이 검증은 이전 패널 구성(구매 행동 결합 전)으로 한 것입니다.")
    with st.expander("📏 평가 규칙 (결과를 보기 전에 정한 기준)"):
        st.table(pd.DataFrame(RULES,columns=["항목","무엇을 보나","판단"]))



# ---------------- 결과 화면(신제품 검토 · 검토 이력 공용) ----------------
def _e(x):
    return escape(str(x if x is not None else ""))


def flowbar(done: int):
    steps = ["① 자료", "② 데이터 경고", "③ 과거·트렌드", "④ 가상 소비자", "⑤ 개선 리포트", "⑥ 실제 조사 연결"]
    st.markdown('<div class="flowbar">' + "".join(f'<div class="{"on" if i < done else ""}">{x}</div>' for i, x in enumerate(steps)) + "</div>",
                unsafe_allow_html=True)


def verdict_banner(title: str, detail: str = ""):
    t = str(title)
    cls, badge = ("v-stop", "보류") if t.startswith(("보류", "판단 불가")) else ("v-go", "진행") if t.startswith(("진행", "재시도")) else ("v-mid", "조건부")
    st.markdown(f'<div class="verdict {cls}"><div class="badge">{badge}</div><div><h3>{_e(t)}</h3><p>{_e(detail)}</p></div></div>',
                unsafe_allow_html=True)


def kpi_cards(k: dict):
    cards = [("진열대에서 신제품 선택", f"{k.get('shelf', 0):.1f}%", f"가상 소비자 {k.get('n_ok', '-')}명 · 미구매 포함")]
    if "top2" in k:
        sub = f"실제 설문(보정) {k['survey_top2']:.1f}%" if k.get("survey_top2") is not None else "같은 문항 가상 설문"
        cards.append(("가상 구매의향 TOP2", f"{k['top2']:.1f}%", sub))
    if "wtp" in k:
        cards.append(("지불가격 중앙값", f"{int(k['wtp']):,}원", f"소비자가 {int(k['price']):,}원 대비 {int(k['wtp']) - int(k['price']):+,}원"))
    if k.get("trial"):
        a, b = k["trial"][0], k["trial"][1]
        cards.append(("예상 12개월 구매경험률", f"약 {a}%" if a == b else f"{a}~{b}%",
                      "과거 컨셉테스트 환산" + (" · 근거 1건(참고)" if a == b else "")))
    cards.append(("실행", f"{k.get('seconds', 0):.0f}초", f"새 응답 {k.get('new_calls', 0)}건 · 약 ${k.get('cost', 0):.2f}"))
    html = "".join(f'<div class="kpi"><div class="l">{_e(l)}</div><div class="v{" red" if i == 0 else ""}">{_e(v)}</div><div class="s">{_e(sb)}</div></div>'
                   for i, (l, v, sb) in enumerate(cards))
    st.markdown(f'<div class="kpis">{html}</div>', unsafe_allow_html=True)


def feedback_cards(fb: dict):
    st.markdown(f'<div class="fbgrid"><div class="fb"><div class="t">과거에 왜 안 됐나</div><p>{_e(fb.get("past_failure"))}</p></div>'
                f'<div class="fb"><div class="t">트렌드·타이밍</div><p>{_e(fb.get("trend_fit"))}</p></div></div>', unsafe_allow_html=True)
    imps = fb.get("improvements") or []
    if imps:
        st.markdown("**개선안**")
        st.markdown('<div class="imps">' + "".join(f'<div class="imp"><div class="k">{_e(x.get("kind"))}</div><b>{_e(x.get("change"))}</b><span>{_e(x.get("why"))}</span></div>'
                                                   for x in imps[:3]) + "</div>", unsafe_allow_html=True)
    st.markdown(f'<div class="fb" style="margin-bottom:.8rem"><div class="t">가격·손익</div><p>{_e(fb.get("price"))}</p></div>', unsafe_allow_html=True)
    if fb.get("survey_question"):
        with st.expander("🙋 실제 조사로 확인할 질문 (펼쳐 보기)"):
            st.markdown(f'<div class="ask"><p>{_e(fb.get("survey_question"))}</p></div>', unsafe_allow_html=True)


def case_cards(history: list):
    if not history:
        st.caption("비슷한 과거 사례가 없습니다.")
        return
    out = []
    for h in history[:6]:
        stt = str(h.get("상태", ""))
        cls = "p-stop" if any(x in stt for x in ("단종", "중단")) else "p-run" if "운영" in stt else "p-etc"
        reason = h.get("중단 사유") if h.get("중단 사유") not in (None, "자료 없음") else ("판매 중" if cls == "p-run" else "사유 기록 없음")
        out.append(f'<div class="case"><span class="pill {cls}">{_e(stt)}</span><span class="pill p-etc">{_e(h.get("사유 유형"))}</span>'
                   f'<b>{_e(h.get("제품"))}</b><span>{_e(reason)}</span></div>')
    st.markdown('<div class="cases">' + "".join(out) + "</div>", unsafe_allow_html=True)


def shelf_chart(choices: list, concept: str, prices: dict | None = None):
    """진열대 선택 비율 + 100명이 진열대 앞에 섰을 때 제품별 매출(선택 인원 × 가격)."""
    import altair as alt
    if not choices:
        return
    prices = prices or {}
    df = pd.DataFrame(choices)
    df["구분"] = df["제품"].map(lambda x: "신제품" if x == concept else ("미구매" if x == "미구매" else "비교 제품"))
    ok = lambda v: v is not None and v == v and v != 0  # noqa: E731  None·NaN·0 제외
    price_of = [prices.get(x) for x in df["제품"]]
    df["가격(원)"] = [int(p) if ok(p) else None for p in price_of]
    df["100명당 매출(원)"] = [int(round(r * p)) if ok(p) else None for r, p in zip(df["선택 비율(%)"], price_of)]
    df["표시"] = [f"{r:.1f}%" + (f" · {int(round(r * p)):,}원" if ok(p) else "") for r, p in zip(df["선택 비율(%)"], price_of)]
    chart = alt.Chart(df).mark_bar(cornerRadiusEnd=6, height=22).encode(
        x=alt.X("선택 비율(%):Q", title="진열대 선택 비율(%)", scale=alt.Scale(domain=[0, max(df["선택 비율(%)"].max() * 1.45, 10)])),
        y=alt.Y("제품:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
        color=alt.Color("구분:N", scale=alt.Scale(domain=["신제품", "비교 제품", "미구매"], range=["#E4002B", "#a1a1aa", "#e4e4e7"]), legend=None),
        tooltip=["제품", "선택 비율(%)", "가격(원)", "100명당 매출(원)"]).properties(height=36 * len(df) + 20)
    text = chart.mark_text(align="left", dx=4, color="#3f3f46").encode(text="표시:N")
    st.altair_chart((chart + text).configure_view(strokeWidth=0).configure(background="transparent"), use_container_width=True)
    if prices:
        st.caption("숫자 = 선택 비율 · 100명이 진열대 앞에 섰을 때 그 제품 매출(선택 인원 × 가격)")


def survey_chart(cmp: list):
    import altair as alt
    if not cmp:
        return
    rows = []
    for r in cmp:
        rows.append({"항목": r["항목"], "구분": "가상 소비자", "TOP2(%)": r["가상(%)"]})
        val = r.get("설문 제외+가중(%)")
        rows.append({"항목": r["항목"], "구분": "실제 설문(보정)", "TOP2(%)": val if val is not None and val == val else r.get("설문 품질 의심 제외(%)")})
    df = pd.DataFrame(rows)
    chart = alt.Chart(df).mark_bar(cornerRadiusEnd=4).encode(
        x=alt.X("항목:N", sort=["이해도", "호감도", "차별성", "구매의향", "가격수용도"], title=None, axis=alt.Axis(labelAngle=0)),
        xOffset="구분:N", y=alt.Y("TOP2(%):Q", title="4~5점 비율(%)"),
        color=alt.Color("구분:N", scale=alt.Scale(domain=["가상 소비자", "실제 설문(보정)"], range=["#E4002B", "#52525b"]),
                        legend=alt.Legend(orient="top", title=None)),
        tooltip=["항목", "구분", "TOP2(%)"]).properties(height=260)
    st.altair_chart(chart.configure_view(strokeWidth=0).configure(background="transparent"), use_container_width=True)


def products_chart(summary: list):
    import altair as alt
    if not summary:
        return
    df = pd.DataFrame(summary)
    if "구매의향 TOP2(%)" not in df:
        return
    first = df.iloc[0]["제품"]
    df["구분"] = df["제품"].map(lambda x: "신제품" if x == first else "비교 제품")
    chart = alt.Chart(df).mark_bar(cornerRadiusEnd=6, height=22).encode(
        x=alt.X("구매의향 TOP2(%):Q", title="같은 문항 구매의향 TOP2(%)"), y=alt.Y("제품:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
        color=alt.Color("구분:N", scale=alt.Scale(domain=["신제품", "비교 제품"], range=["#E4002B", "#a1a1aa"]), legend=None),
        tooltip=["제품", "가격(원)", "구매의향 TOP2(%)", "지불가격 중앙값(원)"]).properties(height=36 * len(df) + 20)
    st.altair_chart(chart.configure_view(strokeWidth=0).configure(background="transparent"), use_container_width=True)


def result_view(visual: dict, sections: dict, analysis: dict | None = None, mock: bool = False, cfg: dict | None = None):
    """결과 첫 화면: 판단 배너 → 핵심 숫자 → 매출·절감 → 과거·트렌드·개선안 → 차트. 자세한 표는 아래 펼침."""
    fb, kpi = visual.get("feedback") or {}, visual.get("kpi") or {}
    flowbar(6 if visual.get("survey_cmp") else 5)
    if mock:
        st.caption("모의 실행 · 수치와 발언은 동작 확인용입니다.")
    title = (analysis or {}).get("verdict", {}).get("판단") or visual.get("analysis_verdict") or fb.get("verdict", "")
    verdict_banner(title, fb.get("verdict", ""))
    if kpi:
        kpi_cards(kpi)  # 예상 매출·절감 카드는 뺌(매출 환산은 인지·유통 가정이 커서 과대해 보임, 절감은 프로젝트 기록에 한 번만)
    if fb:
        feedback_cards(fb)
    hist = (analysis or {}).get("history") or visual.get("history") or []
    if hist:
        st.markdown("**비슷한 과거 사례**")
        case_cards(hist)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**진열대에서 무엇을 집었나**")
        shelf_chart(visual.get("choices", []), kpi.get("concept", ""),
                    {p.get("name"): p.get("price") for p in visual.get("products") or []})
    with c2:
        if visual.get("survey_cmp"):
            st.markdown("**가상 소비자 vs 실제 설문(같은 문항)**")
            survey_chart(visual["survey_cmp"])
        elif (visual.get("survey") or {}).get("summary"):
            st.markdown("**같은 문항으로 본 신제품 vs 비교 제품**")
            products_chart(visual["survey"]["summary"])


def _first_run_seconds(calls: int) -> int:
    return int(calls * 0.63)  # 실측: 150명(301건) 첫 실행 189초


def value_cards(visual: dict, cfg: dict):
    """눈에 보이는 효과: 예상 월 매출(POS 환산)과 조사 비용·시간 절감, 그리고 계산 근거."""
    from . import insight
    kpi = visual.get("kpi") or {}
    try:
        rev = insight.revenue_estimate(visual, cfg)
    except Exception as exc:  # 자료가 없거나 형식이 달라도 결과 화면은 열려야 함
        rev = {"error": f"매출 환산을 하지 못했습니다: {exc}"}
    sv = insight.savings(kpi, cfg)
    fw = insight.fmt_won
    html = []
    if rev and not rev.get("error"):
        lo, mid, hi = rev["sales"]
        own = rev["cannibal"]
        sub = (f"범위 {fw(lo)} ~ {fw(hi)} · 월 {rev['units'][1]:,}개 · 소비자가 {rev['price']:,}원 기준"
               + (f"<br>자사 매출(출고가 {rev['cost_price']:,}원) <b>{fw(rev['revenue'][1])}</b>/월" if rev.get("revenue") else ""))
        chips = (f'<span class="chip">새 수요 {own["새 수요(미구매에서)"]}%</span>'
                 f'<span class="chip">자사 잠식 {own["자사 제품에서 이동"]}%</span>'
                 f'<span class="chip">경쟁사에서 {own["경쟁 제품에서 이동"]}%</span>')
        html.append(f'<div class="val"><div class="l">예상 월 매출 · 신제품 (POS 실판매 환산)</div>'
                    f'<div class="v">{fw(mid)} <small>/ 월</small></div><div class="s">{sub}</div><div class="chips">{chips}</div></div>')
    else:
        why = (rev or {}).get("error") or "등록된 판매(POS) 자료가 없습니다."
        html.append('<div class="val"><div class="l">예상 월 매출 · 신제품 (POS 실판매 환산)</div><div class="v" style="font-size:1.2rem">계산할 수 없음</div>'
                    f'<div class="s">{_e(why)}<br>② 신제품 검토에서 <b>판매 자료에서 같은 카테고리 비교 제품 불러오기</b>로 진열대를 채우면 계산됩니다.</div></div>')
    surveys = sv["surveys"]
    full = surveys[-1]
    quant = next((x for x in surveys if x[0] == "정량조사"), None)
    secs = _first_run_seconds(sv["calls"])
    html.append(f'<div class="val g"><div class="l">조사 비용·시간 절감 · 컨셉 1건</div>'
                f'<div class="v">{full[2]:,}만 원 → {fw(sv["krw"])}</div>'
                f'<div class="s">가상 소비자 {sv["n"]}명 · 약 ${sv["usd"]} · 약 {max(secs // 60, 1)}분 (첫 실행 기준)<br>'
                f'vs {full[0]} {full[1]} · {full[2]:,}만 원 · 최대 6주'
                + (f' / {quant[0]} {quant[1]} · {quant[2]:,}만 원' if quant else "") + "</div>"
                '<div class="chips"><span class="chip">과제 설명 자료(롯데칠성음료) 조사 비용 기준</span></div></div>')
    st.markdown('<div class="vals">' + "".join(html) + "</div>", unsafe_allow_html=True)
    with st.expander("📐 이 숫자를 얼마나 믿을 수 있나 · 계산 근거"):
        if rev and rev.get("error"):
            st.caption(rev["error"])
        elif rev:
            st.markdown(
                f"**계산** · 신제품 진열대 선택 {rev['share'][1]}% × 선택 1%p당 월 {rev['per_point'] / 100:,.0f}개"
                f"(같은 진열대 비교 제품들의 POS 월평균 판매 ÷ 그 제품들의 선택 비율)"
                + (f" × 취급 가능 점포 {rev['coverage']:.0%}" if rev["coverage"] < 1 else "")
                + f" = 월 {rev['units'][1]:,}개 × {rev['price']:,}원")
            st.dataframe(pd.DataFrame([{"비교 제품": r["제품"], "진열대 선택(%)": r["선택(%)"],
                                        "POS 월평균 판매(EA, 행사 포함)": f"{r['월평균 판매(EA)']:,}" if r.get("월평균 판매(EA)") else "-",
                                        "자사/경쟁": "-" if r.get("자사") is None else ("자사" if r["자사"] else "경쟁"),
                                        "POS 기간": str(r.get("기간", "POS에 없음 · 환산에서 제외")).replace("~", "–")} for r in rev["rows"]]),
                         hide_index=True, width="stretch")
            lines = [f"- **범위** · 가상 소비자 {rev['n']}명 표본의 95% 범위(선택 {rev['share'][0]}–{rev['share'][2]}%)를 그대로 매출로 옮긴 값입니다."]
            if rev["cover_detail"]:
                lines.append("- **유통 제약** · 보관 조건 때문에 취급 가능한 점포 비율 " +
                             ", ".join(f"{k} {v:.0%}" for k, v in rev["cover_detail"].items()) + "의 평균을 곱했습니다.")
            lines.append(f"- **자사 잠식** · 신제품 구매자가 지금 선택 비율대로 옮겨 온다고 보고 나눴습니다(자사: {', '.join(rev['own_products']) or '없음'}).")
            lines.append("- **가정** · 출시 후 소비자가 진열대에서 이 제품을 본다는 전제(인지·진열 동일)입니다. 출시 초기 인지도가 낮으면 아래쪽 범위에 가깝습니다.")
            cmp = [r for r in visual.get("survey_cmp") or [] if r.get("항목") == "구매의향"]
            if cmp:
                c = cmp[0]
                lines.append(f"- **실제 설문과 비교** · 같은 문항 구매의향 가상 {c['가상(%)']}% vs 실제 설문(보정) {c.get('설문 제외+가중(%)')}%. "
                             "이 자료에서는 가상 응답이 설문보다 낮게(보수적으로) 나옵니다.")
            lines.append("- **왜 설문 대신 진열대 선택으로 계산하나** · 과거 컨셉테스트에서 설문 구매의향 TOP2 45–61%가 실제 12개월 구매경험률 4–14%로 "
                         "줄었습니다(과거 컨셉테스트 실적). 설문 응답을 그대로 매출로 쓰면 크게 부풀려지므로, 경쟁 제품과 함께 고르는 진열대 선택을 씁니다.")
            lines.append("- **맞는지 확인하는 법** · 출시 후 POS 실제 판매를 '③ 신뢰도 검증'에 넣어 이 추정과 비교하고, 차이를 다음 검토의 보정에 씁니다.")
            st.markdown("\n".join(lines))
        st.markdown(f"**비용** · 이번 검토 호출 약 {sv['calls']}건 × {float(__import__('os').getenv('VM_COST_PER_CALL', '0.02'))}달러 "
                    f"= 약 {sv['usd']}달러 (환율 1달러 {sv['krw_rate']:,.0f}원 가정, .env VM_KRW_PER_USD). 같은 조건 재실행은 저장된 응답을 재사용해 거의 0원입니다.")
        st.dataframe(pd.DataFrame([{"조사": a, "인원·기간": b, "비용": f"{c:,}만 원"} for a, b, c in sv["surveys"]]
                                  + [{"조사": "PreShelf 가상 검토", "인원·기간": f"{sv['n']}명 · 약 {max(_first_run_seconds(sv['calls']) // 60, 1)}분",
                                      "비용": fw(sv["krw"])}]), hide_index=True, width="stretch")
        st.caption("조사 비용·기간: 과제 설명 자료(롯데칠성음료) '시장 조사 비용의 현실' 기준. 가상 검토는 실제 조사를 없애는 것이 아니라, "
                   "실제 조사할 컨셉을 고르는 앞단 필터입니다. 걸러낸 컨셉 수만큼 조사 비용이 절감됩니다.")


def persona_panel(samples: list[dict], pool_size: int, donors: int, n: int):
    """② 신제품 검토 맨 위: 누가 답하는지(AI 페르소나 가상 소비자)를 먼저 보여 준다."""
    stats = [(f"{pool_size:,}명", "후보 페르소나 풀"), (f"{n}명", "이번 평가 패널(기본)"),
             (f"{donors}명", "결합한 실제 패널 구매행동"), ("100만 명", "원천 · Nemotron-Personas-Korea")]
    st.markdown('<div class="persona-head"><div class="e">AI PERSONA PANEL</div>'
                '<h3>🧑‍🤝‍🧑 이 검토는 AI 페르소나 가상 소비자가 답합니다</h3>'
                '<p>한국 인구 분포로 만든 공개 페르소나(NVIDIA Nemotron-Personas-Korea)에 제공된 소비자 패널의 실제 음료 구매행동을 붙여, '
                '연령·성별 구성대로 뽑은 가상 소비자가 진열대에서 고르고 설문에 답합니다.</p>'
                '<div class="persona-stats">' + "".join(f"<div><b>{_e(a)}</b><span>{_e(b)}</span></div>" for a, b in stats) +
                "</div></div>", unsafe_allow_html=True)
    if samples:
        out = []
        for p in samples[:3]:
            icon = "👩" if str(p.get("sex", "")).startswith("여") else "👨"
            out.append(f'<div class="pcard"><div class="who"><div class="av">{icon}</div><div><b>{_e(p.get("age"))}세 {_e(p.get("sex"))}</b>'
                       f'<div class="meta">{_e(p.get("province"))} · {_e(p.get("occupation"))}</div></div></div>'
                       f'<p>{_e(p.get("persona"))}</p>'
                       + (f'<div class="buy">🥤 {_e(p.get("behavior"))}</div>' if p.get("behavior") else "") + "</div>")
        st.markdown('<div class="personas">' + "".join(out) + "</div>", unsafe_allow_html=True)


def rank_agreement(rows: list[dict]) -> tuple[int, int]:
    """컨셉 두 개씩 짝지어, 가상과 설문이 '어느 쪽이 높다'를 같게 본 쌍 수 / 전체 쌍 수."""
    same = total = 0
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a = rows[i]["사 볼 의향(가상, %)"] - rows[j]["사 볼 의향(가상, %)"]
            b = rows[i]["구매의향 TOP2(설문, %)"] - rows[j]["구매의향 TOP2(설문, %)"]
            if b == 0:
                continue
            total += 1
            same += (a > 0) == (b > 0) and a != 0
    return same, total


def validation_view(r: dict):
    """컨셉 대조 결과를 쉬운 말로: 한 줄 결론 → 순위 일치 → 그래프 → 간단한 표 → 자세히."""
    import altair as alt
    rows = r.get("rows") or []
    if not rows:
        st.caption("대조 결과가 비어 있습니다.")
        return
    gaps = [row["차이(%p)"] for row in rows]
    mean_gap = sum(gaps) / len(gaps)
    same, total = rank_agreement(rows)
    order_v = sorted(rows, key=lambda x: -x["사 볼 의향(가상, %)"])
    order_s = sorted(rows, key=lambda x: -x["구매의향 TOP2(설문, %)"])
    top_same = order_v[0]["컨셉"] == order_s[0]["컨셉"]
    direction = "낮게" if mean_gap < 0 else "높게"
    one_way = all(g < 0 for g in gaps) or all(g > 0 for g in gaps)
    msg = (f"가상 소비자는 실제 설문보다 평균 <b>{abs(mean_gap):.0f}%p {direction}</b> 답했습니다"
           + ("(모든 컨셉에서 같은 방향). " if one_way else ". ")
           + f"컨셉을 둘씩 비교하면 {total}쌍 중 <b>{same}쌍</b>에서 '어느 쪽이 더 높은가'가 실제 설문과 같습니다. "
           f"1위 컨셉은 {'<b>같습니다</b>' if top_same else '다릅니다'}(가상 {order_v[0]['컨셉']} · 설문 {order_s[0]['컨셉']}).")
    st.markdown(f'<div class="vhead"><h3>한 줄 결론</h3><p>{msg}</p><p style="margin-top:.5rem;color:#71717a;font-size:.88rem">'
                "가상 패널은 사람 조사를 대신해 '몇 %가 살지'를 맞히는 용도가 아니라, 여러 컨셉 중 <b>어느 것을 먼저 실제 조사할지</b> 고르는 용도입니다. "
                "그래서 절대값 차이보다 순위가 맞는지를 먼저 봅니다.</p></div>", unsafe_allow_html=True)
    if r.get("mock"):
        st.caption("모의 실행 결과입니다. 수치는 의미가 없습니다.")
    c1, c2, c3 = st.columns(3)
    c1.metric("컨셉 순위 일치", f"{same}/{total}쌍", help="컨셉 두 개씩 비교했을 때 가상과 설문이 같은 쪽을 더 높게 본 경우")
    c2.metric("평균 차이(가상 − 설문)", f"{mean_gap:+.1f}%p", help="음수면 가상이 보수적으로(낮게) 답함")
    c3.metric("차이 10%p 이내 컨셉", f"{r.get('within_rule', 0)}/{len(rows)}", help=f"결과를 보기 전에 정한 기준: 차이 {r.get('intent_gap_rule', 10):.0f}%p 이내면 '비슷함'")
    long = []
    for row in rows:
        long.append({"컨셉": row["컨셉"], "구분": "가상 소비자", "구매의향(%)": row["사 볼 의향(가상, %)"]})
        long.append({"컨셉": row["컨셉"], "구분": "실제 설문", "구매의향(%)": row["구매의향 TOP2(설문, %)"]})
    df = pd.DataFrame(long)
    chart = alt.Chart(df).mark_bar(cornerRadiusEnd=4).encode(
        x=alt.X("컨셉:N", title=None, axis=alt.Axis(labelAngle=0, labelLimit=200)), xOffset="구분:N",
        y=alt.Y("구매의향(%):Q", title="사겠다는 비율(%)"),
        color=alt.Color("구분:N", scale=alt.Scale(domain=["가상 소비자", "실제 설문"], range=["#E4002B", "#52525b"]),
                        legend=alt.Legend(orient="top", title=None)),
        tooltip=["컨셉", "구분", "구매의향(%)"]).properties(height=280)
    text = chart.mark_text(dy=-8, color="#3f3f46").encode(text=alt.Text("구매의향(%):Q", format=".0f"))
    st.altair_chart((chart + text).configure_view(strokeWidth=0).configure(background="transparent"), use_container_width=True)
    icon = {"비슷함": "✓ 비슷함", "가상 응답이 낮음": "↓ 가상이 낮음", "가상 응답이 높음": "↑ 가상이 높음"}
    st.dataframe(pd.DataFrame([{"컨셉": row["컨셉"], "가상(%)": row["사 볼 의향(가상, %)"], "실제 설문(%)": row["구매의향 TOP2(설문, %)"],
                                "차이(%p)": row["차이(%p)"], "판정": icon.get(row["판정"], row["판정"])} for row in rows]),
                 hide_index=True, width="stretch")
    with st.expander("자세히 · 용어와 원자료"):
        st.markdown(
            "- **가상(%)** · 진열대에서 '한 번 사 보겠다'고 한 가상 소비자 비율\n"
            "- **실제 설문(%)** · 제공 설문의 구매의향 4~5점 비율. 패널을 만들 때 쓰지 않은 응답자(검증용)만 사용해 정답을 미리 본 효과를 막았습니다.\n"
            "- **보정 계수** · 실제 설문 ÷ 가상. 실제 조사 결과가 쌓이면 이 값으로 가상 결과를 보정합니다.\n"
            f"- **평균 기준선** · 모든 컨셉에 설문 평균 하나만 썼을 때의 오차 {r.get('baseline_mae')}%p (가상 오차 {r.get('mae')}%p). "
            "가상 오차가 이보다 작으면 컨셉 간 차이까지 구분한다는 뜻입니다.")
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(f"{r.get('project') or '전체 컨셉'} · 자료 버전 {r.get('data_version')} · 컨셉당 {r.get('n')}명 · {r.get('time')}")
