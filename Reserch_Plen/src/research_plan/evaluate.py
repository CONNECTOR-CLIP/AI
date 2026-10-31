"""Stage 7: 평가. 구조화 파이프라인이 단순 프롬프트보다 나은지 같은 근거로 비교한다.

조건 (아이디어마다 세 가지를 만든다)
- free: evidence + "연구계획서와 논문의 틀을 써라" 한 번 호출
- template: free + 고정 목차, 18개 필수 요소와 좋은 값의 기준, 작성 규칙을 프롬프트에 넣고 한 번 호출
  (필수 정보와 구조를 프롬프트로 지정하는 효과만 본다)
- pipeline: 1~5단계 전체 (필드 묶음 분해, 규칙 검사, 판정·보완, 코드 렌더링, 인용 검사)
- golden: 6번 아이디어의 사람이 쓴 정답 예시. 평가만 한다(판정기 보정용 기준).

측정
1. 자동 지표 (LLM 없음): 지어낸 숫자·이름, 화이트리스트 밖 인용, arXiv에 없는 인용, 결과 단정 표현, 내부 표기(P1),
   필수 제목 누락, 길이, 비용, 시간. 숫자·이름은 세 조건 모두 같은 기준(evidence)과 대조한다.
2. LLM 판정 (눈가림): 어떤 조건인지 알리지 않고 17개 요소의 포함 여부와 1~5점, 내용 문제를 받는다.
   한 판정 모델만 쓰면 그 모델의 취향이 결과가 된다. 특히 3단계 판정기와 같은 계열 모델은 파이프라인에 유리할 수 있다.
   그래서 서로 다른 회사의 판정 모델 여러 개로 평가하고, 같은 문서를 여러 번 평가해 편차도 기록한다.
3. 사람 평가지: 한 아이디어의 문서를 A/B/C로 섞어 눈가림한 평가지와 정답 키를 따로 만든다.
"""

from __future__ import annotations

import json
import random
import statistics
import time
from datetime import datetime
from pathlib import Path

from .evidence import build_evidence
from .extract import PAPER_LABEL, PROMPTS, compact_evidence, field_guidance
from .inputs import load_run
from .provider import LLMProvider
from .review import CHECKS, JUDGED_FIELDS
from .schemas import FIELD_KEYS
from .validate import ARXIV_ID, PLAN_HEADINGS, SKELETON_HEADINGS, validate_markdown
from .verify import ArxivLookup, check_names, check_numbers, check_phrases

ROOT = PROMPTS.parent
GOLDEN = ROOT / "examples" / "golden" / "idea06_unsupported_token"
GOLDEN_IDEA = 6
CONDITIONS = ("free", "template", "pipeline")
DEFAULT_EVAL_JUDGES = ("openai/gpt-6-luna-pro", "anthropic/claude-haiku-5.5")
DOCS = ("research_plan.md", "paper_skeleton.md")

_STR = {"type": "string"}


def _obj(props: dict) -> dict:
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


BASELINE_SCHEMA = _obj({"research_plan": _STR, "paper_skeleton": _STR})
EVAL_SCHEMA = _obj({
    "element_scores": {"type": "array", "items": _obj({
        "element": {"type": "string", "enum": JUDGED_FIELDS},
        "present": {"type": "boolean"},
        "score": {"type": "integer"},
        "reason": _STR,
    })},
    "issues": {"type": "array", "items": _obj({
        "check": {"type": "string", "enum": CHECKS},
        "severity": {"type": "string", "enum": ["major", "minor"]},
        "problem": _STR,
        "evidence": _STR,
    })},
})


class EvalError(RuntimeError):
    pass


# ---------- 문서 만들기 ----------

def baseline_instructions(condition: str) -> str:
    text = (PROMPTS / f"baseline_{condition}.md").read_text(encoding="utf-8")
    if condition == "template":
        text += "\n\n" + field_guidance(FIELD_KEYS)
    return text


def generate_baseline(evidence: dict, condition: str, provider: LLMProvider) -> dict[str, str]:
    raw = provider.evaluate(
        instructions=baseline_instructions(condition),
        document=json.dumps({"evidence": compact_evidence(evidence)}, ensure_ascii=False, indent=1),
        schema=BASELINE_SCHEMA,
        schema_name=f"baseline_{condition}",
    )
    return {"research_plan.md": raw["research_plan"], "paper_skeleton.md": raw["paper_skeleton"]}


