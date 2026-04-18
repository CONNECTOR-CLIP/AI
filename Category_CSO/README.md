# 가상환경 생성

python -m venv cso_env
source cso_env/bin/activate # Windows: cso_env\Scripts\activate

# 의존성 설치

pip install cso-classifier jsonschema

# CSO.3.5.csv 다운로드 (26MB, 저장소에 포함 안 됨)

# https://cso.kmi.open.ac.uk/downloads 에서 CSO.3.5.csv 다운로드 후

# tree_builder.py와 같은 폴더에 배치

### 1. 실험 실행 (run_experiment.py)

100편 cs.AI 논문을 분류하고 트리를 생성합니다.

```bash
cd /path/to/repo
python run_experiment.py
```

**출력 파일**:

- `results/tree_output.json` — 전체 트리 (JSON Schema 검증 통과)
- `results/analysis.json` — 통계 요약
- `logs/experiment.log` — 실행 로그

**실행 시간**: 약 30초 (CPU 16코어, workers=4 기준)

---

### 2. TreeBuilder API 직접 사용

`tree_builder.py`를 라이브러리로 사용할 수 있습니다.

#### 최소 예시

```python
import json
from tree_builder import TreeBuilder

# 1. 입력 데이터 준비 (INPUT_SCHEMA 형식)
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

# 2. TreeBuilder 초기화 (cso_instance=None이면 내장 CSO 분류기 사용)
builder = TreeBuilder(db_path="output.db")

# 3. 트리 빌드
result = builder.build_tree(input_data)

# 4. 결과 저장
with open("tree_output.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
```

#### CSOClassifier 연결 예시 (run_experiment.py 패턴)

```python
import sys
sys.path.insert(0, "/path/to/category")

from run_experiment import RealCSOClassifier
from tree_builder import TreeBuilder

cso = RealCSOClassifier()           # CSOClassifier 초기화
builder = TreeBuilder(
    cso_instance=cso,               # 외부 분류기 주입
    db_path="results/output.db"
)
result = builder.build_tree(input_data)
```

#### run_config 커스터마이징

```python
input_data = {
    "run_config": {
        "max_iterations": 3,                    # 재표현 최대 반복 횟수 (기본: 3)
        "top_k": 5,                             # 논문당 상위 K개 토픽 (기본: 5)
        "ambiguity_margin": 0.08,               # soft overlap 판정 margin (기본: 0.08)
        "max_intermediate_nodes_per_root": 3,   # root당 최대 중간 노드 수 (기본: 3)
        "subtopic_expansion_threshold": 10,     # 서브토픽 확장 기준 논문 수 (기본: 10)
        "root_allowlist": ["cs.AI"],            # 처리할 arXiv 카테고리 (기본: ["cs.AI"])
    },
    "input_papers": [...]
}
```

---

### 3. 출력 형식 (OUTPUT_SCHEMA)

```json
{
  "version": "1.0",
  "generated_at": "2026-04-16T03:18:22",
  "roots": [
    {
      "arxiv_primary_category": "cs.AI",
      "intermediate_nodes": [
        {
          "node_id": "cs.AI::large language models::language model",
          "label": "Language Model",
          "expanded_from": "large language models",
          "cfo": {
            "label_id": "language model",
            "initial_keywords": ["language model@en .", "language modeling@en ."]
          },
          "children": [
            {
              "paper_id": "2401.00001",
              "assignment": {
                "cfo_label_id": "language model",
                "score": 1.0,
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
    "warnings": ["Unresolved soft overlaps after 2 iterations: [...]"],
    "stats": {
      "num_input_papers": 100,
      "num_roots": 1,
      "num_intermediate_nodes": 9,
      "num_assigned_leaves": 100,
      "num_reexpressed": 30,
      "iterations_used": 2
    }
  },
  "provenance": {
    "cfo_classifier_info": {"name": "CSO Classifier", "version": "4.0.0"},
    "assumptions": [...],
    "adapter_fallbacks": []
  }
}
```

---

**출력 구조 설명**:

- **`version` / `generated_at`**: 출력 스키마 버전과 트리 생성 시각입니다.
- **`roots`**: arXiv 카테고리별 트리 목록입니다. `root_allowlist`에 지정한 카테고리 수만큼 항목이 생깁니다.
  - **`intermediate_nodes`**: 각 root 아래의 토픽 노드들입니다.
    `node_id`는 `카테고리::상위토픽::하위토픽` 형태의 경로이며, `label`은 사람이 읽기 좋은 표시명입니다. `expanded_from`은 이 노드가 어떤 CSO 상위 토픽에서 파생됐는지를 나타냅니다.
  - **`children`**: 해당 토픽 노드에 배정된 논문 목록입니다. `assignment.score`는 분류 신뢰도(0~1)이고, `was_reexpressed`가 `true`이면 초기 분류가 모호해 재표현 과정을 거쳐 이 노드에 배정됐음을 의미합니다.
