from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from ..config import HarnessConfig
from ..schemas import CandidateCard, EvidenceCard, ExternalCheckReport


ARXIV_API_ENDPOINT = "https://export.arxiv.org/api/query"
ATOM_NAMESPACE = {"atom": "http://www.w3.org/2005/Atom"}


@dataclass(frozen=True)
class ExternalCheckContext:
    round_index: int
    config: HarnessConfig
    evidence_by_id: Mapping[str, EvidenceCard]


class ExternalChecker(Protocol):
    def check_candidate(
        self,
        candidate: CandidateCard,
        context: ExternalCheckContext,
    ) -> ExternalCheckReport: ...


class FakeExternalChecker:
    """Deterministic checker seam for unit tests."""

    def __init__(
        self,
        reports_by_candidate_id: Mapping[str, ExternalCheckReport | Exception] | None = None,
    ) -> None:
        self.reports_by_candidate_id = dict(reports_by_candidate_id or {})
        self.calls: list[str] = []

    def check_candidate(
        self,
        candidate: CandidateCard,
        context: ExternalCheckContext,
    ) -> ExternalCheckReport:
        del context
        self.calls.append(candidate.candidate_id)
        report_or_exc = self.reports_by_candidate_id.get(candidate.candidate_id)
        if isinstance(report_or_exc, Exception):
            raise report_or_exc
        if isinstance(report_or_exc, ExternalCheckReport):
            return report_or_exc
        risk = "high" if "duplicate" in candidate.title.lower() else "low"
        return ExternalCheckReport(
            query=build_candidate_query(candidate),
            source="fake_external_checker",
            matches=[],
            duplicate_risk=risk,
            novelty_notes=(f"Deterministic fake risk={risk}.",),
            checked_at=_checked_at_now(),
        )


