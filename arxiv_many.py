# arXiv PDF 파일 크기 확인 스크립트
# 이 스크립트는 arXiv PDF 파일의 정확한 크기를 바이트 단위로 확인하기 위해 HEAD 요청
# GET 요청과 달리 HEAD 요청

import urllib.request

# 테스트할 arXiv PDF 링크 (예시)
pdf_url = 'https://arxiv.org/pdf/2603.11904v1'

print(f"서버에 파일 크기(Byte) 정보 요청 중... ({pdf_url})")

# GET이 아닌 HEAD 메서드로 요청 객체 생성
req = urllib.request.Request(pdf_url, method='HEAD')

try:
    response = urllib.request.urlopen(req)
    
    # 헤더에서 Content-Length (바이트 수) 추출
    content_length = response.headers.get('Content-Length')
    
    if content_length:
        bytes_size = int(content_length)
        mb_size = bytes_size / (1024 * 1024) # Byte -> MB 변환
        
        print(f"✅ 정확한 파일 크기: {bytes_size:,} Bytes")
        print(f"✅ 메가바이트 환산: 약 {mb_size:.2f} MB")
    else:
        print("서버가 Content-Length 정보를 제공하지 않습니다.")
        
except Exception as e:
    print(f"요청 중 에러 발생: {e}")