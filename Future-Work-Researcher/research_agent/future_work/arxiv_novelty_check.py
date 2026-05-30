"""
퓨쳐워크 제안이 이미 arxiv에서 연구된 주제인지 확인한다.
전체 논문 다운로드 없이 title + abstract만 검색해서 novelty 판정.
"""
import re
import time
import requests
import arxiv
from litellm import completion
from litellm.exceptions import ServiceUnavailableError
from research_agent.constant import API_BASE_URL
from typing import List, Dict


def extract_keywords_for_search(future_work_text: str, model: str) -> List[str]:
    """
    LLM을 사용해서 퓨쳐워크 제안 텍스트에서 arxiv 검색용 키워드 추출.
    503 등 일시적 서버 오류 시 최대 3회 재시도.
    """
    last_exc = None
    for attempt in range(3):
        try:
            response = completion(
                model=model,
                messages=[{
                    "role": "user",
                    "content": f"""\
From the following future work proposal, extract 3-5 concise search keywords
suitable for an arxiv paper search query. Return only a Python list of strings.
Example: ["contrastive learning", "graph neural network", "few-shot"]

Future work proposal:
{future_work_text}

Return only the Python list, nothing else."""
                }],
                base_url=API_BASE_URL,
            )
            break
        except ServiceUnavailableError as e:
            last_exc = e
            wait = 10 * (2 ** attempt)  # 10s, 20s, 40s
            print(f"[arxiv_novelty_check] Gemini 503 (attempt {attempt+1}/3), retrying in {wait}s...")
            time.sleep(wait)
    else:
        raise last_exc
    raw = response.choices[0].message.content.strip()
    if "```" in raw:
        raw = raw.split("```")[1]          # ``` 와 ``` 사이 내용
        if "\n" in raw:
            raw = raw.split("\n", 1)[1]    # 첫 줄(언어 식별자) 제거
        raw = raw.strip()
    try:
        keywords = eval(raw)
        if isinstance(keywords, list):
            return keywords
    except Exception:
        pass
    # fallback: 쉼표 분리
    return [k.strip().strip('"').strip("'") for k in raw.strip("[]").split(",")]


def search_arxiv_abstracts(keywords: List[str], max_results: int = 8) -> List[Dict]:
    """
    arxiv에서 키워드로 검색 후 title + abstract만 반환.
    전체 논문 다운로드 없음.
    """
    query = " AND ".join(f'"{kw}"' for kw in keywords)
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
    )
    results = []
    for paper in search.results():
        results.append({
            "title": paper.title,
            "abstract": paper.summary,
            "year": paper.published.year,
            "url": paper.entry_id,
        })
    return results


def format_novelty_check_input(
    future_works: List[str],
    model: str,
) -> str:
    """
    퓨쳐워크 5개 각각에 대해 arxiv 검색 수행 후
    'future_work_agent'에게 넘길 novelty check 결과 텍스트 생성.
    """
    report_parts = []

    for i, fw_text in enumerate(future_works, 1):
        keywords = extract_keywords_for_search(fw_text, model)
        arxiv_results = search_arxiv_abstracts(keywords, max_results=8)

        section = f"=== Novelty Check for Future Work Idea {i} ===\n"
        section += f"Search keywords: {keywords}\n\n"

        if not arxiv_results:
            section += "No closely related papers found on arxiv → likely novel direction.\n"
        else:
            section += f"Found {len(arxiv_results)} potentially related papers (title + abstract only):\n\n"
            for j, paper in enumerate(arxiv_results, 1):
                section += f"[{j}] {paper['title']} ({paper['year']})\n"
                section += f"Abstract: {paper['abstract'][:400]}...\n\n"

        section += "=== END ===\n"
        report_parts.append(section)

    return "\n".join(report_parts)


def get_ambiguous_paper_indices(
    future_work_text: str,
    papers: List[Dict],
    llm_client,
    model: str,
) -> List[int]:
    """
    Abstract만으로 novelty 판단이 모호한 논문의 인덱스(0-based) 반환.
    """
    if not papers:
        return []

    abstracts_text = "\n\n".join([
        f"[{i+1}] {p['title']}\nAbstract: {p['abstract'][:400]}"
        for i, p in enumerate(papers)
    ])

    response = llm_client.chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": f"""\
Future work proposal:
{future_work_text}

Related paper abstracts:
{abstracts_text}

For each paper, judge whether its abstract is sufficient to determine if it already
addresses the proposed future work direction.

Return a JSON list of 1-based indices where the abstract is AMBIGUOUS or INSUFFICIENT
and the Introduction section should be read for a clearer judgment.
If all abstracts are sufficient, return [].

Return only the JSON list, nothing else. Example: [2, 4]"""
        }]
    )
    raw = response.choices[0].message.content.strip()
    try:
        indices = eval(raw)
        if isinstance(indices, list):
            return [i - 1 for i in indices if isinstance(i, int)]  # 0-based로 변환
    except Exception:
        pass
    return []


def fetch_arxiv_introduction(paper_url: str) -> str:
    """
    arxiv 논문의 HTML 버전(arxiv.org/html/{id})에서 Introduction 섹션만 추출.
    전체 다운로드 없이 HTTP GET 한 번으로 끝냄.
    """
    try:
        arxiv_id = paper_url.split("/abs/")[-1].split("v")[0].strip()
        html_url = f"https://arxiv.org/html/{arxiv_id}"

        resp = requests.get(html_url, timeout=15)
        if resp.status_code != 200:
            return ""

        html = resp.text

        # Introduction 섹션 추출 (다음 주요 섹션 전까지)
        pattern = re.search(
            r'(?i)(?:>|\b)introduction\b.*?(?=(?:>|\b)(?:related work|background|'
            r'preliminaries|methodology|method|approach|section\s+2|\d+\.\s+[A-Z]))',
            html,
            re.DOTALL,
        )
        if pattern:
            intro_html = pattern.group(0)
            clean = re.sub(r'<[^>]+>', ' ', intro_html)
            clean = re.sub(r'\s+', ' ', clean).strip()
            return clean[:3000]  # Introduction은 3000자면 충분

        return ""
    except Exception:
        return ""