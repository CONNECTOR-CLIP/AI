import re
import gzip
import tarfile
import os
import time
import requests
import arxiv
from typing import List


def search_arxiv(query, max_results=10):
    """
    search arxiv papers by title.

    공식 `arxiv` 라이브러리를 사용한다(arxiv_novelty_check.py와 동일 방식). 이 라이브러리의 Client는
    (a) descriptive User-Agent를 붙여 raw requests보다 429(rate limit)가 훨씬 덜 나고,
    (b) delay_seconds 간격 + num_retries 재시도로 rate limit/일시 오류를 알아서 백오프 처리한다.
    재시도를 소진하고도 실패하면 예외를 그대로 올린다 — 호출부가 "논문 없음(0건)"과
    "요청 실패(429/네트워크)"를 구분해 보고하도록. (예전엔 HTTP 오류를 삼켜 빈 리스트를 돌려주는 바람에
    429가 "Cannot find the paper"라는 엉뚱한 메시지로 둔갑했다.)

    Args:
        query (str): search title
        max_results (int): max return results

    Returns:
        list: list of paper info dicts (title/author/published/summary/url/pdf_url)
    """
    # 하이픈(-), 콜론(:)은 검색 특수문자 → 공백으로 치환
    safe_query = re.sub(r'[-:]', ' ', query)
    safe_query = ' '.join(safe_query.split())

    search = arxiv.Search(
        query=f'ti:{safe_query}',
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
    )
    # delay_seconds: arxiv 권장 요청 간격, num_retries: 429/일시오류 시 내부 재시도(백오프)
    client = arxiv.Client(page_size=max_results, delay_seconds=3.0, num_retries=5)

    papers = []
    for result in client.results(search):
        papers.append({
            'title': result.title,
            'author': [a.name for a in result.authors],
            'published': result.published,
            'summary': result.summary,
            'url': result.entry_id,   # 'http://arxiv.org/abs/<id>' 형식 → 다운로드 regex(abs/...) 호환
            'pdf_url': result.pdf_url,
        })
    return papers

def extract_tex_content(tar_path):
    try:
        all_content = []

        try:
            with tarfile.open(tar_path, "r:*") as tar:
                tex_files = [
                    f for f in tar.getmembers()
                    if f.isfile() and f.name.endswith(".tex")
                ]

                for tex_file in tex_files:
                    f = tar.extractfile(tex_file)
                    if f is not None:
                        raw = f.read()
                        try:
                            content = raw.decode("utf-8")
                        except UnicodeDecodeError:
                            content = raw.decode("latin-1")

                        all_content.append(
                            f"\n{'=' * 50}\n"
                            f"Filename: {tex_file.name}\n"
                            f"{'=' * 50}\n"
                        )
                        all_content.append(content)
                        all_content.append("\n\n")

        except tarfile.ReadError:
            # 일부 구형 논문은 tar가 아니라 gzip으로 압축된 단일 TeX 파일이다.
            with gzip.open(tar_path, "rb") as source:
                raw = source.read()

            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                content = raw.decode("latin-1")

            all_content.append(
                f"\n{'=' * 50}\n"
                f"Filename: source.tex\n"
                f"{'=' * 50}\n"
            )
            all_content.append(content)

        return "".join(all_content)

    except Exception as e:
        return f"Extract failed with error: {str(e)}"
# arxiv src 다운로드 방어 설정. raw 요청(설명적 User-Agent 없음)은 rate limit에 걸리기 쉬운데,
# 이때 arxiv는 종종 소스 tarball 대신 비-gzip HTML('잠시 후 다시 시도') 페이지를 HTTP 200으로 돌려준다.
# → search_arxiv가 쓰는 공식 클라이언트와 같은 취지로 UA를 달고, 일시적 실패는 백오프 재시도한다.
_ARXIV_HEADERS = {"User-Agent": "Future-Work-Researcher/1.0"}
_GZIP_MAGIC = b"\x1f\x8b"


