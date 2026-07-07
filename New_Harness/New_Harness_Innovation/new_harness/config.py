from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HarnessConfig:
    """Centralized deterministic thresholds and loop defaults for G004."""

    candidates_per_round: int = 3
    max_candidate_rounds: int = 2
    evidence_pass_threshold: float = 0.65
    feasibility_pass_threshold: float = 0.65
    near_pass_margin: float = 0.15
    verification_depth: str = "selected_only"
    external_check_top_k: int = 2
    external_search_max_results: int = 5
    external_request_timeout_seconds: float = 10.0
    external_request_min_interval_seconds: float = 3.0

    def __post_init__(self) -> None:
        for field_name in (
            "candidates_per_round",
            "max_candidate_rounds",
            "external_check_top_k",
            "external_search_max_results",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        for field_name in (
            "evidence_pass_threshold",
            "feasibility_pass_threshold",
            "near_pass_margin",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, (int, float)):
                raise ValueError(f"{field_name} must be numeric")
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{field_name} must be between 0.0 and 1.0")
        for field_name in (
            "external_request_timeout_seconds",
            "external_request_min_interval_seconds",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, (int, float)):
                raise ValueError(f"{field_name} must be numeric")
            if float(value) <= 0.0:
                raise ValueError(f"{field_name} must be greater than 0.0")
        if self.verification_depth not in {"selected_only", "light_external", "strong_external"}:
            raise ValueError(
                "verification_depth must be selected_only, light_external, or strong_external"
            )

    def is_near_pass(
        self,
        *,
        evidence_score: float,
        feasibility_score: float,
        novelty_risk: str,
    ) -> bool:
        evidence_pass = evidence_score >= self.evidence_pass_threshold
        feasibility_pass = feasibility_score >= self.feasibility_pass_threshold
        evidence_within_margin = evidence_score >= max(0.0, self.evidence_pass_threshold - self.near_pass_margin)
        feasibility_within_margin = feasibility_score >= max(0.0, self.feasibility_pass_threshold - self.near_pass_margin)

        if evidence_pass and feasibility_pass:
            return novelty_risk == "unknown"
        if evidence_pass and not feasibility_pass:
            return feasibility_within_margin
        if feasibility_pass and not evidence_pass:
            return evidence_within_margin
        return False
