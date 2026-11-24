"""PreShelf Streamlit app. Start with `streamlit run app.py`."""
from copy import deepcopy
from hashlib import sha256
import json
import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from vm import datasets, project
from vm.config import OUT_DIR, PERSONA_PATH, result_files
from vm.llm import LLM
from vm.personas import load_pool
from vm.simulate import load_scenario
from vm.ui import (
    agent_design_page, cards, example_results, hero, introduction,
    limits_page, show_fgi, show_shelf,
)
from vm.workflow import BOARDS, evaluate, evidence, official_trend, save_report

PAGES = ["신제품 검토", "과거 자료 관리", "검토 이력", "에이전트 설계", "한계와 로드맵"]
BASE = load_scenario("config/scenario_example.json")
PRODUCT_ID = BASE["concept_id"]
DEFAULTS = dict(name="",desc="",price=1800,volume=250,channel="편의점",
                age=(19,59),occasion="간식과 함께 마실 음료를 고르는 중",n=50,price_b=0)
st.set_page_config(page_title="PreShelf · 음료 신제품 검토", page_icon="🥤", layout="wide")
load_dotenv()
try:
    for setting in ("OPENAI_API_KEY","VM_MODEL","VM_AGENT_MODEL","APP_PASSWORD"):
        if setting in st.secrets and not os.getenv(setting):
            os.environ[setting] = st.secrets[setting]
except FileNotFoundError:
    pass
APP_PASSWORD = os.getenv("APP_PASSWORD", "")


def can_run(mock):
    return mock or bool(st.session_state.get("user_key") or st.session_state.get("pw_ok")) or (
        not APP_PASSWORD and bool(os.getenv("OPENAI_API_KEY"))
    )


@st.cache_resource(show_spinner="Nemotron 후보 풀을 준비합니다.")
def pool():
    if not PERSONA_PATH.exists():
        from vm.personas import download_pool_light
        download_pool_light(int(os.getenv("VM_POOL_ROWS","10000")))
    return load_pool()


def scenario_for(cfg):
    scenario = deepcopy(BASE)
    product = next(item for item in scenario["products"] if item["id"] == PRODUCT_ID)
    product.update(name=cfg["name"],description=cfg["desc"],price=cfg["price"],volume_ml=cfg["volume"])
    if "competitors" in cfg:
        scenario["products"] = [product,*cfg["competitors"]]
    return scenario


