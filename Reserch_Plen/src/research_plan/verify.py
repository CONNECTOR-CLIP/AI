"""Stage 5: 인용·날조 검사 (LLM 없음).

4단계 문서(research_plan.md, paper_skeleton.md)와 그 근거 plan을 대조한다.
1. 인용: 문서와 plan에 나온 arXiv ID가 화이트리스트 안에 있고, arXiv에 실제로 존재하며, 제목이 화이트리스트 제목과 맞는지.
   arXiv 조회 결과는 data/arxiv_cache.json에 저장해 다음부터는 오프라인으로도 검사한다.
2. 수치: 문서의 숫자가 plan에 있는 숫자인지. plan에 없는 숫자는 지어낸 것으로 보고 오류로 낸다.
3. 이름: 문서의 고유명사(모델·데이터셋·논문 이름처럼 대문자 묶음, CamelCase, 숫자가 섞인 이름)가 plan이나 화이트리스트 제목에 있는지.
   흔한 약어와 구분이 어려우므로 경고로만 낸다. 사람이 확인한다.
결과 단정 표현은 4단계와 같은 validate.py 목록으로 다시 확인한다(5단계에서 목록을 늘렸다).
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

from .validate import ARXIV_ID, FORBIDDEN_PATTERNS

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = ROOT / "data" / "arxiv_cache.json"
ARXIV_API = "https://export.arxiv.org/api/query"
ATOM = {"a": "http://www.w3.org/2005/Atom"}
TITLE_MIN_SIMILARITY = 0.85
DOCS = ("research_plan.md", "paper_skeleton.md")

# 이름 검사에서 빼는 흔한 약어와 지표 이름
COMMON_NAMES = {
    "RESULT", "TBD", "ID", "IDs", "F1", "AUROC", "LLM", "LLMs", "NLP", "QA", "GPU", "GPUs", "RL", "API",
    "JSON", "LoRA", "CoT4", "CoT5", "NOVEL", "NOT_NOVEL", "URL", "PDF", "SFT", "arXiv", "DB",
}
# 내부 ID와 문서 안 꼬리표(가설 H1, 연구 질문 RQ1, 질문 Q1)는 이름이 아니다.
ID_TOKEN = re.compile(r"^(?:[LMBVECRSHQ]|RQ)\d+$")
TOKEN = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
NUMBER = re.compile(r"(?<![A-Za-z0-9.])\d+(?:\.\d+)?(?![A-Za-z0-9])")
RESULT_SLOT = re.compile(r"\[RESULT:[^\]]*\]")
INTERNAL_ID = re.compile(r"(?<![A-Za-z0-9])[LMBVECRS]\d+(?![A-Za-z0-9])")
# 목록 번호("1. ")와 절 번호("- 2.1 ", "4.2. ")
LIST_NUMBER = re.compile(r"^\s*(?:[-*]\s*)?\d+(?:\.\d+)*\.?\s", re.MULTILINE)
FIG_NUMBER = re.compile(r"\b(?:Fig\.|Figure|Table|Section|Eq\.)\s*\d+")
# 문서 구조에서 나오는 숫자: 제목 줄, 머리 인용 블록, 표 구분선, 절 번호
STRUCTURE_LINE = re.compile(r"^(?:#.*|>.*|\|[-| ]+\|)$", re.MULTILINE)


def _norm_title(title: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", title.lower()).split())


def title_similarity(a: str, b: str) -> float:
    a, b = _norm_title(a), _norm_title(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def fetch_arxiv(ids: list[str], *, timeout: float = 30) -> dict[str, dict]:
    """arXiv API로 여러 ID를 한 번에 조회한다. {id: {"found": bool, "title": str}}"""
    query = urllib.parse.urlencode({"id_list": ",".join(ids), "max_results": len(ids)})
    with urllib.request.urlopen(f"{ARXIV_API}?{query}", timeout=timeout) as resp:
        root = ET.fromstring(resp.read())
    found = {}
    for entry in root.findall("a:entry", ATOM):
        entry_id = (entry.findtext("a:id", default="", namespaces=ATOM) or "").rsplit("/", 1)[-1]
        title = " ".join((entry.findtext("a:title", default="", namespaces=ATOM) or "").split())
        bare = re.sub(r"v\d+$", "", entry_id)
        if bare and title and title.lower() != "error":
            found[bare] = {"found": True, "title": title}
    return {i: found.get(i, {"found": False, "title": ""}) for i in ids}


class ArxivLookup:
    """arXiv 조회와 캐시. offline이면 캐시에 있는 것만 쓰고 나머지는 '확인불가'로 둔다."""

    def __init__(self, cache_path: Path = DEFAULT_CACHE, *, offline: bool = False,
                 fetch: Callable[[list[str]], dict[str, dict]] = fetch_arxiv):
        self.cache_path = Path(cache_path)
        self.offline = offline
        self.fetch = fetch
        self.cache: dict[str, dict] = {}
        if self.cache_path.is_file():
            self.cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.error: str | None = None

    def lookup(self, ids: list[str]) -> dict[str, dict]:
        missing = [i for i in ids if i not in self.cache]
        if missing and not self.offline:
            try:
                for start in range(0, len(missing), 50):
                    if start:
                        time.sleep(3)  # arXiv API 이용 규칙: 연속 요청은 3초 간격
                    result = self.fetch(missing[start:start + 50])
                    today = date.today().isoformat()
                    self.cache.update({i: {**r, "checked": today} for i, r in result.items()})
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.cache_path.write_text(
                    json.dumps(self.cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
            except (urllib.error.URLError, TimeoutError, ET.ParseError, OSError) as exc:
                self.error = f"arXiv 조회 실패: {exc}"
        return {i: self.cache.get(i) for i in ids}


def _plan_text(plan: dict) -> str:
    titles = " ".join(w.get("title", "") for w in plan.get("citation_whitelist", []))
    return json.dumps(plan["fields"], ensure_ascii=False) + " " + titles


def check_citations(plan: dict, docs: dict[str, str], lookup: ArxivLookup) -> tuple[list[str], list[str], list[dict]]:
    whitelist = {w["arxiv_id"]: w.get("title", "") for w in plan.get("citation_whitelist", [])}
    cited = set(ARXIV_ID.findall(json.dumps(plan["fields"], ensure_ascii=False)))
    for text in docs.values():
        cited |= set(ARXIV_ID.findall(text))
    errors, warnings, details = [], [], []
    results = lookup.lookup(sorted(cited))
    if lookup.error:
        warnings.append(lookup.error)
    for arxiv_id in sorted(cited):
        result = results.get(arxiv_id)
        row = {"arxiv_id": arxiv_id, "whitelist_title": whitelist.get(arxiv_id), "arxiv_title": None,
               "similarity": None, "status": ""}
        if arxiv_id not in whitelist:
            row["status"] = "화이트리스트 밖"
            errors.append(f"인용 {arxiv_id}: 화이트리스트에 없음")
        elif result is None:
            row["status"] = "확인불가"
            warnings.append(f"인용 {arxiv_id}: arXiv에서 확인하지 못함 (오프라인 또는 조회 실패)")
        elif not result["found"]:
            row["status"] = "arXiv에 없음"
            errors.append(f"인용 {arxiv_id}: arXiv에 존재하지 않음")
        else:
            row["arxiv_title"] = result["title"]
            row["similarity"] = round(title_similarity(whitelist[arxiv_id], result["title"]), 3)
            if row["similarity"] < TITLE_MIN_SIMILARITY:
                row["status"] = "제목 불일치"
                errors.append(
                    f"인용 {arxiv_id}: 화이트리스트 제목 {whitelist[arxiv_id]!r}과 arXiv 제목 {result['title']!r}이 다름 "
                    f"(유사도 {row['similarity']})"
                )
            else:
                row["status"] = "확인"
        details.append(row)
    return errors, warnings, details


def _strip_structure(text: str) -> str:
    """숫자·이름 검사에서 문서 구조와 내부 표기를 뺀다."""
    text = STRUCTURE_LINE.sub("", text)
    for pattern in (RESULT_SLOT, ARXIV_ID, INTERNAL_ID, FIG_NUMBER):
        text = pattern.sub(" ", text)
    return LIST_NUMBER.sub("", text)


def check_numbers(plan: dict, docs: dict[str, str]) -> list[str]:
    allowed = set(NUMBER.findall(_strip_structure(_plan_text(plan))))
    errors = []
    for name, text in docs.items():
        for number in sorted(set(NUMBER.findall(_strip_structure(text))) - allowed, key=float):
            line = next((l for l in text.splitlines() if number in l), "")
            errors.append(f"{name}: plan에 없는 숫자 {number}: {line.strip()[:80]!r}")
    return errors


def _is_name(token: str) -> bool:
    if ID_TOKEN.match(token) or token in COMMON_NAMES:
        return False
    # 대문자 둘 이상 연속(RAG), 소문자 뒤 대문자(FineRef), 글자와 숫자 섞임(A100)
    return bool(re.search(r"[A-Z]{2}|[a-z][A-Z]|[A-Za-z]\d|\d[A-Za-z]", token))


def check_names(plan: dict, docs: dict[str, str]) -> list[str]:
    known = {t for t in TOKEN.findall(_plan_text(plan))}
    warnings = []
    for name, text in docs.items():
        unknown = set()
        for token in TOKEN.findall(_strip_structure(text)):
            if not _is_name(token):
                continue
            parts = token.split("-")
            # Self-RAG-based처럼 알려진 이름 뒤에 접미어가 붙은 경우는 허용
            if any("-".join(parts[:k]) in known for k in range(len(parts), 0, -1)):
                continue
            unknown.add(token)
        warnings += [f"{name}: plan에 없는 이름 {token} (지어낸 모델·데이터셋인지 확인)" for token in sorted(unknown)]
    return warnings


def check_phrases(docs: dict[str, str]) -> list[str]:
    errors = []
    for name, text in docs.items():
        for pattern in FORBIDDEN_PATTERNS:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                errors.append(f"{name}: 결과 단정 표현 {match.group(0)!r}")
    return errors


def verify(plan: dict, docs: dict[str, str], lookup: ArxivLookup) -> dict:
    cite_errors, cite_warnings, citations = check_citations(plan, docs, lookup)
    errors = cite_errors + check_numbers(plan, docs) + check_phrases(docs)
    warnings = cite_warnings + check_names(plan, docs)
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": warnings,
        "citations": citations,
        "arxiv_cache": str(lookup.cache_path),
        "offline": lookup.offline,
    }
