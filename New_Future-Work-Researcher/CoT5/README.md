논문 기반 LLM 연구 아이디어 신규성 검증 하네스

1. 목적

이 문서는 연구 아이디어가 기존 연구와 중복되는지 점검하기 위한 LLM 기반 하네스를 제안한다. 설계의 중심은 Shahid et al.의 Idea Novelty Checker이며, Si et al.의 논문별 동등성 검사, Lu et al.의 반복 검색, SPECTER2의 과학 문헌 임베딩, RankGPT의 LLM 재순위화를 함께 참고한다.

핵심 파이프라인은 다음과 같다.

아이디어 입력 → 검색 질의 생성 → 후보 논문 검색 → SPECTER2 Top-100 → 목적·메커니즘·평가·적용 분야 기반 LLM 재순위화 → Top-10 논문과 비교 → 문헌 근거가 포함된 신규성 판정

LLM의 내부 기억만으로 “새로운가?”를 판단하게 하지 않는다. 검색된 문헌을 근거로 판단하고, 검색 범위가 불충분하면 NOVEL이 아니라 UNCERTAIN을 출력하도록 한다.

2. 기반 논문

2.1 주요 논문

Simra Shahid et al., Literature-Grounded Novelty Assessment of Scientific Ideas, SDP 2025

ACL Anthology

arXiv HTML

공개 코드

Chenglei Si et al., Can LLMs Generate Novel Research Ideas? A Large-Scale Human Study with 100+ NLP Researchers, ICLR 2025

ICLR 논문

Chris Lu et al., The AI Scientist: Towards Fully Automated Open-Ended Scientific Discovery

Nature 논문

코드

Amanpreet Singh et al., SciRepEval: A Multi-Format Benchmark for Scientific Document Representations

arXiv

Weiwei Sun et al., Is ChatGPT Good at Search? Investigating Large Language Models as Re-Ranking Agents, EMNLP 2023

RankGPT 논문

2.2 출처별 차용 내용

설계 요소

출처

차용한 부분

검색 기반 신규성 평가

Shahid et al.

관련 문헌을 먼저 검색하고 LLM이 문헌에 근거해 판정

질의·예상 제목 생성

Shahid et al.; Lu et al.

아이디어로부터 키워드와 잠재적 논문 제목 생성

Seed-paper 확장

Shahid et al.

입력 seed paper의 관련 논문 추천 검색

Keyword·snippet 검색

Shahid et al.

정확한 용어 검색과 아이디어 전체를 이용한 snippet 검색 병행

SPECTER2 Top-100

Shahid et al.; Singh et al.

과학 문헌 임베딩과 cosine similarity를 이용한 1차 필터링

Facet-based RankGPT

Shahid et al.; Sun et al.

목적·메커니즘·평가·적용 분야를 기준으로 2차 순위화

Top-10 최종 판정

Shahid et al.

상위 10개 논문의 제목·초록을 최종 LLM에 제공

전문가 few-shot 예제

Shahid et al.

전문가가 판정한 아이디어·문헌·근거 예제를 프롬프트에 포함

논문별 동등성 검사

Si et al.

Top-10 각각과 아이디어를 비교하고 하나라도 동등하면 필터링

반복 검색

Lu et al.

질의 생성·검색·비교를 결론 또는 반복 한도까지 수행

3. 신규성의 운영적 정의

Idea Novelty Checker는 아이디어와 문헌을 네 가지 facet으로 비교한다.

Purpose: 해결하려는 목적이나 연구 문제

Mechanism: 제안한 기술적 접근과 작동 방식

Evaluation: 검증 방법과 실험 설계

Application domain: 적용 분야와 환경

해당 논문에서는 검색된 모든 문헌과 비교했을 때 목적, 메커니즘, 평가, 적용 분야 또는 그 조합 중 적어도 하나에서 차이가 있으면 신규 아이디어로 취급한다. 이는 전문가 formative study에서 정의한 연구용 판정 기준이며, 특허법상 신규성이나 모든 학회의 기여 기준을 뜻하지는 않는다.

실제 하네스에서는 결과를 다음처럼 구분하는 것이 안전하다.

문헌 중복 여부: 검색된 문헌 중 사실상 동등한 연구가 있는가?

차이의 위치: 목적·메커니즘·평가·적용 분야 중 무엇이 다른가?

기여 강도: 메커니즘 차이인지, 단순한 데이터·도메인·모델 교체인지?

