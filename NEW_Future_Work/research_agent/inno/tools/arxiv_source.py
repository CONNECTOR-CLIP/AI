import re
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

def extract_tex_content(tar_path, ):
    """
    Extract all .tex file contents from a tar.gz archive.

    Args:
        tar_path: path to the tar.gz file

    Returns:
        str: concatenated contents of all .tex files, each prefixed with its filename
    """
    try:
        all_content = []
        
        with tarfile.open(tar_path, 'r:gz') as tar:
            # 모든 .tex 파일 가져오기
            tex_files = [f for f in tar.getmembers() if f.name.endswith('.tex')]
            
            for tex_file in tex_files:
                # 파일 내용 추출
                f = tar.extractfile(tex_file)
                if f is not None:
                    try:
                        # utf-8로 디코딩 시도
                        content = f.read().decode('utf-8')
                    except UnicodeDecodeError:
                        # utf-8 실패 시 latin-1 시도
                        f.seek(0)
                        content = f.read().decode('latin-1')
                    
                    # 파일명과 내용 추가
                    all_content.append(f"\n{'='*50}\nFilename: {tex_file.name}\n{'='*50}\n")
                    all_content.append(content)
                    all_content.append("\n\n")
        
        # 모든 내용을 하나의 문자열로 결합
        return "".join(all_content)
    
    except Exception as e:
        return f"Extract failed with error: {str(e)}"

# arxiv src 다운로드 방어 설정. raw 요청(설명적 User-Agent 없음)은 rate limit에 걸리기 쉬운데,
# 이때 arxiv는 종종 소스 tarball 대신 비-gzip HTML('잠시 후 다시 시도') 페이지를 HTTP 200으로 돌려준다.
# → search_arxiv가 쓰는 공식 클라이언트와 같은 취지로 UA를 달고, 일시적 실패는 백오프 재시도한다.
_ARXIV_HEADERS = {"User-Agent": "Future-Work-Researcher/1.0 (mailto:yejin100403@gmail.com)"}
_GZIP_MAGIC = b"\x1f\x8b"


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
        paper_id = re.search(r'abs/([^/]+)', arxiv_url).group(1)
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
        #     이건 결정적(재시도해도 계속 PDF)이라 즉시 실패 처리한다 — 헛된 백오프를 없애고, 로그만 봐도
        #     "네트워크 탓이 아니라 LaTeX 소스가 없어서"임을 알 수 있게 한다. (.tex 파이프라인은 처리 불가.)
        ctype = response.headers.get("Content-Type", "")
        if "application/pdf" in ctype or response.content[:4] == b"%PDF":
            return {
                "status": -1,
                "message": (
                    f"Download paper '{title}' skipped — PDF-only on arxiv "
                    f"(no LaTeX source at /src/{paper_id}); cannot build .tex."
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
        safe_title = re.sub(r'[^\w\s]', '', title).strip()
        filename_base = safe_title.replace(' ', '_').lower()
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
        if tex_content.startswith("Extract failed with error:"):
            return {
                "status": -1,
                "message": f"Download paper '{title}' failed — could not extract .tex ({tex_content})",
                "path": None,
            }

        paper_tex_dir = os.path.join(local_root, workplace_name, "papers")
        os.makedirs(paper_tex_dir, exist_ok=True)
        with open(os.path.join(paper_tex_dir, f"{filename_base}.tex"), 'w') as f:
            f.write(tex_content)
        return {"status": 0, "message": f"Download paper '{title}' successfully", "path": f"/{workplace_name}/papers/{filename_base}.tex"}

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


def download_arxiv_source_by_title(paper_list: List[str], local_root: str, workplace_name: str):
    """
    download arxiv paper source file by title (또는 arxiv ID/URL을 직접 줘도 됨)

    paper_list 항목이 제목이면 검색 API로 찾고, arxiv ID나 abs/pdf URL이면 검색을 건너뛰고
    바로 소스를 받는다 — 검색 API(export.arxiv.org/api)가 rate limit로 막힐 때 우회 경로.

    Args:
        title: paper title
        paper_dir: paper directory
    """
    ret_msg = []
    for title in paper_list:
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
            )
            ret_msg.append(msg)

    return "\n".join(ret_msg)
    