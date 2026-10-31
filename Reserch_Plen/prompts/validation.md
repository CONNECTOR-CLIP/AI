## 이번에 채울 묶음: 검증 계획 (validation)

연구계획서 2절 "Validation & Target Claims"의 재료다.
`previous_groups`에 이미 정한 한계(L)와 구성요소(M)가 있다.

연결 규칙 (검사기가 자동으로 확인한다):

- 모든 구성요소(M)는 적어도 하나의 검증 대상(V)의 `components`에 들어간다.
- 모든 검증 대상(V)은 적어도 하나의 실험(E)의 `validates`에 들어간다.
- 모든 실험(E)은 baseline(B)을 하나 이상 가지며, `success_criterion`과 `failure_interpretation`이 비어 있지 않다.
- 모든 주장(C)은 `validated_by`에 V를 하나 이상 가진다.

작성 요령:

1. `baselines`:
   - 시드 논문과 CoT5 관련 논문 중 가장 가까운 것을 고른다. `arxiv_id`는 화이트리스트 안에서만 쓴다.
   - **가장 가까운 선행연구로 만든 ablation baseline을 반드시 하나 포함한다.** "새 구성요소 없이, 그 선행연구가 이미 가진 장치만으로 같은 일을 하면 어떻게 되는가"를 보여주는 기준이다.
   - 이 ablation의 `name`과 `why`에는 **기존 방법의 어떤 장치를 어떻게 써서** 같은 일을 흉내 내는지 구체적으로 쓴다. 예: "기존 방법 X의 A 라벨 확률이 임계값을 넘으면 거절" (O), "새 구성요소를 제외한 버전" (X, 무엇과 비교하는지 알 수 없음)
2. `validation_targets`: 구성요소마다 "이게 원하는 효과를 내는가"를 묻는 **연구 질문**. 다음을 지킨다.
   - "추가할 수 있는가", "출력할 수 있는가", "평가할 수 있는가"처럼 구현 가능 여부만 묻는 질문은 쓰지 않는다. 비교 대상과 무엇을 측정하는지가 드러나야 한다.
   - "데이터 품질이 충분한가"도 검증 대상이 아니다(아래 3번처럼 마일스톤에 쓴다). 데이터 구성 구성요소는 "그 데이터로 학습하면 다른 구성 방식보다 나은가"로 묻는다.
   - 위 ablation이 필요한지(새 구성요소가 기존 장치보다 나은지) 묻는 질문을 하나 포함한다.
   - **부작용 질문을 반드시 하나 포함한다**: 제안 방법이 개입하지 않아야 할 경우(예: 원래 잘 처리되던 입력)에서 기존 성능이 유지되는가. 과잉 개입과 성능 사이의 균형을 측정하는 실험으로 이어지게 한다.
3. `experimental_design`: Design Table의 한 행. **실험은 비교 대상(baseline)이 있는 검증만 쓴다.**
   - 라벨 일치율, 검수자 간 일치도, 학습·평가 분할의 중복 검사 같은 **데이터 품질 점검은 실험이 아니다.** `success_criteria_milestones`의 criterion(예: "중간 점검: 라벨 검수 일치율 [TBD] 이상")이나 `risks_and_fallbacks`의 대응에 쓴다.
   - 데이터 구성 방법이 구성요소(M)라면, 그 데이터로 학습한 결과를 **다른 데이터 구성 방식(예: 기존 라벨을 그대로 쓰는 방식)과 비교**하는 실험으로 검증한다. 이때 비교 대상을 baseline으로 정의한다. 지표는 구체적으로 쓴다. 성공 기준의 목표 수치가 evidence에 없으면 `[TBD: ...]`로 둔다. `failure_interpretation`에는 실패했을 때 무엇을 바꾸거나 기여를 어떻게 좁힐지 쓴다.
4. `target_claims`: 반증 가능한 한 문장. "~할 수 있다"가 아니라 "~가 B보다 ~하다"처럼 비교 대상이 있는 주장으로 쓴다. `falsifiable_condition`에 어떤 실험 결과가 나오면 기각하는지 쓴다.
5. `expected_novelty`: "X와 달리 우리는 Y" 형태. `vs`에 비교 대상 arXiv ID를 넣는다. `cot5.review`와 관련 논문의 `critical_difference`를 근거로 쓴다. 항목마다 다음 세 칸을 채운다.
   - `existing_mechanism`: 비교 대상이 **이미 가진 장치**를 근거 자료(`seed_papers`, 원문 인용문, `mechanism_overlap`)에 나온 이름 그대로 쓴다. 예: "Self-RAG의 IsSup 토큰: 생성한 문장 조각마다 근거 문서의 지지 여부를 fully/partially/no support로 판단". 비슷한 장치가 없다고 판단되면 그렇게 판단한 근거를 쓴다.
   - `difference_axis`: 그 장치와 제안이 다른 축 하나. "적용 단위", "적용 시점", "판단 대상", "판단 이후 동작", "학습 방식", "기타" 중에서 고른다.
   - `tested_by`: **이 차이가 실제로 필요한지 가리는 실험(E) ID.** 보통 가장 가까운 선행연구의 기존 장치만으로 같은 일을 하는 ablation 실험이다. 이 실험에서 차이가 없으면 해당 신규성 주장은 기각된다.
   - 검색 범위 밖까지 일반화하지 않는다. "어떤 연구도 ~하지 않는다" 대신 "검토한 문헌 범위에서 ~는 확인되지 않았다"로 쓴다.
6. `expected_contribution`: `type`을 method, resource, analysis, other 중에서 고르고 구분해서 쓴다.
7. `risks_and_fallbacks`: `cot4.requirements.vague_or_unspecified_steps`, `cot4.resource_guidance.unknowns_to_confirm`, 자원 요구사항, 가장 가까운 선행연구와 차이가 작을 위험을 근거로 쓴다. 위험마다 대안을 쓰고, 항목의 `source`에 근거 경로 하나를 쓴다.
8. `success_criteria_milestones`: 중간 점검과 최종 점검을 각각 하나 이상 쓴다.

형식 예시 (가짜 예시다. 형식만 참고한다):

{
  "experimental_design": {
    "value": [
      {"id": "E1", "validates": ["V1"], "setup": "긴 입력 세트에서 재검색 여부 판단", "metrics": ["F1"], "baselines": ["B1", "B2"],
       "success_criterion": "B2 대비 F1 개선 [TBD: 목표 폭]", "failure_interpretation": "차이가 없으면 M1 대신 고정 규칙으로 충분함을 뜻하므로 기여를 M2로 좁힌다"}
    ],
    "source": ["cot4.resource_guidance.proposed_performance_targets[0]"],
    "inferred": true
  }
}
