from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Constraints:
    compute_budget: str = ""
    data_availability: str = ""
    timeline: str = ""
    team_skills: str = ""

    def is_empty(self) -> bool:
        return not any(
            [self.compute_budget, self.data_availability, self.timeline, self.team_skills]
        )

    def to_text(self) -> str:
        if self.is_empty():
            return "(제약 조건이 제공되지 않음)"
        parts = []
        if self.compute_budget:
            parts.append(f"Compute budget: {self.compute_budget}")
        if self.data_availability:
            parts.append(f"Data availability: {self.data_availability}")
        if self.timeline:
            parts.append(f"Timeline: {self.timeline}")
        if self.team_skills:
            parts.append(f"Team skills: {self.team_skills}")
        return "\n".join(parts)

    @staticmethod
    def from_dict(data: dict | None) -> "Constraints":
        data = data or {}
        return Constraints(
            compute_budget=data.get("compute_budget", ""),
            data_availability=data.get("data_availability", ""),
            timeline=data.get("timeline", ""),
            team_skills=data.get("team_skills", ""),
        )


@dataclass(slots=True)
class ResearchIdea:
    """README.md 5.1절의 아이디어 입력 스키마."""

    title: str
    problem: str
    proposed_method: str
    evaluation_plan: str = ""
    constraints: Constraints = field(default_factory=Constraints)

    def to_text(self) -> str:
        parts = [
            f"Title: {self.title}",
            f"Problem: {self.problem}",
            f"Proposed method: {self.proposed_method}",
        ]
        if self.evaluation_plan:
            parts.append(f"Evaluation plan: {self.evaluation_plan}")
        return "\n".join(parts)

    @staticmethod
    def from_dict(data: dict) -> "ResearchIdea":
        return ResearchIdea(
            title=data["title"],
            problem=data["problem"],
            proposed_method=data["proposed_method"],
            evaluation_plan=data.get("evaluation_plan", ""),
            constraints=Constraints.from_dict(data.get("constraints")),
        )
