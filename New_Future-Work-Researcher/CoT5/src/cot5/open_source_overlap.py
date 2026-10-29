"""Candidate retrieval for public implementations and general web results.

Search results are evidence candidates, not proof that an idea is implemented.
Callers should compare the underlying repository or page before assigning overlap.
"""

from __future__ import annotations

import asyncio
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .idea import ResearchIdea


class SearchError(RuntimeError):
    """A search could not be completed; an empty result is not implied."""


def _queries(idea: ResearchIdea) -> list[str]:
    """Use short, distinct descriptions to avoid sending full idea text to APIs."""
    queries = []
    for value in (idea.title, idea.proposed_method):
        query = " ".join(value.split())[:160].strip()
        if query and query not in queries:
            queries.append(query)
    if not queries:
        raise SearchError("Search requires a title or proposed method")
    return queries


def _fetch_json(url: str, headers: dict[str, str]) -> dict:
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise SearchError(f"Search API returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise SearchError(f"Search API request failed: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise SearchError("Search API returned an invalid response")
    return payload


async def _get_json(url: str, headers: dict[str, str]) -> dict:
    return await asyncio.to_thread(_fetch_json, url, headers)


async def search_web(idea: ResearchIdea) -> list[dict]:
    """Return Google results via existing Custom Search access or SerpApi."""
    key = os.getenv("GOOGLE_SEARCH_API_KEY")
    engine_id = os.getenv("GOOGLE_SEARCH_ENGINE_ID")
    serpapi_key = os.getenv("SERPAPI_API_KEY")
    if not (key and engine_id) and not serpapi_key:
        raise SearchError("Google Custom Search credentials or SERPAPI_API_KEY are required for web search")

    results: list[dict] = []
    seen: set[str] = set()
    for query in _queries(idea):
        if key and engine_id:
            url = "https://www.googleapis.com/customsearch/v1?" + urlencode(
                {"key": key, "cx": engine_id, "q": query, "num": 10}
            )
            result_key = "items"
        else:
            url = "https://serpapi.com/search.json?" + urlencode(
                {"engine": "google", "api_key": serpapi_key, "q": query, "num": 10}
            )
            result_key = "organic_results"
        payload = await _get_json(url, {"User-Agent": "cot5-overlap-search"})
        if payload.get("error"):
            raise SearchError(f"Google search provider rejected request: {payload['error']}")
        items = payload.get(result_key, [])
        if not isinstance(items, list):
            raise SearchError("Google search response has invalid items")
        for item in items:
            if not isinstance(item, dict):
                continue
            link = item.get("link")
            if not isinstance(link, str) or not link or link in seen:
                continue
            seen.add(link)
            results.append(
                {
                    "title": str(item.get("title") or ""),
                    "url": link,
                    "snippet": str(item.get("snippet") or ""),
                    "source": "web",
                }
            )
            if len(results) == 10:
                return results
    return results
