# [CoT2: 한계/언급 추출] — LLM을 쓰지 않는다. 정규식 기반 정적 추출.
#
# 왜 LLM이 없어도 되는가:
# CoT1(goal_decomposition)은 quote를 모델이 "생성"하기 때문에 사후에 원문 대조(grounding)가
# 반드시 필요했다. 반면 여기서는 quote를 원문 문자열에서 정규식으로 직접 슬라이싱해서 뽑는다 —
# 그래서 quote는 애초에 원문에 없는 문장일 수가 없다(구조적으로 grounded). 이후 validation 단계의
# grounding check는 "혹시 모를 버그"를 잡는 방어선일 뿐, 이 자체가 주 검증 로직은 아니다.
#
# 이 단계가 잡아내는 것: 논문이 "스스로" 명시적으로 인정한 한계/미탐색/향후연구 문장.
# 이 단계가 잡아내지 못하는 것: 논문에 안 쓰여 있지만 그 문제를 풀려면 필요한 하위과제(missing subgoal).
# 후자는 CoT1(subgoal 커버리지)와 CoT3(교차비교) 몫이다 — 여기서 억지로 채우려 하지 않는다.

import re
from typing import Dict, List, Tuple

# 애초에 Discussion/Conclusion/Limitation 섹션으로만 스캔을 제한했더니, 실제로는 "we do not make
# claims about real-world relevance ... not in the scope of this paper" 같은 핵심 한계 문장이
# Experiments 섹션 안에 섞여 있는 걸 놓치는 사례가 나왔다(JSON Schema 논문으로 검증). 그래서 섹션
# 제목으로 거르지 않고 본문 전체를 스캔하되, References/Acknowledgments처럼 저자의 주장이 아닌
# 섹션만 제외한다. 노이즈는 _is_prose() 필터 + signal phrase의 특이성으로 억제한다.
EXCLUDED_SECTION_TITLES = re.compile(
    r"^(references?|acknowledg(e)?ments?|bibliography)$",
    re.IGNORECASE,
)

# proof/lemma/theorem/corollary 제목의 (sub)section은 형식적 증명 서술이라 자연어 한계 진술이
# 나올 일이 거의 없다 — 오히려 "we aim to approximate ... using neural networks" 같은, 증명 안에서
# "이번 단계의 목표"를 서술하는 문장이 future-work 신호(we aim to)에 우연히 걸려 오탐을 만든다.
# 실제 검증 논문(positional attention)에서 확인된 오탐 패턴이라 제목 단위로 통째로 제외한다.
EXCLUDED_SECTION_KEYWORDS_RE = re.compile(r"\bproof\b|\blemma\b|\btheorem\b|\bcorollary\b", re.IGNORECASE)

TAIL_FALLBACK_RATIO = 0.25  # \section 헤딩을 아예 못 찾은 논문(비정형 tex)에서 문서 마지막 구간을 대신 스캔

MIN_QUOTE_CHARS = 20
MAX_QUOTE_CHARS = 400
MIN_ALPHA_RATIO = 0.5  # 이 문장이 LaTeX 마크업 찌꺼기가 아니라 자연어인지 판별하는 최소 알파벳 비율

# Complexity/Evaluation/Scope 카테고리는 "related work가 X라서 별로다" 같은 남 얘기도 매칭될 수 있다
# (예: "Early studies ... which are computationally expensive." — 이건 LightGCN 자신이 아니라
# 인용된 이전 연구의 한계). 이 논문 자신의 진술인지 최소한으로 걸러내려면 1인칭 자기지시가 있어야 한다.
# Future_Work와 Unaddressed_Problem은 제외 — "future work" 관용구 자체가 학술 글쓰기에서 거의
# 항상 "이 논문이 남긴 과제"를 뜻해서 "we/our" 없이도(예: "...is an exciting future work.") 신뢰도가
# 높고, "Many interesting problems remain open"처럼 비인칭 서술도 실제로 유효한 gap 신호였다
# (둘 다 검증 논문에서 확인됨). 여기에 self-reference를 강제하면 "Limitations and future work"
# 섹션에 명시된 진짜 future work 문장까지 걸러내는 손해가 더 크다.
SELF_REFERENCE_RE = re.compile(r"\b(we|our|us)\b|\bthis (?:paper|work|study|approach|method|algorithm)\b", re.IGNORECASE)
CATEGORIES_REQUIRING_SELF_REFERENCE = {"Scope_Limitation", "Complexity_Limitation", "Evaluation_Limitation"}