# ---------- 자동 지표 ----------

def evidence_as_plan(evidence: dict) -> dict:
    """verify.py의 검사를 evidence 기준으로 쓰기 위한 모양. 세 조건을 같은 근거와 대조한다."""
    return {"fields": compact_evidence(evidence), "citation_whitelist": evidence["citation_whitelist"]}


def auto_metrics(evidence: dict, docs: dict[str, str], lookup: ArxivLookup) -> dict:
    basis = evidence_as_plan(evidence)
    whitelist = {w["arxiv_id"]: w["title"] for w in evidence["citation_whitelist"]}
    cited = sorted({i for text in docs.values() for i in ARXIV_ID.findall(text)})
    found = lookup.lookup(cited)
    numbers = check_numbers(basis, docs)
    names = check_names(basis, docs)
    phrases = check_phrases(docs)
    headings = [
        e for name, heads in (("research_plan.md", PLAN_HEADINGS), ("paper_skeleton.md", SKELETON_HEADINGS))
        for e in validate_markdown(docs.get(name, ""), heads, set(whitelist)) if e.startswith("필수 제목 누락")
    ]
    return {
        "citations": len(cited),
        "citations_outside_whitelist": [i for i in cited if i not in whitelist],
        "citations_not_on_arxiv": [i for i in cited if found.get(i) and not found[i]["found"]],
        "citations_unchecked": [i for i in cited if found.get(i) is None],
        "numbers_not_in_evidence": numbers,
        "names_not_in_evidence": names,
        "result_claims": phrases,
        "internal_labels": sorted({m for text in docs.values() for m in PAPER_LABEL.findall(text)}),
        "missing_headings": headings,
        "chars": sum(len(t) for t in docs.values()),
    }


# ---------- LLM 판정 ----------

def eval_judge_instructions() -> str:
    return (PROMPTS / "eval_judge.md").read_text(encoding="utf-8") + "\n\n" + field_guidance(JUDGED_FIELDS)


def check_eval_judgement(j: dict) -> list[str]:
    elements = [s.get("element") for s in j.get("element_scores", [])]
    errors = [f"{f}의 점수가 정확히 하나여야 함 (현재 {elements.count(f)}개)"
              for f in JUDGED_FIELDS if elements.count(f) != 1]
    errors += [f"{s.get('element')} 점수 {s.get('score')}는 1~5 밖임"
               for s in j.get("element_scores", []) if not 1 <= int(s.get("score", 0)) <= 5]
    return errors


def judge_documents(evidence: dict, docs: dict[str, str], provider: LLMProvider, samples: int) -> list[dict]:
    """같은 문서를 samples번 평가한다. 형식이 틀린 출력은 한 번 다시 받는다."""
    payload = {"evidence": compact_evidence(evidence), "documents": docs}
    out = []
    for _ in range(samples):
        errors: list[str] = []
        for _attempt in range(2):
            document = json.dumps(payload | ({"fix_errors": errors} if errors else {}), ensure_ascii=False, indent=1)
            j = provider.evaluate(instructions=eval_judge_instructions(), document=document,
                                  schema=EVAL_SCHEMA, schema_name="eval_judge")
            errors = check_eval_judgement(j)
            if not errors:
                out.append(j)
                break
        else:
            raise EvalError(f"평가 판정기 출력이 형식 검사를 통과하지 못함: {errors}")
    return out


def summarize_judgements(judgements: list[dict]) -> dict:
    means = [statistics.mean(s["score"] for s in j["element_scores"]) for j in judgements]
    per_element = {
        f: round(statistics.mean(s["score"] for j in judgements for s in j["element_scores"] if s["element"] == f), 2)
        for f in JUDGED_FIELDS
    }
    present = [s["present"] for j in judgements for s in j["element_scores"]]
    majors = [sum(i["severity"] == "major" for i in j["issues"]) for j in judgements]
    return {
        "samples": len(judgements),
        "mean_score": round(statistics.mean(means), 2),
        "sample_spread": round(max(means) - min(means), 2),  # 같은 문서를 여러 번 평가했을 때의 차이
        "present_rate": round(sum(present) / len(present), 3),
        "major_issues": round(statistics.mean(majors), 2),
        "per_element": per_element,
    }


