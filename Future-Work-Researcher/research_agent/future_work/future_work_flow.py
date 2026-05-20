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

    async def forward(
        self,
        paper_titles: List[str],
        date_limit: str,
        local_root: str,
        workplace_name: str,
        *args,
        **kwargs,
    ):
        references = "\n".join(f"- {t}" for t in paper_titles)

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
        })

        # [2단계] 논문 핵심 섹션 스캔 (전체 읽기 대신 targeted questions)
        # → 각 논문당 question_answer_on_whole_page 6회 호출로 끝냄
        scan_query = f"""\
I have downloaded the following {len(paper_titles)} papers in TeX format:
{download_res}

Paper list:
{references}

For EACH paper, open it and use question_answer_on_whole_page to extract:
- Main claim, problem stated, proposed solution, limitations, future work mentioned, unresolved issues.

Return structured summaries for ALL papers using the required format.
"""
        scan_messages = [{"role": "user", "content": scan_query}]
        scan_result_msgs, context_variables = await self.scan_agent(
            scan_messages, context_variables
        )
        paper_summaries = scan_result_msgs[-1]["content"]

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
        import json
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


        # [4단계] GitHub 검색 — novelty 검증
        metadata = {
            "source_papers": [{"reference": t} for t in paper_titles],
            "date_limit": date_limit,
        }
        github_result = self.git_search({"metadata": metadata})

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

---

For each proposal, determine its novelty status using the criteria below,
then apply the corresponding action.

JUDGMENT CRITERIA (apply in order):

  NOVEL     — 0–1 related papers found in arxiv results,
               OR the papers found use fundamentally different methods
               from the proposal's core approach.
               → Keep proposal as-is.

  PARTIAL   — 2–4 related papers found, but they only address
               part of the proposal's core idea; key aspects remain unexplored.
               → Refine background_and_gap and proposed_direction to focus
                 on the unexplored angle. Do NOT discard.
               ※ When in doubt between PARTIAL and ALREADY DONE, choose PARTIAL.

  ALREADY DONE — 5 or more papers found AND they directly address
                  the same core method as the proposal.
                  → Discard entirely. Use ONLY the paper summaries below
                    to identify a completely new research gap not covered
                    by the remaining 4 proposals. Replace all fields.
               ※ Use this judgment sparingly — only when overlap is unmistakable.

---

ACTION per status:

NOVEL       → Set "novelty_assessment": "CONFIRMED NOVEL"
              Set "novelty_note": brief reason why it is novel.

PARTIAL     → Refine background_and_gap and proposed_direction.
              Set "novelty_assessment": "REFINED"
              Set "novelty_note": explain what was differentiated and why.

ALREADY DONE → Replace the entire proposal with a new one.
               Set "novelty_assessment": "REGENERATED"
               Set "novelty_note": explain why original was discarded
               and how the new topic was derived from the paper summaries.

---

Paper summaries to use for regeneration (ALREADY DONE cases only):
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
