"""Stage 1 입력 어댑터: 한 실행(run)의 FutureWork·CoT1~CoT5·manifest 파일을 읽어 후보별로 짝짓는다.

docs/output_spec.md 1절과 docs/implementation_plan.md 4절 1단계를 구현한다. LLM은 쓰지 않는다.

실행 폴더는 New_Future-Work-Researcher와 같은 상대 경로 구조를 가진다.
진입점은 examples_run_manifest.json이고, 나머지 파일 위치는 manifest에서 읽는다.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

RUN_MANIFEST = "examples_run_manifest.json"
ARXIV_ID_PATTERN = re.compile(r"\d{4}\.\d{4,5}(?:v\d+)?")


class InputError(ValueError):
    """입력 파일끼리 짝이 맞지 않아 진행할 수 없을 때."""


@dataclass
class Paper:
    key: str  # CoT3가 쓰는 P1, P2, ...
    arxiv_id: str
    title: str
    source: str


@dataclass
class Candidate:
    index: int  # 1부터 시작. CoT4 어댑터의 enumerate(..., 1)과 같다.
    proposal: dict  # FutureWork future_work_proposals[index-1]
    cot3: dict | None
    cot4: dict
    cot5: dict
    warnings: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        return self.proposal["proposed_direction"].splitlines()[0].strip()

    @property
    def classification(self) -> str:
        return str(self.cot5.get("classification", ""))

    @property
    def cot3_id(self) -> str:
        return (self.cot3 or {}).get("candidate_id", "")


@dataclass
class Run:
    root: Path
    manifest: dict
    papers: list[Paper]
    candidates: list[Candidate]
    cot1: dict[str, dict]  # P1 → CoT1 결과
    cot2: dict[str, dict]  # P1 → CoT2 결과
    input_files: dict[str, dict]
    warnings: list[str] = field(default_factory=list)

    @property
    def run_id(self) -> str:
        return self.manifest.get("run_id", self.root.name)

    def candidate(self, index: int) -> Candidate:
        if not 1 <= index <= len(self.candidates):
            raise InputError(f"후보 번호 {index}는 범위 밖임 (1~{len(self.candidates)})")
        return self.candidates[index - 1]


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_variants(path: Path) -> set[str]:
    """원본, LF, CRLF 줄바꿈 기준 해시. git 체크아웃 설정에 따라 줄바꿈이 바뀌기 때문이다."""
    raw = path.read_bytes()
    lf = raw.replace(b"\r\n", b"\n")
    return {hashlib.sha256(data).hexdigest() for data in (raw, lf, lf.replace(b"\n", b"\r\n"))}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def title_matches(truncated: str, full: str) -> bool:
    """잘린 제목(CoT4·CoT5의 idea_title)이 원문 proposed_direction 첫 줄의 앞부분인지."""
    short = _norm(truncated)
    if short.endswith("..."):
        short = short[:-3].rstrip()
    return bool(short) and _norm(full.splitlines()[0]).startswith(short)


def _results(data: object, name: str) -> list[dict]:
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        return data["results"]
    raise InputError(f"{name}: results 목록이 없음")


def _papers(manifest: dict, upstream: dict | None) -> list[Paper]:
    # CoT3는 입력 순서대로 P1, P2, ...를 붙인다(build_evidence_pool). upstream의 papers가 그 순서다.
    if upstream and upstream.get("papers"):
        entries, base = upstream["papers"], "manifest.upstream.papers"
        return [
            Paper(f"P{i}", p.get("id", ""), p.get("title", ""), f"{base}[{i - 1}]")
            for i, p in enumerate(entries, 1)
        ]
    entries = manifest.get("source_papers", [])
    return [
        Paper(f"P{i}", p.get("arxiv_id", ""), p.get("title", ""), f"manifest.source_papers[{i - 1}]")
        for i, p in enumerate(entries, 1)
    ]


def _optional(root: Path, rel: str | None, name: str, warnings: list[str]) -> object | None:
    if not rel:
        warnings.append(f"{name}: manifest에 경로가 없어 건너뜀")
        return None
    path = root / rel
    if not path.is_file():
        warnings.append(f"{name}: 파일이 없어 건너뜀 ({rel})")
        return None
    return _read_json(path)


def _cot3_ids(proposals: list[dict], upstream: dict | None) -> list[str | None]:
    """FutureWork 제안 순서에 대응하는 CoT3 candidate_id. upstream 매핑 → novelty_note 순으로 찾는다."""
    mapping = {
        m.get("result_index_1_based"): m.get("cot3_candidate_id")
        for m in (upstream or {}).get("candidate_mapping", [])
    }
    ids: list[str | None] = []
    for i, proposal in enumerate(proposals, 1):
        if i in mapping:
            ids.append(mapping[i])
            continue
        match = re.search(r"\bCoT3\s+(C\d+)\b", str(proposal.get("novelty_note", "")))
        ids.append(match.group(1) if match else None)
    return ids


def load_run(run_dir: Path, *, future_work: Path | None = None) -> Run:
    """실행 폴더를 읽어 후보 목록을 만든다. 짝이 맞지 않으면 InputError."""
    root = Path(run_dir)
    manifest_path = root / RUN_MANIFEST
    if not manifest_path.is_file():
        raise InputError(f"{RUN_MANIFEST}가 없음: {root}")
    manifest = _read_json(manifest_path)
    warnings: list[str] = []

    fw_path = future_work or (root / manifest["input_file"] if manifest.get("input_file") else None)
    if fw_path is None or not Path(fw_path).is_file():
        raise InputError("FutureWork 입력 파일을 찾을 수 없음 (manifest.input_file 또는 --future-work)")
    fw_path = Path(fw_path)
    fw = _read_json(fw_path)
    if not (isinstance(fw, dict) and isinstance(fw.get("future_work_proposals"), list)):
        raise InputError("FutureWork 입력에 future_work_proposals 목록이 없음")
    proposals = fw["future_work_proposals"]
    for i, proposal in enumerate(proposals, 1):
        for key in ("background_and_gap", "proposed_direction"):
            if not str(proposal.get(key, "")).strip():
                raise InputError(f"FutureWork 제안 {i}: {key}가 비어 있음")

    results = manifest.get("results", {})
    cot4 = _results(_read_json(root / results.get("CoT4", "CoT4/examples/result.json")), "CoT4")
    cot5 = _results(_read_json(root / results.get("CoT5", "CoT5/examples/result.json")), "CoT5")

    counts = {"FutureWork": len(proposals), "CoT4": len(cot4), "CoT5": len(cot5)}
    if "input_candidate_count" in manifest:
        counts["manifest"] = manifest["input_candidate_count"]
    if len(set(counts.values())) != 1:
        raise InputError(f"후보 수가 서로 다름: {counts}")

    input_files = {
        "manifest": {"path": RUN_MANIFEST, "sha256": _sha256(manifest_path)},
        "future_work": {"path": _relative(fw_path, root), "sha256": _sha256(fw_path)},
    }
    expected = manifest.get("input_sha256")
    if expected:
        if expected in sha256_variants(fw_path):
            input_files["future_work"]["matches_manifest_sha256"] = True
        else:
            input_files["future_work"]["matches_manifest_sha256"] = False
            warnings.append("FutureWork 파일 해시가 manifest.input_sha256과 다름 (줄바꿈 차이를 제외해도)")

    upstream = _optional(root, manifest.get("upstream_manifest"), "upstream manifest", warnings)
    papers = _papers(manifest, upstream)
    if not papers:
        warnings.append("시드 논문 목록이 없음: P1, P2를 논문과 연결할 수 없음")

    upstream_results = manifest.get("upstream_results", {})
    cot3_data = _optional(root, upstream_results.get("CoT3"), "CoT3 결과", warnings)
    cot3_by_id = {c.get("candidate_id"): c for c in cot3_data or [] if isinstance(c, dict)}
    cot1, cot2 = {}, {}
    for stage, store in (("CoT1", cot1), ("CoT2", cot2)):
        for paper in papers:
            rel = next(
                (r for r in upstream_results.get(stage, []) if paper.arxiv_id and paper.arxiv_id in r), None
            )
            data = _optional(root, rel, f"{stage} 결과({paper.key})", warnings)
            if data is not None:
                store[paper.key] = data

    candidates = []
    for i, (proposal, c4, c5, cot3_id) in enumerate(
        zip(proposals, cot4, cot5, _cot3_ids(proposals, upstream)), 1
    ):
        direction = proposal["proposed_direction"]
        for name, result in (("CoT4", c4), ("CoT5", c5)):
            if not title_matches(str(result.get("idea_title", "")), direction):
                raise InputError(
                    f"후보 {i}: {name} 제목이 FutureWork 제안과 다름 "
                    f"({result.get('idea_title', '')!r} vs {direction[:60]!r})"
                )
        cot3 = cot3_by_id.get(cot3_id)
        if cot3 is not None and _norm(cot3.get("proposed_direction", "")) != _norm(direction):
            raise InputError(f"후보 {i}: CoT3 {cot3_id}의 proposed_direction이 FutureWork와 다름")
        candidate = Candidate(i, proposal, cot3, c4, c5)
        candidate.warnings += _candidate_warnings(candidate, cot3_data is not None)
        candidates.append(candidate)

    for name, rel in (("cot3", upstream_results.get("CoT3")), ("cot4", results.get("CoT4")),
                      ("cot5", results.get("CoT5"))):
        if rel and (root / rel).is_file():
            input_files[name] = {"path": rel, "sha256": _sha256(root / rel)}
    return Run(root, manifest, papers, candidates, cot1, cot2, input_files, warnings)


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _candidate_warnings(candidate: Candidate, has_cot3: bool) -> list[str]:
    warnings = []
    if candidate.classification != "NOVEL":
        warnings.append(f"CoT5 판정이 {candidate.classification or '없음'}임")
    if has_cot3 and candidate.cot3 is None:
        warnings.append("대응하는 CoT3 후보를 찾지 못함: 원 논문 인용문 없이 진행")
    verdict = (candidate.cot3 or {}).get("judge_verdict", {})
    for axis in ("grounding", "validity"):
        if verdict and verdict.get(axis) != "PASS":
            warnings.append(f"CoT3 judge {axis}={verdict.get(axis)}: 근거가 약할 수 있음")
    if candidate.cot4.get("status") == "error":
        warnings.append(f"CoT4 오류: {candidate.cot4.get('error', '')}")
    for source, overlap in candidate.cot5.get("overlaps", {}).items():
        if overlap.get("error"):
            warnings.append(f"CoT5 {source} 검색 실패({overlap.get('status')}): {overlap['error']}")
    if candidate.cot5.get("paper_search", {}).get("coverage") not in (None, "complete"):
        warnings.append(f"CoT5 논문 검색 범위: {candidate.cot5['paper_search']['coverage']}")
    return warnings
