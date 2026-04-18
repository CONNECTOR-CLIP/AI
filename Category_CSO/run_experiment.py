# run_experiment.py
"""
CSO Classifier 실험 스크립트
- arxiv_cs_ai.db에서 추출한 100개 cs.AI 논문에 대해
- CSOClassifier(v4.0.0)를 실제 분류기로 연결하여
- tree_builder.py의 3레벨 트리 분류를 실행하고
- 결과를 저장한다.
"""

import json
import os
import sys
import time
import logging
import concurrent.futures
from pathlib import Path
from datetime import datetime

# 경로 설정
BASE_DIR = Path("E:/experiment")
CATEGORY_DIR = Path("E:/Category")
sys.path.insert(0, str(CATEGORY_DIR))

# CSO.3.5.csv 기반 온톨로지 (단어장)
_CSO_ONTO = None

def _get_cso_onto():
    global _CSO_ONTO
    if _CSO_ONTO is None:
        from tree_builder import _CSOOntology
        _CSO_ONTO = _CSOOntology(CATEGORY_DIR / "CSO.3.5.csv")
        log.info("CSO ontology loaded: %d labels, %d synonym pairs",
                 len(_CSO_ONTO.labels), sum(len(v) for v in _CSO_ONTO.synonyms.values()))
    return _CSO_ONTO

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "logs" / "experiment.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ProcessPool worker (top-level — pickle 가능해야 함)
# ---------------------------------------------------------------------------

# worker 프로세스당 한 번만 초기화되는 전역 변수
_worker_cc = None
_worker_cc_synt = None


def _worker_init():
    """ProcessPool initializer: worker 프로세스 당 1회 실행."""
    global _worker_cc, _worker_cc_synt
    sys.path.insert(0, str(Path("E:/Category")))
    from cso_classifier import CSOClassifier
    _worker_cc = CSOClassifier(
        modules="both",
        enhancement="first",
        fast_classification=True,
        delete_outliers=True,
        get_weights=True,
        silent=True,
    )
    _worker_cc_synt = CSOClassifier(
        modules="syntactic",
        enhancement="no",
        fast_classification=True,
        delete_outliers=False,
        get_weights=True,
        silent=True,
    )


def _worker_classify(args: tuple) -> tuple:
    """
    ProcessPool worker: initializer에서 생성된 인스턴스 재사용.
    args = (paper_id, title, abstract, top_k)
    반환 = (paper_id, [{label_id, score}, ...])
    title이 비어있으면 abstract 전체를 abstract로 사용 (reexpress 텍스트 직접 분류 지원).
    """
    paper_id, title, abstract, top_k = args
    # title이 비어있으면 abstract에 전문이 포함된 reexpress 텍스트
    paper_input = {"title": title, "abstract": abstract, "keywords": ""}

    try:
        result = _worker_cc.run(paper_input)
    except Exception:
        try:
            result = _worker_cc_synt.run(paper_input)
        except Exception:
            return paper_id, []

    scores: dict[str, float] = {}
    synt_w = dict(result.get("syntactic_weights", []))
    sema_w = dict(result.get("semantic_weights", []))
    for topic in result.get("union", []):
        s = synt_w.get(topic, 0.0)
        w = sema_w.get(topic, 0.0)
        raw = (s + w) / 2.0 if (s > 0 and w > 0) else max(s, w)
        if raw == 0.0:
            raw = 0.1
        scores[topic] = round(raw, 4)
    for topic in result.get("enhanced", []):
        if topic not in scores:
            scores[topic] = 0.05

    ranked = sorted(scores.items(), key=lambda x: -x[1])
    return paper_id, [{"label_id": t, "score": sc} for t, sc in ranked[:top_k]]


# ---------------------------------------------------------------------------
# CSOClassifier → CFOAdapter 브리지
# ---------------------------------------------------------------------------

