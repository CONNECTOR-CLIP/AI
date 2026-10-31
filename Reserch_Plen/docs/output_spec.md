# 출력 명세 (Stage 0, v0.1)

이 기능은 **논문 초안이 아니라 "연구계획서 + 논문의 틀"** 을 만든다.
실험은 아직 수행되지 않았으므로, 결과를 단정하는 문장은 어떤 산출물에도 들어가지 않는다.

## 1. 입력

| 입력 | 파일 | 사용하는 필드 |
|---|---|---|
| 실행 기록 (진입점) | `examples_run_manifest.json` | `run_id`, `input_sha256`, `input_file`, `results`, `upstream_manifest`, `upstream_results` |
| 아이디어 원문 | `FutureWork/examples/result.json` (CoT4·CoT5의 실제 입력, `input_sha256`로 확인) | `future_work_proposals[].{id, background_and_gap, proposed_direction, expected_contribution, novelty_note, reference_papers}` |
| CoT3 후보 | `CoT3/examples/result.json` | `candidate_id`, `source_evidence`, `rationale`, `judge_verdict`, `judge_subclaims[].quote` |
| CoT1·CoT2 | `CoT1/examples/<arxiv>.json`, `CoT2/examples/<arxiv>.json` | CoT3 근거 ID `Pk:Gx`(CoT1 subgoal), `Pk:Lx`(CoT2 한계 인용문, 1부터) |
| 상류 기록 | `examples_upstream_manifest.json` | `papers`(P1, P2 순서), `candidate_mapping`(번호 ↔ CoT3 ID) |
| CoT4 자원 안내 | `CoT4/examples/result.json` | `results[].requirements.*`, `results[].resource_guidance.*` |
| CoT5 신규성 검사 | `CoT5/examples/result.json` | `results[].{classification, reason, review, overlaps.{paper,web,patent}, paper_search.coverage}` |

FutureWork와 CoT4·CoT5는 필수다. CoT1~CoT3와 상류 기록이 없으면 경고를 내고, 원 논문 인용문 없이 진행한다.

- 세 결과는 **1부터 시작하는 순서 번호(`candidate_index`)** 로 연결한다. CoT4 어댑터가 `future_work_proposals`를 `enumerate(..., 1)`로 번호 매기는 방식과 같다. `idea_title`은 CoT4에서 120자, CoT5에서 70자로 잘려 있으므로 키로 쓰지 않고, 짝이 맞는지 확인하는 데에만 쓴다.
- 사용자가 후보 목록에서 1개를 골라 처리한다. 기본 정책은 `classification == "NOVEL"`인 후보만 고를 수 있게 하는 것이다. NOT_NOVEL 처리는 열린 결정 사항이다(README 참고).
- 단계별 구현 방법은 `docs/implementation_plan.md`에 있다.

## 2. 산출물 (아이디어 1개당 3개)

```
out/<run_id>/idea<NN>/
├── plan.json           # A. 15+3개 요소, 근거 표시 포함 (schema/plan.schema.json)
├── research_plan.md    # B. 연구계획서 (1절 Proposed Method / 2절 Validation & Target Claims)
└── paper_skeleton.md   # C. 논문의 틀 (제목 후보, 구조화된 초록, 장별 개요, 그림·표 계획)
```

B와 C는 **A에만** 근거해서 작성한다. A에 없는 내용이 B·C에 새로 등장하면 안 된다.

## 3. A. plan.json 규칙

모든 요소는 다음 래퍼를 갖는다.

```json
{ "value": "...", "source": ["cot5.paper.candidates[0]"], "inferred": false }
```

- `source`: 근거 경로 목록. 허용 접두어는 `future_work.`, `cot1.`, `cot2.`, `cot3.`, `cot4.`, `cot5.`, `manifest.`, `seed:<arxiv_id>`. 1단계 `evidence.json`의 `source` 값을 그대로 옮겨 적는다.
- `inferred`: 입력에 직접 없고 작성자(LLM 또는 사람)가 추론한 내용이면 `true`. `source`가 비어 있으면 반드시 `true`.
- 목록형 요소의 항목은 `id`를 가진다(`L1`, `M1`, `B1`, `V1`, `E1`, `C1`, `R1`, `S1`). 이 ID로 서로 참조한다.
- 인용은 `citation_whitelist`에 있는 arXiv ID만 허용한다(시드 논문 + CoT5 후보 논문).