검색 신뢰도: 충분한 문헌이 검색됐는가?

마지막 두 항목은 원 논문의 facet 구조를 실무적으로 확장한 것이다.

4. 전체 하네스

flowchart TD
    A["연구 아이디어"] --> B["검색 질의 생성"]
    A --> C["아이디어 전체 snippet 검색"]
    A --> D["Seed paper 추천 검색"]
    B --> E["후보 논문 통합·중복 제거"]
    C --> E
    D --> E
    E --> F["SPECTER2 Top-100"]
    F --> G["Facet 기반 RankGPT"]
    G --> H["Top-10 논문"]
    H --> I["논문별 동등성 검사"]
    I --> J["근거 기반 최종 판정"]

4.1 아이디어 입력 형식

{
  "title": "아이디어 제목",
  "problem": "해결하려는 연구 문제",
  "proposed_method": "제안 방법과 핵심 메커니즘",
  "motivation": "왜 필요한가",
  "evaluation_plan": "어떻게 검증할 것인가",
  "application_domain": "적용 분야",
  "seed_papers": [
    {
      "title": "",
      "doi": "",
      "arxiv_id": "2401.01234"
    }
  ],
  "cutoff_date": "2026-08-18"
}

cutoff_date는 원 논문을 그대로 재현한 요소가 아니라 시간 누출 방지를 위한 확장이다.

4.2 후보 논문 검색

Idea Novelty Checker가 사용한 주요 검색 경로는 다음과 같다.

Seed-paper 검색: 로컬 DB에서 seed arXiv ID와 CSO 키워드를 공유하는 논문 수집

Query-based 검색: LLM이 키워드와 예상 제목을 만들고 로컬 `cso_keywords` 인덱스로 검색

Idea-text 검색: 아이디어 전체에서 단어·구를 추출해 로컬 `cso_keywords` 인덱스로 검색

candidate_papers = union(
    local_cso_recommendations(seed_arxiv_ids),
    local_cso_search(generated_queries),
    local_cso_search(full_idea),
)

candidate_papers = deduplicate(candidate_papers)
candidate_papers = filter_by_date(candidate_papers, cutoff_date)

날짜 필터는 본 하네스의 추가 설계이다.

5. 검색 질의 생성 프롬프트

다음 프롬프트는 Shahid et al.의 “키워드와 잠재적 논문 제목 생성” 방법을 구현 가능한 형식으로 재구성한 것이다. 논문 부록의 프롬프트를 그대로 복제한 것은 아니다.

SYSTEM

You generate search queries for retrieving scientific papers relevant to
a proposed research idea.

Your objective is not to judge whether the idea is novel.
Your objective is to retrieve papers that may overlap with the idea.

Generate queries covering the following facets:

1. Purpose: the research objective or problem
2. Mechanism: the proposed technical method
3. Evaluation: the validation or experimental method
4. Application: the target domain or environment

Generate both keyword-based queries and plausible paper titles.
Do not generate conclusions about novelty.
Do not assume that a paper does not exist.

USER

Research idea:

Title:
{{TITLE}}

Problem and purpose:
{{PROBLEM}}

Proposed mechanism:
{{METHOD}}

Evaluation:
{{EVALUATION}}

Application domain:
{{DOMAIN}}

Generate:

1. Five purpose-oriented search queries
2. Five mechanism-oriented search queries
3. Five evaluation-oriented search queries
4. Five application-oriented search queries
5. Ten queries combining two or more facets
6. Ten plausible titles of existing papers that could overlap with this idea

Return JSON only.

{
  "purpose_queries": [],
  "mechanism_queries": [],
  "evaluation_queries": [],
  "application_queries": [],
  "combined_queries": [],
  "plausible_titles": []
}

질의 개수는 논문에서 검증된 고정값이 아니라 구현 파라미터이다.

6. 1차 재순위화: SPECTER2

Idea Novelty Checker의 기본 설정은 후보 논문과 아이디어 사이의 SPECTER2 cosine similarity를 계산해 상위 N=100개를 선택하는 것이다.

[
s_i=\frac{e_{idea}\cdot e_{paper_i}}{\lVert e_{idea}\rVert\lVert e_{paper_i}\rVert}
]

아이디어 입력: 제목 + 아이디어 설명

논문 입력: 제목 + 초록

출력: cosine similarity 상위 100개

