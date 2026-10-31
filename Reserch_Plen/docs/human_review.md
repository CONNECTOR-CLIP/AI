# 사람이 확인하고 고치는 방법

자동 단계(2단계 작성, 3단계 심사)가 pass를 내도 **최종 판단은 사람이 한다.**
pass는 "판정기 기준을 넘었다"는 뜻이지 연구계획이 맞다는 보증이 아니다.

## 1. 어떤 파일을 보나

아이디어 하나의 결과는 `out/<run_id>/idea<NN>/` 폴더에 모인다.

### 읽는 파일 (결과물)

| 파일 | 언제 보나 | 무엇을 보나 |
|---|---|---|
| `research_plan.md` | **가장 먼저** | 연구계획서 전체. 4단계 결과라 사람이 읽기 가장 쉽다 |
| `paper_skeleton.md` | 계획서를 본 뒤 | 제목 후보, 구조화 초록, 장별 개요 |
| `review.json` | 계획서에서 이상한 곳을 찾았을 때 | 판정기의 필드별 점수와 이유. 2회차의 `new_findings`(사람 확인용 새 지적), minor 지적 |
| `evidence.json` | 인용이나 근거가 의심될 때 | 원문 인용문(`upstream_evidence`), CoT5 관련 논문의 차이점(`novelty.related`). plan의 `source` 경로가 여기를 가리킨다 |
| `plan.reviewed.json` | 고칠 때 | 연구계획의 원본 데이터. 문서 두 개는 여기서 만들어진다 |
| `run_manifest.json` | 언제 무엇으로 만들었는지 궁금할 때 | 단계별 상태·비용·시간, 사용한 모델과 프롬프트 해시 |
| `verify_report.json` | 문서를 만든 뒤 | 5단계 검사 결과. `warnings`의 "plan에 없는 이름"은 지어낸 모델·데이터셋일 수 있으니 직접 확인한다 |
| `extract_log.json`, `write_log.json` | 비용이나 재시도가 궁금할 때 | 라운드별 오류, 토큰 사용량 |

### 고치는 파일

파일은 두 종류다.

- **plan 파일 (`plan.reviewed.json`)**: 아이디어 하나(예: 6번)의 연구계획 내용이 담긴 데이터. 고치면 **그 아이디어에만** 반영된다.
- **프롬프트 파일 (`prompts/*.md`)**: LLM에게 주는 작성·심사 지침. 모든 아이디어가 같은 지침을 쓰므로, 고치면 **앞으로 돌리는 모든 아이디어**에 반영된다.

그래서 문제를 발견하면 먼저 "이 문제가 이 아이디어에만 있는가, 다른 아이디어를 돌려도 또 나올 문제인가"를 판단한다.

- 6번의 V1과 V3가 겹친다 → 6번만의 내용 문제 → plan 파일을 고친다.
- 2번, 5번, 6번을 돌려 보니 매번 구성요소에 평가 단계가 들어간다 → LLM의 작성 습관 문제 → 프롬프트를 고친다. plan만 고치면 다음 아이디어에서 또 나온다.

아래 표는 왼쪽의 문제가 생기면 오른쪽 파일을 고친다는 뜻이다.

| 문제 종류 | 고칠 파일 | 예 |
|---|---|---|
| 이번 아이디어의 내용 | `plan.reviewed.json` (직접 수정) | 연구 문제 문장을 다듬기, 중복된 V3 지우기, 미지원 질의의 정의 넣기 |
| 여러 아이디어에서 반복되는 작성 습관 | `prompts/system.md`, `problem.md`, `method.md`, `validation.md` (작성기) | 매번 구성요소에 평가 단계를 넣음, 매번 비교 대상이 모호함 |
| 판정기가 잘못 판단함 | `prompts/judge.md` (판정기) | 맞는 내용을 감점함, 중요한 문제를 놓침 |
| "좋은 값"의 기준 자체를 바꾸고 싶음 | `docs/field_definitions.md` 표의 마지막 열 | 작성기와 판정기 프롬프트에 그대로 들어간다 |
| 문서 문장이나 논문 틀 | `prompts/write_plan.md`, `prompts/write_skeleton.md` (4단계) | 개요가 너무 김, 제목 후보 형식 |

### 왜 md가 아니라 json을 고치나

```
plan.reviewed.json  ──(4단계 write)──►  research_plan.md, paper_skeleton.md
   원본 데이터                              원본에서 찍어 낸 문서
```

