# 구현 계획서: 연구계획서 및 논문의 틀 생성 기능

작성일 2026-10-30 · 기준 데이터 `cot45_public_run_20261029_154552` (Category 브랜치 `3255acb`, 복사본은 `data/` 폴더)

## 1. 이 기능이 하는 일

```
CoT3 (Future Work 후보 N개)
   ↓
CoT4 (후보별 필요 자원)  →  CoT5 (후보별 신규성 판정)
   ↓
[사용자] NOVEL 후보 목록을 보고 1개 선택      ← 이 기능의 시작점
   ↓
이 기능: 선택한 1개에 대해
   plan.json → research_plan.md (연구계획서) + paper_skeleton.md (논문의 틀)
```

- 실험 결과가 없으므로 **논문 초안이 아니라 논문의 틀**을 만든다. 결과 자리는 `[RESULT: ...]` 자리표시자로 남긴다.
- 한 번에 후보 1개를 처리한다. 여러 개를 처리할 때는 같은 작업을 반복한다.

## 2. 입력: 무엇이 왜 필요한가

| 입력 | 실제 파일 (Category 브랜치) | 이 기능에서 쓰는 내용 | 없으면 |
|---|---|---|---|
| ① Future Work 결과 (CoT3 후보를 변환한 CoT4·CoT5 입력) | `New_Future-Work-Researcher/FutureWork/examples/result.json` (CRLF 줄바꿈 기준 `input_sha256 = 76f8c2fa…`와 일치) | `background_and_gap`(문제·배경), `proposed_direction`(제안 방법), `expected_contribution`, `reference_papers` | 문제 정의와 제안 방법을 추측해야 함 |
| ② CoT4 결과 | `New_Future-Work-Researcher/CoT4/examples/result.json` | `requirements.*`(데이터, 구현 단계, 모호한 단계), `resource_guidance.*` | 데이터·자원·위험 요소가 빈약해짐 |
| ③ CoT5 결과 | `New_Future-Work-Researcher/CoT5/examples/result.json` | `classification`, `review`, `overlaps.paper.candidates[]`(겹치는 논문 10편과 목적·방법·평가 겹침, 결정적 차이) | 관련 연구, baseline, 차별점 근거가 없어짐 |
| ④ 실행 기록 | `New_Future-Work-Researcher/examples_run_manifest.json` | 다른 파일의 위치, `run_id`, `input_sha256`, `source_status_counts` | 진입점이므로 필수 |
| ⑤ CoT1~CoT3 결과, 상류 기록 | `CoT1/`, `CoT2/`, `CoT3/examples/`, `examples_upstream_manifest.json` | CoT3 근거 ID(`P2:L1` 등)를 원 논문 인용문으로 풀기, judge 판정, P1·P2 순서 | 원 논문 인용문 없이 진행 (경고) |

### ①이 꼭 필요한 이유

제목이 잘리는 것은 문제의 일부일 뿐이다. 진짜 문제는 **아이디어 본문이 ①에만 있다**는 점이다.

- CoT4는 `proposed_direction`의 첫 줄만 제목으로 쓰고, 120자에서 자른다. CoT5는 70자에서 자른다.
- CoT4·CoT5 결과에는 `background_and_gap`, `proposed_direction` 전문이 저장되지 않는다.
- 연구계획서의 1절(문제 정의, 제안 방법)은 이 두 필드가 근거다. ②·③만으로 쓰면 이 부분이 전부 `inferred: true`가 된다.

### 파일을 짝짓는 방법

- 제목은 잘려 있어 키로 쓸 수 없다. **배열 순서(1부터 시작하는 `candidate_index`)** 로 짝짓는다. CoT4 어댑터가 `enumerate(..., 1)`로 번호를 매기므로 이에 맞춘다.
- 짝이 맞는지 확인하는 장치를 둔다.
  1. ①의 SHA-256이 ④의 `input_sha256`과 같은지 확인한다. 원본·LF·CRLF 세 가지로 계산하며, 달라도 경고만 낸다.
  2. ①, ②, ③, ④ `input_candidate_count`의 후보 수가 같은지 확인한다.
  3. CoT4·CoT5 제목이 각각 ① `proposed_direction` 첫 줄의 앞부분인지 확인한다.
  4. CoT3 후보는 상류 기록의 `candidate_mapping`(없으면 ① `novelty_note`의 `CoT3 C7`)으로 찾고, `proposed_direction`이 ①과 같은지 확인한다.
  - 2~4가 어긋나면 진행을 멈춘다.

## 3. 현재 진행 상황

| 단계 | 내용 | 상태 |
|---|---|---|
| 0 | 출력 명세, 필드 정의서, 스키마, 템플릿, 정답 예시 1건, 검증기, 테스트 21개 | ✅ 완료 |
| 1 | 입력 어댑터와 후보 선택, 테스트 26개 | ✅ 완료 (2026-10-30) |
| 2 | plan.json 생성, 테스트 20개 | ✅ 완료 (2026-10-30, 6번 후보 실제 실행 2회) |
| 3 | 심사(LLM 판정기)와 1회 보완 | ✅ 완료 (3차 실행: extract 1회, review pass, 평균 4.24, major 0) |
| 4 | 연구계획서와 논문의 틀 작성 | ✅ 완료 (2회 실행, 제목·초록 표현 개선) |
| 5 | 인용·날조 검사 (LLM 없음) | ✅ 완료 (6번 실행: 인용 3/3 확인, 오류 0) |
| 6 | 한 줄 실행과 실행 기록 | ✅ 완료 (out_test 전체 실행 2회 통과) |
| 7 | 평가 (free·template·pipeline 비교) | 🔧 코드 완료, 시범 1회만 실행 (전체 비교는 데모 범위에서 제외) |
| 8 | 아래 4절 참고 | 시작 전 |

