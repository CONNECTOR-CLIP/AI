from __future__ import annotations

from typing import Protocol

from ..runner import WorkerContext
from ..schemas import CandidateCard, EvidenceCard, SelectedPaper


class EvidenceCardProvider(Protocol):
    """Minimal interface for deterministic evidence-card generation."""

    def generate_evidence_card(
        self,
        context: WorkerContext,
        paper: SelectedPaper,
    ) -> EvidenceCard: ...


class CandidateCardProvider(Protocol):
    """Minimal interface for deterministic candidate generation."""

    def generate_candidate_cards(
        self,
        context: WorkerContext,
        evidence_cards: tuple[EvidenceCard, ...],
        *,
        round_index: int,
        candidates_per_round: int,
    ) -> tuple[CandidateCard, ...]: ...


class HarnessProvider(EvidenceCardProvider, CandidateCardProvider, Protocol):
    """Provider interface required by the current run pipeline."""