# ---------- 사람 평가지 ----------

def human_sheet(idea: int, docs_by_condition: dict[str, dict[str, str]], seed: int) -> tuple[str, dict]:
    """조건을 A, B, C…로 섞은 눈가림 평가지와 정답 키를 만든다."""
    conditions = sorted(c for c in docs_by_condition if c != "golden")
    random.Random(seed).shuffle(conditions)
    key = {chr(ord("A") + n): c for n, c in enumerate(conditions)}
    letters = list(key)
    lines = [
        f"# 사람 평가지: 아이디어 {idea}",
        "",
        "아래 문서들은 같은 근거 자료로 서로 다른 방법을 써서 만든 것이다. 어떤 방법인지는 평가가 끝날 때까지 보지 않는다(정답 키는 별도 파일).",
        "각 요소에 1~5점을 매긴다. 기준은 `docs/field_definitions.md`의 \"좋은 값의 기준\" 열이다. 수치가 [TBD]인 것은 감점하지 않는다.",
        "",
        "## 1. 요소별 점수",
        "",
        "| 요소 | " + " | ".join(letters) + " |",
        "|---|" + "---|" * len(letters),
    ]
    lines += [f"| `{f}` | " + " | ".join(" " for _ in letters) + " |" for f in JUDGED_FIELDS]
    lines += [
        "",
        "## 2. 전체 평가",
        "",
        "| 질문 | " + " | ".join(letters) + " |",
        "|---|" + "---|" * len(letters),
        "| 이대로 지도교수에게 보여줄 수 있는가 (예/고치면/아니오) | " + " | ".join(" " for _ in letters) + " |",
        "| 근거 자료에 없는 내용을 지어냈는가 (예/아니오, 위치) | " + " | ".join(" " for _ in letters) + " |",
        "| 순위 (1이 가장 좋음) | " + " | ".join(" " for _ in letters) + " |",
        "",
        "## 3. 의견",
        "",
        "- ",
        "",
    ]
    if "golden" in docs_by_condition:
        lines += ["## 참고: 사람이 쓴 정답 예시", "",
                  "평가 기준을 맞추는 참고용이다. 위 문서들과 같은 방법으로 점수를 매기지 않는다.", ""]
        for name, text in docs_by_condition["golden"].items():
            lines += [f"### 정답 예시 · {name}", "", text, ""]
    for letter in letters:
        for name, text in docs_by_condition[key[letter]].items():
            lines += [f"## 문서 {letter} · {name}", "", text, ""]
    return "\n".join(lines), key


# ---------- 실행 ----------

def _cost(provider) -> float:
    return round(sum(c.get("usage", {}).get("cost", 0) or 0 for c in getattr(provider, "calls", [])), 6)