class RealCSOClassifier:
    """
    cso_classifier.CSOClassifier를 tree_builder.CFOAdapter가 기대하는
    인터페이스로 감싸는 브리지 클래스.

    CFOAdapter가 introspection으로 탐색하는 메서드:
      classify / predict
      initial_keywords / get_keywords
      parents / get_parents
      info
    """

    def __init__(self):
        log.info("Loading CSOClassifier (both modules, fast_classification=True)...")
        from cso_classifier import CSOClassifier
        self._cc = CSOClassifier(
            modules="both",
            enhancement="first",
            fast_classification=True,
            delete_outliers=True,
            get_weights=True,
            silent=True,
        )
        # syntactic 전용 인스턴스 — both 실패 시 재사용 (매번 새로 생성하지 않음)
        self._cc_synt = CSOClassifier(
            modules="syntactic",
            enhancement="no",
            fast_classification=True,
            delete_outliers=False,
            get_weights=True,
            silent=True,
        )
        # 온톨로지도 미리 로드
        from cso_classifier.ontology import Ontology
        self._onto = Ontology(silent=True)
        log.info("CSOClassifier ready. topics=%d, broaders=%d",
                 len(self._onto.topics), len(self._onto.broaders))

    def classify(self, text: str, top_k: int = 5) -> list[dict]:
        """
        텍스트를 분류하여 [{label_id, score}, ...] 반환.
        CSOClassifier.run() 결과의 'syntactic'+'semantic' union을 점수화.
        """
        # title / abstract 분리 시도 (\\n\\n 구분)
        parts = text.split("\n\n", 1)
        title = parts[0].strip() if len(parts) == 2 else ""
        abstract = parts[1].strip() if len(parts) == 2 else text.strip()

        paper_input = {"title": title, "abstract": abstract, "keywords": ""}
        try:
            result = self._cc.run(paper_input)
        except Exception as e:
            log.warning("CSOClassifier.run error (both): %s — retrying syntactic only", e)
            try:
                result = self._cc_synt.run(paper_input)
            except Exception as e2:
                log.warning("CSOClassifier.run error (syntactic): %s", e2)
                return []

        # 가중치 기반 점수 계산
        # get_weights=True 시 반환 형식: syntactic_weights/semantic_weights = list of (topic, weight)
        scores: dict[str, float] = {}

        synt_w = dict(result.get("syntactic_weights", []))
        sema_w = dict(result.get("semantic_weights", []))

        union = result.get("union", [])
        for topic in union:
            s = synt_w.get(topic, 0.0)
            w = sema_w.get(topic, 0.0)
            raw = (s + w) / 2.0 if (s > 0 and w > 0) else max(s, w)
            if raw == 0.0:
                raw = 0.1
            scores[topic] = round(raw, 4)

        # enhanced (상위 토픽) 추가 - 낮은 점수
        for topic in result.get("enhanced", []):
            if topic not in scores:
                scores[topic] = 0.05

        if not scores:
            return []

        ranked = sorted(scores.items(), key=lambda x: -x[1])
        return [{"label_id": t, "score": s} for t, s in ranked[:top_k]]

    # Pool 주입 (TreeBuilder가 호출)
    def set_pool(self, pool) -> None:
        self._pool = pool

    # TreeBuilder._make_pool이 확인하는 initializer 및 worker 함수
    _pool_initializer = staticmethod(_worker_init)
    _worker_classify_fn = staticmethod(_worker_classify)

    def parallel_classify(
        self,
        papers: list[dict],
        top_k: int = 5,
    ) -> dict[str, list[dict]]:
        """
        주입된 ProcessPool로 논문 병렬 분류 (Pool 재사용 — 초기화 오버헤드 없음).
        pool이 없으면 순차 실행으로 fallback.
        """
        pool = getattr(self, "_pool", None)
        if pool is None:
            # fallback: 순차
            from tree_builder import CFOAdapter, _normalize_text
            results = {}
            for p in papers:
                text = _normalize_text(p["title"] + "\n\n" + p["abstract"])
                results[p["paper_id"]] = self.classify(text, top_k=top_k)
            return results

        args = [
            (p["paper_id"], p.get("title", ""), p.get("abstract", ""), top_k)
            for p in papers
        ]
        results: dict[str, list[dict]] = {}
        for paper_id, res in pool.map(_worker_classify, args):
            results[paper_id] = res
        return results

    def initial_keywords(self, label_id: str) -> list[str]:
        """
        CSO.3.5.csv 기반 단어장에서 키워드 반환.
        label phrase + sameAs/relatedEquivalent 동의어 phrase + children phrase.
        """
        onto = _get_cso_onto()
        # topic_id는 underscore 형식; label_id는 space 형식일 수 있음
        tid = label_id.lower().replace(" ", "_")
        return onto.get_keywords(tid)

    def get_parents(self, label_id: str) -> list[str]:
        """CSO 온톨로지에서 직접 상위 토픽 반환."""
        return list(self._onto.broaders.get(label_id.lower(), []))

    def info(self) -> dict:
        return {
            "name": "CSO Classifier",
            "version": "4.0.0",
            "citations": [
                "Salatino et al., 'The CSO Classifier: Ontology-Driven Detection of Research Topics in Scholarly Articles', TPDL 2019"
            ],
        }


# ---------------------------------------------------------------------------
# 실험 실행
# ---------------------------------------------------------------------------