- **`validation`**: 스키마 검증 결과와 통계입니다. `warnings`에는 재표현 후에도 해소되지 못한 soft overlap 목록이 기록됩니다. `stats`에서 전체 논문 수, 노드 수, 재표현된 논문 수, 반복 횟수를 한눈에 확인할 수 있습니다.
- **`provenance`**: 분류기 정보와 분류 과정에서 적용된 가정(assumptions), 폴백 발생 여부를 기록합니다. 재현성 확인 시 참고합니다.

---

### 4. 테스트 실행

```bash
cd /path/to/category
pytest test_tree_builder.py -v
# 13 passed
```

테스트는 mock CFO 인스턴스를 사용하므로 CSOClassifier 설치 없이 실행 가능합니다.

---

## 주요 컴포넌트

| 컴포넌트                            | 파일                | 역할                                                        |
| ----------------------------------- | ------------------- | ----------------------------------------------------------- |
| `TreeBuilder`                       | `tree_builder.py`   | 메인 API. `build_tree()` 호출 진입점                        |
| `CFOAdapter`                        | `tree_builder.py`   | 외부 분류기를 introspection으로 래핑. `classify_cache` 내장 |
| `_CSOOntology`                      | `tree_builder.py`   | CSO.3.5.csv 파서. synonyms/preferred/children 제공          |
| `RealCSOClassifier`                 | `run_experiment.py` | CSOClassifier v4.0.0 브리지. ProcessPool 병렬화 지원        |
| `_worker_init` / `_worker_classify` | `run_experiment.py` | ProcessPool worker 초기화 / 분류 함수                       |
| `INPUT_SCHEMA` / `OUTPUT_SCHEMA`    | `schemas.py`        | JSON Schema draft-2020-12 검증                              |

---

## 알려진 제약

- **CSO.3.5.csv 필수**: 저장소에 포함되지 않음. 별도 다운로드 필요 (26MB)
- **Python 3.11 권장**: f-string `list[dict]` 타입 힌트 사용
- **Windows ProcessPool**: `if __name__ == "__main__":` 가드 필요 (run_experiment.py에 이미 포함)
- **노드 구성 비결정성**: CSOClassifier semantic 모듈 특성상 동일 입력에도 실행마다 intermediate 노드 수(5~9개)가 달라질 수 있음
- **soft overlap 완전 해소 불가**: 일부 논문은 2개 이상 노드에 동등하게 강하게 분류되어 reexpress 후에도 미해소

## 활용 예시

### 5. 결과 트리 탐색 — 노드별 논문 목록 출력

`results/tree_output.json`을 불러온 뒤 `roots → intermediate_nodes → children` 순으로 순회합니다. 각 child에서 `paper_id`, `assignment.score`, `assignment.was_reexpressed`를 읽어 노드별 논문 목록과 재표현 여부를 출력할 수 있습니다.

### 6. 특정 토픽의 논문만 필터링

`intermediate_nodes`를 순회하며 `node["label"].lower()`가 원하는 토픽명과 일치하는 노드를 찾고, 해당 노드의 `children`에서 `paper_id`만 추출합니다.

### 7. 재표현(reexpress)된 논문만 추출

모든 `children`을 순회하며 `assignment.was_reexpressed == true`인 항목만 필터링합니다. `assignment.reexpress_iteration` 값으로 몇 번째 반복에서 재표현됐는지도 확인할 수 있습니다.

### 8. 분류 통계 요약 출력

`validation.stats`에 `num_input_papers`, `num_intermediate_nodes`, `num_assigned_leaves`, `num_reexpressed`, `iterations_used`가 있습니다. `validation.warnings` 배열에서 미해소 soft overlap 목록도 확인할 수 있습니다.

### 9. 여러 arXiv 카테고리 동시 처리

`run_config.root_allowlist`에 `["cs.AI", "cs.LG", "cs.CL"]`처럼 여러 카테고리를 지정하면 한 번의 `build_tree()` 호출로 카테고리별 트리가 `result["roots"]`에 각각 생성됩니다.

### 10. 결과를 표 형태로 분석

`roots → intermediate_nodes → children`을 평탄화(flatten)하여 `paper_id`, `node_label`, `score`, `was_reexpressed` 컬럼을 가진 레코드 목록으로 만들면 pandas DataFrame 등으로 바로 활용할 수 있습니다. `score` 기준 내림차순 정렬로 가장 강하게 분류된 논문을 파악할 수 있습니다.
