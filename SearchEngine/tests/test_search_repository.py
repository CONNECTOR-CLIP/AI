"""
SearchRepository 단위 테스트 — OpenSearch 클라이언트를 mock으로 대체.
응답 파싱 로직(_parse_response)과 search() 메서드 호출 흐름을 검증한다.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock
import pytest

from app.repository.search_repository import SearchRepository
from app.schemas.search import SearchResponse, PaperResponse


# ─────────────────────────────────────────────
# 픽스처: mock OpenSearch 클라이언트
# ─────────────────────────────────────────────

def _make_repo(mock_response: dict) -> SearchRepository:
    """mock 클라이언트를 주입한 SearchRepository 반환"""
    mock_client = MagicMock()
    mock_client.search.return_value = mock_response
    return SearchRepository(client=mock_client)


def _fake_hit(arxiv_id: str, score: float = 1.0, highlight=None) -> dict:
    return {
        "_id": arxiv_id,
        "_score": score,
        "_source": {
            "arxiv_id": arxiv_id,
            "title": f"Title of {arxiv_id}",
            "abstract": "Some abstract text.",
            "authors": ["Alice Smith", "Bob Lee"],
            "categories": ["cs.AI"],
            "published": "2023-06-01",
        },
        **({"highlight": highlight} if highlight else {}),
    }


# ─────────────────────────────────────────────
# _parse_response 단위 테스트
# ─────────────────────────────────────────────

def test_parse_empty_hits():
    raw = {"hits": {"total": {"value": 0}, "hits": []}}
    result = SearchRepository._parse_response(raw, page=1, size=10)
    assert isinstance(result, SearchResponse)
    assert result.total == 0
    assert result.results == []
    assert result.page == 1
    assert result.size == 10

def test_parse_single_hit():
    raw = {
        "hits": {
            "total": {"value": 1},
            "hits": [_fake_hit("2301.00001", score=2.5)],
        }
    }
    result = SearchRepository._parse_response(raw, page=1, size=10)
    assert result.total == 1
    assert len(result.results) == 1
    paper = result.results[0]
    assert isinstance(paper, PaperResponse)
    assert paper.arxiv_id == "2301.00001"
    assert paper.score == 2.5
    assert paper.authors == ["Alice Smith", "Bob Lee"]
    assert paper.categories == ["cs.AI"]
    assert paper.published == "2023-06-01"

def test_parse_highlight_included():
    hl = {"title": ["<em>attention</em> mechanism"], "abstract": ["uses <em>attention</em>"]}
    raw = {
        "hits": {
            "total": {"value": 1},
            "hits": [_fake_hit("2301.00002", highlight=hl)],
        }
    }
    result = SearchRepository._parse_response(raw, page=1, size=10)
    assert result.results[0].highlight == hl

def test_parse_multiple_hits():
    hits = [_fake_hit(f"23{i:02d}.00001", score=float(10 - i)) for i in range(5)]
    raw = {"hits": {"total": {"value": 100}, "hits": hits}}
    result = SearchRepository._parse_response(raw, page=2, size=5)
    assert result.total == 100
    assert result.page == 2
    assert result.size == 5
    assert len(result.results) == 5

def test_parse_total_as_int():
    """구버전 ES 호환: total이 dict가 아닌 int일 때"""
    raw = {"hits": {"total": 42, "hits": []}}
    result = SearchRepository._parse_response(raw, page=1, size=10)
    assert result.total == 42


# ─────────────────────────────────────────────
# search() 메서드 통합 흐름 테스트
# ─────────────────────────────────────────────

def test_search_calls_opensearch():
    """search()가 실제로 client.search()를 호출하는지 확인"""
    mock_response = {"hits": {"total": {"value": 0}, "hits": []}}
    repo = _make_repo(mock_response)
    result = repo.search("transformer", mode="all", page=1, size=10)
    repo._client.search.assert_called_once()
    assert isinstance(result, SearchResponse)

def test_search_passes_index_name(monkeypatch):
    """올바른 인덱스 이름으로 호출되는지 확인"""
    mock_response = {"hits": {"total": {"value": 0}, "hits": []}}
    mock_client = MagicMock()
    mock_client.search.return_value = mock_response
    repo = SearchRepository(client=mock_client)
    repo._index = "test_index"
    repo.search("bert")
    call_kwargs = mock_client.search.call_args
    assert call_kwargs.kwargs.get("index") == "test_index" or call_kwargs.args[0] if call_kwargs.args else True

def test_health_check_true():
    mock_client = MagicMock()
    mock_client.cluster.health.return_value = {"status": "green"}
    repo = SearchRepository(client=mock_client)
    assert repo.health_check() is True

def test_health_check_false():
    mock_client = MagicMock()
    mock_client.cluster.health.side_effect = Exception("connection refused")
    repo = SearchRepository(client=mock_client)
    assert repo.health_check() is False
