"""프로젝트 단위 관리: 신제품 하나의 검증 과정을 버전·실행 기록·단계 결정·실제 결과로 묶는다.

왜: 운영 프로세스(컨셉 입력 → 타깃 → AI 검증 → 리포트·개선 → 상위안 실제 조사 → 결과로 보정)를
화면 설명이 아니라 실제 기능으로 만들고, '어떤 컨셉 버전을 어떤 조건으로 돌려 어떤 근거로 결정했는지'를 남긴다.
실제 조사 결과를 입력하면 시뮬레이션 예측과 나란히 비교해, 쌓일수록 이 도구의 정확도를 잴 수 있다(사후 검증).

저장: outputs/projects/<id>/project.json (로컬 파일. 배포 서버는 재시작 시 지워질 수 있음)
"""
import json
import re
from datetime import datetime
from pathlib import Path

from .config import DEMO_DIR, OUT_DIR

PROJ_DIR = OUT_DIR / "projects"
DEMO_PROJ_DIR = DEMO_DIR / "projects"  # 시연용(읽기 전용). 수정하면 outputs/projects 에 저장됨
STAGES = ["컨셉 입력", "타깃 설정", "AI 검증", "리포트·개선", "실제 조사 선정", "결과 보정"]
DECISIONS = ["진행", "보류", "중단"]


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _slug(name: str) -> str:
    base = re.sub(r"[^0-9A-Za-z가-힣]+", "-", name).strip("-")[:30] or "project"
    return f"{datetime.now():%Y%m%d_%H%M%S}_{base}"


def list_projects() -> list[dict]:
    out = []
    files = {f.parent.name: f for d in (DEMO_PROJ_DIR, PROJ_DIR) for f in d.glob("*/project.json")}
    for _, f in sorted(files.items(), reverse=True):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
            out.append({"id": p["id"], "name": p["name"], "updated": p.get("updated", "")})
        except Exception:
            continue
    return out


def load(pid: str) -> dict:
    f = PROJ_DIR / pid / "project.json"
    if not f.exists():
        f = DEMO_PROJ_DIR / pid / "project.json"
    return json.loads(f.read_text(encoding="utf-8"))