0단계에서 만든 것은 "판정 기준", 1단계는 "자료 정리", 2단계는 "LLM이 뼈대 데이터를 쓰고 검사기로 고치게 하는 반복"이다.

## 4. 단계별 구현 계획

각 단계는 **입력 → 출력 → 만들 파일 → 완료 기준** 순서로 적는다.

### 1단계. 입력 어댑터와 후보 선택 (LLM 없음) ✅

- **입력**: `--run-dir` 하나. `examples_run_manifest.json`이 있는 폴더이며, 나머지 파일 위치는 manifest에서 읽는다.
- **출력**: `out/<run_id>/idea<NN>/evidence.json` — 선택한 후보의 모든 근거를 한곳에 모은 파일. 새로 만든 내용은 없고, 항목마다 근거 경로(`source`)가 붙는다.

  | 키 | 내용 | 근거 경로 예 |
  |---|---|---|
  | `meta` | 번호, FutureWork ID, CoT3 ID, 전체 제목, CoT5 판정, 입력 파일 해시 | |
  | `papers` | P1, P2와 arXiv ID | `manifest.upstream.papers[0]` |
  | `seed_papers` | 시드 논문마다 원 논문에서 정리한 연구 문제와 하위 목표(달성 여부 포함). 논문이 하는 일을 서술하는 기준 | `cot1.P1.subgoals[1]` |
  | `idea` | 문제·배경, 제안 방향, 참고 논문, CoT3 rationale | `future_work.background_and_gap` |
  | `upstream_evidence` | CoT3 근거 ID를 풀어 쓴 원 논문 인용문과 subgoal | `cot2.P2.candidates[0]` |
  | `judge` | CoT3 judge 판정과 하위 주장별 인용 | `cot3.judge_subclaims[0]` |
  | `resources` | CoT4 요구사항과 자원 안내 (항목 단위) | `cot4.requirements.implementation_steps[2]` |
  | `novelty` | 판정, 이유, 리뷰, 소스별 검색 상태, 관련 논문·특허와 차이점 | `cot5.paper.candidates[3]` |
  | `citation_whitelist` | 시드 논문 + CoT5 논문 후보 (plan.json과 같은 형식) | |
  | `warnings` | 검색 실패, 판정 약함, 해시 불일치 등 | |

- **만든 파일**
  - `src/research_plan/inputs.py`: 실행 폴더를 읽고 2절의 확인을 거쳐 후보 목록을 만든다.
  - `src/research_plan/evidence.py`: 선택한 후보 1개의 `evidence.json` 내용을 만든다.
  - `src/research_plan/cli.py`, `__main__.py`: 아래 두 명령을 제공한다.
    ```
    python -m research_plan list   --run-dir data/cot45_public_run_20261029_154552
    python -m research_plan select --run-dir data/cot45_public_run_20261029_154552 --idea 6
    ```
  - `tests/test_inputs.py`: 실제 데이터 검사와 일부러 망가뜨린 입력 검사 26개.
- **정책**
  - NOT_NOVEL 후보는 `--allow-not-novel` 없이는 선택할 수 없다(종료 코드 2).
  - CoT1~CoT3가 없으면 경고를 내고 `upstream_evidence`를 비운 채 진행한다.
  - CoT5 웹·특허 검색 실패와 `limited_candidates` 범위는 warnings와 `novelty.search_status`에 그대로 남긴다. 2단계에서 부록(신규성 검증 범위)에 쓴다.
- **실제 데이터에서 확인한 것**
  - 8개 후보가 모두 짝지어지고(C2~C9 → 1~8), FutureWork 해시가 manifest와 일치한다.
  - 6번(C7)의 근거 `P2:L1`이 Self-RAG 원문 인용문 "we do not consider the instances where … no support"로 풀린다.
  - NOT_NOVEL 2건(1번, 4번)은 CoT5 결과에 동등 논문이 남아 있지 않다. 어떤 논문과 겹치는지 이 데이터로는 알 수 없다(경고로 표시).
  - FutureWork의 `expected_contribution` 칸에는 CoT3 `rationale`이 그대로 들어가 있다. 실제 기여 서술이 아니므로 2단계 프롬프트에서 근거 설명으로만 쓰게 한다.

### 2단계. 1차 추출: plan.json 생성 (LLM) 🔧

- **입력**: `evidence.json` (1단계 결과)
- **출력**: 같은 폴더에 `plan.json`(검사 통과) 또는 `plan.draft.json`(최대 횟수 안에 통과 못 함), 그리고 `extract_log.json`(라운드별 오류, 프롬프트 해시, 호출별 토큰 사용량과 소요 시간)
- **모델**: OpenRouter `openai/gpt-6-luna` (CoT5와 같은 모델, JSON Schema strict 출력 지원). `--model` 또는 `.env`의 `RESEARCH_PLAN_MODEL`로 바꾼다.
- **만든 파일**
  - `src/research_plan/provider.py`: CoT4의 `LLMProvider`와 같은 `evaluate(instructions, document, schema, schema_name)` 형태. OpenRouter를 표준 라이브러리(urllib)로 호출하고, 429·5xx는 최대 3번 재시도한다. 키는 환경변수 또는 `.env`에서 읽는다.
  - `src/research_plan/schemas.py`: 필드 묶음(`FIELD_GROUPS`)과 strict 모드용 묶음 스키마(`strict_group_schema`)
  - `prompts/system.md`(공통 규칙), `prompts/problem.md`, `method.md`, `validation.md`(묶음별 작성 요령과 형식 예시)
  - `src/research_plan/extract.py`: 묶음 순서대로 호출 → 합치기 → 검사 → 오류가 난 묶음만 다시 쓰기
  - `tests/test_extract.py`: 가짜 모델로 정상 통과, 오류 묶음만 재작성, 지어낸 근거 경로 거부, 최대 횟수 초과, strict 스키마 형식 등을 검사한다.
