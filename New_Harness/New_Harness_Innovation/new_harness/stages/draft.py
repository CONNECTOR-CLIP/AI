from __future__ import annotations

from typing import Any

from ..runner import StageResult, WorkerContext
from ..schemas import CriticReport, EvidenceCard, SelectedCandidate, SelectedPaper


DRAFT_PATH = "draft.md"
CLAIM_MAP_PATH = "draft.claim_map.json"
SELECTED_CANDIDATE_PATH = "selected_candidate.json"
EVIDENCE_INDEX_PATH = "evidence_cards/index.json"
SELECTED_PAPERS_PATH = "selected_papers.normalized.json"


class DraftGenerationStage:
    """Generate a deterministic markdown draft and claim map from a selected candidate."""

    def run(self, context: WorkerContext) -> StageResult:
        selected_candidate = SelectedCandidate.from_dict(
            context.artifacts.read_json(SELECTED_CANDIDATE_PATH)
        )
        evidence_cards = _load_evidence_cards(context)
        selected_papers = _load_selected_papers(context)

        missing_refs = [
            paper_id
            for paper_id in selected_candidate.candidate.supporting_evidence_refs
            if paper_id not in evidence_cards
        ]
        if missing_refs:
            return StageResult(
                status="failed",
                artifacts=(DRAFT_PATH, CLAIM_MAP_PATH),
                error=f"missing evidence cards for supporting refs: {', '.join(missing_refs)}",
            )

        markdown = _render_markdown(
            selected_candidate=selected_candidate,
            evidence_cards=evidence_cards,
            selected_papers=selected_papers,
        )
        claim_map = _build_claim_map(
            selected_candidate=selected_candidate,
            evidence_cards=evidence_cards,
            selected_papers=selected_papers,
        )

        context.artifacts.write_text(DRAFT_PATH, markdown)
        context.artifacts.write_json(CLAIM_MAP_PATH, claim_map)
        return StageResult(
            status="success",
            artifacts=(DRAFT_PATH, CLAIM_MAP_PATH),
            metadata={
                "candidate_id": selected_candidate.candidate_id,
                "claim_count": len(claim_map["claims"]),
                "risk_note_count": len(claim_map["risk_notes"]["candidate_risks"])
                + len(claim_map["risk_notes"]["critic_weaknesses"])
                + len(claim_map["risk_notes"]["required_fixes"]),
            },
        )


DraftStage = DraftGenerationStage


def _load_evidence_cards(context: WorkerContext) -> dict[str, dict[str, Any]]:
    index_payload = context.artifacts.read_json(EVIDENCE_INDEX_PATH)
    cards: dict[str, dict[str, Any]] = {}
    for card_ref in index_payload.get("cards", []):
        if not isinstance(card_ref, dict):
            continue
        paper_id = card_ref.get("paper_id")
        card_path = card_ref.get("card_path")
        if not isinstance(paper_id, str) or not isinstance(card_path, str):
            continue
        card = EvidenceCard.from_dict(context.artifacts.read_json(card_path))
        cards[paper_id] = {"card": card, "card_path": card_path}
    return cards


def _load_selected_papers(context: WorkerContext) -> dict[str, SelectedPaper]:
    payload = context.artifacts.read_json(SELECTED_PAPERS_PATH)
    papers = payload.get("selected_papers", [])
    result: dict[str, SelectedPaper] = {}
    for paper_payload in papers:
        paper = SelectedPaper.from_dict(paper_payload)
        result[paper.paper_id] = paper
    return result


