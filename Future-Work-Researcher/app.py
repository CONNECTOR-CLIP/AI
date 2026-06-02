"""
FutureWork API 서버

실행 방법:
    cd ~/AI/Future-Work-Researcher
    source ~/AI/venv/bin/activate
    uvicorn app:app --reload --port 8001

Swagger UI: http://localhost:8001/docs
"""
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from dotenv import load_dotenv
from research_agent.future_work.future_work_flow import FutureWorkFlow
from research_agent.inno.environment.markdown_browser import RequestsMarkdownBrowser

load_dotenv()

app = FastAPI(
    title="Future Work Researcher API",
    description="논문 제목을 받아 퓨처워크 아이디어를 추천합니다.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class FutureWorkRequest(BaseModel):
    papers: List[dict]  # Java에서 paper_id, title, abstract로 넘김


@app.get("/", include_in_schema=False)
def root():
    return {"message": "Future Work Researcher API", "docs": "/docs"}


@app.post("/api/gap")
async def run_future_work(request: FutureWorkRequest):
    try:
        # title만 추출
        paper_titles = [p.get("title", p.get("paper_id", "")) for p in request.papers]

        local_root = os.path.join(os.getcwd(), "workplace_future_work")
        os.makedirs(local_root, exist_ok=True)

        file_env = RequestsMarkdownBrowser(
            viewport_size=1024 * 4,
            local_root=local_root,
            workplace_name="workplace",
            downloads_folder=os.path.join(local_root, "workplace", "downloads"),
        )

        flow = FutureWorkFlow(
            cache_path="cache_future_work",
            model=os.environ.get("COMPLETION_MODEL", "openrouter/google/gemini/gemini-2.5-pro"),
            file_env=file_env,
        )

        result = await flow(
            paper_titles=paper_titles,
            date_limit="2010-01-01",
            local_root=local_root,
            workplace_name="workplace",
        )

        return {"gap_content": result}  # Java에서 gap_content로 읽음

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/result")
async def get_result():
    return {}