- **필드 묶음**
  1. problem: 연구 주제, 배경, 문제, 기존 방법의 한계(L)
  2. method: 목표, 제안 방법, 구성요소(M), 구성요소 관계, 데이터 — problem 결과를 받아 L을 참조
  3. validation: baseline(B), 검증 대상(V), 실험(E), 주장(C), 신규성, 기여, 위험(R), 마일스톤(S) — 앞 두 묶음을 받아 L·M을 참조
  - 신규성 검증 범위(`novelty_search_scope`)는 LLM이 쓰지 않고 CoT5 검색 상태에서 코드로 만든다.
- **프롬프트에 넣는 것** (구조와 필수 정보를 지정하면 품질이 높아진다는 원칙을 적용한 부분)
  - 공통 규칙: 근거 경로만 쓰기, `inferred` 표시, 화이트리스트 밖 인용 금지, 결과 단정 금지, 모르는 값은 `[TBD: ...]`
  - `field_definitions.md`에서 그 묶음의 행만 뽑은 정의와 "좋은 값" 기준. 필드 정의는 그 문서 한 곳에서만 관리한다.
  - 묶음별 작성 요령. 예를 들어 validation 묶음에는 "가장 가까운 선행연구로 만든 ablation baseline을 반드시 포함"이 들어간다.
  - 형식 예시는 이번 아이디어와 무관한 가짜 예시만 쓴다. **정답 예시(idea06)를 few-shot으로 넣지 않는다.** 같은 아이디어라서 답을 베끼게 되고, 7단계 평가가 의미 없어지기 때문이다.
- **검사**
  - 0단계 검증기(`validate_plan`): 필드 누락, ID 형식, L→M→V→E→C 연결, 화이트리스트 밖 인용
  - 근거 경로 실재 검사(`check_sources`): `source`가 evidence에 실제로 있는 경로(또는 그 상위 경로)인지. 검증기는 접두어만 보므로, 모델이 지어낸 경로를 여기서 잡는다.
  - 오류 메시지마다 고칠 묶음을 정한다. 예: `M2: 존재하지 않는 한계` → method, `V4: 어떤 실험에서도…` → validation, 화이트리스트 밖 인용 → 그 ID가 들어 있는 묶음
- **실행**
  ```
  python -m research_plan extract --evidence out/cot45_public_run_20261029_154552/idea06/evidence.json
  ```
- **완료 기준**: 6번 후보로 검사를 통과하는 plan.json이 실제 모델로 생성되고, 재시도 횟수와 오류 내역이 기록된다. ✅
- **실제 실행 결과** (`openai/gpt-6-luna`, `out/.../idea06/`)

  | | v1 (`plan.v1.json`) | v2 (`plan.json`, 프롬프트 보완 후) |
  |---|---|---|
  | 라운드 / 비용 / 시간 | 2회 / $0.016 / 약 2분 | 2회 / $0.014 / 약 2분 |
  | 1라운드 오류 | 근거 경로 세부 필드 16건 | 본문의 `P1` 표기 2건 |
  | 핵심 ablation | "unsupported 토큰 제외" (무엇과 비교하는지 모호) | Self-RAG 기존 `irrelevant`/`no support` 신호로 거절 (B3) |
  | 과잉 거절 검증 | 없음 | V4·E4·C3 (지원 질의 정확도, false refusal rate) |
  | 구성요소 | 평가 단계(M4)와 토큰 추가 작업이 구성요소로 들어감 | 데이터 구성, 상태 학습, 인용 응답 생성 3개 |
  | 주장 | "~할 수 있다" | "B3보다 F1이 높다"처럼 비교형 |

- **v1 이후 보완한 것**
  - 근거 경로 검사: 항목 안의 세부 필드 경로(`cot5.paper.candidates[0].critical_difference`)를 허용한다.
  - 내부 논문 표기 검사(`check_paper_labels`): 값에 `P1`, `P2`가 남으면 오류로 보내 다시 쓰게 한다.
  - 프롬프트: 가장 가까운 선행연구에 비슷한 장치가 이미 있는지 먼저 확인, 평가 단계와 공학 작업을 구성요소에서 제외, ablation에 기존 장치를 구체적으로 명시, 부작용(과잉 개입) 검증 대상 필수, 비교형 주장
- **남은 약점** (3단계 판정기가 잡아야 할 것)
  - L1이 Self-RAG 인용문(사람 평가에서 `no support` 사례를 제외했다는 내용)을 "미지원 질의 처리를 다루지 않는다"로 과하게 해석한다.
  - Self-RAG의 기존 `no support`는 문장 단위 판단이고 제안은 응답 전체 단위라는 차이가 한계와 신규성에 명시되지 않는다.
  - E1(데이터 품질 점검)의 baseline이 B1·B2로 되어 있어 의미가 없다.


### 3단계. 심사와 보완 (규칙 + LLM 판정기) 🔧

