from __future__ import annotations

from typing import Any

from .idea import Constraints, ResearchIdea


def is_future_work_payload(data: Any) -> bool:
    return isinstance(data, dict) and isinstance(data.get("future_work_proposals"), list)


def ideas_from_future_work(
    data: dict[str, Any], *, constraints: Constraints | None = None
) -> list[ResearchIdea]:
    """Convert Future-Work-Researcher's final JSON into CoT4 ideas."""
    if not is_future_work_payload(data):
        raise ValueError("Future-Work-Researcher JSON must contain a future_work_proposals list")

    shared_constraints = constraints or Constraints.from_dict(data.get("constraints"))
    return [
        _idea_from_proposal(proposal, index, shared_constraints)
        for index, proposal in enumerate(data["future_work_proposals"], 1)
    ]


def _idea_from_proposal(
    proposal: Any, index: int, constraints: Constraints
) -> ResearchIdea:
    if not isinstance(proposal, dict):
        raise ValueError(f"future_work_proposals[{index - 1}] must be an object")

    background = _required_text(proposal, "background_and_gap", index)
    direction = _required_text(proposal, "proposed_direction", index)
    contribution = str(proposal.get("expected_contribution", "")).strip()
    references = [str(value).strip() for value in proposal.get("reference_papers", []) if str(value).strip()]

    problem_parts = [background]
    if references:
        problem_parts.append("Reference papers: " + "; ".join(references))
    if contribution:
        problem_parts.append("Expected contribution: " + contribution)

    return ResearchIdea(
        title=_proposal_title(direction, proposal.get("id", index)),
        problem="\n".join(problem_parts),
        proposed_method=direction,
        constraints=constraints,
    )


def _required_text(proposal: dict[str, Any], field: str, index: int) -> str:
    value = str(proposal.get(field, "")).strip()
    if not value:
        raise ValueError(f"future_work_proposals[{index - 1}].{field} must be a non-empty string")
    return value


def _proposal_title(direction: str, proposal_id: Any) -> str:
    first_line = direction.splitlines()[0].strip()
    if len(first_line) > 120:
        first_line = first_line[:117].rstrip() + "..."
    return first_line or f"Future Work Proposal {proposal_id}"
