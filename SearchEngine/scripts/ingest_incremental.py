"""
증분 적재 스크립트 — DB 업데이트 발생 시 사용.

세 가지 시나리오를 처리한다:
1. 신규 논문 추가: --since YYYY-MM-DD 로 해당 날짜 이후 수집된 논문 적재
2. 논문 수정: 동일 arxiv_id로 재적재 → OpenSearch가 자동 덮어씀 (upsert)
3. 논문 삭제: is_deleted=1 인 문서를 OpenSearch에서도 제거

실행 방법:
    # 2024-01-01 이후 harvested_at(수집일) 기준 신규/수정 논문 적재
    python -m scripts.ingest_incremental --since 2024-01-01

    # 삭제 논문도 함께 처리
    python -m scripts.ingest_incremental --since 2024-01-01 --delete

    # 삭제만 처리
    python -m scripts.ingest_incremental --delete-only
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
from scripts.ingest import paper_to_doc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def upsert_since(db: Session, client, since_date: str, batch_size: int = 1000) -> None:
    """
    harvested_at >= since_date 인 논문을 OpenSearch에 upsert한다.
    (이미 있는 문서는 덮어쓰고, 없으면 신규 삽입)
    """
    total = (
        db.query(Paper)
        .filter(Paper.is_deleted == 0, Paper.harvested_at >= since_date)
        .count()
    )
    logger.info("증분 대상 논문 수 (%s 이후): %d", since_date, total)
    if total == 0:
        logger.info("신규/수정 논문 없음.")
        return

    docs_buffer = []
    indexed = 0
    errors = 0
    start = time.time()

    query = (
        db.query(Paper)
        .options(selectinload(Paper.author_list))
        .filter(Paper.is_deleted == 0, Paper.harvested_at >= since_date)
        .yield_per(batch_size)
    )

    for paper in query:
        docs_buffer.append(paper_to_doc(paper))
        if len(docs_buffer) >= batch_size:
            success, failed = bulk(client, docs_buffer, raise_on_error=False, stats_only=True)
            indexed += success
            errors += failed
            docs_buffer.clear()
            elapsed = time.time() - start
            logger.info("upsert 진행: %d / %d  실패: %d  (%.1fs)", indexed, total, errors, elapsed)

    if docs_buffer:
        success, failed = bulk(client, docs_buffer, raise_on_error=False, stats_only=True)
        indexed += success
        errors += failed

    logger.info("upsert 완료 — 성공: %d, 실패: %d", indexed, errors)


def delete_removed(db: Session, client) -> None:
    """
    SQLite에서 is_deleted=1 인 문서를 OpenSearch에서도 삭제한다.
    """
    deleted_papers = (
        db.query(Paper.arxiv_id)
        .filter(Paper.is_deleted == 1)
        .all()
    )
    ids = [r.arxiv_id for r in deleted_papers]
    if not ids:
        logger.info("삭제할 논문 없음.")
        return

    logger.info("OpenSearch에서 삭제할 논문 수: %d", len(ids))

    # bulk delete
    delete_docs = [
        {"_op_type": "delete", "_index": settings.opensearch_index, "_id": arxiv_id}
        for arxiv_id in ids
    ]
    success, failed = bulk(client, delete_docs, raise_on_error=False, stats_only=True)
    logger.info("삭제 완료 — 성공: %d, 실패: %d", success, failed)


def run_incremental(since_date: str | None, do_delete: bool, delete_only: bool, batch_size: int) -> None:
    client = get_opensearch_client()
    index_name = settings.opensearch_index

    if not client.indices.exists(index=index_name):
        logger.error("인덱스 '%s' 없음. create_index.py를 먼저 실행하세요.", index_name)
        sys.exit(1)

    db: Session = SessionLocal()
    try:
        if not delete_only and since_date:
            upsert_since(db, client, since_date, batch_size)

        if do_delete or delete_only:
            delete_removed(db, client)

        # 최종 문서 수 확인
        client.indices.refresh(index=index_name)
        count = client.count(index=index_name)["count"]
        logger.info("OpenSearch 현재 문서 수: %d", count)

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="증분 적재 — DB 업데이트 시 사용")
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="이 날짜(YYYY-MM-DD) 이후 수집된 논문을 upsert (harvested_at 기준)",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="is_deleted=1 인 논문을 OpenSearch에서도 삭제",
    )
    parser.add_argument(
        "--delete-only",
        action="store_true",
        help="삭제 처리만 수행 (upsert 없이)",
    )
    parser.add_argument("--batch-size", type=int, default=1000)
    args = parser.parse_args()

    if not args.since and not args.delete and not args.delete_only:
        parser.print_help()
        sys.exit(1)

    run_incremental(
        since_date=args.since,
        do_delete=args.delete,
        delete_only=args.delete_only,
        batch_size=args.batch_size,
    )
