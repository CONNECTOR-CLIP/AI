# [1단계: 목표 추론 및 커버리지 진단] 출력에 대한 정적 검증 — AI 미사용, 스키마/형식만 확인 (pydantic).
# ("목표분해"라 부르면 A~F가 이미 정해진 고정 목록을 나누는 것처럼 들리는데, 실제로는 그 목록 자체가
# 논문에 없는 걸 모델이 추론(inference)해서 만들어내고, 그걸 기준으로 이 논문의 커버리지를 진단하는
# 작업이라 이름을 바꿨다. 코드 식별자(goal_decomposition_*)는 영어 관용어라 그대로 둔다.)
# 개수 고정 없음: subgoals 배열의 "원소 형태"만 고정하고 "길이"는 논문마다 다르게 허용한다.
# evidence quote/locator는 여기서 검증하지 않는다 — 정확한 원문 인용 grounding은 ②단계의 역할이고,
# ①은 achieved/partially_achieved/not_achieved 판정 + 짧은 rationale까지만 책임진다.

import json
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ValidationError, field_validator

# 1 = "완전히 비어있는 실패"만 걸러내는 진짜 하한. 몇 개가 "적절한" 개수인지는 논문마다 다르고
# 정적으로 판단 불가능한 영역이라(②~⑤단계 소관) 여기서 3처럼 임의의 숫자로 강제하지 않는다.
MIN_SUBGOALS = 1
OVER_FRAGMENTATION_WARN_THRESHOLD = 12


class Subgoal(BaseModel):
    subgoal_id: str
    label: str
    description: str
    status: Literal["achieved", "partially_achieved", "not_achieved"]
    rationale: str

    @field_validator("subgoal_id", "label", "description", "rationale")
    @classmethod
    def not_empty(cls, v: str, info):
        if not v.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        return v


class GoalDecomposition(BaseModel):
    paper_title: str
    research_problem: str
    subgoals: List[Subgoal]

    @field_validator("paper_title", "research_problem")
    @classmethod
    def not_empty_top(cls, v: str, info):
        if not v.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        return v

    @field_validator("subgoals")
    @classmethod
    def check_subgoals(cls, v: List[Subgoal]):
        if len(v) < MIN_SUBGOALS:
            raise ValueError(f"subgoals must contain at least {MIN_SUBGOALS} items, got {len(v)}")
        ids = [s.subgoal_id for s in v]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate subgoal_id found")
        labels = [s.label.strip().lower() for s in v]
        if len(labels) != len(set(labels)):
            raise ValueError("duplicate subgoal label found")
        return v


def strip_code_fence(text: str) -> str:
    text = text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if "\n" in text:
            text = text.split("\n", 1)[1]
        text = text.strip()
    return text


def format_pydantic_errors(e: ValidationError) -> str:
    """여러 위반사항을 한 번에 모아서 재시도 피드백에 그대로 넣을 수 있는 문자열로 변환."""
    lines = []
    for err in e.errors():
        loc = ".".join(str(p) for p in err["loc"])
        lines.append(f"{loc}: {err['msg']}")
    return "; ".join(lines)


def validate_goal_decomposition(raw_text: str) -> Tuple[Optional[GoalDecomposition], Optional[str]]:
    """
    1단계 agent의 원문 출력을 검증한다.
    성공 시 (GoalDecomposition, None), 실패 시 (None, error_message)를 반환한다.
    """
    text = strip_code_fence(raw_text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON: {e}"

    try:
        result = GoalDecomposition.model_validate(data)
    except ValidationError as e:
        return None, f"Schema validation failed: {format_pydantic_errors(e)}"

    # soft warning — 하드 리젝 아님. 이상 징후로만 로그
    if len(result.subgoals) > OVER_FRAGMENTATION_WARN_THRESHOLD:
        print(
            f"[WARN] '{result.paper_title}': {len(result.subgoals)}개 subgoal — "
            f"과분해(over-fragmentation) 의심, human review 권장"
        )
    if not any(sg.status == "not_achieved" for sg in result.subgoals):
        print(
            f"[WARN] '{result.paper_title}': not_achieved 항목 없음 — "
            f"future work 후보가 이 논문에서는 안 나온다는 뜻인데 이상 없는지 확인 필요"
        )

    return result, None


async def run_goal_decomposition_with_retry(
    agent_module,
    paper_title: str,
    path_hint: str,
    context_variables: Dict,
    paper_index: int = 0,
    max_retries: int = 2,
) -> Tuple[Optional[GoalDecomposition], Dict, Optional[str]]:
    """
    Goal Decomposition Agent를 호출하고, 정적 검증을 통과할 때까지 재시도한다.
    검증 실패 시 (pydantic이 모은) 전체 오류 목록을 다음 턴 피드백으로 넣어
    같은 대화 맥락에서 한 번에 자가수정을 유도한다.
    N회(max_retries) 실패하면 포기하고 (None, context_variables, error) 반환 — 상위에서 해당 논문을 스킵.

    Returns: (parsed_result, context_variables, error_message)
    """
    messages: List[Dict] = [{
        "role": "user",
        "content": (
            f'Decompose the goals of ONE paper:\n'
            f'- Title: "{paper_title}"\n'
            f'- Path: {path_hint}\n\n'
            f'Follow the workflow in your instructions and return the structured JSON.'
        ),
    }]

    last_error = "unknown error"
    for attempt in range(max_retries + 1):
        iter_tag = f"paper{paper_index}" if attempt == 0 else f"paper{paper_index}_retry{attempt}"
        messages, context_variables = await agent_module(messages, context_variables, iter_times=iter_tag)

        # role을 반드시 확인해야 함 — 안 그러면 assistant의 마지막 응답이 비어있을 때(content=None)
        # 그 앞에 있던 tool 실행 결과(원문 LaTeX 덩어리 등)를 잘못 집어와서 그걸 JSON으로 파싱하려다
        # 실패하는 오진(誤診)이 발생한다. assistant 메시지만 본다.
        raw_output = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "assistant" and m.get("content")),
            None,
        )
        if not raw_output:
            last_error = "you ended your turn without returning the final JSON object"
        else:
            parsed, error = validate_goal_decomposition(raw_output)
            if error is None:
                return parsed, context_variables, None
            last_error = error

        if attempt < max_retries:
            messages.append({
                "role": "user",
                "content": (
                    f"Your previous output failed static validation: {last_error}\n"
                    f"Fix ALL of the issues above and return ONLY the corrected JSON object, "
                    f"following the exact schema from your instructions."
                ),
            })

    return None, context_variables, f"'{paper_title}' failed after {max_retries + 1} attempts — {last_error}"
