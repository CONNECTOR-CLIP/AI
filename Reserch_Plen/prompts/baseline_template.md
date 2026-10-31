아래 자료는 연구 아이디어 하나와 그 근거다. 이 자료로 연구계획서와 논문의 틀을 써라.
아직 실험은 하지 않았다. 한 번에 두 문서를 모두 쓴다.

## 출력

- `research_plan`: 연구계획서 (한국어, Markdown). 아래 제목을 이 순서 그대로 쓴다.
  ```
  ## 0. 개요
  ## 1. Proposed Method
  ### 1.1 문제 정의 및 연구 배경
  ### 1.2 제안 방법
  ### 1.3 연구 대상 및 데이터
  ## 2. Validation & Target Claims
  ### 2.1 Experimental Validation Plan
  ### 2.2 Target Claims
  ### 2.3 Expected Novelty & Contribution
  ### 2.4 위험 요소와 대응
  ### 2.5 마일스톤
  ## 부록. 신규성 검증 범위
  ```
  2.1에는 다음 머리글의 표(Design Table)를 넣는다: `| ID | 검증 대상 | 설정 | 지표 | Baseline | 성공 기준 | 실패 시 해석 |`
- `paper_skeleton`: 논문의 틀 (Markdown). 아래 제목을 이 순서 그대로 쓴다.
  ```
  ## 1. Title candidates
  ## 2. Structured Abstract
  ## 3. Section outline
  ## 4. Figures & Tables plan
  ## 5. Contribution bullets
  ```
  초록은 `**Background:**`, `**Gap:**`, `**Method:**`, `**Planned Evaluation:**`, `**Expected Contribution:**` 다섯 칸으로 쓴다. 결과가 들어갈 자리는 `[RESULT: 실험 지표]`로 비워 둔다. 제목·초록·기여 문장은 영어로 쓴다.

## 반드시 들어갈 내용

아래 표의 18개 요소를 모두 연구계획서에 담는다. 마지막 열이 좋은 값의 기준이다.

## 규칙

- 자료(evidence)에 근거해서만 쓴다. 자료에 없는 수치, 데이터셋 이름, 논문을 만들지 않는다. 정할 수 없는 값은 `[TBD: 무엇을 정해야 하는지]`로 둔다.
- 논문은 자료의 `citation_whitelist`에 있는 arXiv 번호로만 인용한다. 예: `Self-RAG [2310.11511]`
- 결과를 단정하지 않는다("달성했다", "입증했다", "향상되었다", "outperforms", "achieves" 금지). 계획형으로 쓴다.
- 자료의 `P1`, `P2` 같은 내부 표기는 쓰지 말고 논문 이름으로 바꾼다.
- 가장 가까운 선행연구와의 차이를 구체적으로 쓰고, 그 선행연구의 기존 장치만으로 같은 일을 하는 비교 대상(ablation)을 넣는다.
- 제안 방법이 개입하지 않아야 할 경우의 성능 유지(부작용)를 검증한다.
