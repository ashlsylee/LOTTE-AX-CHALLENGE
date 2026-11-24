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
    limits_page, reliability_page, show_fgi, show_shelf, show_validation,
)
from vm.workflow import BOARDS, INTENT_GAP, evaluate, evidence, official_trend, save_report, validate_concepts

PAGES = ["신제품 검토", "AI 에이전트", "신뢰도 검증", "과거 자료 관리", "검토 이력", "한계와 로드맵"]
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
    if not BOARDS:
        st.caption("컨셉보드 예시는 로컬 `data/challenge/boards.json`에 두면 아래 '컨셉 시작점'에 나타납니다(저장소에는 올리지 않음).")
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
            with_fgi = st.checkbox("가상 좌담회 5명 포함 (API 호출 약 16회 추가)",value=bool(defaults.get("fgi",False)))
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
                   age=target,n=size,price_b=price_b,occasion=occasion.strip(),competitors=edited_products,
                   fgi=with_fgi)
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
            with st.spinner("가상 진열대 평가"+(" · 5명 좌담회" if cfg.get("fgi") else "")+"를 진행 중입니다."):
                visual = {}
                report,n_ok,share = evaluate(cfg,review["scenario"],review["evidence"],pool(),
                                             LLM(mock=mock,api_key=api_key),mock,review["data"],visual=visual)
            review.update(report=report,n_ok=n_ok,concept_share=share,mock=mock,saved=False,visual=visual)
        except Exception as exc:
            st.error(f"평가를 완료하지 못했습니다. {exc}")
    if "report" not in review:
        return
    visual = review.get("visual",{})
    sections = visual.get("sections",{})
    st.subheader("검토 결과와 다음 단계")
    if review["mock"]:
        st.caption("모의 실행 · 수치와 발언은 동작 확인용입니다.")
    left,right = st.columns(2)
    left.metric("가상 진열대 신제품 선택",f"{review['concept_share']:.1f}%",help=f"유효 응답 {review['n_ok']}명")
    check = visual.get("validation")
    if check:
        right.metric("설문 구매의향과 차이",f"{check['차이(%p)']:+.1f}%p",help=f"규칙: {INTENT_GAP:.0f}%p 이내면 비슷함 · {check['기준 설문']}")
    else:
        right.metric("설문 구매의향과 차이","비교 자료 없음",help="이 컨셉 이름의 제공 설문이 없으면 비교하지 않습니다.")
    st.markdown(sections.get("feedback","").replace("## 종합 피드백","").strip())
    if check:
        show_validation(check)
    with st.expander("평가에 사용한 유사 제품·판매·트렌드 근거"):
        st.markdown(review["evidence"])
    with st.expander("진열대 시뮬레이션 · 선택 분포와 비교 제품"):
        show_shelf(visual)
        for key in ("panel","quant","ab"):
            if sections.get(key):
                st.markdown(sections[key])
    if visual.get("fgi"):
        with st.expander("가상 FGI · 요약과 라운드별 발언"):
            st.markdown(sections.get("fgi",""))
            show_fgi(visual.get("fgi"))
    if sections.get("footer"):
        st.caption(sections["footer"])
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


def review_footer():
    st.divider()
    example_results()


