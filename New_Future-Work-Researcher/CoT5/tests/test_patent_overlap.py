import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from cot5.idea import ResearchIdea
from cot5 import patent_overlap


IDEA = ResearchIdea(title="그래프 검색", problem="검색", proposed_method="적응형 그래프 탐색")
KR = {
    "publication_number": "KR102345678B1",
    "patent_link": "https://patents.google.com/patent/KR102345678B1/ko",
    "title": "그래프 검색 방법",
    "snippet": "그래프를 탐색하는 방법",
    "publication_date": "2024-01-01",
}


def test_korean_patent_search_and_deduplication():
    with patch.dict("os.environ", {"SERPAPI_API_KEY": "secret"}, clear=True), patch.object(
        patent_overlap, "_get_json", new_callable=AsyncMock,
        return_value={"organic_results": [KR, KR, {**KR, "publication_number": "US1234B1"}]},
    ) as get_json:
        result = asyncio.run(patent_overlap.search_patents(IDEA))
    assert len(result) == 1
    assert result[0]["source"] == "google_patents_kr"
    assert result[0]["publication_number"] == "KR102345678B1"
    assert get_json.await_count == 2
    assert "engine=google_patents" in get_json.await_args_list[0].args[0]
    assert "country=KR" in get_json.await_args_list[0].args[0]
    assert "api_key=secret" in get_json.await_args_list[0].args[0]


def test_zero_results_is_empty_not_failure():
    with patch.dict("os.environ", {"SERPAPI_API_KEY": "secret"}, clear=True), patch.object(
        patent_overlap, "_get_json", new_callable=AsyncMock,
        return_value={"search_information": {"total_results": 0}},
    ):
        assert asyncio.run(patent_overlap.search_patents(IDEA)) == []


def test_serpapi_no_results_message_is_empty_not_failure():
    with patch.dict("os.environ", {"SERPAPI_API_KEY": "secret"}, clear=True), patch.object(
        patent_overlap, "_get_json", new_callable=AsyncMock,
        return_value={"error": "Google Patents hasn't returned any results for this query."},
    ):
        assert asyncio.run(patent_overlap.search_patents(IDEA)) == []


def test_missing_key_is_error():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(patent_overlap.SearchError, match="SERPAPI_API_KEY"):
            asyncio.run(patent_overlap.search_patents(IDEA))


def test_provider_error_is_not_empty_result():
    with patch.dict("os.environ", {"SERPAPI_API_KEY": "secret"}, clear=True), patch.object(
        patent_overlap, "_get_json", new_callable=AsyncMock,
        return_value={"error": "quota exceeded"},
    ):
        with pytest.raises(patent_overlap.SearchError, match="quota exceeded"):
            asyncio.run(patent_overlap.search_patents(IDEA))


def test_malformed_response_is_not_empty_result():
    with patch.dict("os.environ", {"SERPAPI_API_KEY": "secret"}, clear=True), patch.object(
        patent_overlap, "_get_json", new_callable=AsyncMock, return_value={},
    ):
        with pytest.raises(patent_overlap.SearchError, match="invalid response"):
            asyncio.run(patent_overlap.search_patents(IDEA))


def test_foreign_and_scholar_results_are_excluded():
    with patch.dict("os.environ", {"SERPAPI_API_KEY": "secret"}, clear=True), patch.object(
        patent_overlap, "_get_json", new_callable=AsyncMock,
        return_value={"organic_results": [{**KR, "is_scholar": True}, {**KR, "publication_number": "US1234B1"}]},
    ):
        assert asyncio.run(patent_overlap.search_patents(IDEA)) == []
