"""
FastAPI 의존성 주입(Depends) 팩토리.

라우터에서 Depends(get_search_service) 형태로 사용한다.
OpenSearch 클라이언트는 요청마다 새로 만들지 않고
모듈 로드 시점에 한 번만 생성해서 재사용한다.
"""
from functools import lru_cache

from app.repository.opensearch_client import get_opensearch_client
from app.repository.search_repository import SearchRepository
from app.service.search_service import SearchService


@lru_cache(maxsize=1)
def _get_repository() -> SearchRepository:
    """SearchRepository 싱글톤 — 앱 생애주기 동안 한 번만 생성."""
    return SearchRepository(client=get_opensearch_client())


def get_search_service() -> SearchService:
    """라우터 Depends용 SearchService 팩토리."""
    return SearchService(repository=_get_repository())
