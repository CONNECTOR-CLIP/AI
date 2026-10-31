"""Stage 1 출력: 선택한 후보 1개의 근거 묶음(evidence.json)을 만든다.

새로 만든 내용은 없다. 입력 파일의 값을 모으고, 항목마다 근거 경로(source)를 붙인다.
근거 경로는 2단계에서 plan.json의 source에 그대로 옮겨 적는다(docs/field_definitions.md).
"""

from __future__ import annotations

import re

from .inputs import ARXIV_ID_PATTERN, Candidate, InputError, Run

EVIDENCE_VERSION = "0.1"


def _item(source: str, text: object, **extra) -> dict:
    return {"source": source, "text": str(text).strip(), **extra}


def _idea(candidate: Candidate) -> list[dict]:
    proposal = candidate.proposal
    items = [
        _item("future_work.background_and_gap", proposal["background_and_gap"]),
        _item("future_work.proposed_direction", proposal["proposed_direction"]),
    ]
    if proposal.get("expected_contribution"):
        # FutureWork 변환 시 CoT3 rationale이 들어간 칸이다. 실제 기여 서술이 아니라 근거 설명에 가깝다.
        items.append(_item("future_work.expected_contribution", proposal["expected_contribution"]))
    for i, title in enumerate(proposal.get("reference_papers", [])):
        items.append(_item(f"future_work.reference_papers[{i}]", title))
    cot3 = candidate.cot3
    if cot3:
        items.append(_item("cot3.source_type", cot3.get("source_type", "")))
        items.append(_item("cot3.rationale", cot3.get("rationale", "")))
    return [item for item in items if item["text"]]


def _upstream(run: Run, candidate: Candidate, warnings: list[str]) -> list[dict]:
    """CoT3 source_evidence(P1:G4, P2:L1 등)를 CoT1 subgoal과 CoT2 한계 인용문으로 풀어 쓴다."""
    papers = {paper.key: paper for paper in run.papers}
    items = []
    for ref in (candidate.cot3 or {}).get("source_evidence", []):
        match = re.fullmatch(r"(P\d+):([GL])(\d+)", ref)
        if not match:
            warnings.append(f"해석할 수 없는 CoT3 근거 ID {ref}")
            continue
        key, kind, number = match.group(1), match.group(2), int(match.group(3))
        paper = papers.get(key)
        cite = {"paper": key, "arxiv_id": paper.arxiv_id if paper else ""}
        if kind == "G":
            subgoals = run.cot1.get(key, {}).get("subgoals", [])
            found = next(
                ((i, g) for i, g in enumerate(subgoals) if g.get("subgoal_id") == f"G{number}"), None
            )
            if found is None:
                warnings.append(f"{ref}: CoT1 결과에서 찾지 못함")
                continue
            i, goal = found
            text = f"{goal.get('description', '')} (status: {goal.get('status', '')}; {goal.get('rationale', '')})"
            items.append(_item(f"cot1.{key}.subgoals[{i}]", text, id=ref, kind="subgoal", **cite))
        else:
            limitations = run.cot2.get(key, {}).get("candidates", [])
            if not 1 <= number <= len(limitations):
                warnings.append(f"{ref}: CoT2 결과에서 찾지 못함")
                continue
            lim = limitations[number - 1]
            items.append(_item(
                f"cot2.{key}.candidates[{number - 1}]", lim.get("quote", ""), id=ref, kind="limitation",
                location=lim.get("location", ""), limitation_type=lim.get("limitation_type", ""), **cite,
            ))
    return items


def _seed_papers(run: Run) -> list[dict]:
    """시드 논문이 실제로 무엇을 했는지(CoT1 목표 분해). 논문을 서술할 때의 기준이다.

    CoT3·CoT4는 논문의 기능을 짧은 이름("P1-style citation generation" 등)으로 부르는데, 이 이름은 축약이나
    과장일 수 있다. CoT1은 논문 원문을 읽고 연구 문제와 하위 목표(달성 여부 포함)를 정리한 것이므로 이쪽을 근거로 쓴다.
    """
    seeds = []
    for paper in run.papers:
        cot1 = run.cot1.get(paper.key)
        if not cot1:
            continue
        subgoals = [
            _item(
                f"cot1.{paper.key}.subgoals[{i}]",
                f"{g.get('label', '')}: {g.get('description', '')}",
                id=g.get("subgoal_id", ""),
                status=g.get("status", ""),
            )
            for i, g in enumerate(cot1.get("subgoals", []))
        ]
        seeds.append({
            "paper": paper.key,
            "arxiv_id": paper.arxiv_id,
            "title": paper.title,
            "research_problem": _item(f"cot1.{paper.key}.research_problem", cot1.get("research_problem", "")),
            "subgoals": subgoals,
        })
    return seeds


