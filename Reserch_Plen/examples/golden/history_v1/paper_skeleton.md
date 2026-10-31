# 논문의 틀: [Unsupported] reflection token

> 사람이 직접 작성한 정답 예시(golden). 결과 자리는 모두 `[RESULT: ...]`로 비워 두었다.

## 1. Title candidates

1. Knowing When the Evidence Is Not Enough: Response-Level Unsupported Tokens for Transparent Retrieval-Augmented Generation
2. Cite Before You Refuse: Learning an Unsupported State for Retrieval-Augmented Language Models
3. Beyond Sentence-Level Support: Transparent Abstention in Self-Reflective RAG

## 2. Structured Abstract

- **Background:** Retrieval-augmented models such as RAG and Self-RAG ground generation in retrieved passages and critique their own outputs with reflection tokens.
- **Gap:** These models still default to answering; none treats "the retrieved evidence as a whole cannot answer the query" as an explicit, learnable state that changes the response.
- **Method:** We propose a response-level `[Unsupported]` reflection token, a procedure to synthesize unsupported training cases, and a citation-coupled response mode that either answers with citations or refuses while citing the passages examined and stating what is missing.
- **Planned Evaluation:** We evaluate detection of unsupported queries against Self-RAG's existing reflection tokens (`[RESULT: E1 F1]`, `[RESULT: E4 ablation]`), the transparency of refusals through human evaluation (`[RESULT: E2 transparency]`), and answer accuracy on answerable queries (`[RESULT: E3 accuracy]`).
- **Expected Contribution:** A method, a data synthesis procedure, and an analysis of the trade-off between abstention and answer quality.

## 3. Section outline

### 1 Introduction
- 내용: 근거 부족 상황의 환각 문제 → 기존 RAG 계열의 한계 → 연구 질문 → 제안 개요 → 기여 목록
- 근거: research_background, research_problem, L1–L4, expected_contribution

### 2 Related Work
- 2.1 Retrieval-augmented generation: 근거 B1, B2
- 2.2 Self-reflection and critique tokens: 근거 L1, expected_novelty[0]
- 2.3 Post-hoc detection and correction of unsupported claims: 근거 L3, expected_novelty[1]
- 2.4 Citation-grounded generation and abstention: 근거 L4, expected_novelty[2]

### 3 Method
- 3.1 Overview (그림 1): 근거 proposed_method, component_relations
- 3.2 `[Unsupported]` token: M1
- 3.3 Synthesizing unsupported cases: M2
- 3.4 Citation-coupled responses: M3
- 3.5 Threshold-based decoding: M4

### 4 Experimental Setup
- 내용: 데이터, 비교 대상, 지표, 구현 세부
- 근거: data_and_subjects, B1–B4, E1–E4의 metrics, R5

### 5 Results
- 5.1 Detecting unsupported queries: E1 → `[RESULT: E1 P/R/F1, AUROC]` (C1)
- 5.2 Transparency of refusals: E2 → `[RESULT: E2 human eval]` (C2)
- 5.3 Preserving answer quality: E3 → `[RESULT: E3 accuracy-abstention curve]` (C3)

### 6 Analysis
- 6.1 Ablation against existing reflection tokens: E4 (C1, R1)
- 6.2 Synthetic vs. real unsupported queries: R3

### 7 Limitations
- 근거: risks_and_fallbacks, novelty_search_scope

### 8 Conclusion
- 근거: target_claims (실험 후 채택 또는 기각된 결과에 맞춰 작성)

## 4. Figures & Tables plan

| 번호 | 내용 | 근거 |
|---|---|---|
| Fig. 1 | M2 → M1 → M4 → M3 파이프라인 개요 | component_relations |
| Fig. 2 | 거절률-정확도 곡선 (임계값 변화) | E3 |
| Table 1 | 근거 부족 판별 결과 (B1–B3 대비) | E1, E4 |
| Table 2 | 투명성 사람 평가 결과 | E2 |
| Table 3 | 답변 가능 질의의 정확도와 인용 품질 | E3 |

## 5. Contribution bullets

- We introduce a response-level `[Unsupported]` reflection token that lets a retrieval-augmented model decide when its evidence cannot support an answer.
- We describe a procedure for synthesizing paired supported and unsupported training cases.
- We propose citation-coupled refusals that state which passages were examined and what information is missing.
- We plan a controlled comparison with Self-RAG's existing reflection tokens to test whether the new state is necessary.
