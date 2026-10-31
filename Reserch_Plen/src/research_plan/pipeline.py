"""Stage 6: 1~5단계를 한 명령으로 잇고 실행 기록(run_manifest.json)을 남긴다.

    select → extract → review → write → verify

- `--from`으로 중간 단계부터 다시 시작한다. 사람이 plan.reviewed.json을 고쳤다면 `--from write`.
- 다시 쓰기 전에 그 단계와 뒤 단계의 기존 결과를 history/<시각>/으로 옮겨 둔다. 덮어써서 잃는 일이 없게 한다.
- 단계별 상태, 소요 시간, LLM 비용, 출력 파일 해시와 입력·프롬프트 해시를 run_manifest.json에 적는다.
  같은 결과를 다시 만들려면 무엇이 필요한지(입력, 프롬프트, 모델)를 이 파일만 보고 알 수 있게 한다.

단계 실패 처리
- extract가 검사를 통과하지 못하면(plan.draft.json) 멈춘다. 뒤 단계에 쓸 plan이 없다.
- review가 needs_review면 계속 진행한다. 문서를 만들어 사람이 함께 보게 하고, 최종 상태에 needs_review를 남긴다.
- write가 실패하면 verify는 돌리지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from .extract import FIELD_DEFINITIONS, PROMPTS

PIPELINE_VERSION = "0.6"
STAGES = ["select", "extract", "review", "write", "verify"]
# 단계별로 만들거나 덮어쓰는 파일
OUTPUTS = {
    "select": ["evidence.json"],
    "extract": ["plan.json", "plan.draft.json", "extract_log.json"],
    "review": ["plan.reviewed.json", "review.json"],
    "write": ["research_plan.md", "paper_skeleton.md", "write_log.json"],
    "verify": ["verify_report.json"],
}
MANIFEST = "run_manifest.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prompt_hashes() -> dict[str, str]:
    files = sorted(PROMPTS.glob("*.md")) + [FIELD_DEFINITIONS]
    return {f.relative_to(PROMPTS.parent).as_posix(): sha256_file(f) for f in files}


def backup_outputs(folder: Path, start: str) -> Path | None:
    """start 단계와 그 뒤 단계의 기존 결과(와 이전 manifest)를 history/<시각>/으로 복사한다."""
    names = [n for s in STAGES[STAGES.index(start):] for n in OUTPUTS[s]] + [MANIFEST]
    existing = [folder / n for n in names if (folder / n).is_file()]
    if not existing:
        return None
    target = folder / "history" / datetime.now().strftime("%Y%m%d-%H%M%S")
    target.mkdir(parents=True, exist_ok=True)
    for path in existing:
        shutil.copy2(path, target / path.name)
    return target


def _remove_outputs(folder: Path, stage: str) -> None:
    """이번 실행에서 다시 만들 파일을 지운다. 지난 실행의 결과가 이번 결과로 오해되지 않게 한다."""
    for name in OUTPUTS[stage]:
        (folder / name).unlink(missing_ok=True)


def _calls(stage: str, folder: Path) -> list[dict]:
    try:
        if stage == "extract":
            return json.loads((folder / "extract_log.json").read_text(encoding="utf-8")).get("calls", [])
        if stage == "review":
            calls = json.loads((folder / "review.json").read_text(encoding="utf-8")).get("calls", {})
            return calls.get("judge", []) + calls.get("writer", [])
        if stage == "write":
            return json.loads((folder / "write_log.json").read_text(encoding="utf-8")).get("calls", [])
    except (OSError, json.JSONDecodeError):
        pass
    return []


def _summary(stage: str, folder: Path) -> dict:
    """단계 결과 파일에서 사람이 볼 요약만 뽑는다."""
    try:
        if stage == "select":
            meta = json.loads((folder / "evidence.json").read_text(encoding="utf-8"))["meta"]
            return {"title": meta["title"], "cot5_classification": meta["cot5_classification"],
                    "cot3_candidate_id": meta.get("cot3_candidate_id")}
        if stage == "extract":
            log = json.loads((folder / "extract_log.json").read_text(encoding="utf-8"))
            return {"rounds": len(log["rounds"]), "model": log["model"]}
        if stage == "review":
            report = json.loads((folder / "review.json").read_text(encoding="utf-8"))
            last = report["rounds"][-1]["summary"]
            return {"rounds": len(report["rounds"]), "mean_score": last["mean_score"],
                    "major_issues": last["major_issues"], "judge_model": report["judge_model"]}
        if stage == "write":
            log = json.loads((folder / "write_log.json").read_text(encoding="utf-8"))
            return {part: len(info["rounds"]) for part, info in log["parts"].items()}
        if stage == "verify":
            report = json.loads((folder / "verify_report.json").read_text(encoding="utf-8"))
            return {"errors": len(report["errors"]), "warnings": len(report["warnings"]),
                    "citations": len(report["citations"])}
    except (OSError, json.JSONDecodeError, KeyError, IndexError):
        pass
    return {}


def _plan_for_write(folder: Path, ran: set[str]) -> Path:
    """write·verify가 쓸 plan. 이번에 extract만 돌고 review를 건너뛰었다면 예전 plan.reviewed.json을 쓰면 안 된다."""
    reviewed = folder / "plan.reviewed.json"
    if "review" in ran:
        return reviewed
    if "extract" in ran:
        return folder / "plan.json"
    return reviewed if reviewed.is_file() else folder / "plan.json"


def _human_edited(folder: Path) -> bool:
    try:
        plan = json.loads((folder / "plan.reviewed.json").read_text(encoding="utf-8"))
        return bool(plan["meta"].get("human_edits"))
    except (OSError, json.JSONDecodeError, KeyError):
        return False


def run_pipeline(
    run_dir: Path,
    idea: int,
    *,
    out: Path = Path("out"),
    start: str = "select",
    allow_not_novel: bool = False,
    model: str | None = None,
    judge_model: str | None = None,
    skip_review: bool = False,
    refine: bool = True,
    offline: bool = False,
    max_rounds: int = 3,
    providers: dict | None = None,
    argv: list[str] | None = None,
) -> int:
    """종료 코드: 0 = 모두 통과, 1 = 사람 확인 필요(needs_review 또는 검사 실패), 2 = 실행 오류."""
    from . import cli  # cli가 이 모듈을 쓰므로 순환을 피하려고 함수 안에서 가져온다
    from .inputs import InputError, load_run

    providers = providers or {}
    try:
        run = load_run(run_dir)
    except InputError as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        return 2
    folder = Path(out) / run.run_id / f"idea{idea:02d}"
    if start != "select" and not (folder / "evidence.json").is_file():
        print(f"[오류] {folder}에 evidence.json이 없음. --from select로 시작할 것", file=sys.stderr)
        return 2
    folder.mkdir(parents=True, exist_ok=True)
    stages = STAGES[STAGES.index(start):]
    if skip_review and "review" in stages:
        stages.remove("review")
    if "review" in stages and _human_edited(folder):
        print("[주의] 사람이 고친 plan.reviewed.json을 review가 새로 만듭니다. 고친 파일은 history에 백업합니다. "
              "고친 내용을 유지하려면 --from write로 실행하세요.")
    backup = backup_outputs(folder, start)

    manifest = {
        "pipeline_version": PIPELINE_VERSION,
        "command": argv,
        "run_id": run.run_id,
        "candidate_index": idea,
        "folder": folder.as_posix(),
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "from_stage": start,
        "backup": backup.as_posix() if backup else None,
        "models": {"writer": model or "기본값(RESEARCH_PLAN_MODEL)", "judge": judge_model or "기본값"},
        "prompts_sha256": prompt_hashes(),
        "inputs": run.input_files,
        "stages": [],
    }
    status = "pass"
    ran: set[str] = set()
    for stage in stages:
        print(f"\n=== {stage} ===")
        if stage != "select":
            _remove_outputs(folder, stage)
        started = time.monotonic()
        if stage == "select":
            try:
                cli.write_evidence(run, idea, Path(out), allow_not_novel=allow_not_novel)
                code = 0
                print(f"[OK] {folder / 'evidence.json'}")
            except InputError as exc:
                print(f"[오류] {exc}", file=sys.stderr)
                code = 2
        elif stage == "extract":
            code = cli.run_extract(folder / "evidence.json", model=model, max_rounds=max_rounds,
                                   provider=providers.get("writer"))
        elif stage == "review":
            plan_path = folder / "plan.json"
            if not plan_path.is_file():
                print(f"[오류] {plan_path}가 없음", file=sys.stderr)
                code = 2
            else:
                code = cli.run_review(plan_path, model=model, judge_model=judge_model, refine=refine,
                                      writer=providers.get("writer"), judge_provider=providers.get("judge"))
        elif stage == "write":
            code = cli.run_write(_plan_for_write(folder, ran), model=model, max_rounds=max_rounds,
                                 provider=providers.get("writer"))
        else:  # verify
            code = cli.run_verify(_plan_for_write(folder, ran), offline=offline,
                                  lookup=providers.get("lookup"))
        if code in (0, 1):
            ran.add(stage)

        calls = _calls(stage, folder)
        outputs = {n: sha256_file(folder / n) for n in OUTPUTS[stage] if (folder / n).is_file()}
        stage_status = {0: "pass", 1: "needs_review" if stage == "review" else "fail", 2: "error"}[code]
        manifest["stages"].append({
            "stage": stage,
            "status": stage_status,
            "seconds": round(time.monotonic() - started, 1),
            "llm_calls": len(calls),
            "cost_usd": round(sum(c.get("usage", {}).get("cost", 0) or 0 for c in calls), 6),
            "summary": _summary(stage, folder),
            "outputs_sha256": outputs,
        })
        if stage_status == "error" or (stage_status == "fail" and stage in ("select", "extract", "write")):
            status = stage_status if stage_status == "error" else "fail"
            break
        if stage_status == "needs_review" and status == "pass":
            status = "needs_review"
        if stage_status == "fail":  # verify 실패
            status = "fail"

    manifest["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    manifest["final_status"] = status
    manifest["total_cost_usd"] = round(sum(s["cost_usd"] for s in manifest["stages"]), 6)
    cli._write_json(folder / MANIFEST, manifest)
    _print_summary(manifest)
    return {"pass": 0, "needs_review": 1, "fail": 1, "error": 2}[status]


def _print_summary(manifest: dict) -> None:
    print(f"\n=== 요약: {manifest['folder']} ===")
    for s in manifest["stages"]:
        print(f"  {s['stage']:<8} {s['status']:<13} {s['seconds']:>6}초  LLM {s['llm_calls']}회  ${s['cost_usd']}")
    print(f"  최종 상태 {manifest['final_status']} · 총비용 ${manifest['total_cost_usd']}"
          + (f" · 이전 결과 백업 {manifest['backup']}" if manifest["backup"] else ""))
