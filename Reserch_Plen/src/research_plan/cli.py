"""명령행 진입점.

    python -m research_plan list   --run-dir <실행 폴더>
    python -m research_plan select --run-dir <실행 폴더> --idea 6 [--allow-not-novel] [--out out]
    python -m research_plan extract --evidence out/<run_id>/idea06/evidence.json [--model ...]
    python -m research_plan review  --plan out/<run_id>/idea06/plan.json [--judge-model ...] [--no-refine]
    python -m research_plan check   --plan out/<run_id>/idea06/plan.reviewed.json
    python -m research_plan write   --plan out/<run_id>/idea06/plan.reviewed.json [--model ...]
    python -m research_plan verify  --plan out/<run_id>/idea06/plan.reviewed.json [--offline]
    python -m research_plan run     --run-dir <실행 폴더> --idea 6 [--from write] [--skip-review] [--offline]
    python -m research_plan evaluate --run-dir <실행 폴더> [--ideas 2,6] [--samples 2] [--judges a,b]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .evidence import build_evidence
from .extract import extract_plan, rule_errors
from .inputs import InputError, Run, load_run
from .provider import DEFAULT_MODEL, OpenRouterProvider, ProviderError
from .review import DEFAULT_JUDGE_MODEL, ReviewError, review_plan
from .verify import DOCS, ArxivLookup, verify
from .write import plan_content_errors, write_documents

SEARCH_SOURCES = ("paper", "web", "patent")


def _status(candidate, source: str) -> str:
    return str(candidate.cot5.get("overlaps", {}).get(source, {}).get("status", "-"))


def print_candidates(run: Run) -> None:
    print(f"run {run.run_id} · 후보 {len(run.candidates)}개")
    header = ["#", "CoT3", "CoT5", "judge", *SEARCH_SOURCES, "제목"]
    print(" | ".join(header))
    for c in run.candidates:
        grounding = (c.cot3 or {}).get("judge_verdict", {}).get("grounding", "-")
        title = c.title if len(c.title) <= 80 else c.title[:77] + "..."
        row = [str(c.index), c.cot3_id or "-", c.classification, grounding,
               *(_status(c, s) for s in SEARCH_SOURCES), title]
        print(" | ".join(row))
    for warning in run.warnings:
        print(f"[경고] {warning}")
    print("선택: python -m research_plan select --run-dir <실행 폴더> --idea <번호>")


def write_evidence(run: Run, index: int, out_dir: Path, *, allow_not_novel: bool) -> Path:
    evidence = build_evidence(run, index, allow_not_novel=allow_not_novel)
    target = out_dir / run.run_id / f"idea{index:02d}" / "evidence.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def run_extract(evidence_path: Path, *, model: str | None, max_rounds: int, provider=None) -> int:
    """evidence.json 옆에 plan.json(통과) 또는 plan.draft.json(실패)과 extract_log.json을 쓴다."""
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    try:
        provider = provider or OpenRouterProvider(model=model)
        plan, log, ok = extract_plan(evidence, provider, max_rounds=max_rounds)
    except ProviderError as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        return 2
    log["calls"] = getattr(provider, "calls", [])
    out_dir = evidence_path.parent
    target = out_dir / ("plan.json" if ok else "plan.draft.json")
    target.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "extract_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[{'OK' if ok else 'FAIL'}] {target} ({len(log['rounds'])}회, 모델 {log['model']})")
    for error in log["rounds"][-1]["errors"]:
        print(f"  - {error}")
    return 0 if ok else 1


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_review(plan_path: Path, *, model: str | None, judge_model: str | None, refine: bool,
               writer=None, judge_provider=None) -> int:
    """plan.json 옆에 plan.reviewed.json과 review.json을 쓴다. 원래 plan.json은 바꾸지 않는다."""
    out_dir = plan_path.parent
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    evidence = json.loads((out_dir / "evidence.json").read_text(encoding="utf-8"))
    try:
        judge_provider = judge_provider or OpenRouterProvider(model=judge_model or DEFAULT_JUDGE_MODEL)
        if refine:
            writer = writer or OpenRouterProvider(model=model)
        final, report, status = review_plan(evidence, plan, writer, judge_provider, refine=refine)
    except (ProviderError, ReviewError) as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        return 2
    report["calls"] = {
        "judge": getattr(judge_provider, "calls", []),
        "writer": getattr(writer, "calls", []) if writer else [],
    }
    _write_json(out_dir / "plan.reviewed.json", final)
    _write_json(out_dir / "review.json", report)
    print(f"[{'OK' if status == 'pass' else 'REVIEW'}] {out_dir / 'plan.reviewed.json'} "
          f"(상태 {status}, 판정 모델 {report['judge_model']})")
    if "refine" in report:
        refine = report["refine"]
        print(f"  고친 필드: {refine['target_fields']} / 고정한 필드: {refine['locked_fields'] or '없음'} "
              f"(규칙 검사 {'통과' if refine['rules_passed'] else '실패'}"
              f"{', 고정 없이 재시도함' if refine.get('unlocked_retry') else ''})")
    for r in report["rounds"]:
        s = r["summary"]
        print(f"  심사 {r['round']}회차: 평균 {s['mean_score']}, 최저 {s['min_score']}, "
              f"major {s['major_issues']}, minor {s['minor_issues']}, 기준 미달 {s['low_fields'] or '없음'}")
        if r["round"] > 1:
            print(f"    바뀐 필드 {s['changed_fields'] or '없음'}"
                  + (f" / 바뀐 필드 때문에 영향받음 {s['affected_by_change']}" if s["affected_by_change"] else "")
                  + (f" / 보완 후 점수 하락 {s['regressed_fields']}" if s["regressed_fields"] else ""))
            if s["drift_fields"]:
                print(f"    판정 편차(내용이 그대로라 1회차 판정 유지): {s['drift_fields']}")
    last = report["rounds"][-1]
    for issue in last.get("effective_judgement", last["judgement"])["issues"]:
        if issue["severity"] == "major":
            print(f"  - [major] {issue['field']} {issue['item_id']}: {issue['problem']}")
    for issue in last["summary"].get("new_findings", []):
        print(f"  - [새 지적, 사람 확인] {issue['field']} {issue['item_id']}: {issue['problem']}")
    # needs_review도 정상 종료다. 종료 코드 1은 "사람이 확인할 것이 남음"을 뜻한다.
    return 0 if status == "pass" else 1


def _load_plan_and_evidence(plan_path: Path) -> tuple[dict, dict]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    evidence = json.loads((plan_path.parent / "evidence.json").read_text(encoding="utf-8"))
    return plan, evidence


def run_check(plan_path: Path) -> int:
    """LLM 없이 규칙 검사만 한다. 사람이 plan을 고친 뒤 4단계 전에 확인하는 용도."""
    try:
        plan, evidence = _load_plan_and_evidence(plan_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        return 2
    errors = rule_errors(plan, evidence) + plan_content_errors(plan)
    print(f"[{'OK' if not errors else 'FAIL'}] {plan_path} (규칙 검사 {len(errors)}건)")
    for error in errors:
        print(f"  - {error}")
    return 0 if not errors else 1


def run_write(plan_path: Path, *, model: str | None, max_rounds: int, provider=None) -> int:
    """plan 옆에 research_plan.md, paper_skeleton.md, write_log.json을 쓴다."""
    plan, evidence = _load_plan_and_evidence(plan_path)
    errors = rule_errors(plan, evidence)
    if errors:
        print(f"[오류] plan이 규칙 검사를 통과하지 못함. 먼저 check로 확인할 것: {errors[:3]}", file=sys.stderr)
        return 2
    try:
        provider = provider or OpenRouterProvider(model=model)
        docs, log, ok = write_documents(plan, provider, max_rounds=max_rounds)
    except ProviderError as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        return 2
    log["plan_file"] = plan_path.name
    log["calls"] = getattr(provider, "calls", [])
    for name, text in docs.items():
        (plan_path.parent / name).write_text(text, encoding="utf-8")
    _write_json(plan_path.parent / "write_log.json", log)
    print(f"[{'OK' if ok else 'FAIL'}] {plan_path.parent} → {', '.join(docs) or '문서 없음'} (모델 {log['model']})")
    for error in log["plan_content_errors"]:
        print(f"  - [plan 내용, 사람이 고칠 것] {error}")
    for part, info in log["parts"].items():
        print(f"  {part}: {len(info['rounds'])}회, {'통과' if info['passed'] else '실패'}")
        for error in info["rounds"][-1]["errors"]:
            print(f"    - {error}")
    return 0 if ok else 1


def run_verify(plan_path: Path, *, offline: bool, lookup=None) -> int:
    """plan 옆의 research_plan.md, paper_skeleton.md를 검사하고 verify_report.json을 쓴다. LLM을 쓰지 않는다."""
    folder = plan_path.parent
    missing = [n for n in DOCS if not (folder / n).is_file()]
    if missing:
        print(f"[오류] 문서가 없음: {missing}. 먼저 write를 실행할 것", file=sys.stderr)
        return 2
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    docs = {n: (folder / n).read_text(encoding="utf-8") for n in DOCS}
    report = verify(plan, docs, lookup or ArxivLookup(offline=offline))
    report["plan_file"] = plan_path.name
    _write_json(folder / "verify_report.json", report)
    checked = sum(1 for c in report["citations"] if c["status"] == "확인")
    print(f"[{'OK' if report['status'] == 'pass' else 'FAIL'}] {folder} "
          f"(인용 {checked}/{len(report['citations'])}건 arXiv 확인, 오류 {len(report['errors'])}, 경고 {len(report['warnings'])})")
    for error in report["errors"]:
        print(f"  - [오류] {error}")
    for warning in report["warnings"]:
        print(f"  - [경고, 사람 확인] {warning}")
    return 0 if report["status"] == "pass" else 1


def run_evaluate(args, *, writer=None, judges=None, lookup=None, pipeline_providers=None) -> int:
    from .evaluate import EvalError, evaluate

    try:
        run = load_run(args.run_dir)
        ideas = ([int(x) for x in args.ideas.split(",")] if args.ideas
                 else [c.index for c in run.candidates if c.classification == "NOVEL"])
        writer = writer or OpenRouterProvider(model=args.model)
        judges = judges or [OpenRouterProvider(model=m.strip()) for m in args.judges.split(",") if m.strip()]
        report = evaluate(
            args.run_dir, ideas, writer=writer, judges=judges, lookup=lookup or ArxivLookup(offline=args.offline),
            out_root=args.out, conditions=tuple(c.strip() for c in args.conditions.split(",")),
            samples=args.samples, include_golden=not args.no_golden, pipeline_providers=pipeline_providers,
        )
    except (InputError, ProviderError, EvalError) as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        return 2
    folder = Path(report["folder"])
    print(f"\n[OK] 평가 결과: {folder}")
    print((folder / "summary.md").read_text(encoding="utf-8"))
    errors = [r for r in report["results"] if r["status"] == "error"]
    for r in errors:
        print(f"  - [실패] 아이디어 {r['idea']} · {r['condition']}")
    return 0 if not errors else 1


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python -m research_plan")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("list", "select"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--run-dir", type=Path, required=True, help="examples_run_manifest.json이 있는 폴더")
        cmd.add_argument("--future-work", type=Path, help="manifest.input_file 대신 쓸 FutureWork 결과 파일")
    select = sub.choices["select"]
    select.add_argument("--idea", type=int, required=True, help="후보 번호 (1부터)")
    select.add_argument("--allow-not-novel", action="store_true", help="NOT_NOVEL 후보도 진행")
    select.add_argument("--out", type=Path, default=Path("out"), help="출력 루트 폴더")
    extract = sub.add_parser("extract")
    extract.add_argument("--evidence", type=Path, required=True, help="select가 만든 evidence.json")
    extract.add_argument("--model", help=f"OpenRouter 모델 ID (기본: RESEARCH_PLAN_MODEL 또는 {DEFAULT_MODEL})")
    extract.add_argument("--max-rounds", type=int, default=3, help="검사 실패 시 다시 쓰는 최대 횟수")
    review = sub.add_parser("review")
    review.add_argument("--plan", type=Path, required=True, help="extract가 만든 plan.json (같은 폴더에 evidence.json 필요)")
    review.add_argument("--judge-model", help=f"판정 모델 ID (기본: {DEFAULT_JUDGE_MODEL})")
    review.add_argument("--model", help="보완할 때 쓰는 작성 모델 ID (기본: extract와 같음)")
    review.add_argument("--no-refine", action="store_true", help="심사만 하고 보완하지 않음")
    check = sub.add_parser("check")
    check.add_argument("--plan", type=Path, required=True, help="검사할 plan 파일 (사람이 고친 뒤 확인용)")
    write = sub.add_parser("write")
    write.add_argument("--plan", type=Path, required=True, help="plan.reviewed.json (같은 폴더에 evidence.json 필요)")
    write.add_argument("--model", help=f"작성 모델 ID (기본: RESEARCH_PLAN_MODEL 또는 {DEFAULT_MODEL})")
    write.add_argument("--max-rounds", type=int, default=3, help="검사 실패 시 다시 쓰는 최대 횟수")
    verify_cmd = sub.add_parser("verify")
    verify_cmd.add_argument("--plan", type=Path, required=True, help="문서를 만든 plan 파일 (같은 폴더의 md 두 개를 검사)")
    verify_cmd.add_argument("--offline", action="store_true", help="arXiv에 접속하지 않고 캐시만 사용")
    run_cmd = sub.add_parser("run", help="select → extract → review → write → verify를 한 번에 실행")
    run_cmd.add_argument("--run-dir", type=Path, required=True, help="examples_run_manifest.json이 있는 폴더")
    run_cmd.add_argument("--idea", type=int, required=True, help="후보 번호 (1부터)")
    run_cmd.add_argument("--out", type=Path, default=Path("out"), help="출력 루트 폴더")
    run_cmd.add_argument("--from", dest="start", choices=["select", "extract", "review", "write", "verify"],
                         default="select", help="이 단계부터 다시 실행 (사람이 plan을 고쳤다면 write)")
    run_cmd.add_argument("--allow-not-novel", action="store_true", help="NOT_NOVEL 후보도 진행")
    run_cmd.add_argument("--model", help=f"작성 모델 ID (기본: RESEARCH_PLAN_MODEL 또는 {DEFAULT_MODEL})")
    run_cmd.add_argument("--judge-model", help=f"판정 모델 ID (기본: {DEFAULT_JUDGE_MODEL})")
    run_cmd.add_argument("--skip-review", action="store_true", help="3단계 심사를 건너뜀")
    run_cmd.add_argument("--no-refine", action="store_true", help="3단계에서 심사만 하고 보완하지 않음")
    run_cmd.add_argument("--offline", action="store_true", help="5단계에서 arXiv에 접속하지 않음")
    run_cmd.add_argument("--max-rounds", type=int, default=3, help="검사 실패 시 다시 쓰는 최대 횟수")
    eval_cmd = sub.add_parser("evaluate", help="free·template·pipeline 조건을 같은 근거로 비교 평가")
    eval_cmd.add_argument("--run-dir", type=Path, required=True, help="examples_run_manifest.json이 있는 폴더")
    eval_cmd.add_argument("--ideas", help="쉼표로 구분한 후보 번호 (기본: NOVEL 후보 전부)")
    eval_cmd.add_argument("--conditions", default="free,template,pipeline", help="비교할 조건")
    eval_cmd.add_argument("--judges", default="openai/gpt-6-luna-pro,anthropic/claude-haiku-5.5",
                          help="평가 판정 모델 ID들 (서로 다른 회사 모델 권장)")
    eval_cmd.add_argument("--samples", type=int, default=2, help="판정 모델마다 같은 문서를 평가하는 횟수")
    eval_cmd.add_argument("--model", help=f"문서 작성 모델 ID (기본: RESEARCH_PLAN_MODEL 또는 {DEFAULT_MODEL})")
    eval_cmd.add_argument("--out", type=Path, default=Path("eval"), help="평가 결과 루트 폴더")
    eval_cmd.add_argument("--no-golden", action="store_true", help="6번 정답 예시를 평가에 넣지 않음")
    eval_cmd.add_argument("--offline", action="store_true", help="arXiv에 접속하지 않음")
    args = parser.parse_args(argv)

    if args.command == "evaluate":
        return run_evaluate(args)
    if args.command == "run":
        from .pipeline import run_pipeline

        return run_pipeline(
            args.run_dir, args.idea, out=args.out, start=args.start, allow_not_novel=args.allow_not_novel,
            model=args.model, judge_model=args.judge_model, skip_review=args.skip_review,
            refine=not args.no_refine, offline=args.offline, max_rounds=args.max_rounds,
            argv=sys.argv[1:] if argv is None else list(argv),
        )
    if args.command == "verify":
        return run_verify(args.plan, offline=args.offline)
    if args.command == "check":
        return run_check(args.plan)
    if args.command == "write":
        return run_write(args.plan, model=args.model, max_rounds=args.max_rounds)
    if args.command == "review":
        return run_review(args.plan, model=args.model, judge_model=args.judge_model, refine=not args.no_refine)
    if args.command == "extract":
        return run_extract(args.evidence, model=args.model, max_rounds=args.max_rounds)
    try:
        run = load_run(args.run_dir, future_work=args.future_work)
        if args.command == "list":
            print_candidates(run)
            return 0
        path = write_evidence(run, args.idea, args.out, allow_not_novel=args.allow_not_novel)
    except InputError as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        return 2
    evidence = json.loads(path.read_text(encoding="utf-8"))
    print(f"[OK] {path}")
    print(f"  후보 {args.idea} ({evidence['meta']['cot3_candidate_id']}): {evidence['meta']['title']}")
    for warning in evidence["warnings"]:
        print(f"  [경고] {warning}")
    return 0
