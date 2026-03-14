# PDF 다운로드, 텍스트 추출, 청킹, 임베딩, 엘라스틱서치 저장까지 한 번에 실행하는 스크립트
# 이 스크립트는 arXiv PDF 파일을 임의로 다운로드(텍스트를 불러오고 원본 PDF는 다시 삭제 후 텍스트는 메모리에 적재)하여 텍스트를 추출하고, 
# 이를 청킹하여 SBERT 임베딩으로 변환한 후, 엘라스틱서치에 저장하는 전체 파이프라인을 구축합니다.
# 각 단계별로 상세한 로그를 출력하여 진행 상황을 명확히 확인할 수 있도록 설계
# 실행 전에 엘라스틱서치가 도커에서 정상적으로 실행 중인지, 그리고 필요한 라이브러리가 설치되어 있는지 확인필요
# LangChain의 RecursiveCharacterTextSplitter를 사용하여 텍스트를 청킹하는 부분도 포함 (pip install langchain_text_splitters)
#sbeart

import urllib.request
import fitz  # PyMuPDF
import os

def download_and_extract_text(pdf_url, save_path="temp_sample.pdf"):
    print(f"📥 PDF 다운로드 중... ({pdf_url})")
    
    # 1. PDF 다운로드 (임시 파일로 저장)
    req = urllib.request.Request(pdf_url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response, open(save_path, 'wb') as out_file:
        out_file.write(response.read())
        
    print("✅ 다운로드 완료!\n")
    print("📄 텍스트 추출 시작...")
    
    # 2. PyMuPDF로 PDF 열기
    doc = fitz.open(save_path)
    full_text = ""
    
    # 3. 모든 페이지를 돌면서 텍스트 추출
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        full_text += page.get_text()
        
    doc.close()
    
    # 4. 다 쓴 임시 PDF 파일은 삭제 (용량 관리)
    if os.path.exists(save_path):
        os.remove(save_path)
        
    return full_text

if __name__ == "__main__":
    # 테스트용 arXiv PDF URL (소프트웨어 공학 관련 임의의 논문)
    test_url = 'http://arxiv.org/pdf/2401.00001v1' 
    
    # 텍스트 추출 함수 실행
    extracted_text = download_and_extract_text(test_url)
    
    # 결과 확인
    print("\n✨ 추출된 텍스트 프리뷰 (앞부분 1000자):")
    print("-" * 50)
    print(extracted_text[:1000])  # 너무 기니까 앞부분만 출력
    print("-" * 50)
    print(f"\n📊 총 추출된 글자 수: {len(extracted_text):,} 자")
    
    # (기존 pdf_extractor.py 코드의 맨 아래에 이어서 작성)
from langchain_text_splitters import RecursiveCharacterTextSplitter

def chunk_text(text, chunk_size=1000, chunk_overlap=150):
    print(f"\n✂️ 청킹 시작: 설정된 크기({chunk_size}자), 겹침({chunk_overlap}자)")
    
    # 분할기 설정 (문단 -> 문장 -> 단어 순으로 똑똑하게 자름)
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""]
    )
    
    # 텍스트를 여러 개의 청크로 분할
    chunks = text_splitter.split_text(text)
    
    print(f"✅ 총 {len(chunks)}개의 청크(조각)로 분할 완료!\n")
    return chunks

if __name__ == "__main__":
    # 1. 아까 작성한 텍스트 추출 함수 실행 (URL은 그대로 유지)
    test_url = 'http://arxiv.org/pdf/2401.00001v1' 
    extracted_text = download_and_extract_text(test_url)
    
    # 2. 추출된 27,000여 자의 텍스트를 청킹 함수에 통과시키기
    text_chunks = chunk_text(extracted_text, chunk_size=1000, chunk_overlap=150)
    
    # 3. 분할된 결과 확인 (첫 번째와 두 번째 청크만 출력)
    print("✨ [청크 #1 프리뷰]")
    print(text_chunks[0])
    print("-" * 50)
    
    print("✨ [청크 #2 프리뷰 (앞부분과 문맥이 150자 정도 겹치는지 확인!)]")
    if len(text_chunks) > 1:
        print(text_chunks[1])
    print("-" * 50)
    
    # (기존 청킹 코드 맨 아래에 이어서 작성)
from sentence_transformers import SentenceTransformer

def embed_text_chunks(chunks):
    print("\n🧠 SBERT AI 모델 로딩 중... (최초 실행 시 모델 다운로드로 1~2분 소요될 수 있습니다)")
    
    # 속도와 성능 밸런스가 좋은 경량화 모델 로드 (생성되는 벡터 차원 수: 384)
    model = SentenceTransformer('all-MiniLM-L6-v2')
    
    print(f"🔄 {len(chunks)}개의 텍스트 조각을 의미를 담은 벡터로 변환하는 중...")
    
    # encode() 함수 하나로 리스트 안의 모든 텍스트를 한 번에 벡터로 변환
    embeddings = model.encode(chunks)
    
    print("✅ 임베딩 변환 완료!\n")
    return embeddings

if __name__ == "__main__":
    # 1. URL에서 텍스트 추출 (앞서 한 작업)
    # test_url = 'http://arxiv.org/pdf/2401.00001v1'
    # extracted_text = download_and_extract_text(test_url)
    
    # 2. 텍스트 청킹 (앞서 한 작업)
    # text_chunks = chunk_text(extracted_text, chunk_size=1000, chunk_overlap=150)
    
    # --- 여기서부터 추가된 실행 코드 ---
    # 3. 33개의 청크를 SBERT 모델에 통과시켜 임베딩(벡터) 추출
    chunk_embeddings = embed_text_chunks(text_chunks)
    
    # 4. 결과 검증 및 확인
    print("📊 [임베딩 결과 데이터 구조 확인]")
    print(f"🔹 변환된 벡터의 총 개수: {len(chunk_embeddings)} 개 (청크 개수와 정확히 일치해야 함)")
    print(f"🔹 1개 벡터의 차원(길이): {len(chunk_embeddings[0])} 차원")
    
    print("-" * 50)
    print("✨ 첫 번째 텍스트 조각이 변환된 실제 벡터값 프리뷰 (앞 5개 숫자만):")
    print(chunk_embeddings[0][:5])
    print("-" * 50)
    # (기존 SBERT 임베딩 코드 맨 아래에 이어서 작성)
