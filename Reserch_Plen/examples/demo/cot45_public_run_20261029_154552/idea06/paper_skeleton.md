# 논문의 틀: 미지원 질의 성찰 토큰과 인용 연계 응답 정책

> run `cot45_public_run_20261029_154552` · candidate 6 · CoT5 판정 NOVEL (검색 범위 한정, 부록 참고)
> 작성 `llm:openai/gpt-6-luna` · 3단계 심사 needs_review (평균 4.06, 판정 `openai/gpt-6-luna-pro`)
> 실험 전 단계의 틀이다. 결과 자리는 모두 `[RESULT: ...]`로 비워 두었다.

## 1. Title candidates

1. Unsupported-State Reflection for Transparent Refusals and External-Knowledge Requests
2. Citation-Linked Unsupported Reflection for Handling Fully Unsupported Queries
3. Learning an Unsupported Reflection Token for Transparent Query Handling

## 2. Structured Abstract

- **Background:** Retrieval-augmented generation uses external non-parametric memory to support generation and provide sources [2005.11401], while Self-RAG uses reflection tokens to control retrieval and assess retrieved context and generated responses [2310.11511].
- **Gap:** Self-RAG mentions a “no support” prediction, but the proposed focus is to learn a distinct state for fully unsupported queries and connect it to a transparent refusal or external-knowledge request with response-level citations. This differs from citation correction after generation, as described for FineRef [2602.18437], in its target and subsequent response behavior.
- **Method:** We propose adding an explicit unsupported reflection token, training it with explicitly labeled and synthetic unsupported-query examples, and using the state to trigger a citation-linked refusal or external-knowledge request. The citation format, refusal citation rules, and unsupported-query construction procedure remain to be specified.
- **Planned Evaluation:** We compare the method with Self-RAG and a closest-baseline ablation using Self-RAG’s existing “no support” judgment across held-out unsupported and supported queries. We evaluate identification, response appropriateness, citation quality, unsupported claims, and supported-query behavior; outcomes will be reported as [RESULT: E1 identification F1], [RESULT: E2 citation quality], [RESULT: E3 unsupported-query handling], and [RESULT: E4 supported-query performance].
- **Expected Contribution:** We propose a method for linking explicit unsupported-state reflection to citation-linked refusals or external-knowledge requests, and plan to evaluate it alongside a training-data construction comparison. We also plan to analyze the balance between handling unsupported queries and avoiding unnecessary intervention on supported queries.

## 3. Section outline

### 1 Introduction

- RAG와 Self-RAG의 검색·성찰 기반 생성 배경 — 근거: research_background
- 완전히 지원되지 않는 질의의 독립 상태 판별과 판단 이후 응답 정책이라는 연구 문제 — 근거: research_problem
- 기존 ‘no support’ 판단과 명시적 unsupported 상태 및 응답 동작의 차이 — 근거: L2, expected_novelty[0]
- 방법, 학습자료, 지원·미지원 질의 평가의 기여를 소개 — 근거: expected_contribution

### 2 Related Work

- 검색된 비매개변수 메모리에 기반한 생성과 출처 제공을 다루는 RAG [2005.11401] — 근거: research_background, L3
- reflection token을 이용한 검색 조절과 검색 내용·생성 결과 평가를 다루는 Self-RAG [2310.11511] — 근거: research_background, L1, L2
- Self-RAG의 기존 ‘no support’ 판단과 제안하는 별도 unsupported 상태 및 후속 응답 정책 비교 — 근거: L1, L2, expected_novelty[0]
- 생성 후 인용별 불일치·무관성을 성찰하고 교정하는 FineRef [2602.18437]와 제안 방법의 대상·시점 비교 — 근거: L4

### 3 Method

- 미지원 라벨 질의와 합성 미지원 질의를 학습자료로 구성하는 절차 — 근거: M3, component_relations
- 미지원 질의를 unsupported reflection token으로 표현하도록 reflection 모듈을 미세조정 — 근거: M1, component_relations
- unsupported 상태를 인용 연계 거절 또는 외부 지식 요청으로 연결 — 근거: M2, component_relations
- 미지원 라벨·합성 절차 및 거절 응답 인용 규칙의 미확정 사항을 명시 — 근거: M2, M3

### 4 Experimental Setup

- 미지원 질의 학습자료, 검색 증강 인용 사례, 보류 평가 세트의 구성 계획 — 근거: data_and_subjects, M3
- Self-RAG 기본 방식(B1), 기존 ‘no support’ 판단 기반 ablation(B2), 합성 질의 추가 여부 비교(B4)의 조건 설정 — 근거: baselines
- 학습·평가 질의 중복 방지와 지원·미지원 질의 구분 평가 설계 — 근거: E1, E3, E4
- 미지원 식별, 응답 적절성, 인용 품질, 근거 없는 주장 및 지원 질의 성능의 평가 항목 — 근거: E1–E4

