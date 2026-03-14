#우선 pdf_extractor.py에서 텍스트 추출과 청킹, 임베딩까지 한 번에 실행한 후, 그 결과를 바탕으로 검색 시나리오를 테스트하는 코드입니다.
#유저가 검색하는 시나리오 스크립트 모델은 (all-MiniLM-L6-v2) 사용
# 엘라스틱 서치(도커) 주소 확인
#맨 밑 test_question에 검색할 질문 입력 후 실행하면 됨.

from elasticsearch import Elasticsearch
from sentence_transformers import SentenceTransformer

# 1. 엘라스틱서치 연결 (명확한 IPv4 주소 사용)
es = Elasticsearch("http://127.0.0.1:9200")

# 2. SBERT 모델 로딩 (데이터를 넣을 때 썼던 모델과 '반드시' 똑같은 모델을 써야 합니다!)
print("🧠 검색용 AI 모델 로딩 중...")
model = SentenceTransformer('all-MiniLM-L6-v2')

def search_paper(question, top_k=3):
    print(f"\n🤔 사용자의 질문: '{question}'")
    print("🔄 질문을 384차원 벡터로 변환 중...")
    
    # 3. 사용자의 질문을 고차원 벡터(숫자 배열)로 변환
    question_vector = model.encode(question).tolist()
    
    # 4. 엘라스틱서치에 날릴 벡터 유사도(kNN) 검색 쿼리
    query = {
        "knn": {
            "field": "embedding",         # 우리가 벡터를 저장했던 필드 이름
            "query_vector": question_vector, # 사용자의 질문 벡터
            "k": top_k,                   # 가장 유사한 결과 몇 개를 가져올지 (상위 3개)
            "num_candidates": 100         # 내부적으로 비교할 후보군 수
        },
        # 결과로 화면에 출력할 필드만 선택 (384개짜리 벡터값 자체는 출력할 필요가 없으므로 제외)
        "_source": ["chunk_id", "text_chunk", "title"] 
    }
    
    print("🔍 엘라스틱서치 공간에서 가장 의미가 비슷한 조각 찾는 중...\n")
    response = es.search(index="arxiv_papers", body=query)
    
    # 5. 검색 결과 출력
    hits = response["hits"]["hits"]
    print(f"✅ 총 {len(hits)}개의 찰떡같은 텍스트 조각을 찾았습니다!\n")
    print("=" * 60)
    
    for i, hit in enumerate(hits):
        score = hit["_score"]     # 유사도 점수 (보통 높을수록 정확함)
        source = hit["_source"]   # 원본 데이터
        
        print(f"🏆 [순위 {i+1} | 유사도 점수: {score:.4f}]")
        print(f"📍 논문 제목: {source['title']} (조각 번호: #{source['chunk_id']})")
        print(f"📝 찾은 내용: {source['text_chunk']}")
        print("-" * 60)

if __name__ == "__main__":
    # 우리가 저장한 논문(Sector Rotation)의 내용과 관련된 영어 질문을 던져봅니다.
    # "모멘텀(momentum)이 섹터 로테이션에 어떤 영향을 미치나요?"
    test_question = "How does momentum affect sector rotation?"
    
    search_paper(test_question)