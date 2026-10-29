import asyncio
from unittest.mock import AsyncMock, patch

from cot5.idea import ResearchIdea
from cot5.overlap import check_source
from cot5 import pipeline


IDEA = ResearchIdea(title="Graph routing", problem="Routing", proposed_method="Adaptive graph routing")


class FakeProvider:
    model = "fake"

    def evaluate(self, *, instructions, document, schema, schema_name):
        return {
            "overlap": "same core mechanism" in document,
            "reason": "mechanism comparison",
            "evidence": "same core mechanism" if "same core mechanism" in document else "",
        }


def test_source_empty_is_not_unknown():
    async def empty(_):
        return []

    result = asyncio.run(check_source(IDEA, "web", empty, FakeProvider()))
    assert result["status"] == "없음"
    assert result["error"] is None


def test_source_error_is_unknown():
    async def broken(_):
        raise RuntimeError("429 rate limit")

    result = asyncio.run(check_source(IDEA, "web", broken, FakeProvider()))
    assert result["status"] == "확인불가"
    assert "429" in result["error"]


def test_source_evidence_can_match():
    async def found(_):
        return [{"title": "Project", "url": "https://example.org", "snippet": "same core mechanism"}]

    timings = []
    result = asyncio.run(check_source(IDEA, "web", found, FakeProvider(),
                                      timing=lambda step, seconds, status: timings.append((step, seconds, status))))
    assert result["status"] == "겹침"
    assert result["matches"][0]["title"] == "Project"
    assert [entry[0] for entry in timings] == ["search", "candidate_comparison"]
    assert all(entry[1] >= 0 and entry[2] == "ok" for entry in timings)


def test_three_independent_results_and_paper_empty():
    output = {"output": {"default": {"category": "novel", "review": "", "evaluation_papers": []}}, "trace": {}}

    async def empty(_):
        return []

    async def broken(_):
        raise RuntimeError("search failed")

    with patch.object(pipeline, "load_config"), patch.object(pipeline, "_run_once", new=AsyncMock(return_value=output)), patch.object(
        pipeline, "check_all_papers", new=AsyncMock(return_value=(False, []))
    ), patch.object(pipeline, "search_web", broken), patch.object(
        pipeline, "search_patents", empty
    ):
        result = asyncio.run(pipeline.check_novelty(IDEA, provider=FakeProvider())).as_dict()

    assert result["classification"] == "NOVEL"
    assert {k: v["status"] for k, v in result["overlaps"].items()} == {
        "web": "확인불가", "paper": "없음", "patent": "없음"
    }


def test_paper_failure_does_not_stop_other_sources():
    async def broken_paper(*_):
        raise RuntimeError("paper backend offline")

    async def empty(_):
        return []

    with patch.object(pipeline, "load_config"), patch.object(pipeline, "_run_once", new=broken_paper), patch.object(pipeline, "search_web", empty), patch.object(pipeline, "search_patents", empty):
        result = asyncio.run(pipeline.check_novelty(IDEA, provider=FakeProvider())).as_dict()

    assert result["overlaps"]["paper"]["status"] == "확인불가"
    assert all(result["overlaps"][key]["status"] == "없음" for key in ("web", "patent"))


def test_real_empty_retrieval_is_not_parse_error_or_retried():
    output = {"output": {}, "trace": {
        "most_relevant_papers": [], "dropped_by_cutoff": [],
        "idea_keywords": ["affine RANSAC"],
        "query_hit_counts": [{"query": "affine RANSAC", "search_type": "keyword", "hits": 0}],
        "vector_index": {"state": "missing", "complete": False},
    }}

    async def empty(_):
        return []

    with patch.object(pipeline, "load_config"), patch.object(pipeline, "_run_once", new=AsyncMock(return_value=output)) as run, \
            patch.object(pipeline, "search_web", empty), \
            patch.object(pipeline, "search_patents", empty):
        result = asyncio.run(pipeline.check_novelty(IDEA, provider=FakeProvider())).as_dict()
    assert run.await_count == 1
    assert result["overlaps"]["paper"]["status"] == "없음"
    assert result["paper_search"]["outcome"] == "completed_empty"
    assert result["paper_search"]["coverage"] == "limited_candidates"
    assert "full-corpus vector search unavailable" in result["paper_search"]["retrieval_warnings"][0]
    assert result["paper_search"]["query_hit_counts"][0]["hits"] == 0
    assert result["warnings"] == []


