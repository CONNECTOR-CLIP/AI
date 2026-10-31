# 수정 가이드북

작성일 2026-10-31 · 기준: 스키마 0.2, 테스트 136개 통과

이 문서는 데모 이후에 무엇을, 어느 파일에서, 어떻게 고칠지 정리한다.
함수 이름과 파일 경로로 위치를 적었다. 줄 번호는 코드가 바뀌면 달라지므로 적지 않았다.

- 왜 이렇게 설계했는지: `docs/design_rationale.md`
- 결과물을 읽고 고치는 절차: `docs/human_review.md`
- 단계별 구현 기록: `docs/implementation_plan.md`

---

## 1. 현재 상태

| 항목 | 상태 |
|---|---|
| 1~6단계 (`run` 명령) | 동작함. 실제 LLM으로 **6번 아이디어에서만** 실행해 봄 |
| 7단계 평가 | 코드 있음. 시범 1회(6번)만 실행. **세 조건 비교 전체는 실행하지 않음** |
| 8단계 팀 CoT 흐름 연결 | 시작 전 |
| Docker 실행 | Dockerfile은 있으나, 개발 PC에서 Docker Desktop이 꺼져 있어 이 작업 중에 `docker build`를 확인하지 못함 |

마지막 실행(6번, 약 5분, $0.043)의 상태는 `needs_review`이고 major 지적 1건이 남아 있다.

**아직 확인하지 못한 것** (결과를 과신하지 말 것)

- 2, 3, 5, 7, 8번 아이디어는 실제로 돌려 보지 않았다. 프롬프트가 6번에 맞춰졌을 수 있다.
- 시범 평가에서 template이 pipeline보다 약간 높았다(4.68 대 4.03, 4.18 대 4.03). 그 뒤 pipeline을 고쳤지만 다시 비교하지 않았으므로, pipeline이 더 낫다는 근거는 현재 없다.
- 정답 예시 v2는 규칙 검사만 통과했고, 평가 판정기로 다시 채점하지 않았다.

---

## 2. 증상별 빠른 찾기

| 증상 | 먼저 볼 곳 |
|---|---|
| 내용이 이 아이디어에서만 틀림 | `out/<run_id>/ideaNN/plan.reviewed.json`을 직접 수정 (3절) |
| 같은 실수가 여러 아이디어에서 반복됨 | 아래 프롬프트 파일 |
| 문제·한계 서술이 이상함 | `prompts/problem.md`, `prompts/system.md` |
| 구성요소·데이터 서술이 이상함 | `prompts/method.md` |
| 실험·비교 대상·주장·신규성이 이상함 | `prompts/validation.md` |
| 판정기가 틀리게 감점하거나 문제를 놓침 | `prompts/judge.md` |
| "좋은 값" 기준 자체를 바꿈 | `docs/field_definitions.md` 표의 마지막 열 (작성기와 판정기에 함께 들어감) |
| 개요 문단이 이상함 | `prompts/write_plan.md` |
| 논문 제목·초록·개요·그림 계획이 이상함 | `prompts/write_skeleton.md` |
| 표·목록의 모양이나 목차를 바꿈 | `src/research_plan/write.py`의 `render_research_plan`, `render_paper_skeleton` + `validate.py`의 `PLAN_HEADINGS`, `SKELETON_HEADINGS` |
| 금지 표현을 추가함 | `src/research_plan/validate.py`의 `FORBIDDEN_PATTERNS` |
| 정상 약어가 "지어낸 이름"으로 경고됨 | `src/research_plan/verify.py`의 `COMMON_NAMES` |
| 기준 점수를 바꿈 | `src/research_plan/review.py`의 `PASS_SCORE` |
| 모델을 바꿈 | `.env`의 `RESEARCH_PLAN_MODEL`, `--model`, `--judge-model` |
| 입력 파일을 못 읽거나 짝이 안 맞음 | `src/research_plan/inputs.py`의 `load_run` |

### 고친 뒤 어디부터 다시 돌리나

| 고친 것 | 다시 실행 | 비용 (6번 기준 실측) |
|---|---|---|
| `plan.reviewed.json` | `run ... --from write` | 약 $0.005 |
| `write_plan.md`, `write_skeleton.md`, `write.py` | `run ... --from write` | 약 $0.005 |
| `judge.md`, `review.py` | `run ... --from review` | 약 $0.035 |
| `system.md`, `problem.md`, `method.md`, `validation.md`, `field_definitions.md`, `schemas.py` | `run ...` 또는 `--from extract` | 약 $0.04 |
| `evidence.py`, `inputs.py` | `run ...` | 약 $0.04 |
| `validate.py`, `verify.py` | `run ... --from verify` | 무료 |

