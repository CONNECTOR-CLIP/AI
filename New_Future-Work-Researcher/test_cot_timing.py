import asyncio
import json
from unittest.mock import AsyncMock, patch

import CoT4
import CoT5


def test_cot4_records_requirements_guidance_and_idea_total(tmp_path, monkeypatch):
    monkeypatch.setenv("COT_TIMING_LOG", str(tmp_path / "cot4.jsonl"))

    class Provider:
        def evaluate(self, **kwargs):
            return {"step": kwargs["schema_name"]}

    idea = CoT4.ResearchIdea(title="T", problem="P", proposed_method="M")
    CoT4.CoT4Pipeline(Provider()).check(idea)
    entries = [json.loads(line) for line in (tmp_path / "cot4.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {entry["step"] for entry in entries} == {"requirements", "resource_guidance", "idea_total"}
    assert all(entry["seconds"] >= 0 and entry["status"] == "ok" for entry in entries)


def test_cot5_records_paper_and_two_source_timings(tmp_path, monkeypatch):
    monkeypatch.setenv("COT_TIMING_LOG", str(tmp_path / "cot5.jsonl"))
    idea = CoT5.ResearchIdea(title="T", problem="P", proposed_method="M")
    output = {"output": {"default": {"category": "novel", "evaluation_papers": [{"title": "Paper"}]}}, "trace": {}}

    async def empty(_):
        return []

    with patch.object(CoT5, "load_config"), patch.object(CoT5, "_run_once", new=AsyncMock(return_value=output)), patch.object(
        CoT5, "check_all_papers", new=AsyncMock(return_value=(False, []))
    ), patch.object(CoT5, "search_web", empty), patch.object(
        CoT5, "search_patents", empty
    ):
        asyncio.run(CoT5.check_novelty(idea, provider=object()))
    entries = [json.loads(line) for line in (tmp_path / "cot5.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {entry["step"] for entry in entries} == {
        "paper_config", "paper_retrieval_review", "paper_equivalence",
        "web_overlap", "patent_overlap", "idea_total",
        "web_search", "patent_search",
    }
    assert all(entry["seconds"] >= 0 for entry in entries)
