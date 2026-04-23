"""
SQLite → OpenSearch 전체 데이터 적재 스크립트.

실행 방법:
    cd e:/SearchEngine
    python -m scripts.ingest
    python -m scripts.ingest --batch-size 1000

성능 최적화:
- authors를 JOIN으로 한 번에 로드 (N+1 쿼리 방지)
- yield_per로 메모리 절약
- bulk 전송으로 네트워크 왕복 최소화
"""
import sys
import os
import argparse
import logging
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from opensearchpy.helpers import bulk
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import SessionLocal
from app.repository.sqlite_model import Paper
from app.repository.opensearch_client import get_opensearch_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# SQLAlchemy SQL 로그는 적재 중 너무 많으니 끈다
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 변환 헬퍼
# ─────────────────────────────────────────────

def paper_to_doc(paper: Paper) -> dict:
    """
    SQLAlchemy Paper 객체를 OpenSearch bulk 문서로 변환.
    authors는 joinedload로 이미 로드된 상태로 전달된다.
    """
    categories = paper.categories.split() if paper.categories else []
    authors = [a.full_name for a in paper.author_list if a.full_name.strip()]
    published_str = paper.created_date or None

    return {
        "_index": settings.opensearch_index,
        "_id": paper.arxiv_id,
        "_source": {
            "arxiv_id": paper.arxiv_id,
            "title": paper.title or "",
            "abstract": paper.abstract or "",
            "authors": authors,
            "categories": categories,
            "published": published_str,
        },
    }


# ─────────────────────────────────────────────
# 배치 읽기 제너레이터 (JOIN 포함)
# ─────────────────────────────────────────────

def iter_papers(db: Session, batch_size: int):
    """
    papers + authors를 JOIN으로 한 번에 읽어 yield한다.
    N+1 쿼리 없이 authors를 즉시 로드한다.
    """
    yield from (
        db.query(Paper)
        .options(selectinload(Paper.author_list))
        .filter(Paper.is_deleted == 0)
        .yield_per(batch_size)
    )


# ─────────────────────────────────────────────
# 메인 적재 로직
# ─────────────────────────────────────────────

def run_ingest(batch_size: int = 1000) -> None:
    client = get_opensearch_client()
    index_name = settings.opensearch_index

    # 인덱스 존재 확인
    if not client.indices.exists(index=index_name):
        logger.error("인덱스 '%s' 없음. 먼저 scripts/create_index.py를 실행하세요.", index_name)
        sys.exit(1)

    db: Session = SessionLocal()
    try:
        total = db.query(Paper).filter(Paper.is_deleted == 0).count()
        logger.info("적재 대상 논문 수: %d", total)

        docs_buffer: list[dict] = []
        indexed = 0
        errors = 0
        start = time.time()

        for paper in iter_papers(db, batch_size):
            docs_buffer.append(paper_to_doc(paper))

            if len(docs_buffer) >= batch_size:
                success, failed = bulk(
                    client,
                    docs_buffer,
                    raise_on_error=False,
                    stats_only=True,
                )
                indexed += success
                errors += failed
                docs_buffer.clear()

                elapsed = time.time() - start
                rate = indexed / elapsed if elapsed > 0 else 0
                eta = (total - indexed) / rate if rate > 0 else 0
                logger.info(
                    "진행: %d / %d (%.1f%%)  실패: %d  속도: %.0f건/s  잔여: %.0f초",
                    indexed, total, indexed / total * 100, errors, rate, eta,
                )

        # 버퍼 잔여분 전송
        if docs_buffer:
            success, failed = bulk(client, docs_buffer, raise_on_error=False, stats_only=True)
            indexed += success
            errors += failed

        elapsed = time.time() - start
        logger.info("적재 완료 — 성공: %d, 실패: %d, 소요: %.1f초", indexed, errors, elapsed)

        # 최종 검증
        client.indices.refresh(index=index_name)
        count = client.count(index=index_name)["count"]
        logger.info("OpenSearch 인덱스 최종 문서 수: %d", count)

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SQLite → OpenSearch 전체 데이터 적재")
    parser.add_argument("--batch-size", type=int, default=1000, help="배치 크기 (기본값: 1000)")
    args = parser.parse_args()
    run_ingest(batch_size=args.batch_size)
