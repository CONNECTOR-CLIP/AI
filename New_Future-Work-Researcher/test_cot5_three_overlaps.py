import asyncio
from unittest.mock import AsyncMock, patch

import CoT5
from cot5 import retrieval_sources


def test_root_cot5_exposes_three_independent_overlap_results():
    idea = CoT5.ResearchIdea(title="T", problem="P", proposed_method="M")
    output = {"output": {"default": {"category": "novel", "evaluation_papers": []}}, "trace": {}}

    async def empty(_):
        return []

    class Provider:
        model = "fake"

        def evaluate(self, **_):
            raise AssertionError("No candidates should need evaluation")

    with patch.object(CoT5, "load_config"), patch.object(CoT5, "_run_once", new=AsyncMock(return_value=output)), patch.object(
        CoT5, "check_all_papers", new=AsyncMock(return_value=(False, []))
    ), patch.object(CoT5, "search_web", empty), patch.object(
        CoT5, "search_patents", empty
    ):
        result = asyncio.run(CoT5.check_novelty(idea, provider=Provider())).as_dict()

    assert list(result["overlaps"]) == ["web", "paper", "patent"]
    assert all(item["status"] == "없음" for item in result["overlaps"].values())


def test_root_empty_paper_search_does_not_retry():
    idea = CoT5.ResearchIdea(title="T", problem="P", proposed_method="M")
    output = {"output": {}, "trace": {"most_relevant_papers": [], "idea_keywords": ["x"],
                                       "query_hit_counts": [{"query": "x", "hits": 0}]}}

    async def empty(_):
        return []

    with patch.object(CoT5, "load_config"), patch.object(CoT5, "_run_once", new=AsyncMock(return_value=output)) as run, \
            patch.object(CoT5, "search_web", empty), \
            patch.object(CoT5, "search_patents", empty):
        result = asyncio.run(CoT5.check_novelty(idea, provider=object())).as_dict()
    assert run.await_count == 1
    assert result["overlaps"]["paper"]["status"] == "없음"
    assert result["paper_search"]["outcome"] == "completed_empty"


def test_root_retrieval_tree_uses_vector_when_keywords_empty():
    import pandas as pd

    CoT5.ensure_submodule_importable()
    from noveltychecker.models.idea_novelty_checker import paper_collection

    paper = {"corpusId": "2401.00001", "title": "Relevant", "abstract": "Details",
             "source": "vector", "embedding": [1.0, 0.0]}

    async def rank(_idea, papers, _max):
        return pd.DataFrame([{"corpusId": key, **value} for key, value in papers.items()])

    with patch.object(paper_collection, "get_query_based_papers_helper", new=AsyncMock(return_value={
        "snippet_papers": {}, "keyword_papers": {}, "idea_keywords": [],
        "title_keywords": [], "query_hit_counts": [],
    })), patch.object(retrieval_sources, "vector_candidates", new=AsyncMock(return_value=(
        {paper["corpusId"]: paper}, {"state": "complete", "complete": True}
    ))), patch.object(retrieval_sources, "lexical_candidates", new=AsyncMock(return_value=(
        {}, {"state": "missing"}
    ))), patch.object(paper_collection, "get_papers_similar_to_input_papers", new=AsyncMock(return_value={})), \
            patch.object(paper_collection, "get_embeddings_ideapapers", new=AsyncMock(side_effect=lambda values: values)), \
            patch.object(paper_collection, "embeddingFiltering", new=rank):
        result = asyncio.run(paper_collection.get_query_based_papers("idea", {}))
    assert result["vector_candidate_count"] == 1
    assert len(result["embedding_ranked"]) == 1
