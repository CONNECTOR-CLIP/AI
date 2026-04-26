"""
OpenSearch 검색 실행 및 결과 파싱 레이어.

이 레이어의 책임:
- OpenSearch 클라이언트 호출
- 원시 hits 응답을 PaperResponse Pydantic 모델로 변환
- OpenSearch 관련 예외를 상위 레이어에 전파
"""
from __future__ import annotations

import logging

from opensearchpy import OpenSearch, NotFoundError, ConnectionError as OSConnectionError

from app.core.config import settings
from app.repository.query_builder import build_search_query, SearchMode, SortOrder
from app.schemas.search import PaperResponse, SearchResponse

logger = logging.getLogger(__name__)


class SearchRepository:
    """OpenSearch 검색 레포지토리"""

    def __init__(self, client: OpenSearch) -> None:
        self._client = client
        self._index = settings.opensearch_index

    # ─────────────────────────────────────────
    # 퍼블릭 메서드
    # ─────────────────────────────────────────

    def search(
        self,
        keyword: str,
        mode: SearchMode = "all",
        categories: list[str] | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        sort: SortOrder = "relevance",
        page: int = 1,
        size: int = 10,
    ) -> SearchResponse:
        """
        검색 쿼리를 실행하고 SearchResponse를 반환한다.

        Args:
            keyword:    검색어
            mode:       검색 범위
            categories: 카테고리 필터 목록
            year_from:  출판 연도 시작
            year_to:    출판 연도 종료
            sort:       정렬 기준
            page:       페이지 번호 (1-indexed)
            size:       페이지당 결과 수

        Returns:
            SearchResponse (total, page, size, results)

        Raises:
            OSConnectionError: OpenSearch 연결 실패
            NotFoundError: 인덱스가 존재하지 않을 때
        """
        query_body = build_search_query(
            keyword=keyword,
            mode=mode,
            categories=categories,
            year_from=year_from,
            year_to=year_to,
            sort=sort,
            page=page,
            size=size,
        )

        logger.debug("OpenSearch 쿼리: %s", query_body)

        try:
            raw = self._client.search(index=self._index, body=query_body)
        except NotFoundError:
            logger.error("인덱스 '%s'를 찾을 수 없습니다.", self._index)
            raise
        except OSConnectionError as e:
            logger.error("OpenSearch 연결 실패: %s", e)
            raise

        return self._parse_response(raw, page=page, size=size)

    # ─────────────────────────────────────────
    # 내부 파싱 메서드
    # ─────────────────────────────────────────

    @staticmethod
    def _parse_response(raw: dict, page: int, size: int) -> SearchResponse:
        """
        OpenSearch 원시 응답 dict를 SearchResponse로 변환한다.

        raw 구조:
        {
            "hits": {
                "total": {"value": 123},
                "hits": [
                    {
                        "_id": "...",
                        "_score": 1.23,
                        "_source": { ... },
                        "highlight": { ... }   # 선택
                    },
                    ...
                ]
            }
        }
        """
        hits_obj = raw.get("hits", {})
        total_value = hits_obj.get("total", {})

        # OpenSearch 7+ 는 {"value": N, "relation": "eq"} 구조
        if isinstance(total_value, dict):
            total = total_value.get("value", 0)
        else:
            total = int(total_value)

        papers: list[PaperResponse] = []
        for hit in hits_obj.get("hits", []):
            source = hit.get("_source", {})
            highlight = hit.get("highlight")

            paper = PaperResponse(
                arxiv_id=source.get("arxiv_id", hit.get("_id", "")),
                title=source.get("title", ""),
                abstract=source.get("abstract"),
                authors=source.get("authors", []),
                categories=source.get("categories", []),
                published=source.get("published"),
                score=hit.get("_score"),
                highlight=highlight,
            )
            papers.append(paper)

        return SearchResponse(total=total, page=page, size=size, results=papers)

    def health_check(self) -> bool:
        """
        OpenSearch 클러스터 연결 상태를 확인한다.
        Returns:
            True: 정상 / False: 연결 불가
        """
        try:
            self._client.cluster.health()
            return True
        except Exception:
            return False
