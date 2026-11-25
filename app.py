"""PreShelf Streamlit app. Start with `streamlit run app.py`."""
from copy import deepcopy
from hashlib import sha256
import json
import re
import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from vm import datasets, project
from vm.config import DEMO_DIR, OUT_DIR, PERSONA_PATH, result_files
from vm.llm import LLM
from vm.personas import load_pool
from vm.simulate import load_scenario
from vm.ui import (
    agent_design_page, cards, case_cards, example_results, flowbar, hero, introduction, limits_page, persona_panel,
    products_chart, reliability_page, result_view, show_fgi, show_shelf, show_validation, verdict_banner,
)
from vm.workflow import BOARDS, INTENT_GAP, analyze, evaluate, evidence, official_trend, save_report, validate_concepts

PAGES = ["① 자료 준비", "② 신제품 검토 · AI 페르소나", "③ 신뢰도 검증", "검토 이력", "한계와 로드맵"]
BASE = load_scenario("config/scenario_example.json")
PRODUCT_ID = BASE["concept_id"]
DEFAULTS = dict(name="",desc="",price=1800,volume=250,channel="편의점",
                age=(19,59),occasion="간식과 함께 마실 음료를 고르는 중",n=50,price_b=0,launch="",storage="상온")
st.set_page_config(page_title="PreShelf · 음료 신제품 검토", page_icon="🥤", layout="wide")
from vm.config import ENV_INFO, load_env  # noqa: E402
load_env()
try:
    for setting in ("OPENAI_API_KEY","VM_MODEL","VM_AGENT_MODEL","APP_PASSWORD"):
        if setting in st.secrets and not os.getenv(setting):
            os.environ[setting] = st.secrets[setting]
except FileNotFoundError:
    pass
APP_PASSWORD = os.getenv("APP_PASSWORD", "")


