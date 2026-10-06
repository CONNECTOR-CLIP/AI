# -*- coding: utf-8 -*-
"""
arXiv API로 논문 메타데이터를 수집하여
result/embedding/documents.json 및 papers_meta.json에 저장

융합 포인트
- 기존 코드의 입력/저장 흐름 유지
- 성공사례의 Session + 요청 간 최소 간격 보장 + feedparser 파싱 도입
- 429 / 빈 페이지 / 네트워크 오류에 대한 보수적 재시도
- 체크포인트(resume) 지원
"""

from __future__ import annotations

import json
import os
import random
import time
import re
import logging
from datetime import datetime, timedelta
from typing import Any, Iterator
from urllib.parse import urlencode

import feedparser
import requests
from requests.exceptions import RequestException

# =========================================================
# 로깅
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# =========================================================
# 설정
# =========================================================
ARXIV_API_URL_FORMAT = "https://export.arxiv.org/api/query?{}"

DEFAULT_MAX_RESULTS = 500
PAGE_SIZE = 20                  # 너무 크게 잡지 않음
DELAY_SECONDS = 12.0            # 성공사례의 강제 간격 철학 + 더 보수적 운영
NUM_RETRIES = 6
REQUEST_TIMEOUT = 120

RETRY_WAIT_TIMEOUT = 20.0
RETRY_WAIT_EMPTY = 30.0
RETRY_WAIT_429_BASE = 90.0

OUTPUT_DIR = "result/embedding"
DOCUMENTS_FILE = os.path.join(OUTPUT_DIR, "documents.json")
META_FILE = os.path.join(OUTPUT_DIR, "papers_meta.json")
CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, "checkpoint.json")

USER_AGENT = "arxiv-research-fetcher/1.0 (your_email@example.com)"

# =========================================================
# 유틸
# =========================================================
def normalize_whitespace(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_checkpoint() -> dict[str, Any] | None:
    if not os.path.exists(CHECKPOINT_FILE):
        return None
    with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_checkpoint(query: str, start: int, papers: list[dict[str, Any]]) -> None:
    data = {
        "query": query,
        "start": start,
        "count": len(papers),
        "saved_at": datetime.now().isoformat(),
    }
    save_json(CHECKPOINT_FILE, data)


def clear_checkpoint() -> None:
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)


# =========================================================
# 검색 입력
# =========================================================
def get_search_query() -> tuple[str, int]:
    print("=" * 60)
    print("arXiv Paper Fetcher")
    print("=" * 60)
    print("\n검색 방법을 선택하세요:")
    print("  1) 키워드 검색  (예: transformer, diffusion model)")
    print("  2) 카테고리 검색 (예: cs.AI, cs.LG, cs.CL, cs.CV)")
    print("  3) 직접 쿼리 입력 (arXiv API 쿼리 문법 그대로)")

    while True:
        choice = input("\n선택 (1/2/3): ").strip()
        if choice in {"1", "2", "3"}:
            break
        print("  1, 2, 3 중 하나를 입력하세요.")

    if choice == "1":
        keywords = input("검색 키워드를 입력하세요 (여러 개는 쉼표로 구분): ").strip()
        parts = [f'all:"{kw.strip()}"' for kw in keywords.split(",") if kw.strip()]
        query = " OR ".join(parts)

    elif choice == "2":
        categories = input("카테고리를 입력하세요 (여러 개는 쉼표로 구분, 예: cs.AI,cs.LG): ").strip()
        parts = [f"cat:{cat.strip()}" for cat in categories.split(",") if cat.strip()]
        query = " OR ".join(parts)

    else:
        query = input("arXiv 쿼리를 직접 입력하세요: ").strip()

    while not query:
        print("  쿼리가 비어 있습니다. 다시 입력하세요.")
        query = input("arXiv 쿼리를 입력하세요: ").strip()

    n_input = input(f"\n가져올 논문 수 (기본값 {DEFAULT_MAX_RESULTS}): ").strip()
    max_results = int(n_input) if n_input.isdigit() and int(n_input) > 0 else DEFAULT_MAX_RESULTS

    return query, max_results