def _judge(candidate: Candidate) -> list[dict]:
    cot3 = candidate.cot3 or {}
    items = []
    verdict = cot3.get("judge_verdict")
    if verdict:
        text = ", ".join(f"{k}={v}" for k, v in verdict.items() if k != "validity_reason")
        items.append(_item("cot3.judge_verdict", text, reason=verdict.get("validity_reason", "")))
    for i, sub in enumerate(cot3.get("judge_subclaims", [])):
        items.append(_item(
            f"cot3.judge_subclaims[{i}]", sub.get("claim", ""),
            verdict=sub.get("verdict", ""), quote=sub.get("quote", ""),
        ))
    return items


def _resources(candidate: Candidate) -> list[dict]:
    items = []
    for group in ("requirements", "resource_guidance"):
        for key, value in candidate.cot4.get(group, {}).items():
            if isinstance(value, list):
                items += [_item(f"cot4.{group}.{key}[{i}]", v) for i, v in enumerate(value)]
            elif str(value).strip():
                items.append(_item(f"cot4.{group}.{key}", value))
    return items


def _novelty(candidate: Candidate, warnings: list[str]) -> dict:
    cot5 = candidate.cot5
    search = cot5.get("paper_search", {})
    related = []
    for source, overlap in cot5.get("overlaps", {}).items():
        for bucket in ("matches", "candidates"):
            for i, cand in enumerate(overlap.get(bucket, [])):
                entry = {
                    "source": f"cot5.{source}.{bucket}[{i}]",
                    "kind": source,
                    "title": cand.get("paper_title") or cand.get("title", ""),
                    "id": cand.get("paper_id") or cand.get("publication_number") or cand.get("url", ""),
                }
                if source == "paper":
                    entry.update({
                        "equivalent": cand.get("equivalent"),
                        "confidence": cand.get("confidence"),
                        "critical_difference": cand.get("critical_difference", ""),
                        "mechanism_overlap": cand.get("mechanism_overlap", ""),
                        "evaluation_overlap": cand.get("evaluation_overlap", ""),
                    })
                else:
                    entry.update({"overlap": cand.get("overlap"), "reason": cand.get("reason", "")})
                related.append(entry)
    if candidate.classification == "NOT_NOVEL" and not any(r.get("equivalent") is True for r in related):
        warnings.append("CoT5가 NOT_NOVEL로 판정했지만 결과에 동등(equivalent) 논문이 남아 있지 않음")
    return {
        "classification": cot5.get("classification", ""),
        "reason": _item("cot5.reason", cot5.get("reason", "")),
        "review": _item("cot5.review", cot5.get("review", "")),
        "search_status": {
            source: {
                "source": f"cot5.{source}.status",
                "status": overlap.get("status"),
                "checked_count": overlap.get("checked_count"),
                "error": overlap.get("error"),
            }
            for source, overlap in cot5.get("overlaps", {}).items()
        },
        "coverage": search.get("coverage"),
        "retrieval_warnings": search.get("retrieval_warnings", []),
        "related": related,
    }


def _whitelist(run: Run, novelty: dict) -> list[dict]:
    """시드 논문과 CoT5 논문 후보만 인용을 허용한다. plan.json citation_whitelist와 같은 형식."""
    entries, seen = [], set()
    for paper in run.papers:
        if paper.arxiv_id and paper.arxiv_id not in seen:
            seen.add(paper.arxiv_id)
            entries.append({"arxiv_id": paper.arxiv_id, "title": paper.title, "role": "seed"})
    for rel in novelty["related"]:
        arxiv_id = str(rel["id"])
        if rel["kind"] == "paper" and ARXIV_ID_PATTERN.fullmatch(arxiv_id) and arxiv_id not in seen:
            seen.add(arxiv_id)
            entries.append({"arxiv_id": arxiv_id, "title": rel["title"], "role": "cot5_candidate"})
    return entries


def build_evidence(run: Run, index: int, *, allow_not_novel: bool = False) -> dict:
    candidate = run.candidate(index)
    if candidate.classification != "NOVEL" and not allow_not_novel:
        raise InputError(
            f"후보 {index}는 CoT5 판정이 {candidate.classification}임. 진행하려면 --allow-not-novel"
        )
    warnings = run.warnings + candidate.warnings
    idea = _idea(candidate)
    upstream = _upstream(run, candidate, warnings)
    judge = _judge(candidate)
    resources = _resources(candidate)
    novelty = _novelty(candidate, warnings)
    return {
        "evidence_version": EVIDENCE_VERSION,
        "meta": {
            "run_id": run.run_id,
            "candidate_index": candidate.index,
            "future_work_id": candidate.proposal.get("id"),
            "cot3_candidate_id": candidate.cot3_id or None,
            "title": candidate.title,
            "cot5_classification": candidate.classification,
            "models": run.manifest.get("models", {}),
            "input_files": run.input_files,
        },
        "papers": [
            {"key": p.key, "arxiv_id": p.arxiv_id, "title": p.title, "source": p.source} for p in run.papers
        ],
        "seed_papers": _seed_papers(run),
        "idea": idea,
        "upstream_evidence": upstream,
        "judge": judge,
        "resources": resources,
        "novelty": novelty,
        "citation_whitelist": _whitelist(run, novelty),
        "warnings": warnings,
    }
