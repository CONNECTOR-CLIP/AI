# CoT4: 연구 아이디어에 필요한 자원 안내

CoT4는 제안을 실행하기 위해 필요한 자원과 준비사항을 정리한다. 사용자의 예산·장비·인력은 상황마다 다르므로 AI가 `FEASIBLE`/`QUESTIONABLE`/`INFEASIBLE`로 분류하거나 실행 여부를 결정하지 않는다. CoT5는 별도로 문헌 기반 신규성을 검사한다.

## 처리 흐름

1. 아이디어에서 계산·데이터 요구사항, 구현 단계, 외부 의존성, 불명확한 단계를 추출한다.
2. 추출 결과와 입력된 제약 조건을 참고해 필요한 자원과 확인할 미지수를 안내한다.
3. 사용자가 안내 내용을 자신의 자원·일정과 대조해 실행 계획을 결정한다.

두 단계 모두 구조화된 JSON을 생성한다. CoT4는 실제 자원 보유 여부를 조사하지 않으며, 근거 없는 수량 추정도 요청하지 않는다. 입력에 수량을 정할 근거가 없으면 무엇이 그 수량을 결정하는지 설명한다. 실제 영어 프롬프트와 JSON Schema는 각각 `src/cot4/pipeline.py`, `src/cot4/schemas.py`에 있다. [한국어 프롬프트 해설](KOREA_README.md)도 참고할 수 있다.

## 입력과 출력

단일 아이디어는 제목·문제·제안 방법을 입력한다. 평가 계획과 제약 조건은 선택 사항이다. 기존 예제 형식은 `examples/idea.json`에 있다. `constraints`에는 `compute_budget`, `data_availability`, `timeline`, `team_skills`를 지정할 수 있다. 비어 있는 값은 자원을 무제한으로 보유한다는 뜻이 아니다. CoT4는 확인이 필요한 항목을 `unknowns_to_confirm`에 남긴다.

첫 번째 단계의 `requirements`에는 다음 필드가 있다.

| 필드 | 내용 |
|---|---|
| `compute_requirements` | 계산 자원·인프라 요구사항 |
| `data_requirements` | 데이터 출처·규모·수집 방식 |
| `implementation_steps` | 구현에 필요한 단계 |
| `external_dependencies` | 외부 도구·API·공개되지 않은 구성요소 |
| `vague_or_unspecified_steps` | 구체화가 필요한 단계 |

최종 결과의 `resource_guidance`에는 아래 필드가 있다.

| 필드 | 내용·형식 |
|---|---|
| `compute_resources` | 필요한 계산 자원·인프라 설명(문자열) |
| `data_resources` | 필요한 데이터 설명(문자열) |
| `tools_and_dependencies` | 도구·외부 의존성 목록 |
| `team_skills` | 필요한 팀 역량 목록 |
| `time_and_effort` | 시간·작업량 설명(문자열) |
| `prerequisites` | 선행 준비사항 목록 |
| `unknowns_to_confirm` | 계획 전에 사용자가 확인할 사항 목록 |
| `required_performance_conditions` | 입력에 명시된 필수 성능 한계. 없으면 빈 목록 |
| `proposed_performance_targets` | 희망 성능·개선 목표. 필수 조건으로 취급하지 않음 |

최상위 결과는 `idea_title`, `requirements`, `resource_guidance`, `checked_at`으로 구성된다. `classification`이나 `confidence` 같은 실현가능성 판정 필드는 없다.

## 실행

저장소 루트에서 단일 아이디어 또는 `future_work_proposals` 배열이 있는 Future Work JSON을 입력할 수 있다. 여러 제안의 결과는 입력 순서를 유지한 `{"results": [...]}` 형태로 출력된다. 공통 제약은 입력 JSON의 최상위 `constraints`에 지정할 수 있다.

```powershell
python CoT4.py CoT4\examples\idea.json
python CoT4.py D:\path\to\future_work_result.json
```

패키지를 설치했다면 `CoT4/` 디렉터리에서 `cot4 examples\idea.json` 명령도 사용할 수 있다. 실제 모델 호출에는 `OPENAI_API_KEY`와 해당 모델에 대한 접근 권한이 필요하다. 로컬 문헌 DB는 필요하지 않다.

### CoT4 다음에 CoT5 실행

```powershell
python run_cot4_then_cot5.py D:\path\to\future_work_result.json `
  --cot5-config CoT5\config.yml > downstream_results.json
```

연결 실행기는 모든 CoT4 자원 안내가 생성된 뒤 CoT5를 시작한다. CoT4 결과를 자원 보유 여부에 따라 걸러내지 않는다. CoT4 처리 중 오류가 발생하면 CoT5를 건너뛰고 오류를 보고한다. CoT5 실행에는 별도의 문헌 DB와 설정이 필요하다.

## 근거와 한계

이 단계의 점검 항목은 Si et al.의 연구 아이디어 평가에서 지적된 계산 자원, 데이터 수집, 구현 명세 문제와 *The AI Scientist*의 방법론적 엄밀성 관점을 참고한다. SoundnessBench가 보고한 모델의 낙관 편향도, 모델 판정 대신 사람이 확인할 자원 목록을 제공하는 이유 중 하나다. 이러한 연구는 특정 사용자가 아이디어를 실행할 수 있는지 자동으로 판정하는 근거가 아니다.

출력은 입력에 기술된 요구사항과 제약에 의존한다. 빠진 정보나 잘못 추출된 요구사항은 안내에도 영향을 준다. 사용자에게 실제로 필요한 자원과 확보 가능 여부는 사람이 확인해야 한다.
예를 들어 `10ms 미만`이 입력에 없다면 필수 CPU 성능으로 쓰지 않는다. 실시간화는 목표로 남기고 구체적인 지연시간 기준은 확인할 사항으로 제시한다.

API 키 없이 실행할 수 있는 단위 테스트는 `CoT4/tests/`에 있다. 실행에는 `pytest` 설치가 필요하다.
