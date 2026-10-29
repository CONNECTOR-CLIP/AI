import unittest
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError, URLError

from cot5.idea import ResearchIdea
from cot5 import open_source_overlap as search


IDEA = ResearchIdea(title="Graph routing", problem="Scheduling", proposed_method="Adaptive graph routing")


class CandidateSearchTests(unittest.IsolatedAsyncioTestCase):


    async def test_web_requires_configuration(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(search.SearchError, "SERPAPI_API_KEY"):
                await search.search_web(IDEA)

    async def test_web_search_returns_deduplicated_candidates(self):
        item = {"title": "Demo", "link": "https://example.org/demo", "snippet": "Working demo"}
        with patch.dict("os.environ", {"GOOGLE_SEARCH_API_KEY": "secret", "GOOGLE_SEARCH_ENGINE_ID": "engine"}), patch.object(
            search, "_get_json", new_callable=AsyncMock, return_value={"items": [item]}
        ) as get_json:
            candidates = await search.search_web(IDEA)
        self.assertEqual(candidates, [{"title": "Demo", "url": "https://example.org/demo", "snippet": "Working demo", "source": "web"}])
        self.assertEqual(get_json.await_count, 2)
        self.assertIn("cx=engine", get_json.await_args_list[0].args[0])

    async def test_serpapi_google_fallback(self):
        item = {"title": "Demo", "link": "https://example.org/demo", "snippet": "Working demo"}
        with patch.dict("os.environ", {"SERPAPI_API_KEY": "secret"}, clear=True), patch.object(
            search, "_get_json", new_callable=AsyncMock, return_value={"organic_results": [item]}
        ) as get_json:
            candidates = await search.search_web(IDEA)
        self.assertEqual(len(candidates), 1)
        self.assertIn("engine=google", get_json.await_args_list[0].args[0])


    def test_http_and_network_errors_are_explicit(self):
        with patch.object(search, "urlopen", side_effect=HTTPError("url", 429, "rate limit", None, None)):
            with self.assertRaisesRegex(search.SearchError, "HTTP 429"):
                search._fetch_json("https://example.org", {})
        with patch.object(search, "urlopen", side_effect=URLError("offline")):
            with self.assertRaisesRegex(search.SearchError, "request failed"):
                search._fetch_json("https://example.org", {})


if __name__ == "__main__":
    unittest.main()
