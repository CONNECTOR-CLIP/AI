"""
FastAPI 라우터 단위 테스트.
SearchService를 mock으로 대체해 HTTP 요청/응답 계층만 검증한다.
OpenSearch, SQLite 연결 없이 실행 가능하다.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.dependencies import get_search_service
from app.schemas.search import SearchResponse, PaperResponse
from app.service.search_service import SearchService


# ─────────────────────────────────────────────
# 픽스처: mock 서비스 주입
# ─────────────────────────────────────────────

def _make_mock_service(total: int = 5, papers: list | None = None) -> SearchService:
    mock_service = MagicMock(spec=SearchService)
    mock_service.search.return_value = SearchResponse(
        total=total,
        page=1,
        size=10,
        results=papers or [
            PaperResponse(
                arxiv_id=f"2301.0000{i}",
                title=f"Paper {i}",
                abstract="Some abstract.",
                authors=["Author A"],
                categories=["cs.AI"],
                published="2023-01-01",
                score=float(10 - i),
            )
            for i in range(min(total, 3))
        ],
    )
    mock_service.health.return_value = True
    return mock_service


@pytest.fixture
def client():
    mock_service = _make_mock_service()
    app.dependency_overrides[get_search_service] = lambda: mock_service
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ─────────────────────────────────────────────
# GET /health
# ─────────────────────────────────────────────

def test_health_ok(client):
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["opensearch"] == "connected"


def test_health_degraded():
    mock_service = _make_mock_service()
    mock_service.health.return_value = False
    app.dependency_overrides[get_search_service] = lambda: mock_service
    with TestClient(app) as c:
        res = c.get("/health")
    app.dependency_overrides.clear()
    assert res.status_code == 200
    assert res.json()["status"] == "degraded"
    assert res.json()["opensearch"] == "disconnected"


# ─────────────────────────────────────────────
# GET /search — 정상 케이스
# ─────────────────────────────────────────────

def test_search_basic(client):
    res = client.get("/search?query=transformer")
    assert res.status_code == 200
    body = res.json()
    assert "total" in body
    assert "results" in body
    assert "page" in body
    assert "size" in body


def test_search_returns_paper_fields(client):
    res = client.get("/search?query=attention")
    papers = res.json()["results"]
    assert len(papers) > 0
    paper = papers[0]
    assert "arxiv_id" in paper
    assert "title" in paper
    assert "authors" in paper
    assert "categories" in paper
    assert "published" in paper
    assert "score" in paper


def test_search_mode_title(client):
    res = client.get("/search?query=bert&mode=title")
    assert res.status_code == 200


def test_search_mode_author(client):
    res = client.get("/search?query=LeCun&mode=author")
    assert res.status_code == 200


def test_search_mode_abstract(client):
    res = client.get("/search?query=diffusion&mode=abstract")
    assert res.status_code == 200


def test_search_with_categories(client):
    res = client.get("/search?query=neural&categories=cs.AI,cs.LG")
    assert res.status_code == 200


def test_search_with_year_filter(client):
    res = client.get("/search?query=network&year_from=2020&year_to=2024")
    assert res.status_code == 200


def test_search_sort_latest(client):
    res = client.get("/search?query=gpt&sort=latest")
    assert res.status_code == 200


def test_search_pagination(client):
    res = client.get("/search?query=learning&page=3&size=20")
    assert res.status_code == 200
    body = res.json()
    assert body["page"] == 1   # mock은 항상 page=1 반환 (실제값 무관)
    assert body["size"] == 10


# ─────────────────────────────────────────────
# GET /search — 에러 케이스
# ─────────────────────────────────────────────

def test_search_missing_query(client):
    """query 파라미터 누락 → 422"""
    res = client.get("/search")
    assert res.status_code == 422


def test_search_empty_query(client):
    """query가 빈 문자열 → 422"""
    res = client.get("/search?query=")
    assert res.status_code == 422


def test_search_invalid_mode(client):
    """mode가 유효하지 않은 값 → 422"""
    res = client.get("/search?query=test&mode=invalid")
    assert res.status_code == 422
    assert "mode" in res.json()["detail"]


def test_search_invalid_sort(client):
    """sort가 유효하지 않은 값 → 422"""
    res = client.get("/search?query=test&sort=random")
    assert res.status_code == 422
    assert "sort" in res.json()["detail"]


def test_search_size_too_large(client):
    """size > 100 → 422"""
    res = client.get("/search?query=test&size=101")
    assert res.status_code == 422


def test_search_page_zero(client):
    """page=0 → 422"""
    res = client.get("/search?query=test&page=0")
    assert res.status_code == 422


def test_search_opensearch_connection_error():
    """OpenSearch 연결 실패 → 503"""
    from opensearchpy import ConnectionError as OSConnectionError
    mock_service = _make_mock_service()
    mock_service.search.side_effect = OSConnectionError("connection refused", None, None)
    app.dependency_overrides[get_search_service] = lambda: mock_service
    with TestClient(app) as c:
        res = c.get("/search?query=test")
    app.dependency_overrides.clear()
    assert res.status_code == 503


def test_search_opensearch_not_found_error():
    """인덱스 없음 → 503"""
    from opensearchpy import NotFoundError
    mock_service = _make_mock_service()
    mock_service.search.side_effect = NotFoundError(404, "index not found", {})
    app.dependency_overrides[get_search_service] = lambda: mock_service
    with TestClient(app) as c:
        res = c.get("/search?query=test")
    app.dependency_overrides.clear()
    assert res.status_code == 503


# ─────────────────────────────────────────────
# GET /  루트
# ─────────────────────────────────────────────

def test_root(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "docs" in res.json()
