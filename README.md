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

## 2. 처음 한 번만: 페르소나 풀 받기 (약 1분, 약 200MB)

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

## 4. 대조실험 (같은 패널, 조건 하나씩만 변경)

```bash
python -m vm.experiments --n 100
```
| 조건 | 바꾸는 것 | 확인하려는 가설 |
|---|---|---|
| `base` | 없음 (기준, simulate 결과 캐시 재사용) | — |
| `no_antibias` | 반편향 지시문 제거 | 지시문이 '가장 싼 것'으로 과잉 교정했나 |
| `neutral_desc` | 제품 설명을 맛·종류만 남김 | '무가당·제로' 같은 건강 단어에 끌렸나 |
| `equal_price` | 모든 제품 같은 가격 | 가격이 선택을 얼마나 좌우하나 |
| `neutral_situ` | 상황을 "음료를 고르려 한다"로 | "목이 조금 마름"이 탄산수로 유도했나 |
| `full_persona` | 페르소나 서술 11종 전부 사용 | 프로필 정보가 부족해서 답이 비슷해졌나 |

일부만: `--only base full_persona`, 적은 인원으로 먼저: `--n 30`

결과: `outputs/exp_날짜시각/comparison.csv` (조건별 비교표) + 조건별 `responses_*.csv`
- `share_*` 선택 비율%, `top_share` 1위 제품 비율(쏠림), `diversity` 선택 다양성(0 독식 ~ 1 균등)
- `concept_intent(_sd)` 신제품 구매의향 평균(표준편차), `intent5_any` 5점을 한 번이라도 준 비율
- `persona_grounding` 이유에 본인 직업·취미·식생활 단어가 나온 비율(대략적인 페르소나 반영도)
- `mentions_thirst` / `mentions_price` 이유에 갈증 / 가격 언급 비율

## 5. 시나리오 바꾸기

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
- [~] 2일차: 대조실험 도구(완료) / 분석·신뢰도 검증(긍정 편향, 위치 편향, 반복 일관성) + 리포트
- [ ] 3일차: Streamlit 화면
