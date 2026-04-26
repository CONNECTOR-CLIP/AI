"""
검색 서비스 레이어.

API Layer(라우터)와 Repository Layer(OpenSearch) 사이에서
비즈니스 로직을 담당한다.

현재 MVP 기준으로는 Repository를 얇게 감싸는 역할이지만,
향후 캐싱, 검색어 전처리, 로깅, Semantic Search 분기 등을
이 레이어에 추가한다.
"""
from __future__ import annotations

from app.repository.search_repository import SearchRepository
from app.schemas.search import SearchRequest, SearchResponse


class SearchService:
    def __init__(self, repository: SearchRepository) -> None:
        self._repo = repository

    def search(self, req: SearchRequest) -> SearchResponse:
        """
        SearchRequest를 받아 SearchResponse를 반환한다.
        검색어 앞뒤 공백을 제거하는 전처리만 수행한다.
        """
        return self._repo.search(
            keyword=req.query.strip(),
            mode=req.mode,
            categories=req.categories,
            year_from=req.year_from,
            year_to=req.year_to,
            sort=req.sort,
            page=req.page,
            size=req.size,
        )

    def health(self) -> bool:
        """OpenSearch 연결 상태를 반환한다."""
        return self._repo.health_check()