def test_missing_review_with_candidates_is_parse_error():
    output = {"output": {}, "trace": {"most_relevant_papers": [{"title": "P"}]}}

    async def empty(_):
        return []

    with patch.object(pipeline, "load_config"), patch.object(pipeline, "_run_once", new=AsyncMock(return_value=output)) as run, \
            patch.object(pipeline, "search_web", empty), \
            patch.object(pipeline, "search_patents", empty):
        result = asyncio.run(pipeline.check_novelty(IDEA, provider=FakeProvider())).as_dict()
    assert run.await_count == 2
    assert result["overlaps"]["paper"]["status"] == "확인불가"
    assert result["paper_search"]["outcome"] == "invalid_review"
    assert [attempt["reason"] for attempt in result["paper_search"]["review_attempts"]] == ["missing_review_output"] * 2


def test_missing_trace_is_not_mistaken_for_successful_empty_search():
    async def empty(_):
        return []

    with patch.object(pipeline, "load_config"), patch.object(pipeline, "_run_once", new=AsyncMock(return_value={
        "output": {}, "trace": {}
    })) as run, patch.object(pipeline, "search_web", empty), \
            patch.object(pipeline, "search_patents", empty):
        result = asyncio.run(pipeline.check_novelty(IDEA, provider=FakeProvider())).as_dict()
    assert run.await_count == 2
    assert result["overlaps"]["paper"]["status"] == "확인불가"


def test_unknown_or_nonstring_category_is_retried_as_invalid_review():
    async def empty(_):
        return []

    for category in ("maybe", 123):
        output = {"output": {"default": {"category": category, "evaluation_papers": [{"title": "P"}]}},
                  "trace": {"most_relevant_papers": [{"title": "P"}]}}
        with patch.object(pipeline, "load_config"), patch.object(pipeline, "_run_once", new=AsyncMock(return_value=output)) as run, \
                patch.object(pipeline, "check_all_papers", new=AsyncMock(return_value=(False, []))), \
                patch.object(pipeline, "search_web", empty), \
                patch.object(pipeline, "search_patents", empty):
            result = asyncio.run(pipeline.check_novelty(IDEA, provider=FakeProvider())).as_dict()
        assert run.await_count == 2
        assert result["paper_search"]["outcome"] == "invalid_review"
        assert result["overlaps"]["paper"]["status"] == "확인불가"
        assert [attempt["reason"] for attempt in result["paper_search"]["review_attempts"]] == [
            "unknown_category" if category == "maybe" else "nonstring_category"
        ] * 2


def test_missing_category_records_response_shape_without_raw_text():
    raw = "Class:\nReview: model omitted classification"
    output = {"output": {"default": {"category": "", "output_novelty_text": raw,
                                      "evaluation_papers": []}},
              "trace": {"most_relevant_papers": [{"title": "P"}]}}

    async def empty(_):
        return []

    with patch.object(pipeline, "load_config"), patch.object(pipeline, "_run_once", new=AsyncMock(return_value=output)) as run, \
            patch.object(pipeline, "search_web", empty), \
            patch.object(pipeline, "search_patents", empty):
        result = asyncio.run(pipeline.check_novelty(IDEA, provider=FakeProvider())).as_dict()

    assert run.await_count == 2
    attempts = result["paper_search"]["review_attempts"]
    assert [a["reason"] for a in attempts] == ["missing_category", "missing_category"]
    assert all(a["has_class_marker"] and a["has_review_marker"] for a in attempts)
    assert all(a["raw_response_length"] == len(raw) for a in attempts)
    assert raw not in str(result)
