import argparse
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*args, **kwargs):
        return False

import global_state


DISABLED_MODE_MESSAGE = "This mode is intentionally disabled for the narrowed future-work pipeline."
NARROWED_MODE = "Narrowed Future Work Pipeline"


def init_ai_researcher():
    a = 1


def get_args_research():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance_path", type=str, default="benchmark/gnn.json")
    parser.add_argument('--container_name', type=str, default='paper_eval')
    parser.add_argument("--task_level", type=str, default="task1")
    parser.add_argument("--model", type=str, default="gpt-4o-2024-08-06")
    parser.add_argument("--workplace_name", type=str, default="workplace")
    parser.add_argument("--cache_path", type=str, default="cache")
    parser.add_argument("--port", type=int, default=12345)
    parser.add_argument("--max_iter_times", type=int, default=0)
    parser.add_argument("--category", type=str, default="recommendation")
    args = parser.parse_args()
    return args


def get_args_paper():
    parser = argparse.ArgumentParser()
    parser.add_argument("--research_field", type=str, default="vq")
    parser.add_argument("--instance_id", type=str, default="rotation_vq")
    args = parser.parse_args()
    return args


def _resolve_db_path() -> str:
    return os.getenv("SEARCHENGINE_SQLITE_DB_PATH") or os.getenv("SQLITE_DB_PATH") or "/mnt/d/arxiv_cs_ai.db"


def _run_narrowed_futurework_pipeline(query: str, reference: str | None, db_path: str):
    from integration.run_futurework_pipeline import run_pipeline_from_mode

    repo_root = Path(__file__).resolve().parent
    return run_pipeline_from_mode(query=query, reference=reference, db_path=db_path, repo_root=str(repo_root))


def main_ai_researcher(input, reference, mode):
    load_dotenv()

    if mode in {"Detailed Idea Description", "Reference-Based Ideation", "Paper Generation Agent"}:
        # Legacy modes are intentionally blurred/disabled for the narrowed workflow.
        raise RuntimeError(DISABLED_MODE_MESSAGE)

    if mode == NARROWED_MODE:
        if global_state.INIT_FLAG is False:
            global_state.INIT_FLAG = True
            try:
                return _run_narrowed_futurework_pipeline(query=str(input), reference=reference, db_path=_resolve_db_path())
            finally:
                global_state.INIT_FLAG = False
        return None

    raise ValueError(f"Unsupported mode: {mode}")