- `--from review`보다 앞에서 시작하면 사람이 고친 `plan.reviewed.json`이 새로 만들어진다. 이전 파일은 `history/`에 남는다.
- 어떤 코드를 고쳐도 `python -m unittest discover -s tests`를 먼저 돌린다. 무료다.
- 프롬프트를 고치면 다른 곳에 부작용이 날 수 있다. 실제로 RAG 과장을 막는 규칙이 제안 방법의 인용 기능까지 빼 버린 적이 있다. 고친 뒤에는 아이디어를 2개 이상 돌려 본다.

---

## 3. 사람이 점검해야 할 부분

자동 검사를 통과해도 아래는 사람이 판단한다. 절차는 `docs/human_review.md`를 따른다.

### 모든 아이디어 공통

| 점검 | 볼 곳 | 이유 |
|---|---|---|
| 가장 가까운 선행연구를 직접 다시 검색 | 신규성 항목, 부록 | CoT5 검색은 범위가 제한되어 있다. **6번은 Trust-Align(arXiv 2409.11242)을 찾지 못했다** |
| 인용문 해석이 원문과 맞는지 | 한계(L), `evidence.json`의 `upstream_evidence` | 판정기도 틀릴 수 있다 |
| 핵심 용어가 정의되었는지 | 연구 질문, M의 데이터 구성 | 정의 없이는 라벨을 만들 수 없다 |
| 연구 질문이 측정 가능한 질문인지 | 1.1절 | "~확인할 수 있는가" 형태로 나오는 경향이 있다 |
| `[TBD]` 항목을 채울 수 있는지 | 문서 전체 | 근거가 없는 값은 일부러 비워 둔다. 6번은 33개 |
| "plan에 없는 이름" 경고 | `verify_report.json`의 `warnings` | 지어낸 모델·데이터셋일 수 있다 |
| 남은 지적 | `review.json` 마지막 회차, `new_findings` | `needs_review`면 반드시 읽는다 |

### 6번 아이디어에 현재 남은 문제

고칠 곳은 모두 `out/cot45_public_run_20261029_154552/idea06/plan.reviewed.json`이다. 고친 뒤 `check`로 연결을 확인하고 `--from write`로 다시 만든다.

| 위치 | 문제 | 고치는 방향 |
|---|---|---|
| `research_problem` | 미지원 질의의 정의가 없고 "확인할 수 있는가"로 끝남 | 예: "검색된 문서 집합에 정답을 뒷받침하는 문서가 없는 질의"로 정의하고 비교형 질문으로 다시 씀 |
| `validation_targets` V2와 `experimental_design` E2 | V2는 Self-RAG와 RAG 대비를 묻는데 E2의 비교 대상은 B2뿐 (남은 major) | V2의 질문을 B2 대비로 좁히거나 E2에 비교 대상을 추가 |
| `expected_novelty` | 차이 축이 "판단 이후 동작"뿐. 적용 단위(문장 조각 대 응답 전체)를 놓침. FineRef 항목은 맞는 실험이 없어 보완 때 빠짐 | Self-RAG 원문 Table 1의 IsSup 정의를 `existing_mechanism`에 적고 축을 검토. FineRef 비교를 유지하려면 그 비교 대상과 실험을 추가 |
| 신규성 전체 | Trust-Align과의 차이를 검토하지 않음 | 논문을 읽고 아이디어가 여전히 새로운지 판단. 겹치면 범위를 바꾸거나 다른 후보를 고름 |
| `baselines` | 번호가 B1, B2, B4 (B3 없음) | 번호를 고칠 때 E의 `baselines`, 문서의 참조도 함께 고침 |

Trust-Align은 현재 허용 목록 밖이라 plan에 그 번호를 쓰면 `check`에서 걸린다. 넣으려면 먼저 항목 B5를 처리하거나, `citation_whitelist`에 직접 추가한다.

### 팀에 전달할 것

