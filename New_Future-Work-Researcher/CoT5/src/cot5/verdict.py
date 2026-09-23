from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Verdict:
    classification: str  # "NOVEL" | "NOT_NOVEL" | "UNCERTAIN"
    reason: str


def resolve_verdict(category: str | None, evaluated_paper_count: int) -> Verdict:
    """idea_novelty_checker 원본은 novel/not novel 두 값만 반환한다
    (noveltychecker/models/idea_novelty_checker/check_novelty.py: parse_output).
    README 1절의 안전성 확장 — "검색 범위가 불충분하면 NOVEL이 아니라 UNCERTAIN을 출력" — 을
    "비교할 문헌을 아예 찾지 못했다"는 조건으로만 구현한다. 문헌이 1건이라도 있으면 그걸 근거로
    LLM이 실제로 검토했다는 뜻이므로 novel 판정을 그대로 신뢰한다(2026-08-18 결정: 최소 문헌 수
    임계값은 근거 없는 과잉 보수였다고 판단해 제거).
    """
    if evaluated_paper_count == 0:
        return Verdict("UNCERTAIN", "비교할 문헌을 전혀 찾지 못했습니다.")
    if category is None:
        return Verdict("UNCERTAIN", "novelty checker의 출력을 파싱하지 못했습니다.")

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
