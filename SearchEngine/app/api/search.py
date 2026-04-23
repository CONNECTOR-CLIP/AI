"""
검색 API 라우터.

GET /search  — 논문 검색
GET /health  — 서버 + OpenSearch 상태 확인
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from opensearchpy import NotFoundError
from opensearchpy import ConnectionError as OSConnectionError

from app.core.dependencies import get_search_service
from app.schemas.search import SearchRequest, SearchResponse
from app.service.search_service import SearchService

router = APIRouter()


# ─────────────────────────────────────────────
# GET /search
# ─────────────────────────────────────────────

@router.get(
    "/search",
    response_model=SearchResponse,
    summary="논문 검색",
    description=(
        "자연어 키워드로 arXiv 논문을 검색합니다.\n\n"
        "- `mode`: 검색 범위 선택 (all / title / author / abstract)\n"
        "- `categories`: arXiv 카테고리 필터 (여러 개 가능, 예: cs.AI,cs.LG)\n"
        "- `year_from` / `year_to`: 출판 연도 범위 필터\n"
        "- `sort`: relevance(관련도순) / latest(최신순)\n"
        "- `page` / `size`: 페이지네이션"
    ),
)
def search_papers(
    query: Annotated[str, Query(min_length=1, description="검색어")],
    mode: Annotated[str, Query(description="검색 범위: all / title / author / abstract")] = "all",
    categories: Annotated[Optional[str], Query(description="카테고리 필터 (쉼표 구분, 예: cs.AI,cs.LG)")] = None,
    year_from: Annotated[Optional[int], Query(ge=1990, le=2100, description="출판 연도 시작")] = None,
    year_to: Annotated[Optional[int], Query(ge=1990, le=2100, description="출판 연도 종료")] = None,
    sort: Annotated[str, Query(description="정렬: relevance / latest")] = "relevance",
    page: Annotated[int, Query(ge=1, description="페이지 번호 (1부터 시작)")] = 1,
    size: Annotated[int, Query(ge=1, le=100, description="페이지당 결과 수")] = 10,
    service: SearchService = Depends(get_search_service),
) -> SearchResponse:
    # mode 유효성 검사
    if mode not in ("all", "title", "author", "abstract"):
        raise HTTPException(status_code=422, detail="mode는 all / title / author / abstract 중 하나여야 합니다.")

    # sort 유효성 검사
    if sort not in ("relevance", "latest"):
        raise HTTPException(status_code=422, detail="sort는 relevance / latest 중 하나여야 합니다.")

    # categories: 쉼표 구분 문자열 → 리스트
    category_list: list[str] | None = None
    if categories:
        category_list = [c.strip() for c in categories.split(",") if c.strip()]

    req = SearchRequest(
        query=query,
        mode=mode,          # type: ignore[arg-type]
        categories=category_list,
        year_from=year_from,
        year_to=year_to,
        sort=sort,          # type: ignore[arg-type]
        page=page,
        size=size,
    )

    try:
        return service.search(req)
    except NotFoundError:
        raise HTTPException(status_code=503, detail="검색 인덱스를 찾을 수 없습니다. 관리자에게 문의하세요.")
    except OSConnectionError:
        raise HTTPException(status_code=503, detail="검색 서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.")


# ─────────────────────────────────────────────
# GET /health
# ─────────────────────────────────────────────

@router.get(
    "/health",
    summary="서버 상태 확인",
    description="API 서버와 OpenSearch 연결 상태를 반환합니다.",
)
def health_check(service: SearchService = Depends(get_search_service)) -> dict:
    opensearch_ok = service.health()
    status = "ok" if opensearch_ok else "degraded"
    return {
        "status": status,
        "opensearch": "connected" if opensearch_ok else "disconnected",
    }
