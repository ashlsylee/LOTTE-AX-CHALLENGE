"""본선 자료 검색과 패널 행동 분포 결합."""
import json
from pathlib import Path
import re

DATA = json.loads((Path(__file__).resolve().parents[1]/"data/challenge/evidence.json").read_text(encoding="utf8"))
ALIASES = {"냉동": ["프리즈", "얼려", "슬러시"], "주스": ["쥬스", "착즙", "과채"], "탄산": ["스파클링", "소다", "에이드"], "커피": ["라떼", "카페모카"], "수박": ["화채"]}


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
    for asset in [*added, *(DATA["assets"] if assets is None else assets)]:
        matched = terms(query) & terms(" ".join(str(asset[k] or "") for k in ("제품","분류","컨셉","규격")))
        if matched:
            candidates.append((len(matched), asset, sorted(matched)))
    return sorted(candidates, key=lambda x: -x[0])[:5]