class LocalArxivDbChecker:
    """Metadata-only duplicate risk checker over a local JSON/list corpus."""

    def __init__(self, corpus: Sequence[Mapping[str, Any]] | str | Path) -> None:
        if isinstance(corpus, (str, Path)):
            payload = json.loads(Path(corpus).read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError("local arXiv corpus JSON must contain a list")
            self.corpus = [dict(item) for item in payload if isinstance(item, dict)]
        else:
            self.corpus = [dict(item) for item in corpus if isinstance(item, Mapping)]

    def check_candidate(
        self,
        candidate: CandidateCard,
        context: ExternalCheckContext,
    ) -> ExternalCheckReport:
        del context
        query = build_candidate_query(candidate)
        candidate_title = _normalize_text(candidate.title)
        candidate_text = _normalize_text(
            " ".join(
                (
                    candidate.title,
                    candidate.gap_statement,
                    candidate.hypothesis,
                    candidate.proposed_method,
                    candidate.expected_contribution,
                )
            )
        )
        scored_matches: list[tuple[float, dict[str, Any]]] = []
        for item in self.corpus:
            title = str(item.get("title", ""))
            abstract = str(item.get("abstract", ""))
            title_norm = _normalize_text(title)
            combined_norm = _normalize_text(f"{title} {abstract}")
            title_overlap = _token_overlap(candidate_title, title_norm)
            text_overlap = _token_overlap(candidate_text, combined_norm)
            exact_title = 1.0 if candidate_title and candidate_title == title_norm else 0.0
            contained_title = (
                0.9
                if candidate_title
                and len(candidate_title.split()) >= 3
                and (candidate_title in title_norm or title_norm in candidate_title)
                else 0.0
            )
            score = max(exact_title, contained_title, 0.8 * title_overlap + 0.2 * text_overlap)
            if score < 0.2:
                continue
            scored_matches.append(
                (
                    score,
                    {
                        "paper_id": item.get("paper_id") or item.get("id") or "",
                        "title": title,
                        "abstract": abstract[:280],
                        "score": round(score, 3),
                    },
                )
            )
        scored_matches.sort(key=lambda item: (-item[0], str(item[1].get("paper_id", ""))))
        matches = [match for _, match in scored_matches[:3]]
        top_score = scored_matches[0][0] if scored_matches else 0.0
        duplicate_risk = _risk_from_similarity(top_score)
        notes = (
            (f"Top local metadata similarity score={top_score:.3f}.",)
            if scored_matches
            else ("No strong local metadata duplicate signals were found.",)
        )
        return ExternalCheckReport(
            query=query,
            source="local_arxiv_db",
            matches=tuple(matches),
            duplicate_risk=duplicate_risk,
            novelty_notes=notes,
            checked_at=_checked_at_now(),
        )


class WebSearchChecker:
    """Generic JSON web-search checker for configurable HTTP search APIs.

    The checker intentionally depends only on a caller-provided JSON search endpoint.
    This keeps the harness provider-neutral: Brave, SerpAPI, a private search proxy,
    or any compatible endpoint can be used without adding SDK dependencies.
    """

    def __init__(
        self,
        *,
        endpoint_url: str,
        query_param: str = "q",
        max_results: int = 5,
        result_count_param: str | None = "count",
        timeout_seconds: float = 10.0,
        min_interval_seconds: float = 3.0,
        headers: Mapping[str, str] | None = None,
        opener: Callable[..., Any] | None = None,
        now_fn: Callable[[], float] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        cleaned_endpoint = endpoint_url.strip()
        if not cleaned_endpoint:
            raise ValueError("endpoint_url is required for web search")
        cleaned_query_param = query_param.strip()
        if not cleaned_query_param:
            raise ValueError("query_param is required for web search")
        if max_results < 1:
            raise ValueError("max_results must be a positive integer")
        self.endpoint_url = cleaned_endpoint
        self.query_param = cleaned_query_param
        self.max_results = max_results
        self.result_count_param = result_count_param
        self.timeout_seconds = timeout_seconds
        self.min_interval_seconds = min_interval_seconds
        self.headers = dict(headers or {})
        self.opener = opener or urlopen
        self.now_fn = now_fn or time.monotonic
        self.sleep_fn = sleep_fn or time.sleep
        self._last_request_at: float | None = None

    def check_candidate(
        self,
        candidate: CandidateCard,
        context: ExternalCheckContext,
    ) -> ExternalCheckReport:
        del context
        query = build_candidate_query(candidate)
        params: dict[str, Any] = {self.query_param: query}
        if self.result_count_param:
            params[self.result_count_param] = self.max_results
        url = _url_with_params(self.endpoint_url, params)
        try:
            self._respect_rate_limit()
            payload = _read_json_url(
                self.opener,
                url,
                timeout_seconds=self.timeout_seconds,
                headers=self.headers,
            )
            matches = _extract_web_matches(payload, candidate=candidate, max_results=self.max_results)
            duplicate_risk = _risk_from_matches(matches)
            return ExternalCheckReport(
                query=query,
                source="web_search",
                matches=tuple(matches),
                duplicate_risk=duplicate_risk,
                novelty_notes=(
                    "Generic JSON web search completed.",
                    f"endpoint_host={urlsplit(self.endpoint_url).netloc or 'local'}",
                ),
                checked_at=_checked_at_now(),
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return degraded_external_check_report(
                query=query,
                source="web_search",
                reason=f"{type(exc).__name__}: {exc}",
            )

    def _respect_rate_limit(self) -> None:
        if self._last_request_at is None:
            self._last_request_at = self.now_fn()
            return
        elapsed = self.now_fn() - self._last_request_at
        remaining = self.min_interval_seconds - elapsed
        if remaining > 0:
            self.sleep_fn(remaining)
        self._last_request_at = self.now_fn()


class SearchEngineChecker:
    """Checker adapter for the local D:/SearchEngine FastAPI /search service."""

    def __init__(
        self,
        *,
        endpoint_url: str = "http://127.0.0.1:8000/search",
        max_results: int = 5,
        timeout_seconds: float = 10.0,
        min_interval_seconds: float = 3.0,
        opener: Callable[..., Any] | None = None,
        now_fn: Callable[[], float] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        cleaned_endpoint = endpoint_url.strip()
        if not cleaned_endpoint:
            raise ValueError("endpoint_url is required for SearchEngine checker")
        if max_results < 1:
            raise ValueError("max_results must be a positive integer")
        self.endpoint_url = cleaned_endpoint
        self.max_results = max_results
        self.timeout_seconds = timeout_seconds
        self.min_interval_seconds = min_interval_seconds
        self.opener = opener or urlopen
        self.now_fn = now_fn or time.monotonic
        self.sleep_fn = sleep_fn or time.sleep
        self._last_request_at: float | None = None

    def check_candidate(
        self,
        candidate: CandidateCard,
        context: ExternalCheckContext,
    ) -> ExternalCheckReport:
        del context
        query = build_candidate_query(candidate)
        url = _url_with_params(
            self.endpoint_url,
            {
                "query": query,
                "mode": "all",
                "sort": "relevance",
                "page": 1,
                "size": self.max_results,
            },
        )
        try:
            self._respect_rate_limit()
            payload = _read_json_url(
                self.opener,
                url,
                timeout_seconds=self.timeout_seconds,
                headers={},
            )
            matches = _extract_search_engine_matches(payload, candidate=candidate, max_results=self.max_results)
            duplicate_risk = _risk_from_matches(matches)
            return ExternalCheckReport(
                query=query,
                source="search_engine",
                matches=tuple(matches),
                duplicate_risk=duplicate_risk,
                novelty_notes=(
                    "Local SearchEngine /search metadata check completed.",
                    f"total={payload.get('total', 'unknown') if isinstance(payload, dict) else 'unknown'}",
                ),
                checked_at=_checked_at_now(),
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return degraded_external_check_report(
                query=query,
                source="search_engine",
                reason=f"{type(exc).__name__}: {exc}",
            )

    def _respect_rate_limit(self) -> None:
        if self._last_request_at is None:
            self._last_request_at = self.now_fn()
            return
        elapsed = self.now_fn() - self._last_request_at
        remaining = self.min_interval_seconds - elapsed
        if remaining > 0:
            self.sleep_fn(remaining)
        self._last_request_at = self.now_fn()


class ArxivSearchChecker:
    """Metadata-only arXiv API checker using Atom XML responses and no PDF downloads."""

    def __init__(
        self,
        *,
        max_results: int = 5,
        timeout_seconds: float = 10.0,
        min_interval_seconds: float = 3.0,
        opener: Callable[..., Any] | None = None,
        now_fn: Callable[[], float] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self.max_results = max_results
        self.timeout_seconds = timeout_seconds
        self.min_interval_seconds = min_interval_seconds
        self.opener = opener or urlopen
        self.now_fn = now_fn or time.monotonic
        self.sleep_fn = sleep_fn or time.sleep
        self._last_request_at: float | None = None

    def check_candidate(
        self,
        candidate: CandidateCard,
        context: ExternalCheckContext,
    ) -> ExternalCheckReport:
        del context
        query = build_candidate_query(candidate)
        params = {
            "search_query": f'all:"{query}"',
            "start": 0,
            "max_results": self.max_results,
        }
        url = f"{ARXIV_API_ENDPOINT}?{urlencode(params)}"
        try:
            self._respect_rate_limit()
            with self.opener(url, timeout=self.timeout_seconds) as response:
                payload = response.read()
            root = ET.fromstring(payload)
            entries = root.findall("atom:entry", ATOM_NAMESPACE)
            matches: list[dict[str, Any]] = []
            best_similarity = 0.0
            for entry in entries:
                title = _entry_text(entry, "atom:title")
                summary = _entry_text(entry, "atom:summary")
                paper_id = _entry_id(entry)
                similarity = max(
                    _token_overlap(_normalize_text(candidate.title), _normalize_text(title)),
                    _token_overlap(_normalize_text(query), _normalize_text(f"{title} {summary}")),
                )
                best_similarity = max(best_similarity, similarity)
                matches.append(
                    {
                        "paper_id": paper_id,
                        "title": title,
                        "summary": summary[:280],
                        "published": _entry_text(entry, "atom:published"),
                        "score": round(similarity, 3),
                    }
                )
            return ExternalCheckReport(
                query=query,
                source="arxiv_api",
                matches=tuple(matches),
                duplicate_risk=_risk_from_similarity(best_similarity),
                novelty_notes=("Metadata-only arXiv API search completed.",),
                checked_at=_checked_at_now(),
            )
        except (OSError, ET.ParseError) as exc:
            return degraded_external_check_report(
                query=query,
                source="arxiv_api",
                reason=f"{type(exc).__name__}: {exc}",
            )

    def _respect_rate_limit(self) -> None:
        if self._last_request_at is None:
            self._last_request_at = self.now_fn()
            return
        elapsed = self.now_fn() - self._last_request_at
        remaining = self.min_interval_seconds - elapsed
        if remaining > 0:
            self.sleep_fn(remaining)
        self._last_request_at = self.now_fn()


def build_candidate_query(candidate: CandidateCard) -> str:
    return " ".join(candidate.title.strip().split())[:180]


def degraded_external_check_report(*, query: str, source: str, reason: str) -> ExternalCheckReport:
    return ExternalCheckReport(
        query=query,
        source=source,
        matches=(),
        duplicate_risk="unknown",
        novelty_notes=("External novelty verification degraded.",),
        checked_at=_checked_at_now(),
        degraded_reason=reason,
    )


def should_external_check_candidate(
    report: Any,
    *,
    verification_depth: str,
) -> bool:
    if verification_depth == "strong_external":
        return True
    if verification_depth == "light_external":
        return report.verdict == "pass" or bool(report.near_pass)
    return False


def _checked_at_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else " " for char in value)
    return " ".join(cleaned.split())


def _token_overlap(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _risk_from_similarity(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _url_with_params(endpoint_url: str, params: Mapping[str, Any]) -> str:
    parts = urlsplit(endpoint_url)
    query_items = parse_qsl(parts.query, keep_blank_values=True)
    query_items.extend((key, str(value)) for key, value in params.items() if value is not None)
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query_items),
            parts.fragment,
        )
    )


def _read_json_url(
    opener: Callable[..., Any],
    url: str,
    *,
    timeout_seconds: float,
    headers: Mapping[str, str],
) -> Any:
    request: str | Request
    request = Request(url, headers=dict(headers)) if headers else url
    with opener(request, timeout=timeout_seconds) as response:
        raw = response.read()
    if isinstance(raw, bytes):
        text = raw.decode("utf-8")
    else:
        text = str(raw)
    payload = json.loads(text)
    if not isinstance(payload, (dict, list)):
        raise ValueError("search response must be a JSON object or list")
    return payload


def _extract_search_engine_matches(
    payload: Any,
    *,
    candidate: CandidateCard,
    max_results: int,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("SearchEngine response must be a JSON object")
    raw_results = payload.get("results", [])
    if not isinstance(raw_results, list):
        raise ValueError("SearchEngine response.results must be a list")
    matches: list[dict[str, Any]] = []
    candidate_title = _normalize_text(candidate.title)
    candidate_text = _candidate_similarity_text(candidate)
    for item in raw_results[:max_results]:
        if not isinstance(item, Mapping):
            continue
        title = str(item.get("title", ""))
        abstract = str(item.get("abstract") or "")
        title_norm = _normalize_text(title)
        combined = _normalize_text(f"{title} {abstract}")
        contained_title = (
            0.9
            if candidate_title
            and len(candidate_title.split()) >= 3
            and (candidate_title in title_norm or title_norm in candidate_title)
            else 0.0
        )
        similarity = max(
            contained_title,
            _token_overlap(candidate_title, title_norm),
            _token_overlap(candidate_text, combined),
        )
        matches.append(
            {
                "paper_id": item.get("arxiv_id") or item.get("paper_id") or "",
                "title": title,
                "abstract": abstract[:280],
                "authors": list(item.get("authors", [])) if isinstance(item.get("authors"), list) else [],
                "categories": list(item.get("categories", [])) if isinstance(item.get("categories"), list) else [],
                "published": item.get("published"),
                "score": item.get("score"),
                "similarity": round(similarity, 3),
            }
        )
    return matches


def _extract_web_matches(
    payload: Any,
    *,
    candidate: CandidateCard,
    max_results: int,
) -> list[dict[str, Any]]:
    raw_results = _find_web_result_list(payload)
    candidate_title = _normalize_text(candidate.title)
    candidate_text = _candidate_similarity_text(candidate)
    matches: list[dict[str, Any]] = []
    for raw_item in raw_results[:max_results]:
        item = _unwrap_search_item(raw_item)
        if not isinstance(item, Mapping):
            continue
        title = _first_str(item, ("title", "name", "headline"))
        snippet = _first_str(item, ("snippet", "description", "summary", "content", "abstract"))
        url = _first_str(item, ("url", "link", "href"))
        title_norm = _normalize_text(title)
        combined = _normalize_text(f"{title} {snippet}")
        contained_title = (
            0.9
            if candidate_title
            and len(candidate_title.split()) >= 3
            and (candidate_title in title_norm or title_norm in candidate_title)
            else 0.0
        )
        similarity = max(
            contained_title,
            _token_overlap(candidate_title, title_norm),
            _token_overlap(candidate_text, combined),
        )
        match: dict[str, Any] = {
            "title": title,
            "url": url,
            "snippet": snippet[:280],
            "score": item.get("score") or item.get("_score"),
            "similarity": round(similarity, 3),
        }
        if item.get("paper_id") or item.get("arxiv_id"):
            match["paper_id"] = item.get("paper_id") or item.get("arxiv_id")
        matches.append(match)
    return matches


def _find_web_result_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, Mapping):
        raise ValueError("web search response must be a JSON object or list")
    for key in ("results", "items", "organic_results"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    web = payload.get("web")
    if isinstance(web, Mapping) and isinstance(web.get("results"), list):
        return list(web["results"])
    web_pages = payload.get("webPages")
    if isinstance(web_pages, Mapping) and isinstance(web_pages.get("value"), list):
        return list(web_pages["value"])
    hits = payload.get("hits")
    if isinstance(hits, Mapping) and isinstance(hits.get("hits"), list):
        return list(hits["hits"])
    raise ValueError("web search response did not contain a supported results list")


def _unwrap_search_item(item: Any) -> Any:
    if isinstance(item, Mapping) and isinstance(item.get("_source"), Mapping):
        merged = dict(item["_source"])
        if "_score" in item:
            merged["_score"] = item["_score"]
        return merged
    return item


def _first_str(item: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def _candidate_similarity_text(candidate: CandidateCard) -> str:
    return _normalize_text(
        " ".join(
            (
                candidate.title,
                candidate.gap_statement,
                candidate.hypothesis,
                candidate.proposed_method,
                candidate.expected_contribution,
            )
        )
    )


def _risk_from_matches(matches: Sequence[Mapping[str, Any]]) -> str:
    top_similarity = 0.0
    for match in matches:
        value = match.get("similarity", 0.0)
        if isinstance(value, (int, float)):
            top_similarity = max(top_similarity, float(value))
    return _risk_from_similarity(top_similarity)


def _entry_text(entry: ET.Element, selector: str) -> str:
    node = entry.find(selector, ATOM_NAMESPACE)
    return "" if node is None or node.text is None else " ".join(node.text.split())


def _entry_id(entry: ET.Element) -> str:
    raw_id = _entry_text(entry, "atom:id")
    return raw_id.rsplit("/", 1)[-1]