SPECTER2는 과학 문헌의 검색과 순위화 작업을 고려한 문헌 표현 모델이므로 일반-purpose embedding보다 이 사용 사례에 직접적인 연구 근거가 있다.

7. 2차 재순위화: Facet-based RankGPT

Idea Novelty Checker는 일반적인 주제 관련성 대신 네 facet을 사용하도록 RankGPT 기준을 변경한다.

우선순위는 다음과 같다.

네 facet이 모두 일치하는 논문

적용 분야와 목적이 일치하는 논문

목적·메커니즘·평가 일부가 일치하는 논문

넓은 주제나 용어만 공유하는 논문

SYSTEM

You are a scientific literature re-ranking system.

Rank candidate papers according to how strongly they overlap with the
research idea. Evaluate relevance using four facets:

1. Application domain
2. Purpose
3. Mechanism
4. Evaluation

Ranking priority:

A. Papers matching all four facets
B. Papers matching application domain and purpose
C. Papers matching purpose, mechanism, or evaluation
D. Papers sharing only a broad topic or terminology

A paper using the same terminology but a different mechanism should not
automatically rank above a paper using different terminology but the
same mechanism.

Do not evaluate novelty yet.
Return only the ordered paper identifiers.

USER

Research idea:
{{IDEA}}

Candidate papers:
{{PAPER_TITLES_AND_ABSTRACTS}}

Return:
{
  "ranked_paper_ids": ["P17", "P3", "..."]
}

8. 논문별 동등성 검사

Si et al.은 Top-10 논문 각각과 아이디어를 비교하고 하나라도 동등하다고 판단되면 해당 아이디어를 필터링했다. 이를 다음처럼 구현한다.

SYSTEM

Compare one research idea against one retrieved paper.

Determine whether the paper presents an equivalent research idea.

Compare:

1. Research problem and purpose
2. Technical mechanism
3. Evaluation design
4. Application domain
5. The combination and interaction of these facets

Equivalent means that the paper contains the same core research
contribution, even if terminology, model names, datasets, or wording differ.

Do not classify the ideas as equivalent merely because they share a broad topic.

USER

Research idea:
{{IDEA}}

Candidate paper:
Title: {{TITLE}}
Abstract: {{ABSTRACT}}

Return JSON:

{
  "equivalent": false,
  "purpose_overlap": "",
  "mechanism_overlap": "",
  "evaluation_overlap": "",
  "application_overlap": "",
  "critical_difference": "",
  "evidence_from_abstract": "",
  "confidence": 0.0
}

results = [compare(idea, paper) for paper in top_10]

if any(result.equivalent for result in results):
    verdict = "NOT_NOVEL"

9. 최종 신규성 판정 프롬프트

원 논문은 아이디어, Top-10 논문의 제목·초록, 전문가 few-shot 예제를 최종 LLM에 제공해 novel/not novel을 판정한다. 아래 프롬프트는 여기에 검색 불충분을 나타내는 UNCERTAIN을 추가한 안전성 확장이다.

SYSTEM

You evaluate the novelty of a scientific research idea using only the
provided literature.

Novelty definition:

An idea is NOVEL if it differs from every retrieved paper in at least
one core facet:

1. Purpose: the research objective
2. Mechanism: the technical approach
3. Evaluation: the validation method
4. Application domain: the target field or environment

An idea may also be NOVEL if it presents a unique combination of these facets.

An idea is NOT_NOVEL if one retrieved paper presents an equivalent
combination of the idea's core facets.

Important rules:

- Base the decision only on the provided papers.
- Do not use unsupported knowledge from memory.
- Do not treat shared keywords alone as equivalence.
- Do not treat different wording alone as novelty.
- Identify the strongest overlapping paper.
- Explicitly describe similarities and differences.
- If the retrieved literature is insufficient, report UNCERTAIN rather
  than claiming that no prior work exists.

{{EXPERT_LABELED_EXAMPLES}}

USER

Research idea:
{{IDEA}}

Retrieved papers:
{{TOP_10_PAPER_TITLES_AND_ABSTRACTS}}

Return JSON only:

{
  "classification": "NOVEL|NOT_NOVEL|UNCERTAIN",
  "strongest_overlapping_paper_id": "",
  "facet_comparison": {
    "purpose": {"same": false, "explanation": ""},
    "mechanism": {"same": false, "explanation": ""},
    "evaluation": {"same": false, "explanation": ""},
    "application_domain": {"same": false, "explanation": ""},
    "combination": {"same": false, "explanation": ""}
  },
  "rationale": "",
  "missing_literature_or_uncertainty": [],
  "confidence": 0.0
}

