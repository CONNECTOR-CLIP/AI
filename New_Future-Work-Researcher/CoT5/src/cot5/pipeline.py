from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import ensure_submodule_importable, load_config, submodule_cwd
from .equivalence import check_all_papers
from .idea import ResearchIdea
from .provider import LLMProvider, OpenAIProvider
from .verdict import Verdict, apply_equivalence_override, resolve_verdict
from .overlap import check_source, paper_overlap
from .open_source_overlap import search_web
from .patent_overlap import search_patents
from .retrieval_sources import summarize_trace
import asyncio

MAX_ITERATIONS = 2  # 구현 파라미터. README 10절의 반복 검색을, 검색 API 재현성(temperature=0)을
# 감안해 "실패 시 그대로 재시도"하는 보수적 bounded retry로 구현한다(자세한 설명은 iterate() 참고).


@dataclass(slots=True)
class NoveltyCheckResult:
    idea_title: str
    verdict: Verdict
    review: str
    evaluated_paper_count: int
    dropped_by_cutoff_count: int
    iterations: int
    equivalence_results: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_at: str = ""
    overlaps: dict[str, dict[str, Any]] = field(default_factory=dict)
    paper_search: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "idea_title": self.idea_title,
            "classification": self.verdict.classification,
            "reason": self.verdict.reason,
            "review": self.review,
            "evaluated_paper_count": self.evaluated_paper_count,
            "dropped_by_cutoff_count": self.dropped_by_cutoff_count,
            "iterations": self.iterations,
            "equivalence_results": self.equivalence_results,
            "warnings": self.warnings,
            "checked_at": self.checked_at,
            "overlaps": self.overlaps,
            "paper_search": self.paper_search,
        }
        # Collapse exact duplicates only at the output boundary. Keep the
        # internal result and all retrieval/evaluation behaviour unchanged.
        paper = self.overlaps.get("paper", {})
        if paper.get("candidates") == self.equivalence_results:
            payload.pop("equivalence_results")
        if paper.get("checked_count") == self.evaluated_paper_count:
            payload.pop("evaluated_paper_count")
        return payload


async def _run_once(idea_text: str, seed_paper_ids: list[str], cutoff_date: str | None):
    ensure_submodule_importable()
    from noveltychecker.models.idea_novelty_checker.pipeline import run_ideanoveltychecker

    with submodule_cwd():
        output = await run_ideanoveltychecker(
            idea_text,
            use_retrieval=True,
            input_papers_ids=seed_paper_ids,
            cutoff_date=cutoff_date,
        )
    return output


