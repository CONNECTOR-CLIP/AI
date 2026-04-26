"""
SearchService 단위 테스트.
Repository를 mock으로 대체해 서비스 레이어 로직만 검증한다.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock
import pytest

from app.service.search_service import SearchService
from app.schemas.search import SearchRequest, SearchResponse, PaperResponse


def _make_service(total: int = 0, papers: list | None = None) -> SearchService:
    mock_repo = MagicMock()
    mock_repo.search.return_value = SearchResponse(
        total=total,
        page=1,
        size=10,
        results=papers or [],
    )
    mock_repo.health_check.return_value = True
    return SearchService(repository=mock_repo)


# ─────────────────────────────────────────────
# search() — 검색어 전처리
# ─────────────────────────────────────────────

def test_query_stripped():
    """앞뒤 공백이 제거된 채로 Repository에 전달되는지 확인"""
    service = _make_service()
    req = SearchRequest(query="  transformer  ")
    service.search(req)
    call_kwargs = service._repo.search.call_args.kwargs
    assert call_kwargs["keyword"] == "transformer"


def test_all_params_forwarded():
    """SearchRequest의 모든 필드가 Repository에 정확히 전달되는지 확인"""
    service = _make_service()
    req = SearchRequest(
        query="bert",
        mode="title",
        categories=["cs.AI", "cs.CL"],
        year_from=2020,
        year_to=2023,
        sort="latest",
        page=2,
        size=20,
    )
    service.search(req)
    kw = service._repo.search.call_args.kwargs
    assert kw["keyword"] == "bert"
    assert kw["mode"] == "title"
    assert kw["categories"] == ["cs.AI", "cs.CL"]
    assert kw["year_from"] == 2020
    assert kw["year_to"] == 2023
    assert kw["sort"] == "latest"
    assert kw["page"] == 2
    assert kw["size"] == 20


def test_returns_search_response():
    papers = [PaperResponse(arxiv_id="2301.00001", title="Test")]
    service = _make_service(total=1, papers=papers)
    req = SearchRequest(query="test")
    result = service.search(req)
    assert isinstance(result, SearchResponse)
    assert result.total == 1
    assert result.results[0].arxiv_id == "2301.00001"


# ─────────────────────────────────────────────
# health()
# ─────────────────────────────────────────────

def test_health_true():
    service = _make_service()
    assert service.health() is True


def test_health_false():
    mock_repo = MagicMock()
    mock_repo.health_check.return_value = False
    service = SearchService(repository=mock_repo)
    assert service.health() is False
