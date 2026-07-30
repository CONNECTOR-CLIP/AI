# 1단계(목표 추론 및 커버리지 진단) agent 단독 테스트 — 논문 1편을 넣어서 실제로 어떤 JSON이 나오는지 확인용.
# future_work_flow.py에는 아직 배선하지 않았으므로, 이 스크립트로 goal_decomposition_agent +
# goal_decomposition_validation(정적 검증 + 재시도)만 떼어서 실행한다.
#
# 실행 예:
#   python test_goal_decomposition.py --paper "Attention Is All You Need"
#
# 주의: 실제 LLM API를 호출하므로 비용이 발생하고, arxiv에서 논문을 다운로드하므로 네트워크가 필요하다.

import argparse
import asyncio
import os
import re

from dotenv import load_dotenv

from research_agent.inno.core import MetaChain
from research_agent.inno.workflow.flowcache import AgentModule, ToolModule
from research_agent.inno.tools.arxiv_source import download_arxiv_source_by_title
from research_agent.inno.environment.markdown_browser import RequestsMarkdownBrowser

from research_agent.future_work.goal_decomposition_agent import get_goal_decomposition_agent
from research_agent.future_work.goal_decomposition_validation import run_goal_decomposition_with_retry

load_dotenv()


def get_args():
    parser = argparse.ArgumentParser(description="1단계(목표 추론 및 커버리지 진단) agent 단독 테스트")
    parser.add_argument("--paper", type=str, required=True, help="논문 제목 (arxiv에서 찾을 수 있는 정확한 제목)")
    parser.add_argument("--model", type=str, default=os.environ.get("COMPLETION_MODEL", "gpt-4o-2024-08-06"))
    parser.add_argument("--workplace_name", type=str, default="workplace_test")
    parser.add_argument("--cache_path", type=str, default="cache_goal_decomposition_test")
    parser.add_argument("--max_retries", type=int, default=2)
    return parser.parse_args()


async def main():
    args = get_args()

    local_root = os.path.join(os.getcwd(), "workplace_future_work")
    os.makedirs(local_root, exist_ok=True)

    file_env = RequestsMarkdownBrowser(
        viewport_size=1024 * 4,
        local_root=local_root,
        workplace_name=args.workplace_name,
        downloads_folder=os.path.join(local_root, args.workplace_name, "downloads"),
    )

    # [1] 논문 다운로드 — 기존 arxiv_source.py 그대로 재사용
    download_paper = ToolModule(download_arxiv_source_by_title, args.cache_path)
    download_res = download_paper({
        "paper_list": [args.paper],
        "local_root": local_root,
        "workplace_name": args.workplace_name,
    })
    paper_paths = re.findall(r'The paper is downloaded to path:\s*(\S+\.tex)', download_res)
    if not paper_paths:
        raise RuntimeError(f"논문을 다운로드하지 못했습니다:\n{download_res}")
    path_hint = paper_paths[0]
    print(f"[다운로드 완료] {path_hint}\n")

    # [2] 목표분해 agent 준비
    client = MetaChain()
    agent = get_goal_decomposition_agent(model=args.model, file_env=file_env)
    agent_module = AgentModule(agent, client, args.cache_path)

    # [3] 실행 + 정적 검증 + 재시도 (goal_decomposition_validation.py가 전부 담당)
    context_variables = {}
    result, context_variables, error = await run_goal_decomposition_with_retry(
        agent_module=agent_module,
        paper_title=args.paper,
        path_hint=path_hint,
        context_variables=context_variables,
        paper_index=0,
        max_retries=args.max_retries,
    )

    if error:
        print(f"[검증 실패, 재시도 소진] {error}")
        return

    print("[검증 통과]")
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