| 내용 | 담당 코드 |
|---|---|
| CoT3·CoT4가 RAG를 "P1-style citation generation"이라 부름. CoT3의 gap 문장은 "provenance"라고 쓰므로 표현이 어긋남 | CoT3, CoT4 프롬프트 |
| CoT5가 6번의 근접 연구 Trust-Align을 찾지 못함. 벡터 인덱스 없음(`limited_candidates`) | CoT5 검색 |
| 웹 검색이 8건 중 7건 실패(시간 초과, HTTP 429) | CoT5 검색 |
| NOT_NOVEL 2건(1번, 4번)의 결과에 동등 판정 논문이 남아 있지 않아 어떤 논문과 겹치는지 알 수 없음 | CoT5 결과 저장 |

---

## 4. 실사용 수준으로 올리기 (우선순위 순)

### A. 먼저 할 일 (구조적 빈칸)

**A1. 연구 일정, 자원, 연구윤리, 기대효과·활용방안 추가**
- 문제: 일반적인 과제 계획서가 요구하는 항목이 없다. 마일스톤에도 날짜가 없다. 사람 평가가 있는데 IRB 필요 여부를 다루지 않는다.
- 고칠 곳
  1. `src/research_plan/schemas.py`: `FIELD_KEYS`, `_ITEM_SCHEMAS`, `FIELD_GROUPS`에 필드 추가, `SCHEMA_VERSION` 올림
  2. `docs/field_definitions.md`: 새 필드의 행 추가 (프롬프트에 자동으로 들어감)
  3. `prompts/validation.md`: 작성 요령 추가
  4. `src/research_plan/validate.py`: `PLAN_HEADINGS`에 제목 추가
  5. `src/research_plan/write.py`: `render_research_plan`에 출력 추가
  6. `templates/research_plan.md.tmpl`, `schema/plan.schema.json` 갱신, `examples/golden/make_golden_v2.py`에 값 추가
- 주의: 날짜와 예산은 근거 자료에 없다. 지어내지 않도록 사용자가 입력하게 하거나 `[TBD]`로 둔다.

**A2. 핵심 용어의 조작적 정의를 필수로**
- 문제: 6번에서 "미지원 질의"의 정의가 `[TBD]`로 미뤄졌다.
- 고칠 곳: `schemas.py`에 `key_definitions` 필드 추가(`problem` 묶음), `validate.py`의 `validate_plan`에서 비어 있으면 오류, `prompts/problem.md`에 작성 요령, `prompts/judge.md`에 확인 항목.
- 확인: 2개 이상의 아이디어에서 라벨 기준으로 쓸 수 있는 정의가 나오는지 본다.

**A3. 연구 질문 형식**
- 문제: "~확인할 수 있는가"처럼 가능 여부를 묻는다.
- 고칠 곳: `prompts/problem.md`의 `research_problem` 항목에 "비교 대상과 측정 대상이 드러나는 질문으로 쓴다" 추가, `prompts/judge.md`의 `claim_quality`에 연구 질문 포함.

**A4. 신규성의 핵심 차이를 놓치지 않게**
- 문제: 기존 장치와 차이 축을 코드가 확인하지만 내용이 맞는지는 판정기에 달려 있다. 판정기가 적용 단위 차이를 놓쳤다.
- 고칠 곳: `prompts/validation.md`의 `expected_novelty`, `prompts/judge.md`의 `closest_work_difference`.
- 한계: 근거 자료에 IsSup의 단위 정보가 없으면 프롬프트로 해결되지 않는다. B4의 원문 근거 확장과 함께 해야 효과가 있다.

**A5. 번호 재정렬**
- 문제: 보완 때 항목이 지워지면 번호가 빈다(B1, B2, B4).
- 고칠 곳: `src/research_plan/extract.py`의 `extract_plan`이 끝난 뒤 또는 `review.py`의 `review_plan` 끝에서 번호를 다시 매기고 모든 참조를 함께 바꾸는 함수 추가. 프롬프트로는 보장되지 않는다.

**A6. 남은 major를 고치는 기회 늘리기**
- 문제: 보완이 1회뿐이라 새로 생긴 불일치(V2-E2)가 남는다.
- 고칠 곳: `review.py`의 `review_plan`. 회수를 늘리면 비용이 늘고 지적이 끝없이 바뀔 수 있으므로, major가 줄어드는 동안만 최대 2회로 제한하는 방식을 권한다.
- 대안: 잠근 필드와 고친 필드의 불일치가 원인이므로, 지적받은 실험과 연결된 V를 함께 고치도록 `fix_targets`를 넓힌다.

### B. 그다음 (근거 자료 확장)