def agent_page(mock, api_key):
    from vm.orchestrator import run_agent
    st.header("AI 에이전트 검토")
    st.write("요청을 문장으로 쓰면 에이전트가 필요한 도구를 골라 계획·실행하고 근거가 붙은 리포트를 씁니다.")
    review = st.session_state.get("workflow_review")
    cfg = review["config"] if review else None
    scenario = review["scenario"] if review else BASE
    concept = next(p for p in scenario["products"] if p["id"]==scenario["concept_id"])
    st.info(f"검증 대상: **{concept['name']}** · {concept['price']:,}원 · {concept['volume_ml']}mL"
            + ("" if review else " (시연용 기본 컨셉 · '신제품 검토'에서 근거를 조회하면 그 컨셉으로 바뀝니다)"))
    default_request = (f"{cfg['age'][0]}~{cfg['age'][1]}세 대상 '{cfg['name']}' {cfg['price']:,}원이 적당한지, "
                       "우리 기존 제품을 잠식하지 않는지 검토해줘") if cfg else \
        f"20~39세 대상 '{concept['name']}' {concept['price']:,}원이 적당한지 검토해줘"
    with st.form("agent_form"):
        request = st.text_area("요청",default_request,height=90)
        left,right = st.columns(2)
        budget = left.number_input("페르소나 호출 예산(회)",50,600,200,step=50,
                                   help="새 API 응답 수 상한. 캐시로 재사용된 응답은 세지 않습니다.")
        steps = right.number_input("최대 단계",3,12,8)
        go = st.form_submit_button("에이전트 실행",type="primary",disabled=not can_run(mock))
    if not can_run(mock):
        st.caption("실행하려면 사이드바에 API 키를 넣거나 API 없이 시험(mock)을 켜세요.")
    labels = {"check_reliability":"신뢰도 확인","lookup_evidence":"유사 제품·판매·트렌드 근거 조회",
              "run_shelf_simulation":"진열대 시뮬레이션","compare_prices":"가격 비교","compare_concepts":"컨셉 문구 비교",
              "get_reasons":"구매·외면 이유 확인","run_fgi":"가상 좌담회","suggest_improvements":"개선안 제안",
              "check_cannibalization":"자사 잠식 확인","write_report":"리포트 작성"}
    if go:
        box = st.status("에이전트 실행 중",expanded=True)
        def on_step(step,name,args,result):
            box.write(f"**{step} · {labels.get(name,name)}** "+(json.dumps(args,ensure_ascii=False) if args else ""))
        try:
            res = run_agent(request,scenario,budget=int(budget),max_steps=int(steps),mock=mock,on_step=on_step,
                            api_key=api_key,min_diff=3.0,data=datasets.current(),pool=pool(),
                            channel=cfg["channel"] if cfg else "")
            box.update(label=f"완료 · 새 응답 {res['api_calls']}회 / 예산 {res['budget']}",state="complete",expanded=False)
            st.session_state["agent_result"] = res
        except Exception as exc:
            box.update(label="실패",state="error")
            st.error(f"{type(exc).__name__}: {exc}")
    res = st.session_state.get("agent_result")
    if res:
        st.markdown(res["report"] or "(리포트 없음)")
        with st.expander("실행 기록(도구 호출 순서와 결과)"):
            st.table(pd.DataFrame([{"단계":t["step"],"도구":labels.get(t["tool"],t["tool"]),
                                    "입력":json.dumps(t["args"],ensure_ascii=False)[:120]} for t in res["trace"]]))
            st.json(res["trace"],expanded=False)
        st.download_button("리포트 다운로드",res["report"] or "",file_name="에이전트_리포트.md")
    with st.expander("에이전트 설계 · 도구와 안전장치"):
        agent_design_page()


def validation_page(mock, api_key):
    data = datasets.current()
    reliability_page(data)
    st.subheader("제공 설문과 컨셉별 대조 실행")
    st.caption(f"검증용 응답자 {data.get('split',{}).get('holdout','-')}명 · 패널에 붙인 응답자 "
               f"{data.get('split',{}).get('panel','-')}명 (응답자 ID 해시로 고정 분할, 서로 겹치지 않음)")
    n = st.radio("컨셉당 가상 인원",[30,50],horizontal=True,
                 help="컨셉 수 × 인원만큼 API를 호출합니다. 같은 조건을 다시 돌리면 캐시를 씁니다.")
    if st.button("컨셉별 대조 실행",disabled=not (can_run(mock) and data.get("references"))):
        try:
            with st.spinner("컨셉마다 같은 패널로 '사 볼 의향'을 묻는 중입니다."):
                validate_concepts(pool(),LLM(mock=mock,api_key=api_key),BASE,data,n=n)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    if not data.get("references"):
        st.caption("설문 구매의향 자료가 없어 실행할 수 없습니다. '과거 자료 관리'에서 표준 엑셀 3종을 등록하세요.")


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
                st.success(f"표준 데이터 등록 완료 · {data['version']} · 제외한 행 {len(data['issues'])}개")
            except Exception as exc:
                st.error(f"표준 데이터 등록 실패 · {exc}")
    active_standard = datasets.current()
    st.caption(f"현재 적용 중 · {active_standard['version']}")
    if active_standard.get("issues"):
        with st.expander(f"등록에서 제외한 행 {len(active_standard['issues'])}개 · 사유 확인"):
            st.caption("형식이 다른 행은 등록을 멈추지 않고 빼 두었습니다. 원본을 고친 뒤 다시 등록하면 반영됩니다.")
            issues = pd.DataFrame(active_standard["issues"])
            st.dataframe(issues.groupby(["시트","사유"]).size().rename("행 수").reset_index(),hide_index=True)
            st.dataframe(issues,hide_index=True)
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
if st.session_state.get("navigation") not in PAGES:
    st.session_state["navigation"] = PAGES[0]
page = st.segmented_control("이동",PAGES,key="navigation",label_visibility="collapsed") or PAGES[0]
if page == "신제품 검토":
    review_page(mock,api_key)
    review_footer()
elif page == "AI 에이전트":
    agent_page(mock,api_key)
elif page == "신뢰도 검증":
    validation_page(mock,api_key)
elif page == "과거 자료 관리":
    archive_page(mock,api_key)
elif page == "검토 이력":
    history_page()
else:
    limits_page()