### 5 Results

- E1 미지원 질의 식별 precision, recall, F1 및 응답 적절성 결과: [RESULT: E1 precision], [RESULT: E1 recall], [RESULT: E1 F1], [RESULT: E1 response appropriateness]; 검증 주장 C1 — 근거: E1, C1
- E2 인용 정확성·관련성, 응답 투명성 및 근거 없는 주장 비율 결과: [RESULT: E2 citation quality], [RESULT: E2 transparency], [RESULT: E2 unsupported-claim rate]; 검증 주장 C2 — 근거: E2, C2
- E3 합성 질의 포함 여부에 따른 미지원 처리와 지원 질의 응답 성능 결과: [RESULT: E3 unsupported-query handling], [RESULT: E3 supported-query performance]; 검증 주장 C3 — 근거: E3, C3
- E4 지원 질의 답변 성능, 불필요한 개입률 및 미지원 처리 결과: [RESULT: E4 supported-query performance], [RESULT: E4 unnecessary-intervention rate], [RESULT: E4 unsupported-query handling]; 검증 주장 C4 — 근거: E4, C4

### 6 Analysis

- 가장 가까운 선행연구 Self-RAG [2310.11511]의 기존 ‘no support’ 판단을 이용한 B2 ablation과 전용 unsupported 토큰의 차이를 분석 — 근거: B2, E1, E2, R5
- 합성 미지원 질의 추가 여부(B4)에 따른 자료 구성 효과와 지원 질의 성능 변화를 분석 — 근거: B4, E3, C3
- 지원 질의 성능과 불필요한 거절·외부 지식 요청률의 균형을 분석 — 근거: E4, C4
- 학습 목적함수·loss 가중치, 라벨 및 합성 절차, 인용 통합 규칙 관련 위험과 대안 검토 — 근거: R1, R2, R3

### 7 Limitations

- 미지원 토큰 학습 목적함수와 loss 가중치가 정해지지 않았으며, 지도 미세조정과 RL 기반 목적의 실행 가능성 비교가 필요 — 근거: R1
- 미지원 라벨 정의와 합성 절차가 미확정이어서 라벨 오류와 평가 누수 가능성이 있음 — 근거: R2
- 거절 응답의 인용 적용 방식과 reflection token에서 인용 출력으로 이어지는 통합 규칙이 미확정 — 근거: R3
- 가용 GPU·추론 자원에 따라 모델 규모 또는 비교 실험 범위를 조정해야 할 수 있음 — 근거: R4
- 신규성 검색은 논문 10건의 제한된 후보 검색에 한정되었고, 웹 검색은 실패했으며 특허 검색은 0건이므로 전 세계적 신규성을 입증하지 않음 — 근거: novelty_search_scope

### 8 Conclusion

- 결론은 E1–E4의 결과에 따라 작성한다 — 근거: E1–E4, C1–C4

## 4. Figures & Tables plan

| 번호 | 내용 | 근거 |
|---|---|---|
| Fig. 1 | 미지원 라벨·합성 질의와 인용 사례에서 unsupported 상태 학습을 거쳐 인용 연계 거절 또는 외부 지식 요청 생성으로 이어지는 방법 흐름도. | M1, M2, M3, component_relations |
| Table 1 | E1 결과표: 행은 제안 방법, Self-RAG 기본 방식(B1), 기존 ‘no support’ 판단 기반 ablation(B2); 열은 미지원 질의 식별 precision, recall, F1 및 응답 적절성 평가. | E1, B1, B2, C1 |
| Table 2 | E2 결과표: 행은 제안 방법과 B2; 열은 인용 정확성·관련성, 응답 투명성, 미지원 응답의 근거 없는 주장 비율. | E2, B2, C2 |
| Table 3 | E3 결과표: 행은 합성 미지원 질의를 포함한 학습자료와 이를 추가하지 않은 B4; 열은 미지원 질의 식별 precision, recall, F1, 응답 적절성 및 지원 질의 응답 성능. | E3, B4, C3 |
| Fig. 2 | E4 균형 곡선: x축은 지원된 질의의 불필요한 거절·외부 지식 요청률, y축은 지원된 질의 답변 성능; 제안 방법, B1, B2를 비교하고 미지원 질의 처리 지표는 별도 표기로 표시. | E4, B1, B2, C4 |

## 5. Contribution bullets

- We propose a method that links an explicit unsupported reflection state to citation-linked refusals or external-knowledge requests.
- We plan to construct training materials with explicitly labeled unsupported queries and citation examples, alongside a held-out evaluation set of unsupported queries.
- We evaluate whether the proposed state and response policy differ from a Self-RAG-based baseline that uses its existing “no support” judgment.
- We analyze the trade-off between handling unsupported queries and avoiding unnecessary intervention on supported queries.