10. 반복 검색

AI Scientist의 반복적 검색 아이디어를 사용하되, 결론에 실패했을 때 자동으로 NOVEL을 반환하지 않는다.

for iteration in range(MAX_ITERATIONS):
    queries = generate_queries(idea, previous_results)
    candidates += search(queries)
    top_100 = embedding_rank(candidates)
    top_10 = facet_rerank(top_100)
    verdict = novelty_check(idea, top_10)

    if verdict.classification in ["NOVEL", "NOT_NOVEL"] \
       and verdict.confidence >= threshold:
        break

if no_clear_decision:
    verdict = "UNCERTAIN"

11. 전문가 few-shot 데이터

Shahid et al.은 67개의 합의 판정 사례를 수집했다.

Novel: 39개

Not novel: 28개

훈련: 35개

테스트: 32개

해당 데이터셋에서는 전문가 아이디어 예제 15개를 제공한 설정이 가장 좋은 성능을 보였고, 대략 Accuracy 0.78, Precision 0.77, Recall 0.76, F1 0.77을 기록했다. 그러나 데이터가 작고 같은 전문가가 예제와 테스트 판정을 수행했다는 한계가 있다.

분야별 하네스에서는 다음 형식으로 자체 데이터를 축적하는 것이 좋다.

{
  "idea": "...",
  "retrieved_papers": ["..."],
  "label": "NOVEL",
  "expert_reasoning": "기존 연구와 목적은 같지만 메커니즘이 다르다."
}

예제에는 명백한 동일 아이디어뿐 아니라 표현만 다른 동일 연구, 목적만 같은 연구, 메커니즘만 같은 연구, 단순 모델 교체, 새로운 도메인 적용, 기존 요소의 새로운 조합과 같은 경계 사례가 포함되어야 한다.

12. 평가와 절제 실험

12.1 분류 평가

Accuracy

Precision

Recall

F1

전문가와의 일치율

필요하면 Cohen's kappa

12.2 파이프라인 절제 실험

실험

Keyword

Snippet

Embedding

Facet RankGPT

A

O

X

X

X

B

X

O

X

X

C

O

O

O

X

D

O

O

O

일반 relevance RankGPT

E

O

O

O

Facet RankGPT

Idea Novelty Checker의 절제 실험에서 완전한 시스템의 Top-10과 비교한 평균 overlap은 다음과 같았다.

방식

Top-10 평균 overlap

일반 relevance RankGPT

7.97

Embedding filtering

7.93

Snippet retrieval

2.88

Keyword retrieval

1.17

논문은 embedding과 facet-based re-ranking을 결합한 완전한 시스템이 핵심 문헌을 Top-10에 배치하는 데 중요하다고 결론 내린다.

12.3 추가 권장 평가

다음은 원 논문의 평가를 확장한 항목이다.

정답 선행논문 Recall@10·Recall@100

동일 아이디어 패러프레이즈에 대한 판정 일관성

근거 문장이 실제 결론을 지지하는 비율

정답 선행논문이 검색되지 않았을 때 UNCERTAIN을 출력하는 비율

기준일 이후 문헌을 사용하는 temporal leakage 비율

프롬프트 변경에 대한 판정 안정성

13. 논문 직접 차용과 추가 설계의 구분

구성

구분

설명

검색→임베딩→facet reranking→LLM 비교

논문 직접 차용

Idea Novelty Checker

Purpose·mechanism·evaluation·application 비교

논문 직접 차용

Idea Novelty Checker

Top-100→Top-10

논문 직접 차용

Idea Novelty Checker 기본 설정

SPECTER2

논문 직접 차용

Idea Novelty Checker·SciRepEval

전문가 few-shot 15개

논문 실험 설정

특정 데이터셋의 최적값이며 보편적 상수는 아님

하나의 논문이라도 equivalent면 필터링

논문 직접 차용

Si et al.

반복 검색

논문 직접 차용

AI Scientist

UNCERTAIN 클래스

추가 설계

검색 실패를 신규성으로 오판하지 않기 위함

기준 날짜 필터

추가 설계

시간 누출 방지

Facet별 JSON 근거 저장

추가 설계

추적성과 평가 가능성 향상

기여 강도 별도 평가

추가 설계

단순 도메인·모델 교체와 메커니즘 차이를 분리

