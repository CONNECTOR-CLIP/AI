"""
OpenSearch 클라이언트 초기화.
앱 전체에서 이 모듈의 get_opensearch_client()를 통해 클라이언트를 주입받는다.
"""
from opensearchpy import OpenSearch

from app.core.config import settings


def get_opensearch_client() -> OpenSearch:
    """
    OpenSearch 클라이언트 인스턴스를 생성해서 반환한다.
    FastAPI 의존성 주입(Depends)에서 사용하거나 직접 호출해도 된다.
    """
    client = OpenSearch(
        hosts=[{"host": settings.opensearch_host, "port": settings.opensearch_port}],
        use_ssl=settings.opensearch_use_ssl,
        verify_certs=False,          # 로컬 개발용 — 프로덕션에서는 True로 변경
        ssl_show_warn=False,
        http_compress=True,          # gzip 압축으로 네트워크 절약
    )
    return client
