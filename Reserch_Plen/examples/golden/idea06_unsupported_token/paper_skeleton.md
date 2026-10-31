# 논문의 틀: 응답 단위 미지원 상태와 근거 표시 거절

> run `cot45_public_run_20261029_154552` · candidate 6 · CoT5 판정 NOVEL (검색 범위 한정, 부록 참고)
> 3단계 심사를 거치지 않은 plan으로 작성했다.
> 실험 전 단계의 틀이다. 결과 자리는 모두 `[RESULT: ...]`로 비워 두었다.

## 1. Title candidates

1. When the Evidence Is Not Enough: Response-Level Unsupported States for Attributed Abstention in Retrieval-Augmented Generation
2. Beyond Segment-Level Support: Learning When to Refuse with Citations in Self-Reflective RAG

## 2. Structured Abstract

- **Background:** Retrieval-augmented models condition generation on retrieved documents [2005.11401], and Self-RAG critiques whether each generated segment is supported by a retrieved passage [2310.11511].
- **Gap:** Support is judged per segment and used to select segments; deciding that the retrieved evidence as a whole cannot answer the query, and changing the response accordingly, is not part of these methods.
- **Method:** We propose a response-level unsupported state, a procedure that pairs answerable and unsupported training cases, a threshold policy that decides between answering and abstaining, and abstentions that cite the documents examined and state what is missing.
- **Planned Evaluation:** We compare against an ablation that abstains using Self-RAG's existing support signals ([RESULT: E1 detection F1]), test the data procedure against existing labels ([RESULT: E2 F1]), measure citation support of abstentions ([RESULT: E3 citation support]), and check answer accuracy on answerable queries ([RESULT: E4 accuracy at matched abstention]).
- **Expected Contribution:** A method for attributed abstention, a paired data procedure, and an analysis of the abstention-accuracy trade-off.

## 3. Section outline

### 1 Introduction

- 근거 부족 상황의 문제와 연구 질문 — 근거: research_problem
- 기여 요약 — 근거: expected_contribution

### 2 Related Work

- 검색 증강 생성과 근거 제시 — 근거: B1, research_background
- 자기 평가 토큰과 문장 조각 단위 지지 판단 — 근거: L2, expected_novelty[0]
- 생성 후 탐지·교정 — 근거: L3, expected_novelty[1]

### 3 Method

- 응답 단위 상태 — 근거: M1
- 짝 데이터 구성 — 근거: M2
- 결정 규칙 — 근거: M3
- 근거 표시 거절 — 근거: M4

### 4 Experimental Setup

- 데이터 분할과 중복 검사 — 근거: data_and_subjects, S1
- 비교 대상 — 근거: B1–B5

### 5 Results

- 미지원 판별 — E1 → [RESULT: E1 F1] (C1)
- 데이터 구성 효과 — E2 → [RESULT: E2 F1] (C2)
- 거절의 근거 표시 — E3 → [RESULT: E3 citation support] (C3)
- 답변 성능 유지 — E4 → [RESULT: E4 accuracy curve] (C4)

### 6 Analysis

- 기존 지지 신호 ablation 해석 — 근거: E1, R1
- 합성 사례와 실제 사례의 차이 — 근거: R3

### 7 Limitations

- 신규성 검색 범위 — 근거: novelty_search_scope, R6
- 자원과 합성 데이터의 한계 — 근거: R3, R5

### 8 Conclusion

- 실험 결과에 따라 채택·기각된 주장으로 작성 — 근거: target_claims

## 4. Figures & Tables plan

| 번호 | 내용 | 근거 |
|---|---|---|
| Fig. 1 | M2 → M1 → M3 → M4 흐름도 | component_relations |
| Table 1 | E1 결과 표: 행 = 제안 방법, B2, B3 / 열 = precision, recall, F1, AUROC | E1 |
| Table 2 | E3 결과 표: 행 = 제안 방법, B3, B4 / 열 = 인용 지지율, 인용 정밀도, 사람 평가 | E3 |
| Fig. 2 | E4 거절률-정확도 곡선: x축 = 불필요한 거절률, y축 = 정답 정확도, 선 = 제안 방법, B2 | E4 |

## 5. Contribution bullets

- We propose a response-level unsupported state that decides whether the retrieved evidence as a whole can support an answer.
- We evaluate whether this state is needed beyond Self-RAG's existing segment-level support signals through a direct ablation.
- We describe attributed abstentions that cite the documents examined and state what is missing, and we measure their citation support.
