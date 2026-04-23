"""
검증용 소량 샘플 적재 스크립트 (1,000건).
전체 적재(921,636건) 전에 파이프라인이 정상 동작하는지 빠르게 확인한다.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import logging
from opensearchpy.helpers import bulk
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.repository.sqlite_model import Paper
from app.repository.opensearch_client import get_opensearch_client
from scripts.ingest import paper_to_doc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SAMPLE_SIZE = 1000


def run_sample_ingest():
    client = get_opensearch_client()
    db: Session = SessionLocal()
    try:
        papers = (
            db.query(Paper)
            .filter(Paper.is_deleted == 0)
            .limit(SAMPLE_SIZE)
            .all()
        )
        docs = [paper_to_doc(p) for p in papers]
        success, failed = bulk(client, docs, raise_on_error=False, stats_only=True)
        logger.info("샘플 적재 완료 — 성공: %d, 실패: %d", success, failed)

        client.indices.refresh(index=settings.opensearch_index)
        count = client.count(index=settings.opensearch_index)["count"]
        logger.info("인덱스 문서 수: %d", count)
    finally:
        db.close()


if __name__ == "__main__":
    run_sample_ingest()
