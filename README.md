# 칠성 버추얼 마켓 (가칭) — 프로토타입

AI 페르소나 패널이 가상 진열대 앞에서 신제품 컨셉에 반응하는 시뮬레이터입니다.
LOTTE AX Challenge [과제 1] 롯데칠성음료 "AI 페르소나 기반 신제품 시장 검증" 프로토타입.

- 페르소나: [nvidia/Nemotron-Personas-Korea](https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea) (CC BY 4.0, 국가통계 분포 기반 합성 데이터)
- LLM: OpenAI (기본 `gpt-5.4-mini`, `.env`에서 변경)

## 1. 처음 한 번만: 설치 (VS Code 터미널)

VS Code에서 이 폴더를 연 뒤 `터미널 → 새 터미널`에서 실행합니다.

**Windows (PowerShell)**
```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```
> `Activate.ps1` 실행이 막히면 한 번만: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

**Mac**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

그다음 `.env` 파일을 열어 `OPENAI_API_KEY=` 뒤에 본인 키를 넣습니다. (`.env`는 절대 공유·업로드하지 마세요.)

VS Code 오른쪽 아래 Python 인터프리터를 `.venv`로 선택해 두면 편합니다.

## 2. 처음 한 번만: 페르소나 풀 받기 (약 20초~1분, 약 50MB)

```bash
python -m vm.personas --shards 1
```
→ `data/personas_pool.parquet` (약 11만 명)

## 3. 실행

**① API 없이 동작 확인 (가짜 응답, 비용 0원)**
```bash
python -m vm.simulate --n 100 --mock
```

**② 실제 API로 소규모 확인 (5명)**
```bash
python -m vm.simulate --n 5
```

**③ 본 실행 (100명)**
```bash
python -m vm.simulate --n 100
```

옵션: `--scenario 파일경로`, `--seed 숫자`(같은 seed = 같은 패널, 대조실험용), `--age-min 20 --age-max 39`(타깃 연령), `--model 모델명`, `--workers 8`(동시 요청 수)

결과는 `outputs/run_날짜시각/`에 저장됩니다.
- `responses.csv` — 한 사람당 한 행 (선택, 제품별 구매의향·최대 지불가격, 이유, 신제품 진열 위치)
- `summary.txt` — 선택 비율, 신제품 구매의향·지불의사가격, 연령대별 선택률
- `meta.json` — 실행 조건 기록

같은 조건으로 다시 돌리면 `outputs/llm_cache.jsonl`의 응답을 재사용합니다(비용 0, 같은 결과).
새로 받고 싶으면 이 파일을 지우세요.

## 4. 시나리오 바꾸기

`config/scenario_example.json`을 복사해 수정합니다.
- `situation`: 소비자가 처한 상황
- `products`: 진열대 제품들 (`id`, `name`, `volume_ml`, `price`, `description`)
- `concept_id`: 검증할 신제품의 `id`

## 설계 메모 (편향을 줄이기 위한 장치)

- **블라인드**: 신제품에 '신제품' 표시를 하지 않고 경쟁 제품과 같은 형식으로 보여줍니다.
- **진열 순서 무작위화**: 페르소나마다 순서를 섞고 신제품 위치를 기록합니다(위치 편향 점검).
- **비구매 선택지**: "사지 않음"을 정상적인 선택으로 명시합니다.
- **반편향 지시**: 광고 문구·고정관념이 아니라 프로필의 구체적 생활에 근거하게 합니다.
- **JSON 스키마 강제 출력**: 집계 오류를 막고, 형식이 깨진 응답은 버리지 않고 `error` 열에 기록합니다.

## 진행 상황

- [x] 1일차: 페르소나 패널 + 에이전트 + CLI 실행
- [ ] 2일차: 분석·신뢰도 검증(긍정 편향, 위치 편향, 반복 일관성, 가격 대조실험) + 리포트
- [ ] 3일차: Streamlit 화면
