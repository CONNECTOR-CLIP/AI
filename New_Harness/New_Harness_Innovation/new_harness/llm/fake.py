from __future__ import annotations

import re

from ..runner import WorkerContext
from ..schemas import CandidateCard, EvidenceCard, SelectedPaper


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_METHOD_HINTS = ("method", "approach", "model", "framework", "algorithm", "pipeline")
_LIMITATION_HINTS = ("limit", "however", "but", "challenge", "constraint", "bottleneck")
_EVAL_HINTS = ("result", "benchmark", "accuracy", "evaluation", "experiment", "score")
_FUTURE_HINTS = ("future", "extend", "next", "open question", "improve", "direction")


class FakeLLMProvider:
    """Offline deterministic heuristic extractor for evidence cards and candidates."""

    def generate_evidence_card(
        self,
        context: WorkerContext,
        paper: SelectedPaper,
    ) -> EvidenceCard:
        del context
        text = paper.text_for_evidence().strip()
        title = paper.title.strip() or paper.paper_id
        sentences = _split_sentences(text) if text else []
        snippets = _truncate_unique([title, *sentences], limit=3)

        claims = _truncate_unique(
            [f"Selected paper focuses on: {title}", *_match_sentences(sentences, ())],
            limit=3,
        )
        methods = _truncate_unique(
            _match_sentences(sentences, _METHOD_HINTS) or [f"No explicit method extracted for {paper.paper_id}."],
            limit=3,
        )
        limitations = _truncate_unique(
            _match_sentences(sentences, _LIMITATION_HINTS) or [f"No explicit limitations extracted for {paper.paper_id}."],
            limit=2,
        )
        evaluation_signals = _truncate_unique(
            _match_sentences(sentences, _EVAL_HINTS) or [f"No explicit evaluation signals extracted for {paper.paper_id}."],
            limit=2,
        )
        future_work_clues = _truncate_unique(
            _match_sentences(sentences, _FUTURE_HINTS) or [f"No explicit future-work clues extracted for {paper.paper_id}."],
            limit=2,
        )
        confidence = 0.25
        if paper.title.strip():
            confidence += 0.25
        if paper.abstract.strip():
            confidence += 0.35
        if len(sentences) >= 2:
            confidence += 0.15

        return EvidenceCard(
            paper_id=paper.paper_id,
            claims=tuple(claims),
            methods=tuple(methods),
            limitations=tuple(limitations),
            evaluation_signals=tuple(evaluation_signals),
            future_work_clues=tuple(future_work_clues),
            quotes_or_snippets=tuple(snippets or [paper.paper_id]),
            confidence=confidence,
        )

    def generate_candidate_cards(
        self,
        context: WorkerContext,
        evidence_cards: tuple[EvidenceCard, ...],
        *,
        round_index: int,
        candidates_per_round: int,
    ) -> tuple[CandidateCard, ...]:
        del context
        cards = tuple(evidence_cards)
        if not cards:
            return ()

        generated: list[CandidateCard] = []
        for slot in range(candidates_per_round):
            anchor = cards[(round_index - 1 + slot) % len(cards)]
            partner = cards[(round_index + slot) % len(cards)] if len(cards) > 1 else anchor
            title_seed = _first_nonempty(anchor.future_work_clues, anchor.claims, anchor.quotes_or_snippets) or anchor.paper_id
            gap_seed = _first_nonempty(anchor.limitations, anchor.future_work_clues, anchor.claims) or anchor.paper_id
            method_seed = _first_nonempty(anchor.methods, partner.methods, anchor.claims) or f"Method extension for {anchor.paper_id}"
            eval_seed = _first_nonempty(anchor.evaluation_signals, partner.evaluation_signals) or f"Compare against the reported setup in {anchor.paper_id}."
            candidate_id = f"cand-r{round_index}-{slot + 1}"

            evidence_refs = (anchor.paper_id,) if slot > 0 or len(cards) == 1 else tuple(
                _unique_preserve([anchor.paper_id, partner.paper_id])
            )
            evaluation_plan = (
                f"Run an ablation and benchmark comparison grounded in: {eval_seed}"
                if slot == 0
                else f"Validate against one focused benchmark from {anchor.paper_id}."
            )
            if round_index > 1 and slot == candidates_per_round - 1:
                evaluation_plan = f"Regenerate with a narrower pilot study tied to {anchor.paper_id}."

            generated.append(
                CandidateCard(
                    candidate_id=candidate_id,
                    title=f"Round {round_index}: {title_seed[:70]}",
                    gap_statement=f"Evidence indicates an unresolved gap: {gap_seed[:160]}",
                    hypothesis=f"If we adapt {method_seed[:120]}, we can address the gap surfaced by {anchor.paper_id}.",
                    supporting_evidence_refs=evidence_refs,
                    proposed_method=f"Prototype an extension based on: {method_seed[:180]}",
                    evaluation_plan=evaluation_plan,
                    expected_contribution=f"Deliver a testable improvement motivated by {anchor.paper_id}.",
                    risks=(
                        "Novelty not externally verified yet.",
                        f"Requires validation against evidence from {', '.join(evidence_refs)}.",
                    ),
                )
            )
        return tuple(generated)


def _split_sentences(text: str) -> list[str]:
    chunks = _SENTENCE_SPLIT_RE.split(text.replace("\n", " ").strip())
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _match_sentences(sentences: list[str], hints: tuple[str, ...]) -> list[str]:
    if not hints:
        return [sentences[0]] if sentences else []
    matches = [
        sentence
        for sentence in sentences
        if any(hint in sentence.lower() for hint in hints)
    ]
    return matches or ([sentences[0]] if sentences else [])


def _truncate_unique(items: list[str], *, limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = item.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def _first_nonempty(*groups: tuple[str, ...]) -> str:
    for group in groups:
        for item in group:
            cleaned = item.strip()
            if cleaned:
                return cleaned
    return ""


def _unique_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
