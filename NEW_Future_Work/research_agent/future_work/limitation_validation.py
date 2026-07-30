# [2단계: 한계/언급 추출] 출력에 대한 정적 검증 — AI 미사용, pydantic 스키마 + grounding 방어 확인.
#
# 1단계(goal_decomposition_validation.py)와의 차이: 거기서는 LLM이 만들어낸 자유서술 텍스트를
# 파싱/검증하고, 실패 시 LLM에게 재시도를 요청하는 대화형 루프가 필요했다. 여기서는 애초에
# extract_limitation_candidates()가 정규식으로 원문 substring만 뽑기 때문에 "같은 입력이면
# 항상 같은 출력"이다 — 재시도해도 결과가 안 바뀌므로 retry 루프 자체가 의미 없다. 대신
# 이 파일은 (a) 스키마/필드 검증 (b) grounding 방어 확인 (c) 중복 제거만 담당한다.
#
# grounding 방어 확인이 "방어"인 이유: extract_limitation_candidates()는 quote를 원문에서
# 직접 슬라이싱하므로 구조적으로 항상 grounded다. 그런데도 여기서 다시 `quote in paper_text`를
# 확인하는 이유는, 추출 로직이 버그로 quote를 잘못 조합하거나 잘라내는 경우(예: 향후 리팩터링,
# 인코딩 문제)를 잡기 위한 회귀 방지 장치이지, 주 검증 로직이 아니다.

from typing import Dict, List, Literal, Tuple

from pydantic import BaseModel, ValidationError, field_validator

LIMITATION_TYPES = (
    "Future_Work",
    "Scope_Limitation",
    "Complexity_Limitation",
    "Evaluation_Limitation",
    "Unaddressed_Problem",
)


class LimitationCandidate(BaseModel):
    quote: str
    location: str
    context: str
    limitation_type: Literal[
        "Future_Work", "Scope_Limitation", "Complexity_Limitation",
        "Evaluation_Limitation", "Unaddressed_Problem",
    ]
    matched_signal: str
    evidence_status: Literal["grounded", "rejected"] = "grounded"

    @field_validator("quote", "location", "context", "matched_signal")
    @classmethod
    def not_empty(cls, v: str, info):
        if not v.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        return v


def format_pydantic_errors(e: ValidationError) -> str:
    lines = []
    for err in e.errors():
        loc = ".".join(str(p) for p in err["loc"])
        lines.append(f"{loc}: {err['msg']}")
    return "; ".join(lines)


def validate_limitation_extraction(
    raw_candidates: List[Dict],
    paper_text: str,
) -> Tuple[List[LimitationCandidate], List[str]]:
    """
    2단계 추출 결과를 검증한다. LLM 재시도 루프가 없다 — 실패한 후보는 그냥 드롭하고
    사유를 warnings에 남긴다 (전체를 실패 처리하지 않음. 후보 하나의 결함이 다른 후보를
    막을 이유가 없다).

    Returns: (검증 통과한 LimitationCandidate 목록, 경고/드롭 사유 목록)
    """
    validated: List[LimitationCandidate] = []
    warnings: List[str] = []

    for i, raw in enumerate(raw_candidates):
        try:
            candidate = LimitationCandidate.model_validate(raw)
        except ValidationError as e:
            warnings.append(f"[DROP] candidate#{i}: schema validation failed — {format_pydantic_errors(e)}")
            continue

        # 방어적 grounding 재확인 — extract_limitation_candidates()가 정상이라면 항상 True.
        if candidate.quote not in paper_text:
            warnings.append(
                f"[DROP] candidate#{i}: quote not found verbatim in paper_text "
                f"(grounding invariant violated — check extraction logic): {candidate.quote[:80]!r}"
            )
            continue

        validated.append(candidate)

    # 중복 제거: 정규화된 quote가 이미 채택된 후보의 부분집합이면 드롭 (더 긴 쪽을 유지)
    deduped: List[LimitationCandidate] = []
    normalized_kept: List[str] = []
    for candidate in sorted(validated, key=lambda c: len(c.quote), reverse=True):
        norm = " ".join(candidate.quote.lower().split())
        if any(norm in kept for kept in normalized_kept):
            warnings.append(f"[DEDUP] dropped near-duplicate quote: {candidate.quote[:80]!r}")
            continue
        normalized_kept.append(norm)
        deduped.append(candidate)

    if not deduped:
        warnings.append(
            "[WARN] no grounded limitation candidates found — "
            "this paper may not explicitly state limitations/future work in the sections scanned"
        )

    return deduped, warnings
