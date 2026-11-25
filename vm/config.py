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


ENV_INFO = {"file": None, "keys": [], "note": ""}


def load_env() -> dict:
    """프로젝트 폴더의 .env 를 확실히 읽는다(실행 위치와 무관).
    - 윈도우 메모장이 '.env.txt'로 저장한 경우도 읽는다.
    - .env 값이 우선(이전에 창에 입력한 값보다). 키 값은 기록하지 않고 이름만 남긴다."""
    from dotenv import dotenv_values, load_dotenv
    for name in (".env", ".env.txt", "env", ".env.env"):
        f = ROOT / name
        if f.is_file():
            vals = dotenv_values(f, encoding="utf-8-sig")
            load_dotenv(f, override=True, encoding="utf-8-sig")
            ENV_INFO.update(file=name, keys=[k for k, v in vals.items() if v],
                            note="" if name == ".env" else f"파일 이름이 '{name}'입니다. '.env'로 바꾸는 것을 권장합니다.")
            commented = [l.strip()[1:].split("=")[0].strip() for l in f.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
                         if l.strip().startswith("#") and "=" in l and l.strip()[1:].split("=")[0].strip().isupper()]
            ENV_INFO["commented"] = [c for c in commented if c in ("OPENAI_BASE_URL", "VM_MODEL", "OPENAI_API_KEY", "GATEWAY_KEY")
                                     and c not in ENV_INFO["keys"]]
            return ENV_INFO
    ENV_INFO.update(file=None, keys=[], note=f".env 파일을 찾지 못했습니다: {ROOT}")
    return ENV_INFO
