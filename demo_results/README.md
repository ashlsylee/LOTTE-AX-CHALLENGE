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
