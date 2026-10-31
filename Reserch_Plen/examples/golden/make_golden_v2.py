"""정답 예시(golden) v2를 실제 evidence 경로로 다시 만든다. Reserch_Plen 폴더에서 PYTHONPATH=src로 실행한다."""
import json
from pathlib import Path

from research_plan.evidence import build_evidence
from research_plan.extract import rule_errors, search_scope
from research_plan.inputs import load_run
from research_plan.schemas import SCHEMA_VERSION
from research_plan.write import (
    check_llm_output, check_reader_text, check_short_title, check_skeleton_structure,
    render_paper_skeleton, render_research_plan,
)
from research_plan.validate import validate_paper_skeleton, validate_research_plan

RUN = Path("data/cot45_public_run_20261029_154552")
OUT = Path("examples/golden/idea06_unsupported_token")
evidence = build_evidence(load_run(RUN), 6)


def w(value, source, inferred):
    return {"value": value, "source": source, "inferred": inferred}


fields = {
    "research_topic": w(
        "검색 근거 전체가 질의를 뒷받침하지 못하는 상태를 응답 단위로 학습하고, 그 상태에서 근거를 표시한 거절 또는 외부 지식 요청을 생성하는 검색 증강 생성",
        ["future_work.proposed_direction", "cot5.review"], False),
    "research_background": w(
        "RAG(2005.11401)는 검색한 문서를 조건으로 답을 생성하며, 생성에 쓴 문서를 근거(provenance)로 보여주는 것을 목표로 한다. "
        "Self-RAG(2310.11511)는 reflection token으로 검색 필요 여부를 정하고, 검색한 문서의 관련성과 생성한 문장 조각이 문서에 의해 지지되는지를 스스로 평가한다.",
        ["cot1.P1.subgoals[0]", "cot1.P1.subgoals[1]", "cot1.P2.subgoals[0]", "cot1.P2.subgoals[1]"], False),
    "research_problem": w(
        "'미지원 질의'를 검색된 근거 문서 집합 안에 정답을 뒷받침하는 문서가 없는 질의로 정의할 때, 응답 단위의 미지원 상태를 학습한 모델은 "
        "Self-RAG의 기존 지지 판단 신호만 쓰는 방식보다 미지원 질의를 더 정확히 가려내고, 무엇을 검토했고 무엇이 부족한지 근거를 표시해 거절하거나 외부 지식을 요청하는가?",
        ["future_work.background_and_gap", "future_work.proposed_direction", "cot2.P2.candidates[0]"], True),
    "limitations_of_existing_approaches": w([
        {"id": "L1", "text": "Self-RAG는 사람 평가(S&P)에서 모델이 irrelevant 또는 no support를 예측한 사례를 고려하지 않았다고 밝힌다. 따라서 그 평가는 근거가 없다고 판단된 경우의 응답 품질을 보여주지 않는다.", "cites": ["2310.11511"]},
        {"id": "L2", "text": "Self-RAG의 지지 판단은 생성한 문장 조각과 개별 문서 사이에서 이루어지고, 생성 중 조각을 고르는 데 쓰인다. 근거 문서 집합 전체가 질의에 답하기에 부족한지를 응답 단위로 판단해 응답 방식을 바꾸는 장치는 이 논문의 목표에 포함되어 있지 않다.", "cites": ["2310.11511"]},
        {"id": "L3", "text": "근거 없는 주장을 다루는 관련 연구는 생성한 뒤에 주장을 탐지하거나(ORION) 인용 오류를 교정한다(FineRef). 생성 시점에 응답 방식을 거절이나 외부 지식 요청으로 바꾸지는 않는다.", "cites": ["2504.15771", "2602.18437"]},
        {"id": "L4", "text": "근거가 부족할 때 질의를 바꿔 검색을 반복하는 방식(Self-MedRAG)은 근거가 끝내 없을 때의 응답 형식을 다루지 않는다.", "cites": ["2601.04531"]},
    ], ["cot2.P2.candidates[0]", "cot1.P2.subgoals[1]", "cot5.paper.candidates[6]", "cot5.paper.candidates[5]", "cot5.paper.candidates[7]"], False),
    "research_objective": w(
        "근거가 질의를 뒷받침하지 못하는 경우를 투명하게 처리하기 위해 응답 단위 미지원 상태와 그 학습 데이터 구성, 근거 표시 거절 생성 방법을 개발하고, "
        "미지원 판별 정확도, 거절 응답의 근거 표시 품질, 답변 가능한 질의에서의 성능 유지로 검증한다.",
        ["future_work.proposed_direction", "cot4.requirements.implementation_steps[3]"], True),
    "proposed_method": w(
        "Self-RAG의 reflection token 체계에 응답 단위 상태 [Unsupported]를 추가한다. 모델은 검색 근거 집합을 읽고 이 상태를 예측하며, "
        "상태가 아니면 근거를 표시한 답변을, 상태이면 검토한 문서와 부족한 정보를 근거와 함께 밝힌 거절 또는 외부 지식 요청을 생성한다. 근거 표시 형식은 [TBD: 거절 응답의 인용 형식]으로 둔다.",
        ["future_work.proposed_direction", "cot4.requirements.implementation_steps[0]", "cot4.requirements.implementation_steps[2]"], True),
    "method_components": w([
        {"id": "M1", "name": "응답 단위 미지원 상태 토큰", "description": "근거 문서 집합 전체가 질의에 답하기에 부족한지를 예측하는 상태 토큰. 어휘 확장과 미세조정으로 학습한다.", "addresses": ["L2"]},
        {"id": "M2", "name": "짝 지은 미지원 학습 데이터 구성", "description": "답변 가능한 질의에서 정답 근거 문서를 제거하거나 무관한 문서로 바꿔 미지원 사례를 만들고, 원래 사례와 짝지어 라벨을 붙인다. 평가용 질의는 학습용과 다른 출처에서 따로 만든다.", "addresses": ["L1", "L2"]},
        {"id": "M3", "name": "상태 기반 응답 결정 규칙", "description": "미지원 상태 확률의 임계값으로 답변과 거절을 고른다. 임계값으로 거절률과 답변 성능의 균형을 조절한다.", "addresses": ["L2", "L4"]},
        {"id": "M4", "name": "근거 표시 거절·요청 생성", "description": "거절이나 외부 지식 요청에 검토한 문서와 부족한 정보를 근거 표시와 함께 쓴다. 근거가 될 문서가 없으면 근거를 지어내지 않고 그 사실을 밝힌다.", "addresses": ["L1", "L3"]},
    ], ["cot4.requirements.implementation_steps[0]", "cot4.requirements.implementation_steps[1]", "cot4.requirements.implementation_steps[2]", "cot4.requirements.data_requirements"], True),
    "component_relations": w([
        {"from": "M2", "to": "M1", "relation": "M2가 만든 짝 라벨로 M1을 학습한다"},
        {"from": "M1", "to": "M3", "relation": "M1의 상태 확률이 M3의 결정 신호가 된다"},
        {"from": "M3", "to": "M4", "relation": "M3가 거절을 고르면 M4가 근거 표시 거절·요청을 생성한다"},
    ], ["cot4.requirements.implementation_steps"], True),
    "data_and_subjects": w([
        {"name": "Self-RAG 코드와 체크포인트", "use": "기반 모델과 기존 reflection token", "status": "확인 필요", "source_hint": "cot4.requirements.external_dependencies[0]"},
        {"name": "M2로 만든 짝 학습 데이터", "use": "M1 학습 (평가에는 쓰지 않음)", "status": "구축 필요", "source_hint": "cot4.requirements.data_requirements"},
        {"name": "학습과 출처가 다른 평가용 미지원·답변 가능 질의", "use": "E1~E4 평가. 학습 데이터와 중복 검사", "status": "[TBD: 데이터셋 목록과 분할 확정 필요]", "source_hint": "cot4.requirements.implementation_steps[3]"},
    ], ["cot4.requirements.data_requirements", "cot4.requirements.external_dependencies"], True),
    "baselines": w([
        {"id": "B1", "name": "RAG", "arxiv_id": "2005.11401", "why": "근거 부족을 판단하지 않고 항상 답하는 기본 검색 증강 생성"},
        {"id": "B2", "name": "Self-RAG", "arxiv_id": "2310.11511", "why": "reflection token을 쓰는 가장 가까운 선행연구 원본"},
        {"id": "B3", "name": "Self-RAG 기존 지지 신호 기반 거절", "arxiv_id": "2310.11511", "why": "새 상태 없이, 모든 문장 조각에서 IsSup가 no support이거나 모든 문서에서 IsRel이 irrelevant이면 거절하고 M4와 같은 근거 표시 형식을 쓴다. 응답 단위 상태가 필요한지 가리는 핵심 ablation"},
        {"id": "B4", "name": "생성 후 탐지 뒤 거절", "arxiv_id": "2504.15771", "why": "답을 생성한 뒤 근거 없는 주장을 탐지해 거절로 바꾸는 방식. 판단 시점의 차이를 비교한다"},
        {"id": "B5", "name": "기존 라벨만으로 학습한 M1", "arxiv_id": "", "why": "M2의 짝 데이터 대신 Self-RAG의 기존 지지 라벨만으로 M1을 학습한다. 데이터 구성 방법(M2)이 필요한지 가린다"},
    ], ["seed:2005.11401", "seed:2310.11511", "cot5.paper.candidates[6]", "cot1.P2.subgoals[1]"], True),
    "validation_targets": w([
        {"id": "V1", "question": "M1은 B3(기존 지지 신호 기반 판정)보다 미지원 질의를 더 정확히 가려내는가?", "components": ["M1", "M3"]},
        {"id": "V2", "question": "M2의 짝 데이터로 학습하면 기존 라벨만으로 학습한 B5보다 미지원 판별이 나아지는가?", "components": ["M2"]},
        {"id": "V3", "question": "M4의 거절 응답은 B3, B4보다 표시한 근거가 실제로 그 문장을 뒷받침하고 부족한 정보를 정확히 밝히는가?", "components": ["M4"]},
        {"id": "V4", "question": "답변 가능한 질의에서 제안 방법은 B1, B2보다 불필요한 거절을 늘리지 않으면서 정확도를 유지하는가?", "components": ["M3"]},
    ], ["cot4.requirements.implementation_steps[3]"], True),
    "experimental_design": w([
        {"id": "E1", "validates": ["V1"], "setup": "평가용 미지원·답변 가능 질의를 섞어 상태 판별", "metrics": ["판별 precision", "판별 recall", "판별 F1", "AUROC"], "baselines": ["B2", "B3"], "success_criterion": "B3 대비 F1이 [TBD: 목표 폭] 이상 높고 paired bootstrap으로 유의", "failure_interpretation": "B3와 차이가 없으면 응답 단위 상태가 기존 신호로 대체 가능하므로 신규성 주장을 거두고 기여를 M4로 좁힌다"},
        {"id": "E2", "validates": ["V2"], "setup": "같은 모델을 M2 데이터와 기존 라벨로 각각 학습해 E1과 같은 평가", "metrics": ["판별 F1"], "baselines": ["B5"], "success_criterion": "B5 대비 F1이 높음 [TBD: 목표 폭]", "failure_interpretation": "차이가 없으면 데이터 구성 방법은 기여에서 뺀다"},
        {"id": "E3", "validates": ["V3"], "setup": "거절 응답의 근거 표시를 자동 지표와 사람 평가로 측정", "metrics": ["인용 문장 지지율(AIS 방식)", "인용 정밀도", "부족 정보 명시 여부(사람 평가, [TBD: 척도와 평가자 수])"], "baselines": ["B3", "B4"], "success_criterion": "인용 지지율과 사람 평가가 B3, B4보다 높음 [TBD: 목표 폭]", "failure_interpretation": "판별은 되지만 근거 표시가 부정확하면 M4의 응답 형식을 다시 설계한다"},
        {"id": "E4", "validates": ["V4"], "setup": "답변 가능한 질의에서 M3 임계값을 바꿔 가며 측정", "metrics": ["정답 정확도", "불필요한 거절률", "거절률-정확도 곡선"], "baselines": ["B1", "B2"], "success_criterion": "B2 대비 정확도 하락이 [TBD: 허용 폭] 이내인 임계값이 있음", "failure_interpretation": "그런 임계값이 없으면 M2의 음성 사례 비율이나 M3를 조정하고, 적용 범위를 좁힌다"},
    ], ["cot4.requirements.implementation_steps[3]", "cot4.resource_guidance.unknowns_to_confirm"], True),
    "target_claims": w([
        {"id": "C1", "claim": "응답 단위 미지원 상태는 Self-RAG의 기존 지지 신호보다 미지원 질의를 더 정확히 가려낸다.", "falsifiable_condition": "E1에서 B3 대비 유의한 F1 차이가 없으면 기각", "validated_by": ["V1"]},
        {"id": "C2", "claim": "짝 지은 미지원 데이터는 기존 라벨보다 미지원 판별 학습에 효과적이다.", "falsifiable_condition": "E2에서 B5 대비 우위가 없으면 기각", "validated_by": ["V2"]},
        {"id": "C3", "claim": "근거 표시 거절은 기존 신호 기반 거절과 생성 후 탐지 방식보다 정확한 근거를 제시한다.", "falsifiable_condition": "E3에서 B3, B4 대비 우위가 없으면 기각", "validated_by": ["V3"]},
        {"id": "C4", "claim": "적절한 임계값에서 답변 가능한 질의의 정확도는 허용 폭 안에서 유지된다.", "falsifiable_condition": "E4에서 허용 폭 이내의 임계값이 없으면 기각", "validated_by": ["V4"]},
    ], [], True),
    "expected_novelty": w([
        {"text": "Self-RAG가 생성한 문장 조각마다 지지 여부를 판단하는 것과 달리, 근거 문서 집합 전체에 대한 응답 단위 상태를 학습해 응답 방식을 바꾼다.", "vs": ["2310.11511"],
         "existing_mechanism": "Self-RAG의 IsSup 토큰: 생성한 문장 조각마다 문서의 지지 여부를 fully/partially/no support로 판단하고 조각 선택에 쓴다", "difference_axis": "적용 단위", "tested_by": ["E1"]},
        {"text": "생성한 뒤 근거 없는 주장을 탐지하거나 인용을 교정하는 방식과 달리, 생성 시점에 거절이나 외부 지식 요청으로 응답 방식을 바꾼다. 검토한 문헌 범위에서 이 조합은 확인되지 않았다.", "vs": ["2504.15771", "2602.18437"],
         "existing_mechanism": "ORION의 생성 후 근거 없는 주장 탐지, FineRef의 생성 후 인용 오류 반성·교정", "difference_axis": "적용 시점", "tested_by": ["E3"]},
    ], ["cot5.review", "cot5.paper.candidates[0]", "cot5.paper.candidates[5]", "cot5.paper.candidates[6]", "cot1.P2.subgoals[1]"], True),
    "expected_contribution": w([
        {"type": "method", "text": "응답 단위 미지원 상태와 근거 표시 거절·요청 생성 방법"},
        {"type": "resource", "text": "답변 가능·미지원 사례를 짝지은 학습 데이터 구성 절차"},
        {"type": "analysis", "text": "Self-RAG 기존 신호 대비 비교와 거절률-정확도 균형 분석"},
    ], [], True),
    "risks_and_fallbacks": w([
        {"id": "R1", "risk": "응답 단위 상태가 Self-RAG의 기존 지지 신호로 대체될 수 있음", "fallback": "E1을 핵심 실험으로 두고, 차이가 없으면 기여를 M4로 좁힌다", "source": "cot5.paper.candidates[0]"},
        {"id": "R2", "risk": "상태 토큰의 학습 목적함수와 손실 가중치가 정해지지 않음", "fallback": "지도학습 단일 목적부터 시작하고 가중치는 검증 세트로 정한다", "source": "cot4.requirements.vague_or_unspecified_steps[0]"},
        {"id": "R3", "risk": "합성한 미지원 사례가 실제 분포와 다를 수 있음", "fallback": "평가용 질의를 학습과 다른 출처에서 만들고 일부는 사람이 라벨링한다", "source": "cot4.requirements.vague_or_unspecified_steps[2]"},
        {"id": "R4", "risk": "거절 응답에 근거를 어떻게 표시할지 정해지지 않음", "fallback": "'검토한 문서'와 '부족한 정보' 두 칸 형식을 먼저 고정하고 사람 평가로 고친다", "source": "cot4.requirements.vague_or_unspecified_steps[1]"},
        {"id": "R5", "risk": "대규모 미세조정 자원이 필요함", "fallback": "소형 모델로 파일럿을 먼저 수행한다", "source": "cot4.requirements.compute_requirements"},
        {"id": "R6", "risk": "신규성 검색 범위가 제한되어 가장 가까운 선행연구를 놓쳤을 수 있음", "fallback": "착수 전에 거절·인용을 함께 다루는 RAG 연구를 직접 다시 검색하고 차이를 재확인한다", "source": "cot5.paper.status"},
    ], ["cot4.requirements.vague_or_unspecified_steps", "cot4.requirements.compute_requirements", "cot5.paper.status"], False),
    "success_criteria_milestones": w([
        {"id": "S1", "milestone": "중간: 미지원 정의와 데이터 분할 확정", "criterion": "라벨 검수 일치율 [TBD] 이상, 학습·평가 질의 중복 없음, 선행연구 재검색 완료"},
        {"id": "S2", "milestone": "중간: E1 파일럿", "criterion": "소형 모델에서 B3 대비 개선 경향 확인, 남은 [TBD] 값 확정"},
        {"id": "S3", "milestone": "최종: E1~E4 전체", "criterion": "C1~C4 각각 채택 또는 기각 판단 가능"},
    ], [], True),
}
fields["novelty_search_scope"] = search_scope(evidence)

