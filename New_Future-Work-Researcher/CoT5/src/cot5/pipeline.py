from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import ensure_submodule_importable, load_config, submodule_cwd
from .equivalence import check_all_papers
from .idea import ResearchIdea
from .provider import LLMProvider, OpenAIProvider
from .verdict import Verdict, apply_equivalence_override, resolve_verdict

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

    def as_dict(self) -> dict[str, Any]:
        return {
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
        }


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
    load_config(config_path)
    idea_text = idea.to_text()
    warnings: list[str] = []

    output = None
    for iteration in range(1, MAX_ITERATIONS + 1):
        output = await _run_once(idea_text, idea.seed_paper_ids, idea.cutoff_date)
        default = output["output"].get("default", {})
        if default.get("category") is not None:
            break
        warnings.append(f"{iteration}번째 시도에서 novelty checker 출력을 파싱하지 못해 재시도했습니다.")

    default = (output or {}).get("output", {}).get("default", {})
    category = default.get("category")
    review = default.get("review", "")
    evaluated_papers = default.get("evaluation_papers", [])
    dropped = output["trace"].get("dropped_by_cutoff", []) if output else []

    verdict = resolve_verdict(category, len(evaluated_papers))

    # README 8절(Si et al.): Top-10 각각과 개별 비교해 하나라도 동등하면 그 자체로 NOT_NOVEL.
    # 종합 판단(위 verdict)이 "전체적으로는 새로워 보인다"고 해도 이 개별 근거가 우선한다.
    equivalence_provider = provider or OpenAIProvider()
    equivalent_found, equivalence_results = await check_all_papers(
        equivalence_provider, idea_text, evaluated_papers
    )
    equivalent_title = next(
        (r["paper_title"] for r in equivalence_results if r["equivalent"]), ""
    )
    verdict = apply_equivalence_override(verdict, equivalent_found, equivalent_title)

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
    )
