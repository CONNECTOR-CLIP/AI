# 전체 흐름 오케스트레이션

from typing import List, Union
from tqdm import tqdm

from research_agent.inno.workflow.flowcache import FlowModule, ToolModule, AgentModule
from research_agent.inno.tools.inno_tools.code_search import search_github_repos
from research_agent.inno.tools.arxiv_source import download_arxiv_source_by_title
from research_agent.inno.environment.markdown_browser import RequestsMarkdownBrowser
from research_agent.inno.logger import MetaChainLogger
from research_agent.constant import CHEEP_MODEL

from research_agent.future_work.paper_scan_agent import get_paper_scan_agent
from research_agent.future_work.future_work_agent import get_future_work_agent
from research_agent.agents.inno_agent.idea_agent import get_idea_agent

import re
import json


def github_search(metadata: dict) -> str:
    github_result = ""
    for source_paper in tqdm(metadata["source_papers"]):
        github_result += search_github_repos(metadata, source_paper["reference"], 10)
        github_result += "*" * 30 + "\n"
    return github_result


class FutureWorkFlow(FlowModule):
    def __init__(
        self,
        cache_path: str,
        log_path: Union[str, None, MetaChainLogger] = None,
        model: str = "gpt-4o-2024-08-06",
        file_env: RequestsMarkdownBrowser = None,
    ):
        super().__init__(cache_path, log_path, model)
        self.download_paper = ToolModule(download_arxiv_source_by_title, cache_path)
        self.git_search = ToolModule(github_search, cache_path)
        # scan_agent: 논문 핵심 섹션 빠른 추출 (CHEEP_MODEL 사용 — 단순 추출 작업)
        self.scan_agent = AgentModule(
            get_paper_scan_agent(model=CHEEP_MODEL, file_env=file_env),
            self.client,
            cache_path,
        )
        # future_work_agent: 연구 공백 분석 (고성능 모델 사용)
        self.future_work_agent = AgentModule(
            get_future_work_agent(model=model),
            self.client,
            cache_path,
        )
        # idea_agent: 가장 유망한 공백 선택 후 논문 초안 생성
        self.idea_agent = AgentModule(
            get_idea_agent(model=model, file_env=file_env),
            self.client,
            cache_path,
        )

    async def forward(
        self,
        paper_titles: List[str],
        date_limit: str,
        local_root: str,
        workplace_name: str,
        paper_ids: dict = None,
        *args,
        **kwargs,
    ):
        context_variables = {
            "working_dir": workplace_name,
            "date_limit": date_limit,
            "paper_list": paper_titles,
            "notes": [],
        }

        # [1단계] 논문 다운로드
        download_res = self.download_paper({
            "paper_list": paper_titles,
            "local_root": local_root,
            "workplace_name": workplace_name,
            "paper_ids": paper_ids or {},
        })

        # [2단계] 논문별 개별 스캔
        # download_res에서 각 논문의 실제 경로 추출
        paper_paths = re.findall(r'The paper is downloaded to path:\s*(\S+\.tex)', download_res)

        all_summaries = []
        for i, title in enumerate(paper_titles):
            path_hint = paper_paths[i] if i < len(paper_paths) else f"{workplace_name}/papers/"

            scan_query = (
                f'Scan this ONE paper:\n'
                f'- Title: "{title}"\n'
                f'- Path: {path_hint}\n\n'
                f'Open the file, navigate past the LaTeX preamble, '
                f'ask all 6 questions, and return the structured summary.'
            )

            scan_messages = [{"role": "user", "content": scan_query}]
            scan_result_msgs, context_variables = await self.scan_agent(
                scan_messages, context_variables
            )

            # content가 있는 마지막 메시지를 역방향 탐색 (마지막이 null일 수 있음)
            summary = next(
                (msg["content"] for msg in reversed(scan_result_msgs) if msg.get("content")),
                None
            )
            all_summaries.append(
                summary if summary
                else f"=== PAPER SUMMARY: {title} ===\nFAILED TO EXTRACT\n=== END SUMMARY ==="
            )

        paper_summaries = "\n\n".join(all_summaries)

        if not paper_summaries.strip():
            raise ValueError("Paper Scanner Agent가 모든 논문 요약에 실패했습니다.")

        # [3단계] 구조화된 요약 → 연구 공백 5개 도출
        fw_query = f"""\
Here are structured summaries of {len(paper_titles)} research papers:

{paper_summaries}

Based only on these summaries, identify EXACTLY 5 future work proposals (연구 공백).
Use the required output format with the Korean field names.
Distribute proposals across different papers — do not focus on only one paper.
"""
        fw_messages = [{"role": "user", "content": fw_query}]
        fw_result_msgs, context_variables = await self.future_work_agent(
            fw_messages, context_variables
        )
        draft_future_works = fw_result_msgs[-1]["content"]


        # [3.5단계] arxiv novelty check — abstract만 검색, 전체 읽기 없음
        from research_agent.future_work.arxiv_novelty_check import format_novelty_check_input
        
        # 모델이 ```json ... ``` 코드 펜스로 감싸는 경우 제거
        draft_text = draft_future_works.strip()
        if "```" in draft_text:
            draft_text = draft_text.split("```")[1]      # ``` 와 ``` 사이 내용
            if "\n" in draft_text:
                draft_text = draft_text.split("\n", 1)[1]  # 첫 줄(언어 식별자) 제거
            draft_text = draft_text.strip()
            
        # JSON 출력에서 각 제안의 텍스트를 추출하여 키워드 검색에 사용
        try:
            draft_json = json.loads(draft_text)
            draft_proposals = [
                f"{p['background_and_gap']}\n\n{p['proposed_direction']}"
                for p in draft_json["future_work_proposals"]
            ]
        except (json.JSONDecodeError, KeyError):
            draft_proposals = [draft_future_works]

        arxiv_novelty_report = format_novelty_check_input(
                future_works=draft_proposals,
                model=CHEEP_MODEL,   # 키워드 추출은 저렴한 모델
        )


        # [4단계] GitHub 검색 — novelty 검증 (토큰 없으면 건너뜀)
        from research_agent.constant import GITHUB_AI_TOKEN
        if GITHUB_AI_TOKEN:
            try:
                metadata = {
                    "source_papers": [{"reference": t} for t in paper_titles],
                    "date_limit": date_limit,
                }
                github_result = self.git_search({"metadata": metadata})
            except Exception:
                github_result = "GitHub search skipped (API error)."
        else:
            github_result = "GitHub search skipped (no token configured)."

        # [5단계] GitHub 결과 반영 → 최종 정제
        refine_query = f"""\
You previously generated 5 future work proposals in JSON format:
{draft_future_works}

[Arxiv Novelty Check Results]
These are title + abstract only from arxiv search — NOT full papers.
Use these to judge whether each proposal is already being researched:
{arxiv_novelty_report}

[GitHub Search Results]
{github_result}


For each proposal, apply these rules STRICTLY:

NOVEL → Keep as-is. Set "novelty_assessment": "CONFIRMED NOVEL", "novelty_note": brief reason.

PARTIAL → Refine background_and_gap and proposed_direction to a more specific unexplored angle.
           Set "novelty_assessment": "REFINED", "novelty_note": explain the differentiation.

ALREADY DONE → DISCARD this proposal entirely.
               Using ONLY the paper summaries below, find a completely NEW research gap
               not covered by the other 4 proposals. Replace all fields with the new proposal.
               Set "novelty_assessment": "REGENERATED", "novelty_note": explain why original

Paper summaries to use for regeneration:
{paper_summaries}

Output ONLY a valid JSON object with exactly 5 proposals, adding "novelty_assessment" and
"novelty_note" fields to each entry. Keep all other fields from the original schema.
No markdown, no code fences — raw JSON only.

"""
        refine_messages = [{"role": "user", "content": refine_query}]
        final_msgs, context_variables = await self.future_work_agent(
            refine_messages, context_variables, iter_times="refine"
        )
        result = final_msgs[-1]["content"]
        print(result)
        return result

    async def generate_paper_draft(
        self,
        proposal: dict,
        workplace_name: str,
    ) -> str:
        """사용자가 선택한 제안 하나로 논문 초안 생성."""
        context_variables = {"working_dir": workplace_name, "notes": []}
        idea_query = f"""\
Generate a comprehensive paper draft outline for the following research proposal.
Use the paper files at {workplace_name}/papers/ to ground your writing.

Proposal:
- Background & Gap: {proposal.get('background_and_gap', '')}
- Proposed Direction: {proposal.get('proposed_direction', '')}
- Expected Contribution: {proposal.get('expected_contribution', '')}
- Reference Papers: {', '.join(proposal.get('reference_papers', []))}

Include:
1. Suggested paper title
2. Abstract (150-200 words)
3. Introduction: motivation, problem statement, key contributions
4. Related Work: key research areas to survey
5. Proposed Methodology: technical approach with details
6. Experiments & Evaluation: metrics, datasets, baselines
7. Expected Contributions
"""
        idea_messages = [{"role": "user", "content": idea_query}]
        idea_msgs, context_variables = await self.idea_agent(
            idea_messages, context_variables
        )
        return next(
            (msg["content"] for msg in reversed(idea_msgs) if msg.get("content")),
            ""
        )