def run():
    log.info("=" * 60)
    log.info("CSO Tree Builder Experiment START")
    log.info("=" * 60)

    # 1. 입력 데이터 로드
    input_path = BASE_DIR / "data" / "papers_100.json"
    log.info("Loading input: %s", input_path)
    with open(input_path, encoding="utf-8") as f:
        input_data = json.load(f)
    n = len(input_data["input_papers"])
    log.info("Loaded %d papers", n)

    # 2. 분류기 초기화
    cso = RealCSOClassifier()

    # 3. tree_builder 임포트
    from tree_builder import TreeBuilder
    db_path = str(BASE_DIR / "results" / "experiment.db")
    builder = TreeBuilder(cso_instance=cso, db_path=db_path)
    log.info("TreeBuilder initialized. DB: %s", db_path)

    # 4. 분류 실행
    log.info("Running build_tree on %d papers...", n)
    t0 = time.time()
    result = builder.build_tree(input_data)
    elapsed = time.time() - t0
    log.info("build_tree completed in %.1fs", elapsed)

    # 5. 결과 저장
    result_path = BASE_DIR / "results" / "tree_output.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log.info("Tree output saved: %s", result_path)

    # 6. 요약 출력
    v = result["validation"]
    stats = v["stats"]
    log.info("-" * 60)
    log.info("=== RESULTS SUMMARY ===")
    log.info("is_valid         : %s", v["is_valid"])
    log.info("num_input_papers : %d", stats["num_input_papers"])
    log.info("num_roots        : %d", stats["num_roots"])
    log.info("num_intermediate : %d", stats["num_intermediate_nodes"])
    log.info("num_leaves       : %d", stats["num_assigned_leaves"])
    log.info("num_reexpressed  : %d", stats["num_reexpressed"])
    log.info("iterations_used  : %d", stats["iterations_used"])
    log.info("elapsed_sec      : %.1f", elapsed)

    if v["errors"]:
        log.warning("ERRORS (%d):", len(v["errors"]))
        for e in v["errors"]:
            log.warning("  - %s", e)
    if v["warnings"]:
        log.info("Warnings (%d):", len(v["warnings"]))
        for w in v["warnings"][:10]:
            log.info("  - %s", w)

    # 7. 트리 구조 출력
    log.info("-" * 60)
    log.info("=== TREE STRUCTURE ===")
    for root in result["roots"]:
        cat = root["arxiv_primary_category"]
        nodes = root["intermediate_nodes"]
        log.info("ROOT: %s  (%d intermediate nodes)", cat, len(nodes))
        for node in nodes:
            children = node["children"]
            reexpr_count = sum(1 for c in children if c["assignment"]["was_reexpressed"])
            log.info("  [%s] label='%s'  papers=%d  reexpressed=%d",
                     node["node_id"], node["label"], len(children), reexpr_count)
            for leaf in children[:3]:
                pid = leaf["paper_id"]
                score = leaf["assignment"]["score"]
                # title 찾기
                title = next((p["title"][:55] for p in input_data["input_papers"]
                              if p["paper_id"] == pid), pid)
                log.info("    * [%.3f] %s | %s", score, pid, title)
            if len(children) > 3:
                log.info("    ... (%d more)", len(children) - 3)

    # 8. 간단 분석 저장
    analysis = {
        "experiment_time": datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "stats": stats,
        "is_valid": v["is_valid"],
        "errors": v["errors"],
        "warnings": v["warnings"],
        "provenance": result["provenance"],
        "tree_summary": [
            {
                "root": r["arxiv_primary_category"],
                "intermediate_nodes": [
                    {
                        "node_id": n["node_id"],
                        "label": n["label"],
                        "cfo_label_id": n["cfo"]["label_id"],
                        "keywords": n["cfo"]["initial_keywords"][:5],
                        "num_papers": len(n["children"]),
                        "num_reexpressed": sum(
                            1 for c in n["children"] if c["assignment"]["was_reexpressed"]
                        ),
                        "papers": [
                            {
                                "paper_id": c["paper_id"],
                                "score": c["assignment"]["score"],
                                "was_reexpressed": c["assignment"]["was_reexpressed"],
                                "reexpress_iteration": c["assignment"]["reexpress_iteration"],
                                "title": next(
                                    (p["title"] for p in input_data["input_papers"]
                                     if p["paper_id"] == c["paper_id"]), ""
                                ),
                            }
                            for c in n["children"]
                        ],
                    }
                    for n in r["intermediate_nodes"]
                ],
            }
            for r in result["roots"]
        ],
    }

    analysis_path = BASE_DIR / "results" / "analysis.json"
    with open(analysis_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    log.info("Analysis saved: %s", analysis_path)
    log.info("=" * 60)
    log.info("Experiment DONE.")


if __name__ == "__main__":
    run()
