"""
앱 전체 설정을 pydantic-settings로 관리.
.env 파일 또는 환경 변수에서 자동으로 값을 읽어온다.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # OpenSearch
    opensearch_host: str = "localhost"
    opensearch_port: int = 9200
    opensearch_use_ssl: bool = False
    opensearch_index: str = "arxiv_papers"

    # SQLite
    sqlite_db_path: str = "./data/arxiv.db"

    # App
    app_env: str = "development"


# 싱글톤 인스턴스 — 앱 전체에서 import해서 사용
settings = Settings()