- **입력**: `plan.json`과 같은 폴더의 `evidence.json`
- **출력**: `plan.reviewed.json`(최종 plan, `meta.review`에 상태·점수 기록), `review.json`(회차별 점수, 지적 사항, 보완 기록, 호출 사용량). **원래 `plan.json`은 바꾸지 않는다.**
- **흐름**
  1. 규칙 검사(`rule_errors`: 0단계 검증기 + 근거 경로 실재 + 내부 논문 표기)를 다시 돌린다. 통과하지 못하면 심사하지 않는다.
  2. 판정기가 17개 필드에 1~5점을 주고 지적 사항을 낸다. 신규성 검증 범위는 코드로 만든 것이라 심사하지 않는다.
  3. 4점 미만 필드나 major 지적이 있는 필드의 묶음만, 지적 사항을 `fix_errors`로 붙여 2단계 작성기로 다시 쓴다(1회). 다시 쓴 결과도 규칙 검사를 거친다. 규칙 검사를 못 넘으면 원래 plan을 유지한다.
  4. 다시 쓴 plan을 한 번 더 심사한다. 그래도 남은 문제는 `needs_review`로 표시해 사람이 본다. 무한히 고치지 않는다.
- **판정 모델**: 기본 `openai/gpt-6-luna-pro`. 작성 모델(`gpt-6-luna`)과 같은 계열이지만 추론을 더 많이 쓴다. `--judge-model`로 다른 회사 모델로 바꿀 수 있다.
- **확인 항목** (`prompts/judge.md`, 지적 사항의 `check` 값)

  | check | 확인 내용 | 2단계 실제 결과에서 남았던 예 |
  |---|---|---|
  | `quote_fidelity` | 원문 인용문을 넓히거나 뜻을 바꾸지 않았는가 | L1이 "사람 평가에서 제외"를 "처리하지 않음"으로 해석 |
  | `closest_work_difference` | 가장 가까운 선행연구와의 차이가 구체적인가 | 문장 단위 vs 응답 단위 차이 누락 |
  | `baseline_fit` | 실험의 baseline이 그 실험 목적에 맞는가 | 데이터 품질 점검(E1)에 모델 baseline |
  | `metric_fit` | 지표가 측정 가능하고 V 질문에 답하는가 | |
  | `claim_quality` | 주장이 비교형·반증 가능한가 | |
  | `component_quality` | 구성요소가 방법의 부분인가 | |
  | `side_effect` | 과잉 개입 검증이 있는가 | |
  | `source_honesty` | `inferred: false`인데 근거에 없는 내용을 단정하는가 | |
  | `internal_consistency` | 주제·문제·목표·방법·기여가 일치하는가 | |

- **판정기 출력 검사**: 17개 필드에 점수가 정확히 하나씩 있는지, 1~5 범위인지, 4점 미만에 지적 사항이 있는지 확인한다. 어기면 한 번 다시 받는다.
- **만든 파일**: `prompts/judge.md`, `src/research_plan/review.py`, `tests/test_review.py`, `extract.py`에 기존 plan에서 일부 묶음만 다시 쓰는 기능(`start`, `fixes`), `cli.py`의 `review` 명령
- **실행** (유료 호출: 심사 1~2회 + 보완 1~3회)
  ```
  python -m research_plan review --plan out/cot45_public_run_20261029_154552/idea06/plan.json
  python -m research_plan review --plan ... --no-refine    # 심사만
  ```
- **완료 기준**: 6번 후보의 plan.json을 심사해 2단계에서 남았던 약점(인용 과잉 해석, 단위 차이 누락, E1 baseline)이 지적되고, 보완 후 점수가 오르거나 남은 문제가 needs_review로 표시된다.
- **1차 실제 실행** (판정 `gpt-6-luna-pro`, 작성 `gpt-6-luna`, $0.029, 약 3분)
  - 1회차 평균 3.82, major 5건 → 보완 → 2회차 평균 4.0, major 1건, needs_review
  - 잡은 것: L1 인용 과잉 해석(major), E1 baseline 부적절(minor), 근거 없는 질의에서 무엇을 인용하는지 불명확(major), E3 지표 채점 기준 없음(major), C2 판정 불가(major)
  - 놓친 것: Self-RAG `no support`(문장 단위)와 제안(응답 단위)의 차이
- **1차 실행 후 보정**
  1. **TBD 감점 제거**: 작성 규칙은 근거 없는 수치를 `[TBD]`로 두라고 하는데 판정기가 그것을 감점했다. TBD 자체는 감점하지 않고, 무엇을 정해야 하는지(지표, 비교 대상, 성공 방향, 사람 평가의 단위·척도)가 빠진 경우만 감점하도록 `judge.md`에 명시했다.
  2. **동기와 증명 구분**: 남은 major(연구 대상이 인용문보다 넓음)는 연구자가 정할 범위 문제였다. 판정기는 인용문이 넓은 공백을 "증명한다고 주장할 때만" 지적하고, 작성기는 인용문을 동기로 쓰고 연구 대상을 별도로 정의하도록 했다.
  3. **단위 차이 확인 강화**: 원문이나 `mechanism_overlap`에 비슷한 장치가 나오면 적용 단위·시점·판단 대상·이후 동작 중 무엇이 다른지 명시했는지 반드시 확인하게 했다(없으면 major). 작성기에도 같은 항목을 한계 문장에 쓰게 했다.
  4. **보완 중 퇴행 방지**: 묶음을 통째로 다시 쓰다가 지적받지 않은 `validation_targets`가 4점에서 3점으로 떨어졌다. 다시 쓰는 묶음 안에서도 지적받지 않은 필드는 원래 값으로 고정하고(`locked_fields`), 고정 때문에 규칙 검사를 못 넘으면 고정 없이 한 번 더 시도한다. 2회차에 점수가 떨어진 필드는 `regressed_fields`로 보고한다.
