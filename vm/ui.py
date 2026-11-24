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
[data-testid="stSegmentedControl"] {margin:.9rem 0 .4rem;}
[data-testid="stSegmentedControl"] button {font-weight:600; padding:.45rem 1rem;}
[data-testid="stSegmentedControl"] button[aria-checked="true"], [data-testid="stSegmentedControl"] button[kind="segmented_controlActive"]
  {background:#E4002B !important; color:#fff !important; border-color:#E4002B !important;}
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
        pick = st.selectbox("대조 결과",vals,format_func=lambda f: Path(f).parent.name.replace("validation_",""))
        r = json.loads(Path(pick).read_text(encoding="utf8"))
        c1,c2,c3 = st.columns(3)
        c1.metric("가상 vs 설문 오차",f"{r['mae']}%p",help="컨셉별 '사 볼 의향'과 구매의향 TOP2 차이의 평균")
        c2.metric("평균 기준선",f"{r['baseline_mae']}%p",help="모든 컨셉에 설문 평균 하나만 쓸 때 오차")
        c3.metric("규칙 안에 든 컨셉",f"{r['within_rule']}/{len(r['rows'])}",help=f"차이 {r['intent_gap_rule']:.0f}%p 이내")
        if r["mock"]:
            st.caption("모의 실행 결과입니다. 수치는 의미가 없습니다.")
        elif r["mae"] < r["baseline_mae"]:
            st.success("가상 응답이 평균 기준선보다 설문에 가깝습니다. 컨셉 간 순위 비교에 참고할 수 있습니다.")
        else:
            st.warning("가상 응답이 평균 기준선보다 낫지 않습니다. 컨셉 간 차이는 단정하지 말고 보정 계수와 실제 조사로 확인하세요.")
        st.dataframe(pd.DataFrame(r["rows"]),hide_index=True,width="stretch")
        st.caption(f"자료 버전 {r['data_version']} · 컨셉당 {r['n']}명 · {r['time']}")
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