def review_page(mock, api_key):
    st.header("새 음료 아이디어를 검토하세요")
    introduction()
    example_results()
    cards([
        ("쥬시모먼트","비가열 HPP 프리미엄 주스 · 300mL · 3,000원"),
        ("레쓰비 프리즈","얼려 먹는 슬러시형 커피 · 170mL · 1,800원"),
        ("밀키스 화채","수박화채맛 시즌 탄산 · 캔 250mL / PET 500mL"),
    ])
    template = st.selectbox("컨셉 시작점", ["직접 작성",*BOARDS,"제주 청귤 제로 스파클링 · 시연용"], key="review_template")
    pending = st.session_state.pop("history_config",None)
    generation = st.session_state.get("review_generation",0)
    if pending is not None:
        st.session_state["review_defaults"] = pending
        generation += 1
        st.session_state["review_generation"] = generation
    if template in BOARDS:
        desc,price,volume,channel = BOARDS[template]
        defaults = {**DEFAULTS,"name":template.split(" · ")[0],"desc":desc,"price":price,"volume":volume,"channel":channel}
    elif template.endswith(" · 시연용"):
        idea = next(p for p in BASE["products"] if p["id"]==PRODUCT_ID)
        defaults = {**DEFAULTS,"name":idea["name"],"desc":idea["description"],"price":idea["price"],
                    "volume":idea["volume_ml"],"occasion":BASE["situation"]}
    else:
        defaults = {**DEFAULTS,**st.session_state.get("review_defaults",{})}
    competitors = defaults.get("competitors",[p for p in BASE["products"] if p["id"]!=PRODUCT_ID])

    with st.form(f"concept_{generation}_{template}"):
        name = st.text_input("제품명",defaults["name"])
        description = st.text_area("컨셉 설명",defaults["desc"],placeholder="맛·제형·누가 언제 마시는지")
        left,right = st.columns(2)
        price = left.number_input("소비자가(원)",min_value=1,value=defaults["price"],step=100)
        volume = right.number_input("용량(mL)",min_value=1,value=defaults["volume"])
        channel = st.text_input("판매 채널",defaults["channel"])
        target = st.slider("타깃 연령(세)",19,99,tuple(defaults["age"]))
        st.caption("60세 이상은 Nemotron 생활 배경으로 탐색합니다. 평가 결과에 연령대별 데이터 근거를 표시합니다.")
        with st.expander("평가 설정 · 인원, 가격 비교, 구매 상황, 경쟁 제품"):
            size = st.radio("평가 규모",[50,150], index=1 if defaults["n"]==150 else 0,
                            format_func=lambda n:f"{'빠른 검토' if n==50 else '비교 검토'} · {n}명",horizontal=True)
            price_b = st.number_input("B안 가격(원) · 0이면 단일안 평가",min_value=0,value=defaults["price_b"],step=100)
            occasion = st.text_input("구매 상황",defaults["occasion"])
            competitor_table = pd.DataFrame([{"제품명":p["name"],"가격(원)":p["price"],"용량(mL)":p["volume_ml"],"설명":p["description"]}
                                             for p in competitors],columns=["제품명","가격(원)","용량(mL)","설명"])
            edited = st.data_editor(competitor_table,num_rows="dynamic",hide_index=True,column_config={
                "가격(원)":st.column_config.NumberColumn(min_value=1),
                "용량(mL)":st.column_config.NumberColumn(min_value=1)})
            trend_file = st.file_uploader("Google Trends 주간 CSV (선택)",type="csv",
                help="대한민국에서 검색어 하나를 최근 12개월로 조회한 주간 CSV")
        first,full = st.columns(2)
        check = first.form_submit_button("근거 먼저 보기",width="stretch")
        complete = full.form_submit_button("평가까지 한 번에",type="primary",width="stretch",disabled=not can_run(mock))
    if not can_run(mock):
        st.caption("평가하려면 사이드바에 API 키를 넣거나 API 없이 시험(mock)을 켜세요.")
    if check or complete:
        if not all(v.strip() for v in (name,description,channel,occasion)):
            st.error("제품명, 컨셉 설명, 판매 채널, 구매 상황을 입력해 주세요.")
            return
        edited_products = []
        for row in edited.to_dict("records"):
            if pd.notna(row["제품명"]) and str(row["제품명"]).strip() and pd.notna(row["가격(원)"]):
                edited_products.append(dict(id=f"C{len(edited_products)+1}",name=str(row["제품명"]).strip(),
                                            price=int(row["가격(원)"]),volume_ml=int(row["용량(mL)"]) if pd.notna(row["용량(mL)"]) else 500,
                                            description=str(row["설명"]) if pd.notna(row["설명"]) else ""))
        cfg = dict(name=name.strip(),desc=description.strip(),price=price,volume=volume,channel=channel.strip(),
                   age=target,n=size,price_b=price_b,occasion=occasion.strip(),competitors=edited_products)
        data = datasets.current()
        source,count = evidence(cfg["name"],cfg["desc"],data,cfg["channel"])
        if trend_file:
            try:
                source += "\n\n"+official_trend(trend_file.getvalue())
            except ValueError as exc:
                st.warning(f"실측 CSV를 적용하지 못했습니다. {exc}")
        st.session_state["workflow_review"] = dict(config=cfg,evidence=source,count=count,data=data,
                                                   scenario=scenario_for(cfg))
    review = st.session_state.get("workflow_review")
    if not review:
        return
    cfg = review["config"]
    st.subheader(f"{cfg['name']} 검토 · {cfg['price']:,}원 / {cfg['volume']}mL")
    st.caption(f"{cfg['age'][0]}~{cfg['age'][1]}세 · 요청 {cfg['n']}명 · 자료 {review['data']['version']}")
    if "report" not in review and not complete:
        with st.expander("유사 제품·판매·트렌드 근거",expanded=True):
            st.markdown(review["evidence"])
    start = st.button("이 근거로 평가 시작",type="primary",disabled=not can_run(mock)) if "report" not in review and not complete else False
    if start or complete:
        try:
            with st.spinner("정량 선택 평가와 5명 좌담회를 진행 중입니다."):
                visual = {}
                report,n_ok,share = evaluate(cfg,review["scenario"],review["evidence"],pool(),
                                             LLM(mock=mock,api_key=api_key),mock,review["data"],visual=visual)
            review.update(report=report,n_ok=n_ok,concept_share=share,mock=mock,saved=False,visual=visual)
        except Exception as exc:
            st.error(f"평가를 완료하지 못했습니다. {exc}")
    if "report" not in review:
        return
    details,_,feedback = review["report"].partition("## 종합 피드백")
    st.subheader("검토 결과와 다음 단계")
    if review["mock"]:
        st.caption("모의 실행 · 수치와 발언은 동작 확인용입니다.")
    st.metric("가상 진열대 신제품 선택",f"{review['concept_share']:.1f}%",help=f"유효 응답 {review['n_ok']}명")
    st.markdown(feedback.split("## 검토 판단",1)[0].strip())
    visual = review.get("visual",{})
    with st.expander("평가에 사용한 유사 제품·판매·트렌드 근거"):
        st.markdown(review["evidence"])
    before_fgi,_,fgi_text = details.partition("## 정성 평가")
    quantitative = before_fgi.split("## 평가 패널",1)[-1]
    with st.expander("진열대 시뮬레이션 · 선택 분포와 비교 제품"):
        show_shelf(visual)
        st.markdown("## 평가 패널"+quantitative)
    with st.expander("가상 FGI · 요약과 라운드별 발언"):
        fgi_summary,_,reference = fgi_text.partition("## 평가 후 비교")
        st.markdown(fgi_summary.strip())
        show_fgi(visual.get("fgi"))
    if reference:
        with st.expander("제공 설문과 비교"):
            st.markdown(reference.strip())
    if not review["saved"]:
        projects = {item["id"]:item["name"] for item in project.list_projects()}
        with st.form("review_decision"):
            decision = st.selectbox("다음 단계",["수정 후 재검토","실제 조사로 진행","보류"])
            reason = st.text_area("판단 이유")
            project_id = st.selectbox("연결할 프로젝트 (선택)",[None,*projects],
                                      format_func=lambda key:projects.get(key,"단독 보고서"))
            save = st.form_submit_button("판단과 보고서 저장")
        if save and not reason.strip():
            st.warning("판단 이유를 입력해 주세요.")
        elif save:
            path = save_report(review["report"],decision,reason.strip(),cfg,visual=visual)
            review.update(saved=True,report=path.read_text(encoding="utf8"))
            if project_id:
                selected = project.load(project_id)
                project.log_run(selected,cfg,"본선 통합 검토",
                                {"검토 판단":decision,"사유":reason.strip(),"mock":review["mock"],
                                 "신제품 구매 비율(%)":review["concept_share"],"정량 응답":review["n_ok"]},str(path.parent))
            st.rerun()
    if review["saved"]:
        st.success("검토 이력에 저장했습니다.")
    st.download_button("검토 보고서 다운로드",review["report"],file_name="컨셉_검토보고서.md")