def evaluate(
    run_dir: Path,
    ideas: list[int],
    *,
    writer: LLMProvider,
    judges: list[LLMProvider],
    lookup: ArxivLookup,
    out_root: Path = Path("eval"),
    conditions: tuple[str, ...] = CONDITIONS,
    samples: int = 2,
    include_golden: bool = True,
    pipeline_providers: dict | None = None,
    human_idea: int | None = None,
    seed: int = 7,
) -> dict:
    from .pipeline import run_pipeline  # pipeline이 cli를 쓰므로 함수 안에서 가져온다

    run = load_run(run_dir)
    eval_dir = Path(out_root) / f"eval_{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    eval_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "run_id": run.run_id,
        "ideas": ideas,
        "conditions": list(conditions),
        "writer_model": writer.model,
        "judge_models": [j.model for j in judges],
        "samples_per_judge": samples,
        "results": [],
    }
    docs_for_sheet: dict[str, dict[str, str]] = {}
    sheet_idea = human_idea or (GOLDEN_IDEA if GOLDEN_IDEA in ideas else ideas[0])
    for idea in ideas:
        evidence = build_evidence(run, idea)
        folder = eval_dir / f"idea{idea:02d}"
        folder.mkdir(exist_ok=True)
        targets = list(conditions) + (["golden"] if include_golden and idea == GOLDEN_IDEA and GOLDEN.is_dir() else [])
        for condition in targets:
            print(f"[평가] 아이디어 {idea} · {condition}")
            started, before = time.monotonic(), _cost(writer)
            status, cost = "ok", 0.0
            if condition == "pipeline":
                code = run_pipeline(run_dir, idea, out=eval_dir / "pipeline_runs", providers=pipeline_providers)
                src = eval_dir / "pipeline_runs" / run.run_id / f"idea{idea:02d}"
                docs = {n: (src / n).read_text(encoding="utf-8") for n in DOCS if (src / n).is_file()}
                manifest = src / "run_manifest.json"
                if manifest.is_file():
                    cost = json.loads(manifest.read_text(encoding="utf-8"))["total_cost_usd"]
                status = {0: "ok", 1: "needs_review"}.get(code, "error")
            elif condition == "golden":
                docs = {n: (GOLDEN / n).read_text(encoding="utf-8") for n in DOCS}
            else:
                docs = generate_baseline(evidence, condition, writer)
                cost = round(_cost(writer) - before, 6)
            seconds = round(time.monotonic() - started, 1)
            if len(docs) < len(DOCS):
                report["results"].append({"idea": idea, "condition": condition, "status": "error", "seconds": seconds})
                continue
            out = folder / condition
            out.mkdir(exist_ok=True)
            for name, text in docs.items():
                (out / name).write_text(text, encoding="utf-8")
            if idea == sheet_idea:
                docs_for_sheet[condition] = docs
            judged = {}
            for judge in judges:
                judgements = judge_documents(evidence, docs, judge, samples)
                judged[judge.model] = {"summary": summarize_judgements(judgements), "judgements": judgements}
            report["results"].append({
                "idea": idea, "condition": condition, "status": status, "seconds": seconds, "cost_usd": cost,
                "metrics": auto_metrics(evidence, docs, lookup), "judges": judged,
            })
    report["summary"] = summarize(report)
    report["judge_cost_usd"] = round(sum(_cost(j) for j in judges), 6)
    (eval_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (eval_dir / "summary.md").write_text(summary_markdown(report), encoding="utf-8")
    if docs_for_sheet:
        sheet, key = human_sheet(sheet_idea, docs_for_sheet, seed)
        (eval_dir / "human").mkdir(exist_ok=True)
        (eval_dir / "human" / f"idea{sheet_idea:02d}_sheet.md").write_text(sheet, encoding="utf-8")
        (eval_dir / "human" / f"idea{sheet_idea:02d}_key.json").write_text(
            json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["folder"] = eval_dir.as_posix()
    return report


def rescore(eval_dir: Path, run_dir: Path, lookup: ArxivLookup) -> dict:
    """저장된 문서로 자동 지표만 다시 계산한다(LLM 호출 없음). 자동 지표 검사를 고친 뒤 기존 평가에 반영할 때 쓴다."""
    eval_dir = Path(eval_dir)
    report = json.loads((eval_dir / "report.json").read_text(encoding="utf-8"))
    run = load_run(run_dir)
    evidences: dict[int, dict] = {}
    for r in report["results"]:
        folder = eval_dir / f"idea{r['idea']:02d}" / r["condition"]
        if r["status"] == "error" or not folder.is_dir():
            continue
        evidence = evidences.setdefault(r["idea"], build_evidence(run, r["idea"]))
        docs = {n: (folder / n).read_text(encoding="utf-8") for n in DOCS}
        r["metrics"] = auto_metrics(evidence, docs, lookup)
    report["summary"] = summarize(report)
    report["rescored_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    (eval_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (eval_dir / "summary.md").write_text(summary_markdown(report), encoding="utf-8")
    return report


def summarize(report: dict) -> dict:
    """조건별로 아이디어 평균을 낸다."""
    by_condition = {}
    for condition in report["conditions"] + ["golden"]:
        rows = [r for r in report["results"] if r["condition"] == condition and r["status"] != "error"]
        if not rows:
            continue
        mean = lambda xs: round(statistics.mean(xs), 3) if xs else None  # noqa: E731
        entry = {
            "ideas": len(rows),
            "errors": sum(r["condition"] == condition and r["status"] == "error" for r in report["results"]),
            "cost_usd": mean([r["cost_usd"] for r in rows]),
            "seconds": mean([r["seconds"] for r in rows]),
            "numbers_not_in_evidence": mean([len(r["metrics"]["numbers_not_in_evidence"]) for r in rows]),
            "names_not_in_evidence": mean([len(r["metrics"]["names_not_in_evidence"]) for r in rows]),
            "citations_outside_whitelist": mean([len(r["metrics"]["citations_outside_whitelist"]) for r in rows]),
            "citations_not_on_arxiv": mean([len(r["metrics"]["citations_not_on_arxiv"]) for r in rows]),
            "result_claims": mean([len(r["metrics"]["result_claims"]) for r in rows]),
            "internal_labels": mean([len(r["metrics"]["internal_labels"]) for r in rows]),
            "missing_headings": mean([len(r["metrics"]["missing_headings"]) for r in rows]),
            "judges": {},
        }
        for model in report["judge_models"]:
            sums = [r["judges"][model]["summary"] for r in rows]
            entry["judges"][model] = {
                "mean_score": mean([s["mean_score"] for s in sums]),
                "present_rate": mean([s["present_rate"] for s in sums]),
                "major_issues": mean([s["major_issues"] for s in sums]),
                "sample_spread": mean([s["sample_spread"] for s in sums]),
            }
        by_condition[condition] = entry
    return by_condition


def summary_markdown(report: dict) -> str:
    s = report["summary"]
    conds = list(s)
    head = "| 지표 | " + " | ".join(conds) + " |"
    sep = "|---|" + "---|" * len(conds)
    lines = [
        f"# 평가 요약: run `{report['run_id']}`",
        "",
        f"- 아이디어: {report['ideas']} · 작성 모델 `{report['writer_model']}` · 판정 모델 {report['judge_models']} "
        f"(문서마다 {report['samples_per_judge']}회)",
        "- 값은 아이디어 평균이다. golden은 6번 아이디어 하나뿐이다.",
        "",
        "## LLM 판정 (눈가림, 높을수록 좋음)",
        "",
        head, sep,
    ]
    for model in report["judge_models"]:
        for key, label in (("mean_score", "평균 점수 (1~5)"), ("present_rate", "요소 포함률"),
                           ("major_issues", "major 지적 수 (낮을수록 좋음)"), ("sample_spread", "같은 문서 반복 평가 차이")):
            lines.append(f"| {label} · `{model}` | " + " | ".join(str(s[c]["judges"][model][key]) for c in conds) + " |")
    lines += ["", "## 자동 지표 (낮을수록 좋음)", "", head, sep]
    for key, label in (("numbers_not_in_evidence", "근거에 없는 숫자"), ("names_not_in_evidence", "근거에 없는 이름 (경고)"),
                       ("citations_outside_whitelist", "화이트리스트 밖 인용"), ("citations_not_on_arxiv", "arXiv에 없는 인용"),
                       ("result_claims", "결과 단정 표현"), ("internal_labels", "내부 표기 (P1 등)"),
                       ("missing_headings", "필수 제목 누락")):
        lines.append(f"| {label} | " + " | ".join(str(s[c][key]) for c in conds) + " |")
    lines += ["", "## 비용과 시간", "", head, sep,
              "| 비용 (USD, 문서 생성) | " + " | ".join(str(s[c]["cost_usd"]) for c in conds) + " |",
              "| 시간 (초) | " + " | ".join(str(s[c]["seconds"]) for c in conds) + " |",
              "", f"판정 비용 합계: ${report.get('judge_cost_usd', 0)}", "",
              "## 읽는 법", "",
              "- free와 template의 차이는 \"필수 정보와 구조를 프롬프트로 지정한\" 효과, template과 pipeline의 차이는 분해·검사·보완의 효과다.",
              "- 판정 모델끼리 순위가 다르면 결과를 믿기 어렵다. 같은 문서 반복 평가 차이가 조건 간 차이보다 크면 차이가 의미 없을 수 있다.",
              "- 필수 제목 누락은 free 조건에 목차를 주지 않았으므로 free에 불리한 지표다. 내용 비교는 LLM 판정과 사람 평가를 본다.",
              ""]
    return "\n".join(lines)