원자 주장·관계 그래프

향후 확장

위 논문들에서 직접 검증되지 않음

Prosecutor·Defender·Judge 에이전트

향후 확장

위 논문들에서 직접 검증되지 않음

임의의 신규성 가중 점수

제외 권장

검증된 척도가 아님

14. 권장 MVP

입력
└─ 연구 아이디어 + 선택적 seed paper + 기준일

검색
├─ 로컬 CSO seed-paper 유사 검색
├─ 로컬 CSO query 검색
└─ 로컬 CSO idea-text 검색

후보 처리
├─ arXiv ID 중복 제거
└─ 기준일 필터링

1차 순위
└─ SPECTER2 cosine similarity Top-100

2차 순위
└─ Purpose·mechanism·evaluation·application RankGPT Top-10

평가
├─ Top-10 각각과 equivalence 비교
├─ 전문가 예제 기반 최종 판정
└─ NOVEL / NOT_NOVEL / UNCERTAIN + 근거

처음에는 위 baseline을 구현한 뒤 검색 방법, 임베딩, facet reranker, 전문가 예제의 효과를 각각 절제 실험해야 한다. 원자 주장 분해나 멀티에이전트 토론 같은 확장은 baseline 성능을 확인한 후 독립 모듈로 추가해야 어떤 변경이 실제 개선을 만들었는지 측정할 수 있다.

15. 한계

Top-10에 진짜 선행연구가 포함되지 않으면 최종 LLM도 올바르게 판정할 수 없다.

제목과 초록만으로 세부 메커니즘을 판단하기 어려울 수 있다.

신규성 정의가 전문가와 분야에 따라 달라진다.

전문가 few-shot 결과는 예제 선택과 프롬프트 표현에 민감하다.

NOVEL은 “검색 범위에서 동등한 문헌을 찾지 못했다”는 의미이지, 전 세계에 선행연구가 없다는 증명이 아니다.

연구 신규성 평가는 특허 신규성·진보성에 대한 법률 판단을 대신하지 않는다.

따라서 최종 보고서에는 반드시 검색 데이터베이스, 검색일, 기준일, 사용 질의, 후보 수, Top-10 문헌, 판정 근거와 미확인 범위를 함께 기록해야 한다.

16. 구현

Shahid et al.의 공식 구현체(`simra-shahid/idea_novelty_checker`)가 GitHub에 공개돼 있어, 직접 재구현하는 대신 `external/idea_novelty_checker`에 git submodule로 참조하고 CoT5는 그 위에 얇은 래퍼만 둔다. 라이선스가 명시되지 않은 저장소라 코드를 복사(vendoring)하지 않고 submodule로만 연결한다.

16.1 submodule에 가한 로컬 patch

원본 코드는 그대로 두는 것이 원칙이지만, CoT5 실행 환경과 로컬 문헌 DB를 위해 다음 지점을 patch했다(업스트림에 반영된 것이 아니라 이 저장소에서만 적용되는 변경이다).

- `noveltychecker/ranking/embedding.py`: Hugging Face의 `allenai/specter2_base`와 retrieval/proximity adapter `allenai/specter2`를 최초 실행 시 내려받는다. 아이디어와 후보 논문의 `title [SEP] abstract`를 같은 로컬 SPECTER2 공간에서 임베딩하고 CLS 토큰 벡터로 cosine similarity를 계산한다. 모델은 프로세스당 한 번 지연 로드되며 `SPECTER2_DEVICE=auto`일 때 CUDA가 있으면 GPU, 없으면 CPU를 사용한다.
- `noveltychecker/models/idea_novelty_checker/pipeline.py`: `run_ideanoveltychecker`에 `cutoff_date` 매개변수를 추가해, RankGPT 재정렬이 끝난 후보에서 top-k로 자르기 *전에* 기준일 이후 문헌을 제거하도록 했다(4.2절의 시간 누출 방지).

16.2 CoT5가 새로 작성한 코드 (`src/cot5/`)

README가 "논문 직접 차용"이 아니라 "추가 설계"로 표시한 부분들이다.

