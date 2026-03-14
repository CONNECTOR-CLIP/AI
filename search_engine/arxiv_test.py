# arXiv cs.SE (소프트웨어 공학) 최신 논문 가져오기 스크립트
# 이 스크립트는 arXiv API를 사용하여 cs.SE 카테고리의 최신 논문 정보를 가져옴
# 논문 제목, 저자, 출판일, PDF 링크, 요약 정보를 출력합니다.


import urllib.request
import feedparser

def fetch_arxiv_se_papers(max_results=5):
    # cs.SE (소프트웨어 공학) 카테고리, 최신순 정렬 URL
    url = f'http://export.arxiv.org/api/query?search_query=cat:cs.SE&sortBy=submittedDate&sortOrder=descending&max_results={max_results}'
    
    print(f"arXiv API 호출 중... (URL: {url})")
    response = urllib.request.urlopen(url).read()
    feed = feedparser.parse(response)
    
    papers = []
    
    for entry in feed.entries:
        title = entry.title.replace('\n', '')
        authors = [author.name for author in entry.authors]
        published_date = entry.published
        summary = entry.summary.replace('\n', ' ')
        
        pdf_url = None
        for link in entry.links:
            if 'title' in link and link.title == 'pdf':
                pdf_url = link.href
                break
                
        paper_info = {
            "title": title,
            "authors": authors,
            "published_date": published_date,
            "pdf_url": pdf_url,
            "summary": summary
        }
        papers.append(paper_info)
        
    return papers

# 테스트 실행 (최신 논문 3개 가져오기)
if __name__ == "__main__":
    se_papers = fetch_arxiv_se_papers(max_results=3)
    
    for i, paper in enumerate(se_papers, 1):
        print(f"\n[{i}번 논문]")
        print(f" 제목: {paper['title']}")
        print(f" 저자: {', '.join(paper['authors'])}")
        print(f" 출판일: {paper['published_date']}")
        print(f" PDF 링크: {paper['pdf_url']}")
        print("-" * 50)