"""Typed input schemas and normalized artifact models for the harness."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Final
from urllib.parse import urlsplit


SCHEMA_VERSION: Final[int] = 1
_ARXIV_HOSTS: Final[set[str]] = {"arxiv.org", "www.arxiv.org"}
_NEW_ID_RE: Final[re.Pattern[str]] = re.compile(r"^\d{4}\.\d{4,5}(?:v\d+)?$")
_OLD_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z][a-z0-9-]*(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?$"
)


class SchemaValidationError(ValueError):
    """Raised when schema input cannot be normalized or validated."""


@dataclass(frozen=True)
class ArxivReference:
    """Canonical arXiv identifier plus normalized arXiv URLs."""

    arxiv_id: str
    abs_url: str
    pdf_url: str


def parse_arxiv_reference(value: str) -> ArxivReference:
    """Parse an arXiv ID, arXiv-prefixed ID, abs URL, or pdf URL."""

    if not isinstance(value, str):
        raise SchemaValidationError("arXiv reference must be a string")

    raw_value = value.strip()
    if not raw_value:
        raise SchemaValidationError("arXiv reference cannot be empty")

    if _looks_like_url(raw_value):
        arxiv_id = _parse_arxiv_url(raw_value)
    else:
        arxiv_id = _strip_arxiv_prefix(raw_value)

    arxiv_id = _strip_pdf_suffix(arxiv_id.strip())
    _validate_arxiv_id(arxiv_id)

    return ArxivReference(
        arxiv_id=arxiv_id,
        abs_url=f"https://arxiv.org/abs/{arxiv_id}",
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}.pdf",
    )


@dataclass(frozen=True)
class SelectedPaperInput:
    """User-selected arXiv paper input normalized for downstream stages."""

    source: str
    title: str | None = None
    schema_version: int = SCHEMA_VERSION
    arxiv_id: str = field(init=False)
    abs_url: str = field(init=False)
    pdf_url: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_schema_version(self.schema_version)
        if self.title is not None and not isinstance(self.title, str):
            raise SchemaValidationError("title must be a string when provided")

        parsed = parse_arxiv_reference(self.source)
        object.__setattr__(self, "arxiv_id", parsed.arxiv_id)
        object.__setattr__(self, "abs_url", parsed.abs_url)
        object.__setattr__(self, "pdf_url", parsed.pdf_url)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SelectedPaperInput":
        if not isinstance(payload, dict):
            raise SchemaValidationError("selected paper input must be an object")
        return cls(
            source=_required_str(payload, "source"),
            title=_optional_str(payload, "title"),
            schema_version=payload.get("schema_version", SCHEMA_VERSION),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "title": self.title,
            "arxiv_id": self.arxiv_id,
            "abs_url": self.abs_url,
            "pdf_url": self.pdf_url,
        }


@dataclass(frozen=True)
class UserDraftInput:
    """Optional user-authored draft and memo text."""

    draft_text: str | None = None
    memo_text: str | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_schema_version(self.schema_version)
        if self.draft_text is not None and not isinstance(self.draft_text, str):
            raise SchemaValidationError("draft_text must be a string when provided")
        if self.memo_text is not None and not isinstance(self.memo_text, str):
            raise SchemaValidationError("memo_text must be a string when provided")

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "UserDraftInput | None":
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise SchemaValidationError("user draft input must be an object")
        return cls(
            draft_text=_optional_str(payload, "draft_text"),
            memo_text=_optional_str(payload, "memo_text"),
            schema_version=payload.get("schema_version", SCHEMA_VERSION),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "draft_text": self.draft_text,
            "memo_text": self.memo_text,
        }


@dataclass(frozen=True)
class HarnessInput:
    """Top-level schema for selected papers plus optional user draft input."""

    selected_papers: tuple[SelectedPaperInput, ...]
    user_draft: UserDraftInput | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_schema_version(self.schema_version)
        if not isinstance(self.selected_papers, tuple):
            object.__setattr__(self, "selected_papers", tuple(self.selected_papers))
        if not self.selected_papers:
            raise SchemaValidationError("selected_papers must include at least one paper")
        for paper in self.selected_papers:
            if not isinstance(paper, SelectedPaperInput):
                raise SchemaValidationError("selected_papers must contain SelectedPaperInput values")
        if self.user_draft is not None and not isinstance(self.user_draft, UserDraftInput):
            raise SchemaValidationError("user_draft must be UserDraftInput when provided")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "HarnessInput":
        if not isinstance(payload, dict):
            raise SchemaValidationError("harness input must be an object")

        papers_payload = payload.get("selected_papers")
        if not isinstance(papers_payload, list):
            raise SchemaValidationError("selected_papers must be a list")

        return cls(
            selected_papers=tuple(
                SelectedPaperInput.from_dict(paper_payload)
                for paper_payload in papers_payload
            ),
            user_draft=UserDraftInput.from_dict(payload.get("user_draft")),
            schema_version=payload.get("schema_version", SCHEMA_VERSION),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "selected_papers": [paper.to_dict() for paper in self.selected_papers],
            "user_draft": None if self.user_draft is None else self.user_draft.to_dict(),
        }


@dataclass(frozen=True)
class SelectedPaper:
    """Normalized selected-paper artifact persisted by ingest."""

    paper_id: str
    title: str = ""
    abstract: str = ""
    authors: tuple[str, ...] = ()
    published: str = ""
    arxiv_primary_category: str = ""
    arxiv_categories: tuple[str, ...] = ()
    abs_url: str = ""
    pdf_url: str = ""
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_schema_version(self.schema_version)
        if not self.paper_id:
            raise SchemaValidationError("paper_id must be a non-empty string")
        if not isinstance(self.title, str):
            raise SchemaValidationError("title must be a string")
        if not isinstance(self.abstract, str):
            raise SchemaValidationError("abstract must be a string")
        if not isinstance(self.published, str):
            raise SchemaValidationError("published must be a string")
        if not isinstance(self.arxiv_primary_category, str):
            raise SchemaValidationError("arxiv_primary_category must be a string")
        if not isinstance(self.abs_url, str):
            raise SchemaValidationError("abs_url must be a string")
        if not isinstance(self.pdf_url, str):
            raise SchemaValidationError("pdf_url must be a string")
        object.__setattr__(self, "authors", _normalize_str_tuple(self.authors, key="authors"))
        object.__setattr__(
            self,
            "arxiv_categories",
            _normalize_str_tuple(self.arxiv_categories, key="arxiv_categories"),
        )

    @classmethod
    def from_input(cls, payload: SelectedPaperInput) -> "SelectedPaper":
        return cls(
            paper_id=payload.arxiv_id,
            title=payload.title or "",
            abstract="",
            authors=(),
            published="",
            arxiv_primary_category="",
            arxiv_categories=(),
            abs_url=payload.abs_url,
            pdf_url=payload.pdf_url,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SelectedPaper":
        if not isinstance(payload, dict):
            raise SchemaValidationError("selected paper artifact must be an object")
        return cls(
            paper_id=_required_str(payload, "paper_id"),
            title=_optional_str(payload, "title") or "",
            abstract=_optional_str(payload, "abstract") or "",
            authors=tuple(_optional_str_list(payload, "authors")),
            published=_optional_str(payload, "published") or "",
            arxiv_primary_category=_optional_str(payload, "arxiv_primary_category") or "",
            arxiv_categories=tuple(_optional_str_list(payload, "arxiv_categories")),
            abs_url=_optional_str(payload, "abs_url") or "",
            pdf_url=_optional_str(payload, "pdf_url") or "",
            schema_version=payload.get("schema_version", SCHEMA_VERSION),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "abstract": self.abstract,
            "authors": list(self.authors),
            "published": self.published,
            "arxiv_primary_category": self.arxiv_primary_category,
            "arxiv_categories": list(self.arxiv_categories),
            "abs_url": self.abs_url,
            "pdf_url": self.pdf_url,
        }

    def text_for_evidence(self) -> str:
        parts = [self.title.strip(), self.abstract.strip()]
        return "\n\n".join(part for part in parts if part)


@dataclass(frozen=True)
class EvidenceCard:
    """Normalized offline evidence extraction output for one paper."""

    paper_id: str
    claims: tuple[str, ...] = ()
    methods: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    evaluation_signals: tuple[str, ...] = ()
    future_work_clues: tuple[str, ...] = ()
    quotes_or_snippets: tuple[str, ...] = ()
    confidence: float = 0.0
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_schema_version(self.schema_version)
        if not self.paper_id:
            raise SchemaValidationError("paper_id must be a non-empty string")
        for field_name in (
            "claims",
            "methods",
            "limitations",
            "evaluation_signals",
            "future_work_clues",
            "quotes_or_snippets",
        ):
            object.__setattr__(self, field_name, _normalize_str_tuple(getattr(self, field_name), key=field_name))
        if not isinstance(self.confidence, (int, float)):
            raise SchemaValidationError("confidence must be numeric")
        bounded_confidence = min(1.0, max(0.0, float(self.confidence)))
        object.__setattr__(self, "confidence", bounded_confidence)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvidenceCard":
        if not isinstance(payload, dict):
            raise SchemaValidationError("evidence card must be an object")
        return cls(
            paper_id=_required_str(payload, "paper_id"),
            claims=tuple(_optional_str_list(payload, "claims")),
            methods=tuple(_optional_str_list(payload, "methods")),
            limitations=tuple(_optional_str_list(payload, "limitations")),
            evaluation_signals=tuple(_optional_str_list(payload, "evaluation_signals")),
            future_work_clues=tuple(_optional_str_list(payload, "future_work_clues")),
            quotes_or_snippets=tuple(_optional_str_list(payload, "quotes_or_snippets")),
            confidence=payload.get("confidence", 0.0),
            schema_version=payload.get("schema_version", SCHEMA_VERSION),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "claims": list(self.claims),
            "methods": list(self.methods),
            "limitations": list(self.limitations),
            "evaluation_signals": list(self.evaluation_signals),
            "future_work_clues": list(self.future_work_clues),
            "quotes_or_snippets": list(self.quotes_or_snippets),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class CandidateCard:
    """Deterministic innovation candidate generated from evidence cards."""

    candidate_id: str
    title: str
    gap_statement: str
    hypothesis: str
    supporting_evidence_refs: tuple[str, ...] = ()
    proposed_method: str = ""
    evaluation_plan: str = ""
    expected_contribution: str = ""
    risks: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_schema_version(self.schema_version)
        for field_name in (
            "candidate_id",
            "title",
            "gap_statement",
            "hypothesis",
            "proposed_method",
            "evaluation_plan",
            "expected_contribution",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise SchemaValidationError(f"{field_name} must be a non-empty string")
        object.__setattr__(
            self,
            "supporting_evidence_refs",
            _normalize_str_tuple(self.supporting_evidence_refs, key="supporting_evidence_refs"),
        )
        if not self.supporting_evidence_refs:
            raise SchemaValidationError("supporting_evidence_refs must include at least one paper_id")
        object.__setattr__(self, "risks", _normalize_str_tuple(self.risks, key="risks"))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CandidateCard":
        if not isinstance(payload, dict):
            raise SchemaValidationError("candidate card must be an object")
        return cls(
            candidate_id=_required_str(payload, "candidate_id"),
            title=_required_str(payload, "title"),
            gap_statement=_required_str(payload, "gap_statement"),
            hypothesis=_required_str(payload, "hypothesis"),
            supporting_evidence_refs=tuple(_optional_str_list(payload, "supporting_evidence_refs")),
            proposed_method=_required_str(payload, "proposed_method"),
            evaluation_plan=_required_str(payload, "evaluation_plan"),
            expected_contribution=_required_str(payload, "expected_contribution"),
            risks=tuple(_optional_str_list(payload, "risks")),
            schema_version=payload.get("schema_version", SCHEMA_VERSION),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "title": self.title,
            "gap_statement": self.gap_statement,
            "hypothesis": self.hypothesis,
            "supporting_evidence_refs": list(self.supporting_evidence_refs),
            "proposed_method": self.proposed_method,
            "evaluation_plan": self.evaluation_plan,
            "expected_contribution": self.expected_contribution,
            "risks": list(self.risks),
        }


@dataclass(frozen=True)
class CriticReport:
    """Balanced offline critic report for one innovation candidate."""

    candidate_id: str
    verdict: str
    evidence_score: float
    feasibility_score: float
    novelty_risk: str = "unknown"
    weaknesses: tuple[str, ...] = ()
    required_fixes: tuple[str, ...] = ()
    rationale: str = ""
    near_pass: bool = False
    verification_status: str = "not_checked"
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_schema_version(self.schema_version)
        if not isinstance(self.candidate_id, str) or not self.candidate_id.strip():
            raise SchemaValidationError("candidate_id must be a non-empty string")
        if self.verdict not in {"pass", "revise", "fail"}:
            raise SchemaValidationError("verdict must be pass, revise, or fail")
        if self.novelty_risk not in {"unknown", "low", "medium", "high"}:
            raise SchemaValidationError("novelty_risk must be unknown, low, medium, or high")
        if not isinstance(self.verification_status, str) or not self.verification_status.strip():
            raise SchemaValidationError("verification_status must be a non-empty string")
        if not isinstance(self.rationale, str) or not self.rationale.strip():
            raise SchemaValidationError("rationale must be a non-empty string")
        object.__setattr__(self, "weaknesses", _normalize_str_tuple(self.weaknesses, key="weaknesses"))
        object.__setattr__(self, "required_fixes", _normalize_str_tuple(self.required_fixes, key="required_fixes"))
        if not isinstance(self.metadata, dict):
            raise SchemaValidationError("metadata must be an object")
        object.__setattr__(self, "evidence_score", _bounded_score(self.evidence_score, key="evidence_score"))
        object.__setattr__(self, "feasibility_score", _bounded_score(self.feasibility_score, key="feasibility_score"))
        object.__setattr__(self, "confidence", _bounded_score(self.confidence, key="confidence"))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CriticReport":
        if not isinstance(payload, dict):
            raise SchemaValidationError("critic report must be an object")
        return cls(
            candidate_id=_required_str(payload, "candidate_id"),
            verdict=_required_str(payload, "verdict"),
            evidence_score=payload.get("evidence_score", 0.0),
            feasibility_score=payload.get("feasibility_score", 0.0),
            novelty_risk=_optional_str(payload, "novelty_risk") or "unknown",
            weaknesses=tuple(_optional_str_list(payload, "weaknesses")),
            required_fixes=tuple(_optional_str_list(payload, "required_fixes")),
            rationale=_required_str(payload, "rationale"),
            near_pass=bool(payload.get("near_pass", False)),
            verification_status=_optional_str(payload, "verification_status") or "not_checked",
            confidence=payload.get("confidence", 0.0),
            metadata=payload.get("metadata", {}),
            schema_version=payload.get("schema_version", SCHEMA_VERSION),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "verdict": self.verdict,
            "evidence_score": self.evidence_score,
            "feasibility_score": self.feasibility_score,
            "novelty_risk": self.novelty_risk,
            "weaknesses": list(self.weaknesses),
            "required_fixes": list(self.required_fixes),
            "rationale": self.rationale,
            "near_pass": self.near_pass,
            "verification_status": self.verification_status,
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SelectedCandidate:
    """Run-bound selected pass candidate artifact."""

    run_id: str
    candidate_id: str
    selected_at: str
    candidate: CandidateCard
    critic_report: CriticReport
    source_paths: dict[str, str] = field(default_factory=dict)
    pass_candidate_ids: tuple[str, ...] = ()
    status: str = "selected"
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_schema_version(self.schema_version)
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise SchemaValidationError("run_id must be a non-empty string")
        if not isinstance(self.candidate_id, str) or not self.candidate_id.strip():
            raise SchemaValidationError("candidate_id must be a non-empty string")
        if not isinstance(self.selected_at, str) or not self.selected_at.strip():
            raise SchemaValidationError("selected_at must be a non-empty string")
        if self.status != "selected":
            raise SchemaValidationError("status must be selected")
        if not isinstance(self.candidate, CandidateCard):
            raise SchemaValidationError("candidate must be a CandidateCard")
        if not isinstance(self.critic_report, CriticReport):
            raise SchemaValidationError("critic_report must be a CriticReport")
        if self.candidate.candidate_id != self.candidate_id:
            raise SchemaValidationError("candidate_id must match candidate.candidate_id")
        if self.critic_report.candidate_id != self.candidate_id:
            raise SchemaValidationError("candidate_id must match critic_report.candidate_id")
        if self.critic_report.verdict != "pass":
            raise SchemaValidationError("selected candidate critic verdict must be pass")
        if not isinstance(self.source_paths, dict):
            raise SchemaValidationError("source_paths must be an object")
        normalized_source_paths: dict[str, str] = {}
        for key in ("candidate_loop", "candidate", "critic_report"):
            value = self.source_paths.get(key, "")
            if not isinstance(value, str):
                raise SchemaValidationError(f"source_paths[{key!r}] must be a string")
            normalized_source_paths[key] = value
        object.__setattr__(self, "source_paths", normalized_source_paths)
        object.__setattr__(
            self,
            "pass_candidate_ids",
            _normalize_str_tuple(self.pass_candidate_ids, key="pass_candidate_ids"),
        )
        if self.candidate_id not in self.pass_candidate_ids:
            raise SchemaValidationError("selected candidate must be listed in pass_candidate_ids")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SelectedCandidate":
        if not isinstance(payload, dict):
            raise SchemaValidationError("selected candidate artifact must be an object")
        return cls(
            run_id=_required_str(payload, "run_id"),
            candidate_id=_required_str(payload, "candidate_id"),
            selected_at=_required_str(payload, "selected_at"),
            candidate=CandidateCard.from_dict(payload.get("candidate", {})),
            critic_report=CriticReport.from_dict(payload.get("critic_report", {})),
            source_paths=_optional_dict(payload, "source_paths") or {},
            pass_candidate_ids=tuple(_optional_str_list(payload, "pass_candidate_ids")),
            status=_optional_str(payload, "status") or "selected",
            schema_version=payload.get("schema_version", SCHEMA_VERSION),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "run_id": self.run_id,
            "candidate_id": self.candidate_id,
            "selected_at": self.selected_at,
            "candidate": self.candidate.to_dict(),
            "critic_report": self.critic_report.to_dict(),
            "source_paths": dict(self.source_paths),
            "pass_candidate_ids": list(self.pass_candidate_ids),
        }


@dataclass(frozen=True)
class RevisionRecord:
    """Run-bound persisted revision or Q/A artifact."""

    mode: str
    user_request: str
    answer_or_diff_summary: str
    files_changed: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    run_id: str = ""
    selected_candidate_id: str = ""
    draft_path: str = "draft.md"
    claim_map_path: str = "draft.claim_map.json"
    selected_candidate_path: str = "selected_candidate.json"
    created_at: str = ""
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_schema_version(self.schema_version)
        if self.mode not in {"qa_suggest", "auto_edit"}:
            raise SchemaValidationError("mode must be qa_suggest or auto_edit")
        for field_name in (
            "user_request",
            "answer_or_diff_summary",
            "run_id",
            "selected_candidate_id",
            "draft_path",
            "claim_map_path",
            "selected_candidate_path",
            "created_at",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise SchemaValidationError(f"{field_name} must be a non-empty string")
        object.__setattr__(self, "files_changed", _normalize_str_tuple(self.files_changed, key="files_changed"))
        object.__setattr__(self, "evidence_refs", _normalize_str_tuple(self.evidence_refs, key="evidence_refs"))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RevisionRecord":
        if not isinstance(payload, dict):
            raise SchemaValidationError("revision record must be an object")
        return cls(
            mode=_required_str(payload, "mode"),
            user_request=_required_str(payload, "user_request"),
            answer_or_diff_summary=_required_str(payload, "answer_or_diff_summary"),
            files_changed=tuple(_optional_str_list(payload, "files_changed")),
            evidence_refs=tuple(_optional_str_list(payload, "evidence_refs")),
            run_id=_required_str(payload, "run_id"),
            selected_candidate_id=_required_str(payload, "selected_candidate_id"),
            draft_path=_required_str(payload, "draft_path"),
            claim_map_path=_required_str(payload, "claim_map_path"),
            selected_candidate_path=_required_str(payload, "selected_candidate_path"),
            created_at=_required_str(payload, "created_at"),
            schema_version=payload.get("schema_version", SCHEMA_VERSION),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "user_request": self.user_request,
            "answer_or_diff_summary": self.answer_or_diff_summary,
            "files_changed": list(self.files_changed),
            "evidence_refs": list(self.evidence_refs),
            "run_id": self.run_id,
            "selected_candidate_id": self.selected_candidate_id,
            "draft_path": self.draft_path,
            "claim_map_path": self.claim_map_path,
            "selected_candidate_path": self.selected_candidate_path,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ExternalCheckReport:
    """Metadata-only external novelty/duplicate-risk check result."""

    query: str
    source: str
    matches: tuple[dict[str, Any], ...] = ()
    duplicate_risk: str = "unknown"
    novelty_notes: tuple[str, ...] = ()
    checked_at: str = ""
    degraded_reason: str | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_schema_version(self.schema_version)
        if not isinstance(self.query, str) or not self.query.strip():
            raise SchemaValidationError("query must be a non-empty string")
        if not isinstance(self.source, str) or not self.source.strip():
            raise SchemaValidationError("source must be a non-empty string")
        if self.duplicate_risk not in {"unknown", "low", "medium", "high"}:
            raise SchemaValidationError("duplicate_risk must be unknown, low, medium, or high")
        object.__setattr__(self, "novelty_notes", _normalize_str_tuple(self.novelty_notes, key="novelty_notes"))
        if not isinstance(self.checked_at, str) or not self.checked_at.strip():
            raise SchemaValidationError("checked_at must be a non-empty string")
        if self.degraded_reason is not None and (
            not isinstance(self.degraded_reason, str) or not self.degraded_reason.strip()
        ):
            raise SchemaValidationError("degraded_reason must be a non-empty string when provided")
        normalized_matches: list[dict[str, Any]] = []
        for match in self.matches:
            if not isinstance(match, dict):
                raise SchemaValidationError("matches must contain objects")
            normalized_matches.append(dict(match))
        object.__setattr__(self, "matches", tuple(normalized_matches))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExternalCheckReport":
        if not isinstance(payload, dict):
            raise SchemaValidationError("external check report must be an object")
        return cls(
            query=_required_str(payload, "query"),
            source=_required_str(payload, "source"),
            matches=tuple(payload.get("matches", ())),
            duplicate_risk=_optional_str(payload, "duplicate_risk") or "unknown",
            novelty_notes=tuple(_optional_str_list(payload, "novelty_notes")),
            checked_at=_required_str(payload, "checked_at"),
            degraded_reason=_optional_str(payload, "degraded_reason"),
            schema_version=payload.get("schema_version", SCHEMA_VERSION),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "source": self.source,
            "matches": [dict(match) for match in self.matches],
            "duplicate_risk": self.duplicate_risk,
            "novelty_notes": list(self.novelty_notes),
            "checked_at": self.checked_at,
            "degraded_reason": self.degraded_reason,
        }


def _bounded_score(value: Any, *, key: str) -> float:
    if not isinstance(value, (int, float)):
        raise SchemaValidationError(f"{key} must be numeric")
    return min(1.0, max(0.0, float(value)))


def _parse_arxiv_url(value: str) -> str:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in _ARXIV_HOSTS:
        raise SchemaValidationError("URL must point to arxiv.org")

    path = parsed.path.strip("/")
    if path.startswith("abs/"):
        return path.removeprefix("abs/")
    if path.startswith("pdf/"):
        return path.removeprefix("pdf/")
    raise SchemaValidationError("arXiv URL must use /abs/ or /pdf/")


def _strip_arxiv_prefix(value: str) -> str:
    if value.lower().startswith("arxiv:"):
        return value.split(":", 1)[1].strip()
    return value


def _strip_pdf_suffix(value: str) -> str:
    if value.lower().endswith(".pdf"):
        return value[:-4]
    return value


def _validate_arxiv_id(value: str) -> None:
    if _NEW_ID_RE.fullmatch(value) or _OLD_ID_RE.fullmatch(value):
        return
    raise SchemaValidationError(f"invalid arXiv identifier: {value}")


def _validate_schema_version(value: Any) -> None:
    if value != SCHEMA_VERSION:
        raise SchemaValidationError(f"schema_version must be {SCHEMA_VERSION}")


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{key} must be a non-empty string")
    return value


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SchemaValidationError(f"{key} must be a string when provided")
    return value


def _optional_dict(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SchemaValidationError(f"{key} must be an object when provided")
    return dict(value)


def _optional_str_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise SchemaValidationError(f"{key} must be a list when provided")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise SchemaValidationError(f"{key} items must be strings")
        result.append(item)
    return result


def _normalize_str_tuple(values: Any, *, key: str) -> tuple[str, ...]:
    try:
        materialized = tuple(values)
    except TypeError as exc:
        raise SchemaValidationError(f"{key} must be iterable") from exc
    for item in materialized:
        if not isinstance(item, str):
            raise SchemaValidationError(f"{key} items must be strings")
    return materialized


def _looks_like_url(value: str) -> bool:
    parsed = urlsplit(value)
    return bool(parsed.scheme and parsed.netloc)