# ---------------------------------------------------------------------------
# PDF fallback: LaTeX 소스가 없는(PDF-only) 논문도 파이프라인을 계속 타게 한다.
# PDF에서 텍스트를 뽑아 papers/<name>.tex 로 저장한다(확장자를 .tex로 유지해야 CoT1/CoT2/flow의
# `\S+\.tex` 경로 regex와 open_local_file 흐름을 그대로 쓸 수 있다). 변환은 로컬에서 1~수 초면 끝나고,
# /src/가 이미 PDF 바이트를 돌려준 경우엔 추가 다운로드도 없다 → 전체 실행 시간은 사실상 그대로.
# 에이전트 프롬프트가 "\begin{abstract}", "\section{Introduction}" 등으로 ctrl+f 하므로
# 헤딩으로 보이는 줄 앞에 가짜 LaTeX 마커를 붙여 네비게이션도 .tex와 동일하게 동작하게 한다.
# ---------------------------------------------------------------------------
_SECTION_KEYWORDS = (
    "introduction", "related work", "background", "preliminaries", "method", "methods",
    "methodology", "approach", "model", "experiments", "experiment", "experimental setup",
    "evaluation", "results", "analysis", "discussion", "limitations", "limitation",
    "conclusion", "conclusions", "future work", "conclusion and future work",
    "conclusions and future work", "acknowledgments", "acknowledgements", "references",
    "appendix",
)
_NUMBERED_HEADING = re.compile(r'^(?:\d{1,2}|[IVX]{1,4})\.?\s+([A-Z][^.!?]{1,80})$')
_SUBSECTION_HEADING = re.compile(r'^\d{1,2}\.\d{1,2}\.?\s+([A-Z][^.!?]{1,80})$')


def _pdf_bytes_to_text(pdf_bytes: bytes) -> str:
    """PDF 바이트 → 평문. 빠른 pypdfium2를 우선 쓰고, 없으면 이미 의존성인 pdfminer로 대체."""
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(pdf_bytes)
        try:
            pages = [pdf[i].get_textpage().get_text_range() for i in range(len(pdf))]
        finally:
            pdf.close()
        return "\n".join(pages)
    except ImportError:
        import io
        import pdfminer.high_level
        return pdfminer.high_level.extract_text(io.BytesIO(pdf_bytes))


def _pdf_text_to_pseudo_tex(text: str) -> str:
    """추출된 평문에 \\begin{abstract} / \\section{...} 마커를 붙여 .tex 네비게이션과 호환되게 한다."""
    out = []
    abstract_done = False
    for raw_line in text.replace("\r", "").split("\n"):
        line = raw_line.strip()
        low = line.lower().rstrip(":")
        if not abstract_done and low in ("abstract", "a b s t r a c t"):
            out.append("\\begin{abstract}")
            abstract_done = True
            continue
        if not abstract_done and low.startswith("abstract") and len(line) > 20:
            # "Abstract—We propose ..." 처럼 같은 줄에 본문이 붙은 경우
            out.append("\\begin{abstract}")
            abstract_done = True
            out.append(raw_line)
            continue
        m = _SUBSECTION_HEADING.match(line)
        if m:
            out.append(f"\\subsection{{{m.group(1).strip()}}}")
            continue
        m = _NUMBERED_HEADING.match(line)
        if m and len(m.group(1).split()) <= 8:
            out.append(f"\\section{{{m.group(1).strip()}}}")
            continue
        if low in _SECTION_KEYWORDS:
            out.append(f"\\section{{{line.rstrip(':')}}}")
            continue
        out.append(raw_line)
    body = "\n".join(out)
    body = re.sub(r'\n{3,}', '\n\n', body)
    return (
        "% NOTE: LaTeX source unavailable on arXiv; this file was converted from the PDF.\n"
        "% Section markers (\\section{...}) are heuristic; equations/tables may be garbled.\n"
        + body
    )


def _save_pdf_as_tex(pdf_bytes: bytes, local_root: str, workplace_name: str, filename_base: str):
    """PDF를 원본(.pdf)과 변환본(.tex) 둘 다 저장하고, 변환본 상대경로를 반환한다. 실패 시 None."""
    try:
        text = _pdf_bytes_to_text(pdf_bytes)
    except Exception:
        return None
    if len(text.strip()) < 500:  # 스캔본 등 텍스트 레이어가 없는 PDF
        return None
    paper_src_dir = os.path.join(local_root, workplace_name, "paper_source")
    os.makedirs(paper_src_dir, exist_ok=True)
    with open(os.path.join(paper_src_dir, f"{filename_base}.pdf"), "wb") as f:
        f.write(pdf_bytes)
    paper_tex_dir = os.path.join(local_root, workplace_name, "papers")
    os.makedirs(paper_tex_dir, exist_ok=True)
    with open(os.path.join(paper_tex_dir, f"{filename_base}.tex"), "w", encoding="utf-8") as f:
        f.write(_pdf_text_to_pseudo_tex(text))
    return f"/{workplace_name}/papers/{filename_base}.tex"


