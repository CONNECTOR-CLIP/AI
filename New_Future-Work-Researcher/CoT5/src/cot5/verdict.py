from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Verdict:
    classification: str  # "NOVEL" | "NOT_NOVEL" | "UNCERTAIN"
    reason: str


def resolve_verdict(category: str | None, evaluated_paper_count: int) -> Verdict:
    """Resolve the legacy paper verdict; empty successful search is not an error.

    NOVEL with zero papers means only that this search found no overlap, not that
    global novelty has been established. Invalid model output remains UNCERTAIN.
    """
    if category is None:
        return Verdict("UNCERTAIN", "novelty checker의 출력을 파싱하지 못했습니다.")
    if evaluated_paper_count == 0:
        return Verdict("NOVEL", "검색 범위에서 비교할 문헌을 찾지 못했습니다. 신규성의 증명은 아닙니다.")

    if not isinstance(category, str):
        return Verdict("UNCERTAIN", "novelty checker가 문자열이 아닌 분류를 반환했습니다.")
    normalized = category.strip().lower()
    if normalized == "novel":
        return Verdict("NOVEL", "검색된 문헌 중 동등한 연구를 찾지 못했습니다.")
    if normalized == "not novel":
        return Verdict("NOT_NOVEL", "검색된 문헌 중 동등한 연구가 있습니다.")
    return Verdict("UNCERTAIN", f"novelty checker가 알 수 없는 분류를 반환했습니다: {category!r}")


def apply_equivalence_override(verdict: Verdict, equivalent_found: bool, equivalent_paper_title: str = "") -> Verdict:
    """Si et al.의 논문별 동등성 검사(README 8절): Top-10 각각과 개별 비교해 하나라도 동등하면
    그 자체로 NOT_NOVEL이다. 이 개별 근거는 종합 판단(resolve_verdict)보다 우선한다 — "전체적으로
    보면 새로워 보인다"는 홀리스틱 판단이 명확한 개별 일치를 덮어써서는 안 된다(하나라도 겹치는 게
    나오면 그걸로 확정한다는 원칙). NOVEL이든 UNCERTAIN이든 이 override가 적용되면 NOT_NOVEL로 바뀐다.
    """
    if not equivalent_found:
        return verdict
    reason = "개별 비교에서 동등한 연구로 판단된 논문이 있습니다"
    if equivalent_paper_title:
        reason += f"({equivalent_paper_title!r})"
    reason += "(Si et al. 방식 논문별 동등성 검사)."
    return Verdict("NOT_NOVEL", reason)