async def check_novelty(
    idea: ResearchIdea, *, config_path: str | None = None, provider: LLMProvider | None = None
) -> NoveltyCheckResult:
    """README.md 전체 하네스(4절)의 진입점. idea_novelty_checker(외부 submodule)를 호출해
    NOVEL/NOT_NOVEL/UNCERTAIN 판정을 만든다. LLM의 내부 기억만으로 판정하지 않고, 검색된 문헌을
    근거로만 판단한다는 원칙(README 1절)은 submodule이 그대로 지킨다 — CoT5는 그 위에 cutoff
    필터링, Si et al.의 논문별 동등성 검사(8절), UNCERTAIN 안전성 확장을 추가한다.
    """
    idea_text = idea.to_text()
    warnings: list[str] = []

    async def check_papers():
        def valid_category(value):
            return isinstance(value, str) and value.strip().lower() in ("novel", "not novel")

        def review_failure(default):
            if not isinstance(default, dict) or not default:
                return "missing_review_output"
            category = default.get("category")
            if category is None or category == "":
                return "missing_category"
            if not isinstance(category, str):
                return "nonstring_category"
            if not valid_category(category):
                return "unknown_category"
            return None

        load_config(config_path)
        output = None
        empty_search = False
        review_attempts = []
        for iteration in range(1, MAX_ITERATIONS + 1):
            output = await _run_once(idea_text, idea.seed_paper_ids, idea.cutoff_date)
            trace = output.get("trace") or {}
            default = (output.get("output") or {}).get("default") or {}
            ranked = trace.get("most_relevant_papers")
            if not default and ranked is not None and len(ranked) == 0:
                empty_search = True
                break
            reason = review_failure(default)
            raw = default.get("output_novelty_text") if isinstance(default, dict) else None
            review_attempts.append({
                "attempt": iteration,
                "reason": reason or "valid",
                "category": str(default.get("category"))[:80] if isinstance(default, dict) and default.get("category") is not None else None,
                "candidate_count": len(ranked) if isinstance(ranked, (list, tuple)) else None,
                "raw_response_length": len(raw) if isinstance(raw, str) else None,
                "has_class_marker": "Class:" in raw if isinstance(raw, str) else None,
                "has_review_marker": "Review:" in raw if isinstance(raw, str) else None,
            })
            if reason is None:
                break
            warnings.append(f"{iteration}번째 시도에서 novelty checker 검토 실패({reason}); {'재시도합니다' if iteration < MAX_ITERATIONS else '재시도 한도에 도달했습니다'}.")
        default = (output or {}).get("output", {}).get("default") or {}
        evaluated_papers = default.get("evaluation_papers", [])
        trace = (output or {}).get("trace") or {}
        dropped = trace.get("dropped_by_cutoff", [])
        paper_search = summarize_trace(trace)
        paper_search["review_attempts"] = review_attempts
        if empty_search:
            paper_search["outcome"] = "completed_empty"
            verdict = Verdict("NO_MATCH_IN_SCOPE", "이번 검색 범위에서 비교할 논문을 찾지 못했습니다. 전체 문헌의 신규성 증명은 아닙니다.")
        else:
            paper_search["outcome"] = "reviewed" if valid_category(default.get("category")) else "invalid_review"
            verdict = resolve_verdict(default.get("category"), len(evaluated_papers))
        if evaluated_papers:
            equivalent_found, equivalence_results = await check_all_papers(
                provider or OpenAIProvider(), idea_text, evaluated_papers
            )
        else:
            equivalent_found, equivalence_results = False, []
        equivalent_title = next((r["paper_title"] for r in equivalence_results if r["equivalent"]), "")
        verdict = apply_equivalence_override(verdict, equivalent_found, equivalent_title)
        return verdict, default.get("review", ""), evaluated_papers, dropped, iteration, equivalence_results, paper_search

    paper_task, web_task, patent_task = await asyncio.gather(
        check_papers(),
        check_source(idea, "web", search_web, provider),
        check_source(idea, "patent", search_patents, provider),
        return_exceptions=True,
    )
    if isinstance(paper_task, BaseException):
        verdict = Verdict("UNCERTAIN", f"논문 검사 실패: {paper_task}")
        review, evaluated_papers, dropped, iteration, equivalence_results, paper_search = "", [], [], 0, [], {}
        papers = {"status": "확인불가", "checked_count": 0, "matches": [], "candidates": [], "error": str(paper_task)}
    else:
        verdict, review, evaluated_papers, dropped, iteration, equivalence_results, paper_search = paper_task
        papers = paper_overlap(verdict, equivalence_results, len(evaluated_papers))

    def external_result(value):
        if isinstance(value, BaseException):
            return {"status": "확인불가", "checked_count": 0, "matches": [], "candidates": [], "error": str(value)}
        return value

    overlaps = {
        "web": external_result(web_task),
        "paper": papers,
        "patent": external_result(patent_task),
    }

    return NoveltyCheckResult(
        idea_title=idea.title,
        verdict=verdict,
        review=review,
        evaluated_paper_count=len(evaluated_papers),
        dropped_by_cutoff_count=len(dropped),
        iterations=iteration,
        equivalence_results=equivalence_results,
        warnings=warnings,
        checked_at=datetime.now(timezone.utc).isoformat(),
        overlaps=overlaps,
        paper_search=paper_search,
    )
