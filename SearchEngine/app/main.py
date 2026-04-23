"""
FastAPI 애플리케이션 진입점.

실행 방법:
    cd e:/SearchEngine
    uvicorn app.main:app --reload --port 8000

Swagger UI:  http://localhost:8000/docs
ReDoc:       http://localhost:8000/redoc
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.search import router as search_router

# ─────────────────────────────────────────────
# 앱 생성
# ─────────────────────────────────────────────

app = FastAPI(
    title="arXiv 논문 검색엔진",
    description=(
        "arXiv에서 수집한 92만 건의 논문을 BM25 기반으로 검색합니다.\n\n"
        "## 검색 모드\n"
        "- `all`: 제목 + 초록 + 저자 동시 검색 (제목 가중치 3배)\n"
        "- `title`: 제목만 검색\n"
        "- `author`: 저자명만 검색\n"
        "- `abstract`: 초록만 검색\n\n"
        "## 필터\n"
        "- `categories`: arXiv 카테고리 (cs.AI, cs.LG, cs.CL 등)\n"
        "- `year_from` / `year_to`: 출판 연도 범위\n\n"
        "## 정렬\n"
        "- `relevance`: BM25 관련도 순 (기본값)\n"
        "- `latest`: 출판일 최신 순"
    ),
    version="1.0.0",
)

# ─────────────────────────────────────────────
# CORS 설정 — 프론트엔드 어느 주소에서든 호출 가능하도록
# ─────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # 프로덕션에서는 실제 도메인으로 교체
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────
# 라우터 등록
# ─────────────────────────────────────────────

app.include_router(search_router, tags=["search"])


# ─────────────────────────────────────────────
# 루트
# ─────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def root():
    return {"message": "arXiv 논문 검색엔진 API", "docs": "/docs"}
