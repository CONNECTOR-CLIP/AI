"""
query_builder 단위 테스트.
OpenSearch 연결 없이 쿼리 dict 구조만 검증한다.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app.repository.query_builder import (
    build_search_query,
    _build_category_filter,
    _build_year_filter,
    _build_sort,
)


# ─────────────────────────────────────────────
# _build_category_filter
# ─────────────────────────────────────────────

def test_category_filter_empty():
    assert _build_category_filter([]) is None

def test_category_filter_none():
    assert _build_category_filter(None) is None

def test_category_filter_single():
    result = _build_category_filter(["cs.AI"])
    assert result == {"terms": {"categories": ["cs.AI"]}}

def test_category_filter_multiple():
    result = _build_category_filter(["cs.AI", "cs.LG"])
    assert result["terms"]["categories"] == ["cs.AI", "cs.LG"]


# ─────────────────────────────────────────────
# _build_year_filter
# ─────────────────────────────────────────────

def test_year_filter_none():
    assert _build_year_filter(None, None) is None

def test_year_filter_from_only():
    result = _build_year_filter(2020, None)
    assert result["range"]["published"]["gte"] == "2020-01-01"
    assert "lte" not in result["range"]["published"]

def test_year_filter_to_only():
    result = _build_year_filter(None, 2023)
    assert result["range"]["published"]["lte"] == "2023-12-31"
    assert "gte" not in result["range"]["published"]

def test_year_filter_range():
    result = _build_year_filter(2020, 2023)
    assert result["range"]["published"]["gte"] == "2020-01-01"
    assert result["range"]["published"]["lte"] == "2023-12-31"


# ─────────────────────────────────────────────
# _build_sort
# ─────────────────────────────────────────────

def test_sort_relevance():
    result = _build_sort("relevance")
    assert result == [{"_score": {"order": "desc"}}]

def test_sort_latest():
    result = _build_sort("latest")
    assert result[0] == {"published": {"order": "desc"}}
    assert result[1] == {"_score": {"order": "desc"}}


# ─────────────────────────────────────────────
# build_search_query — 전체 조합
# ─────────────────────────────────────────────

def test_mode_all_uses_multi_match():
    body = build_search_query("transformer", mode="all")
    # multi_match 사용 확인
    assert "multi_match" in body["query"]
    fields = body["query"]["multi_match"]["fields"]
    # title에 boost=3 적용 확인
    assert any("title^3" in f for f in fields)

def test_mode_title_uses_match():
    body = build_search_query("attention", mode="title")
    assert "match" in body["query"]
    assert "title" in body["query"]["match"]
    assert body["query"]["match"]["title"]["boost"] == 3.0

def test_mode_author():
    body = build_search_query("LeCun", mode="author")
    assert "match" in body["query"]
    assert "authors" in body["query"]["match"]

def test_mode_abstract():
    body = build_search_query("diffusion model", mode="abstract")
    assert "match" in body["query"]
    assert "abstract" in body["query"]["match"]

def test_with_category_filter():
    body = build_search_query("bert", categories=["cs.CL"])
    # 필터가 있으면 bool.must + bool.filter 구조
    assert "bool" in body["query"]
    assert "must" in body["query"]["bool"]
    assert "filter" in body["query"]["bool"]
    filters = body["query"]["bool"]["filter"]
    assert any("terms" in f for f in filters)

def test_with_year_filter():
    body = build_search_query("gpt", year_from=2022, year_to=2024)
    assert "bool" in body["query"]
    filters = body["query"]["bool"]["filter"]
    assert any("range" in f for f in filters)

def test_pagination():
    body = build_search_query("llm", page=3, size=20)
    assert body["from"] == 40   # (3-1) * 20
    assert body["size"] == 20

def test_pagination_first_page():
    body = build_search_query("llm", page=1, size=10)
    assert body["from"] == 0

def test_sort_latest_in_body():
    body = build_search_query("neural", sort="latest")
    assert body["sort"][0] == {"published": {"order": "desc"}}

def test_source_fields_included():
    body = build_search_query("attention")
    assert "_source" in body
    assert "title" in body["_source"]
    assert "abstract" in body["_source"]

def test_highlight_included():
    body = build_search_query("attention")
    assert "highlight" in body
    assert "title" in body["highlight"]["fields"]
    assert "abstract" in body["highlight"]["fields"]

def test_no_filter_no_bool_wrapper():
    """필터 없을 때 bool 래퍼 없이 직접 match 쿼리"""
    body = build_search_query("deep learning", mode="all")
    # 필터 없으면 최상위가 multi_match여야 함
    assert "bool" not in body["query"]
    assert "multi_match" in body["query"]
