# arXiv 논문 검색엔진

arXiv에서 수집한 92만 건의 논문 메타데이터를 자연어로 검색할 수 있는 검색엔진입니다.
제목, 초록, 저자 기준 검색과 카테고리·연도 필터를 지원합니다.

---

## 목차

1. [이 시스템이 하는 일](#1-이-시스템이-하는-일)
2. [전체 구조 이해하기](#2-전체-구조-이해하기)
3. [검색이 동작하는 원리 (BM25)](#3-검색이-동작하는-원리-bm25)
4. [디렉토리 구조](#4-디렉토리-구조)
5. [설치 방법](#5-설치-방법)
6. [처음 시작하기 (최초 1회)](#6-처음-시작하기-최초-1회)
7. [매번 시작하는 방법](#7-매번-시작하는-방법)
8. [검색 테스트 방법](#8-검색-테스트-방법)
9. [DB가 업데이트됐을 때](#9-db가-업데이트됐을-때)
10. [자주 묻는 질문](#10-자주-묻는-질문)

---

## 1. 이 시스템이 하는 일

### 문제 상황
arXiv에서 수집한 논문 데이터가 SQLite 파일(`arxiv_cs_ai.db`)에 저장되어 있습니다.
SQLite는 단순한 데이터 저장에는 훌륭하지만, **"attention mechanism을 다룬 최신 논문 찾아줘"** 같은
자연어 검색에는 적합하지 않습니다.

SQLite로 검색하면 이런 한계가 있습니다:
- 단어가 정확히 일치해야만 찾음 (`LIKE '%attention%'`)
- 결과가 관련도 순으로 정렬되지 않음
- 여러 필드(제목 + 초록 + 저자)를 동시에 검색하기 어려움
- 데이터가 많을수록 느려짐

### 이 시스템의 해결 방법
SQLite 데이터를 **OpenSearch**라는 검색 전문 엔진에 복사해두고, 검색은 OpenSearch에서 합니다.

```
사용자 검색어
     ↓
  FastAPI (검색 API 서버)        ← 나중에 EPIC 4에서 구현 예정
     ↓
  OpenSearch (검색 엔진)         ← 현재 구현 완료
     ↓
  검색 결과 반환

  SQLite (원본 DB)               ← 데이터 보관용, 검색에는 사용 안 함
```

---

## 2. 전체 구조 이해하기

### 두 개의 데이터 저장소

| 저장소 | 파일/서버 | 역할 | 비유 |
|---|---|---|---|
| **SQLite** | `e:/arxiv_cs_ai.db` | 원본 데이터 보관 | 도서관 창고 |
| **OpenSearch** | `localhost:9200` | 빠른 검색 전용 | 도서관 카탈로그 |

책을 찾을 때 창고를 직접 뒤지지 않고 카탈로그(색인)를 먼저 보는 것과 같습니다.
OpenSearch가 그 카탈로그 역할을 합니다.

### 적재(Ingest)란?
SQLite의 원본 데이터를 읽어서 OpenSearch에 복사하는 작업입니다.
**최초 1회**만 하면 되고, 이후에는 DB가 업데이트될 때만 증분 적재합니다.

```
scripts/ingest.py 실행
        ↓
SQLite에서 논문 1,000건씩 읽기
        ↓
OpenSearch에 bulk로 밀어넣기
        ↓
완료 (921,636건, 약 7분 소요)
```

### 레이어드 아키텍처
코드가 역할별로 4개 층(Layer)으로 나뉘어 있습니다.

```
┌─────────────────────────────┐
│  API Layer (app/api/)       │  ← 사용자 요청을 받는 창구 (FastAPI 라우터)
├─────────────────────────────┤
│  Service Layer (app/service/)│  ← 비즈니스 로직 처리
├─────────────────────────────┤
│  Repository Layer           │  ← 데이터베이스/검색엔진 직접 접근
│  (app/repository/)          │
├─────────────────────────────┤
│  Schema Layer (app/schemas/)│  ← 요청/응답 데이터 형태 정의
└─────────────────────────────┘
```

각 층은 바로 아래 층하고만 통신합니다. 예를 들어 API Layer가 OpenSearch를 직접 건드리지 않고,
Service → Repository 순서를 거칩니다. 이렇게 하면 나중에 OpenSearch를 다른 검색엔진으로
바꿔도 Repository Layer만 수정하면 됩니다.

---

## 3. 검색이 동작하는 원리 (BM25)

### BM25란?
BM25(Best Match 25)는 검색엔진에서 가장 널리 쓰이는 **관련도 점수 계산 알고리즘**입니다.
Google, Elasticsearch, OpenSearch가 기본으로 사용합니다.

한 마디로: **"검색어 단어가 문서에 얼마나 많이, 중요한 위치에 나오는가"** 를 숫자로 계산합니다.

### BM25 점수 계산 기준

검색어를 입력하면 OpenSearch는 모든 문서에 점수(score)를 매기고 높은 순으로 반환합니다.

점수에 영향을 주는 요소:

| 요소 | 설명 | 예시 |
|---|---|---|
| **단어 빈도 (TF)** | 문서 안에서 검색어가 많이 나올수록 점수 높음 | abstract에 "attention"이 10번 → "attention"이 1번보다 점수 높음 |
| **문서 빈도 역수 (IDF)** | 희귀한 단어일수록 점수 높음 | "transformer" (특수 용어) > "the" (흔한 단어) |
| **문서 길이** | 짧은 문서에서 나온 단어가 더 의미있음 | 짧은 제목에서 나온 단어 > 긴 초록에서 나온 단어 |

### 검색 대상 필드와 가중치

이 시스템은 논문의 3개 텍스트 필드를 검색합니다:

```
검색어 입력
    ↓
┌─────────────────────────────────────────┐
│  title    (제목)    → 가중치 3배 (boost=3) │  ← 제목에 있으면 점수가 3배
│  abstract (초록)    → 가중치 1배           │
│  authors  (저자명)  → 가중치 1배           │
└─────────────────────────────────────────┘
    ↓
점수 높은 순으로 정렬해서 반환
```

**왜 title을 3배로?**
논문 제목에 검색어가 있다면 그 논문이 핵심 주제를 다루는 경우가 많습니다.
초록에만 잠깐 언급된 논문보다 제목에 있는 논문이 더 관련성이 높습니다.

### 검색 모드

사용자가 검색 범위를 선택할 수 있습니다:

| 모드 | 검색 대상 | 사용 예시 |
|---|---|---|
| `mode=all` | title + abstract + authors 동시 | 일반적인 주제 검색 |
| `mode=title` | 제목만 | 논문 제목을 알고 있을 때 |
| `mode=author` | 저자명만 | 특정 저자 논문 찾을 때 |
| `mode=abstract` | 초록만 | 특정 내용이 포함된 논문 찾을 때 |

### BM25의 한계 (Semantic Search와의 차이)

BM25는 **단어 그 자체**만 봅니다. 의미를 이해하지 못합니다.

```
검색어: "개 훈련"

BM25     → "개", "훈련" 이 단어가 있는 문서만 찾음
Semantic → "puppy training", "반려견 교육", "dog behavior" 도 찾음 (의미 기반)
```

arXiv 논문처럼 **영어 전문 용어가 명확한 도메인**에서는 BM25로도 충분히 좋은 결과가 나옵니다.
의미 기반 검색(Semantic Search)은 향후 EPIC 6에서 추가할 예정입니다.

### 필터 (검색 범위 좁히기)

BM25 점수와 별개로 결과를 필터링할 수 있습니다:

| 필터 | 설명 | 예시 |
|---|---|---|
| `categories` | arXiv 카테고리로 걸러내기 | `cs.AI`, `cs.LG`, `cs.CL` |
| `year_from` / `year_to` | 출판 연도 범위 | 2020년 ~ 2024년 |

필터는 점수에 영향을 주지 않고 **해당 조건을 만족하는 문서만 남깁니다.**

### 정렬

| 정렬 | 기준 |
|---|---|
| `sort=relevance` | BM25 점수 높은 순 (기본값) |
| `sort=latest` | 출판일 최신 순 |

---

## 4. 디렉토리 구조

```
e:/SearchEngine/
│
├── app/                        # FastAPI 애플리케이션
│   ├── api/                    # 라우터 (HTTP 요청 처리)
│   ├── service/                # 비즈니스 로직
│   ├── repository/             # DB·검색엔진 접근
│   │   ├── opensearch_client.py    # OpenSearch 연결
│   │   ├── query_builder.py        # 검색 쿼리 생성
│   │   ├── search_repository.py    # 검색 실행 + 결과 파싱
│   │   └── sqlite_model.py         # SQLite ORM 모델
│   ├── schemas/
│   │   └── search.py               # 요청/응답 데이터 형태
│   └── core/
│       ├── config.py               # 환경변수 설정
│       └── database.py             # SQLite 연결
│
├── scripts/                    # 데이터 관리 스크립트
│   ├── create_index.py             # OpenSearch 인덱스 생성
│   ├── ingest.py                   # 전체 데이터 적재 (최초 1회)
│   ├── ingest_incremental.py       # 증분 적재 (DB 업데이트 시)
│   └── ingest_sample.py            # 샘플 1,000건 적재 (테스트용)
│
├── tests/                      # 테스트 코드
│   ├── test_query_builder.py       # 쿼리 생성 로직 테스트
│   ├── test_schemas.py             # 스키마 검증 테스트
│   └── test_search_repository.py   # 검색 결과 파싱 테스트
│
├── .env                        # 환경변수 (실제 설정값, git에 올리면 안 됨)
├── .env.example                # 환경변수 예시 (git에 올려도 됨)
├── docker-compose.yml          # OpenSearch Docker 실행 설정
├── requirements.txt            # Python 패키지 목록
└── README.md                   # 이 파일
```

---

## 5. 설치 방법

### 필요한 것

| 항목 | 버전 | 확인 방법 |
|---|---|---|
| Python | 3.11 이상 | `python --version` |
| Java | 11 이상 | `java -version` |
| OpenSearch | 2.13.0 | `e:/opensearch-2.13.0/` 에 설치됨 |

### Python 패키지 설치

```bash
cd e:/SearchEngine
pip install -r requirements.txt
```

설치되는 주요 패키지:

| 패키지 | 역할 |
|---|---|
| `fastapi` | API 서버 프레임워크 |
| `uvicorn` | FastAPI 실행 서버 |
| `opensearch-py` | OpenSearch Python 클라이언트 |
| `sqlalchemy` | SQLite ORM |
| `pydantic` | 데이터 검증 |

---

## 6. 처음 시작하기 (최초 1회)

> 이미 완료된 작업입니다. 새 환경에서 처음 세팅할 때만 필요합니다.

### Step 1. OpenSearch 실행

```bash
e:/opensearch-2.13.0/bin/opensearch.bat
```

새 터미널 창에서 실행하고 약 20초 기다립니다.
아래 명령으로 정상 실행 여부를 확인합니다:

```bash
curl http://localhost:9200/_cluster/health
```

결과에 `"status":"green"` 또는 `"status":"yellow"` 가 나오면 정상입니다.

### Step 2. 인덱스 생성

OpenSearch에 논문 데이터를 담을 그릇(인덱스)을 만듭니다.

```bash
cd e:/SearchEngine
python -m scripts.create_index
```

성공 시 출력:
```
[OK] OpenSearch 연결 성공: 2.13.0
[OK] 인덱스 'arxiv_papers' 생성 완료.
[INFO] 등록된 필드: ['abstract', 'all_text', 'arxiv_id', 'authors', 'categories', 'published', 'title']
```

### Step 3. 전체 데이터 적재

SQLite의 921,636건을 OpenSearch에 복사합니다. **약 7분** 소요됩니다.

```bash
python -m scripts.ingest
```

진행 중 출력 예시:
```
[INFO] 적재 대상 논문 수: 921636
[INFO] 진행: 1000 / 921636 (0.1%)  실패: 0  속도: 312건/s  잔여: 2918초
[INFO] 진행: 2000 / 921636 (0.2%)  ...
...
[INFO] 적재 완료 — 성공: 921636, 실패: 0, 소요: 404.0초
[INFO] OpenSearch 인덱스 최종 문서 수: 921636
```

---

## 7. 매번 시작하는 방법

PC를 재부팅하거나 OpenSearch가 꺼졌을 때만 다시 실행하면 됩니다.
**데이터 적재는 다시 할 필요 없습니다.** 데이터는 `e:/opensearch-2.13.0/data/` 에 영구 저장됩니다.

### OpenSearch 재시작

```bash
e:/opensearch-2.13.0/bin/opensearch.bat
```

### 실행 확인

```bash
curl http://localhost:9200/arxiv_papers/_count
```

출력:
```json
{"count": 921636, ...}
```

---

## 8. 검색 테스트 방법

### 방법 A. curl로 직접 테스트

**기본 검색 — "transformer attention" 전체 검색**

```bash
curl -X GET "http://localhost:9200/arxiv_papers/_search?pretty" \
  -H "Content-Type: application/json" \
  -d '{
    "query": {
      "multi_match": {
        "query": "transformer attention",
        "fields": ["title^3", "abstract", "authors"]
      }
    },
    "size": 5
  }'
```

**제목만 검색 — "deep learning"**

```bash
curl -X GET "http://localhost:9200/arxiv_papers/_search?pretty" \
  -H "Content-Type: application/json" \
  -d '{
    "query": { "match": { "title": "deep learning" } },
    "size": 5
  }'
```

**카테고리 필터 + 최신순 정렬**

```bash
curl -X GET "http://localhost:9200/arxiv_papers/_search?pretty" \
  -H "Content-Type: application/json" \
  -d '{
    "query": {
      "bool": {
        "must": [{ "match": { "title": "neural network" } }],
        "filter": [{ "terms": { "categories": ["cs.AI"] } }]
      }
    },
    "sort": [{ "published": { "order": "desc" } }],
    "size": 5
  }'
```

**연도 범위 필터 (2020~2024)**

```bash
curl -X GET "http://localhost:9200/arxiv_papers/_search?pretty" \
  -H "Content-Type: application/json" \
  -d '{
    "query": {
      "bool": {
        "must": [{ "match": { "abstract": "language model" } }],
        "filter": [{
          "range": { "published": { "gte": "2020-01-01", "lte": "2024-12-31" } }
        }]
      }
    },
    "size": 5
  }'
```

---

### 방법 B. Python 코드로 테스트

```bash
cd e:/SearchEngine
python - << 'EOF'
import sys
sys.path.insert(0, ".")
from app.repository.opensearch_client import get_opensearch_client
from app.repository.search_repository import SearchRepository

repo = SearchRepository(get_opensearch_client())

# 전체 검색
result = repo.search("transformer", mode="all", size=5)
print(f"총 {result.total}건 중 {len(result.results)}건 반환\n")
for paper in result.results:
    print(f"  점수: {paper.score:.2f}")
    print(f"  제목: {paper.title}")
    print(f"  저자: {', '.join(paper.authors[:3])}")
    print(f"  출판: {paper.published}")
    print()
EOF
```

**mode별 테스트**

```python
# 제목만 검색
repo.search("attention", mode="title", size=5)

# 저자 검색
repo.search("LeCun", mode="author", size=5)

# 초록 검색
repo.search("diffusion model", mode="abstract", size=5)

# 카테고리 필터
repo.search("neural", categories=["cs.AI", "cs.LG"], size=5)

# 연도 필터
repo.search("bert", year_from=2018, year_to=2020, size=5)

# 최신순 정렬
repo.search("large language model", sort="latest", size=5)

# 페이지네이션 (2페이지, 한 페이지 10건)
repo.search("reinforcement learning", page=2, size=10)
```

---

### 방법 C. 테스트 실행

**단위 테스트** — OpenSearch 없이 로직만 검증 (쿼리 빌더, 스키마, 서비스, API)

```bash
cd e:/SearchEngine
python -m pytest tests/ -v
```

**통합 테스트만** — 실제 OpenSearch + 921,636건 데이터 기준 검증

```bash
python -m pytest tests/test_integration.py -v
```

예상 출력:
```
85 passed in 5.48s
```

테스트 파일별 역할:

| 파일 | 대상 | OpenSearch 필요 |
|---|---|---|
| `test_query_builder.py` | 쿼리 생성 로직 | 불필요 |
| `test_schemas.py` | 요청/응답 스키마 검증 | 불필요 |
| `test_search_repository.py` | 결과 파싱 로직 | 불필요 |
| `test_search_service.py` | 서비스 레이어 | 불필요 |
| `test_api.py` | HTTP 라우터 | 불필요 |
| `test_integration.py` | 전체 흐름 (실제 데이터) | **필요** |

---

## 9. DB가 업데이트됐을 때

SQLite에 새 논문이 추가되거나 기존 논문이 수정/삭제된 경우, OpenSearch에도 반영해야 합니다.
전체를 다시 적재할 필요 없이 **증분 적재**로 처리합니다.

### 케이스별 처리 방법

**케이스 1. 새 논문이 추가된 경우**

`harvested_at` 컬럼(수집 날짜) 기준으로 특정 날짜 이후 논문만 적재합니다.

```bash
# 2024-06-01 이후 수집된 논문 추가
python -m scripts.ingest_incremental --since 2024-06-01
```

이미 OpenSearch에 있는 논문은 자동으로 덮어씁니다(upsert).

**케이스 2. 논문 내용이 수정된 경우**

같은 `arxiv_id`로 다시 적재하면 자동 덮어씁니다. 케이스 1과 동일하게 처리합니다.

**케이스 3. 논문이 삭제된 경우**

SQLite에서 `is_deleted=1` 로 표시된 논문을 OpenSearch에서도 삭제합니다.

```bash
python -m scripts.ingest_incremental --delete-only
```

**케이스 4. 신규 추가 + 삭제 동시 처리**

```bash
python -m scripts.ingest_incremental --since 2024-06-01 --delete
```

**케이스 5. 처음부터 전체 재적재 (필요한 경우)**

인덱스 구조(매핑)를 바꾸거나 데이터를 완전히 새로 구성할 때만 사용합니다.

```bash
python -m scripts.create_index --force   # 인덱스 삭제 후 재생성
python -m scripts.ingest                 # 전체 재적재 (약 7분)
```

---

## 10. 자주 묻는 질문

**Q. OpenSearch를 껐다가 켜면 데이터가 사라지나요?**

아닙니다. 데이터는 `e:/opensearch-2.13.0/data/` 폴더에 영구 저장됩니다.
재시작해도 적재는 다시 할 필요 없습니다.

---

**Q. SQLite 파일을 직접 수정하면 OpenSearch에 자동으로 반영되나요?**

아닙니다. 자동 동기화는 없습니다. SQLite를 수정한 후에는 수동으로 증분 적재를 실행해야 합니다.

```bash
python -m scripts.ingest_incremental --since YYYY-MM-DD
```

---

**Q. 검색 결과가 없거나 이상할 때 확인 방법은?**

```bash
# 1. OpenSearch 살아있는지 확인
curl http://localhost:9200/_cluster/health

# 2. 인덱스 문서 수 확인
curl http://localhost:9200/arxiv_papers/_count

# 3. 샘플 문서 1건 확인
curl "http://localhost:9200/arxiv_papers/_search?size=1&pretty"
```

---

**Q. BM25와 Semantic Search의 차이는 무엇인가요?**

| | BM25 (현재) | Semantic Search (향후) |
|---|---|---|
| 방식 | 단어 일치 기반 | 문장 의미 기반 |
| 속도 | 빠름 | 느림 |
| 동의어 처리 | 안 됨 | 됨 |
| 예시 | "neural net" 검색 시 "neural network" 못 찾음 | "neural net" 검색 시 "neural network" 찾음 |

---

**Q. 카테고리 목록을 어떻게 알 수 있나요?**

```bash
curl -X GET "http://localhost:9200/arxiv_papers/_search?pretty" \
  -H "Content-Type: application/json" \
  -d '{
    "size": 0,
    "aggs": {
      "categories": {
        "terms": { "field": "categories", "size": 50 }
      }
    }
  }'
```

자주 쓰이는 카테고리:

| 카테고리 | 분야 |
|---|---|
| `cs.AI` | 인공지능 |
| `cs.LG` | 머신러닝 |
| `cs.CL` | 자연어처리 |
| `cs.CV` | 컴퓨터 비전 |
| `cs.IR` | 정보 검색 |
| `cs.RO` | 로보틱스 |
| `stat.ML` | 통계적 머신러닝 |
