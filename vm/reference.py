"""KREI 식품소비행태조사(성인 가구원) 원자료 → 비교 기준표(집계값만) 만들기.

출처: 한국농촌경제연구원 식품소비행태조사 통계원시자료
      https://krei.re.kr/foodSurvey/page/460  (2023~2025년 Excel, '성인가구원' 파일)
원자료는 저장소에 넣지 않고, 이 스크립트가 만든 집계표(data/reference/krei_beverage.json)만 사용한다.

가중치 (실행 전에 정한 규칙)
- 연도 안: 조사가 제공한 개인 가중치(psfwt)
- 연도 합치기: 연령대별 분포를 연도마다 구한 뒤 2023:0.2, 2024:0.3, 2025:0.5 로 섞는다(최근 가중)
- 연령: 70대 이상은 표본이 작아 '60대 이상'으로 합친다
- 제로 음료 섭취 빈도(A19)는 2025년에만 있어 2025년 값만 쓴다(검증 전용)

실행 (원자료를 받은 뒤 1회):
    python -m vm.reference --files 2023=경로.xlsx 2024=경로.xlsx 2025=경로.xlsx
"""
import argparse
import json
import re

import pandas as pd

from .config import DATA_DIR

REF_PATH = DATA_DIR / "reference" / "krei_beverage.json"
YEAR_WEIGHTS = {2023: 0.2, 2024: 0.3, 2025: 0.5}
AGE_BUCKETS = ["20대 이하", "30대", "40대", "50대", "60대 이상"]
AGE_MAP = {"19~29세": "20대 이하", "30~39세": "30대", "40~49세": "40대", "50~59세": "50대",
           "60~69세": "60대 이상", "70세 이상": "60대 이상"}

# 연도마다 보기 번호가 달라(2023: 탄산수=13, 2024~25: 12) 보기 문구로 묶는다. 위에서부터 먼저 맞는 규칙 적용.
FAV_RULES = [
    ("음료전문점|테이크아웃 커피 외", "제조음료"), ("무가당", "제로탄산"), ("가당 탄산", "가당탄산"),
    ("탄산수", "탄산수"), ("이온음료", "이온음료"), ("커피", "커피"), ("우유", "우유"),
    ("과일 주스|저과즙", "주스"), ("발효유", "발효유"), ("두유", "두유·식물성"), ("녹차", "차"),
    ("기능성", "기능성음료"), ("물 이외", "물만 마심"), ("기타", "기타"),
]
FAV_GROUPS = [g for _, g in FAV_RULES]
FOUR = ["가당탄산", "이온음료", "제로탄산", "탄산수"]
ZERO_LEVELS = ["주 1회 이상", "월 2~3회", "월 1회", "월 1회 미만", "먹어본 적 없음"]


def fav_group(label) -> str | None:
    if not isinstance(label, str):
        return None
    for pat, g in FAV_RULES:
        if re.search(pat, label):
            return g
    return None


def _find(labels: dict, pattern: str) -> str | None:
    c = [k for k, v in labels.items() if re.search(pattern, v) and not str(k).startswith("J")]
    return c[0] if c else None


