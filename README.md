# 프리셸프 PreShelf — AI 페르소나 신제품 가상시장 검증 프로토타입

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
기본 응답 방식은 `--mode prob`("이 프로필과 비슷한 100명이 어떻게 나뉠지")입니다. 설문 재현 검증에서 대표 답 쏠림을 줄이는 효과가 확인되어 채택했습니다.
예전 방식(한 사람이 하나를 고름)은 `--mode single`.

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

**2차 후보** (1차 30명 결과를 보고 추가, 기본 실행에는 포함되지 않음)

| 조건 | 내용 |
|---|---|
| `balanced` | 가격·새로움 어느 쪽으로도 치우치지 않게 다시 쓴 지시문 |
| `balanced_neutral` | balanced + 중립 상황 |
| `habit_first` | balanced_neutral + 프로필에서 음료 습관을 먼저 추정해 붙임(2단계 호출) |

```bash
python -m vm.experiments --n 30 --only base balanced balanced_neutral habit_first
```

결과: `outputs/exp_날짜시각/comparison.csv` (조건별 비교표) + 조건별 `responses_*.csv`
- `share_*` 선택 비율%, `top_share` 1위 제품 비율(쏠림), `diversity` 선택 다양성(0 독식 ~ 1 균등)
- `concept_intent(_sd)` 신제품 구매의향 평균(표준편차), `intent5_any` 5점을 한 번이라도 준 비율
- `persona_grounding` 이유에 본인 직업·취미·식생활 단어가 나온 비율(대략적인 페르소나 반영도)
- `mentions_thirst` / `mentions_price` 이유에 갈증 / 가격 언급 비율

## 5. 설문 재현 검증 (실제 소비자 조사와 비교)

진열대 결과가 맞는지 판단할 기준이 없어서, 공개된 실제 설문과 **같은 질문**을 페르소나에게 묻고 비교합니다.