def _download_pdf_fallback(paper_id: str, local_root: str, workplace_name: str, title: str, filename_base: str):
    """소스 tar에 .tex가 없을 때 arxiv.org/pdf/<id> 에서 PDF를 받아 변환한다."""
    try:
        resp = requests.get(f"https://arxiv.org/pdf/{paper_id}", headers=_ARXIV_HEADERS, timeout=60)
    except Exception:
        return None
    if resp.status_code != 200 or resp.content[:4] != b"%PDF":
        return None
    return _save_pdf_as_tex(resp.content, local_root, workplace_name, filename_base)


def _filename_base(title: str) -> str:
    safe_title = re.sub(r'[^\w\s]', '', title).strip()
    return safe_title.replace(' ', '_').lower()


def download_arxiv_source(arxiv_url, local_root, workplace_name, title: str, max_attempts: int = 4):
    """
    download arxiv paper source file

    Args:
        arxiv_url: arxiv paper url, e.g. 'http://arxiv.org/abs/2006.11239v2'
        local_root: local root directory
        workplace_name: workplace name
        max_attempts: rate limit 등 일시적 실패에 대한 최대 시도 횟수(선형 백오프)

    다운로드가 "성공"으로 위장되지 않도록 두 가지를 검증한다:
      (1) 응답 본문이 실제 gzip인지 매직바이트로 확인 — 아니면(=rate limit HTML 등) 재시도.
      (2) tar 추출이 실제로 .tex를 뽑았는지 확인 — 추출 실패면 status:-1로 실패 반환(쓰레기 .tex를 남기지 않음).
    이렇게 해야 상위(ToolModule 캐시/테스트)가 실패를 실패로 인지하고 해당 논문을 제외할 수 있다.
    """
    try:
        paper_id = re.search(r'abs/(.+?)(?:[?#]|$)', arxiv_url).group(1)
    except Exception as e:
        return {"status": -1, "message": f"Download paper '{title}' failed with error: {str(e)}", "path": None}

    source_url = f'http://arxiv.org/src/{paper_id}'
    last_reason = "unknown"

    for attempt in range(max_attempts):
        if attempt:
            time.sleep(3.0 * attempt)  # 선형 백오프로 rate limit 완화

        try:
            response = requests.get(source_url, headers=_ARXIV_HEADERS, timeout=60)
        except Exception as e:
            last_reason = f"request error: {type(e).__name__}: {e}"
            continue

        if response.status_code != 200:
            last_reason = f"HTTP status code {response.status_code}"
            continue

        # (0) PDF-only 논문: 저자가 LaTeX 소스를 안 올리면 arxiv가 /src/에서 소스 대신 PDF를 준다.
        #     예전엔 여기서 바로 실패 처리했지만, 이제 이 PDF 바이트를 그대로 텍스트로 변환해 .tex로 저장한다
        #     (추가 다운로드 없음, 로컬 변환 1~수 초). 변환 불가(스캔본 등)일 때만 실패.
        ctype = response.headers.get("Content-Type", "")
        if "application/pdf" in ctype or response.content[:4] == b"%PDF":
            pdf_path = _save_pdf_as_tex(response.content, local_root, workplace_name, _filename_base(title))
            if pdf_path:
                return {
                    "status": 0,
                    "message": f"Download paper '{title}' successfully (PDF-only on arxiv → converted PDF text to .tex)",
                    "path": pdf_path,
                    "source": "pdf",
                }
            return {
                "status": -1,
                "message": (
                    f"Download paper '{title}' skipped — PDF-only on arxiv and PDF text extraction failed "
                    f"(scanned/image PDF?) for /src/{paper_id}."
                ),
                "path": None,
            }

        # (1) 진짜 gzip tarball인지 확인. 비-gzip 200은 rate limit/오류 페이지일 가능성이 커서 재시도한다.
        if response.content[:2] != _GZIP_MAGIC:
            last_reason = (
                f"response is not a gzip archive (likely rate-limit/HTML page): "
                f"{len(response.content)} bytes starting with {response.content[:16]!r}"
            )
            continue

        paper_src_dir = os.path.join(local_root, workplace_name, "paper_source")
        os.makedirs(paper_src_dir, exist_ok=True)
        filename_base = _filename_base(title)
        filepath = os.path.join(paper_src_dir, f"{filename_base}.tar.gz")
        try:
            with open(filepath, 'wb') as f:
                f.write(response.content)
            tex_content = extract_tex_content(filepath)
        except Exception as e:
            last_reason = f"{type(e).__name__}: {e}"
            continue

        # (2) extract_tex_content는 실패 시 예외 대신 "Extract failed with error: ..." 문자열을 돌려준다.
        #     본문은 이미 gzip이므로 이 실패는 대개 결정적(예: LaTeX 소스가 없는 논문)이라 재시도하지 않는다.
        #     tar 안에 .tex가 하나도 없을 때(빈 문자열)도 실패로 보고, 두 경우 모두 PDF로 대체 시도한다.
        if tex_content.startswith("Extract failed with error:") or not tex_content.strip():
            pdf_path = _download_pdf_fallback(paper_id, local_root, workplace_name, title, filename_base)
            if pdf_path:
                return {
                    "status": 0,
                    "message": f"Download paper '{title}' successfully (no usable LaTeX → converted PDF text to .tex)",
                    "path": pdf_path,
                    "source": "pdf",
                }
            return {
                "status": -1,
                "message": f"Download paper '{title}' failed — could not extract .tex ({tex_content})",
                "path": None,
            }

        paper_tex_dir = os.path.join(local_root, workplace_name, "papers")
        os.makedirs(paper_tex_dir, exist_ok=True)
        with open(os.path.join(paper_tex_dir, f"{filename_base}.tex"), 'w', encoding='utf-8') as f:
            f.write(tex_content)
        return {"status": 0, "message": f"Download paper '{title}' successfully", "path": f"/{workplace_name}/papers/{filename_base}.tex", "source": "latex"}

    return {
        "status": -1,
        "message": f"Download paper '{title}' failed after {max_attempts} attempts ({last_reason})",
        "path": None,
    }







