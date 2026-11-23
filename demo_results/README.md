# 시연용 결과 (demo_results)

`outputs/`는 GitHub에 올라가지 않으므로, 배포 앱에서 보여줄 결과는 이 폴더에 **같은 폴더 이름 그대로** 넣습니다.
앱은 `outputs/`와 이 폴더를 함께 읽습니다(같은 이름이면 `outputs/` 우선).

| 넣을 폴더 | 필요한 파일 | 보이는 곳 |
|---|---|---|
| `survey_<시각>/` | `comparison.csv`, `meta.json` | ④ 신뢰도 검증, 에이전트 신뢰도 도구 |
| `agent_<시각>/` | `report.md`, `trace.json`, `request.json` | ① 저장된 결과 보기 |
| `fgi_<시각>/` | `fgi.json` | ③ 저장된 좌담회 보기 |
| `connect_<시각>/` | `result.json`, `comparison_by_age.csv` | ④ 추가 검증, ⑤ 데이터 연결 |
| `projects/<id>/` | `project.json` | ⓪ 프로젝트 |

올리지 말 것: `llm_cache.jsonl`, `.env`, `_mock`이 붙은 폴더, 개인정보가 담긴 원본 데이터.

## 지금 들어 있는 결과

- `survey_20261122_220905/`: 설문 재현(KREI) 연령대당 30명, seed 42. `responses_base.csv`·`meta.json`은 실행 원본.
  `comparison.csv`는 같은 실행을 읽은 에이전트 기록(`agent_20261123_144927/trace.json`의 check_reliability 결과표)에서 옮긴 값이며,
  base 행은 `responses_base.csv`로 다시 계산해 같은 값(fav_mae 8.37, four_rate_mae 12.76 등)임을 확인함. prob(argmax) 행은 없음.
- `agent_20261123_144927/`: 가격 대조실험(1,900 / 2,200 / 2,500원, 20~45세 각 50명) 에이전트 실행.
