from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from new_harness.artifacts import RunArtifacts
from new_harness.config import HarnessConfig
from new_harness.runner import StageRunner
from new_harness.schemas import CandidateCard, EvidenceCard, ExternalCheckReport
from new_harness.stages.critic import CandidateCriticStage
from new_harness.stages.external_check import (
    ARXIV_API_ENDPOINT,
    ArxivSearchChecker,
    FakeExternalChecker,
    LocalArxivDbChecker,
    SearchEngineChecker,
    WebSearchChecker,
)


class CandidateExternalVerificationTests(unittest.TestCase):
    def test_selected_only_does_not_call_checker_and_marks_selected_only_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-selected-only")
            _seed_evidence_cards(artifacts)
            candidate = _strong_candidate("cand-selected-only")
            _write_candidates(artifacts, candidate)
            checker = FakeExternalChecker(
                {"cand-selected-only": RuntimeError("selected_only should not call checker")}
            )

            StageRunner(artifacts).run_stage(
                "candidate_critic_round_1",
                CandidateCriticStage(
                    round_index=1,
                    config=HarnessConfig(verification_depth="selected_only"),
                    external_checker=checker,
                ),
                {"critic_reports/critic_reports_round_1.json": ("reports", "report_count")},
            )

            report = artifacts.read_json("critic_reports/critic_reports_round_1.json")["reports"][0]
            self.assertEqual(checker.calls, [])
            self.assertEqual(report["verification_status"], "selected_only")
            self.assertEqual(report["novelty_risk"], "unknown")
            self.assertFalse(
                artifacts.artifact_path("external_checks/round_1/cand-selected-only.json").exists()
            )

    def test_light_external_checks_only_pass_or_near_pass_and_respects_top_k(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-light-external")
            _seed_evidence_cards(artifacts)
            strong = _strong_candidate("cand-pass")
            near_pass = _near_pass_candidate("cand-near-pass")
            fail = _fail_candidate("cand-fail")
            _write_candidates(artifacts, strong, near_pass, fail)
            checker = FakeExternalChecker(
                {
                    "cand-pass": _external_report("Grounded benchmark extension", risk="low"),
                    "cand-near-pass": _external_report("Near pass idea", risk="medium"),
                    "cand-fail": _external_report("Failing idea", risk="high"),
                }
            )

            StageRunner(artifacts).run_stage(
                "candidate_critic_round_1",
                CandidateCriticStage(
                    round_index=1,
                    config=HarnessConfig(
                        verification_depth="light_external",
                        external_check_top_k=1,
                    ),
                    external_checker=checker,
                ),
                {"critic_reports/critic_reports_round_1.json": ("reports", "report_count")},
            )

            payload = artifacts.read_json("critic_reports/critic_reports_round_1.json")
            reports = {report["candidate_id"]: report for report in payload["reports"]}
            self.assertEqual(checker.calls, ["cand-pass"])
            self.assertEqual(reports["cand-pass"]["verification_status"], "checked")
            self.assertEqual(reports["cand-near-pass"]["verification_status"], "light_external_skipped")
            self.assertEqual(reports["cand-fail"]["verification_status"], "light_external_skipped")
            self.assertEqual(reports["cand-pass"]["metadata"]["external_check_path"], "external_checks/round_1/cand-pass.json")
            self.assertFalse(
                artifacts.artifact_path("external_checks/round_1/cand-near-pass.json").exists()
            )
            self.assertFalse(artifacts.artifact_path("external_checks/round_1/cand-fail.json").exists())

    def test_strong_external_checks_every_candidate_and_downgrades_high_duplicate_risk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-strong-external")
            _seed_evidence_cards(artifacts)
            strong = _strong_candidate("cand-pass")
            fail = _fail_candidate("cand-fail")
            _write_candidates(artifacts, strong, fail)
            checker = FakeExternalChecker(
                {
                    "cand-pass": _external_report(
                        "Grounded benchmark extension",
                        risk="high",
                        matches=[{"paper_id": "2401.00001", "title": "Close duplicate"}],
                    ),
                    "cand-fail": _external_report("Failing idea", risk="low"),
                }
            )

            StageRunner(artifacts).run_stage(
                "candidate_critic_round_1",
                CandidateCriticStage(
                    round_index=1,
                    config=HarnessConfig(verification_depth="strong_external"),
                    external_checker=checker,
                ),
                {"critic_reports/critic_reports_round_1.json": ("reports", "report_count")},
            )

            payload = artifacts.read_json("critic_reports/critic_reports_round_1.json")
            reports = {report["candidate_id"]: report for report in payload["reports"]}
            self.assertEqual(set(checker.calls), {"cand-pass", "cand-fail"})
            self.assertEqual(reports["cand-pass"]["verdict"], "fail")
            self.assertEqual(reports["cand-pass"]["novelty_risk"], "high")
            self.assertEqual(reports["cand-pass"]["verification_status"], "checked")
            self.assertIn("high duplicate/publication overlap risk", " ".join(reports["cand-pass"]["weaknesses"]))
            self.assertTrue(artifacts.artifact_path("external_checks/round_1/cand-pass.json").exists())
            self.assertTrue(artifacts.artifact_path("external_checks/round_1/cand-fail.json").exists())

    def test_checker_failure_marks_degraded_status_without_clearing_novelty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-degraded-external")
            _seed_evidence_cards(artifacts)
            candidate = _strong_candidate("cand-degraded")
            _write_candidates(artifacts, candidate)
            checker = FakeExternalChecker({"cand-degraded": RuntimeError("boom")})

            StageRunner(artifacts).run_stage(
                "candidate_critic_round_1",
                CandidateCriticStage(
                    round_index=1,
                    config=HarnessConfig(verification_depth="light_external"),
                    external_checker=checker,
                ),
                {"critic_reports/critic_reports_round_1.json": ("reports", "report_count")},
            )

            report = artifacts.read_json("critic_reports/critic_reports_round_1.json")["reports"][0]
            external_payload = artifacts.read_json("external_checks/round_1/cand-degraded.json")
            self.assertEqual(report["verification_status"], "degraded")
            self.assertEqual(report["novelty_risk"], "unknown")
            self.assertIn("boom", report["metadata"]["external_check_report"]["degraded_reason"])
            self.assertIn("boom", external_payload["degraded_reason"])
            self.assertIn("degraded", " ".join(report["weaknesses"]).lower())


class CheckerImplementationTests(unittest.TestCase):
    def test_local_arxiv_db_checker_detects_duplicate_risk_from_metadata(self) -> None:
        checker = LocalArxivDbChecker(
            [
                {
                    "paper_id": "2401.00001",
                    "title": "Grounded Benchmark Extension for Cross-Domain Control",
                    "abstract": "Extends a benchmarked cross-domain controller with the same contribution.",
                },
                {
                    "paper_id": "2401.00002",
                    "title": "Different Paper",
                    "abstract": "Unrelated abstract.",
                },
            ]
        )

        report = checker.check_candidate(
            _strong_candidate("cand-local"),
            _external_context(),
        )

        self.assertEqual(report.source, "local_arxiv_db")
        self.assertEqual(report.duplicate_risk, "high")
        self.assertTrue(report.matches)
        self.assertEqual(report.matches[0]["paper_id"], "2401.00001")

    def test_arxiv_search_checker_builds_metadata_query_and_parses_atom(self) -> None:
        requests: list[tuple[str, float]] = []

        class _Response:
            def __init__(self, payload: bytes) -> None:
                self.payload = payload

            def read(self) -> bytes:
                return self.payload

            def __enter__(self) -> "_Response":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                del exc_type, exc, tb
                return None

        atom_payload = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>Grounded benchmark extension for cross-domain control</title>
    <summary>Metadata-only related work entry.</summary>
    <published>2024-01-01T00:00:00Z</published>
  </entry>
</feed>
"""

        def opener(url: str, timeout: float) -> _Response:
            requests.append((url, timeout))
            return _Response(atom_payload)

        checker = ArxivSearchChecker(opener=opener, timeout_seconds=7.5, min_interval_seconds=3.0)
        report = checker.check_candidate(_strong_candidate("cand-api"), _external_context())

        self.assertEqual(report.source, "arxiv_api")
        self.assertTrue(report.matches)
        self.assertEqual(report.matches[0]["paper_id"], "2401.00001v1")
        self.assertEqual(len(requests), 1)
        url, timeout = requests[0]
        self.assertEqual(timeout, 7.5)
        self.assertTrue(url.startswith(ARXIV_API_ENDPOINT))
        self.assertEqual(urlsplit(url).scheme, "https")
        self.assertNotIn("pdf", url.lower())
        params = parse_qs(urlsplit(url).query)
        self.assertIn("search_query", params)
        self.assertEqual(params["start"], ["0"])
        self.assertEqual(params["max_results"], ["5"])

    def test_arxiv_search_checker_degrades_on_failing_opener(self) -> None:
        def opener(url: str, timeout: float):  # noqa: ANN202
            del url, timeout
            raise OSError("network unavailable")

        checker = ArxivSearchChecker(opener=opener)
        report = checker.check_candidate(_strong_candidate("cand-api-fail"), _external_context())

        self.assertEqual(report.source, "arxiv_api")
        self.assertEqual(report.duplicate_risk, "unknown")
        self.assertIn("network unavailable", report.degraded_reason or "")

    def test_web_search_checker_parses_generic_json_results(self) -> None:
        requests: list[tuple[str, float]] = []

        class _Response:
            def read(self) -> bytes:
                return b"""{
                    "web": {
                        "results": [
                            {
                                "title": "Grounded benchmark extension for cross-domain control",
                                "url": "https://example.test/paper",
                                "description": "A benchmark-calibrated extension improves generalization."
                            }
                        ]
                    }
                }"""

            def __enter__(self) -> "_Response":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                del exc_type, exc, tb
                return None

        def opener(url: str, timeout: float) -> _Response:
            requests.append((url, timeout))
            return _Response()

        checker = WebSearchChecker(
            endpoint_url="https://search.example.test/api?existing=1",
            query_param="q",
            max_results=3,
            timeout_seconds=4.5,
            opener=opener,
        )
        report = checker.check_candidate(_strong_candidate("cand-web"), _external_context())

        self.assertEqual(report.source, "web_search")
        self.assertEqual(report.duplicate_risk, "high")
        self.assertEqual(report.matches[0]["url"], "https://example.test/paper")
        self.assertEqual(len(requests), 1)
        url, timeout = requests[0]
        self.assertEqual(timeout, 4.5)
        params = parse_qs(urlsplit(url).query)
        self.assertEqual(params["existing"], ["1"])
        self.assertEqual(params["q"], ["Grounded benchmark extension"])
        self.assertEqual(params["count"], ["3"])

    def test_search_engine_checker_parses_local_search_api_results(self) -> None:
        requests: list[tuple[str, float]] = []

        class _Response:
            def read(self) -> bytes:
                return b"""{
                    "total": 1,
                    "page": 1,
                    "size": 5,
                    "results": [
                        {
                            "arxiv_id": "2401.00001",
                            "title": "Grounded benchmark extension for cross-domain control",
                            "abstract": "A benchmark-calibrated extension can improve generalization.",
                            "authors": ["Author A"],
                            "categories": ["cs.AI"],
                            "published": "2024-01-01",
                            "score": 12.5
                        }
                    ]
                }"""

            def __enter__(self) -> "_Response":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                del exc_type, exc, tb
                return None

        def opener(url: str, timeout: float) -> _Response:
            requests.append((url, timeout))
            return _Response()

        checker = SearchEngineChecker(
            endpoint_url="http://127.0.0.1:8000/search",
            max_results=5,
            timeout_seconds=6.0,
            opener=opener,
        )
        report = checker.check_candidate(_strong_candidate("cand-search-engine"), _external_context())

        self.assertEqual(report.source, "search_engine")
        self.assertEqual(report.duplicate_risk, "high")
        self.assertEqual(report.matches[0]["paper_id"], "2401.00001")
        self.assertEqual(report.matches[0]["categories"], ["cs.AI"])
        self.assertEqual(len(requests), 1)
        url, timeout = requests[0]
        self.assertEqual(timeout, 6.0)
        params = parse_qs(urlsplit(url).query)
        self.assertEqual(params["query"], ["Grounded benchmark extension"])
        self.assertEqual(params["mode"], ["all"])
        self.assertEqual(params["sort"], ["relevance"])
        self.assertEqual(params["size"], ["5"])


def _external_report(
    query: str,
    *,
    risk: str,
    matches: list[dict[str, str]] | None = None,
) -> ExternalCheckReport:
    return ExternalCheckReport(
        query=query,
        source="fake_external_checker",
        matches=tuple(matches or []),
        duplicate_risk=risk,
        novelty_notes=(f"risk={risk}",),
        checked_at="2026-07-07T00:00:00+00:00",
    )


def _external_context():
    return type(
        "Ctx",
        (),
        {
            "round_index": 1,
            "config": HarnessConfig(),
            "evidence_by_id": {},
        },
    )()


def _seed_evidence_cards(artifacts: RunArtifacts) -> None:
    card_a = EvidenceCard(
        paper_id="paper-a",
        claims=("Benchmarking agent systems identifies a cross-domain transfer gap.",),
        methods=("A benchmark method and agent pipeline are described.",),
        limitations=("Generalization across tasks remains limited.",),
        evaluation_signals=("Experiments report benchmark accuracy and ablations.",),
        future_work_clues=("Future work should extend the benchmark to harder tasks.",),
        quotes_or_snippets=("Benchmarking agent systems",),
        confidence=0.9,
    )
    card_b = EvidenceCard(
        paper_id="paper-b",
        claims=("A symbolic control method improves planning reliability.",),
        methods=("The approach combines planning constraints with an algorithmic controller.",),
        limitations=("The controller is only tested on narrow domains.",),
        evaluation_signals=("Baseline comparison and experiment scores are reported.",),
        future_work_clues=("Future work can extend the controller to multi-domain settings.",),
        quotes_or_snippets=("Symbolic control for planning",),
        confidence=0.85,
    )
    artifacts.write_json("evidence_cards/paper-a.json", card_a.to_dict())
    artifacts.write_json("evidence_cards/paper-b.json", card_b.to_dict())
    artifacts.write_json(
        "evidence_cards/index.json",
        {
            "cards": [
                {"paper_id": "paper-a", "card_path": "evidence_cards/paper-a.json", "confidence": 0.9},
                {"paper_id": "paper-b", "card_path": "evidence_cards/paper-b.json", "confidence": 0.85},
            ],
            "card_count": 2,
        },
    )


def _write_candidates(artifacts: RunArtifacts, *candidates: CandidateCard) -> None:
    artifacts.write_json(
        "candidates/candidates_round_1.json",
        {
            "round_index": 1,
            "candidates": [candidate.to_dict() for candidate in candidates],
            "candidate_count": len(candidates),
        },
    )


def _strong_candidate(candidate_id: str) -> CandidateCard:
    return CandidateCard(
        candidate_id=candidate_id,
        title="Grounded benchmark extension",
        gap_statement="Evidence shows current evaluation leaves an open cross-domain gap.",
        hypothesis="A benchmark-calibrated extension can improve generalization.",
        supporting_evidence_refs=("paper-a", "paper-b"),
        proposed_method="Adapt the benchmarked agent pipeline into a cross-domain controller.",
        evaluation_plan="Run an ablation and benchmark comparison with reported metrics from paper-a and paper-b.",
        expected_contribution="A feasible evidence-grounded improvement.",
        risks=("Novelty not externally verified yet.",),
    )


def _near_pass_candidate(candidate_id: str) -> CandidateCard:
    return CandidateCard(
        candidate_id=candidate_id,
        title="Near pass idea",
        gap_statement="A grounded but incomplete extension idea.",
        hypothesis="A small variation might help.",
        supporting_evidence_refs=("paper-a",),
        proposed_method="Sketch a direction.",
        evaluation_plan="Benchmark pilot.",
        expected_contribution="Possibly useful insight.",
        risks=("Needs more validation.",),
    )


def _fail_candidate(candidate_id: str) -> CandidateCard:
    return CandidateCard(
        candidate_id=candidate_id,
        title="Failing idea",
        gap_statement="Something might be missing.",
        hypothesis="An idea may help.",
        supporting_evidence_refs=("paper-a",),
        proposed_method="TBD",
        evaluation_plan="TBD",
        expected_contribution="A maybe useful idea.",
        risks=("No executable plan.",),
    )


if __name__ == "__main__":
    unittest.main()
