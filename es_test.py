# 엘라스틱서치 연결 진단 스크립트
#도커에 엘라스틱서치를 띄우고, 스크립트를 실행해서 파이썬 서버와 연결되는지 확인
# 버전이 다를 시에 엘라스틱 서치가 오류가 발생하니 확인하고 실행하세요

import urllib.request
from elasticsearch import Elasticsearch

print("🔍 엘라스틱서치 연결 정밀 진단 시작...\n")

# 1. 파이썬 기본 모듈로 찔러보기 (curl과 같은 역할)
print("--- [테스트 1] 파이썬 기본 네트워크 통신 ---")
try:
    response = urllib.request.urlopen("http://127.0.0.1:9200", timeout=3)
    print("✅ 성공! 엘라스틱서치가 파이썬의 기본 요청에 응답했습니다.")
    print(f"응답 데이터 요약: {response.read().decode('utf-8')[:100]}...\n")
except Exception as e:
    print(f"❌ 실패! 기본 네트워크 에러: {e}\n")

# 2. Elasticsearch 공식 클라이언트로 찔러보기
print("--- [테스트 2] Elasticsearch 라이브러리 통신 ---")
try:
    # 혹시 모를 타임아웃 방지를 위해 시간 넉넉히 설정
    es = Elasticsearch("http://127.0.0.1:9200", request_timeout=10)
    
    # ping() 대신 info()를 호출하면 에러의 진짜 원인을 토해냅니다.
    info = es.info()
    print("✅ 성공! Elasticsearch 라이브러리로 완벽하게 연결되었습니다.")
    print(f"클러스터 이름: {info.get('cluster_name')}")
except Exception as e:
    print(f"❌ 실패! 클라이언트 연결 에러 상세 원인:\n{e}")