논문 기반 아이디어 실현가능성(Feasibility) 검증 하네스

1. 목적

이 문서는 CoT5(신규성 검증)에서 분리한 축을 다룬다. CoT5는 "이 아이디어가 이미 존재하는 문헌/구현과 겹치는가"를 검증하고, CoT4는 "겹치지 않더라도 이 아이디어가 기술적·방법론적으로 실행 가능한가"를 검증한다. 두 축은 독립적이다 — 완전히 새로운 아이디어도 실행 불가능할 수 있고, 이미 존재하는 아이디어도 그 자체로는 실행 가능할 수 있다.

핵심 파이프라인은 다음과 같다.

아이디어 입력 → 구현 요구사항 추출(자원·데이터·의존성·구현 명세) → 제약 조건 대조 → 방법론적 정합성 점검(목표-방법 논리 비약 탐지) → 회의적 프롬프팅으로 낙관 편향 완화 → 근거가 포함된 FEASIBLE/QUESTIONABLE/INFEASIBLE 판정

LLM이 아이디어를 "그럴듯해 보인다"는 인상만으로 통과시키지 않는다. SoundnessBench가 보고한 낙관 편향(optimism bias) — 모델이 실제로는 타당성 낮은 제안도 타당하다고 평가하는 경향 — 을 이 하네스의 핵심 위험으로 명시하고, 이를 완화하는 프롬프트 설계와 사람 확인 절차를 둔다.

2. 기반 논문

2.1 주요 논문

Chenglei Si et al., Can LLMs Generate Novel Research Ideas? A Large-Scale Human Study with 100+ NLP Researchers, ICLR 2025 (arXiv:2409.04109) — CoT5와 같은 논문이지만 다른 부분을 차용한다: novelty가 아니라 리뷰 폼의 Feasibility 축.

Yilun Zhao / (SoundnessBench 저자), SoundnessBench: Can Your AI Scientist Really Tell Good Research Ideas from Bad Ones?, 2026 (arXiv:2605.30329)

Chris Lu et al., The AI Scientist: Towards Fully Automated Open-Ended Scientific Discovery — CoT5와 같은 논문이지만 반복 검색이 아니라 자동 동료평가의 rigor(엄밀성) 축을 차용한다.

2.2 출처별 차용 내용

| 설계 요소 | 출처 | 차용한 부분 |
|---|---|---|
| Feasibility 운영적 정의 | Si et al. | 사람 리뷰어가 실제로 지적한 실현가능성 실패 유형: 계산 자원 부족(대규모 파인튜닝 등), 수동 데이터 수집의 시간 소요, 구현 세부사항 불명확 |
| 회의적(skeptical) 프롬프팅 | SoundnessBench | "aggressive prompting"이 false positive(부당 통과)를 false negative(부당 반려) 쪽으로 옮긴다는 실증 결과 — 어느 쪽으로도 완전히 치우치지 않도록 설계에 반영 |
| 낙관 편향 경고 | SoundnessBench | 모델이 저타당성 제안도 타당하다고 판정하는 경향이 있다는 벤치마크 결과. 최종 판정을 자동 승인/거부가 아니라 "사람이 확인해야 할 근거 목록"으로 설계하는 근거 |
| 방법론적 엄밀성(rigor) 축 | AI Scientist (Lu et al.) | 4개 자동 동료평가 축(독창성/엄밀성/명료성/중요도) 중 rigor를 방법론적 정합성 점검에 반영 |
| Facet 기반 구조화 출력 | CoT5 설계 재사용 | purpose/mechanism 등 facet을 JSON으로 구조화해 근거를 남기는 패턴을 CoT4의 요구사항 추출에도 동일하게 적용(신규 근거 논문 없이 CoT5 설계를 그대로 재사용) |

3. CoT5와의 경계

| 질문 | 담당 |
|---|---|
| 이미 존재하는가? (문헌·구현과의 중복) | CoT5 |
| 존재하지 않더라도 실행 가능한가? (자원·방법론·논리) | CoT4 |

CoT5의 산출물(`rejected`/`helpful_links`)과 CoT4의 산출물(`feasibility_verdict`)은 서로를 대체하지 않는다. 하나의 아이디어는 NOVEL이면서 INFEASIBLE일 수 있고, NOT_NOVEL이면서 FEASIBLE일 수 있다. 두 결과를 합쳐 최종 채택 여부를 정하는 것은 이 하네스의 범위 밖이며, 사람이 결정한다.

4. 실현가능성의 운영적 정의

Si et al.의 리뷰 폼과 그 질적 분석(8.1절)에서 실제로 반복 지적된 실패 유형을 그대로 하네스의 점검 항목으로 삼는다.