# (limitation_type, [정규식 패턴, ...]) — 순서가 우선순위. 먼저 매칭되는 카테고리로 태깅한다.
SIGNAL_PATTERNS: List[Tuple[str, List[str]]] = [
    ("Future_Work", [
        r"future work",
        r"in future research",
        r"we (?:plan|intend|aim) to",
        r"we leave .{0,80}?(?:for|as) future",
        r"left for future work",
        r"as future work",
        r"we would like to explore",
        r"an?\s+(?:interesting|natural|promising) (?:direction|extension) for future",
    ]),
    ("Scope_Limitation", [
        r"(?:is|are) (?:beyond|outside) the scope",
        r"out of scope",
        r"we do not (?:address|consider|explore|study|investigate|examine)",
        r"we (?:only )?focus on .{0,80}?,?\s*(?:not|rather than)",
        r"we restrict (?:our|this) (?:attention|analysis|study) to",
        r"is not covered (?:in|by) this (?:paper|work|study)",
        r"we do not make claims about",
    ]),
    ("Complexity_Limitation", [
        r"computationally (?:expensive|infeasible|intractable)",
        r"(?:does|do) not scale",
        r"scalability (?:issue|limitation|challenge)",
        r"(?:high|significant) (?:computational )?overhead",
        r"worst[- ]case complexity",
        # trade-off 인정 패턴 — 저자가 자기 해법의 대가를 시인하는 문장. 이게 없어서 JSON Schema
        # 논문의 "We defined a technique to eliminate dynamic references, at the price of a potential
        # exponential increase in the schema size."(Conclusions)를 통째로 놓쳤다. 이런 문장은
        # "그 대가 없이 같은 걸 할 수 있나?"라는 아주 좋은 future work 후보로 직결된다.
        r"at the (?:price|cost|expense) of",
        r"comes? at (?:a|the) (?:price|cost)",
    ]),
    ("Evaluation_Limitation", [
        r"(?:small|limited) (?:sample size|scale|dataset|benchmark)",
        r"(?:may|might) not generalize",
        r"(?:limited|narrow) generali[sz]ation",
        r"(?:evaluated|tested) only on",
        r"a single dataset",
    ]),
    ("Unaddressed_Problem", [
        r"remains? an? open (?:problem|question)",
        r"(?:problems?|questions?) remains? open",
        r"remains? open\b",
        r"(?:it is |this )?(?:still |currently )?unclear whether",
        r"not yet (?:clear|known|understood)",
        r"we do not (?:know|understand) (?:whether|how)",
        r"an interesting open (?:direction|question|problem)",
    ]),
]
_COMPILED_SIGNALS: List[Tuple[str, "re.Pattern", str]] = [
    (label, re.compile(pat, re.IGNORECASE), pat)
    for label, patterns in SIGNAL_PATTERNS
    for pat in patterns
]

# 제목 안에 {\jsonsch} 같은 1중 중첩 매크로가 있어도 안 깨지도록 1-level 중첩까지만 허용.
_SECTION_HEADING_RE = re.compile(r"\\(?:sub)?section\*?\{((?:[^{}]|\{[^{}]*\})*)\}")
# 문장부호+대문자/백슬래시 경계 OR 빈 줄(LaTeX 문단 구분자). 후자가 없으면 masking으로 공백 처리된
# 주석/comment 줄이 다음 실제 문장이 나올 때까지 통째로 하나의 "문장"에 흡수되어, 정상 길이의
# 후보가 MAX_QUOTE_CHARS를 넘겨 통째로 드롭되는 문제가 생긴다 (masked 공백에는 대문자 트리거가 없음).
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\\])|\n[ \t]*\n+")
_LATEX_ENV_BLOCK_RE = re.compile(
    r"\\begin\{(equation|align|figure|table|tabular)\*?\}.*?\\end\{\1\*?\}",
    re.IGNORECASE | re.DOTALL,
)
_INLINE_COMMENT_RE = re.compile(r"(?<!\\)%.*")  # 이스케이프 안 된 %부터 줄 끝까지 (인라인/전체 주석 모두 포함)
_HIDE_COMMAND_RE = re.compile(r"\\hide\{")  # \hide{...}는 저자가 컴파일 결과물에서 의도적으로 뺀 초안 메모 — 논문 본문이 아님


def _mask_balanced_command(text: str, start_pattern: "re.Pattern") -> str:
    """start_pattern이 매칭된 지점부터 중괄호 짝이 맞는 지점까지를 같은 길이의 공백으로 치환한다.
    \\hide{...}처럼 안에 임의로 중첩된 {}가 들어있는 커맨드를 다루기 위해 [^}]* 정규식 대신
    괄호 깊이를 직접 세어 짝을 맞춘다."""
    chars = list(text)
    for m in start_pattern.finditer(text):
        depth = 1
        i = m.end()
        while i < len(text) and depth > 0:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        for j in range(m.start(), i):
            chars[j] = " " if text[j] != "\n" else "\n"
    return "".join(chars)


