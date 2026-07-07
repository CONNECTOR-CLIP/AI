from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from .artifacts import RunArtifacts
from .config import HarnessConfig
from .llm.base import HarnessProvider
from .llm.fake import FakeLLMProvider
from .llm.openrouter import OpenRouterError, OpenRouterLLMProvider
from .runner import StageResult, StageRunner
from .stages.candidates import CandidateLoopStage
from .stages.draft import DraftGenerationStage
from .stages.evidence import EvidenceStage
from .stages.external_check import (
    ArxivSearchChecker,
    ExternalChecker,
    SearchEngineChecker,
    WebSearchChecker,
)
from .stages.ingest import IngestStage
from .stages.revise import RevisionStage
from .stages.selection import CandidateSelectionStage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m new_harness.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the offline smoke pipeline through selection gating.")
    run_parser.add_argument("--input", required=True)
    run_parser.add_argument("--run-id", required=True)
    run_parser.add_argument("--run-root", default=".")
    run_parser.add_argument("--verification-depth", default="selected_only", choices=["selected_only", "light_external", "strong_external"])
    run_parser.add_argument("--provider", default="fake", choices=["fake", "openrouter"])
    run_parser.add_argument("--openrouter-model", default=None)
    run_parser.add_argument("--env-file", default=None, help="Optional KEY=VALUE file; defaults to .env.local/.env when present.")
    run_parser.add_argument("--external-checker", default="none", choices=["none", "arxiv_api", "web", "search_engine"])
    run_parser.add_argument("--external-check-top-k", type=int, default=2)
    run_parser.add_argument("--external-max-results", type=int, default=5)
    run_parser.add_argument("--external-timeout", type=float, default=10.0)
    run_parser.add_argument("--external-min-interval", type=float, default=3.0)
    run_parser.add_argument(
        "--external-search-url",
        default=None,
        help=(
            "Search endpoint URL for --external-checker web/search_engine. "
            "search_engine defaults to http://127.0.0.1:8000/search."
        ),
    )
    run_parser.add_argument("--external-search-query-param", default="q")
    run_parser.add_argument(
        "--external-search-api-key-env",
        default=None,
        help="Optional env var containing a web-search API key; the value is never written to artifacts.",
    )
    run_parser.add_argument(
        "--external-search-api-key-header",
        default="X-Subscription-Token",
        help="HTTP header name used with --external-search-api-key-env.",
    )

    select_parser = subparsers.add_parser("select", help="Persist selected_candidate.json for a run.")
    select_parser.add_argument("--run-id", required=True)
    select_parser.add_argument("--candidate-id", required=True)
    select_parser.add_argument("--run-root", default=".")

    draft_parser = subparsers.add_parser("draft", help="Generate draft.md and draft.claim_map.json for a run.")
    draft_parser.add_argument("--run-id", required=True)
    draft_parser.add_argument("--run-root", default=".")

    revise_parser = subparsers.add_parser("revise", help="Run offline qa_suggest or auto_edit for a run.")
    revise_parser.add_argument("--run-id", required=True)
    revise_parser.add_argument("--mode", required=True, choices=["qa_suggest", "auto_edit"])
    revise_parser.add_argument("--request", required=True)
    revise_parser.add_argument("--run-root", default=".")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command
    if command == "run":
        return _cmd_run(args)
    if command == "select":
        return _cmd_select(args)
    if command == "draft":
        return _cmd_draft(args)
    if command == "revise":
        return _cmd_revise(args)
    parser.error(f"unsupported command: {command}")
    return 2


def _cmd_run(args: argparse.Namespace) -> int:
    _load_env(args.env_file)
    artifacts = RunArtifacts(Path(args.run_root), run_id=args.run_id)
    runner = StageRunner(artifacts)
    try:
        config = HarnessConfig(
            verification_depth=args.verification_depth,
            external_check_top_k=args.external_check_top_k,
            external_search_max_results=args.external_max_results,
            external_request_timeout_seconds=args.external_timeout,
            external_request_min_interval_seconds=args.external_min_interval,
        )
    except ValueError as exc:
        return _emit_and_exit(
            StageResult(status="failed", metadata={"reason": "configuration_error"}, error=str(exc)),
            artifacts,
        )
    try:
        provider = _build_provider(args)
    except OpenRouterError as exc:
        return _emit_and_exit(
            StageResult(status="failed", metadata={"reason": "provider_configuration_error"}, error=str(exc)),
            artifacts,
        )
    try:
        external_checker = _build_external_checker(args, config)
    except ValueError as exc:
        return _emit_and_exit(
            StageResult(status="failed", metadata={"reason": "external_checker_configuration_error"}, error=str(exc)),
            artifacts,
        )
    ingest_result = runner.run_stage(
        "ingest",
        IngestStage(Path(args.input)),
        {"selected_papers.normalized.json": ("selected_papers",)},
    )
    if ingest_result.status != "success":
        return _emit_and_exit(ingest_result, artifacts)
    _prepare_offline_smoke_selected_papers(artifacts)
    evidence_result = runner.run_stage(
        "evidence",
        EvidenceStage(provider),
        {"evidence_cards/index.json": ("cards", "card_count")},
    )
    if evidence_result.status != "success":
        return _emit_and_exit(evidence_result, artifacts)

    candidate_result = runner.run_stage(
        "candidate_loop",
        CandidateLoopStage(config=config, provider=provider, external_checker=external_checker),
        {"candidate_loop.json": ("status", "rounds_completed")},
    )
    return _emit_and_exit(candidate_result, artifacts)