- **2차 실제 실행** ($0.031): L1 인용 과잉 해석은 고쳐졌다(3→5점). 하지만 두 가지 설계 문제가 드러났다.
  - **규칙 충돌**: 판정기는 데이터 품질 점검 실험 E1에서 모델 baseline을 빼라고 했다. 작성기가 빼자 0단계 검사기가 "모든 실험에는 baseline이 있어야 한다"로 거부해 다시 넣었다. 고칠 수 없는 지적이었다.
  - **판정 편차**: 고정되어 한 글자도 바뀌지 않은 `research_problem`이 4점에서 3점으로 떨어지고 새 major가 붙었다. 같은 글에 다른 판정이 나온 것이다.
- **2차 실행 후 보정**
  5. **데이터 품질 점검은 실험이 아님**: 실험은 비교 대상이 있는 검증만 쓰고, 라벨 일치율·분할 중복 같은 점검은 마일스톤이나 위험 대응에 쓰게 했다(`validation.md`). 데이터 구성 구성요소는 "그 데이터로 학습하면 다른 구성 방식보다 나은가"를 묻는 비교 실험으로 검증한다. 검사기 규칙(모든 E에 baseline)은 그대로 둔다. 비교 없는 점검은 가설 검증 실험이 아니라 방법·데이터 절의 품질 관리에 해당하기 때문이다.
  6. **판정기에 형식 규칙 알려주기**: 판정기가 형식 규칙을 모른 채 제안하면 같은 충돌이 다시 생긴다. `judge.md`에 바뀌지 않는 형식 규칙(모든 E에 baseline, M→V→E 연결, 화이트리스트)을 적고, 그 안에서만 고칠 방향을 제안하게 했다.
  7. **재심사는 이전 판정을 기준으로**: 2회차 판정기에 1회차 판정(`previous_judgement`)과 실제로 바뀐 필드 목록(`changed_fields`)을 함께 준다. 바뀌지 않은 필드는 이전 판정을 유지하고, 바뀐 필드 때문에 생긴 문제만 "변경된 필드 …때문:"으로 표시해 반영한다.
  8. **같은 글에는 같은 판정 (코드로 강제)**: 프롬프트만으로는 편차를 막을 수 없으므로 `reconcile`이 상태 판단에 쓸 판정을 만든다. 바뀌지 않은 필드는 1회차 점수와 지적을 쓰고, 바뀐 필드와 그 영향을 받은 필드만 2회차 판정을 쓴다. 바뀌지 않은 필드에 나온 그 밖의 새 지적은 상태 판단에서 빼고 `new_findings`로 따로 보여준다. 무시하지 않고 사람이 확인하게 한다. 보고는 다음 셋으로 나눈다.
     - `regressed_fields`: 바뀐 필드인데 점수가 떨어짐 (보완이 오히려 나빠지게 함)
     - `drift_fields`: 바뀌지 않았는데 점수가 달라짐 (판정기 편차, 1회차 판정 유지)
     - `new_findings`: 바뀌지 않은 필드에서 새로 나온 지적 (사람 확인)
  - 한계: 1회차 판정 자체의 편차는 이 방식으로 줄일 수 없다. 더 줄이려면 같은 plan을 여러 번 심사해 점수를 합치는 방법이 있다(호출 수만큼 비용 증가). 7단계 평가에서 필요성을 판단한다.
  - 종료 코드: needs_review는 1로 끝난다(VS Code에서 빨간 원). 오류가 아니라 사람이 확인할 것이 남았다는 뜻이다.


### 4단계. 연구계획서와 논문의 틀 작성 (코드 렌더링 + LLM) 🔧

- **입력**: `plan.reviewed.json`만. evidence는 LLM에 주지 않는다. plan에 없는 내용이 끼어드는 것을 막기 위해서다. 같은 폴더의 `evidence.json`은 실행 전 규칙 검사에만 쓴다.
- **출력**: 같은 폴더에 `research_plan.md`, `paper_skeleton.md`, `write_log.json`
- **누가 무엇을 쓰나**

  | 부분 | 작성 | 이유 |
  |---|---|---|
  | 한계 목록, 구성요소 하위 절, 구성요소 관계, 데이터 표, V·B 목록, Design Table, 주장, 신규성·기여 목록, 위험 표, 마일스톤 표, 신규성 검증 범위 | **코드** | 이미 심사를 통과한 구조화 데이터다. LLM이 옮기면 바뀌거나 지어낼 수 있다 |
  | 0. 개요, 1.1 "현재 방식" 문단, 1.2 첫 문단 | LLM (한국어) | 연결 문장이라 데이터에 없다 |
  | 논문의 틀: 제목 후보, 구조화 초록 5칸, 8개 장 개요, 그림·표 계획, 기여 문장 | LLM (제목·초록·기여는 영어, 개요 내용은 한국어) | 논문 형태로 재구성하는 작업이다 |

- **검사**
  - 렌더링한 문서에 0단계 Markdown 검사(고정 제목과 순서, Design Table 머리글, 결과 단정 표현, 인용 범위, 구조화 초록 5칸, `[RESULT:]` 자리표시자)
  - LLM 출력에 plan에 없는 ID 참조(예: M9), 내부 논문 표기(P1)
  - 논문의 틀 구조: 제목 2~3개, 8개 장 제목과 순서, 초록 평가 칸과 Results 항목의 `[RESULT:]`, 그림·표 3~6개, 기여 2~4개
  - 오류가 있으면 그 부분만 오류를 붙여 다시 쓴다(최대 3회).
  - **plan 자체의 문제**(예: plan 문장에 "입증했다")는 LLM이 고칠 수 없으므로 다시 쓰지 않고 `[plan 내용, 사람이 고칠 것]`으로 보고한다.