plan = {
    "schema_version": SCHEMA_VERSION,
    "meta": {
        "run_id": evidence["meta"]["run_id"],
        "candidate_index": 6,
        "cot3_candidate_id": "C7",
        "idea_title": evidence["meta"]["title"],
        "cot5_classification": "NOVEL",
        "generated_by": "golden_v2 (Claude 작성, 팀 검토 필요)",
        "language": "ko",
        "notes": "v1은 원본 파일 없이 써서 Self-RAG 인용문을 넓게 해석했다. v2는 실제 evidence 경로와 Self-RAG 원문(Table 1, 5.2절)을 기준으로 다시 썼다. 사람이 검토하기 전까지는 판정기 보정용 참고 답안으로만 쓴다.",
    },
    "citation_whitelist": evidence["citation_whitelist"],
    "fields": fields,
}

prose = {
    "short_title": "응답 단위 미지원 상태와 근거 표시 거절",
    "overview": "검색 증강 언어모델은 찾아온 문서로 답할 수 없을 때도 답을 만들어 내는 경향이 있다. 이 연구는 검색한 근거 전체가 질문에 답하기에 부족한지를 모델이 응답 단위로 판단하도록 학습하고, 그렇다면 무엇을 검토했고 무엇이 부족한지 근거와 함께 밝히며 거절하거나 추가 정보를 요청하게 하는 방법을 계획한다. 가장 가까운 선행연구인 Self-RAG의 기존 신호만으로 같은 일을 할 때와 비교해 새 상태가 필요한지 검증하고, 답할 수 있는 질문에서 불필요한 거절이 늘지 않는지도 확인한다.",
    "current_approach": "RAG [2005.11401]는 검색한 문서를 조건으로 답을 생성하고, 생성에 쓴 문서를 근거로 보여주는 것을 목표로 한다. Self-RAG [2310.11511]는 reflection token으로 검색 여부를 정하고, 문서의 관련성과 생성한 문장 조각이 문서에 의해 지지되는지를 스스로 평가한다.",
    "method_overview": "Self-RAG [2310.11511]의 reflection token 체계에 응답 단위 미지원 상태(M1)를 더하고, 이를 학습할 짝 데이터(M2), 상태에 따라 응답 방식을 고르는 규칙(M3), 근거를 표시한 거절·요청 생성(M4)으로 구성한다.",
}
skeleton = {
    "titles": [
        "When the Evidence Is Not Enough: Response-Level Unsupported States for Attributed Abstention in Retrieval-Augmented Generation",
        "Beyond Segment-Level Support: Learning When to Refuse with Citations in Self-Reflective RAG",
    ],
    "abstract": {
        "background": "Retrieval-augmented models condition generation on retrieved documents [2005.11401], and Self-RAG critiques whether each generated segment is supported by a retrieved passage [2310.11511].",
        "gap": "Support is judged per segment and used to select segments; deciding that the retrieved evidence as a whole cannot answer the query, and changing the response accordingly, is not part of these methods.",
        "method": "We propose a response-level unsupported state, a procedure that pairs answerable and unsupported training cases, a threshold policy that decides between answering and abstaining, and abstentions that cite the documents examined and state what is missing.",
        "planned_evaluation": "We compare against an ablation that abstains using Self-RAG's existing support signals ([RESULT: E1 detection F1]), test the data procedure against existing labels ([RESULT: E2 F1]), measure citation support of abstentions ([RESULT: E3 citation support]), and check answer accuracy on answerable queries ([RESULT: E4 accuracy at matched abstention]).",
        "expected_contribution": "A method for attributed abstention, a paired data procedure, and an analysis of the abstention-accuracy trade-off.",
    },
    "outline": [
        {"heading": "1 Introduction", "items": ["근거 부족 상황의 문제와 연구 질문 — 근거: research_problem", "기여 요약 — 근거: expected_contribution"]},
        {"heading": "2 Related Work", "items": ["검색 증강 생성과 근거 제시 — 근거: B1, research_background", "자기 평가 토큰과 문장 조각 단위 지지 판단 — 근거: L2, expected_novelty[0]", "생성 후 탐지·교정 — 근거: L3, expected_novelty[1]"]},
        {"heading": "3 Method", "items": ["응답 단위 상태 — 근거: M1", "짝 데이터 구성 — 근거: M2", "결정 규칙 — 근거: M3", "근거 표시 거절 — 근거: M4"]},
        {"heading": "4 Experimental Setup", "items": ["데이터 분할과 중복 검사 — 근거: data_and_subjects, S1", "비교 대상 — 근거: B1–B5"]},
        {"heading": "5 Results", "items": ["미지원 판별 — E1 → [RESULT: E1 F1] (C1)", "데이터 구성 효과 — E2 → [RESULT: E2 F1] (C2)", "거절의 근거 표시 — E3 → [RESULT: E3 citation support] (C3)", "답변 성능 유지 — E4 → [RESULT: E4 accuracy curve] (C4)"]},
        {"heading": "6 Analysis", "items": ["기존 지지 신호 ablation 해석 — 근거: E1, R1", "합성 사례와 실제 사례의 차이 — 근거: R3"]},
        {"heading": "7 Limitations", "items": ["신규성 검색 범위 — 근거: novelty_search_scope, R6", "자원과 합성 데이터의 한계 — 근거: R3, R5"]},
        {"heading": "8 Conclusion", "items": ["실험 결과에 따라 채택·기각된 주장으로 작성 — 근거: target_claims"]},
    ],
    "figures": [
        {"label": "Fig. 1", "content": "M2 → M1 → M3 → M4 흐름도", "basis": "component_relations"},
        {"label": "Table 1", "content": "E1 결과 표: 행 = 제안 방법, B2, B3 / 열 = precision, recall, F1, AUROC", "basis": "E1"},
        {"label": "Table 2", "content": "E3 결과 표: 행 = 제안 방법, B3, B4 / 열 = 인용 지지율, 인용 정밀도, 사람 평가", "basis": "E3"},
        {"label": "Fig. 2", "content": "E4 거절률-정확도 곡선: x축 = 불필요한 거절률, y축 = 정답 정확도, 선 = 제안 방법, B2", "basis": "E4"},
    ],
    "contributions": [
        "We propose a response-level unsupported state that decides whether the retrieved evidence as a whole can support an answer.",
        "We evaluate whether this state is needed beyond Self-RAG's existing segment-level support signals through a direct ablation.",
        "We describe attributed abstentions that cite the documents examined and state what is missing, and we measure their citation support.",
    ],
}

errors = rule_errors(plan, evidence)
errors += check_short_title(prose["short_title"]) + check_reader_text(prose, allow_ids=True)
errors += check_llm_output(prose, plan) + check_llm_output(skeleton, plan) + check_skeleton_structure(skeleton)
reader = {f"titles[{i}]": t for i, t in enumerate(skeleton["titles"])}
reader |= {f"abstract.{k}": v for k, v in skeleton["abstract"].items()}
reader |= {f"contributions[{i}]": c for i, c in enumerate(skeleton["contributions"])}
errors += check_reader_text(reader, allow_ids=False)
whitelist = {w_["arxiv_id"] for w_ in plan["citation_whitelist"]}
rp = render_research_plan(plan, prose)
ps = render_paper_skeleton(plan, skeleton, prose["short_title"])
errors += validate_research_plan(rp, whitelist) + validate_paper_skeleton(ps, whitelist)
if errors:
    raise SystemExit("\n".join(errors))
(OUT / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
(OUT / "research_plan.md").write_text(rp, encoding="utf-8")
(OUT / "paper_skeleton.md").write_text(ps, encoding="utf-8")
print("golden v2 written, all checks passed")