**B1. 다른 아이디어로 검증** (가장 먼저 해 볼 만함)
- `run --idea 2`, `3`, `5`, `7`, `8`을 돌리고 같은 지적이 반복되는지 본다. 합계 약 $0.2.
- 반복되는 것은 프롬프트로, 한 번만 나오는 것은 plan에서 고친다.

**B2. 데이터셋 후보 제안**
- 문제: 데이터셋 이름이 전부 `[TBD]`다. 근거 자료(CoT4)에 없고, 지어내기를 금지했기 때문이다.
- 고치는 방법: 1단계와 2단계 사이에 후보를 찾는 단계를 추가한다. 예를 들어 시드 논문과 관련 논문 원문에서 데이터셋 이름을 뽑아 근거 경로와 함께 evidence에 넣는다.
- 고칠 곳: `src/research_plan/evidence.py`에 항목 추가, `prompts/method.md`의 `data_and_subjects`, `verify.py`의 이름 검사는 evidence와 plan을 기준으로 이미 동작.

**B3. 관련 연구 확장**
- 문제: 인용이 3편뿐이다. 허용 목록이 시드 논문과 CoT5 후보 10편으로 한정되고, 그중 일부만 쓴다.
- 고치는 방법: arXiv 등에서 추가 후보를 검색하는 단계, 또는 사용자가 논문 번호를 넣는 `--extra-papers` 옵션.
- 고칠 곳: `evidence.py`의 `_whitelist`, `cli.py`의 `run`·`select` 인자, `verify.py`의 arXiv 확인은 그대로 재사용.
- 주의: 제목만으로는 내용을 서술할 근거가 없다. 초록까지 evidence에 넣어야 한다.

**B4. 원문 근거 확장**
- 문제: `seed_papers`는 CoT1 요약이다. IsSup의 정의처럼 신규성 판단에 필요한 세부가 없다.
- 고칠 곳: `evidence.py`의 `_seed_papers`. 시드 논문 원문에서 관련 부분을 찾아 넣는 기능 추가.

**B5. 사람이 찾은 근접 연구를 넣는 경로**
- 문제: Trust-Align처럼 사람이 찾은 논문을 넣는 정식 경로가 없다.
- 고칠 곳: B3의 `--extra-papers`로 해결하거나, `plan.reviewed.json`의 `citation_whitelist`에 `{"arxiv_id", "title", "role"}`을 추가한다. `schemas.py`의 `role` enum에 `human_added`를 추가해야 스키마와 맞는다.

**B6. 문장 품질**
- 문제: "보류 질의"(held-out), "성찰 토큰" 같은 번역투와 긴 문장.
- 고칠 곳: `prompts/system.md` 규칙 6에 용어표 추가(예: held-out은 원어 유지). `prompts/write_plan.md`.

**B7. 논문 이름**
- 문제: 실행에 따라 긴 전체 제목으로 쓰이기도 한다.
- 고칠 곳: `evidence.py`의 `_seed_papers`에 짧은 이름 필드 추가, `prompts/system.md`에 규칙 추가.

### C. 평가와 신뢰성

**C1. 비교 평가 전체 실행**
- `python -m research_plan evaluate --run-dir data/<run_id>` (시범 기준 추정 약 $0.75, 약 2시간)
- 이유: pipeline 비용이 template의 약 10배인데 더 낫다는 근거가 아직 없다. 교수님이 물으실 가능성이 크다.
- 주의: 표본은 6개다. 차이가 작으면 결론을 내리지 않는다.

**C2. 사람 평가**
- `evaluate`가 만드는 `human/ideaNN_sheet.md`로 눈가림 평가를 한다. 평가 전에 `_key.json`을 열지 않는다. LLM 판정의 최종 기준은 사람 판단이다.

**C3. 정답 예시 검토**
- 문제: `examples/golden/`의 v1, v2 모두 Claude가 썼다. 사람이 검토하기 전에는 정답이 아니라 참고 답안이다.
- 고칠 곳: 내용은 `examples/golden/make_golden_v2.py`에서 고치고 다시 실행한다. 검토 후 `meta.generated_by`를 바꾼다.

**C4. 판정 신뢰성**

| 문제 | 고칠 곳 | 방법 |
|---|---|---|
| 작성과 판정이 같은 계열 모델 | `review.py`의 `DEFAULT_JUDGE_MODEL` | 다른 회사 모델로 바꾸고 결과 비교 |
| 1회차 판정의 편차를 줄이지 못함 | `review.py`의 `judge` | 여러 번 판정해 합치기 (비용 증가) |
| 루브릭이 공통 5단계 + 기준 한 줄뿐 | `prompts/judge.md`, `docs/field_definitions.md` | 점수별 설명이나 예/아니오 체크리스트 |