- **만든 파일**: `prompts/write_plan.md`, `prompts/write_skeleton.md`, `src/research_plan/write.py`, `tests/test_write.py`, `cli.py`의 `write`·`check` 명령
- **1차 실제 실행 후 개선** ($0.004, 두 문서 모두 1회 통과)
  - 문서 제목이 연구 주제 문장 전체("~방법을 연구한다.")로 나왔다 → LLM이 짧은 명사구 제목(`short_title`, 4~40자, 문장형 금지)을 따로 쓰고 두 문서에 같이 쓴다. 연구 주제 문장은 개요 위에 "연구 주제."로 넣는다.
  - 초록에 필드 이름 `(expected_contribution)`과 내부 ID `(L1, L2)`, `(E1–E4)`가 그대로 나왔다 → 제목·초록·기여 문장과 계획서 문단에서 필드 이름을, 제목·초록·기여 문장에서는 `[RESULT: ...]` 밖의 내부 ID를 코드로 막는다(`check_reader_text`). 장별 개요의 "근거:"에는 계속 허용한다.
  - "결과 자리표시자를 모은 그림"처럼 무엇을 그리는지 모호한 항목이 나왔다 → 그림·표마다 그릴 대상(흐름도, 실험 하나의 결과 표, 균형 곡선)과 축·열이 되는 지표를 쓰게 했다(프롬프트).
  - 입력 문장의 과장(예: RAG가 "인용을 생성"한다)을 그대로 옮기지 않게 했다(프롬프트). 근본적으로는 plan의 해당 문장을 사람이 고쳐야 한다.
- **사람 확인**: `docs/human_review.md`에 읽을 파일, 고칠 파일, 순서를 정리했다. 사람이 `plan.reviewed.json`을 고친 뒤 `check`(무료)로 연결을 확인하고 `write`를 다시 돌린다.
- **실행** (유료 호출 2~6회)
  ```
  python -m research_plan write --plan out/cot45_public_run_20261029_154552/idea06/plan.reviewed.json
  ```

### 5단계. 인용·날조 검사 (LLM 없음) ✅

- **입력**: plan 파일과 같은 폴더의 `research_plan.md`, `paper_skeleton.md`
- **출력**: `verify_report.json` (상태, 오류, 경고, 인용별 확인 결과)
- **검사**

  | 검사 | 방법 | 걸리면 |
  |---|---|---|
  | 인용 범위 | 문서와 plan의 arXiv ID가 `citation_whitelist` 안에 있는가 | 오류 |
  | 인용 실재 | arXiv API로 실제로 존재하는가 | 오류 |
  | 인용 제목 | arXiv 제목과 화이트리스트 제목의 유사도 0.85 이상인가 (CoT5 DB의 제목이 실제 논문과 같은지) | 오류 |
  | 수치 | 문서의 숫자가 plan에 있는 숫자인가. 절 번호, 목록 번호, ID, arXiv ID, `[RESULT:]`, 머리 인용 블록은 뺀다 | 오류 |
  | 이름 | 모델·데이터셋·논문처럼 보이는 이름(대문자 묶음, CamelCase, 숫자가 섞인 이름)이 plan이나 화이트리스트 제목에 있는가. 흔한 약어(F1, LLM 등)는 뺀다 | **경고** (사람 확인. 일반 약어와 구분이 어렵다) |
  | 결과 단정 표현 | 0단계 목록 + 5단계 추가분(state-of-the-art, SOTA, significantly improves, results show, we found, for the first time, 증명했다, 개선되었다, 확인되었다, 보여주었다, 최초로 등). 4단계 검사에도 같은 목록이 쓰인다 | 오류 |

- **arXiv 조회**: 한 번에 최대 50개를 묶어 조회하고 결과를 `data/arxiv_cache.json`에 저장한다. 다음 실행부터는 캐시를 쓰고, `--offline`이면 접속하지 않는다. 접속 실패나 캐시 없는 오프라인은 오류가 아니라 "확인불가" 경고다.
- **만든 파일**: `src/research_plan/verify.py`, `tests/test_verify.py`, `cli.py`의 `verify` 명령, `validate.py`의 결과 단정 표현 추가
- **실행** (무료, LLM 호출 없음)
  ```
  python -m research_plan verify --plan out/cot45_public_run_20261029_154552/idea06/plan.reviewed.json
  ```
- **plan 수정 기록**: 5단계 전에 6번 plan에서 RAG를 "인용 생성 방법"으로 과장한 표현 5곳을 "생성에 쓴 검색 문서를 근거(provenance)로 보여줄 수 있다"로 고쳤다. 수정 내용과 이유는 `plan.reviewed.json`의 `meta.human_edits`에, 수정 전 파일은 `plan.reviewed.before_edit.json`에 있다. 과장의 출처는 CoT3·CoT4의 "P1-style citation generation"이다(CoT3 원문의 근거 문장은 "P1's provenance capability").

- **반복되는 과장의 일반 수정 (6단계 테스트 후)**: 처음부터 다시 실행하자 RAG를 "인용 생성 방법"으로 과장하는 표현이 다시 나왔다. 6번 plan만 고쳤기 때문이다. 원인은 CoT3·CoT4가 RAG의 기능을 "P1-style citation generation"이라는 줄임말로 부르는 것이다. 그래서 아이디어마다 고치는 대신 다음처럼 고쳤다.
  1. evidence에 `seed_papers`를 항상 넣는다. CoT1이 원 논문을 읽고 정리한 연구 문제와 하위 목표다(예: RAG의 G2 "provide provenance for decisions"). 이전에는 CoT3가 근거로 든 하위 목표만 들어갔다.
  2. 작성기 규칙 11: 논문이 하는 일은 `seed_papers`를 근거로 쓰고, 이전 단계의 줄임말과 다르면 `seed_papers`를 따른다. `not_achieved` 목표는 그 논문이 해낸 일로 쓰지 않는다.
  3. 판정기 `source_honesty`: 논문 기능을 줄임말에 기대어 넓혀 쓰면 major로 지적한다.