# 유사도 함수 새로 추가 - 두 제목이 얼마나 비슷한지 0.0~1.0 숫자로 계산
def _title_similarity(a: str, b: str) -> float:
    """Compute word-overlap Jaccard similarity between two titles (case-insensitive)."""
    stop = {"a", "an", "the", "of", "in", "on", "for", "and", "with", "to", "from", "is", "are"}
    def tokenize(s):
        return set(re.sub(r'[^\w\s]', '', s.lower()).split()) - stop  # 특수문자 제거, 대소문자 무시, 의미없는 단어 제거
    wa = tokenize(a)
    wb = tokenize(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)  # Jaccard 유사도: 공통 단어 수 ÷ 전체 단어 수









def _looks_like_arxiv_id_or_url(s: str) -> bool:
    """입력이 논문 '제목'이 아니라 arxiv ID나 abs/pdf URL인지 판별한다.
    이러면 (지금 429/503으로 막힌) 검색 API를 건너뛰고 바로 소스 다운로드로 갈 수 있다."""
    s = s.strip()
    if "arxiv.org/abs/" in s or "arxiv.org/pdf/" in s:
        return True
    if re.match(r'^\d{4}\.\d{4,5}(v\d+)?$', s):   # 최신 형식: 2412.09569 / 2412.09569v2
        return True
    return False


def _to_abs_url(s: str) -> str:
    """arxiv ID 또는 abs/pdf URL을 표준 abs URL로 변환한다. download_arxiv_source가 여기서 ID를 뽑아
    src 엔드포인트(arxiv.org/src/<id>)로 받는다 — 검색 API와 다른 서비스라 검색이 막혀도 통할 수 있다."""
    s = s.strip().rstrip('/')
    m = re.search(r'(?:abs|pdf)/(.+?)(?:\.pdf)?$', s)  # URL이면 id 부분 추출
    paper_id = m.group(1) if m else s                  # 아니면 bare id 그대로
    return f'http://arxiv.org/abs/{paper_id}'