def read_raw(path: str) -> pd.DataFrame:
    """변수 이름이 연도마다 달라도 변수 설명으로 문항을 찾아 필요한 열만 읽는다."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True)
    lab_ws = [w for w in wb.worksheets if w.title.startswith("Variable")][0]
    labels = {r[0]: str(r[1]) for r in lab_ws.iter_rows(values_only=True) if r[0]}
    cols = {
        "age_range": _find(labels, r"응답자 연령대"),
        "weight": _find(labels, r"개인 최종 가중치"),
        "fav1": _find(labels, r"가장 좋아하는 음료\s*\(1순위\)"),
        "zero": _find(labels, r"제로식품 섭취 빈도_\(1\) 제로 음료"),
    }
    ws = [w for w in wb.worksheets if w.title == "String"][0]
    it = ws.iter_rows(values_only=True)
    hdr = list(next(it))
    use = {k: hdr.index(v) for k, v in cols.items() if v}
    df = pd.DataFrame([[r[i] for i in use.values()] for r in it], columns=list(use))
    df["age"] = df["age_range"].str.replace(r"^\(\d\)\s*만\s*", "", regex=True).map(AGE_MAP)
    df["fav"] = df["fav1"].map(fav_group)
    if "zero" in df:
        df["zero"] = df["zero"].str.replace(r"^\(\d\)\s*", "", regex=True)
    return df


def dist_by_age(df: pd.DataFrame, col: str, levels: list) -> dict:
    out = {}
    for age in AGE_BUCKETS:
        g = df[(df["age"] == age) & df[col].notna()]
        s = g.groupby(col)["weight"].sum()
        out[age] = {lv: float(s.get(lv, 0) / s.sum()) for lv in levels}
    return out


def mae(a: dict, b: dict) -> float:
    """연령대별 분포 MAE(%p)를 연령대 평균."""
    vals = []
    for age in AGE_BUCKETS:
        vals.append(sum(abs(a[age][k] - b[age][k]) for k in a[age]) / len(a[age]) * 100)
    return sum(vals) / len(vals)


def build(files: dict) -> dict:
    per_year, age_share, zero = {}, {}, None
    for y, path in sorted(files.items()):
        print(f"[{y}] 읽는 중: {path}")
        df = read_raw(path)
        per_year[y] = dist_by_age(df, "fav", FAV_GROUPS)
        w = df.groupby("age")["weight"].sum()
        age_share[y] = {a: float(w.get(a, 0) / w.sum()) for a in AGE_BUCKETS}
        if y == 2025 and "zero" in df:
            zero = dist_by_age(df, "zero", ZERO_LEVELS)
        print(f"   응답자 {len(df):,}명")

    pooled = {a: {g: sum(YEAR_WEIGHTS[y] * per_year[y][a][g] for y in per_year) /
                  sum(YEAR_WEIGHTS[y] for y in per_year) for g in FAV_GROUPS} for a in AGE_BUCKETS}
    pooled_share = {a: sum(YEAR_WEIGHTS[y] * age_share[y][a] for y in age_share) /
                    sum(YEAR_WEIGHTS[y] for y in age_share) for a in AGE_BUCKETS}

    # 기준 자체의 흔들림: 연도끼리 비교한 MAE (시뮬레이션 오차를 해석할 때의 참고선)
    years = sorted(per_year)
    year_to_year = {f"{a}_vs_{b}": round(mae(per_year[a], per_year[b]), 2)
                    for i, a in enumerate(years) for b in years[i + 1:]}

    ref = {
        "source": "한국농촌경제연구원 식품소비행태조사 성인가구원 원자료 (https://krei.re.kr/foodSurvey/page/460)",
        "years": years, "year_weights": {str(k): v for k, v in YEAR_WEIGHTS.items()},
        "age_buckets": AGE_BUCKETS, "fav_groups": FAV_GROUPS, "four": FOUR,
        "age_share": pooled_share,
        "fav1_by_age": pooled,
        "fav1_by_age_per_year": {str(y): per_year[y] for y in years},
        "zero_drink_by_age_2025": zero, "zero_levels": ZERO_LEVELS,
        "year_to_year_fav1_mae": year_to_year,
    }
    REF_PATH.parent.mkdir(parents=True, exist_ok=True)
    REF_PATH.write_text(json.dumps(ref, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {REF_PATH}")
    print("연도 간 1순위 분포 MAE(%p):", year_to_year)
    return ref


def load_reference() -> dict:
    if not REF_PATH.exists():
        raise FileNotFoundError(f"{REF_PATH} 가 없습니다. `python -m vm.reference --files ...` 를 먼저 실행하세요.")
    return json.loads(REF_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="+", required=True, help="연도=경로 (예: 2025=data/raw/2025_성인.xlsx)")
    a = ap.parse_args()
    build({int(x.split("=", 1)[0]): x.split("=", 1)[1] for x in a.files})
