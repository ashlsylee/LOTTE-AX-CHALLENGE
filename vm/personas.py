"""페르소나 풀 준비와 패널 샘플링.

nvidia/Nemotron-Personas-Korea(100만 명, CC BY 4.0)는 9개 파일로 나뉘어 있다.
프로토타입은 첫 번째 파일(약 11만 명)만 받아 풀로 쓴다. 파일 안의 순서는 무작위라
전체 분포와 거의 같다(필요하면 --shards 로 늘릴 수 있음).

실행 (최초 1회, 인터넷 필요):
    python -m vm.personas --shards 1
"""
import argparse

import pandas as pd

from .config import AGE_BINS, AGE_LABELS, PERSONA_PATH

N_TOTAL_SHARDS = 9
COLUMNS = [
    "uuid", "sex", "age", "marital_status", "family_type", "housing_type",
    "education_level", "bachelors_field", "occupation", "province", "district",
    # 서술형 페르소나 (기본 프로필은 persona·culinary·hobbies만, 'full' 프로필은 전부 사용)
    "persona", "culinary_persona", "hobbies_and_interests",
    "professional_persona", "sports_persona", "arts_persona", "travel_persona",
    "family_persona", "cultural_background", "skills_and_expertise", "career_goals_and_ambitions",
]


def download_pool_light(max_rows: int = 10000) -> None:
    """첫 shard 전체에서 재현 가능한 무작위 우선순위로 최대 max_rows명 보관."""
    import numpy as np
    import pyarrow.parquet as pq
    from huggingface_hub import HfFileSystem

    rng = np.random.default_rng(42)
    path = f"datasets/nvidia/Nemotron-Personas-Korea/data/train-00000-of-{N_TOTAL_SHARDS:05d}.parquet"
    selected = pd.DataFrame()
    with HfFileSystem().open(path,"rb") as stream:
        for batch in pq.ParquetFile(stream).iter_batches(batch_size=5000,columns=COLUMNS):
            current = batch.to_pandas()
            current["_priority"] = rng.random(len(current))
            selected = pd.concat([selected,current],ignore_index=True)
            selected = selected.nsmallest(max_rows,"_priority")
    if selected.empty:
        raise ValueError("Nemotron 후보 풀이 비어 있습니다.")
    PERSONA_PATH.parent.mkdir(parents=True,exist_ok=True)
    temporary = PERSONA_PATH.with_suffix(".tmp.parquet")
    selected.drop(columns="_priority").to_parquet(temporary,index=False)
    temporary.replace(PERSONA_PATH)
    print(f"총 {len(selected):,}명 저장: {PERSONA_PATH}")


def download_pool(shards: int = 1) -> pd.DataFrame:
    parts = []
    for i in range(shards):
        url = (f"hf://datasets/nvidia/Nemotron-Personas-Korea/data/"
               f"train-{i:05d}-of-{N_TOTAL_SHARDS:05d}.parquet")
        print(f"[{i + 1}/{shards}] 받는 중: {url}")
        parts.append(pd.read_parquet(url, columns=COLUMNS))
    pool = pd.concat(parts, ignore_index=True)
    PERSONA_PATH.parent.mkdir(exist_ok=True)
    pool.to_parquet(PERSONA_PATH, index=False)
    print(f"총 {len(pool):,}명 저장: {PERSONA_PATH}")
    return pool


def load_pool() -> pd.DataFrame:
    if not PERSONA_PATH.exists():
        raise FileNotFoundError(
            f"{PERSONA_PATH} 가 없습니다. 먼저 `python -m vm.personas` 를 실행하세요.")
    pool = pd.read_parquet(PERSONA_PATH)
    if "sports_persona" not in pool.columns:
        print("※ 페르소나 풀이 예전 버전이라 'full' 프로필용 열이 없습니다. "
              "`python -m vm.personas` 를 다시 실행하세요.")
    if len(pool) > 10000:
        pool = pool.sample(10000, random_state=42).copy()
    pool["age_group"] = pd.cut(pool["age"], bins=AGE_BINS, labels=AGE_LABELS, right=False)
    pool["is_capital"] = pool["province"].isin(["서울", "경기", "인천"]).map(
        {True: "수도권", False: "비수도권"})
    return pool


def sample_panel(pool: pd.DataFrame, n: int, seed: int = 42,
                 age_min: int | None = None, age_max: int | None = None,
                 sex: str | None = None, single_only: bool = False,
                 region: str | None = None) -> pd.DataFrame:
    """타깃 조건으로 거른 뒤 무작위 추출. 같은 seed면 같은 패널(대조실험용).
    single_only: 1인 가구만, region: '수도권' 또는 '비수도권'."""
    df = pool
    if single_only:
        df = df[df["family_type"].astype(str).str.contains("혼자")]
    if region:
        df = df[df["is_capital"] == region]
    if age_min is not None:
        df = df[df["age"] >= age_min]
    if age_max is not None:
        df = df[df["age"] <= age_max]
    if sex:
        df = df[df["sex"] == sex]
    if len(df) < n:
        raise ValueError(f"조건에 맞는 페르소나가 {len(df)}명뿐이라 {n}명을 뽑을 수 없습니다.")
    return df.sample(n=n, random_state=seed).reset_index(drop=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="페르소나 풀 다운로드")
    ap.add_argument("--shards", type=int, default=1, help="받을 파일 수(1~9, 1개≈11만 명)")
    args = ap.parse_args()
    if args.shards == 1:
        download_pool_light()
    else:
        download_pool(args.shards)
