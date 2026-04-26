"""
SQLAlchemy 엔진 및 세션 팩토리 구성.
SQLite를 원본 데이터 저장소로 사용한다.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.core.config import settings

# SQLite URL: 절대경로 또는 상대경로 모두 지원
DATABASE_URL = f"sqlite:///{settings.sqlite_db_path}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite 전용 옵션
    echo=(settings.app_env == "development"),   # 개발 환경에서는 SQL 로그 출력
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """모든 ORM 모델의 베이스 클래스"""
    pass


def get_db():
    """FastAPI 의존성 주입용 DB 세션 제너레이터"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