- `idea.py`: 4.1절 JSON 스키마 ↔ 원본이 기대하는 단일 문자열(`<IDEA> ... </IDEA>`) 변환
- `cutoff.py`: 기준일 필터(순수 함수, API 키 없이 테스트 가능)
- `verdict.py`: novel/not novel 두 값뿐인 원본 출력을 NOVEL/NOT_NOVEL/UNCERTAIN으로 확장. 비교할 문헌을 아예 찾지 못했을 때만 UNCERTAIN으로 강등한다(문헌이 1건이라도 있으면 novel 판정을 그대로 신뢰 — 애초에 "최소 3건" 같은 임계값은 원 논문이 검증한 게 아니라 CoT5가 임의로 얹은 과잉 보수였다고 판단해 뺐다. 순수 함수, 테스트 가능)
- `provider.py`, `schemas.py`, `equivalence.py`: **8절(Si et al. 논문별 동등성 검사)의 실제 구현.** 이 부분은 원래 이 README가 "논문 직접 차용"이라고 표시했지만, 실제로는 submodule 어디에도 구현돼 있지 않았다 — `get_review()`는 Top-10 전체를 한 번에 보고 종합 판단만 하고, "각 논문과 개별 비교해 하나라도 동등하면 확정 필터링"하는 8절의 `compare()`/`equivalent` 루프는 코드로 존재하지 않았다. `equivalence.py`가 Top-10 각각에 대해 8절 프롬프트(한국어로 새로 작성, 신뢰할 수 없는 데이터 처리 원칙 포함)로 구조화된 비교를 수행하고, `verdict.py: apply_equivalence_override`가 "하나라도 동등하면 종합 판단(NOVEL이든 UNCERTAIN이든)보다 우선해 NOT_NOVEL로 확정"한다.
- `pipeline.py`: 위 조각들과 submodule의 `run_ideanoveltychecker`를 엮는 오케스트레이션. 반복 검색은 실패 시 최대 2회까지만 재시도하는 보수적 bounded loop이며, README 10절이 말하는 AI Scientist식 "질의를 매번 새로 만들어가는 적응적 반복 검색"을 그대로 구현한 것은 아니다(같은 아이디어 문자열로는 결정적으로 같은 검색 결과가 나오므로, 진짜 반복 확장을 하려면 회차마다 질의를 변형하는 로직이 추가로 필요하다 — 다음 단계로 남겨둔다)
- `config.py`: submodule import 경로 등록, 상대경로 파일을 여는 submodule 코드를 위한 작업 디렉터리 전환
- `cli.py`: `cot5 idea.json` CLI

16.3 설치와 실행

CoT1.py와 마찬가지로 프로젝트 루트에서 `CoT5.py`를 직접 실행할 수 있다.
`CoT5/`에는 신규성 검사 라이브러리와 외부 코드가 남아 있으며, 루트 스크립트가 이를 불러온다.

```powershell
cd D:\Future-Work-Researcher
python CoT5.py CoT5\examples\idea.json --config CoT5\config.yml
python CoT5.py D:\path\to\future_work_result.json --config CoT5\config.yml
```

아래 설치 명령은 기존 `cot5` 콘솔 명령을 사용할 때 필요하다.

```powershell
cd D:\Future-Work-Researcher\CoT5
git submodule update --init --recursive
python -m pip install -e .
copy config.yml.example config.yml   # OPENAI_API_KEY와 ARXIV_DB_PATH 채우기
cot5 examples\idea.json
```

### Future-Work-Researcher 연결

`Future-Work-Researcher`가 반환한 최종 JSON(`future_work_proposals` 배열)을 파일로 저장하면
별도 변환 없이 같은 CLI에 전달할 수 있다. 각 제안은 순서대로 CoT5 신규성 검사를 거치며
결과는 `{"results": [...]}` 형식으로 출력된다. Future-Work-Researcher 소스나 출력 스키마는
변경하지 않는다.

```powershell
cot5 D:\path\to\future_work_result.json > cot5_results.json
```

CoT4 실현가능성 검증을 먼저 통과시킨 뒤 CoT5를 실행하려면 저장소 루트의
`run_cot4_then_cot5.py`를 사용한다. 이 통합 실행기는 CoT4 결과가 모든 제안에
대해 `FEASIBLE`인 경우에만 CoT5를 호출하며, 그렇지 않으면 CoT5를 건너뛴다.

16.4 테스트

API 키 없이 실행 가능한 순수 로직(`idea.py`/`cutoff.py`/`verdict.py`)만 단위 테스트로 커버한다. `pipeline.py`의 실제 검색·LLM 호출 경로는 API 키가 있어야 하므로 이 저장소의 자동 테스트 범위 밖이다.

```powershell
python -m pytest tests -v
```
