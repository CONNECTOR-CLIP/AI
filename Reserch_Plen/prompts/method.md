## 이번에 채울 묶음: 제안 방법 (method)

연구계획서 1.2절 "제안 방법"과 1.3절 "연구 대상 및 데이터"의 재료다.
`previous_groups.problem`에 이미 정한 한계(L)가 있다.

작성 요령:

1. `proposed_method`: `future_work.proposed_direction`을 중심으로 핵심 개념을 2~3문장으로 쓴다. 구성요소 세부는 넣지 않는다.
   - `future_work.proposed_direction`에 나오는 **출력 동작**(예: "인용을 붙인 거절이나 외부 지식 요청을 생성")을 빠짐없이 핵심 동작으로 쓴다.
   - 실험(E)이나 주장(C)이 평가할 동작을 "별도 확장", "추후 연구", "범위 밖"으로 미루지 않는다. 미루려면 실험과 주장에서도 그 동작을 빼야 한다. 방법과 검증의 대상이 같아야 한다.
   - 구체적 형식(인용 표기 방식 등)이 정해지지 않았으면 동작은 핵심에 두고 형식만 `[TBD: ...]`로 남긴다.
2. `method_components`: 2~5개.
   - `cot4.requirements.implementation_steps`를 참고하되, 구현 단계를 그대로 옮기지 않는다. 구성요소는 **방법이 무엇을 하는지**를 나눈 것이다.
   - **평가·벤치마크·실험 단계는 구성요소가 아니다.** 이것은 validation 묶음에서 다룬다.
   - "어휘에 토큰 추가", "라이브러리 설치"처럼 연구 내용이 없는 공학 작업은 별도 구성요소로 두지 말고, 그것을 쓰는 구성요소의 설명에 합친다.
   - 학습 데이터를 어떻게 만드는지(라벨 정의, 합성 방법)가 방법의 핵심이면 별도 구성요소로 둔다.
   - 결정 규칙이나 임계값처럼 "언제 어떤 동작을 하는지" 정하는 부분이 있으면 별도 구성요소로 둔다.
   - 각 구성요소의 `addresses`에는 그것이 해결하는 한계 ID(L)를 넣는다. 모든 구성요소가 적어도 하나의 L을 다룬다.
   - 어떤 L도 다루지 않는 구성요소는 넣지 않는다.
3. `component_relations`: 구성요소 사이에 데이터나 신호가 흐르는 방향을 `from` → `to`로 쓴다. 이번 묶음의 M ID만 쓴다.
4. `data_and_subjects`: `cot4.requirements.data_requirements`, `cot4.resource_guidance.data_resources`, `external_dependencies`를 근거로 쓴다. 각 항목의 `status`는 "확보", "구축 필요", "확인 필요" 중 하나 또는 `[TBD: ...]`로 쓴다. 실제 데이터셋 이름이 evidence에 없으면 지어내지 말고 `[TBD: 데이터셋 목록 확정 필요]`로 둔다.
5. `research_objective`: "~를 위해 ~를 개발하고 ~로 검증한다" 형태의 한 문장.

형식 예시 (가짜 예시다. 형식만 참고한다):

{
  "method_components": {
    "value": [
      {"id": "M1", "name": "재검색 판단기", "description": "입력 길이와 불확실성을 보고 재검색 여부를 결정한다.", "addresses": ["L1"]}
    ],
    "source": ["cot4.requirements.implementation_steps[0]"],
    "inferred": true
  },
  "component_relations": {
    "value": [{"from": "M1", "to": "M2", "relation": "M1의 결정이 M2의 검색 호출을 일으킨다"}],
    "source": [],
    "inferred": true
  }
}