# =========================================================
# 파싱
# =========================================================
def parse_entry(entry: feedparser.FeedParserDict) -> dict[str, Any] | None:
    entry_id = getattr(entry, "id", "") or ""
    title = normalize_whitespace(getattr(entry, "title", ""))
    summary = normalize_whitespace(getattr(entry, "summary", ""))

    if not entry_id or not title or not summary:
        return None

    authors = []
    if hasattr(entry, "authors"):
        for author in entry.authors:
            name = getattr(author, "name", "")
            if name:
                authors.append(name)

    categories = []
    if hasattr(entry, "tags"):
        for tag in entry.tags:
            term = tag.get("term")
            if term:
                categories.append(term)

    links = []
    pdf_url = None
    if hasattr(entry, "links"):
        for link in entry.links:
            href = link.get("href")
            title_attr = link.get("title")
            rel = link.get("rel")
            content_type = link.get("type") or link.get("content_type")
            if href:
                links.append(
                    {
                        "href": href,
                        "title": title_attr,
                        "rel": rel,
                        "content_type": content_type,
                    }
                )
                if title_attr == "pdf" and pdf_url is None:
                    pdf_url = href

    primary_category = ""
    if hasattr(entry, "arxiv_primary_category"):
        primary_category = entry.arxiv_primary_category.get("term", "")

    published = ""
    updated = ""
    if hasattr(entry, "published"):
        published = normalize_whitespace(entry.published)
    if hasattr(entry, "updated"):
        updated = normalize_whitespace(entry.updated)

    return {
        "id": entry_id,
        "title": title,
        "abstract": summary,
        "published": published,
        "updated": updated,
        "authors": authors,
        "categories": categories,
        "primary_category": primary_category,
        "comment": entry.get("arxiv_comment"),
        "journal_ref": entry.get("arxiv_journal_ref"),
        "doi": entry.get("arxiv_doi"),
        "link": entry_id,
        "pdf_url": pdf_url,
        "links": links,
    }