from elasticsearch import Elasticsearch

def create_elasticsearch_index():
    print("\n🗄️ 엘라스틱서치 연결 및 인덱스 생성 준비 중...")
    
    # 💡 핵심: localhost 대신 명확한 IPv4 주소인 127.0.0.1 사용
    es = Elasticsearch("http://127.0.0.1:9200")
    
    # 연결 확인 (실패 시 상세 에러를 출력하도록 강화)
    try:
        if es.ping():
            print("✅ 엘라스틱서치와 성공적으로 연결되었습니다!")
        else:
            print("❌ 엘라스틱서치 ping 테스트 실패.")
            return None
    except Exception as e:
        print(f"❌ 엘라스틱서치 연결 중 상세 에러 발생: {e}")
        return None

    index_name = "arxiv_papers"
    
    
    #-------------인덱스 매핑-------------
    
    mapping = {
        "mappings": {
            "properties": {
                "paper_url": {"type": "keyword"},
                "title": {"type": "text"},
                "chunk_id": {"type": "integer"},
                "text_chunk": {"type": "text"},
                "embedding": {
                    "type": "dense_vector",
                    "dims": 384,
                    "index": True,
                    "similarity": "cosine"
                }
            }
        }
    }

    if es.indices.exists(index=index_name):
        es.indices.delete(index=index_name)
        print(f"🗑️ 기존 '{index_name}' 인덱스를 삭제하고 초기화합니다.")

    es.indices.create(index=index_name, body=mapping)
    print(f"🎉 '{index_name}' 인덱스(그릇)가 성공적으로 생성되었습니다!\n")
    
    return es, index_name

if __name__ == "__main__":
    # 1. 테스트용 URL 설정 및 텍스트 추출 (앞서 정상 작동했던 부분)
    test_url = 'http://arxiv.org/pdf/2401.00001v1' 
    extracted_text = download_and_extract_text(test_url)
    
    # 2. 텍스트 청킹 (조각내기)
    text_chunks = chunk_text(extracted_text, chunk_size=1000, chunk_overlap=150)
    
    # 3. SBERT 임베딩 (벡터 변환)
    chunk_embeddings = embed_text_chunks(text_chunks)
    
    # 4. 엘라스틱서치 인덱스 생성 및 안전한 결과 처리 (에러 방지 적용)
    es_result = create_elasticsearch_index()
    
    if es_result is not None:
        es_client, es_index_name = es_result
        print("🚀 완벽합니다! 모든 준비가 끝났습니다.")
    else:
        print("🛑 인덱스 생성에 실패하여 다음 단계로 넘어갈 수 없습니다.")
        # (기존 코드의 맨 아래에 이어서 작성)

def insert_data_to_es(es_client, index_name, text_chunks, chunk_embeddings, paper_url, paper_title):
    print(f"\n📦 '{index_name}' 인덱스에 데이터 저장을 시작합니다...")
    
    success_count = 0
    
    # 조각(chunk)과 벡터(embedding)를 하나씩 짝지어서 엘라스틱서치에 저장
    for i, (chunk, emb) in enumerate(zip(text_chunks, chunk_embeddings)):
        # 엘라스틱서치에 들어갈 문서(Document) 1개의 구조 (JSON 형태)
        doc = {
            "paper_url": paper_url,
            "title": paper_title,
            "chunk_id": i + 1,
            "text_chunk": chunk,
            "embedding": emb.tolist()  # Numpy 배열을 일반 리스트로 변환 (필수!)
        }
        
        # 문서 고유 ID 생성 (예: http://arxiv.org/pdf/2401.00001v1_chunk_1)
        doc_id = f"{paper_url}_chunk_{i+1}"
        
        try:
            # 엘라스틱서치에 데이터 1개 삽입(Index)
            es_client.index(index=index_name, id=doc_id, document=doc)
            success_count += 1
        except Exception as e:
            print(f"❌ {i+1}번째 조각 저장 실패: {e}")
            
    print(f"✅ 총 {success_count}개의 텍스트 조각과 벡터가 완벽하게 저장되었습니다!\n")


if __name__ == "__main__":
    # ... (기존에 작성한 URL 추출, 청킹, 임베딩, 인덱스 생성 코드는 그대로 유지) ...
    
    # 5. 엘라스틱서치 인덱스 생성
    # es_result = create_elasticsearch_index()
    # ...
    
    # --- 여기서부터 추가된 실행 코드 ---
    if es_result is not None:
        es_client, es_index_name = es_result
        
        # 테스트용 임시 논문 제목 (실제 파이프라인에서는 API에서 가져온 제목 사용)
        temp_title = "Sector Rotation by Factor Model and Fundamental Analysis"
        
        # 6. 엘라스틱서치에 데이터 밀어넣기 함수 실행
        insert_data_to_es(
            es_client=es_client,
            index_name=es_index_name,
            text_chunks=text_chunks,
            chunk_embeddings=chunk_embeddings,
            paper_url=test_url,
            paper_title=temp_title
        )
        print("🚀 모든 데이터 파이프라인 구축 완료! 이제 검색 테스트만 남았습니다.")