**C5. 검사의 약한 부분**

| 문제 | 위치 | 영향 |
|---|---|---|
| 숫자 검사가 plan의 근거 경로 숫자도 허용함 (`candidates[3]`의 3 등) | `verify.py`의 `_plan_text`, `check_numbers` | 작은 숫자를 지어내면 통과할 수 있음 |
| 이름 검사는 경고만 하고 흔한 약어 목록은 손으로 관리함 | `verify.py`의 `COMMON_NAMES`, `_is_name` | 지어낸 이름이 자동으로 막히지 않음 |
| 세부 필드 경로의 실재를 확인하지 않음 (`candidates[0].없는필드`도 통과) | `extract.py`의 `_source_exists` | 근거 경로를 지어낼 여지가 조금 있음 |
| 근거 경로가 있어도 내용이 그 근거와 맞는지는 코드로 알 수 없음 | 판정기(`source_honesty`)에 의존 | 사람 점검 필요 |
| CoT3의 `Pk:Lx`를 CoT2 후보의 순번으로 푸는 방식은 내보낸 CoT2 파일이 CoT3가 쓴 목록과 같다고 가정함 | `evidence.py`의 `_upstream` | 6번은 인용문이 일치함을 확인. 다른 실행에서는 어긋날 수 있음 |
| arXiv 캐시에 만료가 없음 | `data/arxiv_cache.json`, `verify.py`의 `ArxivLookup` | 오래되면 파일을 지우고 다시 확인 |

### D. 운영과 연결

**D1. 8단계: 팀 CoT 흐름에 연결**
- 문제: 지금은 `examples_run_manifest.json`과 `examples_upstream_manifest.json`이 있는 공개 실행 폴더 구조만 읽는다. `run_cot4_then_cot5.py`의 새 실행 결과는 그 구조가 아니다.
- 고칠 곳: `inputs.py`의 `load_run`에 팀의 실제 출력 형식 지원 추가, 또는 runner가 같은 구조로 저장하도록 수정. 팀과 합의 필요. CoT5 결과에서 후보를 고르는 화면이 필요한지도 정한다.

**D2. 실행 기록 보강**
- 문제: `run_manifest.json`의 `models`에 옵션을 주지 않으면 "기본값"으로만 적힌다. 실제 모델 이름은 단계별 로그에만 있다. temperature를 고정하지 않아 같은 입력에도 결과가 달라진다.
- 고칠 곳: `pipeline.py`의 `run_pipeline`에서 manifest의 `models`, `provider.py`의 `OpenRouterProvider.evaluate`의 요청 본문.

**D3. 비용 안전장치**
- 문제: 재시도 횟수만 제한하고 금액 상한이 없다.
- 고칠 곳: `provider.py`에 누적 비용 확인, `cli.py`에 `--max-cost`.

**D4. 정리**

| 항목 | 위치 |
|---|---|
| Docker 동작 확인 (`docker build`, `docker run`) | `Dockerfile` |
| `history/` 백업이 계속 쌓임 | `pipeline.py`의 `backup_outputs` |
| 출력 언어가 고정됨 (계획서 한국어, 논문 틀 영어) | `prompts/system.md`, `prompts/write_*.md` |
| 폴더 이름 오타 `Reserch_Plen` | 폴더 이름과 README, 문서의 경로. 코드는 폴더 이름에 의존하지 않음 |
| 스키마 0.1로 만든 plan은 읽을 수 없음 | extract부터 다시 실행 |

---

## 5. 권장 순서

1. **B1**: 다른 아이디어 돌려 보기. 진짜 반복되는 문제를 먼저 찾는다.
2. **A2, A3, A5, A6**: 작은 수정으로 효과가 큰 항목.
3. **A1**: 빠진 항목 추가. 스키마가 바뀌므로 한 번에 한다.
4. **B2, B3, B4, B5**: 근거 자료 확장. 데이터셋과 관련 연구의 빈칸은 여기서 줄어든다.
5. **C1, C2, C3**: 고친 결과를 평가한다. 발표 전에 근거가 필요하면 이 순서를 앞당긴다.
6. **D1**: 팀 흐름에 연결한다.