- Resource feasibility: 요구되는 연산 자원(GPU/시간)·데이터 규모가 명시된 제약(예산·기간·보유 장비) 안에서 실현 가능한가
- Data feasibility: 필요한 데이터를 수집/확보할 수 있는가, 수동 수집이 필요하다면 소요 시간이 현실적인가
- Implementation clarity: 제안된 방법이 실제로 구현할 수 있을 만큼 구체적으로 기술되어 있는가, 아니면 핵심 단계가 생략되어 있는가
- Methodological soundness: 제안한 방법이 목표를 달성한다는 논리에 비약이 없는가(AI Scientist의 rigor 축)

특허법상 실시가능성이나 특정 기관의 승인 기준을 뜻하지 않는다. "이 정보만으로 구현을 시작할 수 있는가"라는 실무적 질문에 대한 판정이다.

5. 전체 하네스

```
flowchart TD
    A["아이디어 입력"] --> B["구현 요구사항 추출"]
    B --> C["제약 조건 대조(선택적)"]
    B --> D["방법론적 정합성 점검"]
    C --> E["회의적 재검토"]
    D --> E
    E --> F["근거 기반 FEASIBLE / QUESTIONABLE / INFEASIBLE"]
```

5.1 아이디어 입력 형식

CoT5와 동일한 아이디어 스키마를 재사용하고, 실현가능성 판정에 필요한 제약 조건을 선택적으로 추가한다.

```json
{
  "title": "아이디어 제목",
  "problem": "해결하려는 문제",
  "proposed_method": "제안 방법과 핵심 메커니즘",
  "evaluation_plan": "어떻게 검증할 것인가",
  "constraints": {
    "compute_budget": "",
    "data_availability": "",
    "timeline": "",
    "team_skills": ""
  }
}
```

`constraints`가 비어 있으면 일반적 실현가능성(구현 명세의 구체성, 논리적 정합성)만 판정하고, 자원 특이적 판정(이 예산으로 가능한가)은 `missing_constraints` 경고와 함께 생략한다.

6. 요구사항 추출 프롬프트

SYSTEM

You extract the concrete implementation requirements of a proposed idea.
Do not judge feasibility yet. Only extract what the idea requires to be built.

Identify:
1. Compute/infrastructure requirements
2. Data requirements (source, volume, collection method)
3. Key implementation steps that must be specified to build this
4. Dependencies on external tools, APIs, or unpublished components

Flag any step described only in vague or aspirational terms
(e.g., "use a novel technique to..." without specifying what technique).

USER

Idea:
{{IDEA}}

Return JSON only:

```json
{
  "compute_requirements": "",
  "data_requirements": "",
  "implementation_steps": [],
  "external_dependencies": [],
  "vague_or_unspecified_steps": []
}
```

7. 실현가능성 판정 프롬프트

SoundnessBench의 낙관 편향 결과를 반영해, "그럴듯하다"가 아니라 구체적 결함을 찾도록 명시적으로 지시한다. 동시에 과도하게 공격적인 프롬프팅은 false negative를 늘린다는 같은 논문의 결과를 반영해, 결함에는 반드시 근거(추출된 요구사항 중 어떤 항목 때문인지)를 남기도록 강제한다.

SYSTEM

You evaluate whether a proposed idea is technically feasible to implement,
using only the extracted requirements and any stated constraints.

Do not reward ideas merely for sounding plausible or well-written.
Actively look for the following failure modes before concluding FEASIBLE:

1. Resource requirements exceeding stated constraints
2. Data that is not realistically obtainable in the stated timeline
3. Implementation steps left vague or unspecified
4. Logical gaps between the proposed method and the stated goal

Classification:
- FEASIBLE: requirements are concrete and within any stated constraints,
  no unresolved logical gap between method and goal
- QUESTIONABLE: at least one concern above applies, but it is not fatal
- INFEASIBLE: a requirement clearly exceeds stated constraints, or the
  method could not achieve the stated goal as described

If constraints were not provided, do not assume unlimited resources;
classify resource-dependent concerns as QUESTIONABLE with a note that
constraints are missing, not as FEASIBLE.

USER

Extracted requirements:
{{EXTRACTED_REQUIREMENTS}}

Stated constraints:
{{CONSTRAINTS}}

Return JSON only:

```json
{
  "classification": "FEASIBLE|QUESTIONABLE|INFEASIBLE",
  "resource_concern": {"present": false, "explanation": ""},
  "data_concern": {"present": false, "explanation": ""},
  "implementation_concern": {"present": false, "explanation": ""},
  "methodological_concern": {"present": false, "explanation": ""},
  "missing_constraints": [],
  "rationale": "",
  "confidence": 0.0
}
```

