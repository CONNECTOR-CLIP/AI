# 퓨쳐워크(연구 공백) 분석 agent

from research_agent.inno.tools.file_surfer_tool import with_env as with_env_file
from research_agent.inno.tools.file_surfer_tool import (
    open_local_file,
    page_up_markdown,
    page_down_markdown,
    find_on_page_ctrl_f,
    find_next,
    question_answer_on_whole_page,
)
from research_agent.inno.environment.markdown_browser import RequestsMarkdownBrowser
from research_agent.inno.types import Agent
from inspect import signature


def get_paper_scan_agent(model: str, **kwargs):
    file_env: RequestsMarkdownBrowser = kwargs.get("file_env", None)
    assert file_env is not None, "file_env is required"

    def instructions(context_variables):
        return f"""\
You are a `Paper Scanner Agent`. Your job is to scan ONE paper and extract research-gap-relevant information.

WORKFLOW:
1. Call `open_local_file` with the paper path provided in the task.

2. Navigate past the LaTeX preamble:
   Step A: Call find_on_page_ctrl_f(search_string="\\\\begin{{abstract}}")
   Step B: If not found, call find_on_page_ctrl_f(search_string="\\\\section{{Introduction}}")
   Step C: If both fail, call page_down_markdown until you see actual sentences

3. After reaching content, ask these 6 questions using question_answer_on_whole_page (one at a time):
   - "What is the main claim and central contribution of this paper?"
   - "What specific research problems or challenges does the introduction identify?"
   - "What method or solution does this paper propose to address the problem?"
   - "What limitations or weaknesses does this paper explicitly acknowledge?"
   - "Does this paper mention future work or open problems? List them precisely."
   - "What aspects of the methodology or experiments appear limited or not generalizable?"

4. Compile all 6 answers into the OUTPUT FORMAT below and return it as your final text response.

OUTPUT FORMAT:
=== PAPER SUMMARY: [exact paper title] ===
**Main Claim**: [answer to Q1]
**Problem Stated**: [answer to Q2]
**Proposed Solution**: [answer to Q3]
**Limitations**: [answer to Q4]
**Future Work Mentioned**: [answer to Q5]
**Unresolved Issues**: [answer to Q6]
=== END SUMMARY ===

RULES:
- question_answer_on_whole_page does NOT take a path argument
- Keep each field to 2-5 sentences
- Always return the structured summary as your final text response

After asking all 6 questions, if future work information seems incomplete,
call find_on_page_ctrl_f(search_string="\\conclusion") or 
find_on_page_ctrl_f(search_string="\\future") to find the conclusion section,
then call question_answer_on_whole_page again for Q5 and Q6.
"""

    tool_list = [
        open_local_file,
        page_up_markdown,
        page_down_markdown,
        find_on_page_ctrl_f,
        find_next,
        question_answer_on_whole_page,
    ]
    tool_list = [
        with_env_file(file_env)(tool) if "env" in signature(tool).parameters else tool
        for tool in tool_list
    ]

    return Agent(
        name="Paper Scanner Agent",
        model=model,
        instructions=instructions,
        functions=tool_list,
        tool_choice="auto",
        parallel_tool_calls=False,
    )