def download_arxiv_source_by_title(
    paper_list: List[str],
    local_root: str,
    workplace_name: str,
    paper_ids: dict | None = None,
):
    """
    download arxiv paper source file by title (또는 arxiv ID/URL을 직접 줘도 됨)

    paper_list 항목이 제목이면 검색 API로 찾고, arxiv ID나 abs/pdf URL이면 검색을 건너뛰고
    바로 소스를 받는다 — 검색 API(export.arxiv.org/api)가 rate limit로 막힐 때 우회 경로.

    Args:
        title: paper title
        paper_dir: paper directory
    """
    ret_msg = []
    paper_ids = paper_ids or {}
    for title in paper_list:
        mapped_id = paper_ids.get(title)
        if mapped_id:
            abs_url = _to_abs_url(str(mapped_id))
            download_info = download_arxiv_source(abs_url, local_root, workplace_name, title)
            if download_info["status"] == -1:
                ret_msg.append(download_info["message"])
            else:
                ret_msg.append(
                    download_info["message"]
                    + f"\nResolved directly from mapped arxiv id: {mapped_id}"
                    + f"\nThe paper is downloaded to path: {download_info['path']}"
                + f"\nPaper source: {download_info['source']}"
                )
            continue

        # 입력이 arxiv ID/URL이면 (막힌) 검색 API를 건너뛰고 바로 소스 다운로드
        if _looks_like_arxiv_id_or_url(title):
            abs_url = _to_abs_url(title)
            download_info = download_arxiv_source(abs_url, local_root, workplace_name, title)
            if download_info["status"] == -1:
                ret_msg.append(download_info["message"])
            else:
                ret_msg.append(
                    download_info["message"]
                    + f"\nResolved directly from arxiv id/url (search skipped): {abs_url}"
                    + f"\nThe paper is downloaded to path: {download_info['path']}"
                + f"\nPaper source: {download_info['source']}"
                )
            continue

        try:
            papers = search_arxiv(title, max_results=5)  # 논문을 5개 검색해서
        except Exception as e:
            # 429(rate limit)/네트워크 오류를 "논문 없음"과 구분해서 진짜 사유를 보고한다.
            ret_msg.append(
                f"ERROR: arxiv search for '{title}' failed after retries "
                f"(likely rate limit / network issue): {type(e).__name__}: {e}"
            )
            continue
        if len(papers) == 0:
            ret_msg.append(f"Cannot find the paper '{title}' in arxiv (search returned 0 results)")
            continue
        
        # Pick the result whose title best matches the requested title
        best_paper = max(papers, key=lambda p: _title_similarity(p['title'], title))
        similarity = _title_similarity(best_paper['title'], title)

        # 완전 다른 논문. 다운로드 안함, 경고만 출력
        if similarity < 0.3:
            ret_msg.append(
                f"WARNING: Could not find a close match for '{title}' in arxiv. "
                f"Best candidate was '{best_paper['title']}' (similarity={similarity:.2f}). "
                f"Skipping download to avoid saving the wrong paper."
            )
            continue

        # 애매함. 일단 다운로드 하되 경고 출력
        if similarity < 0.6:
            ret_msg.append(
                f"WARNING: Weak title match for '{title}'. "
                f"Closest arxiv result: '{best_paper['title']}' (similarity={similarity:.2f}). "
                f"Proceeding with download but please verify."
            )

        # 정상 다운로드
        download_info = download_arxiv_source(best_paper['url'], local_root, workplace_name, title)

        # 다운로드 결과 메시지에 매칭 정보 추가
        if download_info["status"] == -1:
            ret_msg.append(download_info["message"])
        else:
            msg = (
                download_info["message"]
                + f"\nMatched arxiv title: '{best_paper['title']}' (similarity={similarity:.2f})"
                + f"\nThe paper is downloaded to path: {download_info['path']}"
                + f"\nPaper source: {download_info['source']}"
            )
            ret_msg.append(msg)

    return "\n".join(ret_msg)
    