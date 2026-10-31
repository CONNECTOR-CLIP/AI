# 필드 정의서 (Stage 0, v0.1)

PDF의 15개 필수 요소에 Heilmeier 문항과 NIH Specific Aims 기준으로 3개를 더했다(★ 표시).
"좋은 값" 열은 검토자와 Stage 3 LLM 판정기가 함께 쓰는 기준이다.

| # | 키 | 이름 | 형태 | 주 출처 | 좋은 값의 기준 |
|---|---|---|---|---|---|
| 1 | `research_topic` | Research Topic | 문자열 | future_work.proposed_direction | 한 문장. 방법과 대상이 함께 드러난다 |
| 2 | `research_background` | Research Background | 문자열 | seed 논문, cot1.Pk.subgoals | 현재 방식이 무엇인지 설명한다. 한계는 3번과 4번에서 다룬다 |
| 3 | `research_problem` | Research Problem | 문자열 | future_work.background_and_gap | 질문 형태로 쓴다. 답이 측정 가능해야 한다 |
| 4 | `limitations_of_existing_approaches` | Limitations of Existing Approaches | 목록 `L{n}` | cot2.Pk.candidates (원문 인용), cot3.judge_subclaims, cot5.paper.candidates[].critical_difference | 한계마다 해당 논문을 인용한다(화이트리스트) |
| 5 | `research_objective` | Research Objective | 문자열 | 3번과 4번에서 도출 | "~를 위해 ~를 개발하고 ~로 검증한다" 형태 |
| 6 | `proposed_method` | Proposed Method | 문자열 | future_work.proposed_direction | 핵심 개념 2~3문장. 구성요소 세부는 7번으로 |
| 7 | `method_components` | 핵심 구성요소 | 목록 `M{n}` | cot4.requirements.implementation_steps | 2~5개. 각각 어떤 한계(L)를 다루는지 `addresses`로 표시 |
| 8 | `component_relations` | 구성요소 간 관계 | 목록 `{from,to,relation}` | 7번에서 도출 | 데이터나 신호가 흐르는 방향이 드러난다 |
| 9 | `data_and_subjects` | 예상 연구 대상 및 데이터 | 목록 | cot4.requirements.data_requirements | 데이터별 용도(학습/평가)와 확인 필요 여부 |
| 10 | `baselines` | 예상 비교 대상 및 기준 | 목록 `B{n}` | seed, cot5 후보 논문 | **가장 가까운 선행연구로 만든 ablation baseline을 반드시 포함** |
| 11 | `validation_targets` | Validation Targets | 목록 `V{n}` | 7번, cot4.resource_guidance.proposed_performance_targets | 구성요소(M)마다 "이게 작동하는가"를 묻는 질문 |
| 12 | `experimental_design` | Experimental Design | 목록 `E{n}` | 11번, cot4.resource_guidance.unknowns_to_confirm | Design Table의 한 행. 성공 기준과 실패 시 해석 필수 |
| 13 | `target_claims` | Target Claims | 목록 `C{n}` | 11번, 12번 | 반증 가능한 한 문장 + 반증 조건 + 연결된 V |
| 14 | `expected_novelty` | Expected Novelty | 목록 `{text, vs, existing_mechanism, difference_axis, tested_by}` | cot5.review, critical_difference, seed_papers | "X와 달리 우리는 Y" 형태로 비교 대상을 인용한다. 비교 대상의 기존 장치를 근거 그대로 적고, 다른 축 하나를 고르고, 그 차이가 필요한지 가리는 실험(E)을 연결한다(Heilmeier: "지금은 어떻게 하는가", "무엇이 새로운가") |
| 15 | `expected_contribution` | Expected Contribution | 목록 | 13번, 14번 | 방법·자원(데이터)·분석 기여를 구분한다 |
| 16★ | `risks_and_fallbacks` | 위험 요소와 대응 | 목록 `R{n}` | cot4.requirements.vague_or_unspecified_steps | 위험마다 대안이 있다 |
| 17★ | `success_criteria_milestones` | 성공 기준과 마일스톤 | 목록 `S{n}` | 12번 | 중간과 최종 점검 지점(Heilmeier "midterm/final exam") |
| 18★ | `novelty_search_scope` | 신규성 검증 범위 | 객체 | manifest, cot5.overlaps.*.status/error | 소스별 상태, 실패 원인, 판정 범위 문구 |

## 공통 래퍼

```json
{ "value": <값>, "source": ["<근거 경로>", ...], "inferred": <bool> }
```

## 근거 경로 표기

- `future_work.<field>`: 아이디어 원문 필드 (`background_and_gap`, `proposed_direction`, `reference_papers[i]` 등)
- `cot1.<Pk>.subgoals[i]`, `cot2.<Pk>.candidates[i]`: CoT3 근거 ID(`Pk:Gx`, `Pk:Lx`)를 풀어 쓴 원 논문 근거
- `cot3.rationale`, `cot3.judge_verdict`, `cot3.judge_subclaims[i]`
- `cot4.requirements.<field>[i]`, `cot4.resource_guidance.<field>[i]`
- `cot5.review`, `cot5.reason`, `cot5.<source>.candidates[i]`, `cot5.<source>.status` (`source` = paper | web | patent)
- `manifest.<field>`
- `seed:<arxiv_id>`: 시드 논문 원문 또는 초록