### 연결 규칙 (검증기가 강제)

```
L(한계) ──► M(구성요소) ──► V(검증 대상) ──► E(실험) ──► C(주장)
                                   ▲             │
                                   └── B(비교 대상)
```

1. 모든 `M`은 최소 하나의 `V`에서 다뤄진다.
2. 모든 `V`는 최소 하나의 `E`에서 검증된다.
3. 모든 `C`는 존재하는 `V`를 `validated_by`로 참조한다.
4. 모든 `E`는 존재하는 `B`를 최소 하나 참조한다.
5. 모든 `E`는 `success_criterion`과 `failure_interpretation`을 가진다. 결과가 어떻게 나와도 해석할 수 있어야 한다(NIH Aims 원칙).
6. `component_relations`의 `from`과 `to`는 존재하는 `M`이어야 한다.

## 4. B. research_plan.md 구조 (제목 고정)

| 절 | 반드시 포함할 내용 | 근거 필드 |
|---|---|---|
| 0. 개요 | 한 문단 요약(Heilmeier 1번: 전문용어 없이 무엇을 하려는가) | topic, objective |
| 1.1 문제 정의 및 연구 배경 | ① 현재 방식 ② 그 한계(L) ③ 연구 질문 | background, problem, limitations |
| 1.2 제안 방법 | 핵심 개념 2~3문장 → 1.2.x 구성요소별 하위 절(M) → 구성요소 관계도 | proposed_method, components, relations |
| 1.3 연구 대상 및 데이터 | 데이터 후보, 확인이 필요한 항목 | data_and_subjects |
| 2.1 Experimental Validation Plan | 검증 대상(V), 비교 대상(B), **Design Table**(E) | validation_targets, baselines, experimental_design |
| 2.2 Target Claims | 주장(C)마다 반증 조건과 연결된 V | target_claims |
| 2.3 Expected Novelty & Contribution | 가장 가까운 선행연구와의 차이(인용) + 기여 | expected_novelty, expected_contribution |
| 2.4 위험 요소와 대응 | 위험(R)과 대안 | risks_and_fallbacks |
| 2.5 마일스톤 | 중간·최종 성공 기준(S) | success_criteria_milestones |
| 부록. 신규성 검증 범위 | 소스별 상태, 실패한 검색, "NOVEL은 검색 범위 내 판정" 문구 | novelty_search_scope |

### Design Table 열 (고정)

| ID | 검증 대상 | 설정 | 지표 | Baseline | 성공 기준 | 실패 시 해석 |

## 5. C. paper_skeleton.md 구조 (제목 고정)

1. Title candidates (2~3개)
2. Structured Abstract: Background / Gap / Method / Planned Evaluation / Expected Contribution
3. Section outline: 1 Introduction, 2 Related Work, 3 Method, 4 Experimental Setup, 5 Results, 6 Analysis, 7 Limitations, 8 Conclusion
   - 각 절에 `내용:`과 `근거:` (plan.json 필드 또는 ID)를 적는다.
4. Figures & Tables plan
5. Contribution bullets (Introduction 끝에 들어갈 문장)

## 6. 금지 규칙 (모든 산출물)

- 결과 수치를 단정하지 않는다. 결과 자리는 `[RESULT: <E-ID> <지표>]`로 비운다.
- 정해지지 않은 값은 `[TBD: <이유>]`로 표시한다.
- 실험이 끝난 것처럼 쓰지 않는다. 금지 예: "achieves", "outperforms", "we show that", "달성했다", "입증했다", "향상되었다".
  허용: "we hypothesize", "we expect", "~할 것으로 기대한다", "~를 검증한다".
- 화이트리스트 밖의 논문을 인용하지 않는다. 일반적인 지표 이름은 쓸 수 있지만, 출처 논문을 인용하려면 Stage 5에서 검증한 뒤 추가한다.