def _render_markdown(
    *,
    selected_candidate: SelectedCandidate,
    evidence_cards: dict[str, dict[str, Any]],
    selected_papers: dict[str, SelectedPaper],
) -> str:
    candidate = selected_candidate.candidate
    critic = selected_candidate.critic_report
    support_bullets = _support_bullets(candidate.supporting_evidence_refs, evidence_cards, selected_papers)
    related_bullets = _related_work_bullets(candidate.supporting_evidence_refs, evidence_cards, selected_papers)
    evaluation_bullets = _evaluation_signal_bullets(candidate.supporting_evidence_refs, evidence_cards, selected_papers)
    risk_bullets = _risk_bullets(candidate, critic)
    claim_map_bullets = _claim_map_bullets(selected_candidate)

    sections = [
        f"# {candidate.title}",
        "",
        "## Abstract",
        (
            "_Abstract stub:_ This draft frames the selected candidate as a manuscript-ready direction. "
            f"It targets the gap '{candidate.gap_statement}' and remains grounded in the cited evidence anchors "
            "while preserving explicit critic and risk notes for later revision."
        ),
        "",
        "## Introduction",
        "### Gap",
        candidate.gap_statement,
        "",
        "### Evidence Anchors",
        *support_bullets,
        "",
        "## Related and Future-Work Motivation",
        (
            "The selected papers motivate this direction by combining reported limitations, future-work clues, "
            "and transferable evaluation signals that justify a concrete follow-on manuscript draft."
        ),
        *related_bullets,
        "",
        "## Proposed Direction",
        "### Hypothesis",
        candidate.hypothesis,
        "",
        "### Method",
        candidate.proposed_method,
        "",
        "### Contribution",
        candidate.expected_contribution,
        "",
        "## Evaluation Plan",
        "### Evaluation",
        candidate.evaluation_plan,
        *evaluation_bullets,
        "",
        "## Limitations and Risks",
        "### Risk Notes",
        f"- Critic verdict: {critic.verdict}",
        f"- Novelty risk: {critic.novelty_risk}",
        *risk_bullets,
        "",
        "## Conclusion",
        (
            f"In summary, {candidate.expected_contribution} The manuscript should advance only after the "
            "documented risk notes and required fixes are addressed."
        ),
        "",
        "## Claim Map and Traceability Notes",
        f"- Candidate ID: {selected_candidate.candidate_id}",
        f"- Selected candidate path: {SELECTED_CANDIDATE_PATH}",
        *claim_map_bullets,
        "",
    ]
    return "\n".join(sections).strip() + "\n"


def _build_claim_map(
    *,
    selected_candidate: SelectedCandidate,
    evidence_cards: dict[str, dict[str, Any]],
    selected_papers: dict[str, SelectedPaper],
) -> dict[str, Any]:
    candidate = selected_candidate.candidate
    critic = selected_candidate.critic_report
    claims = [
        _claim_entry(
            claim_id="gap",
            section="Gap",
            text=candidate.gap_statement,
            candidate_field="gap_statement",
            selected_candidate=selected_candidate,
            evidence_cards=evidence_cards,
            selected_papers=selected_papers,
            evidence_refs=candidate.supporting_evidence_refs,
        ),
        _claim_entry(
            claim_id="hypothesis",
            section="Hypothesis",
            text=candidate.hypothesis,
            candidate_field="hypothesis",
            selected_candidate=selected_candidate,
            evidence_cards=evidence_cards,
            selected_papers=selected_papers,
            evidence_refs=candidate.supporting_evidence_refs,
        ),
        _claim_entry(
            claim_id="method",
            section="Method",
            text=candidate.proposed_method,
            candidate_field="proposed_method",
            selected_candidate=selected_candidate,
            evidence_cards=evidence_cards,
            selected_papers=selected_papers,
            evidence_refs=candidate.supporting_evidence_refs,
        ),
        _claim_entry(
            claim_id="evaluation",
            section="Evaluation",
            text=candidate.evaluation_plan,
            candidate_field="evaluation_plan",
            selected_candidate=selected_candidate,
            evidence_cards=evidence_cards,
            selected_papers=selected_papers,
            evidence_refs=candidate.supporting_evidence_refs,
        ),
        _claim_entry(
            claim_id="contribution",
            section="Contribution",
            text=candidate.expected_contribution,
            candidate_field="expected_contribution",
            selected_candidate=selected_candidate,
            evidence_cards=evidence_cards,
            selected_papers=selected_papers,
            evidence_refs=candidate.supporting_evidence_refs,
        ),
    ]
    return {
        "run_id": selected_candidate.run_id,
        "candidate_id": selected_candidate.candidate_id,
        "selected_at": selected_candidate.selected_at,
        "selected_candidate_path": SELECTED_CANDIDATE_PATH,
        "source_paths": dict(selected_candidate.source_paths),
        "claims": claims,
        "risk_notes": {
            "candidate_risks": list(candidate.risks),
            "critic_weaknesses": list(critic.weaknesses),
            "required_fixes": list(critic.required_fixes),
            "critic_verdict": critic.verdict,
            "novelty_risk": critic.novelty_risk,
        },
    }