def reload_review(cfg):
    st.session_state.pop("workflow_review",None)
    st.session_state["history_config"] = cfg
    st.session_state["review_template"] = "직접 작성"
    st.session_state["navigation"] = PAGES[0]


def history_page():
    st.header("검토 이력")
    reports = sorted(OUT_DIR.glob("challenge_*/report.md"),key=lambda p:p.stat().st_mtime,reverse=True)
    if not reports:
        st.info("저장한 검토 보고서가 여기에 표시됩니다.")
    else:
        names, text = {}, {}
        for path in reports:
            text[path] = path.read_text(encoding="utf8")
            names[path] = text[path].splitlines()[0].lstrip("# ").removesuffix(" 검토 보고서")
        selected = st.selectbox("보고서",reports,format_func=lambda p:names[p])
        st.markdown(text[selected])
        st.download_button("선택한 보고서 다운로드",text[selected],file_name="컨셉_검토보고서.md")
        evaluation = selected.with_name("evaluation.json")
        if evaluation.is_file():
            visual = json.loads(evaluation.read_text(encoding="utf8"))
            with st.expander("저장한 진열대 시뮬레이션과 가상 FGI"):
                show_shelf(visual)
                show_fgi(visual.get("fgi"))
        meta = selected.with_name("config.json")
        if meta.is_file():
            cfg = json.loads(meta.read_text(encoding="utf8"))["config"]
            st.button("이 컨셉으로 다시 검토",on_click=reload_review,args=(cfg,))
    older_fgi = result_files("fgi_*/fgi.json")[::-1]
    if older_fgi:
        from pathlib import Path
        with st.expander("이전에 저장한 좌담회"):
            selected_fgi = st.selectbox("좌담회 기록",older_fgi,format_func=lambda f:Path(f).parent.name)
            saved_fgi = json.loads(Path(selected_fgi).read_text(encoding="utf8"))
            st.markdown(f"**{saved_fgi.get('concept','가상 좌담회')}**")
            show_fgi(saved_fgi)
    with st.expander("프로젝트 기록"):
        with st.form("new_project"):
            name = st.text_input("새 프로젝트 이름")
            create = st.form_submit_button("프로젝트 만들기")
        if create and name.strip():
            project.create(name.strip())
        options = {p["id"]:p["name"] for p in project.list_projects()}
        if options:
            pid = st.selectbox("프로젝트",options,format_func=options.get)
            record = project.load(pid)
            st.markdown(project.export_markdown(record))
            cards = {v["id"]:v["card"] for v in record["versions"]}
            if cards:
                version = st.selectbox("컨셉 버전",cards)
                st.button("프로젝트 컨셉 다시 검토",on_click=reload_review,args=(cards[version],))


