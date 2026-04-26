"""
검색 요청 / 응답 Pydantic 스키마.
FastAPI 라우터와 서비스 레이어 사이의 계약을 정의한다.
"""
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# 요청 스키마
# ─────────────────────────────────────────────

class SearchRequest(BaseModel):
    """GET /search 쿼리 파라미터 스키마"""

    query: str = Field(..., min_length=1, description="검색어")
    mode: Literal["all", "title", "author", "abstract"] = Field(
        default="all",
        description="검색 범위: all / title / author / abstract",
    )
    categories: Optional[list[str]] = Field(
        default=None,
        description="arXiv 카테고리 필터 (예: ['cs.AI', 'cs.IR'])",
    )
    year_from: Optional[int] = Field(
        default=None,
        ge=1990,
        le=2100,
        description="출판 연도 시작 (포함)",
    )
    year_to: Optional[int] = Field(
        default=None,
        ge=1990,
        le=2100,
        description="출판 연도 종료 (포함)",
    )
    sort: Literal["relevance", "latest"] = Field(
        default="relevance",
        description="정렬 기준: relevance / latest",
    )
    page: int = Field(default=1, ge=1, description="페이지 번호 (1-indexed)")
    size: int = Field(default=10, ge=1, le=100, description="페이지당 결과 수")


# ─────────────────────────────────────────────
# 응답 스키마
# ─────────────────────────────────────────────

class PaperResponse(BaseModel):
    """논문 한 건의 응답 스키마"""

    arxiv_id: str
    title: str
    abstract: Optional[str] = None
    authors: list[str] = []
    categories: list[str] = []
    published: Optional[str] = None   # "YYYY-MM-DD" 문자열
    score: Optional[float] = None      # BM25 relevance score
    # 검색어 하이라이트 (있을 때만 포함)
    highlight: Optional[dict[str, list[str]]] = None


class SearchResponse(BaseModel):
    """검색 응답 전체 스키마"""

    total: int = Field(description="전체 매칭 문서 수")
    page: int = Field(description="현재 페이지")
    size: int = Field(description="페이지당 결과 수")
    results: list[PaperResponse] = Field(description="논문 목록")
