"""
arXiv 논문 메타데이터 SQLite ORM 모델.
실제 arXiv OAI-PMH 수집 스키마 기준 (e:/arxiv_cs_ai.db).

테이블 구조:
- papers: arxiv_id, title, abstract, categories, created_date, ...
- authors: id, arxiv_id, position, keyname, forenames
"""
from sqlalchemy import Column, String, Text, Integer, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base


class Author(Base):
    """저자 테이블 — papers.arxiv_id와 FK 관계"""
    __tablename__ = "authors"

    id = Column(Integer, primary_key=True)
    arxiv_id = Column(String(64), ForeignKey("papers.arxiv_id"), nullable=False, index=True)
    position = Column(Integer, nullable=True)   # 저자 순서
    keyname = Column(String(256), nullable=True)    # 성 (예: "LeCun")
    forenames = Column(String(256), nullable=True)  # 이름 (예: "Yann")

    @property
    def full_name(self) -> str:
        parts = []
        if self.forenames:
            parts.append(self.forenames)
        if self.keyname:
            parts.append(self.keyname)
        return " ".join(parts)


class Paper(Base):
    """arXiv 논문 메타데이터 테이블"""
    __tablename__ = "papers"

    arxiv_id = Column(String(64), primary_key=True, nullable=False, index=True)
    title = Column(Text, nullable=True)
    abstract = Column(Text, nullable=True)

    # 카테고리: 공백 구분 문자열 (예: "cs.AI cs.LG stat.ML")
    categories = Column(Text, nullable=True)
    primary_category = Column(String(64), nullable=True)

    # 출판일: TEXT "YYYY-MM-DD"
    created_date = Column(String(32), nullable=True)
    updated_date = Column(String(32), nullable=True)

    is_deleted = Column(Integer, default=0)

    # 저자 목록 (relationship)
    author_list = relationship(
        "Author",
        foreign_keys=[Author.arxiv_id],
        primaryjoin="Paper.arxiv_id == Author.arxiv_id",
        order_by=Author.position,
        lazy="select",
    )

    def __repr__(self) -> str:
        title_preview = (self.title or "")[:40]
        return f"<Paper arxiv_id={self.arxiv_id!r} title={title_preview!r}>"
