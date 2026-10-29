"""Search Korean patent publications through SerpApi's Google Patents engine.

This is technical-overlap screening based on search snippets, not legal analysis.
"""

from __future__ import annotations

import os
from urllib.parse import urlencode

from .idea import ResearchIdea
from .open_source_overlap import SearchError, _get_json, _queries


async def search_patents(idea: ResearchIdea) -> list[dict]:
    """Return up to ten distinct KR patent-publication candidates."""
    key = os.getenv("SERPAPI_API_KEY")
    if not key:
        raise SearchError("SERPAPI_API_KEY is required for Korean patent search")

    candidates: list[dict] = []
    seen: set[str] = set()
    for query in _queries(idea):
        url = "https://serpapi.com/search.json?" + urlencode({
            "engine": "google_patents", "api_key": key, "country": "KR",
            "patents": "true", "scholar": "false", "q": query, "num": 10,
        })
        payload = await _get_json(url, {"User-Agent": "cot5-overlap-search"})
        error = str(payload.get("error") or "")
        if "hasn't returned any results for this query" in error:
            continue
        if error:
            raise SearchError(f"Korean patent search failed: {error}")
        items = payload.get("organic_results")
        if items is None and payload.get("search_information", {}).get("total_results") == 0:
            items = []
        if not isinstance(items, list):
            raise SearchError("Korean patent search returned an invalid response")

        for item in items:
            if not isinstance(item, dict) or item.get("is_scholar"):
                continue
            number = str(item.get("publication_number") or "").upper().replace("-", "")
            # Do not silently count foreign publications as Korean patents.
            if not number.startswith("KR") or number in seen:
                continue
            link = str(item.get("patent_link") or "")
            if not link.startswith("https://patents.google.com/patent/KR"):
                continue
            seen.add(number)
            candidates.append({
                "title": str(item.get("title") or number),
                "url": link,
                "snippet": str(item.get("snippet") or ""),
                "source": "google_patents_kr",
                "publication_number": number,
                "publication_date": str(item.get("publication_date") or ""),
            })
            if len(candidates) == 10:
                return candidates
    return candidates
