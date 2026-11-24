"""본선 자료 검색과 패널 행동 분포 결합.

대회 제공 자료(data/challenge/)는 저장소에 올리지 않는다. 파일이 없으면 빈 자료로 동작한다.
"""
import json
import re
from pathlib import Path

CHALLENGE_DIR = Path(__file__).resolve().parents[1] / "data" / "challenge"
ALIASES = {"냉동": ["프리즈", "얼려", "슬러시"], "주스": ["쥬스", "착즙", "과채"], "탄산": ["스파클링", "소다", "에이드"], "커피": ["라떼", "카페모카"], "수박": ["화채"]}


def local_json(name, default):
    """로컬에만 있는 대회 자료 JSON. 없거나 깨졌으면 default."""
    path = CHALLENGE_DIR / name
    try:
        return json.loads(path.read_text(encoding="utf8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def boards():
    """컨셉보드 예시(로컬 data/challenge/boards.json). 형식: {"이름": [설명, 가격, 용량mL, 채널]}"""
    return {k: tuple(v) for k, v in local_json("boards.json", {}).items()}


def terms(text):
    words = set(re.findall(r"[가-힣a-zA-Z]{2,}", text.lower()))
    for tag, aliases in ALIASES.items():
        if any(a in text for a in [tag, *aliases]):
            words.add(tag)
    return words - {"음료", "신제품", "제품"}


def retrieve(query, assets=None):
    candidates = []
    from .archive_records import records
    added = [{**r, "코드":"과거자료-"+r["id"][:10], "비고":r["file"]+" / "+r["location"]} for r in records()]
    base = local_json("evidence.json", {"assets": []})["assets"] if assets is None else assets
    for asset in [*added, *base]:
        matched = terms(query) & terms(" ".join(str(asset.get(k) or "") for k in ("제품","분류","컨셉","규격")))
        if matched:
            candidates.append((len(matched), asset, sorted(matched)))
    return sorted(candidates, key=lambda x: -x[0])[:5]