8. 출력 계약과 사람 확인

- `classification`은 최종 결정이 아니라 검토 우선순위를 정하기 위한 신호다.
- SoundnessBench가 보인 낙관 편향 때문에, FEASIBLE 판정도 그대로 신뢰하지 않고 `rationale`과 각 `*_concern.explanation`을 사람이 확인해야 한다.
- `constraints`가 비어 있는데 `classification`이 FEASIBLE이면 경고를 남긴다(자원 제약을 확인하지 못한 채 내린 판정이므로).

9. 한계

- 이 하네스는 텍스트로 기술된 요구사항만 보고 판단하므로, 실제 프로토타입 실험 없이는 결론이 틀릴 수 있다.
- SoundnessBench 자체가 12개 최신 LLM 전반에서 낙관 편향을 보고했으므로, 특정 모델 하나의 판정에 의존하지 않는 것이 안전하다.
- "회의적 프롬프팅"은 false negative(실행 가능한 아이디어를 부당하게 거부)를 늘릴 수 있으므로, INFEASIBLE 판정도 최종 거부 근거로 자동 사용해서는 안 된다.
- CoT5의 신규성 판정과 이 문서의 실현가능성 판정은 서로 다른 질문에 답하며, 하나가 다른 하나를 대체하지 않는다.

10. 구현

`src/cot4/`에 6~7절의 두 프롬프트를 그대로 옮겼다. CoT5와 달리 외부 GitHub 구현체를 재사용할 대상이 없어(SPECTER2/RankGPT 같은 검색·재순위화가 필요 없는, 순수 2단계 LLM 판정이라) 새로 작성했다.

- `idea.py`: 5.1절 JSON 스키마(구조화 입력) ↔ 프롬프트에 넣을 텍스트 변환. `Constraints.is_empty()`로 "제약 조건이 비어 있는가"를 코드에서 직접 판단한다.
- `schemas.py`: 6·7절 프롬프트의 JSON 출력 형식을 그대로 OpenAI structured output 스키마로 옮김.
- `pipeline.py`: 요구사항 추출 → 실현가능성 판정 2단계 호출. **8절의 "constraints 비어있는데 FEASIBLE이면 경고"** 규칙은 LLM의 `missing_constraints` 자기보고에만 맡기지 않고, 코드에서 `idea.constraints.is_empty() and judgment["classification"] == "FEASIBLE"`로 직접 강제한다.
- `provider.py`: OpenAI structured output 호출 래퍼(CoT5의 예전 구현과 동일한 패턴).

설치와 실행:

CoT1.py와 마찬가지로 프로젝트 루트에서 `CoT4.py`를 직접 실행할 수 있다.
`CoT4/`에는 기존 라이브러리와 테스트가 지원 코드로 남아 있다.

```powershell
cd D:\Future-Work-Researcher
python CoT4.py CoT4\examples\idea.json
python CoT4.py D:\path\to\future_work_result.json
```

기존 `cot4` 콘솔 명령을 사용할 경우에는 아래처럼 설치한다.

```powershell
cd D:\Future-Work-Researcher\CoT4
python -m pip install -e .
$env:OPENAI_API_KEY="sk-..."
cot4 examples\idea.json
```

### Future-Work-Researcher 연결

`Future-Work-Researcher`의 최종 JSON(`future_work_proposals` 배열)을 그대로 입력할 수 있다.
각 제안은 순서대로 CoT4 실현가능성 검사를 거치며 `{"results": [...]}`가 출력된다.
공통 자원 제약을 제공하려면 최상위에 선택적인 `constraints` 객체를 추가할 수 있다.
원본 Future-Work-Researcher의 코드와 출력 스키마는 수정하지 않는다.

```powershell
cot4 D:\path\to\future_work_result.json > cot4_results.json
```

### 통합 실행 순서: CoT4 → CoT5

Future-Work 결과에 대해 두 검사를 연결할 때는 저장소 루트의
`run_cot4_then_cot5.py`를 사용한다.

```powershell
cd D:\Future-Work-Researcher
python run_cot4_then_cot5.py D:\path\to\future_work_result.json `
  --cot5-config CoT5\config.yml > downstream_results.json
```

CoT4가 모든 제안을 `FEASIBLE`로 판정한 경우에만 CoT5가 실행된다.
하나라도 `QUESTIONABLE`, `INFEASIBLE` 또는 검증 오류이면 CoT5는 호출되지
않고 결과에 `"status": "skipped"`로 기록된다.

테스트(API 키 없이 FakeProvider로 실행 가능):

```powershell
python -m unittest discover -s tests -v
```