### 6단계. 한 줄 실행과 실행 기록 ✅

- **명령**
  ```
  python -m research_plan run --run-dir data/cot45_public_run_20261029_154552 --idea 6
  ```
  select → extract → review → write → verify를 차례로 실행한다. 각 단계는 지금까지의 개별 명령과 같은 코드를 쓴다.
- **중간부터 다시 실행** (`--from`)

  | 상황 | 명령 |
  |---|---|
  | 사람이 `plan.reviewed.json`을 고쳤다 | `--from write` (review를 다시 돌리면 고친 파일이 새로 만들어진다) |
  | 판정기 프롬프트를 고쳤다 | `--from review` |
  | 작성기 프롬프트를 고쳤다 | `--from extract` |
  | 문서 프롬프트를 고쳤다 | `--from write` |
  | arXiv 확인만 다시 | `--from verify` (LLM 호출 없음) |

  그 밖의 선택: `--skip-review`(심사 건너뜀), `--no-refine`(심사만), `--offline`(arXiv 접속 안 함), `--model`, `--judge-model`, `--allow-not-novel`
- **자동 백업**: 실행 전에 다시 만들 단계와 그 뒤 단계의 기존 결과, 그리고 이전 `run_manifest.json`을 `history/<시각>/`으로 복사한다. `--from` 이전 단계의 파일은 건드리지 않는다. 사람이 고친 `plan.reviewed.json`을 review가 다시 만들게 되면 실행 전에 경고한다.
- **단계 실패 처리**
  - select 오류(예: NOT_NOVEL), extract 실패(`plan.draft.json`): 멈춘다. 뒤 단계에 쓸 입력이 없다.
  - review `needs_review`: **계속 진행**한다. 문서를 만들어 사람이 함께 보게 하고, 최종 상태를 needs_review로 남긴다.
  - write 실패: verify를 돌리지 않고 멈춘다.
  - verify 실패: 최종 상태 fail.
  - 종료 코드: 0 = 모두 통과, 1 = 사람 확인 필요(needs_review 또는 검사 실패), 2 = 실행 오류
  - `--skip-review`로 extract부터 돌리면, 예전 `plan.reviewed.json`이 남아 있어도 새 `plan.json`으로 문서를 만든다.
- **실행 기록** `run_manifest.json`
  - 명령, 시작·끝 시각, 시작 단계, 백업 위치
  - 입력 파일 해시(FutureWork, CoT3~5, manifest), 프롬프트 7개와 `field_definitions.md`의 해시, 모델
  - 단계별 상태, 소요 시간, LLM 호출 수, 비용(USD), 요약(라운드 수, 평균 점수, major 수, 검사 오류 수), 출력 파일 해시
  - 최종 상태와 총비용
  - 같은 결과를 다시 만들려면 무엇이 같아야 하는지(입력, 프롬프트, 모델)를 이 파일만 보고 알 수 있다. 7단계 평가에서 실행끼리 비교할 때도 이 파일을 쓴다.
- **만든 파일**: `src/research_plan/pipeline.py`, `tests/test_pipeline.py`, `cli.py`의 `run` 명령
- **Docker**
  ```
  docker run --rm --env-file .env -v ${PWD}/out:/app/out reserch-plen python -m research_plan run --run-dir data/cot45_public_run_20261029_154552 --idea 6
  ```

### 7단계. 평가 🔧

- **질문**: 이 파이프라인이 "근거 자료를 주고 한 번에 써 달라고 하는 것"보다 실제로 나은가? 낫다면 어느 부분 덕분인가?
- **조건** (같은 evidence, 같은 작성 모델)

  | 조건 | LLM이 받는 것 | 보려는 효과 |
  |---|---|---|
  | `free` | evidence + "연구계획서와 논문의 틀을 써라" (`prompts/baseline_free.md`) | 기준선 |
  | `template` | free + 고정 목차, 18개 필수 요소와 좋은 값의 기준, 작성 규칙 (`prompts/baseline_template.md`) | 필수 정보와 구조를 **프롬프트로 지정한** 효과 (free 대비) |
  | `pipeline` | 1~5단계 전체 (`run`) | 분해·검사·판정·보완·코드 렌더링의 효과 (template 대비) |
  | `golden` | 6번 아이디어의 사람이 쓴 정답 예시 (평가만) | 판정기가 좋은 문서를 알아보는지 확인하는 기준 |

- **측정**
  1. 자동 지표 (LLM 없음, 세 조건 모두 같은 evidence와 대조): 근거에 없는 숫자, 근거에 없는 이름(경고), 화이트리스트 밖 인용, arXiv에 없는 인용, 결과 단정 표현, 내부 표기(P1), 필수 제목 누락, 비용, 시간
  2. LLM 판정 (`prompts/eval_judge.md`): **눈가림**(어떤 조건인지 알리지 않음). 17개 요소의 포함 여부와 1~5점, 내용 문제(3단계와 같은 확인 항목)를 받는다.
     - **판정 모델 여러 개**: 기본 `openai/gpt-6-luna-pro`와 `anthropic/claude-haiku-5.5`. 3단계 판정기와 같은 계열 모델 하나로만 평가하면 파이프라인이 그 판정기에 맞춰 고쳐졌기 때문에 유리하게 나올 수 있다. 다른 회사 모델에서도 순위가 같아야 결과를 믿을 수 있다.
     - **반복 평가**: 같은 문서를 판정 모델마다 2번 평가해 평균을 내고, 두 번 사이의 차이(`sample_spread`)를 기록한다. 조건 간 차이가 이 차이보다 작으면 의미 있는 차이로 보지 않는다.
  3. 사람 평가지: 한 아이디어(기본 6번)의 세 문서를 A/B/C로 섞은 평가지(`human/idea06_sheet.md`)와 정답 키(`idea06_key.json`)를 따로 만든다. 정답 예시는 참고용으로 붙인다.
