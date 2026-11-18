from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "outputs"
CONFIG_DIR = ROOT / "config"
PERSONA_PATH = DATA_DIR / "personas_pool.parquet"
DEFAULT_MODEL = "gpt-5.4-mini"

AGE_BINS = [19, 30, 40, 50, 60, 200]
AGE_LABELS = ["20대 이하", "30대", "40대", "50대", "60대 이상"]
