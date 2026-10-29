import asyncio
from unittest.mock import AsyncMock, patch

import pandas as pd

from noveltychecker.models.idea_novelty_checker import paper_collection
from noveltychecker.retrieval import query_based_retrieval
from cot5 import retrieval_sources


PAPER = {"corpusId": "2401.00001", "title": "Vector result", "abstract": "Relevant paper",
         "embedding": [1.0, 0.0], "source": "vector"}


def test_full_corpus_vector_candidate_survives_empty_keyword_search():
    trace = {"snippet_papers": {}, "keyword_papers": {}, "idea_keywords": ["rare term"],
             "title_keywords": [], "query_hit_counts": [{"query": "rare term", "hits": 0}]}
    observed = {}

    async def rank(_idea, papers, _max):
        observed.update(papers)
        return pd.DataFrame([{"corpusId": key, **paper} for key, paper in papers.items()])

    with patch.object(paper_collection, "get_query_based_papers_helper", new=AsyncMock(return_value=trace)), \
            patch.object(retrieval_sources, "vector_candidates", new=AsyncMock(return_value=(
                {PAPER["corpusId"]: PAPER.copy()}, {"state": "complete", "complete": True}
            ))), patch.object(retrieval_sources, "lexical_candidates", new=AsyncMock(return_value=(
                {}, {"state": "missing"}
            ))), patch.object(paper_collection, "get_papers_similar_to_input_papers", new=AsyncMock(return_value={})), \
            patch.object(paper_collection, "get_embeddings_ideapapers", new=AsyncMock(side_effect=lambda papers: papers)), \
            patch.object(paper_collection, "embeddingFiltering", new=rank):
        result = asyncio.run(paper_collection.get_query_based_papers("idea", []))

    assert list(observed) == [PAPER["corpusId"]]
    assert observed[PAPER["corpusId"]]["embedding"] == [1.0, 0.0]
    assert result["vector_candidate_count"] == 1
    assert result["query_hit_counts"][0]["hits"] == 0


def test_keyword_failure_can_continue_with_vector_candidate():
    async def rank(_idea, papers, _max):
        return pd.DataFrame([{"corpusId": key, **paper} for key, paper in papers.items()])

    with patch.object(paper_collection, "get_query_based_papers_helper", new=AsyncMock(side_effect=RuntimeError("capacity"))), \
            patch.object(retrieval_sources, "vector_candidates", new=AsyncMock(return_value=(
                {PAPER["corpusId"]: PAPER.copy()}, {"state": "complete", "complete": True}
            ))), patch.object(retrieval_sources, "lexical_candidates", new=AsyncMock(return_value=(
                {}, {"state": "missing"}
            ))), patch.object(paper_collection, "get_papers_similar_to_input_papers", new=AsyncMock(return_value={})), \
            patch.object(paper_collection, "get_embeddings_ideapapers", new=AsyncMock(side_effect=lambda papers: papers)), \
            patch.object(paper_collection, "embeddingFiltering", new=rank):
        result = asyncio.run(paper_collection.get_query_based_papers("idea", {}))
    assert len(result["embedding_ranked"]) == 1
    assert "capacity" in result["retrieval_warnings"][0]


def test_no_candidates_skips_unneeded_facet_llm_call():
    empty_ranked = pd.DataFrame(columns=["title", "abstract", "embedding"])
    with patch.object(paper_collection, "get_query_based_papers", new=AsyncMock(return_value={
        "embedding_ranked": empty_ranked, "query_hit_counts": []
    })), patch.object(paper_collection, "get_priority_facets", new=AsyncMock(
        side_effect=AssertionError("facet LLM should not run"))):
        result = asyncio.run(paper_collection.get_most_relevant_papers("idea", {}))
    assert len(result["most_relevant_papers"]) == 0


def test_lexical_fallback_is_used_when_keywords_find_nothing():
    lexical = {key: value for key, value in PAPER.items() if key != "embedding"}
    lexical["source"] = "title_abstract"
    trace = {"snippet_papers": {}, "keyword_papers": {}, "idea_keywords": [],
             "title_keywords": [], "query_hit_counts": []}
    observed = {}

    async def rank(_idea, papers, _max):
        observed.update(papers)
        return pd.DataFrame([{"corpusId": key, **paper} for key, paper in papers.items()])

    async def encode_missing(papers):
        for paper in papers.values():
            paper.setdefault("embedding", [0.5, 0.5])
        return papers

    with patch.object(paper_collection, "get_query_based_papers_helper", new=AsyncMock(return_value=trace)), \
            patch.object(retrieval_sources, "vector_candidates", new=AsyncMock(return_value=(
                {}, {"state": "missing", "complete": False}
            ))), patch.object(retrieval_sources, "lexical_candidates", new=AsyncMock(return_value=(
                {PAPER["corpusId"]: lexical}, {"state": "complete"}
            ))), patch.object(paper_collection, "get_papers_similar_to_input_papers", new=AsyncMock(return_value={})), \
            patch.object(paper_collection, "get_embeddings_ideapapers", new=encode_missing), \
            patch.object(paper_collection, "embeddingFiltering", new=rank):
        result = asyncio.run(paper_collection.get_query_based_papers("idea", {}))
    assert list(observed) == [PAPER["corpusId"]]
    assert observed[PAPER["corpusId"]]["embedding"] == [0.5, 0.5]
    assert result["lexical_candidate_count"] == 1


def test_generated_queries_record_individual_database_hit_counts(monkeypatch):
    monkeypatch.setenv("QUERY_RETRIEVAL_METHOD", "keyword+title")

    async def fetch(query, _search_type, limit):
        del limit
        return [{"corpusId": "x"}] if query == "broad query" else []

    with patch.object(query_based_retrieval, "get_keywords", new=AsyncMock(return_value=(
        ["narrow query"], ["broad query"]
    ))), patch.object(query_based_retrieval, "fetch_papers_for_query", new=fetch), \
            patch.object(query_based_retrieval, "get_embeddings_ideapapers", new=AsyncMock(side_effect=lambda papers: papers)):
        trace = asyncio.run(query_based_retrieval.get_query_based_papers_helper("idea"))
    assert trace["query_hit_counts"] == [
        {"query": "narrow query", "search_type": "keyword", "hits": 0},
        {"query": "broad query", "search_type": "keyword", "hits": 1},
    ]
