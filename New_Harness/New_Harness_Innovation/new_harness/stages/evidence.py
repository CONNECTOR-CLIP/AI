from __future__ import annotations

from pathlib import Path

from ..llm.base import EvidenceCardProvider
from ..llm.fake import FakeLLMProvider
from ..runner import StageResult, WorkerContext
from ..schemas import EvidenceCard, SelectedPaper


class EvidenceStage:
    """Generate per-paper evidence cards and an aggregate index."""

    def __init__(self, provider: EvidenceCardProvider | None = None) -> None:
        self.provider = provider or FakeLLMProvider()

    def run(self, context: WorkerContext) -> StageResult:
        selected_papers_payload = context.artifacts.read_json("selected_papers.normalized.json")
        papers = [
            SelectedPaper.from_dict(payload)
            for payload in selected_papers_payload.get("selected_papers", [])
        ]

        if not papers:
            return StageResult(
                status="failed",
                artifacts=("evidence_cards/index.json",),
                error="selected_papers.normalized.json does not contain selected_papers",
            )

        artifacts_written: list[str] = []
        index_cards: list[dict[str, object]] = []

        for paper in papers:
            worker_context = WorkerContext(
                run_id=context.run_id,
                stage_name=f"{context.stage_name}:{paper.paper_id}",
                artifacts=context.artifacts,
                settings={"paper_id": paper.paper_id},
                retry_metadata=context.retry_metadata,
            )
            context.artifacts.append_event(
                "worker_started",
                stage=worker_context.stage_name,
                status="running",
                metadata={"paper_id": paper.paper_id},
                artifacts=[],
            )
            card = self.provider.generate_evidence_card(worker_context, paper)
            card_path = _card_relative_path(paper.paper_id)
            context.artifacts.write_json(card_path, card.to_dict())
            context.artifacts.append_event(
                "worker_completed",
                stage=worker_context.stage_name,
                status="success",
                metadata={"paper_id": paper.paper_id},
                artifacts=[card_path],
            )
            artifacts_written.append(card_path)
            index_cards.append(
                {
                    "paper_id": card.paper_id,
                    "card_path": card_path,
                    "confidence": card.confidence,
                }
            )

        index_path = "evidence_cards/index.json"
        context.artifacts.write_json(
            index_path,
            {
                "cards": index_cards,
                "card_count": len(index_cards),
            },
        )
        artifacts_written.append(index_path)

        return StageResult(
            status="success",
            artifacts=tuple(artifacts_written),
            metadata={"paper_count": len(papers), "provider": type(self.provider).__name__},
        )


def _card_relative_path(paper_id: str) -> str:
    safe_name = paper_id.replace("/", "__")
    return str(Path("evidence_cards") / f"{safe_name}.json")
