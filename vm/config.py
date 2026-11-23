from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "outputs"
CONFIG_DIR = ROOT / "config"
PERSONA_PATH = DATA_DIR / "personas_pool.parquet"
DEFAULT_MODEL = "gpt-5.4-mini"

AGE_BINS = [19, 30, 40, 50, 60, 200]
AGE_LABELS = ["20대 이하", "30대", "40대", "50대", "60대 이상"]

# 저장소에 함께 올리는 시연용 결과(outputs/ 는 .gitignore 라 배포 앱에 없음). 같은 폴더 구조로 넣는다.
DEMO_DIR = ROOT / "demo_results"


def result_files(pattern: str) -> list[str]:
    """outputs/ 와 demo_results/ 에서 pattern(예: 'agent_*', 'fgi_*/fgi.json')을 찾아
    결과 폴더 이름(시각) 순으로 정렬. 같은 이름이 둘 다 있으면 outputs/ 쪽을 쓴다."""
    import glob
    found = {}
    for base in (DEMO_DIR, OUT_DIR):  # 나중 것이 덮어씀 → outputs 우선
        for f in glob.glob(str(base / pattern)):
            found[Path(f).relative_to(base).as_posix()] = f
    return [found[k] for k in sorted(found)]
