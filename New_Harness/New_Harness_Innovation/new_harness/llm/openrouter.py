from __future__ import annotations

import json
import os
import re
from typing import Any, Callable
import urllib.error
from urllib.request import Request, urlopen

from ..runner import WorkerContext
from ..schemas import CandidateCard, EvidenceCard, SelectedPaper


OPENROUTER_CHAT_COMPLETIONS_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODEL = "~openai/gpt-latest"
_FENCED_JSON_RE = re.compile(r"^```(?:json)?\s*(?P<body>.*?)\s*```$", re.DOTALL)


class OpenRouterError(RuntimeError):
    """Raised when the OpenRouter provider cannot return schema-valid JSON."""


class OpenRouterLLMProvider:
    """OpenRouter-backed provider for evidence and candidate generation.

    The provider intentionally depends only on the Python standard library so the
    offline fake-provider tests and dependency-free package remain usable.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        endpoint: str = OPENROUTER_CHAT_COMPLETIONS_ENDPOINT,
        timeout_seconds: float = 60.0,
        opener: Callable[..., Any] | None = None,
        app_title: str = "NEW_HARNESS_INNOVATION",
    ) -> None:
        resolved_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        if not resolved_key.strip():
            raise OpenRouterError(
                "OPENROUTER_API_KEY is required for --provider openrouter. "
                "Put it in .env.local or export it in the shell."
            )
        self.api_key = resolved_key.strip()
        self.model = (model or os.environ.get("OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODEL).strip()
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.opener = opener or urlopen
        self.app_title = app_title

    def generate_evidence_card(
        self,
        context: WorkerContext,
        paper: SelectedPaper,
    ) -> EvidenceCard:
        del context
        payload = self._chat_json(
            system=(
                "You extract evidence from selected arXiv metadata for an artifact-first "
                "research harness. Return JSON only. Do not invent details beyond the title, "
                "abstract, and provided metadata."
            ),
            user={
                "task": "Create one evidence card.",
                "required_schema": {
                    "claims": ["string"],
                    "methods": ["string"],
                    "limitations": ["string"],
                    "evaluation_signals": ["string"],
                    "future_work_clues": ["string"],
                    "quotes_or_snippets": ["string"],
                    "confidence": "number between 0 and 1",
                },
                "paper": paper.to_dict(),
            },
            max_tokens=900,
        )
        return EvidenceCard(
            paper_id=paper.paper_id,
            claims=tuple(_string_list(payload, "claims")),
            methods=tuple(_string_list(payload, "methods")),
            limitations=tuple(_string_list(payload, "limitations")),
            evaluation_signals=tuple(_string_list(payload, "evaluation_signals")),
            future_work_clues=tuple(_string_list(payload, "future_work_clues")),
            quotes_or_snippets=tuple(_string_list(payload, "quotes_or_snippets")),
            confidence=_number(payload, "confidence", default=0.5),
        )

    def generate_candidate_cards(
        self,
        context: WorkerContext,
        evidence_cards: tuple[EvidenceCard, ...],
        *,
        round_index: int,
        candidates_per_round: int,
    ) -> tuple[CandidateCard, ...]:
        del context
        candidate_ids = [f"cand-r{round_index}-{index + 1}" for index in range(candidates_per_round)]
        payload = self._chat_json(
            system=(
                "You generate evidence-grounded future-work innovation candidates. "
                "Return JSON only. Every supporting_evidence_refs entry must be one of the "
                "provided paper_id values. Do not claim novelty is externally verified."
            ),
            user={
                "task": "Create candidate cards from evidence cards.",
                "round_index": round_index,
                "candidate_ids_to_use_in_order": candidate_ids,
                "required_schema": {
                    "candidates": [
                        {
                            "candidate_id": "string",
                            "title": "string",
                            "gap_statement": "string",
                            "hypothesis": "string",
                            "supporting_evidence_refs": ["paper_id"],
                            "proposed_method": "string",
                            "evaluation_plan": "string",
                            "expected_contribution": "string",
                            "risks": ["string"],
                        }
                    ]
                },
                "evidence_cards": [card.to_dict() for card in evidence_cards],
            },
            max_tokens=1800,
        )
        raw_candidates = payload.get("candidates")
        if not isinstance(raw_candidates, list):
            raise OpenRouterError("OpenRouter candidate response must contain a candidates list")
        if len(raw_candidates) < candidates_per_round:
            raise OpenRouterError(
                f"OpenRouter returned {len(raw_candidates)} candidates; expected {candidates_per_round}"
            )

        candidates: list[CandidateCard] = []
        for index, candidate_payload in enumerate(raw_candidates[:candidates_per_round]):
            if not isinstance(candidate_payload, dict):
                raise OpenRouterError("each candidate must be a JSON object")
            normalized = dict(candidate_payload)
            normalized["candidate_id"] = candidate_ids[index]
            candidates.append(CandidateCard.from_dict(normalized))
        return tuple(candidates)

    def _chat_json(self, *, system: str, user: dict[str, Any], max_tokens: int) -> dict[str, Any]:
        request_payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False, sort_keys=True)},
            ],
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        request = Request(
            self.endpoint,
            data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-OpenRouter-Title": self.app_title,
            },
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise OpenRouterError(
                f"OpenRouter returned HTTP {exc.code} ({exc.reason}). "
                "Check OPENROUTER_API_KEY, OPENROUTER_MODEL, account credits, and rate limits."
            ) from exc
        except urllib.error.URLError as exc:
            raise OpenRouterError(f"OpenRouter request failed: {exc.reason}") from exc
        except OSError as exc:
            raise OpenRouterError(f"OpenRouter request failed: {exc}") from exc

        try:
            response_payload = json.loads(response_body)
        except json.JSONDecodeError as exc:
            preview = response_body[:200]
            raise OpenRouterError(
                f"OpenRouter response body was not valid JSON: {exc}. Body preview: {preview!r}"
            ) from exc
        content = _extract_message_content(response_payload)
        return _loads_json_object(content)


def _extract_message_content(response_payload: dict[str, Any]) -> str:
    try:
        message = response_payload["choices"][0]["message"]
        content = message["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenRouterError("OpenRouter response missing choices[0].message.content") from exc
    if isinstance(content, str):
        return content
    raise OpenRouterError("OpenRouter response content must be a string")


def _loads_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    fenced = _FENCED_JSON_RE.fullmatch(stripped)
    if fenced:
        stripped = fenced.group("body").strip()
    if not stripped.startswith("{"):
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            stripped = stripped[start : end + 1]
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise OpenRouterError(f"OpenRouter response was not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise OpenRouterError("OpenRouter response JSON must be an object")
    return payload


def _string_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise OpenRouterError(f"OpenRouter response field {key!r} must be a list")
    result = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if not result:
        raise OpenRouterError(f"OpenRouter response field {key!r} must contain at least one string")
    return result


def _number(payload: dict[str, Any], key: str, *, default: float) -> float:
    value = payload.get(key, default)
    if not isinstance(value, (int, float)):
        raise OpenRouterError(f"OpenRouter response field {key!r} must be numeric")
    return float(value)