def _mask_non_prose(text: str) -> str:
    """comment(전체/인라인)와 equation/figure/table 블록, \\hide{...}(저자 초안 메모, 실제 논문 본문 아님)를
    같은 길이의 공백으로 치환한 '마스킹된' 사본을 만든다. 오프셋이 원문과 동일하게 유지되므로,
    이 마스킹된 텍스트에서 찾은 (start, end)를 원문 slicing에 그대로 재사용해도 안전하다 —
    quote는 항상 진짜 원문 substring이 된다."""
    masked = _LATEX_ENV_BLOCK_RE.sub(lambda m: " " * len(m.group(0)), text)
    masked = _mask_balanced_command(masked, _HIDE_COMMAND_RE)
    masked = _INLINE_COMMENT_RE.sub(lambda m: " " * len(m.group(0)), masked)
    return masked


def _find_target_sections(text: str) -> List[Tuple[int, int, str]]:
    """(start, end, section_title) 목록 — \\section 아래(전문/프리앰블 제외) 전체를, References류만 뺴고 스캔한다.
    \\section 헤딩이 아예 없는 논문(비정형 tex)이면 문서 마지막 구간을 fallback으로 반환한다."""
    headings = [(m.start(), m.end(), m.group(1).strip()) for m in _SECTION_HEADING_RE.finditer(text)]
    spans = []
    for i, (h_start, h_end, title) in enumerate(headings):
        body_end = headings[i + 1][0] if i + 1 < len(headings) else len(text)
        if not EXCLUDED_SECTION_TITLES.match(title) and not EXCLUDED_SECTION_KEYWORDS_RE.search(title):
            spans.append((h_end, body_end, title))

    if spans:
        return spans

    tail_start = int(len(text) * (1 - TAIL_FALLBACK_RATIO))
    return [(tail_start, len(text), "TAIL_FALLBACK")]


def _split_sentences(text: str, masked_text: str, base_offset: int) -> List[Tuple[int, int]]:
    """masked_text(마스킹된 사본)에서 문장 경계를 찾되, 반환하는 offset은 원문(base_offset 기준) 좌표."""
    boundaries = [0] + [m.end() for m in _SENTENCE_BOUNDARY_RE.finditer(masked_text)] + [len(masked_text)]
    spans = []
    for i in range(len(boundaries) - 1):
        s, e = boundaries[i], boundaries[i + 1]
        if masked_text[s:e].strip():
            spans.append((base_offset + s, base_offset + e))
    return spans


def _is_prose(sentence: str) -> bool:
    stripped = sentence.strip()
    if not (MIN_QUOTE_CHARS <= len(stripped) <= MAX_QUOTE_CHARS):
        return False
    if len(stripped.split()) < 5:
        return False
    alpha_count = sum(c.isalpha() or c.isspace() for c in stripped)
    return (alpha_count / len(stripped)) >= MIN_ALPHA_RATIO


def _match_signal(sentence: str) -> Tuple[str, str] | Tuple[None, None]:
    for label, compiled, raw_pattern in _COMPILED_SIGNALS:
        m = compiled.search(sentence)
        if m:
            return label, m.group(0)
    return None, None


def extract_limitation_candidates(paper_text: str) -> List[Dict]:
    """
    논문 원문(.tex 전체 텍스트)에서 저자가 스스로 인정한 한계/미탐색/future work 후보를 추출한다.
    LLM 호출 없음 — 순수 정규식 기반. quote는 항상 paper_text의 실제 substring이므로
    grounding은 구조적으로 보장된다 (validation 단계에서는 방어적으로만 재확인).

    Returns: List[dict] — 각 dict는 {quote, location, context, limitation_type, matched_signal}
    """
    masked_full = _mask_non_prose(paper_text)
    candidates: List[Dict] = []
    seen_quotes = set()

    for sec_start, sec_end, section_title in _find_target_sections(paper_text):
        section_masked = masked_full[sec_start:sec_end]
        sentence_spans = _split_sentences(paper_text[sec_start:sec_end], section_masked, sec_start)

        for i, (s, e) in enumerate(sentence_spans):
            quote = paper_text[s:e].strip()
            if not _is_prose(quote):
                continue

            label, matched_signal = _match_signal(quote)
            if label is None:
                continue
            if label in CATEGORIES_REQUIRING_SELF_REFERENCE and not SELF_REFERENCE_RE.search(quote):
                continue

            norm = " ".join(quote.lower().split())
            if norm in seen_quotes:
                continue
            seen_quotes.add(norm)

            ctx_start = sentence_spans[i - 1][0] if i > 0 else s
            ctx_end = sentence_spans[i + 1][1] if i + 1 < len(sentence_spans) else e
            context = paper_text[ctx_start:ctx_end].strip()

            candidates.append({
                "quote": quote,
                "location": section_title,
                "context": context,
                "limitation_type": label,
                "matched_signal": matched_signal,
            })

    return candidates
