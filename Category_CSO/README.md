# CSO Category Tree Builder

CSO.3.5 온톨로지 기반 arXiv 논문 3단계 분류 트리 생성기입니다.

## 환경 설정

### Python 설치 확인

```
C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe --version
```

의존성 설치:

```
pip install jsonschema
```

`cso-classifier` 패키지를 외부 분류기로 사용할 경우에만 추가 설치:

```
pip install cso-classifier
```

### CSO.3.5.csv 준비

`CSO.3.5.csv` (약 26MB)는 저장소에 포함되어 있습니다. 없을 경우
[https://cso.kmi.open.ac.uk/downloads](https://cso.kmi.open.ac.uk/downloads) 에서 다운로드 후 `tree_builder.py`와 같은 폴더에 배치하세요.

---

## 파일 구조

| 파일 | 역할 |
|---|---|
| `tree_builder.py` | 메인 API. `build_tree()` 호출 진입점 |
| `schemas.py` | JSON Schema draft-2020-12 정의 (`INPUT_SCHEMA` / `OUTPUT_SCHEMA`) |
| `test_tree_builder.py` | pytest 테스트 (13개, mock CSO 사용) |
| `CSO.3.5.csv` | CSO 온톨로지 원본 데이터 |

`run_experiment.py`는 현재 저장소에 포함되지 않습니다. 아래 "TreeBuilder API 직접 사용" 예시를 통해 직접 실험을 구성할 수 있습니다.

---

## 테스트 실행

```
C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe -m pytest test_tree_builder.py -v
# 13 passed
```

테스트는 mock CSO 인스턴스를 사용하므로 외부 분류기 설치 없이 실행 가능합니다.

---

## CLI 직접 실행

```
C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe tree_builder.py input.json [db_path]
```

`input.json`은 아래 INPUT_SCHEMA 형식의 JSON 파일입니다. 결과는 stdout으로 출력됩니다.

---

## TreeBuilder API 사용

### 최소 예시 (내장 CSO 분류기 사용)

```python
import json
from tree_builder import TreeBuilder

input_data = {
    "input_papers": [
        {
            "paper_id": "2401.00001",
            "title": "Attention Is All You Need",
            "abstract": "We propose a new architecture based solely on attention mechanisms...",
            "arxiv_id": "2401.00001",
            "arxiv_primary_category": "cs.AI",
            "arxiv_categories": ["cs.AI", "cs.LG"],
            "authors": ["Vaswani, A."],
            "year": 2024,
            "source": "arxiv_api"
        }
    ]
}

builder = TreeBuilder(db_path="output.db")
result = builder.build_tree(input_data)

with open("tree_output.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
```

`cso_instance=None`이면 `_CSOClassifier` (CSO.3.5.csv 기반 내장 분류기)가 자동으로 사용됩니다.

### 외부 CSOClassifier 주입 예시

외부 `cso_classifier` 패키지가 있는 경우 `CFOAdapter`를 통해 자동으로 래핑됩니다.

```python
from cso_classifier import CSOClassifier
from tree_builder import TreeBuilder

cso = CSOClassifier()
builder = TreeBuilder(cso_instance=cso, db_path="results/output.db")
result = builder.build_tree(input_data)
```

### 모듈 레벨 편의 함수

```python
from tree_builder import build_tree

result = build_tree(input_data, cso_instance=None, db_path="cfo_tree.db")
```

---

## run_config 파라미터

`input_data["run_config"]`로 동작을 제어합니다. 모든 항목은 선택 사항이며 기본값이 있습니다.

```python
input_data = {
    "run_config": {
        "max_iterations": 2,                    # 재표현 최대 반복 횟수 (기본: 2)
        "top_k": 5,                             # 논문당 상위 K개 토픽 (기본: 5)
        "ambiguity_margin": 0.08,               # soft overlap 판정 margin (기본: 0.08)
        "max_intermediate_nodes_per_root": 3,   # root당 최대 중간 노드 수 (기본: 3, 최대: 3)
        "subtopic_expansion_threshold": 20,     # 노드 확장 기준 논문 수 (기본: 20)
        "max_expansion_depth": 3,               # 서브토픽 재귀 확장 최대 깊이 (기본: 3)
        "allow_arxiv_fetch": False,             # 누락된 primary_category를 arXiv API로 조회 (기본: False)
        "root_allowlist": ["cs.AI"],            # 처리할 arXiv 카테고리 (기본: ["cs.AI"], null이면 전체)
    },
    "input_papers": [...]
}
```

---

## 입력 형식 (INPUT_SCHEMA)

각 논문 객체의 필수 필드:

| 필드 | 타입 | 설명 |
|---|---|---|
| `paper_id` | string | 고유 식별자 (중복 불가) |
| `title` | string | 논문 제목 |
| `abstract` | string | 초록 (빈 문자열 허용이나 품질 저하) |
| `arxiv_id` | string \| null | arXiv ID |
| `arxiv_primary_category` | string \| null | 주 카테고리 (null이면 categories[0] 사용) |
| `arxiv_categories` | string[] | 전체 카테고리 목록 |
| `authors` | string[] | 저자 목록 |
| `year` | integer \| null | 출판 연도 |
| `source` | string | `"arxiv_api"` \| `"arxiv_oai"` \| `"user_search"` \| `"other"` |

---

## 출력 형식 (OUTPUT_SCHEMA)

```json
{
  "version": "1.0",
  "generated_at": "2026-04-26T03:18:22+00:00",
  "roots": [
    {
      "arxiv_primary_category": "cs.AI",
      "intermediate_nodes": [
        {
          "node_id": "cs.AI::machine_learning",
          "label": "Machine Learning",
          "expanded_from": null,
          "rescued_from": null,
          "cfo": {
            "label_id": "machine_learning",
            "initial_keywords": ["machine learning", "neural network"]
          },
          "children": [
            {
              "paper_id": "2401.00001",
              "title": "Attention Is All You Need",
              "assignment": {
                "cfo_label_id": "machine_learning",
                "score": 0.82,
                "was_reexpressed": false,
                "reexpress_iteration": null
              }
            }
          ]
        }
      ]
    }
  ],
  "validation": {
    "is_valid": true,
    "errors": [],
    "warnings": [],
    "stats": {
      "num_input_papers": 10,
      "num_roots": 1,
      "num_intermediate_nodes": 3,
      "num_assigned_leaves": 10,
      "num_reexpressed": 2,
      "iterations_used": 1
    }
  },
  "provenance": {
    "cfo_classifier_info": {"name": "CSO (Computer Science Ontology)", "version": "3.5"},
    "assumptions": ["..."],
    "adapter_fallbacks": []
  }
}
```

### 출력 구조 설명

- **`version` / `generated_at`**: 출력 스키마 버전과 트리 생성 시각(UTC ISO 8601)
- **`roots`**: arXiv 카테고리별 트리 목록. `root_allowlist`에 지정한 카테고리 수만큼 생성됨
- **`intermediate_nodes`**: 각 root 아래의 토픽 노드. `node_id`는 `카테고리::토픽` 형태 경로
  - `expanded_from`: 서브토픽 확장으로 생성된 경우 원래 상위 토픽 ID
  - `rescued_from`: unassigned 구제 노드인 경우 `"unassigned"` 표시
- **`children`**: 해당 토픽 노드에 배정된 논문 목록. `title` 필드 포함
  - `assignment.score`: 분류 신뢰도 (0~1)
  - `assignment.was_reexpressed`: 재표현 과정을 거쳐 배정된 경우 `true`
  - `assignment.reexpress_iteration`: 몇 번째 반복에서 재표현됐는지
- **`validation`**: 스키마 검증 결과와 통계. `errors`가 없으면 `is_valid=true`
- **`provenance`**: 분류기 정보, 적용된 가정, adapter fallback 발생 여부

---

## 주요 컴포넌트

| 컴포넌트 | 파일 | 역할 |
|---|---|---|
| `TreeBuilder` | `tree_builder.py` | 메인 API. `build_tree()` 호출 진입점 |
| `CFOAdapter` | `tree_builder.py` | 외부 분류기를 introspection으로 래핑. `classify_cache` 내장 |
| `_CSOClassifier` | `tree_builder.py` | CSO.3.5.csv 기반 내장 분류기 (외부 분류기 없을 때 자동 사용) |
| `_CSOOntology` | `tree_builder.py` | CSO.3.5.csv 파서. synonyms/preferred/children/parents 제공 |
| `INPUT_SCHEMA` / `OUTPUT_SCHEMA` | `schemas.py` | JSON Schema draft-2020-12 검증 |

---

## 알려진 제약

- **Python 3.11 권장**: f-string `list[dict]` 타입 힌트 사용
- **`run_experiment.py` 없음**: 해당 파일은 저장소에 포함되지 않음. TreeBuilder API를 직접 사용할 것
- **노드 구성 비결정성**: 내장 `_CSOClassifier`는 결정론적이지만, 외부 CSO semantic 모듈 특성상 동일 입력에도 intermediate 노드 수가 달라질 수 있음 (5~9개)
- **soft overlap 완전 해소 불가**: 일부 논문은 재표현 후에도 미해소. `validation.warnings`에 기록됨
- **`subtopic_expansion_threshold` 기본값**: 20편 이상인 노드만 서브토픽 확장 시도
- **Windows ProcessPool**: 외부 분류기가 `parallel_classify`를 지원할 경우 `if __name__ == "__main__":` 가드 필요

---

## 활용 예시

### 노드별 논문 목록 출력

```python
import json

with open("tree_output.json", encoding="utf-8") as f:
    tree = json.load(f)

for root in tree["roots"]:
    for node in root["intermediate_nodes"]:
        print(f"[{node['label']}]")
        for child in node["children"]:
            print(f"  {child['paper_id']}: {child['title']}")
```

### 특정 토픽 논문만 필터링

```python
target = "machine learning"
for root in tree["roots"]:
    for node in root["intermediate_nodes"]:
        if node["label"].lower() == target:
            paper_ids = [c["paper_id"] for c in node["children"]]
```

### 재표현된 논문만 추출

```python
reexpressed = [
    (c["paper_id"], c["assignment"]["reexpress_iteration"])
    for root in tree["roots"]
    for node in root["intermediate_nodes"]
    for c in node["children"]
    if c["assignment"]["was_reexpressed"]
]
```

### 여러 arXiv 카테고리 동시 처리

```python
input_data["run_config"] = {
    "root_allowlist": ["cs.AI", "cs.LG", "cs.CL"]
}
result = builder.build_tree(input_data)
# result["roots"]에 카테고리별 트리가 각각 생성됨
```

### 결과를 pandas DataFrame으로 변환

```python
import pandas as pd

records = [
    {
        "paper_id": c["paper_id"],
        "title": c.get("title", ""),
        "node_label": node["label"],
        "root": root["arxiv_primary_category"],
        "score": c["assignment"]["score"],
        "was_reexpressed": c["assignment"]["was_reexpressed"],
    }
    for root in tree["roots"]
    for node in root["intermediate_nodes"]
    for c in node["children"]
]
df = pd.DataFrame(records).sort_values("score", ascending=False)
```
