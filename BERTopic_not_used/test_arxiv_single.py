# -*- coding: utf-8 -*-
"""
arXiv API 단일 논문 요청 테스트
- 논문 1편을 가져오는 데 걸리는 시간 측정
"""
import time
import requests
import feedparser
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

URL = "https://export.arxiv.org/api/query?search_query=all:attention&start=0&max_results=1"
USER_AGENT = "arxiv-research-fetcher/1.0 (test)"

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})
session.verify = False

print("=" * 60)
print("arXiv 단일 논문 요청 테스트")
print("=" * 60)
print(f"URL: {URL}\n")

start_time = time.time()
try:
    resp = session.get(URL, timeout=30)
    elapsed_request = time.time() - start_time
    print(f"[요청 완료]  HTTP {resp.status_code}  ({elapsed_request:.3f}초)")

    resp.raise_for_status()

    parse_start = time.time()
    feed = feedparser.parse(resp.text)
    elapsed_parse = time.time() - parse_start

    total = time.time() - start_time

    entries = feed.entries
    print(f"[파싱 완료]  entries: {len(entries)}  ({elapsed_parse:.3f}초)")
    print(f"[총 소요시간] {total:.3f}초")

    if entries:
        e = entries[0]
        print(f"\n[논문 정보]")
        print(f"  ID      : {getattr(e, 'id', 'N/A')}")
        print(f"  Title   : {getattr(e, 'title', 'N/A')[:80]}")
        print(f"  Abstract: {getattr(e, 'summary', 'N/A')[:100]}...")
    else:
        print("\n결과 없음 (쿼리 확인 필요)")

except requests.exceptions.Timeout:
    print(f"  오류: Timeout ({time.time() - start_time:.3f}초 후)")
except requests.exceptions.HTTPError as e:
    print(f"  오류: HTTP {e.response.status_code if e.response else '?'}")
except Exception as e:
    print(f"  오류: {e}")
finally:
    session.close()