def save(p: dict) -> dict:
    p["updated"] = _now()
    d = PROJ_DIR / p["id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "project.json").write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def create(name: str, goal: str = "") -> dict:
    return save({"id": _slug(name), "name": name, "goal": goal, "created": _now(),
                 "versions": [], "runs": [], "decisions": [], "actuals": []})


def card_of(cond: dict) -> dict:
    """비교에 쓰는 컨셉 카드(제품 정보만)."""
    return {k: cond[k] for k in ("name", "price", "desc", "volume")}


def current_version(p: dict, cond: dict) -> dict | None:
    """지금 카드와 같은 버전이 있으면 그 버전."""
    card = card_of(cond)
    return next((v for v in reversed(p["versions"]) if v["card"] == card), None)


def ensure_version(p: dict, cond: dict, note: str = "") -> tuple[dict, bool]:
    """지금 카드가 기존 버전과 다르면 새 버전(v1, v2…)으로 저장. (버전, 새로 만들었는지)"""
    v = current_version(p, cond)
    if v:
        return v, False
    v = {"id": f"v{len(p['versions']) + 1}", "card": card_of(cond), "created": _now(), "note": note,
         "stage": 1}  # 1 = 컨셉 입력 완료
    p["versions"].append(v)
    save(p)
    return v, True


def advance(v: dict, stage_no: int):
    """버전의 진행 단계를 올린다(내려가지는 않음). stage_no: 1~6"""
    v["stage"] = max(v.get("stage", 1), stage_no)


def log_run(p: dict, cond: dict, kind: str, summary: dict, path: str = "") -> dict:
    """실행 기록을 남기고 해당 버전의 단계를 자동으로 올린다."""
    v, _ = ensure_version(p, cond)
    advance(v, 2)  # 타깃을 정하고 실행했으므로
    if kind in ("진열대", "에이전트", "FGI", "데이터 검증"):
        advance(v, 3)
    if kind in ("에이전트", "개선 비교", "본선 통합 검토"):
        advance(v, 4)
    run = {"time": _now(), "version": v["id"], "kind": kind, "target": cond_text(cond), "summary": summary, "path": path}
    p["runs"].append(run)
    save(p)
    return run


def decide(p: dict, version_id: str, decision: str, note: str, to_survey: bool):
    v = next(x for x in p["versions"] if x["id"] == version_id)
    if decision == "진행":
        advance(v, 4)
    if to_survey:
        advance(v, 5)
        v["to_survey"] = True
    v["decision"] = decision
    p["decisions"].append({"time": _now(), "version": version_id, "decision": decision, "note": note,
                           "to_survey": to_survey})
    save(p)


def add_actual(p: dict, version_id: str, metric: str, actual: float, predicted: float | None, n: int | None, source: str):
    v = next(x for x in p["versions"] if x["id"] == version_id)
    advance(v, 6)
    p["actuals"].append({"time": _now(), "version": version_id, "metric": metric, "actual": actual,
                         "predicted": predicted, "n": n, "source": source})
    save(p)


def latest_prediction(p: dict, version_id: str) -> dict:
    """버전의 가장 최근 시뮬레이션 수치(실제 결과와 비교용)."""
    for r in reversed(p["runs"]):
        if r["version"] == version_id and "신제품 구매 비율(%)" in r["summary"]:
            return r["summary"]
    return {}


def cond_text(c: dict) -> str:
    seg = " · ".join(x for x in [c.get("sex"), c.get("region"), "1인 가구" if c.get("single") else None] if x)
    return f"{c['age'][0]}~{c['age'][1]}세" + (f" · {seg}" if seg else "") + (" · 데이터 구성" if c.get("quota") else "")


def export_markdown(p: dict) -> str:
    L = [f"# {p['name']}", "", f"- 목표: {p.get('goal') or '-'}", f"- 생성: {p['created']} · 최종 수정: {p.get('updated', '')}", ""]
    L += ["## 컨셉 버전", "", "| 버전 | 제품명 | 가격 | 설명 | 단계 | 결정 |", "|---|---|---|---|---|---|"]
    for v in p["versions"]:
        c = v["card"]
        L.append(f"| {v['id']} | {c['name']} | {c['price']:,}원 | {c['desc']} | {v.get('stage', 1)}. {STAGES[v.get('stage', 1) - 1]} | "
                 f"{v.get('decision', '-')}{' · 실제 조사 대상' if v.get('to_survey') else ''} |")
    L += ["", "## 실행 기록", ""]
    for r in p["runs"]:
        s = ", ".join(f"{k} {v}" for k, v in r["summary"].items())
        L.append(f"- {r['time']} · {r['version']} · **{r['kind']}** · {r['target']} — {s}")
    L += ["", "## 결정 기록", ""]
    for d in p["decisions"]:
        L.append(f"- {d['time']} · {d['version']} · **{d['decision']}**{' · 실제 조사로 넘김' if d['to_survey'] else ''} — {d['note']}")
    if p["actuals"]:
        L += ["", "## 실제 결과와 예측 비교 (사후 검증)", "", "| 버전 | 지표 | 실제 | 예측 | 차이 | 표본 | 출처 |", "|---|---|---|---|---|---|---|"]
        for a in p["actuals"]:
            diff = "-" if a["predicted"] is None else f"{a['predicted'] - a['actual']:+.1f}%p"
            L.append(f"| {a['version']} | {a['metric']} | {a['actual']}% | {a['predicted'] if a['predicted'] is not None else '-'}% | "
                     f"{diff} | {a['n'] or '-'} | {a['source']} |")
    L += ["", "> AI 페르소나 결과는 실제 조사를 대신하지 않는 앞단 필터입니다. 신뢰도는 실제 설문 대비 검증 결과를 함께 보세요."]
    return "\n".join(L)