def _build_provider(args: argparse.Namespace) -> HarnessProvider:
    if args.provider == "fake":
        return FakeLLMProvider()
    if args.provider == "openrouter":
        return OpenRouterLLMProvider(model=args.openrouter_model)
    raise ValueError(f"unsupported provider: {args.provider}")


def _build_external_checker(
    args: argparse.Namespace,
    config: HarnessConfig,
) -> ExternalChecker | None:
    if args.external_checker == "none":
        return None
    if args.external_checker == "arxiv_api":
        return ArxivSearchChecker(
            max_results=config.external_search_max_results,
            timeout_seconds=config.external_request_timeout_seconds,
            min_interval_seconds=config.external_request_min_interval_seconds,
        )
    if args.external_checker == "web":
        if not args.external_search_url:
            raise ValueError("--external-search-url is required when --external-checker web")
        return WebSearchChecker(
            endpoint_url=args.external_search_url,
            query_param=args.external_search_query_param,
            max_results=config.external_search_max_results,
            timeout_seconds=config.external_request_timeout_seconds,
            min_interval_seconds=config.external_request_min_interval_seconds,
            headers=_external_search_headers(args),
        )
    if args.external_checker == "search_engine":
        return SearchEngineChecker(
            endpoint_url=args.external_search_url or "http://127.0.0.1:8000/search",
            max_results=config.external_search_max_results,
            timeout_seconds=config.external_request_timeout_seconds,
            min_interval_seconds=config.external_request_min_interval_seconds,
        )
    raise ValueError(f"unsupported external checker: {args.external_checker}")


def _external_search_headers(args: argparse.Namespace) -> dict[str, str]:
    if not args.external_search_api_key_env:
        return {}
    key = os.environ.get(args.external_search_api_key_env, "")
    if not key.strip():
        raise ValueError(f"{args.external_search_api_key_env} is required for web external search")
    header_name = str(args.external_search_api_key_header or "").strip()
    if not header_name:
        raise ValueError("--external-search-api-key-header cannot be empty")
    return {header_name: key.strip()}


def _load_env(env_file: str | None) -> None:
    paths = [Path(env_file)] if env_file else [Path(".env.local"), Path(".env")]
    for path in paths:
        if path.exists():
            _load_env_file(path)


def _load_env_file(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _cmd_select(args: argparse.Namespace) -> int:
    artifacts = RunArtifacts(Path(args.run_root), run_id=args.run_id)
    runner = StageRunner(artifacts)
    result = runner.run_stage(
        "selection",
        CandidateSelectionStage(requested_run_id=args.run_id, candidate_id=args.candidate_id),
        {"selected_candidate.json": ("run_id", "candidate_id", "selected_at", "source_paths")},
        force=True,
    )
    return _emit_and_exit(result, artifacts)


def _cmd_draft(args: argparse.Namespace) -> int:
    artifacts = RunArtifacts(Path(args.run_root), run_id=args.run_id)
    runner = StageRunner(artifacts)
    result = runner.run_stage(
        "draft",
        DraftGenerationStage(),
        {"draft.md": (), "draft.claim_map.json": ("run_id", "candidate_id", "claims", "risk_notes")},
        force=True,
    )
    return _emit_and_exit(result, artifacts)


def _cmd_revise(args: argparse.Namespace) -> int:
    artifacts = RunArtifacts(Path(args.run_root), run_id=args.run_id)
    runner = StageRunner(artifacts)
    result = runner.run_stage(
        f"revise_{args.mode}",
        RevisionStage(requested_run_id=args.run_id, mode=args.mode, user_request=args.request),
        {},
        force=True,
    )
    return _emit_and_exit(result, artifacts)


def _prepare_offline_smoke_selected_papers(artifacts: RunArtifacts) -> None:
    payload = artifacts.read_json("selected_papers.normalized.json")
    selected_papers = payload.get("selected_papers", [])
    changed = False
    for index, paper in enumerate(selected_papers):
        if not isinstance(paper, dict):
            continue
        paper_id = paper.get("paper_id", f"paper-{index + 1}")
        title = paper.get("title") or f"Offline smoke paper {index + 1}: {paper_id}"
        abstract = paper.get("abstract") or (
            f"{title} describes a deterministic method, benchmark evaluation, and future work direction for {paper_id}. "
            f"The approach reports experiment signals and highlights one limitation that future work can address."
        )
        if paper.get("title") != title:
            paper["title"] = title
            changed = True
        if paper.get("abstract") != abstract:
            paper["abstract"] = abstract
            changed = True
    if changed:
        artifacts.write_json("selected_papers.normalized.json", payload)


def _emit_and_exit(result, artifacts: RunArtifacts) -> int:
    payload = {
        "run_id": artifacts.run_id,
        "run_dir": str(artifacts.run_dir),
        "status": result.status,
        "artifacts": list(result.artifacts),
        "metadata": dict(result.metadata),
        "error": result.error,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if result.status in {"success", "selection_required", "blocked"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