- **출력**: `eval/eval_<시각>/` 아래 `report.json`(전체), `summary.md`(조건별 표), 아이디어별 문서, `pipeline_runs/`(파이프라인 실행 기록), `human/`
- **실행**
  ```
  python -m research_plan evaluate --run-dir data/cot45_public_run_20261029_154552 --ideas 6        # 시범 (1개)
  python -m research_plan evaluate --run-dir data/cot45_public_run_20261029_154552                  # NOVEL 6개 전부
  ```
- **예상 비용과 시간** (추정): 아이디어 하나에 약 $0.1, 10~15분. NOVEL 6개 전부면 약 $0.6, 1시간 이상.
- **해석할 때 주의**
  - `missing_headings`는 free에 목차를 주지 않았으므로 free에 불리하다. 내용 비교는 LLM 판정과 사람 평가로 한다.
  - pipeline의 3단계 판정기와 평가 판정기가 같은 계열(gpt-6-luna-pro)이면 pipeline에 유리할 수 있다. 다른 회사 판정 모델의 결과를 함께 본다.
  - 아이디어 6개는 표본이 작다. 차이가 작으면 결론을 내리지 않는다.
- **시범 평가 후 수정 (2026-10-30)**: 근거와 예상 질문은 `docs/design_rationale.md` 2절.
  1. 선행 논문이 한 일과 제안 방법이 할 일을 구분 (작성 규칙 11, `method.md`)
  2. 신규성을 반증 가능한 구조로: `expected_novelty`에 `existing_mechanism`, `difference_axis`, `tested_by` 추가(스키마 0.2), 검사기가 연결을 확인
  3. 정답 예시 v2: 실제 evidence 경로, Self-RAG 원문 기준, pipeline과 같은 검사·렌더링 통과(`examples/golden/make_golden_v2.py`), v1은 `history_v1/`
  - 자동 지표 오탐 3가지 수정(arXiv 번호 뒤 마침표, 절 번호, H1·RQ1·DB)과 `rescore`(LLM 없이 자동 지표 재계산)
  - 스키마 0.1로 만든 plan은 `schema_version` 오류가 난다. extract부터 다시 만든다.
- **테스트 중 발견**: "We achieve better results"가 결과 단정 표현 검사에 걸리지 않았다(`achieves`/`achieved`만 있었음). `we achieve`, `we outperform`을 추가했다. "aim to achieve"는 계획 표현이라 막지 않는다.

### 8단계. 기존 흐름에 연결

- `run_cot4_then_cot5.py`의 결과 뒤에 붙는다. 연결 방식은 두 가지 중 하나다.
  - ① Future Work JSON과 CoT4/5 보고서를 그대로 이 기능의 입력으로 넘기는 방식
  - 보고서 안에 원문을 같이 저장하도록 runner를 수정하는 방식 (팀 합의 필요)
- Category 브랜치는 직접 수정하거나 푸시하지 않는다. 연결 코드는 팀이 리뷰한 PR로 반영한다.

## 5. 필요한 것 체크리스트

| 구분 | 항목 | 담당·상태 |
|---|---|---|
| 데이터 | FutureWork, CoT1~CoT5 결과, manifest 2개 | ✅ `data/`에 복사함 (Category `3255acb`) |
| 환경 | OpenRouter API 키 (`.env`에 `OPENROUTER_API_KEY`) | **필요 — 2단계 실제 실행을 막고 있음** |
| 환경 | 모델 | 작성: `openai/gpt-6-luna`. 3단계 판정기는 다른 모델 권장 |
| 환경 | 네트워크 (5단계 arXiv 확인) | 선택 |
| 품질 | 정답 예시 추가 2건 | 7단계 전에 필요 |
| 결정 | 사용자 선택 방식: CLI 번호 선택으로 충분한지, 화면(UI)이 필요한지 | 1단계 전에 정하면 좋음 |
| 결정 | NOT_NOVEL 후보 허용 여부 (현재 기본값: 막음, 옵션으로 허용) | |
| 결정 | 웹 검색 실패 7건 재실행 여부 (현재 기본값: 부록에 명시) | |
| 결정 | 출력 언어 (현재 기본값: 계획서 한국어, 논문 틀 영어) | |

## 6. 예상 비용과 위험

- LLM 호출 수: 후보 1개당 약 3(추출) + 재시도 0~3 + 1(판정) + 7~10(절 단위 작성)회
- **위험 1**: 정답 예시는 원문 없이 만들어 일부 필드가 추측이다. 2단계 전에 실제 근거 경로로 고쳐야 평가 기준으로 쓸 수 있다.
- **위험 2**: CoT5의 벡터 검색 인덱스가 없어(`vector_index.state = missing`) 겹침 후보가 키워드 검색 결과에 한정되어 있다. 신규성 부록에 이 한계를 그대로 적는다.
- **위험 3**: 가장 가까운 선행 연구와 차별점이 작을 수 있다(예: 6번 후보와 Self-RAG의 reflection token). 3단계 판정기가 이 비교 실험의 유무를 반드시 확인하게 한다.
