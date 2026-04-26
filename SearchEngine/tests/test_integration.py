"""
통합 테스트 — 실제 OpenSearch + FastAPI 서버를 대상으로 실행한다.
OpenSearch가 localhost:9200에서 실행 중이어야 한다.

실행 방법:
    pytest tests/test_integration.py -v
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from app.main import app

# ─────────────────────────────────────────────
# OpenSearch 연결 여부 확인 — 없으면 스킵
# ─────────────────────────────────────────────

def _opensearch_available() -> bool:
    try:
        from app.repository.opensearch_client import get_opensearch_client
        client = get_opensearch_client()
        client.cluster.health(request_timeout=2)
        return True
    except Exception:
        return False


skip_if_no_opensearch = pytest.mark.skipif(
    not _opensearch_available(),
    reason="OpenSearch가 실행 중이지 않음 — 통합 테스트 스킵",
)

client = TestClient(app)


# ─────────────────────────────────────────────
# health
# ─────────────────────────────────────────────

@skip_if_no_opensearch
def test_integration_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.json()["opensearch"] == "connected"


# ─────────────────────────────────────────────
# 검색 모드별 결과 확인
# ─────────────────────────────────────────────

@skip_if_no_opensearch
def test_integration_mode_all():
    res = client.get("/search?query=transformer&mode=all&size=5")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] > 0
    assert len(body["results"]) == 5
    # 관련도 점수가 내림차순인지 확인
    scores = [p["score"] for p in body["results"]]
    assert scores == sorted(scores, reverse=True)


@skip_if_no_opensearch
def test_integration_mode_title():
    res = client.get("/search?query=neural+network&mode=title&size=5")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] > 0
    # 결과 논문 제목에 검색어 단어가 하나 이상 포함되어야 함
    for paper in body["results"]:
        title_lower = paper["title"].lower()
        assert "neural" in title_lower or "network" in title_lower


@skip_if_no_opensearch
def test_integration_mode_author():
    res = client.get("/search?query=Bengio&mode=author&size=5")
    assert res.status_code == 200
    # 결과 수에 상관없이 응답 형태는 올바르게 반환
    body = res.json()
    assert "total" in body
    assert "results" in body


@skip_if_no_opensearch
def test_integration_mode_abstract():
    res = client.get("/search?query=attention+mechanism&mode=abstract&size=5")
    assert res.status_code == 200
    assert res.json()["total"] > 0


# ─────────────────────────────────────────────
# 필터
# ─────────────────────────────────────────────

@skip_if_no_opensearch
def test_integration_category_filter():
    res = client.get("/search?query=learning&categories=cs.AI&size=5")
    assert res.status_code == 200
    body = res.json()
    # 반환된 모든 논문이 cs.AI 카테고리를 포함해야 함
    for paper in body["results"]:
        assert "cs.AI" in paper["categories"], f"{paper['arxiv_id']} 카테고리: {paper['categories']}"


@skip_if_no_opensearch
def test_integration_multi_category_filter():
    res = client.get("/search?query=model&categories=cs.AI,cs.LG&size=5")
    assert res.status_code == 200
    body = res.json()
    for paper in body["results"]:
        assert "cs.AI" in paper["categories"] or "cs.LG" in paper["categories"]


@skip_if_no_opensearch
def test_integration_year_filter():
    res = client.get("/search?query=network&year_from=2020&year_to=2024&size=10")
    assert res.status_code == 200
    body = res.json()
    for paper in body["results"]:
        if paper["published"]:
            year = int(paper["published"][:4])
            assert 2020 <= year <= 2024, f"연도 범위 벗어남: {paper['published']}"


@skip_if_no_opensearch
def test_integration_year_from_only():
    res = client.get("/search?query=deep&year_from=2022&size=5")
    assert res.status_code == 200
    body = res.json()
    for paper in body["results"]:
        if paper["published"]:
            assert int(paper["published"][:4]) >= 2022


# ─────────────────────────────────────────────
# 정렬
# ─────────────────────────────────────────────

@skip_if_no_opensearch
def test_integration_sort_latest():
    res = client.get("/search?query=neural&sort=latest&size=5")
    assert res.status_code == 200
    body = res.json()
    dates = [p["published"] for p in body["results"] if p["published"]]
    assert dates == sorted(dates, reverse=True), f"최신순 정렬 실패: {dates}"


@skip_if_no_opensearch
def test_integration_sort_relevance():
    res = client.get("/search?query=transformer&sort=relevance&size=5")
    assert res.status_code == 200
    scores = [p["score"] for p in res.json()["results"]]
    assert scores == sorted(scores, reverse=True)


# ─────────────────────────────────────────────
# 페이지네이션
# ─────────────────────────────────────────────

@skip_if_no_opensearch
def test_integration_pagination_no_overlap():
    """page1과 page2 결과가 겹치지 않아야 함"""
    r1 = client.get("/search?query=learning&page=1&size=10").json()
    r2 = client.get("/search?query=learning&page=2&size=10").json()
    ids1 = {p["arxiv_id"] for p in r1["results"]}
    ids2 = {p["arxiv_id"] for p in r2["results"]}
    assert len(ids1 & ids2) == 0, f"페이지 중복: {ids1 & ids2}"


@skip_if_no_opensearch
def test_integration_pagination_total_consistent():
    """모든 페이지의 total이 동일해야 함"""
    r1 = client.get("/search?query=learning&page=1&size=5").json()
    r2 = client.get("/search?query=learning&page=2&size=5").json()
    assert r1["total"] == r2["total"]


@skip_if_no_opensearch
def test_integration_size_respected():
    """size 파라미터대로 결과 수가 반환되어야 함"""
    for size in [1, 5, 20]:
        body = client.get(f"/search?query=neural&size={size}").json()
        returned = len(body["results"])
        # 전체 결과가 size보다 적을 수 있으므로 min 처리
        assert returned <= size


# ─────────────────────────────────────────────
# 응답 형태 (schema)
# ─────────────────────────────────────────────

@skip_if_no_opensearch
def test_integration_response_schema():
    """응답 필드가 모두 있는지 확인"""
    res = client.get("/search?query=attention&size=3")
    body = res.json()
    # SearchResponse 필드
    assert "total" in body
    assert "page" in body
    assert "size" in body
    assert "results" in body
    # PaperResponse 필드
    paper = body["results"][0]
    for field in ("arxiv_id", "title", "abstract", "authors", "categories", "published", "score"):
        assert field in paper, f"필드 누락: {field}"


@skip_if_no_opensearch
def test_integration_highlight_returned():
    """highlight가 응답에 포함되는지 확인"""
    res = client.get("/search?query=deep+learning&size=3")
    body = res.json()
    # highlight는 null일 수도 있지만 필드 자체는 존재해야 함
    paper = body["results"][0]
    assert "highlight" in paper
