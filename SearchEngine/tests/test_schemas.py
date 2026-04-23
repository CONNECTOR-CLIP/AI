"""
Pydantic 스키마 검증 단위 테스트.
필수 필드 누락, 잘못된 타입, 경계값 등을 확인한다.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from pydantic import ValidationError
from app.schemas.search import SearchRequest, PaperResponse, SearchResponse


# ─────────────────────────────────────────────
# SearchRequest
# ─────────────────────────────────────────────

def test_search_request_defaults():
    req = SearchRequest(query="attention")
    assert req.mode == "all"
    assert req.sort == "relevance"
    assert req.page == 1
    assert req.size == 10
    assert req.categories is None
    assert req.year_from is None
    assert req.year_to is None

def test_search_request_missing_query():
    with pytest.raises(ValidationError):
        SearchRequest()

def test_search_request_empty_query():
    with pytest.raises(ValidationError):
        SearchRequest(query="")

def test_search_request_invalid_mode():
    with pytest.raises(ValidationError):
        SearchRequest(query="test", mode="full_text")

def test_search_request_invalid_sort():
    with pytest.raises(ValidationError):
        SearchRequest(query="test", sort="random")

def test_search_request_page_below_1():
    with pytest.raises(ValidationError):
        SearchRequest(query="test", page=0)

def test_search_request_size_above_100():
    with pytest.raises(ValidationError):
        SearchRequest(query="test", size=101)

def test_search_request_year_range():
    req = SearchRequest(query="gpt", year_from=2020, year_to=2024)
    assert req.year_from == 2020
    assert req.year_to == 2024

def test_search_request_categories_list():
    req = SearchRequest(query="llm", categories=["cs.AI", "cs.CL"])
    assert req.categories == ["cs.AI", "cs.CL"]


# ─────────────────────────────────────────────
# PaperResponse
# ─────────────────────────────────────────────

def test_paper_response_minimal():
    paper = PaperResponse(arxiv_id="2301.00001", title="Test Paper")
    assert paper.arxiv_id == "2301.00001"
    assert paper.abstract is None
    assert paper.authors == []
    assert paper.categories == []
    assert paper.score is None
    assert paper.highlight is None

def test_paper_response_full():
    paper = PaperResponse(
        arxiv_id="2301.00001",
        title="Attention Is All You Need",
        abstract="We propose a new network architecture...",
        authors=["Vaswani", "Shazeer"],
        categories=["cs.CL", "cs.LG"],
        published="2017-06-12",
        score=4.5,
        highlight={"title": ["<em>Attention</em> Is All You Need"]},
    )
    assert paper.score == 4.5
    assert "cs.CL" in paper.categories


# ─────────────────────────────────────────────
# SearchResponse
# ─────────────────────────────────────────────

def test_search_response_empty():
    resp = SearchResponse(total=0, page=1, size=10, results=[])
    assert resp.total == 0
    assert resp.results == []

def test_search_response_with_papers():
    papers = [
        PaperResponse(arxiv_id=f"230{i}.00001", title=f"Paper {i}")
        for i in range(3)
    ]
    resp = SearchResponse(total=100, page=2, size=3, results=papers)
    assert len(resp.results) == 3
    assert resp.total == 100
    assert resp.page == 2
