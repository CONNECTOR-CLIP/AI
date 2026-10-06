from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class SeedPaper:
    title: str = ""
    doi: str = ""
    arxiv_id: str = ""
    # Backward compatibility for existing input JSON. New local-DB inputs should use arxiv_id.
    semantic_scholar_id: str = ""


@dataclass(slots=True)
class ResearchIdea:
    """README.md 4.1절의 아이디어 입력 스키마."""

    title: str
    problem: str
    proposed_method: str
    motivation: str = ""
    evaluation_plan: str = ""
    application_domain: str = ""
    seed_papers: list[SeedPaper] = field(default_factory=list)
    cutoff_date: str | None = None  # "YYYY-MM-DD"

    def to_text(self) -> str:
        """idea_novelty_checker는 아이디어를 하나의 자유 텍스트 문자열로만 받는다
        (noveltychecker/models/idea_novelty_checker/prompts.py의 `<IDEA> {idea} </IDEA>` 참고).
        구조화된 필드를 라벨을 붙여 순서대로 나열해, 원본이 기대하는 하나의 텍스트로 직렬화한다.
        """
        parts = [
            f"Title: {self.title}",
            f"Problem and purpose: {self.problem}",
            f"Proposed mechanism: {self.proposed_method}",
        ]
        if self.motivation:
            parts.append(f"Motivation: {self.motivation}")
        if self.evaluation_plan:
            parts.append(f"Evaluation: {self.evaluation_plan}")
        if self.application_domain:
            parts.append(f"Application domain: {self.application_domain}")
        return "\n".join(parts)

    @property
    def seed_paper_ids(self) -> list[str]:
        return [p.arxiv_id or p.semantic_scholar_id for p in self.seed_papers if p.arxiv_id or p.semantic_scholar_id]

    @staticmethod
    def from_dict(data: dict) -> "ResearchIdea":
        seed_papers = [
            SeedPaper(
                title=p.get("title", ""),
                doi=p.get("doi", ""),
                arxiv_id=p.get("arxiv_id", ""),
                semantic_scholar_id=p.get("semantic_scholar_id", ""),
            )
            for p in data.get("seed_papers", [])
        ]
        return ResearchIdea(
            title=data["title"],
            problem=data["problem"],
            proposed_method=data["proposed_method"],
            motivation=data.get("motivation", ""),
            evaluation_plan=data.get("evaluation_plan", ""),
            application_domain=data.get("application_domain", ""),
            seed_papers=seed_papers,
            cutoff_date=data.get("cutoff_date"),
        )