def can_run(mock):
    return mock or bool(st.session_state.get("user_key") or st.session_state.get("pw_ok")) or (
        not APP_PASSWORD and bool(os.getenv("OPENAI_API_KEY") or os.getenv("GATEWAY_KEY"))
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
    from vm import store as _store
    _summ = _store.summary() if _store.datasets() else []
    if _summ:
        st.caption(f"분석 묶음: {', '.join(_store.analysis_datasets())} · 자료 {len(_summ)}종 (바꾸려면 왼쪽 사이드바)")
    else:
        st.warning("등록된 자료가 없어 과거 사례·트렌드·설문 비교가 비어 나옵니다. '① 자료 준비' 탭에서 자료를 넣거나 묶음을 고르세요.")
    if st.session_state.pop("reload_notice",False):
        st.success("검토 이력의 컨셉을 불러왔습니다. 아래 입력란을 확인하세요.")
    show_persona_panel()
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
        desc,price,volume,channel,*extra = BOARDS[template]
        defaults = {**DEFAULTS,"name":template.split(" · ")[0],"desc":desc,"price":price,"volume":volume,"channel":channel,
                    "launch":extra[0] if extra else "","storage":extra[1] if len(extra) > 1 else "상온",
                    "cost_price":extra[2] if len(extra) > 2 else 0}
    elif template.endswith(" · 시연용"):
        idea = next(p for p in BASE["products"] if p["id"]==PRODUCT_ID)
        defaults = {**DEFAULTS,"name":idea["name"],"desc":idea["description"],"price":idea["price"],
                    "volume":idea["volume_ml"],"occasion":BASE["situation"]}
    else:
        defaults = {**DEFAULTS,**st.session_state.get("review_defaults",{})}
    competitors = defaults.get("competitors",[p for p in BASE["products"] if p["id"]!=PRODUCT_ID])
    from vm import insight
    if st.button("판매 자료에서 같은 카테고리 비교 제품 불러오기",help="POS의 같은 카테고리 자사·경쟁 제품과 행사 없는 실제 평균 단가"):
        found = insight.competitors(defaults["name"] or template, defaults["desc"])
        if found:
            st.session_state["comp_override"] = {"key":template,"rows":found}
            st.session_state["review_generation"] = generation = generation + 1
        else:
            st.info("등록된 판매 자료에서 비슷한 카테고리 제품을 찾지 못했습니다.")
    override = st.session_state.get("comp_override")
    if override and override["key"] == template:
        competitors = override["rows"]

    with st.form(f"concept_{generation}_{template}"):
        name = st.text_input("제품명",defaults["name"])
        description = st.text_area("컨셉 설명",defaults["desc"],placeholder="맛·제형·누가 언제 마시는지")
        left,right = st.columns(2)
        price = left.number_input("소비자가(원)",min_value=1,value=defaults["price"],step=100)
        volume = right.number_input("용량(mL)",min_value=1,value=defaults["volume"])
        cost_price = left.number_input("출고가(원, 선택 · 마진 계산용)",min_value=0,value=int(defaults.get("cost_price",0) or 0),step=10)
        from vm import insight as _ins
        ch_opts = _ins.channel_options()
        ch_default = [c.strip() for c in re.split(r"[,/]", str(defaults["channel"])) if c.strip()]
        if not defaults.get("name") or not ch_default or ch_default == ["편의점"]:
            ch_default = _ins.suggest_channels(defaults.get("name") or template, defaults.get("desc",""), defaults.get("storage",""))["channels"]
        ch_opts = list(dict.fromkeys(ch_default + ch_opts))
        try:
            channels = st.multiselect("판매 채널 · 비슷한 제품 판매 자료로 미리 채움, 검색해서 추가·직접 입력 가능",ch_opts,default=ch_default,
                                      accept_new_options=True,placeholder="채널 검색 또는 입력")
        except TypeError:  # 오래된 Streamlit: 직접 입력 없이 선택만
            channels = st.multiselect("판매 채널 · 비슷한 제품 판매 자료로 미리 채움, 검색해서 추가",ch_opts,default=ch_default)
        channel = ", ".join(channels)
        c1,c2 = st.columns(2)
        launch = c1.text_input("출시 예정(YYYY-MM)",defaults.get("launch",""),help="트렌드 최고 시기와 비교해 타이밍을 봅니다")
        storage = c2.radio("보관 조건",["상온","냉장","냉동"],index=["상온","냉장","냉동"].index(defaults.get("storage","상온")),horizontal=True,
                           help="냉장·냉동이면 채널별 취급 가능 점포와 환산계수에 반영")
        target = st.slider("타깃 연령(세)",19,99,tuple(defaults["age"]))
        st.caption("60세 이상은 Nemotron 생활 배경으로 탐색합니다. 평가 결과에 연령대별 데이터 근거를 표시합니다.")
        with st.expander("평가 설정 · 인원, 가격 비교, 구매 상황, 경쟁 제품"):
            size = st.radio("평가 규모",[50,150], index=1 if defaults["n"]==150 else 0,
                            format_func=lambda n:f"{'빠른 검토' if n==50 else '비교 검토'} · {n}명",horizontal=True)
            price_b = st.number_input("B안 가격(원) · 0이면 단일안 평가",min_value=0,value=defaults["price_b"],step=100)
            with_survey = st.checkbox("가상 소비자 설문(신제품+비교 제품, 실제 설문과 같은 문항) · 인원만큼 호출",value=bool(defaults.get("survey",True)))
            with_fgi = st.checkbox("가상 좌담회 5명 포함 (API 호출 약 16회 추가)",value=bool(defaults.get("fgi",False)))
            occasion = st.text_input("구매 상황",defaults["occasion"])
            st.caption("비교 제품(경쟁·자사) — 진열대와 가상 설문에 같이 쓰입니다. 위 버튼으로 판매 자료에서 불러오거나 직접 고치세요.")
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
        if not all(v.strip() for v in (name,description,occasion)):
            st.error("제품명, 컨셉 설명, 구매 상황을 입력해 주세요.")
            return
        if not channel.strip():  # 비워 두면 판매 자료로 추천
            sug_ch = _ins.suggest_channels(name,description,storage if storage != "상온" else "")
            channel = ", ".join(sug_ch["channels"])
            st.info(f"판매 채널을 비워 두어 추천값을 썼습니다: {channel} ({sug_ch['why']})")
        edited_products = []
        for row in edited.to_dict("records"):
            if pd.notna(row["제품명"]) and str(row["제품명"]).strip() and pd.notna(row["가격(원)"]):
                edited_products.append(dict(id=f"C{len(edited_products)+1}",name=str(row["제품명"]).strip(),
                                            price=int(row["가격(원)"]),volume_ml=int(row["용량(mL)"]) if pd.notna(row["용량(mL)"]) else 500,
                                            description=str(row["설명"]) if pd.notna(row["설명"]) else ""))
        cfg = dict(name=name.strip(),desc=description.strip(),price=price,volume=volume,channel=channel.strip(),
                   age=target,n=size,price_b=price_b,occasion=occasion.strip(),competitors=edited_products,
                   fgi=with_fgi,survey=with_survey,launch=launch.strip() or None,storage=storage if storage != "상온" else "",
                   cost_price=int(cost_price) or None)
        data = datasets.current()
        analysis = analyze(cfg["name"],cfg["desc"],cfg["launch"],cfg["storage"],cfg["channel"])
        cfg["concerns"] = analysis["verdict"].get("가상 소비자로 확인할 질문",[])
        source,count = evidence(cfg["name"],cfg["desc"],data,cfg["channel"],analysis=analysis)
        if trend_file:
            try:
                source += "\n\n"+official_trend(trend_file.getvalue())
            except ValueError as exc:
                st.warning(f"실측 CSV를 적용하지 못했습니다. {exc}")
        st.session_state["workflow_review"] = dict(config=cfg,evidence=source,count=count,data=data,
                                                   scenario=scenario_for(cfg),analysis=analysis)
    review = st.session_state.get("workflow_review")
    if not review:
        return
    cfg = review["config"]
    st.subheader(f"{cfg['name']} 검토 · {cfg['price']:,}원 / {cfg['volume']}mL")
    est = cfg["n"] * (1 + bool(cfg.get("survey",True)) + bool(cfg.get("price_b"))) + (16 if cfg.get("fgi") else 0) + 1
    unit = float(os.getenv("VM_COST_PER_CALL","0.02"))
    st.caption(f"{cfg['age'][0]}~{cfg['age'][1]}세 · 요청 {cfg['n']}명 · 자료 {review['data']['version']} · "
               f"평가 예상 호출 약 {est}건 ≈ ${est*unit:.1f} (같은 조건 재실행은 저장된 응답 재사용)")
    if "report" not in review and not complete:
        flowbar(3)
        v = review["analysis"]["verdict"]
        verdict_banner(v["판단"], " / ".join(v.get("이유", [])[:3]))
        st.markdown("**비슷한 과거 사례**")
        case_cards(review["analysis"]["history"])
        with st.expander("근거 전체 · 트렌드 타이밍·유통 조건·데이터 경고"):
            st.markdown(review["evidence"])
    start = st.button("이 근거로 평가 시작",type="primary",disabled=not can_run(mock)) if "report" not in review and not complete else False
    if start or complete:
        try:
            with st.spinner("가상 진열대"+(" · 가상 설문" if cfg.get("survey",True) else "")+(" · 5명 좌담회" if cfg.get("fgi") else "")+"를 진행 중입니다."):
                visual = {}
                report,n_ok,share = evaluate(cfg,review["scenario"],review["evidence"],pool(),
                                             LLM(mock=mock,api_key=api_key),mock,review["data"],visual=visual)
            review.update(report=report,n_ok=n_ok,concept_share=share,mock=mock,saved=False,visual=visual)
            st.rerun()  # 평가 전 근거 카드를 접고 결과 화면만 보이게
        except Exception as exc:
            st.error(f"평가를 완료하지 못했습니다. {exc}")
    if "report" not in review:
        return
    visual = review.get("visual",{})
    sections = visual.get("sections",{})
    st.subheader("검토 결과와 다음 단계")
    if review.get("analysis"):
        visual["analysis_verdict"] = review["analysis"]["verdict"]["판단"]
        visual["history"] = [{k: h.get(k) for k in ("제품","상태","중단 사유","사유 유형")} for h in review["analysis"]["history"]]
    if visual.get("kpi"):
        result_view(visual, sections, review.get("analysis"), review["mock"], cfg=cfg)
    else:
        st.markdown(sections.get("feedback","").replace("## 종합 피드백","").strip())
    check = visual.get("validation")
    st.markdown("**자세히 보기**")
    with st.expander("과거 사례·트렌드 타이밍·데이터 경고"):
        st.markdown(review["evidence"])
    if sections.get("survey"):
        with st.expander("가상 소비자 설문 · 비교 제품·실제 설문 대조·우려 점검",expanded=True):
            st.markdown(sections["survey"])
    if sections.get("price"):
        with st.expander("가격·마진 점검"):
            st.markdown(sections["price"])
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
    from datetime import datetime as _dt
    fname = st.text_input("내려받을 파일 이름 (입력 후 Enter)",f"{cfg['name']}_{cfg['n']}명_{_dt.now():%m%d_%H%M}_검토보고서",key="dl_name")
    st.download_button("검토 보고서 다운로드",review["report"],file_name=(fname.strip() or "검토보고서").removesuffix(".md")+".md")


@st.cache_data(show_spinner=False)
def _persona_examples(version):
    """예시 페르소나 3명(연령대가 겹치지 않게). API 호출 없음."""
    from vm.workflow import panel_sample
    data = datasets.current()
    panel,_,donors = panel_sample(pool(),30,19,59,data=data)
    picked, seen = [], set()
    for _,r in panel.iterrows():
        band = str(r["age"])[:1]
        if band in seen or (picked and r["sex"] == picked[-1]["sex"]):
            continue  # 연령대·성별이 겹치지 않게
        seen.add(band)
        text = str(r.get("culinary_persona",""))
        behavior = text.split("결합한 음료 구매 행동",1)[1].split(":",1)[-1].strip() if "결합한 음료 구매 행동" in text else ""
        picked.append({"age":r["age"],"sex":r["sex"],"province":r.get("province",""),"occupation":r.get("occupation",""),
                       "persona":str(r.get("persona",""))[:140],"behavior":behavior[:120]})
        if len(picked)==3:
            break
    return picked, len(pool()), int(data.get("split",{}).get("panel") or donors)


def show_persona_panel():
    try:
        samples,pool_size,donors = _persona_examples(datasets.current().get("version",""))
    except Exception as exc:  # 페르소나 파일·자료가 없어도 화면은 열리게
        samples,pool_size,donors = [],0,0
        st.caption(f"예시 페르소나를 불러오지 못했습니다: {exc}")
    persona_panel(samples,pool_size,donors,150)


def review_footer():
    st.divider()
    example_results()


def validation_page(mock, api_key):
    data = datasets.current()
    reliability_page(data)
    st.subheader("제공 설문과 컨셉별 대조 실행")
    st.caption(f"검증용 응답자 {data.get('split',{}).get('holdout','-')}명 · 패널에 붙인 응답자 "
               f"{data.get('split',{}).get('panel','-')}명 (응답자 ID 해시로 고정 분할, 서로 겹치지 않음)")
    c1,c2 = st.columns(2)
    n = c1.radio("컨셉당 가상 인원",[30,50],horizontal=True,
                 help="컨셉 수 × 인원만큼 API를 호출합니다. 같은 조건을 다시 돌리면 캐시를 씁니다.")
    projects = {item["id"]:item["name"] for item in project.list_projects()}
    proj = c2.selectbox("결과 이름에 붙일 프로젝트 (선택)",[None,*projects],format_func=lambda k:projects.get(k,"전체 컨셉"))
    if st.button("컨셉별 대조 실행",disabled=not (can_run(mock) and data.get("references"))):
        try:
            with st.spinner("컨셉마다 같은 패널로 '사 볼 의향'을 묻는 중입니다."):
                validate_concepts(pool(),LLM(mock=mock,api_key=api_key),BASE,data,n=n,project=projects.get(proj))
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    if not data.get("references"):
        st.caption("설문 구매의향 자료가 없어 실행할 수 없습니다. '① 자료 준비'에서 소비자 조사 자료를 등록하세요.")
    st.subheader("실제 조사 연결 · 가상 → 실제 설문 → 비교·보정")
    st.markdown("1. 가상 소비자에게 물은 것과 **같은 문항**의 설문지 양식을 내려받아 실제 조사(정량 패널 등)에 씁니다.\n"
                "2. 조사 결과 파일을 '① 자료 준비'에 **새 묶음**(예: '2027-03 쥬시 실조사')으로 올리면 열 이름으로 자동 인식됩니다.\n"
                "3. 분석 묶음에 그 묶음을 함께 고르고 같은 컨셉을 다시 평가하면, 결과의 **'실제 설문과 같은 항목 비교'** 표에 가상·실제가 나란히 나오고 "
                "차이와 보정 계수가 계산됩니다(가상 응답은 저장된 것을 재사용해 비용 거의 없음).")
    tmpl = pd.DataFrame([{"응답자ID":"R001","성별":"여성","연령대":"19~29세","컨셉":"(컨셉 이름)","컨셉이해도":"","호감도":"","차별성":"",
                          "구매의향":"","가격수용도":"","최대지불의향가격":"","예상월구매횟수":"","제시가격":"","제시순서":"","자유응답":""}])
    st.download_button("같은 문항 설문 결과 양식(CSV) 내려받기",tmpl.to_csv(index=False).encode("utf-8-sig"),
                       file_name="실제조사_결과양식.csv",mime="text/csv")
    st.caption("문항: 이해도·호감도·차별성·구매의향·가격수용도는 1~5점, 지불의향가격(원), 예상 월 구매 횟수. 모든 컨셉을 같은 문장·같은 가격 표시로 물어야 비교가 공정합니다.")


def reload_review(cfg):
    st.session_state.pop("workflow_review",None)
    st.session_state["history_config"] = cfg
    st.session_state["review_template"] = "직접 작성"
    st.session_state["reload_notice"] = True
    st.session_state["nav"] = PAGES[1]


def manage(selected, meta, report_text):
    """저장 결과 이름 바꾸기 · 프로젝트에 연결 · 지우기(휴지통)."""
    import shutil
    folder = selected.parent
    c1,c2,c3 = st.columns(3)
    with c1.popover("이름 바꾸기"):
        new = st.text_input("표시 이름",meta.get("title") or report_text.splitlines()[0].lstrip("# ").removesuffix(" 검토 보고서"),key=f"t_{folder.name}")
        if st.button("저장",key=f"ts_{folder.name}"):
            meta["title"] = new.strip()
            (folder / "config.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf8")
            st.rerun()
    with c2.popover("프로젝트에 연결"):
        projects = {item["id"]:item["name"] for item in project.list_projects()}
        if not projects:
            st.caption("아래 '프로젝트 기록'에서 먼저 프로젝트를 만드세요.")
        else:
            pid = st.selectbox("프로젝트",list(projects),format_func=projects.get,key=f"p_{folder.name}")
            already = any(r.get("path") == str(folder) for r in project.load(pid).get("runs",[]))
            if already:
                st.caption(f"✓ 이미 '{projects[pid]}'에 연결돼 있습니다.")
            if st.button("연결",key=f"ps_{folder.name}",disabled=already):
                cfg = meta.get("config",{})
                vis_f = folder / "evaluation.json"
                kpi = json.loads(vis_f.read_text(encoding="utf8")).get("kpi",{}) if vis_f.is_file() else {}
                project.log_run(project.load(pid),cfg,"본선 통합 검토",
                                {"검토 판단":meta.get("decision",""),"신제품 구매 비율(%)":kpi.get("shelf"),
                                 "가상 구매의향 TOP2(%)":kpi.get("top2")},str(folder))
                st.success(f"'{projects[pid]}'에 연결했습니다.")
    with c3.popover("지우기"):
        st.caption("목록에서 빼고 outputs/trash 로 옮깁니다(되살리려면 폴더를 다시 옮기면 됨).")
        if st.button("이 결과 지우기",key=f"d_{folder.name}",type="primary"):
            trash = OUT_DIR / "trash"
            trash.mkdir(parents=True,exist_ok=True)
            shutil.move(str(folder), str(trash / folder.name))
            st.rerun()


def project_links():
    """보고서 폴더 → 연결된 프로젝트 이름들."""
    out = {}
    for item in project.list_projects():
        try:
            rec = project.load(item["id"])
        except Exception:
            continue
        for r in rec.get("runs",[]):
            if r.get("path"):
                out.setdefault(r["path"],[])
                if rec["name"] not in out[r["path"]]:
                    out[r["path"]].append(rec["name"])
    return out


def project_savings(record):
    """프로젝트에 묶인 검토: 실제 조사로 보낸 컨셉 수와 걸러서 아낀 조사 비용(과제 설명 자료 기준)."""
    from vm.insight import survey_costs
    latest = {}
    for r in record.get("runs",[]):
        if r.get("kind") == "본선 통합 검토":
            latest[r.get("version") or r.get("path") or r.get("time")] = r  # 컨셉 버전마다 가장 최근 판단 하나만
    if not latest:
        return
    decisions = [str(r.get("summary",{}).get("검토 판단","")) for r in latest.values()]
    go = sum("실제 조사" in d for d in decisions)
    skipped = len(decisions) - go
    name,who,cost = survey_costs()[-1]
    c1,c2,c3 = st.columns(3)
    c1.metric("가상으로 검토한 컨셉",f"{len(decisions)}개")
    c2.metric("실제 조사로 보낸 컨셉",f"{go}개")
    c3.metric("걸러서 아낀 조사 비용",f"{skipped*cost:,}만 원",help=f"보류·수정 판단 {skipped}건 × {name}({who}) {cost:,}만 원 · 과제 설명 자료 기준")


def history_page():
    st.header("검토 이력")
    st.caption("저장한 검토 결과를 API 없이 다시 엽니다 · 시연은 여기서 보여 주면 됩니다.")
    reports = sorted([*OUT_DIR.glob("challenge_*/report.md"),*DEMO_DIR.glob("challenge_*/report.md")],key=lambda p:p.stat().st_mtime,reverse=True)
    if not reports:
        st.info("저장한 검토 보고서가 여기에 표시됩니다.")
    else:
        names, text, metas = {}, {}, {}
        linked = project_links()
        for path in reports:
            text[path] = path.read_text(encoding="utf8")
            meta_f = path.with_name("config.json")
            metas[path] = json.loads(meta_f.read_text(encoding="utf8")) if meta_f.is_file() else {}
            base = metas[path].get("title") or text[path].splitlines()[0].lstrip("# ").removesuffix(" 검토 보고서")
            when = str(metas[path].get("saved_at",""))[5:19].replace("T"," ")  # 월-일 시:분:초
            dec = metas[path].get("decision","")
            n = metas[path].get("config",{}).get("n")
            proj = ", ".join(linked.get(str(path.parent), []))
            names[path] = " · ".join(x for x in [base, when, dec, f"{n}명" if n else "", f"📁 {proj}" if proj else ""] if x)
        selected = st.selectbox("보고서",reports,format_func=lambda p:names[p])
        manage(selected, metas[selected], text[selected])
        evaluation = selected.with_name("evaluation.json")
        visual = json.loads(evaluation.read_text(encoding="utf8")) if evaluation.is_file() else {}
        if visual.get("kpi"):
            st.subheader(names[selected])
            result_view(visual, visual.get("sections",{}), cfg=metas[selected].get("config"))
            if visual.get("fgi"):
                with st.expander("가상 FGI · 라운드별 발언"):
                    show_fgi(visual.get("fgi"))
            with st.expander("보고서 전문"):
                st.markdown(text[selected])
        else:
            st.markdown(text[selected])
            if visual:
                with st.expander("저장한 진열대 시뮬레이션과 가상 FGI"):
                    show_shelf(visual)
                    show_fgi(visual.get("fgi"))
        default_name = names[selected].split(" · 📁")[0].replace(" · ","_").replace(":","").replace(" ","_")
        fname = st.text_input("내려받을 파일 이름 (입력 후 Enter)",default_name,key=f"dl_{selected.parent.name}")
        st.download_button("선택한 보고서 다운로드",text[selected],file_name=(fname.strip() or "검토보고서").removesuffix(".md")+".md")
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
            project_savings(record)
            st.markdown(project.export_markdown(record))
            cards = {v["id"]:v["card"] for v in record["versions"]}
            if cards:
                version = st.selectbox("컨셉 버전",cards)
                st.button("프로젝트 컨셉 다시 검토",on_click=reload_review,args=(cards[version],))


def severity_boxes(ws):
    """경고를 심각도별 개수로 보여 주고, 누르면 펼쳐 본다."""
    from vm.audit import SEV
    icon = {"높음":"🔴","중간":"🟠","참고":"⚪"}
    cols = st.columns(3)
    for col,level in zip(cols,SEV):
        col.metric(f"{icon[level]} {level}",f"{sum(w['심각도']==level for w in ws)}개")
    for level in SEV:
        items = [w for w in ws if w["심각도"]==level]
        if items:
            with st.expander(f"{icon[level]} {level} 경고 {len(items)}개 보기",expanded=False):
                st.dataframe(pd.DataFrame(items).drop(columns="심각도"),hide_index=True,width="stretch")


def proceed_bar(key):
    """자료를 더 넣지 않을 때 바로 다음 단계로."""
    from vm import store
    names = store.analysis_datasets()
    summ = store.summary() if names else []
    left,right = st.columns([3,1],vertical_alignment="center")
    left.caption(("다음 단계에서 쓸 자료: " + ", ".join(names) + f" · {len(summ)}종") if summ
                 else "분석에 쓸 자료가 아직 없습니다. 그래도 넘어가면 과거 사례·트렌드·설문 비교 없이 가상 소비자 평가만 합니다.")
    right.button("변경 없이 진행 → ② 신제품 검토",key=key,type="primary",width="stretch",
                 on_click=lambda: st.session_state.update(nav=PAGES[1]))


def scope_picker(key):
    """분석에 쓸 묶음(여러 개). 처음에는 전체 선택, 필요하면 빼기."""
    from vm import store
    names = store.datasets()
    if not names:
        st.caption("아직 자료 묶음이 없습니다. '① 자료 준비'에서 만드세요.")
        return
    cur = store.analysis_datasets()
    ver = st.session_state.get("scope_ver",0)  # 두 곳(사이드바·자료 준비)의 선택 칸이 같은 값을 쓰도록, 바뀌면 둘 다 새로 만든다
    pick = st.multiselect("분석에 쓸 자료 묶음(여러 개 가능)",names,default=cur,key=f"{key}_{ver}",
                          help="처음에는 모든 묶음이 선택됩니다. 필요 없는 묶음은 x로 빼세요. 같은 자료가 든 묶음을 같이 고르면 중복으로 잡힙니다.")
    c1,c2 = st.columns(2)
    if c1.button("전체 선택",key=f"{key}_all_{ver}"):
        pick = names
    if c2.button("모두 해제",key=f"{key}_none_{ver}"):
        pick = []
    if pick != cur:
        store.set_analysis_datasets(pick)
        st.session_state["scope_ver"] = ver + 1
        st.rerun()


def data_page(mock, api_key):
    from vm import audit, store, trends_ext
    st.header("① 자료 준비")
    proceed_bar("proceed_top")
    st.caption("자료는 **묶음** 단위로 넣습니다(예: '2027 신제품 후보', '한빛 시험 세트1'). 원본은 고치거나 지우지 않고, 위험한 행은 표시만 합니다. "
               "분석에 어떤 묶음을 쓸지는 왼쪽 사이드바나 아래 '분석에 쓰는 자료 점검'에서 고릅니다.")
    st.subheader("자료 넣기")
    names = store.datasets()
    current_ds = store.active_dataset()
    left,right = st.columns([2,1],vertical_alignment="bottom")
    choice = left.selectbox("자료를 넣을 묶음",[*names,"＋ 새 묶음 만들기"],
                            index=names.index(current_ds) if current_ds in names else len(names))
    ds = None
    if choice == "＋ 새 묶음 만들기":
        new = right.text_input("새 묶음 이름",placeholder="예: 2027 신제품 후보")
        if right.button("만들기",disabled=not new.strip()):
            err = store.create_dataset(new)
            if err:
                right.error(err)
            else:
                st.rerun()
        if not names:
            st.info("먼저 묶음 이름을 정하세요. 그다음 파일을 올리거나 DB를 연결합니다.")
            return
    else:
        if choice != current_ds:
            store.set_active_dataset(choice)
            st.rerun()
        ds = store.active_dataset()
        with right.popover("이름 바꾸기"):
            renamed = st.text_input("새 이름",ds,key="rename_ds")
            if st.button("바꾸기",disabled=renamed.strip() in ("",ds)):
                err = store.rename_dataset(ds,renamed)
                if err:
                    st.error(err)
                else:
                    st.rerun()
        t1,t2,t3 = st.tabs(["파일 올리기","기존 DB 연결","외부 트렌드(네이버 데이터랩)"])
        with t1:
            ups = st.file_uploader("자료 파일(여러 개 가능) · 엑셀·CSV·Word·PowerPoint·텍스트",type=["xlsx","xls","csv","docx","pptx","txt","md"],
                                   accept_multiple_files=True,key=f"store_files_{ds}")
            if st.button("이 묶음에 등록",disabled=not ups):
                for f in ups:
                    try:
                        r = store.add_file(f.name,f.getvalue(),ds)
                        st.write(f"**{f.name}** · {r['status']}")
                    except Exception as exc:
                        st.error(f"{f.name} 등록 실패 · {exc}")
        with t2:
            st.caption("이미 있는 DB의 표를 읽어 이 묶음에 사본으로 넣습니다(원본 DB는 바꾸지 않음). 다시 가져오면 최신 내용으로 바뀝니다. "
                       "SQLite는 `sqlite:///C:/경로/파일.db`, 사내 DB는 `postgresql://아이디:비번@주소/DB이름` 형식(드라이버 설치 필요). "
                       "비밀번호가 들어간 주소는 저장하지 않으니 `.env`에 `DATA_DB_URL`로 두면 편합니다.")
            url = st.text_input("연결 주소",os.getenv("DATA_DB_URL",""),type="password")
            if url:
                try:
                    names_db = store.db_tables(url)
                    pick = st.multiselect("가져올 표",names_db,default=store.get_setting("db_links",{}).get(ds,{}).get(store.mask_url(url),[]))
                    if st.button("가져오기 / 최신으로 다시 가져오기",disabled=not pick):
                        for r in store.add_db(url,pick,ds):
                            st.write(r["file"],"·",r["status"])
                except Exception as exc:
                    st.error(f"연결 실패 · {exc}")
        with t3:
            st.caption("네이버 데이터랩 검색어 트렌드(공식 API) · 주 단위로 받아 월 평균으로 분석합니다. 같은 요청 안의 키워드는 같은 기준이라 서로 비교할 수 있습니다. "
                       "키: developers.naver.com 에서 '데이터랩(검색어트렌드)' 앱 등록 → `.env`에 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET.")
            job = store.get_setting("trend_jobs",{}).get(ds)
            if job:
                st.write(f"마지막 수집 {job['last']} · " + " / ".join(f"{g}: {', '.join(k)}" for g,k in job["groups"].items()))
                if trends_ext.due():
                    st.warning("마지막 수집 후 7일이 지났습니다. 아래에서 다시 받으세요.")
            default = "\n".join(f"{g}: {', '.join(k)}" for g,k in (job or {}).get("groups",{}).items()) or "수박화채: 수박화채, 수박화채 음료\n얼려먹는 커피: 얼려먹는 커피, 커피 슬러시"
            txt = st.text_area("키워드 그룹(한 줄에 하나, 최대 5줄) · '그룹 이름: 검색어1, 검색어2'",default,height=120)
            unit = st.radio("단위",["week","month"],format_func={"week":"주","month":"월"}.get,horizontal=True)
            if st.button("받기",disabled=not trends_ext.has_key()):
                groups = {}
                for line in txt.splitlines():
                    if ":" in line:
                        g,ks = line.split(":",1)
                        groups[g.strip()] = [k.strip() for k in ks.split(",") if k.strip()]
                try:
                    r = trends_ext.collect(groups,unit)
                    st.success(f"수집 완료 · {r['period']} · {r['rows']}개 시점")
                except Exception as exc:
                    st.error(f"수집 실패 · {exc}")
            if not trends_ext.has_key():
                st.caption("키가 없어 버튼이 꺼져 있습니다.")

    st.divider()
    st.subheader("분석에 쓰는 자료 점검")
    scope_picker("scope_data_page")
    cat = store.catalog()
    if cat.empty:
        st.info("선택한 묶음에 아직 자료가 없습니다.")
        return
    act = cat[cat["active"]==1]
    todo = act[act["how"]=="미분류"]
    ws = audit.run_all()
    labels = ["내용 요약","데이터 경고 " + f"(높음 {sum(w['심각도']=='높음' for w in ws)})","오염도·위험 행 빼기",
              f"짝짓기 필요 ({len(todo)})","등록 파일·빼기"]
    u1,u2,u3,u4,u5 = st.tabs(labels)
    with u1:
        summ = store.summary()
        if summ:
            st.dataframe(pd.DataFrame(summ),hide_index=True,width="stretch")
        else:
            st.caption("요약할 자료가 없습니다.")
        sm = audit.survey_metrics()
        if not sm.empty:
            with st.expander("설문 구매의향 등 · 원자료 / 품질 의심 제외 / 모집단 가중 나란히"):
                st.dataframe(sm,hide_index=True,width="stretch")
    with u2:
        st.caption("자료를 고치거나 버리지 않고, 결론을 틀리게 만들 수 있는 점을 표시합니다. 리포트와 AI 에이전트에도 그대로 들어갑니다.")
        severity_boxes(ws)
    with u3:
        cont = audit.contamination()
        if cont:
            st.dataframe(pd.DataFrame(cont),hide_index=True,width="stretch")
            reasons = audit.risk_reasons()
            chosen = st.multiselect("분석에서 뺄 위험 행(여러 개 선택 가능 · 원본은 그대로 보관)",reasons,
                                    default=[r for r in audit.excluded_reasons() if r in reasons],
                                    help="고른 사유에 해당하는 행만 분석에서 뺍니다. 리포트의 자료 버전에 뺀 항목이 표시됩니다.")
            if chosen != audit.excluded_reasons():
                store.set_setting(f"exclude_reasons::{store.scope_key()}",chosen)
                st.rerun()
        else:
            st.caption("행 단위로 위험을 표시할 자료(설문 응답·POS·온라인 로그)가 없습니다.")
    with u4:
        if not len(todo):
            st.caption("모든 표의 역할을 알아봤습니다.")
        else:
                st.caption("① 이 표가 무슨 자료인지 고르고 ② 아래 표의 '어디에 쓸지'만 확인하세요. 열 이름과 값 모양으로 미리 채워 둡니다. "
                           "저장하면 같은 머리글의 다음 파일은 자동으로 인식합니다.")
                for _, row in todo.iterrows():
                    key = row["table_id"]
                    df = store.sample(key)
                    header = [c for c in df.columns if c != "_row"]
                    st.markdown(f"**{row['name']} · {row['sheet']}**")
                    a,b = st.columns([2,1])
                    if b.button("AI 제안 받기",key=f"ai_{key}",disabled=not can_run(mock)):
                        st.session_state[f"map_{key}"] = store.suggest_mapping(key,LLM(mock=mock,api_key=api_key))
                    sug = st.session_state.get(f"map_{key}") or {"role":store.guess_role(df),"mapping":{}}
                    roles = [None,*store.ROLES]
                    role = a.selectbox("① 이 표는 (값 모양으로 추측해 미리 골라 둠)",roles,index=roles.index(sug["role"]) if sug["role"] in roles else 0,
                                       format_func=lambda r:"선택" if r is None else store.ROLES[r]["label"],key=f"role_{key}")
                    if not role:
                        st.dataframe(df.drop(columns="_row",errors="ignore").head(3),hide_index=True)
                        continue
                    guess = {**store.guess_mapping(df,role),**sug.get("mapping",{})}
                    back = {v:k for k,v in guess.items()}
                    req = store.ROLES[role]["required"]
                    opts = ["(쓰지 않음)",*[f"{c} ★" if c in req else c for c in store.ROLES[role]["columns"]]]
                    plan = pd.DataFrame([{"원래 열":h,"예시 값":", ".join(df[h].dropna().astype(str).head(3)),
                                          "② 어디에 쓸지":(f"{back[h]} ★" if back.get(h) in req else back.get(h)) or "(쓰지 않음)"} for h in header])
                    edited = st.data_editor(plan,hide_index=True,width="stretch",disabled=["원래 열","예시 값"],key=f"plan_{key}_{role}",
                                            column_config={"② 어디에 쓸지":st.column_config.SelectboxColumn(options=opts,required=True)})
                    mapping = {}
                    for _, r in edited.iterrows():
                        target = str(r["② 어디에 쓸지"]).replace(" ★","")
                        if target != "(쓰지 않음)" and target not in mapping:
                            mapping[target] = r["원래 열"]
                    need = [c for c in req if c not in mapping]
                    st.caption("★ 꼭 필요한 항목: " + ", ".join(req) + (f" · 아직 없음: {', '.join(need)}" if need else " · 모두 채움"))
                    if st.button("저장(같은 머리글의 다음 파일에도 적용)",key=f"save_{key}",disabled=bool(need),type="primary"):
                        store.set_mapping(key,role,mapping)
                        st.rerun()
                    st.divider()
    with u5:
        view = act.assign(역할=lambda d:d["role"].map(lambda r:store.ROLES[r]["label"] if r in store.ROLES else "-"))
        st.dataframe(view[["dataset","name","source","sheet","역할","how","added"]].rename(columns={
            "dataset":"묶음","name":"파일","source":"출처","sheet":"시트/표","how":"인식 방식","added":"등록"}),hide_index=True,width="stretch")
        files = act.drop_duplicates("file_id")
        drop = st.multiselect("분석에서 뺄 파일(여러 개 가능, 원본은 보관)",list(files["file_id"]),
                              format_func=lambda k:f"{files.set_index('file_id').at[k,'dataset']} · {files.set_index('file_id').at[k,'name']}")
        if drop and st.button("선택한 파일 빼기"):
            for k in drop:
                store.deactivate(k)
            st.rerun()
    st.divider()
    proceed_bar("proceed_bottom")


def archive_page(mock, api_key):
    from vm import datasets
    from vm import archive_records as intake
    data_page(mock, api_key)
    active_standard = datasets.current()
    st.header("옛 자료 항목별 정리")
    st.caption("표 형식이 아닌 메모·문서형 옛 자료를 행·문단 단위로 AI가 분류하고 담당자가 확인해 저장합니다. 저장한 항목은 유사 사례 검색에 쓰입니다.")
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
    mock = st.toggle("API 없이 시험(mock)", value=not bool(os.getenv("OPENAI_API_KEY") or os.getenv("GATEWAY_KEY")),
                     help="모의 응답으로 화면과 흐름을 확인합니다.")
    api_key = st.text_input("OpenAI API 키 (선택)",type="password",key="user_key") or None
    if APP_PASSWORD and not mock and not api_key:
        password = st.text_input("실행 비밀번호",type="password")
        st.session_state["pw_ok"] = bool(password) and password == APP_PASSWORD
    else:
        st.session_state["pw_ok"] = False
    _base = os.getenv('OPENAI_BASE_URL') or ""
    if ENV_INFO.get("file"):
        st.caption(f"설정 파일: `{ENV_INFO['file']}` · 읽은 항목: {', '.join(k for k in ENV_INFO['keys'] if k in ('OPENAI_API_KEY','GATEWAY_KEY','OPENAI_BASE_URL','VM_MODEL','APP_PASSWORD','NAVER_CLIENT_ID')) or '없음'}")
        if ENV_INFO.get("note"):
            st.warning(ENV_INFO["note"])
        if ENV_INFO.get("commented"):
            st.warning("주석(#) 처리돼 읽히지 않은 항목: " + ", ".join(ENV_INFO["commented"]) + " → 줄 앞의 # 를 지우세요.")
    else:
        st.error(ENV_INFO.get("note") or ".env 파일을 찾지 못했습니다.")
    st.caption(f"접속: {'대회 게이트웨이' if 'pydantic' in _base else ('사용자 지정 주소' if _base else 'OpenAI 기본')} · 모델 `{os.getenv('VM_MODEL') or '기본'}`")
    if st.button("연결 시험(짧은 호출 2번)",disabled=mock):
        from vm.llm import check_connection
        lines = check_connection(api_key)
        ok = all("실패" not in l for l in lines[1:])
        (st.success if ok else st.error)("연결 정상" if ok else "연결 실패")
        for l in lines[1:]:
            st.caption(("✅ " if "성공" in l else "❌ ") + l.split(":")[0] + ("" if "성공" in l else ":" + l.split(":",1)[1][:160]))
    st.divider()
    scope_picker("scope_sidebar")

hero()
if st.session_state.get("nav") not in PAGES:
    st.session_state["nav"] = PAGES[0]
page = st.radio("메뉴",PAGES,key="nav",horizontal=True,label_visibility="collapsed")
st.markdown('<div class="nav-line"></div>',unsafe_allow_html=True)
if page == PAGES[0]:
    archive_page(mock,api_key)
elif page == PAGES[1]:
    review_page(mock,api_key)
    review_footer()
elif page == PAGES[2]:
    validation_page(mock,api_key)
elif page == PAGES[3]:
    history_page()
else:
    limits_page()
    with st.expander("AI 에이전트 설계 · 도구와 안전장치 (화면 탭은 '② 신제품 검토'로 합침)"):
        agent_design_page()