- `research_plan.md`는 `write` 명령이 `plan.reviewed.json`을 읽어 **매번 새로 만드는** 파일이다. 엑셀 데이터로 보고서를 출력하는 것과 같다. `write`를 다시 돌리면 같은 이름으로 새로 쓰므로, md에 손으로 고친 내용은 사라진다.
- 반대로 `plan.reviewed.json`은 어느 명령도 덮어쓰지 않는다(3단계 `review`를 다시 돌릴 때만 새로 만들어진다). 그리고 `check`로 연결이 맞는지 검사할 수 있다. md를 고치면 이런 검사도 받지 못한다.
- 따라서 **내용은 json에서 고치고 `write`로 md를 다시 만든다.** md를 손으로 다듬는 것은 모든 단계가 끝난 뒤, 다른 이름으로 복사한 파일에서 한다(예: `research_plan.final.md`).

## 2. 확인 순서

1. **`research_plan.md`를 처음부터 읽는다.** 다음을 확인한다.
   - 연구 질문이 측정 가능한 질문인가 ("~할 수 있는가"처럼 가능 여부만 묻지 않는가)
   - 핵심 용어(예: "미지원 질의")가 정의되어 있는가
   - 한계(L)가 원문 인용을 넘어서 말하지 않는가 → 의심되면 `evidence.json`의 `upstream_evidence`와 대조
   - 가장 가까운 선행연구와의 차이가 구체적인가
   - **가장 가까운 선행연구를 직접 한 번 더 검색했는가.** CoT5의 신규성 검색은 범위가 제한되어 있다. 6번 아이디어의 경우 CoT5가 Trust-Align(arXiv 2409.11242, RAG에서 근거 부족 시 거절과 인용을 함께 다룸)을 찾지 못했다. 신규성 항목의 "기존 장치 · 차이 · 검증 실험"이 그 논문에도 성립하는지 확인한다
   - 검증 대상(V)끼리 겹치지 않는가, 실험(E)마다 비교 대상이 맞는가
   - 과잉 개입(부작용) 실험이 있는가
2. **`review.json`의 마지막 회차를 본다.** 남은 minor 지적과 `new_findings`를 읽고, 동의하는 것만 고친다.
3. **고칠지 정한다.** 위 표에 따라 `plan.reviewed.json`을 고치거나 프롬프트를 고친다.
4. **`plan.reviewed.json`을 고쳤다면 규칙 검사를 한다** (LLM 호출 없음, 무료).
   ```
   PYTHONPATH=src python3 -m research_plan check --plan out/<run_id>/idea06/plan.reviewed.json
   ```
   `[OK]`가 나와야 한다. 예를 들어 V3를 지웠는데 E3가 여전히 V3를 가리키면 여기서 걸린다.
5. **문서를 다시 만든다.** 4단계(write)와 5단계(verify)만 다시 돈다. 이전 문서는 `history/`에 자동으로 백업된다.
   ```
   PYTHONPATH=src python3 -m research_plan run --run-dir data/<run_id> --idea 6 --from write
   ```
   `--from review`나 그보다 앞에서 시작하면 `plan.reviewed.json`이 새로 만들어져 **사람이 고친 내용이 사라진다**(history에는 남는다). 실행 전에 경고가 나온다.
6. **프롬프트를 고쳤다면** 그 프롬프트가 쓰이는 단계부터 다시 돌린다. 작성기 프롬프트는 `--from extract`, 판정기 프롬프트는 `--from review`, 4단계 프롬프트는 `--from write`.

## 3. plan.reviewed.json을 고칠 때 지킬 것

- 각 필드는 `{"value": ..., "source": [...], "inferred": ...}` 모양이다. 사람이 새로 쓴 내용이면 `"inferred": true`로 바꾼다.
- 목록 항목의 ID(L1, M1, V1, E1 …)를 지우거나 바꾸면, 그 ID를 참조하는 곳(`addresses`, `components`, `validates`, `baselines`, `validated_by`)도 함께 고친다. `check`가 끊어진 곳을 알려준다.
- 논문 인용은 `citation_whitelist`에 있는 arXiv ID만 쓴다.
- 결과를 단정하는 표현("입증했다", "향상되었다", "outperforms")을 쓰지 않는다. 4단계에서 문서 검사에 걸린다.
