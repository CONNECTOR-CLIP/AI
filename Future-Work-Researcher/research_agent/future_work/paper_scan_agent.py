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
        paper_list = context_variables.get("paper_list", [])
        paper_paths = "\n".join(f"- {p}" for p in paper_list)
        return f"""\
You are a `Paper Scanner Agent`. Your job is to rapidly extract only the research-gap-relevant information from each paper.

Papers are located in: `{file_env.docker_workplace}/papers/`

Papers to scan:
{paper_paths}

WORKFLOW — for EACH paper:
1. Call `open_local_file` with the paper path to open it.
   Example: open_local_file(path="workplace/papers/paper_title.tex")
   
2. After opening, call `question_answer_on_whole_page` with ONLY a `question` argument.
   IMPORTANT — .tex files begin with a LaTeX preamble (package imports, \\newcommand, etc.)
   The actual paper content starts much later. You MUST navigate past the preamble first:
   
   Step A: Call find_on_page_ctrl_f(search_string="\\\\begin{{abstract}}")
           → This jumps directly to the abstract section
   Step B: If Step A fails (not found), call find_on_page_ctrl_f(search_string="\\\\section{{Introduction}}")
   Step C: If both fail, call page_down_markdown repeatedly until you see actual sentences
           (not \\\\usepackage or \\\\newcommand lines)
   
   Only AFTER reaching actual content, call question_answer_on_whole_page.
   The function reads from the current position automatically — do NOT pass a path.
   
   Ask these 6 questions one at a time:
   - question_answer_on_whole_page(question="What is the main claim and central contribution of this paper?")
   - question_answer_on_whole_page(question="What specific research problems or challenges does the introduction identify?")
   - question_answer_on_whole_page(question="What method or solution does this paper propose to address the problem?")
   - question_answer_on_whole_page(question="What limitations or weaknesses does this paper explicitly acknowledge?")
   - question_answer_on_whole_page(question="Does this paper mention future work or open problems? List them precisely.")
   - question_answer_on_whole_page(question="What aspects of the methodology or experiments appear limited or not generalizable?")

3. Compile the 6 answers into the structured summary format below.
4. Repeat steps 1-3 for every paper in the list.

OUTPUT FORMAT — repeat for each paper:
=== PAPER SUMMARY: [exact paper title] ===
**Main Claim**: [answer to Q1]
**Problem Stated**: [answer to Q2]
**Proposed Solution**: [answer to Q3]
**Limitations**: [answer to Q4]
**Future Work Mentioned**: [answer to Q5]
**Unresolved Issues**: [answer to Q6]
=== END SUMMARY ===

RULES:
- .tex files start with LaTeX preamble — always navigate past it with find_on_page_ctrl_f BEFORE calling question_answer_on_whole_page
- question_answer_on_whole_page does NOT take a path argument — it reads from the current position automatically
- Keep each field to 2-5 sentences max
- Complete ALL papers before finishing
- If a paper cannot be found, write "NOT FOUND" for that paper
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