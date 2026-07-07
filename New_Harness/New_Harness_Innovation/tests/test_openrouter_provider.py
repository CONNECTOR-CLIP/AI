from __future__ import annotations

import json
import socket
import unittest
import urllib.error

from new_harness.llm.openrouter import OpenRouterError, OpenRouterLLMProvider
from new_harness.runner import WorkerContext
from new_harness.schemas import EvidenceCard, SelectedPaper
from new_harness.artifacts import RunArtifacts
from pathlib import Path
import tempfile


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb
        return None


class OpenRouterProviderTests(unittest.TestCase):
    def test_missing_key_raises_actionable_error(self) -> None:
        with self.assertRaisesRegex(OpenRouterError, "OPENROUTER_API_KEY"):
            OpenRouterLLMProvider(api_key="")

    def test_generate_evidence_card_posts_chat_completion_and_parses_json(self) -> None:
        requests = []

        def opener(request, timeout):  # noqa: ANN001, ANN202
            requests.append((request, timeout))
            return _Response(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "claims": ["Claim from metadata."],
                                        "methods": ["Method from abstract."],
                                        "limitations": ["Limitation from abstract."],
                                        "evaluation_signals": ["Evaluation signal."],
                                        "future_work_clues": ["Future clue."],
                                        "quotes_or_snippets": ["Snippet."],
                                        "confidence": 0.77,
                                    }
                                )
                            }
                        }
                    ]
                }
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            provider = OpenRouterLLMProvider(api_key="sk-test", model="test/model", opener=opener)
            card = provider.generate_evidence_card(
                _context(Path(tmp_dir)),
                SelectedPaper(
                    paper_id="2401.14196",
                    title="A title",
                    abstract="An abstract with method and evaluation.",
                    abs_url="https://arxiv.org/abs/2401.14196",
                ),
            )

        self.assertEqual(card.paper_id, "2401.14196")
        self.assertEqual(card.confidence, 0.77)
        request, timeout = requests[0]
        self.assertEqual(timeout, 60.0)
        self.assertEqual(request.full_url, "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer sk-test")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["model"], "test/model")
        self.assertEqual(body["response_format"], {"type": "json_object"})

    def test_generate_candidate_cards_uses_expected_ids_and_validates_count(self) -> None:
        def opener(request, timeout):  # noqa: ANN001, ANN202
            del request, timeout
            return _Response(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "candidates": [
                                            {
                                                "candidate_id": "ignored",
                                                "title": "Grounded candidate",
                                                "gap_statement": "Gap from evidence.",
                                                "hypothesis": "A testable hypothesis.",
                                                "supporting_evidence_refs": ["paper-a"],
                                                "proposed_method": "A concrete method.",
                                                "evaluation_plan": "Run a benchmark evaluation.",
                                                "expected_contribution": "A useful contribution.",
                                                "risks": ["Novelty not externally verified."],
                                            }
                                        ]
                                    }
                                )
                            }
                        }
                    ]
                }
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            provider = OpenRouterLLMProvider(api_key="sk-test", opener=opener)
            candidate = provider.generate_candidate_cards(
                _context(Path(tmp_dir)),
                (
                    EvidenceCard(
                        paper_id="paper-a",
                        claims=("Claim.",),
                        methods=("Method.",),
                        limitations=("Limit.",),
                        evaluation_signals=("Eval.",),
                        future_work_clues=("Future.",),
                        quotes_or_snippets=("Snippet.",),
                        confidence=0.8,
                    ),
                ),
                round_index=2,
                candidates_per_round=1,
            )[0]

        self.assertEqual(candidate.candidate_id, "cand-r2-1")
        self.assertEqual(candidate.supporting_evidence_refs, ("paper-a",))

    def test_invalid_json_response_raises_provider_error(self) -> None:
        def opener(request, timeout):  # noqa: ANN001, ANN202
            del request, timeout
            return _Response({"choices": [{"message": {"content": "not-json"}}]})

        with tempfile.TemporaryDirectory() as tmp_dir:
            provider = OpenRouterLLMProvider(api_key="sk-test", opener=opener)
            with self.assertRaisesRegex(OpenRouterError, "not valid JSON"):
                provider.generate_evidence_card(
                    _context(Path(tmp_dir)),
                    SelectedPaper(paper_id="2401.14196", title="A title"),
                )

    def test_non_json_openrouter_response_body_raises_provider_error(self) -> None:
        class _HtmlResponse:
            def read(self) -> bytes:
                return b"<html>temporarily unavailable</html>"

            def __enter__(self) -> "_HtmlResponse":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                del exc_type, exc, tb
                return None

        def opener(request, timeout):  # noqa: ANN001, ANN202
            del request, timeout
            return _HtmlResponse()

        with tempfile.TemporaryDirectory() as tmp_dir:
            provider = OpenRouterLLMProvider(api_key="sk-test", opener=opener)
            with self.assertRaisesRegex(OpenRouterError, "response body was not valid JSON"):
                provider.generate_evidence_card(
                    _context(Path(tmp_dir)),
                    SelectedPaper(paper_id="2401.14196", title="A title"),
                )

    def test_http_error_raises_actionable_provider_error(self) -> None:
        def opener(request, timeout):  # noqa: ANN001, ANN202
            del timeout
            raise urllib.error.HTTPError(
                url=request.full_url,
                code=401,
                msg="Unauthorized",
                hdrs={},
                fp=None,
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            provider = OpenRouterLLMProvider(api_key="sk-test", opener=opener)
            with self.assertRaisesRegex(OpenRouterError, "HTTP 401"):
                provider.generate_evidence_card(
                    _context(Path(tmp_dir)),
                    SelectedPaper(paper_id="2401.14196", title="A title"),
                )

    def test_read_timeout_raises_provider_error(self) -> None:
        class _TimeoutResponse:
            def read(self) -> bytes:
                raise socket.timeout("timed out while reading")

            def __enter__(self) -> "_TimeoutResponse":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                del exc_type, exc, tb
                return None

        def opener(request, timeout):  # noqa: ANN001, ANN202
            del request, timeout
            return _TimeoutResponse()

        with tempfile.TemporaryDirectory() as tmp_dir:
            provider = OpenRouterLLMProvider(api_key="sk-test", opener=opener)
            with self.assertRaisesRegex(OpenRouterError, "timed out while reading"):
                provider.generate_evidence_card(
                    _context(Path(tmp_dir)),
                    SelectedPaper(paper_id="2401.14196", title="A title"),
                )


def _context(root: Path) -> WorkerContext:
    artifacts = RunArtifacts(root, run_id="openrouter-test")
    return WorkerContext(run_id="openrouter-test", stage_name="test", artifacts=artifacts)


if __name__ == "__main__":
    unittest.main()