- 기준 데이터: 한국농촌경제연구원 **식품소비행태조사** 성인 가구원 원자료 2023~2025
  ([통계원시자료](https://krei.re.kr/foodSurvey/page/460)) — "가장 좋아하는 음료(1~3순위)", "제로 음료 섭취 빈도"
- 저장소에는 원자료를 넣지 않고 집계표 `data/reference/krei_beverage.json`만 넣었습니다.
  원자료에서 다시 만들려면: `python -m vm.reference --files 2023=경로 2024=경로 2025=경로`
- 가중치: 연도 안에서는 조사 개인 가중치(psfwt), 연도는 2023:0.2 / 2024:0.3 / 2025:0.5, 70대 이상은 60대 이상으로 합침

```bash
python -m vm.survey --n-per-age 10            # 연령대 5개 × 10명 × 조건 5개
python -m vm.survey --n-per-age 20 --only base balanced
```

**평가 규칙 (실행 전에 고정, 결과를 보고 바꾸지 않음)**

| 구분 | 지표 | 쓰임 |
|---|---|---|
| 주 지표 | `fav_mae`: 연령대별 '좋아하는 음료 1순위' 분포 오차(%p) | **가장 작은 조건을 기본 설정으로 채택** (0.3%p 미만 차이면 `four_rate_mae`로 결정) |
| 보조 | `four_rate_mae`: 연령대별 '탄산·이온 4종을 1순위로 꼽은 비율' 오차, `four_age_corr`: 연령 방향 일치도 | 해석용 |
| 검증 | `zero_mae`: 연령대별 제로 음료 섭취 빈도 오차 (2025) | **설정 선택에 쓰지 않음**, 채택한 설정이 다른 문항에서도 맞는지 확인 |
| 참고선 | 실제 조사끼리 연도 비교 `fav_mae` 1.2~1.8%p / 무작위 응답 기준선 | 오차가 어느 수준인지 해석 |

**응답 방식 조건 `prob` (1차 실행 후 추가)**: "이 프로필과 비슷한 100명이 어떻게 나뉠지"를 묻는 방식.
1차 실행에서 1순위가 몇 종류에만 몰리고(우유류 0명) 극단 답이 사라진 문제를 줄이기 위함.
같은 응답을 분포 평균(`prob`)과 가장 큰 답 하나(`prob(argmax)`)로 함께 집계해 방식의 효과를 분리한다.
※ 분포를 평균하면 고르게 퍼진 답만으로도 오차가 어느 정도 줄어든다(균등 분포 = 무작위 기준선 4.3%p).
  그래서 `prob`은 **무작위 기준선보다 확실히 낮아야** 의미 있는 개선으로 본다.

## 6. 시장 검증 에이전트 (오케스트레이터)

마케터의 자연어 요청을 받아 LLM이 스스로 계획 → 도구 호출 → 결과 확인 → 추가 실험 → 리포트 작성까지 진행합니다(OpenAI tool calling).

```bash
python -m vm.orchestrator "20~30대 대상 제주 청귤 제로 스파클링, 1,900원이 적당한지 검토해줘"
python -m vm.orchestrator "..." --budget 300 --max-steps 8
python -m vm.orchestrator "..." --mock          # API 없이 도구 연결만 시험
```

| 도구 | 하는 일 | 비용 |
|---|---|---|
| `check_reliability` | 최근 설문 재현 검증 결과로 패널 신뢰도 확인 | 없음 |
| `run_shelf_simulation` | 타깃 연령·가격·이름·설명을 바꿔 진열대 시뮬레이션 | 패널 인원만큼 |
| `compare_prices` | 같은 패널로 가격만 바꿔 비교 | 인원 × 가격 수 |
| `compare_concepts` | 같은 패널로 이름·설명만 바꾼 안 A/B 비교 | 인원 × 안 수 |
| `get_reasons` | 구매·비구매 이유 표본 | 없음 |
| `run_fgi` | 가상 좌담회: 4~6명이 3라운드 대화, 입장 변화(설득 장면) 추적 | 약 인원×3+1 |
| `suggest_improvements` | 비구매 이유를 근거로 개선안 제안 → `compare_concepts`로 재검증 | 1 |

모든 시뮬레이션 도구는 연령에 더해 성별(`sex`)·지역(`region`: 수도권/비수도권)·1인 가구(`single_only`) 타깃을 받습니다.
| `write_report` | 최종 리포트 제출 | — |

안전장치: 페르소나 호출 예산(`--budget`, 기본 400), 최대 단계(`--max-steps`, 기본 10, 마지막 단계는 리포트 강제), 패널 상한 100명, 숫자는 도구 결과만 인용하도록 지시.
결과: `outputs/agent_날짜시각/report.md`(리포트), `trace.json`(모든 도구 호출과 결과 기록).
에이전트 모델을 따로 쓰려면 `--agent-model 모델명` 또는 `.env`에 `VM_AGENT_MODEL=`.

## 7. 데모 화면 (Streamlit)

```bash
streamlit run app.py
```
브라우저가 열리면 왼쪽에서 신제품 컨셉(이름·설명·가격·용량·타깃 연령)을 정하고 탭을 오갑니다.

| 탭 | 내용 |
|---|---|
| (사이드바) 메모로 컨셉 채우기 | 자유 메모 → 컨셉 카드(이름·설명·가격·용량) 자동 정리. 메모에 없는 값은 기존 값 유지 |
| ① 컨셉 검증 (AI 에이전트) | 요청 입력 → 에이전트의 단계별 실행이 실시간으로 표시 → 리포트, 실행 기록(trace) |
| ② 진열대 시뮬레이션 | 구매 비율 그래프, 사 볼 의향, 지불의사가격, 연령대별 결과, 이유 표본, **개선 컨셉 루프**(개선안 → 같은 패널 재검증) |
| ③ 가상 FGI | 페르소나 좌담회 대화, 라운드별 입장 변화, 핵심 반응·우려·개선 아이디어·설득 장면 요약 |
| ④ 신뢰도 검증 | 실제 설문(KREI) 대비 오차, 연령별 탄산·이온 선호 비교 그래프 |
| ⑤ 서비스 구조·운영 | 아키텍처, 운영 프로세스 6단계, 롯데칠성 활용처 |
| ⑥ 한계와 로드맵 | 발견한 LLM 편향과 대응, 다음 단계 |

- **화이트/다크 모드**: 왼쪽 맨 위 🌙/☀️ 버튼으로 바꿉니다(입력값 유지). 포인트 컬러는 레드로 같습니다.
- **실행 권한**: `.env`(로컬) 또는 Secrets(배포)에 `APP_PASSWORD`를 정하면, 서버에 넣어 둔 내 API 키는 그 비밀번호를 아는 사람만 씁니다. 비워 두면 비밀번호 없이 실행됩니다.
- **다른 사람의 API 키로 실행**: 왼쪽 아래 'OpenAI API 키'에 입력하면 그 키로 실행합니다. 이번 접속에서만 쓰고 저장하지 않으며, 비용은 키 주인 계정에 청구됩니다. 비워 두면 `.env`(로컬) 또는 Secrets(배포)의 키를 씁니다.
- **경쟁 진열대 편집**: 왼쪽 '경쟁 진열대 → 제품 추가·수정'에서 제품명·용량·가격·설명을 직접 넣고 지울 수 있습니다(최대 8개).
- **서비스 이름 바꾸기**: `app.py` 맨 위의 `APP_NAME`, `APP_TAGLINE` 두 줄만 바꾸면 됩니다.
- **API 없이 시연**: ①의 '저장된 결과 보기'에서 이전 실행을 불러오면 됩니다(인터넷·크레딧 불필요).
- 왼쪽 'API 없이 시험(mock)'은 화면 흐름 확인용이며 수치는 의미가 없습니다.

## 8. 시나리오 바꾸기

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
- [~] 2일차: 대조실험 도구(완료) / 설문 재현 검증(완료) / 신뢰도 검증(긍정 편향, 위치 편향, 반복 일관성) + 리포트
- [x] 진열대 시뮬레이션에 '100명 분포 응답' 적용
- [x] 시장 검증 에이전트(오케스트레이터)
- [x] 3일차: Streamlit 화면
