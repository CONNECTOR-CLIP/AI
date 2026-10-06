from __future__ import annotations

from datetime import date, datetime
from typing import Any


def _parse_cutoff(cutoff_date: str | None) -> date | None:
    if not cutoff_date:
        return None
    return datetime.strptime(cutoff_date, "%Y-%m-%d").date()


def _paper_date(paper: dict[str, Any]) -> date | None:
    pub_date = paper.get("publicationDate")
    if pub_date:
        try:
            return datetime.strptime(str(pub_date)[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    year = paper.get("year")
    if year:
        try:
            # 월/일 정보가 없으면 그 해 마지막 날로 본다: cutoff_date가 그 해 안에 있어도
            # "같은 해에 나온 논문일 수 있다"는 쪽으로 보수적으로 걸러낸다(시간 누출 방지 우선).
            return date(int(year), 12, 31)
        except (TypeError, ValueError):
            pass
    return None


def filter_by_date(
    papers: list[dict[str, Any]], cutoff_date: str | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """cutoff_date 이후에 출판된 후보를 제거한다(README 4.2절: "본 하네스의 추가 설계").

    날짜를 알 수 없는 논문은 걸러낼 근거가 없으므로 유지한다(과도한 제거보다 안전).
    반환값: (kept, dropped_because_after_cutoff)
    """
    cutoff = _parse_cutoff(cutoff_date)
    if cutoff is None:
        return list(papers), []

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for paper in papers:
        paper_date = _paper_date(paper)
        if paper_date is None or paper_date <= cutoff:
            kept.append(paper)
        else:
            dropped.append(paper)
    return kept, dropped