def _claim_entry(
    *,
    claim_id: str,
    section: str,
    text: str,
    candidate_field: str,
    selected_candidate: SelectedCandidate,
    evidence_cards: dict[str, dict[str, Any]],
    selected_papers: dict[str, SelectedPaper],
    evidence_refs: tuple[str, ...],
) -> dict[str, Any]:
    evidence_entries: list[dict[str, Any]] = []
    for paper_id in evidence_refs:
        if paper_id not in evidence_cards:
            continue
        card = evidence_cards[paper_id]["card"]
        paper = selected_papers.get(paper_id)
        evidence_entries.append(
            {
                "paper_id": paper_id,
                "card_path": evidence_cards[paper_id]["card_path"],
                "selected_paper_title": "" if paper is None else paper.title,
                "claims": list(card.claims[:2]),
                "methods": list(card.methods[:1]),
                "evaluation_signals": list(card.evaluation_signals[:1]),
                "future_work_clues": list(card.future_work_clues[:1]),
            }
        )

    return {
        "claim_id": claim_id,
        "section": section,
        "text": text,
        "trace": {
            "selected_candidate_path": SELECTED_CANDIDATE_PATH,
            "candidate_field": candidate_field,
            "candidate_id": selected_candidate.candidate_id,
            "evidence_refs": evidence_entries,
        },
    }


def _support_bullets(
    evidence_refs: tuple[str, ...],
    evidence_cards: dict[str, dict[str, Any]],
    selected_papers: dict[str, SelectedPaper],
) -> list[str]:
    bullets: list[str] = []
    for paper_id in evidence_refs:
        evidence = evidence_cards.get(paper_id)
        if evidence is None:
            continue
        paper = selected_papers.get(paper_id)
        title = paper.title if paper and paper.title else paper_id
        card = evidence["card"]
        support = _first_nonempty(
            card.future_work_clues,
            card.claims,
            card.evaluation_signals,
            default=f"Supporting evidence extracted for {paper_id}.",
        )
        bullets.append(f"- Evidence anchor ({title} / {paper_id}): {support}")
    return bullets


def _related_work_bullets(
    evidence_refs: tuple[str, ...],
    evidence_cards: dict[str, dict[str, Any]],
    selected_papers: dict[str, SelectedPaper],
) -> list[str]:
    bullets: list[str] = []
    for paper_id in evidence_refs:
        evidence = evidence_cards.get(paper_id)
        if evidence is None:
            continue
        paper = selected_papers.get(paper_id)
        title = paper.title if paper and paper.title else paper_id
        card = evidence["card"]
        motivation = _first_nonempty(
            card.future_work_clues,
            card.claims,
            default=f"Future-work motivation extracted for {paper_id}.",
        )
        bullets.append(f"- {title} ({paper_id}) motivates follow-on work via: {motivation}")
    return bullets or ["- No explicit related-work motivation was recorded."]


def _evaluation_signal_bullets(
    evidence_refs: tuple[str, ...],
    evidence_cards: dict[str, dict[str, Any]],
    selected_papers: dict[str, SelectedPaper],
) -> list[str]:
    bullets: list[str] = []
    for paper_id in evidence_refs:
        evidence = evidence_cards.get(paper_id)
        if evidence is None:
            continue
        paper = selected_papers.get(paper_id)
        title = paper.title if paper and paper.title else paper_id
        card = evidence["card"]
        signal = _first_nonempty(
            card.evaluation_signals,
            card.methods,
            default=f"Evaluation signal extracted for {paper_id}.",
        )
        bullets.append(f"- Evaluation anchor ({title} / {paper_id}): {signal}")
    return bullets or ["- No explicit evaluation anchors were recorded."]


def _risk_bullets(candidate, critic: CriticReport) -> list[str]:
    bullets: list[str] = []
    for risk in candidate.risks:
        bullets.append(f"- Candidate risk: {risk}")
    for weakness in critic.weaknesses:
        bullets.append(f"- Critic weakness: {weakness}")
    for fix in critic.required_fixes:
        bullets.append(f"- Required fix: {fix}")
    if not bullets:
        bullets.append("- No explicit risks were recorded for the selected candidate.")
    return bullets


def _claim_map_bullets(selected_candidate: SelectedCandidate) -> list[str]:
    candidate = selected_candidate.candidate
    return [
        f"- gap -> candidate.gap_statement -> refs: {', '.join(candidate.supporting_evidence_refs)}",
        f"- hypothesis -> candidate.hypothesis -> refs: {', '.join(candidate.supporting_evidence_refs)}",
        f"- method -> candidate.proposed_method -> refs: {', '.join(candidate.supporting_evidence_refs)}",
        f"- evaluation -> candidate.evaluation_plan -> refs: {', '.join(candidate.supporting_evidence_refs)}",
        f"- contribution -> candidate.expected_contribution -> refs: {', '.join(candidate.supporting_evidence_refs)}",
    ]


def _first_nonempty(*groups: tuple[str, ...], default: str) -> str:
    for group in groups:
        for item in group:
            cleaned = item.strip()
            if cleaned:
                return cleaned
    return default
