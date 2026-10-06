from __future__ import annotations

from typing import Any

from .idea import ResearchIdea, SeedPaper


def is_future_work_payload(data: Any) -> bool:
    return isinstance(data, dict) and isinstance(data.get("future_work_proposals"), list)


def ideas_from_future_work(data: dict[str, Any]) -> list[ResearchIdea]:
    """Convert Future-Work-Researcher's final JSON into CoT5 ideas.

    The researcher intentionally has no CoT5-specific fields, so the adapter keeps
    every available proposal field as evaluation context instead of changing the
    upstream output contract.
    """
    if not is_future_work_payload(data):
        raise ValueError("Future-Work-Researcher JSON must contain a future_work_proposals list")

    return [_idea_from_proposal(proposal, index) for index, proposal in enumerate(data["future_work_proposals"], 1)]


def _idea_from_proposal(proposal: Any, index: int) -> ResearchIdea:
    if not isinstance(proposal, dict):
        raise ValueError(f"future_work_proposals[{index - 1}] must be an object")

    background = _required_text(proposal, "background_and_gap", index)
    direction = _required_text(proposal, "proposed_direction", index)
    proposal_id = proposal.get("id", index)
    references = [str(value).strip() for value in proposal.get("reference_papers", []) if str(value).strip()]
    contribution = str(proposal.get("expected_contribution", "")).strip()
    novelty_note = str(proposal.get("novelty_note", "")).strip()

    context = []
    if references:
        context.append("Reference papers: " + "; ".join(references))
    if contribution:
        context.append("Expected contribution: " + contribution)
    if novelty_note:
        context.append("Upstream novelty note: " + novelty_note)

    return ResearchIdea(
        title=_proposal_title(direction, proposal_id),
        problem=background,
        proposed_method=direction,
        motivation="\n".join(context),
        seed_papers=[SeedPaper(title=title) for title in references],
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
