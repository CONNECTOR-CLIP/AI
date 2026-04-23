"""
OpenSearch 인덱스 생성 스크립트.

실행 방법:
    python -m scripts.create_index
    또는
    python scripts/create_index.py

인덱스가 이미 존재하면 삭제 후 재생성할지 확인 메시지를 출력한다.
"""
import sys
import os

# 프로젝트 루트를 sys.path에 추가 (scripts/ 에서 app/ 임포트 가능하도록)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import settings
from app.repository.opensearch_client import get_opensearch_client

# ─────────────────────────────────────────────
# 인덱스 매핑 정의
# ─────────────────────────────────────────────
INDEX_BODY = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,          # 단일 노드 개발 환경
        "analysis": {
            "analyzer": {
                # 영문 논문 전용: lowercase + stop words + stemming
                "english_custom": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "english_stop", "english_stemmer"],
                }
            },
            "filter": {
                "english_stop": {
                    "type": "stop",
                    "stopwords": "_english_",
                },
                "english_stemmer": {
                    "type": "stemmer",
                    "language": "english",
                },
            },
        },
    },
    "mappings": {
        "properties": {
            # arXiv 논문 식별자 — 필터용, 분석 불필요
            "arxiv_id": {"type": "keyword"},

            # 제목: BM25 검색 대상, boost는 쿼리 시점에 적용
            "title": {
                "type": "text",
                "analyzer": "english_custom",
                # copy_to로 all_text 필드에도 병합 (mode=all 검색용)
                "copy_to": "all_text",
            },

            # 초록: BM25 검색 대상
            "abstract": {
                "type": "text",
                "analyzer": "english_custom",
                "copy_to": "all_text",
            },

            # 저자: keyword + text 이중 매핑
            # - keyword: 정확한 필터링
            # - text: 부분 문자열 검색 (multi-field)
            "authors": {
                "type": "text",
                "analyzer": "standard",
                "copy_to": "all_text",
                "fields": {
                    "keyword": {"type": "keyword"}
                },
            },

            # 전체 검색용 통합 필드 (copy_to 수신)
            "all_text": {
                "type": "text",
                "analyzer": "english_custom",
            },

            # 카테고리: 다중 값 keyword (필터용)
            # 저장 형태: ["cs.AI", "cs.LG", "stat.ML"]
            "categories": {"type": "keyword"},

            # 출판일: 날짜 정렬 및 범위 필터용
            "published": {
                "type": "date",
                "format": "yyyy-MM-dd",
            },
        }
    },
}


def create_index(force: bool = False) -> None:
    """
    OpenSearch 인덱스를 생성한다.

    Args:
        force: True이면 기존 인덱스를 삭제 후 재생성.
    """
    client = get_opensearch_client()
    index_name = settings.opensearch_index

    # ── 연결 확인 ──────────────────────────────
    try:
        info = client.info()
        print(f"[OK] OpenSearch 연결 성공: {info['version']['number']}")
    except Exception as e:
        print(f"[ERROR] OpenSearch 연결 실패: {e}")
        sys.exit(1)

    # ── 기존 인덱스 처리 ──────────────────────
    if client.indices.exists(index=index_name):
        if force:
            client.indices.delete(index=index_name)
            print(f"[INFO] 기존 인덱스 '{index_name}' 삭제 완료.")
        else:
            print(f"[SKIP] 인덱스 '{index_name}'가 이미 존재합니다. 재생성하려면 --force 옵션을 사용하세요.")
            return

    # ── 인덱스 생성 ───────────────────────────
    client.indices.create(index=index_name, body=INDEX_BODY)
    print(f"[OK] 인덱스 '{index_name}' 생성 완료.")

    # ── 매핑 확인 출력 ────────────────────────
    mapping = client.indices.get_mapping(index=index_name)
    fields = list(mapping[index_name]["mappings"]["properties"].keys())
    print(f"[INFO] 등록된 필드: {fields}")


if __name__ == "__main__":
    force_flag = "--force" in sys.argv
    create_index(force=force_flag)
