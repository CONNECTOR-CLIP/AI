"""
OpenSearch 쿼리 빌더.

검색 모드(mode), 카테고리 필터, 연도 필터, 정렬, 페이지네이션을
조합하여 OpenSearch가 소비하는 query body dict를 생성한다.

각 함수는 독립적으로 테스트할 수 있도록 순수 함수로 작성되어 있다.
"""
from __future__ import annotations

from typing import Literal

SearchMode = Literal["all", "title", "author", "abstract"]
SortOrder = Literal["relevance", "latest"]


# ─────────────────────────────────────────────
# 검색 모드별 BM25 쿼리 빌더
# ─────────────────────────────────────────────

def _build_match_query(keyword: str, mode: SearchMode) -> dict:
    """
    검색 모드에 따라 BM25 매치 쿼리를 생성한다.

    title에는 boost=3을 적용하여 제목 일치를 우선한다.
    mode=all  → all_text 필드 (title·abstract·authors가 copy_to된 통합 필드)
               + title 별도 boost로 제목 적중 시 스코어 증폭
    mode=title    → title 단독
    mode=author   → authors 단독
    mode=abstract → abstract 단독
    """
    if mode == "all":
        return {
            "multi_match": {
                "query": keyword,
                "fields": [
                    "title^3",       # title 가중치 3배
                    "abstract^1",
                    "authors^1",
                ],
                "type": "best_fields",   # 가장 높은 스코어 필드 기준
                "operator": "or",
                "fuzziness": "AUTO",     # 오타 허용
            }
        }

    if mode == "title":
        return {
            "match": {
                "title": {
                    "query": keyword,
                    "operator": "or",
                    "fuzziness": "AUTO",
                    "boost": 3.0,
                }
            }
        }

    if mode == "author":
        return {
            "match": {
                "authors": {
                    "query": keyword,
                    "operator": "or",
                }
            }
        }

    if mode == "abstract":
        return {
            "match": {
                "abstract": {
                    "query": keyword,
                    "operator": "or",
                    "fuzziness": "AUTO",
                }
            }
        }

    # 기본 fallback: all_text
    return {"match": {"all_text": {"query": keyword}}}


# ─────────────────────────────────────────────
# 필터 빌더
# ─────────────────────────────────────────────

def _build_category_filter(categories: list[str]) -> dict | None:
    """
    arXiv 카테고리 필터를 생성한다.
    categories가 비어 있으면 None을 반환해 필터를 생략한다.

    예: ["cs.AI", "cs.LG"] → terms 쿼리
    """
    if not categories:
        return None
    return {"terms": {"categories": categories}}


def _build_year_filter(year_from: int | None, year_to: int | None) -> dict | None:
    """
    출판 연도 범위 필터를 생성한다.
    year_from, year_to 모두 None이면 None 반환.

    예: year_from=2020, year_to=2023
        → published >= "2020-01-01" AND published <= "2023-12-31"
    """
    if year_from is None and year_to is None:
        return None

    range_clause: dict = {}
    if year_from is not None:
        range_clause["gte"] = f"{year_from}-01-01"
    if year_to is not None:
        range_clause["lte"] = f"{year_to}-12-31"

    return {"range": {"published": range_clause}}


# ─────────────────────────────────────────────
# 정렬 빌더
# ─────────────────────────────────────────────

def _build_sort(sort: SortOrder) -> list[dict]:
    """
    정렬 옵션을 OpenSearch sort 절로 변환한다.

    relevance → BM25 스코어 내림차순 (기본값)
    latest    → published 날짜 내림차순, 스코어 보조 정렬
    """
    if sort == "latest":
        return [
            {"published": {"order": "desc"}},
            {"_score": {"order": "desc"}},
        ]
    # relevance (기본)
    return [{"_score": {"order": "desc"}}]


# ─────────────────────────────────────────────
# 최종 쿼리 조합
# ─────────────────────────────────────────────

def build_search_query(
    keyword: str,
    mode: SearchMode = "all",
    categories: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    sort: SortOrder = "relevance",
    page: int = 1,
    size: int = 10,
) -> dict:
    """
    검색 파라미터를 받아 OpenSearch query body dict를 반환한다.

    Args:
        keyword:    검색어
        mode:       검색 범위 (all / title / author / abstract)
        categories: arXiv 카테고리 필터 목록 (예: ["cs.AI", "cs.IR"])
        year_from:  출판 연도 시작 (포함)
        year_to:    출판 연도 종료 (포함)
        sort:       정렬 기준 (relevance / latest)
        page:       페이지 번호 (1-indexed)
        size:       페이지당 결과 수

    Returns:
        OpenSearch search() 메서드의 body 파라미터로 전달할 dict
    """
    # ── 검색 쿼리 ────────────────────────────
    match_query = _build_match_query(keyword, mode)

    # ── 필터 수집 ────────────────────────────
    filters: list[dict] = []

    cat_filter = _build_category_filter(categories or [])
    if cat_filter:
        filters.append(cat_filter)

    year_filter = _build_year_filter(year_from, year_to)
    if year_filter:
        filters.append(year_filter)

    # ── bool 쿼리 조립 ───────────────────────
    # 필터가 있으면 bool.must + bool.filter 구조 사용
    # 필터가 없으면 단순 match 쿼리 사용 (스코어 계산 절약)
    if filters:
        query = {
            "bool": {
                "must": [match_query],
                "filter": filters,
            }
        }
    else:
        query = match_query

    # ── 페이지네이션 ─────────────────────────
    from_offset = (page - 1) * size

    return {
        "query": query,
        "sort": _build_sort(sort),
        "from": from_offset,
        "size": size,
        # 검색 결과에 포함할 필드만 지정 (abstract는 길어서 일부만 반환)
        "_source": ["arxiv_id", "title", "authors", "categories", "published", "abstract"],
        # 하이라이트: 검색어가 어느 필드에 매칭됐는지 강조 표시
        "highlight": {
            "fields": {
                "title": {"number_of_fragments": 0},
                "abstract": {"number_of_fragments": 2, "fragment_size": 200},
            },
            "pre_tags": ["<em>"],
            "post_tags": ["</em>"],
        },
    }
