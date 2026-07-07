from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..runner import StageResult, WorkerContext
from ..schemas import HarnessInput, SelectedPaper


class IngestStage:
    """Normalize selected papers and persist optional draft/memo input."""

    def __init__(self, payload: HarnessInput | dict[str, Any] | str | Path) -> None:
        self.payload = payload

    def run(self, context: WorkerContext) -> StageResult:
        harness_input = _coerce_harness_input(self.payload)
        normalized_papers = [SelectedPaper.from_input(paper) for paper in harness_input.selected_papers]

        artifacts_written = ["selected_papers.normalized.json"]
        context.artifacts.write_json(
            "selected_papers.normalized.json",
            {
                "selected_papers": [paper.to_dict() for paper in normalized_papers],
            },
        )

        if harness_input.user_draft is not None:
            context.artifacts.write_json(
                "user_draft.json",
                harness_input.user_draft.to_dict(),
            )
            artifacts_written.append("user_draft.json")

        return StageResult(
            status="success",
            artifacts=tuple(artifacts_written),
            metadata={
                "selected_paper_count": len(normalized_papers),
                "user_draft_persisted": harness_input.user_draft is not None,
            },
        )


def _coerce_harness_input(payload: HarnessInput | dict[str, Any] | str | Path) -> HarnessInput:
    if isinstance(payload, HarnessInput):
        return payload
    if isinstance(payload, dict):
        return HarnessInput.from_dict(payload)
    if isinstance(payload, (str, Path)):
        path = Path(payload)
        data = json.loads(path.read_text(encoding="utf-8"))
        return HarnessInput.from_dict(data)
    raise TypeError("ingest payload must be HarnessInput, dict, or JSON path")