def archive_page(mock, api_key):
    from vm import datasets
    from vm import archive_records as intake
    st.header("표준 데이터 등록")
    with st.expander("표준 엑셀 3종 등록"):
        files = {k:st.file_uploader(f"{k} {label}",type="xlsx",key=f"standard_{k}") for k,label in {
            "3-1":"POS·제품자산","3-2":"소비자 조사","3-3":"구매여정·트렌드"}.items()}
        if st.button("표준 데이터 검증 및 등록",disabled=not all(files.values())):
            try:
                data = datasets.register({k:(f.name,f.getvalue()) for k,f in files.items()})
                st.success(f"표준 데이터 등록 완료 · {data['version']}")
            except Exception as exc:
                st.error(f"표준 데이터 등록 실패 · {exc}")
    active_standard = datasets.current()
    st.caption(f"현재 적용 중 · {active_standard['version']}")
    st.header("과거 자료 정리")
    upload = st.file_uploader("자료 파일 · CSV, XLSX, TXT, MD", type=["csv","xlsx","txt","md"], key="legacy_file")
    st.caption("표는 시트별 행, 텍스트는 빈 줄로 나눈 문단 단위입니다. AI 분류 시 선택한 원문을 모델에 전송합니다.")
    if upload:
        try:
            raw_upload = upload.getvalue()
            upload_digest = sha256(raw_upload).hexdigest()
            items = intake.extract(upload.name, raw_upload)
            if items:
                start = st.number_input("시작 항목 번호",1,len(items),1,key="intake_start_"+items[0]["id"])
                batch = items[start-1:start+9]
                key = "_".join((batch[0]["id"], upload_digest, str(mock), active_standard["version"]))
                if st.button(f"{len(batch)}개 분류 초안 만들기", disabled=not can_run(mock)):
                    engine = LLM(mock=mock, api_key=api_key)
                    st.session_state["legacy_editor_version"] = st.session_state.get("legacy_editor_version",0)+1
                    st.session_state["legacy_draft"] = (key,[intake.classify(i,engine,active_standard["assets"]) for i in batch])
                draft = st.session_state.get("legacy_draft")
                if draft and draft[0] == key:
                    table = [{"위치":i["location"],"원문":i["original"],**d} for i,d in zip(batch,draft[1])]
                    columns = {field:st.column_config.SelectboxColumn(options=options)
                               for field,options in intake.choices(active_standard["assets"]).items()}
                    reviewed = st.data_editor(pd.DataFrame(table),disabled=["위치","원문"],column_config=columns,
                                              key=f"review_{key}_{st.session_state['legacy_editor_version']}",hide_index=True)
                    if st.button("검토한 항목 저장"):
                        intake.save(batch,reviewed.fillna("").to_dict("records"))
                        st.success(f"{len(batch)}개 항목을 저장했습니다.")
                        st.session_state.pop("legacy_draft",None)
            else:
                st.info("읽을 수 있는 항목이 없습니다.")
        except Exception as exc:
            st.error(f"자료를 정리하지 못했습니다. {exc}")
    saved = intake.records()
    if saved:
        search = st.text_input("저장 자료 검색 · 제품명, 원문, 파일명")
        found = [r for r in saved if search.casefold() in " ".join(str(v) for v in r.values()).casefold()]
        st.dataframe(pd.DataFrame(found).drop(columns=["id","fields"],errors="ignore"),hide_index=True)
        if found:
            by_id = {r["id"]:r for r in found}
            item_id = st.selectbox("버전 이력 보기", [None,*by_id], format_func=lambda k:
                "항목 선택" if k is None else f"{by_id[k].get('제품','자료 없음')} · {by_id[k]['location']}")
            if item_id:
                versions = intake.history(item_id)
                st.dataframe(pd.DataFrame(versions).drop(columns=["id","fields"],errors="ignore"),hide_index=True)

with st.sidebar:
    st.header("실행 설정")
    mock = st.toggle("API 없이 시험(mock)", value=not bool(os.getenv("OPENAI_API_KEY")),
                     help="모의 응답으로 화면과 흐름을 확인합니다.")
    api_key = st.text_input("OpenAI API 키 (선택)",type="password",key="user_key") or None
    if APP_PASSWORD and not mock and not api_key:
        password = st.text_input("실행 비밀번호",type="password")
        st.session_state["pw_ok"] = bool(password) and password == APP_PASSWORD
    else:
        st.session_state["pw_ok"] = False

hero()
page = st.radio("이동",PAGES,key="navigation",horizontal=True,label_visibility="collapsed")
st.divider()
if page == PAGES[0]:
    review_page(mock,api_key)
elif page == PAGES[1]:
    archive_page(mock,api_key)
elif page == PAGES[2]:
    history_page()
elif page == PAGES[3]:
    agent_design_page()
else:
    limits_page()