# =========================================================
# 클라이언트
# =========================================================
class ArxivFetcher:
    def __init__(
        self,
        page_size: int = PAGE_SIZE,
        delay_seconds: float = DELAY_SECONDS,
        num_retries: int = NUM_RETRIES,
    ) -> None:
        self.page_size = page_size
        self.delay_seconds = delay_seconds
        self.num_retries = num_retries
        self._last_request_dt: datetime | None = None
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})

    def _enforce_delay(self) -> None:
        if self._last_request_dt is None:
            return

        required = timedelta(seconds=self.delay_seconds + random.uniform(0, 3))
        elapsed = datetime.now() - self._last_request_dt
        if elapsed < required:
            sleep_sec = (required - elapsed).total_seconds()
            logger.info("Sleeping %.2f seconds before next request", sleep_sec)
            time.sleep(sleep_sec)

    def _build_url(self, query: str, start: int, max_results: int) -> str:
        params = {
            "search_query": query,
            "start": str(start),
            "max_results": str(max_results),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        return ARXIV_API_URL_FORMAT.format(urlencode(params))

    def _request_once(self, url: str) -> feedparser.FeedParserDict:
        self._enforce_delay()
        logger.info("Requesting: %s", url)

        response = self._session.get(url, timeout=REQUEST_TIMEOUT)
        self._last_request_dt = datetime.now()

        if response.status_code == 429:
            raise requests.HTTPError("429 Too Many Requests", response=response)
        response.raise_for_status()

        feed = feedparser.parse(response.content)
        return feed

    def fetch_page(self, query: str, start: int, max_results: int, first_page: bool = False) -> list[dict[str, Any]]:
        url = self._build_url(query, start, max_results)

        for attempt in range(1, self.num_retries + 1):
            try:
                feed = self._request_once(url)

                if getattr(feed, "bozo", False):
                    logger.warning("Bozo feed detected: %s", getattr(feed, "bozo_exception", None))

                entries = getattr(feed, "entries", [])

                # 첫 페이지가 아닌데 빈 페이지가 오면 일시적 오류로 취급
                if not entries and not first_page:
                    wait = RETRY_WAIT_EMPTY + random.uniform(0, 10)
                    logger.warning(
                        "Unexpected empty page (attempt %d/%d). Sleeping %.1f sec",
                        attempt, self.num_retries, wait
                    )
                    time.sleep(wait)
                    continue

                results = []
                for entry in entries:
                    paper = parse_entry(entry)
                    if paper:
                        results.append(paper)

                return results

            except requests.exceptions.Timeout:
                wait = RETRY_WAIT_TIMEOUT + random.uniform(0, 5)
                logger.warning(
                    "Timeout (attempt %d/%d). Sleeping %.1f sec",
                    attempt, self.num_retries, wait
                )
                time.sleep(wait)

            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else None
                if status == 429:
                    wait = RETRY_WAIT_429_BASE * (2 ** (attempt - 1)) + random.uniform(0, 15)
                    logger.warning(
                        "429 Too Many Requests (attempt %d/%d). Sleeping %.1f sec",
                        attempt, self.num_retries, wait
                    )
                    time.sleep(wait)
                else:
                    logger.error("HTTP error: %s", e)
                    return []

            except RequestException as e:
                logger.error("Request error: %s", e)
                return []

            except Exception as e:
                logger.error("Unexpected error: %s", e)
                return []

        logger.error("Exceeded max retries for page start=%d", start)
        return []


# =========================================================
# 데이터 정리
# =========================================================
def deduplicate_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = []
    seen = set()

    for paper in papers:
        key = paper.get("id") or paper.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(paper)

    return deduped


def build_documents(papers: list[dict[str, Any]]) -> list[str]:
    return [
        f"{paper['title']} {paper['abstract']}".strip()
        for paper in papers
    ]


# =========================================================
# 메인
# =========================================================
def main() -> None:
    query, target_count = get_search_query()

    print("\n수집 설정")
    print(f"  Query:          {query}")
    print(f"  Target:         {target_count} papers")
    print(f"  Page size:      {PAGE_SIZE}")
    print(f"  Delay seconds:  {DELAY_SECONDS}")
    print(f"  Retries:        {NUM_RETRIES}")

    fetcher = ArxivFetcher()

    collected_papers: list[dict[str, Any]] = []
    start = 0

    checkpoint = load_checkpoint()
    if checkpoint and checkpoint.get("query") == query:
        resume = input(
            f"\n이전 체크포인트 발견: start={checkpoint.get('start')}, "
            f"count={checkpoint.get('count')}개\n이어받기 하시겠습니까? (y/n): "
        ).strip().lower()
        if resume == "y":
            start = int(checkpoint.get("start", 0))
            if os.path.exists(META_FILE):
                with open(META_FILE, "r", encoding="utf-8") as f:
                    collected_papers = json.load(f)
                collected_papers = deduplicate_papers(collected_papers)
            print(f"체크포인트에서 재개합니다. start={start}, 현재 {len(collected_papers)}개")
        else:
            clear_checkpoint()

    first_page = (start == 0)

    while len(collected_papers) < target_count:
        current_page_size = min(PAGE_SIZE, target_count - len(collected_papers))
        print(f"\nFetching [{start} ~ {start + current_page_size - 1}] ...")

        batch = fetcher.fetch_page(
            query=query,
            start=start,
            max_results=current_page_size,
            first_page=first_page
        )

        first_page = False

        if not batch:
            print("  No more results or request failed.")
            break

        before = len(collected_papers)
        collected_papers.extend(batch)
        collected_papers = deduplicate_papers(collected_papers)
        after = len(collected_papers)

        print(f"  Got {len(batch)} papers")
        print(f"  Unique total so far: {after} (+{after - before})")

        documents = build_documents(collected_papers)
        save_json(META_FILE, collected_papers)
        save_json(DOCUMENTS_FILE, documents)

        start += current_page_size
        save_checkpoint(query, start, collected_papers)

    collected_papers = collected_papers[:target_count]
    documents = build_documents(collected_papers)

    save_json(META_FILE, collected_papers)
    save_json(DOCUMENTS_FILE, documents)
    clear_checkpoint()

    print("\nSaved:")
    print(f"  - {DOCUMENTS_FILE} ({len(documents)} documents)")
    print(f"  - {META_FILE}")

    print("\n" + "=" * 60)
    print("Done! Now run:")
    print("  test_embedding_time.py → UMAP.py → HDBSCAN.py → c-tf-idf.py")
    print("=" * 60)


if __name__ == "__main__":
    main()