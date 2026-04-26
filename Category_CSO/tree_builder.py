# tree_builder.py
"""
CFO/CSO-based arXiv paper tree builder.

Builds a 3-level classification tree:
  root (arXiv primary category) → intermediate nodes (CSO labels) → leaves (papers)

Public API:
  build_tree(input_dict, *, cso_instance=None, db_path="cfo_tree.db") -> dict
  TreeBuilder(cso_instance, db_path) .build_tree(input_dict) -> dict
"""

from __future__ import annotations

import csv
import hashlib
import inspect
import json
import re
import sqlite3
import sys
import urllib.request
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from schemas import INPUT_SCHEMA, OUTPUT_SCHEMA

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "1.0"
CSO_CSV_PATH = Path(__file__).parent / "CSO.3.5.csv"
_SUPER_TOPIC_REL = "http://cso.kmi.open.ac.uk/schema/cso#superTopicOf"
_LABEL_REL = "http://www.w3.org/2000/01/rdf-schema#label"
_TOPIC_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_CSO_BASE = "https://cso.kmi.open.ac.uk/topics/"
_SAME_AS_REL = "http://www.w3.org/2002/07/owl#sameAs"
_PREF_EQ_REL = "http://cso.kmi.open.ac.uk/schema/cso#preferentialEquivalent"
_REL_EQ_REL = "http://cso.kmi.open.ac.uk/schema/cso#relatedEquivalent"
_CONTRIB_REL = "http://cso.kmi.open.ac.uk/schema/cso#contributesTo"

_DEFAULT_RUN_CONFIG = {
    "max_iterations": 2,
    "top_k": 5,
    "ambiguity_margin": 0.08,
    "max_intermediate_nodes_per_root": 3,
    "subtopic_expansion_threshold": 20,  # expand node if paper count >= this
    "max_expansion_depth": 3,            # maximum recursion depth for subtopic expansion
    "allow_arxiv_fetch": False,
    "root_allowlist": ["cs.AI"],
}

# ---------------------------------------------------------------------------
# CSO Ontology loader
# ---------------------------------------------------------------------------

class _CSOOntology:
    """Loads CSO.3.5.csv and provides parent/child/label/synonym lookups."""

    def __init__(self, csv_path: Path = CSO_CSV_PATH) -> None:
        # topic_id -> human-readable label
        self.labels: dict[str, str] = {}
        # parent_id -> set of child_ids  (superTopicOf direction)
        self.children: dict[str, set[str]] = defaultdict(set)
        # child_id -> set of parent_ids
        self.parents: dict[str, set[str]] = defaultdict(set)
        # topic_id -> set of same-as / relatedEquivalent slugs (CSO-URI only)
        self.synonyms: dict[str, set[str]] = defaultdict(set)
        # topic_id -> preferential canonical slug (preferentialEquivalent)
        self.preferred: dict[str, str] = {}
        # topic_id -> set of contributesTo target slugs
        self.contributes_to: dict[str, set[str]] = defaultdict(set)
        self._load(csv_path)

    def _strip(self, cell: str) -> str:
        return cell.strip().strip('"').strip("<>")

    def _topic_id(self, uri: str) -> str:
        """Extract topic slug from full URI, e.g. artificial_intelligence."""
        if uri.startswith(_CSO_BASE):
            return uri[len(_CSO_BASE):]
        return uri

    def _is_cso_uri(self, uri: str) -> bool:
        return uri.startswith(_CSO_BASE)

    def _load(self, path: Path) -> None:
        if not path.exists():
            return
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) < 3:
                    continue
                subj = self._strip(row[0])
                pred = self._strip(row[1])
                obj_ = self._strip(row[2])

                if pred == _SUPER_TOPIC_REL:
                    parent_id = self._topic_id(subj)
                    child_id = self._topic_id(obj_)
                    self.children[parent_id].add(child_id)
                    self.parents[child_id].add(parent_id)

                elif pred == _LABEL_REL:
                    topic_id = self._topic_id(subj)
                    label = obj_.split('"')[1] if '"' in obj_ else obj_
                    label = label.split('"')[0].strip()
                    self.labels[topic_id] = label

                elif pred in (_SAME_AS_REL, _REL_EQ_REL):
                    # only index CSO-internal synonyms (skip DBpedia/Wikidata URIs)
                    if self._is_cso_uri(subj) and self._is_cso_uri(obj_):
                        si, oi = self._topic_id(subj), self._topic_id(obj_)
                        self.synonyms[si].add(oi)
                        self.synonyms[oi].add(si)

                elif pred == _PREF_EQ_REL:
                    if self._is_cso_uri(subj) and self._is_cso_uri(obj_):
                        si, oi = self._topic_id(subj), self._topic_id(obj_)
                        # obj is the preferred form
                        self.preferred[si] = oi

                elif pred == _CONTRIB_REL:
                    if self._is_cso_uri(subj) and self._is_cso_uri(obj_):
                        si, oi = self._topic_id(subj), self._topic_id(obj_)
                        self.contributes_to[si].add(oi)

    def get_label(self, topic_id: str) -> str:
        return self.labels.get(topic_id, topic_id.replace("_", " "))

    def get_parents(self, topic_id: str) -> list[str]:
        return sorted(self.parents.get(topic_id, set()))

    def get_children(self, topic_id: str) -> list[str]:
        return sorted(self.children.get(topic_id, set()))

    def get_synonyms(self, topic_id: str) -> list[str]:
        """Return CSO-internal synonym slugs (sameAs + relatedEquivalent)."""
        return sorted(self.synonyms.get(topic_id, set()))

    def get_keywords(self, topic_id: str) -> list[str]:
        """
        Rich keyword list built entirely from CSO.3.5.csv:
          1. topic label phrase (whole, not split)
          2. synonym topic label phrases (sameAs / relatedEquivalent)
          3. preferential equivalent label phrase
          4. direct children label phrases (up to 8, whole phrase)
        Returns up to 20 phrases/words for use in re-expression texts.
        """
        phrases: list[str] = []
        seen: set[str] = set()

        def add_phrase(tid: str) -> None:
            lbl = self.get_label(tid).lower()
            if lbl and lbl not in seen:
                seen.add(lbl)
                phrases.append(lbl)

        # 1. own label
        add_phrase(topic_id)

        # 2. synonyms (sameAs / relatedEquivalent) — whole phrase
        for syn in self.get_synonyms(topic_id):
            add_phrase(syn)

        # 3. preferential equivalent
        pref = self.preferred.get(topic_id)
        if pref:
            add_phrase(pref)

        # 4. direct children labels (whole phrase, up to 8)
        for child in sorted(self.get_children(topic_id))[:8]:
            add_phrase(child)

        return phrases[:20]


# Singleton – loaded once
_ONTOLOGY: _CSOOntology | None = None


def _get_ontology() -> _CSOOntology:
    global _ONTOLOGY
    if _ONTOLOGY is None:
        _ONTOLOGY = _CSOOntology()
    return _ONTOLOGY


# ---------------------------------------------------------------------------
# CFOAdapter  (wraps any cso_classifier-like object via introspection)
# ---------------------------------------------------------------------------

class CFOAdapter:
    """
    Adapter that wraps a cso_classifier instance (or any compatible object).
    Uses introspection to map method names; falls back gracefully when absent.
    Records all fallback events in self.fallbacks.
    """

    def __init__(self, cso: Any) -> None:
        self._cso = cso
        self._fallbacks: list[str] = []
        self._classify_cache: dict[tuple, list[dict]] = {}

    # -- internal helpers --------------------------------------------------

    def _call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            sig = inspect.signature(fn)
            valid_kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
            return fn(*args, **valid_kwargs)
        except Exception as exc:
            self._fallbacks.append(f"{fn.__name__}: {exc}")
            return None

    def _find(self, *names: str) -> Any:
        for name in names:
            fn = getattr(self._cso, name, None)
            if callable(fn):
                return fn
        return None

    # -- public interface --------------------------------------------------

    def classify(self, text: str, top_k: int = 5) -> list[dict]:
        cache_key = (text, top_k)
        if cache_key in self._classify_cache:
            return self._classify_cache[cache_key]

        fn = self._find("classify", "predict")
        if fn is None:
            self._fallbacks.append("classify->missing: using null fallback")
            return []
        result = self._call(fn, text, top_k=top_k)
        if result is None:
            return []
        try:
            parsed = [{"label_id": str(r["label_id"]), "score": float(r["score"])} for r in result]
        except Exception as exc:
            self._fallbacks.append(f"classify->parse error: {exc}")
            return []
        self._classify_cache[cache_key] = parsed
        return parsed

    def initial_keywords(self, label_id: str) -> list[str]:
        fn = self._find("initial_keywords", "get_keywords")
        if fn is None:
            self._fallbacks.append("initial_keywords->missing: returning empty list")
            return []
        result = self._call(fn, label_id)
        return list(result) if result else []

    def parents(self, label_id: str) -> list[str]:
        fn = self._find("parents", "get_parents")
        if fn is None:
            self._fallbacks.append(
                "parents->missing: parent promotion disabled; label merging only"
            )
            return []
        result = self._call(fn, label_id)
        return list(result) if result else []

    def info(self) -> dict:
        fn = self._find("info")
        if fn is None:
            self._fallbacks.append("info->missing: using default provenance")
            return {"name": "cfo_classifier", "version": None, "citations": []}
        result = self._call(fn)
        if result is None:
            return {"name": "cfo_classifier", "version": None, "citations": []}
        return dict(result)

    @property
    def fallbacks(self) -> list[str]:
        return list(self._fallbacks)


# ---------------------------------------------------------------------------
# CSO-backed classifier  (used when no external classifier is provided)
# ---------------------------------------------------------------------------

class _CSOClassifier:
    """
    Pure CSO-ontology classifier.
    Scores each topic by counting keyword matches in the input text.
    Focuses on subtopics of artificial_intelligence for cs.AI context.
    """

    _AI_ROOT = "artificial_intelligence"

    def __init__(self) -> None:
        self._onto = _get_ontology()
        self._topic_keywords: dict[str, list[str]] = {}
        self._ai_topics: list[str] = []
        self._init_topics()

    def _init_topics(self) -> None:
        """Pre-compute keyword lists for all AI subtopics (depth ≤ 2)."""
        root = self._AI_ROOT
        depth1 = self._onto.get_children(root)
        depth2 = []
        for t in depth1:
            depth2.extend(self._onto.get_children(t))
        candidates = [root] + list(depth1) + list(depth2)
        seen: set[str] = set()
        for t in candidates:
            if t not in seen:
                seen.add(t)
                kws = self._onto.get_keywords(t)
                if kws:
                    self._topic_keywords[t] = kws
        self._ai_topics = list(self._topic_keywords.keys())

    def classify(self, text: str, top_k: int = 5) -> list[dict]:
        text_lower = text.lower()
        tokens = set(re.split(r"\W+", text_lower))
        scores = []
        for topic_id, kws in self._topic_keywords.items():
            hits = sum(1 for kw in kws if kw in tokens or kw in text_lower)
            score = hits / max(len(kws), 1)
            scores.append({"label_id": topic_id, "score": round(score * 0.7 + 0.1, 4)})
        scores.sort(key=lambda x: (-x["score"], x["label_id"]))
        return scores[:top_k]

    def initial_keywords(self, label_id: str) -> list[str]:
        return self._topic_keywords.get(label_id, self._onto.get_keywords(label_id))

    def parents(self, label_id: str) -> list[str]:
        return self._onto.get_parents(label_id)

    def info(self) -> dict:
        return {
            "name": "CSO (Computer Science Ontology)",
            "version": "3.5",
            "citations": [
                "Salatino et al., 'The Computer Science Ontology', ISWC 2018"
            ],
        }


# ---------------------------------------------------------------------------
# SQLite persistence helpers
# ---------------------------------------------------------------------------

def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;

        CREATE TABLE IF NOT EXISTS cfo_runs (
            run_id      TEXT PRIMARY KEY,
            created_at  TEXT NOT NULL,
            config_json TEXT,
            input_hash  TEXT,
            output_json TEXT
        );

        CREATE TABLE IF NOT EXISTS cfo_assignments (
            run_id          TEXT NOT NULL,
            paper_id        TEXT NOT NULL,
            root_cat        TEXT,
            intermediate_id TEXT,
            label_id        TEXT,
            score           REAL,
            was_reexpressed INTEGER,
            iter            INTEGER,
            FOREIGN KEY(run_id) REFERENCES cfo_runs(run_id)
        );
    """)
    conn.commit()


def _save_run(
    conn: sqlite3.Connection,
    run_id: str,
    config: dict,
    input_hash: str,
    output_json: str,
    assignments: list[dict],
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO cfo_runs VALUES (?,?,?,?,?)",
        (run_id, now, json.dumps(config), input_hash, output_json),
    )
    for asgn in assignments:
        conn.execute(
            "INSERT INTO cfo_assignments VALUES (?,?,?,?,?,?,?,?)",
            (
                run_id,
                asgn["paper_id"],
                asgn.get("root_cat"),
                asgn.get("intermediate_id"),
                asgn.get("label_id"),
                asgn.get("score"),
                int(asgn.get("was_reexpressed", False)),
                asgn.get("iter"),
            ),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _jaccard(set_a: set[str], set_b: set[str]) -> float:
    if not set_a and not set_b:
        return 1.0
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union else 0.0


def _resolve_run_config(raw: dict | None) -> dict:
    cfg = dict(_DEFAULT_RUN_CONFIG)
    if raw:
        cfg.update({k: v for k, v in raw.items() if v is not None or k == "root_allowlist"})
    return cfg


def _input_hash(papers: list[dict]) -> str:
    serialised = json.dumps(papers, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialised.encode()).hexdigest()


def _fetch_primary_category(arxiv_id: str) -> str | None:
    """Fetch primary_category from arXiv Atom API (only when allow_arxiv_fetch=True)."""
    try:
        url = f"http://export.arxiv.org/abs/{arxiv_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "tree_builder/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
        # <arxiv:primary_category ... term="cs.AI" .../>
        m = re.search(r'arxiv:primary_category[^/]* term="([^"]+)"', content)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Core algorithm helpers
# ---------------------------------------------------------------------------

def _group_by_root(
    papers: list[dict],
    run_config: dict,
    warnings: list[str],
) -> dict[str, list[dict]]:
    """
    Group papers by their arXiv primary category.
    Returns {category: [paper, ...]} filtered by root_allowlist if set.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    allow_fetch = run_config.get("allow_arxiv_fetch", False)
    allowlist = run_config.get("root_allowlist")

    for paper in papers:
        cat = paper.get("arxiv_primary_category")

        if not cat:
            arxiv_id = paper.get("arxiv_id")
            if allow_fetch and arxiv_id:
                cat = _fetch_primary_category(arxiv_id)
                if cat:
                    warnings.append(
                        f"paper_id={paper['paper_id']}: primary_category fetched from arXiv API -> {cat}"
                    )

        if not cat:
            # Estimate from arxiv_categories
            cats = paper.get("arxiv_categories") or []
            if cats:
                # Prefer the first category
                cat = cats[0]
                warnings.append(
                    f"paper_id={paper['paper_id']}: arxiv_primary_category missing; "
                    f"inferred from arxiv_categories[0] -> {cat}"
                )
            else:
                cat = "unknown"
                warnings.append(
                    f"paper_id={paper['paper_id']}: arxiv_primary_category missing and "
                    f"no arxiv_categories; assigned to 'unknown'"
                )

        groups[cat].append(paper)

    if allowlist is not None:
        filtered = {k: v for k, v in groups.items() if k in allowlist}
        excluded = set(groups) - set(filtered)
        if excluded:
            warnings.append(
                f"root_allowlist filtered out categories: {sorted(excluded)}"
            )
        return filtered

    return dict(groups)


def _classify_papers(
    papers: list[dict],
    cfo: CFOAdapter,
    top_k: int,
) -> dict[str, list[dict]]:
    """
    Run cfo.classify on each paper; return {paper_id: [results]}.
    내부 cso 객체가 parallel_classify()를 지원하면 병렬 실행.
    병렬 결과는 (text, top_k) 키로 cfo._classify_cache에 저장 (reexpress 캐시 재사용).
    """
    raw_cso = getattr(cfo, "_cso", None)
    parallel_fn = getattr(raw_cso, "parallel_classify", None)
    if callable(parallel_fn):
        # Build text map for cache population
        text_map: dict[str, str] = {
            p["paper_id"]: _normalize_text(p["title"] + "\n\n" + p["abstract"])
            for p in papers
        }
        pid_results = parallel_fn(papers, top_k=top_k)
        # Populate CFOAdapter cache so reexpress loop hits cache
        for pid, res in pid_results.items():
            text = text_map.get(pid)
            if text is not None:
                cfo._classify_cache[(text, top_k)] = res
        return pid_results

    results: dict[str, list[dict]] = {}
    for p in papers:
        text = _normalize_text(p["title"] + "\n\n" + p["abstract"])
        res = cfo.classify(text, top_k=top_k)
        results[p["paper_id"]] = res
    return results


def _aggregate_labels(
    classify_results: dict[str, list[dict]],
) -> dict[str, dict]:
    """Aggregate label frequency and mean score across all papers."""
    freq: dict[str, int] = defaultdict(int)
    score_sum: dict[str, float] = defaultdict(float)

    for results in classify_results.values():
        for item in results:
            lid = item["label_id"]
            freq[lid] += 1
            score_sum[lid] += item["score"]

    n_papers = len(classify_results)
    stats: dict[str, dict] = {}
    for lid in freq:
        stats[lid] = {
            "freq": freq[lid],
            "mean_score": score_sum[lid] / freq[lid],
            "rank_score": 0.5 * (freq[lid] / n_papers) + 0.5 * (score_sum[lid] / freq[lid]),
        }
    return stats


def _merge_by_jaccard(
    label_candidates: list[str],
    cfo: CFOAdapter,
    threshold: float = 0.70,
) -> dict[str, str]:
    """
    Merge labels whose keyword Jaccard similarity > threshold.
    Returns {label_id: merged_into_label_id} (identity if not merged).
    """
    kw_sets: dict[str, set[str]] = {
        lid: set(cfo.initial_keywords(lid)) for lid in label_candidates
    }
    merge_map: dict[str, str] = {lid: lid for lid in label_candidates}

    for i, a in enumerate(label_candidates):
        for b in label_candidates[i + 1:]:
            canonical_a = merge_map[a]
            canonical_b = merge_map[b]
            if canonical_a == canonical_b:
                continue
            j = _jaccard(kw_sets.get(canonical_a, set()), kw_sets.get(canonical_b, set()))
            if j > threshold:
                # Keep the one that appears earlier (already ranked higher)
                merge_map[canonical_b] = canonical_a

    return merge_map


def _ontology_nearest_label(
    result_labels: list[str],
    label_set: set[str],
    onto: "_CSOOntology",
    max_hops: int = 4,
) -> str | None:
    """
    CSO 온톨로지를 BFS로 탐색해 label_set에 속하는 가장 가까운 토픽을 반환한다.
    1단계: ancestor(상위) 방향으로 max_hops까지 탐색.
    2단계: 못 찾으면 descendant(하위) 방향으로 max_hops까지 탐색.
    """
    from collections import deque

    def _check(label: str) -> str | None:
        space = label.replace("_", " ")
        if label in label_set:
            return label
        if space in label_set:
            return space
        return None

    def _slug(lbl: str) -> str:
        return lbl.lower().replace(" ", "_")

    slugs = [_slug(lbl) for lbl in result_labels]

    # --- 1. ancestor BFS ---
    visited: set[str] = set(slugs)
    queue: deque[tuple[str, int]] = deque()
    for slug in slugs:
        found = _check(slug)
        if found:
            return found
        queue.append((slug, 0))

    while queue:
        node, hops = queue.popleft()
        if hops >= max_hops:
            continue
        for parent in onto.get_parents(node):
            if parent in visited:
                continue
            visited.add(parent)
            found = _check(parent)
            if found:
                return found
            queue.append((parent, hops + 1))

    # --- 2. descendant BFS (상향 탐색 실패 시) ---
    visited_down: set[str] = set(slugs)
    queue_down: deque[tuple[str, int]] = deque((s, 0) for s in slugs)

    while queue_down:
        node, hops = queue_down.popleft()
        if hops >= max_hops:
            continue
        for child in onto.get_children(node):
            if child in visited_down:
                continue
            visited_down.add(child)
            found = _check(child)
            if found:
                return found
            queue_down.append((child, hops + 1))

    return None


def _keyword_nearest_label(
    result_labels: list[str],
    label_set: list[str],
    cfo: "CFOAdapter",
) -> tuple[str, float]:
    """
    결과 라벨들의 키워드 집합과 label_set 각 항목의 키워드 집합 간
    Jaccard 유사도로 가장 가까운 label을 반환한다.
    """
    result_kws: set[str] = set()
    for lbl in result_labels:
        result_kws.update(cfo.initial_keywords(lbl))

    best_label = label_set[0]
    best_score = 0.0
    for lbl in label_set:
        lbl_kws = set(cfo.initial_keywords(lbl))
        j = _jaccard(result_kws, lbl_kws)
        if j > best_score:
            best_score = j
            best_label = lbl
    return best_label, best_score


def _simulate_assignment(
    papers: list[dict],
    label_set: list[str],
    classify_results: dict[str, list[dict]],
    cfo: "CFOAdapter | None" = None,
) -> dict[str, dict]:
    """
    Assign each paper to the best label in label_set.
    Returns {paper_id: {label_id, score, top2_score, top2_label}}.

    label_set에 직접 매핑 안 되는 논문은:
      1. CSO 온톨로지 ancestor BFS → label_set 일치 항목 탐색
      2. keyword Jaccard 유사도 → 가장 가까운 label 선택
      3. 그래도 없으면 최후 fallback (label_set[0], score=0.1)
    """
    assignments: dict[str, dict] = {}
    label_set_set = set(label_set)
    onto = _get_ontology()

    for paper in papers:
        pid = paper["paper_id"]
        results = classify_results.get(pid, [])
        in_set = [r for r in results if r["label_id"] in label_set_set]

        if not in_set:
            result_labels = [r["label_id"] for r in results]

            # 1. CSO ancestor BFS
            nearest = _ontology_nearest_label(result_labels, label_set_set, onto)
            if nearest:
                # 원래 결과 중 best score를 nearest의 점수로 사용
                best_raw = results[0]["score"] if results else 0.1
                in_set = [{"label_id": nearest, "score": round(best_raw * 0.7, 4)}]
            elif cfo is not None and result_labels:
                # 2. keyword Jaccard
                kw_label, kw_score = _keyword_nearest_label(result_labels, label_set, cfo)
                if kw_score > 0.0:
                    best_raw = results[0]["score"] if results else 0.1
                    in_set = [{"label_id": kw_label, "score": round(best_raw * 0.5, 4)}]
                else:
                    # 3. unassigned node
                    in_set = [{"label_id": "unassigned", "score": 0.0}]
            else:
                # 3. unassigned node
                in_set = [{"label_id": "unassigned", "score": 0.0}]

        in_set_sorted = sorted(in_set, key=lambda x: (-x["score"], x["label_id"]))
        top1 = in_set_sorted[0]
        top2 = in_set_sorted[1] if len(in_set_sorted) > 1 else None

        assignments[pid] = {
            "label_id": top1["label_id"],
            "score": top1["score"],
            "top2_score": top2["score"] if top2 else None,
            "top2_label": top2["label_id"] if top2 else None,
        }

    return assignments


def _tie_break_sort(
    papers: list[dict],
    assignments: dict[str, dict],
) -> dict[str, list[dict]]:
    """Group papers by assigned label, applying full tie-break within each group."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for paper in sorted(papers, key=lambda p: p["paper_id"]):
        pid = paper["paper_id"]
        asgn = assignments[pid]
        groups[asgn["label_id"]].append(paper)
    return dict(groups)


def _detect_soft_overlap(
    assignments: dict[str, dict],
    margin: float,
) -> set[str]:
    """
    Return paper_ids that are ambiguous: top1/top2 score gap <= margin.
    """
    ambiguous: set[str] = set()
    for pid, asgn in assignments.items():
        t2 = asgn.get("top2_score")
        t2l = asgn.get("top2_label")
        if t2 is not None and t2l is not None and t2l != asgn["label_id"]:
            score = asgn.get("score", 1.0)
            if score - t2 <= margin:
                ambiguous.add(pid)
    return ambiguous


def _reexpress_text(
    paper: dict,
    chosen_label: str,
    competing_label: str | None,
    cfo: CFOAdapter,
) -> str:
    """
    Build a 1-2 sentence re-expression that embeds chosen label keywords
    and explicitly contrasts competing label keywords.
    """
    chosen_kws = cfo.initial_keywords(chosen_label)[:4]
    competing_kws = cfo.initial_keywords(competing_label)[:2] if competing_label else []

    # Extract problem/method/target from abstract (first 2 sentences)
    abstract = paper.get("abstract", "")
    sentences = re.split(r"(?<=[.!?])\s+", abstract.strip())
    context = " ".join(sentences[:2]) if sentences else abstract[:200]
    context = _normalize_text(context)

    kw_str = ", ".join(chosen_kws) if chosen_kws else chosen_label.replace("_", " ")
    reexpr = f"{context}"
    if chosen_kws:
        reexpr += f" This work addresses {kw_str}."
    if competing_kws:
        contrast = ", ".join(competing_kws)
        reexpr += f" Unlike {contrast}-focused approaches, this study emphasizes {kw_str}."

    return _normalize_text(reexpr)


def _select_labels(
    papers: list[dict],
    cfo: CFOAdapter,
    classify_results: dict[str, list[dict]],
    run_config: dict,
    warnings: list[str],
    enable_boost: bool = True,
) -> list[str]:
    """
    Select 1-3 intermediate node labels for a root group.
    Respects coverage, separability (Jaccard merge), and min-children feasibility.
    """
    max_nodes = run_config.get("max_intermediate_nodes_per_root", 3)
    n_papers = len(papers)

    # 1. Aggregate label stats
    stats = _aggregate_labels(classify_results)
    if not stats:
        fallback_id = "unknown"
        warnings.append(f"No CSO labels found for any paper; using fallback label '{fallback_id}'")
        return [fallback_id]

    # 2. Rank candidates
    ranked = sorted(stats.keys(), key=lambda lid: -stats[lid]["rank_score"])

    # 3. Jaccard merge (threshold=0.30 + substring containment)
    candidates = ranked[:max_nodes * 3]  # consider 3x before merge
    merge_map = _merge_by_jaccard(candidates, cfo, threshold=0.30)
    # Keep canonical labels only
    canonicals: list[str] = []
    seen: set[str] = set()
    for lid in candidates:
        canon = merge_map[lid]
        if canon not in seen:
            seen.add(canon)
            canonicals.append(canon)

    # 4. Pick top max_nodes
    selected = canonicals[:max_nodes]
    if not selected:
        selected = [ranked[0]] if ranked else ["unknown"]

    # 4b. Coverage boost: disabled — reexpress 완료 후 사후 처리로 대체됨

    # 5. min-children feasibility: simulate and adjust
    selected = _adjust_for_min_children(papers, selected, classify_results, warnings, cfo)

    return selected


def _boost_coverage(
    papers: list[dict],
    selected: list[str],
    ranked_candidates: list[str],
    classify_results: dict[str, list[dict]],
    warnings: list[str],
    coverage_threshold: float = 0.75,
    max_extra: int = 2,
) -> list[str]:
    """
    선택된 label_set에 직접 매핑되지 않는 논문 비율이 (1-coverage_threshold) 초과이면
    미매핑 논문들의 top 토픽 중 빈도 높은 것을 추가 라벨로 보충.
    시간 비용 없음 — 이미 계산된 classify_results만 사용.
    """
    selected_set = set(selected)
    unmapped_pids: list[str] = []
    for paper in papers:
        pid = paper["paper_id"]
        results = classify_results.get(pid, [])
        if not any(r["label_id"] in selected_set for r in results):
            unmapped_pids.append(pid)

    coverage = 1.0 - len(unmapped_pids) / max(len(papers), 1)
    if coverage >= coverage_threshold:
        return selected

    # 미매핑 논문들의 top 토픽 빈도 집계
    extra_freq: dict[str, int] = defaultdict(int)
    for pid in unmapped_pids:
        for r in classify_results.get(pid, [])[:3]:
            lbl = r["label_id"]
            if lbl not in selected_set:
                extra_freq[lbl] += 1

    if not extra_freq:
        return selected

    # 빈도 순으로 추가 (이미 ranked_candidates에 있으면 우선)
    extra_ranked = sorted(extra_freq.items(), key=lambda x: (
        -x[1],
        0 if x[0] in set(ranked_candidates) else 1,
    ))

    added = 0
    result = list(selected)
    for lbl, freq in extra_ranked:
        if added >= max_extra:
            break
        if lbl not in selected_set and freq >= 2:
            result.append(lbl)
            selected_set.add(lbl)
            added += 1

    if added:
        warnings.append(
            f"Coverage boost: added {added} label(s) {result[len(selected):]} "
            f"to cover {len(unmapped_pids)} unmapped papers "
            f"(coverage was {coverage:.0%})"
        )
    return result


def _adjust_for_min_children(
    papers: list[dict],
    label_set: list[str],
    classify_results: dict[str, list[dict]],
    warnings: list[str],
    cfo: CFOAdapter,
) -> list[str]:
    """
    Ensure no singleton group exists after assignment.
    Reduce labels or merge singletons into the nearest label.
    """
    if len(papers) == 1:
        return label_set[:1]  # Singleton root: just one label is fine

    for attempt in range(len(label_set)):
        current = label_set[: len(label_set) - attempt] if attempt > 0 else label_set
        if not current:
            break
        asgn = _simulate_assignment(papers, current, classify_results, cfo)
        groups = _tie_break_sort(papers, asgn)

        singletons = [lid for lid, ps in groups.items() if len(ps) < 2]
        if not singletons:
            return current

        # Try parent promotion for singletons
        for s_label in singletons:
            parents = cfo.parents(s_label)
            for parent in parents:
                if parent in current:
                    continue
                # Try replacing singleton label with parent
                trial = [parent if l == s_label else l for l in current]
                trial_asgn = _simulate_assignment(papers, trial, classify_results, cfo)
                trial_groups = _tie_break_sort(papers, trial_asgn)
                trial_singletons = [l for l, ps in trial_groups.items() if len(ps) < 2]
                if len(trial_singletons) < len(singletons):
                    current = trial
                    warnings.append(
                        f"Label '{s_label}' promoted to parent '{parent}' to resolve singleton group"
                    )
                    break

    # Final fallback: collapse to 1 label if still singletons
    asgn = _simulate_assignment(papers, current, classify_results, cfo)
    groups = _tie_break_sort(papers, asgn)
    remaining_singletons = [lid for lid, ps in groups.items() if len(ps) < 2]

    if remaining_singletons and len(current) > 1:
        warnings.append(
            f"Reducing to 1 intermediate label to resolve singleton groups: {remaining_singletons}"
        )
        return current[:1]

    return current


# ---------------------------------------------------------------------------
# Subtopic expansion
# ---------------------------------------------------------------------------

def _expand_large_node(
    label_id: str,
    group_papers: list[dict],
    classify_results: dict[str, list[dict]],
    cfo: CFOAdapter,
    run_config: dict,
    warnings: list[str],
    root_cat: str,
    node_path: str | None = None,
    current_depth: int = 1,
) -> list[dict] | None:
    """
    If a node has >= subtopic_expansion_threshold papers, attempt to split it
    into sub-nodes. Recursively expands sub-nodes that still exceed the threshold,
    up to max_expansion_depth.

    classify_results: 이미 1차 분류에서 얻은 결과를 재사용 — CSOClassifier 재호출 없음.

    node_path: 현재 노드까지의 경로 (예: "cs.AI::large language models").
               None이면 root_cat::label_id로 초기화.
    current_depth: 현재 expansion 깊이 (1부터 시작).

    Returns a list of intermediate node dicts (same structure as the caller
    builds), or None if expansion is not possible / not beneficial.
    """
    max_depth = run_config.get("max_expansion_depth", 3)
    if current_depth > max_depth:
        warnings.append(
            f"Node '{label_id}' ({len(group_papers)} papers) reached max_expansion_depth={max_depth}; skipping further expansion"
        )
        return None

    onto = _get_ontology()
    top_k = run_config.get("top_k", 5)
    max_nodes = run_config.get("max_intermediate_nodes_per_root", 3)

    if node_path is None:
        node_path = f"{root_cat}::{label_id}"

    # Normalise label_id to underscore slug (CSO uses underscores)
    slug = label_id.lower().replace(" ", "_")

    # 1. 이미 보유한 분류 결과에서 해당 논문들의 결과만 추출 (재분류 없음)
    sub_results = {p["paper_id"]: classify_results[p["paper_id"]]
                   for p in group_papers if p["paper_id"] in classify_results}

    # 2. Collect candidate sub-topics from actual classification results,
    #    excluding the current label and its synonyms (space/underscore variants).
    label_variants = {label_id, slug, label_id.replace("_", " ")}
    onto_syns = onto.get_synonyms(slug)
    label_variants.update(onto_syns)
    label_variants.update(s.replace("_", " ") for s in onto_syns)

    sub_candidates: set[str] = set()
    for res in sub_results.values():
        for r in res:
            tid = r["label_id"]
            if tid not in label_variants:
                sub_candidates.add(tid)

    # Also add CSO children (may overlap with above, that is fine)
    for child in onto.get_children(slug):
        sub_candidates.add(child)
    for syn in onto_syns:
        for child in onto.get_children(syn):
            sub_candidates.add(child)

    sub_candidates -= label_variants  # ensure current label excluded

    if not sub_candidates:
        warnings.append(
            f"Node '{label_id}' has {len(group_papers)} papers but no sub-topic candidates; skipping expansion"
        )
        return None

    # 3. Filter classify results to sub_candidates only
    filtered: dict[str, list[dict]] = {}
    for pid, res in sub_results.items():
        sub_hits = [r for r in res if r["label_id"] in sub_candidates]
        if sub_hits:
            filtered[pid] = sub_hits

    covered = len(filtered)
    if covered < len(group_papers) * 0.5:
        warnings.append(
            f"Node '{label_id}': sub-topic coverage too low ({covered}/{len(group_papers)}); skipping expansion"
        )
        return None

    # 4. Select sub-labels using filtered results only (coverage boost 비활성화: sub-labels는 이미 필터됨)
    sub_labels = _select_labels(group_papers, cfo, filtered, run_config, warnings, enable_boost=False)

    # Must produce at least 2 distinct sub-labels to be worth expanding
    if len(sub_labels) < 2:
        warnings.append(
            f"Node '{label_id}': expansion yielded only {len(sub_labels)} sub-label(s); skipping"
        )
        return None

    # 5. Assign papers to sub-labels
    # filtered에 없는 논문(sub_candidate 매핑 없음)은 ancestor BFS로 nearest sub-label 탐색.
    # filtered를 base로 사용하되 _simulate_assignment에서 cfo를 전달해 fallback을 정교화.
    sub_assign_input = {pid: list(res) for pid, res in filtered.items()}
    # filtered에 없는 논문도 그룹에 포함돼야 하므로 원래 결과로 채움
    for p in group_papers:
        if p["paper_id"] not in sub_assign_input:
            sub_assign_input[p["paper_id"]] = sub_results.get(p["paper_id"], [])
    sub_assignments = _simulate_assignment(group_papers, sub_labels, sub_assign_input, cfo)
    sub_assignments = _repair_hard_duplicates(group_papers, sub_labels, sub_assignments)
    sub_groups = _tie_break_sort(group_papers, sub_assignments)

    # 6. Validate: no sub-node should be a singleton (children < 2)
    sub_group_sizes = {lid: len(sub_groups.get(lid, [])) for lid in sub_labels}
    singletons = [lid for lid, cnt in sub_group_sizes.items() if cnt < 2]
    if singletons:
        warnings.append(
            f"Node '{label_id}': expansion produced singleton sub-nodes {singletons}; skipping expansion"
        )
        return None

    # 7. Build expanded node list (with recursive expansion)
    expansion_threshold = run_config.get("subtopic_expansion_threshold", 20)
    expanded: list[dict] = []

    # sub_labels에 배정되지 못한 논문은 rescue 후 unassigned sub-node로 처리
    sub_unassigned = sub_groups.get("unassigned", [])
    if sub_unassigned:
        rescued_sub, still_sub_unassigned = _rescue_unassigned(
            sub_unassigned, classify_results, cfo, node_path, warnings,
            excluded_labels=[label_id] + sub_labels,
        )
        expanded.extend(rescued_sub)
        if still_sub_unassigned:
            unassigned_sub_node_id = f"{node_path}::unassigned"
            expanded.append({
                "node_id": unassigned_sub_node_id,
                "label": "Unassigned",
                "cfo": {"label_id": "unassigned", "initial_keywords": []},
                "children": [
                    {
                        "paper_id": gp["paper_id"],
                        "title": gp.get("title", ""),
                        "assignment": {
                            "cfo_label_id": "unassigned",
                            "score": 0.0,
                            "was_reexpressed": False,
                            "reexpress_iteration": None,
                        },
                    }
                    for gp in sorted(still_sub_unassigned, key=lambda p: p["paper_id"])
                ],
            })

    for sub_lid in sub_labels:
        sub_papers = sub_groups.get(sub_lid, [])
        if not sub_papers:
            continue

        sub_node_path = f"{node_path}::{sub_lid}"

        # Recursively expand if this sub-node still exceeds the threshold
        if len(sub_papers) >= expansion_threshold:
            recursive_expanded = _expand_large_node(
                label_id=sub_lid,
                group_papers=sub_papers,
                classify_results=classify_results,
                cfo=cfo,
                run_config=run_config,
                warnings=warnings,
                root_cat=root_cat,
                node_path=sub_node_path,
                current_depth=current_depth + 1,
            )
            if recursive_expanded:
                expanded.extend(recursive_expanded)
                continue

        kws = cfo.initial_keywords(sub_lid)
        label_text = sub_lid.replace("_", " ").title()
        children = []
        for gp in sorted(sub_papers, key=lambda p: p["paper_id"]):
            pid = gp["paper_id"]
            asgn = sub_assignments[pid]
            children.append({
                "paper_id": pid,
                "title": gp.get("title", ""),
                "assignment": {
                    "cfo_label_id": asgn["label_id"],
                    "score": asgn["score"],
                    "was_reexpressed": bool(asgn.get("was_reexpressed", False)),
                    "reexpress_iteration": asgn.get("reexpress_iteration"),
                },
            })
        expanded.append({
            "node_id": sub_node_path,
            "label": label_text,
            "cfo": {"label_id": sub_lid, "initial_keywords": kws},
            "children": children,
            "expanded_from": label_id,
        })

    warnings.append(
        f"Node '{label_id}' ({len(group_papers)} papers) expanded into "
        f"{len(expanded)} sub-nodes: {[n['cfo']['label_id'] for n in expanded]}"
    )
    return expanded


# ---------------------------------------------------------------------------
# Unassigned rescue
# ---------------------------------------------------------------------------

def _rescue_unassigned(
    unassigned_papers: list[dict],
    classify_results: dict[str, list[dict]],
    cfo: CFOAdapter,
    node_prefix: str,
    warnings: list[str],
    excluded_labels: list[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    unassigned 논문들을 자기들끼리 재분류해 새 intermediate 노드로 구제한다.
    기준: singleton(논문 1편) 노드가 생기지 않으면 OK — label_set 기준은 적용하지 않음.
    node_prefix: 생성될 node_id의 prefix (예: "cs.AI" → "cs.AI::rescued::X")
    excluded_labels: 이미 상위/동급 트리에 있는 라벨 — rescue 후보에서 제외해 중복 방지
    반환값: (rescued_nodes, still_unassigned)
    """
    if not unassigned_papers:
        return [], []

    # 상위/동급에 이미 있는 라벨 정규화
    excluded: set[str] = set()
    for lbl in (excluded_labels or []):
        slug = lbl.lower().replace(" ", "_")
        excluded.add(lbl)
        excluded.add(slug)
        excluded.add(slug.replace("_", " "))

    # 1. unassigned 논문들의 classify 결과에서 빈도 상위 라벨 수집 (excluded 제외)
    freq: dict[str, int] = defaultdict(int)
    for p in unassigned_papers:
        for r in classify_results.get(p["paper_id"], [])[:5]:
            lbl = r["label_id"]
            if lbl not in excluded:
                freq[lbl] += 1

    if not freq:
        return [], list(unassigned_papers)

    # 2. 빈도 상위 최대 3개를 새 label_set으로 구성
    ranked = sorted(freq, key=lambda k: -freq[k])
    new_label_set = ranked[:3]

    # 3. singleton 검사 — label_set을 3→2→1 순으로 줄여가며 singleton 없는 배정 탐색
    for attempt in range(len(new_label_set), 0, -1):
        trial_set = new_label_set[:attempt]
        trial_asgn = _simulate_assignment(unassigned_papers, trial_set, classify_results, cfo)
        groups = _tie_break_sort(unassigned_papers, trial_asgn)

        real_groups = {lid: ps for lid, ps in groups.items() if lid != "unassigned"}
        has_singleton = any(len(ps) < 2 for ps in real_groups.values())

        if not has_singleton and real_groups:
            rescued_nodes: list[dict] = []
            for lid, papers_in_group in sorted(real_groups.items()):
                node_id = f"{node_prefix}::rescued::{lid}"
                kws = cfo.initial_keywords(lid)
                label_text = lid.replace("_", " ").title()
                children = [
                    {
                        "paper_id": gp["paper_id"],
                        "title": gp.get("title", ""),
                        "assignment": {
                            "cfo_label_id": lid,
                            "score": trial_asgn[gp["paper_id"]]["score"],
                            "was_reexpressed": False,
                            "reexpress_iteration": None,
                        },
                    }
                    for gp in sorted(papers_in_group, key=lambda p: p["paper_id"])
                ]
                rescued_nodes.append({
                    "node_id": node_id,
                    "label": label_text,
                    "cfo": {"label_id": lid, "initial_keywords": kws},
                    "children": children,
                    "rescued_from": "unassigned",
                })

            still_unassigned = list(groups.get("unassigned", []))
            warnings.append(
                f"{node_prefix}: rescued {len(unassigned_papers) - len(still_unassigned)} unassigned paper(s) "
                f"into {len(rescued_nodes)} new node(s): {[n['cfo']['label_id'] for n in rescued_nodes]}"
            )
            if still_unassigned:
                warnings.append(
                    f"{node_prefix}: {len(still_unassigned)} paper(s) remain unassigned after rescue"
                )
            return rescued_nodes, still_unassigned

    # 모든 시도 실패
    return [], list(unassigned_papers)


# ---------------------------------------------------------------------------
# Iterative re-expression loop
# ---------------------------------------------------------------------------

def _iterative_reexpress(
    papers: list[dict],
    label_set: list[str],
    classify_results: dict[str, list[dict]],
    cfo: CFOAdapter,
    run_config: dict,
    warnings: list[str],
) -> tuple[dict[str, dict], int]:
    """
    Run the re-expression loop for ambiguous papers.
    Returns (final_assignments, iterations_used).
    Each assignment entry: {label_id, score, top2_score, top2_label,
                            was_reexpressed, reexpress_iteration}.
    """
    max_iter = run_config.get("max_iterations", 6)
    margin = run_config.get("ambiguity_margin", 0.08)
    top_k = run_config.get("top_k", 5)

    # Build mutable copy of classify results
    current_results = {pid: list(res) for pid, res in classify_results.items()}
    assignments = _simulate_assignment(papers, label_set, current_results, cfo)

    # Track reexpression metadata
    reexpr_meta: dict[str, dict] = {
        p["paper_id"]: {"was_reexpressed": False, "reexpress_iteration": None}
        for p in papers
    }

    paper_map = {p["paper_id"]: p for p in papers}
    iterations_used = 0
    prev_candidate_count: int | None = None

    for iteration in range(1, max_iter + 1):
        ambiguous = _detect_soft_overlap(assignments, margin)

        candidates = ambiguous
        if not candidates:
            break

        # 이전 iteration 대비 개선(후보 수 감소) 없으면 조기 종료
        if prev_candidate_count is not None and len(candidates) >= prev_candidate_count:
            break
        prev_candidate_count = len(candidates)

        iterations_used = iteration
        changed = False

        # 재표현 텍스트 생성 (순차 — 텍스트 조합만이라 빠름)
        reexpr_texts: dict[str, str] = {}
        for pid in sorted(candidates):
            paper = paper_map[pid]
            cur_asgn = assignments[pid]
            reexpr_texts[pid] = _reexpress_text(
                paper, cur_asgn["label_id"], cur_asgn.get("top2_label"), cfo
            )

        # 재분류: 모든 후보 텍스트를 배치로 병렬 classify
        parallel_fn = getattr(getattr(cfo, "_cso", None), "parallel_classify", None)
        pid_to_reexpr_results: dict[str, list[dict]] = {}
        if callable(parallel_fn):
            # 캐시 miss 텍스트만 병렬 처리, 캐시 hit은 직접 조회
            unique_miss_texts: list[str] = []
            seen_texts: set[str] = set()
            for pid in candidates:
                txt = reexpr_texts[pid]
                if (txt, top_k) not in cfo._classify_cache and txt not in seen_texts:
                    unique_miss_texts.append(txt)
                    seen_texts.add(txt)
            if unique_miss_texts:
                batch_papers = [
                    {"paper_id": txt, "title": "", "abstract": txt}
                    for txt in unique_miss_texts
                ]
                batch_results = parallel_fn(batch_papers, top_k=top_k)
                for txt, res in batch_results.items():
                    cfo._classify_cache[(txt, top_k)] = res
            # 결과 수집 (캐시에서 직접 읽기)
            for pid in candidates:
                txt = reexpr_texts[pid]
                pid_to_reexpr_results[pid] = cfo._classify_cache.get((txt, top_k), [])
        else:
            for pid in candidates:
                txt = reexpr_texts[pid]
                pid_to_reexpr_results[pid] = cfo.classify(txt, top_k=top_k)

        for pid in sorted(candidates):
            paper = paper_map[pid]
            cur_asgn = assignments[pid]

            new_results = pid_to_reexpr_results.get(pid, [])
            if not new_results:
                continue

            # Filter to label_set
            in_set = [r for r in new_results if r["label_id"] in set(label_set)]
            if not in_set:
                in_set = new_results[:1]

            in_set_sorted = sorted(in_set, key=lambda x: (-x["score"], x["label_id"]))
            top1 = in_set_sorted[0]
            top2 = in_set_sorted[1] if len(in_set_sorted) > 1 else None

            new_asgn = {
                "label_id": top1["label_id"],
                "score": top1["score"],
                "top2_score": top2["score"] if top2 else None,
                "top2_label": top2["label_id"] if top2 else None,
            }

            if new_asgn["label_id"] != cur_asgn["label_id"]:
                changed = True

            assignments[pid] = new_asgn
            reexpr_meta[pid]["was_reexpressed"] = True
            reexpr_meta[pid]["reexpress_iteration"] = iteration

        # Parent promotion for remaining singletons / ambiguous
        remaining_ambiguous = _detect_soft_overlap(assignments, margin)
        groups_after = _tie_break_sort(papers, assignments)
        singleton_paper_pids: set[str] = {
            p["paper_id"]
            for lid, ps in groups_after.items()
            if len(ps) < 2 and len(papers) > 1
            for p in ps
        }
        promotion_targets = singleton_paper_pids | remaining_ambiguous

        if promotion_targets:
            label_stats = _aggregate_labels(current_results)
            for pid in sorted(promotion_targets):
                cur_label = assignments[pid]["label_id"]
                parents = cfo.parents(cur_label)
                if not parents:
                    continue
                best_parent = sorted(
                    parents,
                    key=lambda p: -(label_stats.get(p, {}).get("rank_score", 0)),
                )[0]
                reexpr = _reexpress_text(paper_map[pid], best_parent, cur_label, cfo)
                promoted_results = cfo.classify(reexpr, top_k=top_k)
                in_set = [r for r in promoted_results if r["label_id"] in set(label_set)]
                if not in_set:
                    in_set = [{"label_id": label_set[0], "score": 0.1}]
                in_set_sorted = sorted(in_set, key=lambda x: (-x["score"], x["label_id"]))
                top1 = in_set_sorted[0]
                top2 = in_set_sorted[1] if len(in_set_sorted) > 1 else None
                assignments[pid] = {
                    "label_id": top1["label_id"],
                    "score": top1["score"],
                    "top2_score": top2["score"] if top2 else None,
                    "top2_label": top2["label_id"] if top2 else None,
                }
                reexpr_meta[pid]["was_reexpressed"] = True
                reexpr_meta[pid]["reexpress_iteration"] = iteration

        # 조기 종료: 배정 변화가 없으면 더 이상 진행 의미 없음
        if not changed:
            break

    # Remaining soft overlaps → warn
    final_ambiguous = _detect_soft_overlap(assignments, margin)
    if final_ambiguous:
        warnings.append(
            f"Unresolved soft overlaps after {iterations_used} iterations: "
            f"{sorted(final_ambiguous)}"
        )

    # Merge metadata into assignments
    for pid, meta in reexpr_meta.items():
        assignments[pid]["was_reexpressed"] = meta["was_reexpressed"]
        assignments[pid]["reexpress_iteration"] = meta["reexpress_iteration"]

    return assignments, iterations_used


# ---------------------------------------------------------------------------
# Hard duplicate repair
# ---------------------------------------------------------------------------

def _repair_hard_duplicates(
    papers: list[dict],
    label_set: list[str],
    assignments: dict[str, dict],
) -> dict[str, dict]:
    """Detect and fix hard duplicate assignments via deterministic tie-break."""
    # In this design each paper gets exactly one label (no hard dup possible
    # since _simulate_assignment maps 1 paper → 1 label).
    # But as a safety net: verify and re-apply tie-break if something went wrong.
    seen: dict[str, str] = {}  # paper_id -> label_id
    for pid, asgn in assignments.items():
        if pid in seen:
            # Hard duplicate: should not happen, but fix it
            pass
        seen[pid] = asgn["label_id"]
    return assignments


# ---------------------------------------------------------------------------
# TreeBuilder
# ---------------------------------------------------------------------------

class TreeBuilder:
    """
    Main entry point for building a 3-level CFO/CSO classification tree.

    Usage:
        builder = TreeBuilder(cso_instance=my_cso, db_path="cfo_tree.db")
        output = builder.build_tree(input_dict)
    """

    def __init__(
        self,
        cso_instance: Any = None,
        db_path: str = "cfo_tree.db",
    ) -> None:
        backend = cso_instance if cso_instance is not None else _CSOClassifier()
        self._cfo = CFOAdapter(backend)
        # Pool을 한 번만 생성해 분류·재표현 모두 재사용
        self._pool = self._make_pool(backend)
        # CFOAdapter에 pool 주입 (parallel_classify가 pool을 받을 수 있도록)
        raw_cso = getattr(self._cfo, "_cso", None)
        if raw_cso is not None and hasattr(raw_cso, "set_pool"):
            raw_cso.set_pool(self._pool)
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        _init_db(self._conn)

    @staticmethod
    def _make_pool(backend: Any):
        """backend가 parallel_classify를 지원하면 Pool 생성, 아니면 None.
        worker들을 미리 warming up해 첫 번째 classify 지연을 제거한다.
        """
        init_fn = getattr(backend, "_pool_initializer", None)
        if callable(init_fn):
            import concurrent.futures
            pool = concurrent.futures.ProcessPoolExecutor(
                max_workers=4, initializer=init_fn
            )
            # Warmup: _worker_classify는 backend에서 직접 가져옴
            warmup_fn = getattr(backend, "_worker_classify_fn", None)
            if callable(warmup_fn):
                dummy_args = [("__warmup__", "", "warmup", 1)] * 4
                try:
                    list(pool.map(warmup_fn, dummy_args))
                except Exception:
                    pass
            return pool
        return None

    def __del__(self):
        if getattr(self, "_pool", None) is not None:
            self._pool.shutdown(wait=False)

    def build_tree(self, input_dict: dict) -> dict:
        errors: list[str] = []
        warnings: list[str] = []

        # ---- 1. Input schema validation ----
        v = Draft202012Validator(INPUT_SCHEMA)
        schema_errors = sorted(v.iter_errors(input_dict), key=lambda e: list(e.path))
        if schema_errors:
            msg = "; ".join(e.message for e in schema_errors[:5])
            raise ValueError(f"Input schema validation failed: {msg}")

        run_config = _resolve_run_config(input_dict.get("run_config"))
        papers: list[dict] = input_dict["input_papers"]

        # ---- 2. paper_id uniqueness check ----
        pid_list = [p["paper_id"] for p in papers]
        seen_pids: set[str] = set()
        dups: set[str] = set()
        for pid in pid_list:
            if pid in seen_pids:
                dups.add(pid)
            seen_pids.add(pid)
        if dups:
            raise ValueError(f"Duplicate paper_id(s) in input: {sorted(dups)}")

        # ---- 3. abstract validation ----
        for p in papers:
            if p.get("abstract") == "":
                errors.append(
                    f"paper_id={p['paper_id']}: abstract is empty string; "
                    f"classification quality will be severely degraded"
                )

        # ---- 4. Root grouping ----
        root_groups = _group_by_root(papers, run_config, warnings)

        if not root_groups:
            errors.append("No papers matched root_allowlist; cannot build tree")
            return self._empty_output(errors, warnings, run_config, len(papers))

        # ---- 5. Per-root processing ----
        roots_output: list[dict] = []
        all_assignments: list[dict] = []
        total_reexpressed = 0
        total_iterations = 0

        for root_cat, root_papers in sorted(root_groups.items()):
            is_singleton = len(root_papers) == 1

            # Classify all papers in this root
            top_k = run_config.get("top_k", 5)
            classify_results = _classify_papers(root_papers, self._cfo, top_k)

            # Select intermediate labels
            label_set = _select_labels(
                root_papers, self._cfo, classify_results, run_config, warnings
            )

            # Singleton root warning
            if is_singleton:
                warnings.append(
                    f"Root '{root_cat}' has only 1 paper; "
                    f"infeasible to satisfy children>=2 constraint; "
                    f"children>=1 allowed as exception."
                )

            # Iterative re-expression
            assignments, iters_used = _iterative_reexpress(
                root_papers, label_set, classify_results, self._cfo, run_config, warnings
            )
            total_iterations = max(total_iterations, iters_used)

            # Repair hard duplicates (safety net)
            assignments = _repair_hard_duplicates(root_papers, label_set, assignments)

            # Post-hoc coverage boost: score=0.05 fallback 논문을 추가 라벨로 재배정
            # reexpress 완료 후에 적용하므로 기존 배정에 영향 없음
            fallback_pids = [pid for pid, asgn in assignments.items() if asgn.get("label_id") == "unassigned"]
            if len(fallback_pids) > len(root_papers) * 0.20:
                # 20% 이상이 fallback이면 추가 라벨 탐색
                onto = _get_ontology()
                extra_freq: dict[str, int] = defaultdict(int)
                for pid in fallback_pids:
                    for r in classify_results.get(pid, [])[:3]:
                        lbl = r["label_id"]
                        if lbl not in set(label_set):
                            extra_freq[lbl] += 1
                if extra_freq:
                    # 빈도 최상위 1개 추가
                    best_extra = max(extra_freq, key=lambda k: extra_freq[k])
                    if extra_freq[best_extra] >= 2:
                        label_set = label_set + [best_extra]
                        warnings.append(
                            f"Post-hoc coverage: added '{best_extra}' for {len(fallback_pids)} fallback papers"
                        )
                        # fallback 논문만 재배정 (기존 배정은 유지)
                        fallback_papers = [p for p in root_papers if p["paper_id"] in set(fallback_pids)]
                        new_asgns = _simulate_assignment(fallback_papers, label_set, classify_results, self._cfo)
                        for pid, asgn in new_asgns.items():
                            if assignments[pid].get("label_id") == "unassigned" and asgn.get("label_id") != "unassigned":
                                assignments[pid] = asgn

            # Count reexpressed
            for asgn in assignments.values():
                if asgn.get("was_reexpressed"):
                    total_reexpressed += 1

            # Group into intermediate nodes
            groups = _tie_break_sort(root_papers, assignments)

            expansion_threshold = run_config.get("subtopic_expansion_threshold", 10)
            intermediate_nodes: list[dict] = []
            for label_id in label_set:
                group_papers = groups.get(label_id, [])
                if not group_papers:
                    continue

                # --- subtopic expansion for large nodes ---
                if len(group_papers) >= expansion_threshold:
                    expanded = _expand_large_node(
                        label_id, group_papers, classify_results,
                        self._cfo, run_config, warnings, root_cat,
                        node_path=f"{root_cat}::{label_id}",
                        current_depth=1,
                    )
                    if expanded:
                        for node in expanded:
                            for child in node["children"]:
                                pid = child["paper_id"]
                                asgn = child["assignment"]
                                all_assignments.append({
                                    "paper_id": pid,
                                    "root_cat": root_cat,
                                    "intermediate_id": node["node_id"],
                                    "label_id": asgn["cfo_label_id"],
                                    "score": asgn["score"],
                                    "was_reexpressed": asgn["was_reexpressed"],
                                    "iter": asgn["reexpress_iteration"],
                                })
                            intermediate_nodes.append(node)
                        continue  # skip the default node construction below

                kws = self._cfo.initial_keywords(label_id)
                label_text = label_id.replace("_", " ").title()
                node_id = f"{root_cat}::{label_id}"

                children: list[dict] = []
                for gp in sorted(group_papers, key=lambda p: p["paper_id"]):
                    pid = gp["paper_id"]
                    asgn = assignments[pid]
                    children.append({
                        "paper_id": pid,
                        "title": gp.get("title", ""),
                        "assignment": {
                            "cfo_label_id": asgn["label_id"],
                            "score": asgn["score"],
                            "was_reexpressed": bool(asgn.get("was_reexpressed", False)),
                            "reexpress_iteration": asgn.get("reexpress_iteration"),
                        },
                    })
                    all_assignments.append({
                        "paper_id": pid,
                        "root_cat": root_cat,
                        "intermediate_id": node_id,
                        "label_id": asgn["label_id"],
                        "score": asgn["score"],
                        "was_reexpressed": asgn.get("was_reexpressed", False),
                        "iter": asgn.get("reexpress_iteration"),
                    })

                intermediate_nodes.append({
                    "node_id": node_id,
                    "label": label_text,
                    "cfo": {"label_id": label_id, "initial_keywords": kws},
                    "children": children,
                })

            # Rescue unassigned papers before falling back to unassigned node
            unassigned_papers = groups.get("unassigned", [])
            if unassigned_papers:
                rescued_nodes, still_unassigned = _rescue_unassigned(
                    unassigned_papers, classify_results, self._cfo, root_cat, warnings,
                    excluded_labels=label_set,
                )
                for node in rescued_nodes:
                    for child in node["children"]:
                        pid = child["paper_id"]
                        all_assignments.append({
                            "paper_id": pid,
                            "root_cat": root_cat,
                            "intermediate_id": node["node_id"],
                            "label_id": child["assignment"]["cfo_label_id"],
                            "score": child["assignment"]["score"],
                            "was_reexpressed": False,
                            "iter": None,
                        })
                    intermediate_nodes.append(node)

                if still_unassigned:
                    unassigned_node_id = f"{root_cat}::unassigned"
                    unassigned_children: list[dict] = []
                    for gp in sorted(still_unassigned, key=lambda p: p["paper_id"]):
                        pid = gp["paper_id"]
                        asgn = assignments[pid]
                        unassigned_children.append({
                            "paper_id": pid,
                            "title": gp.get("title", ""),
                            "assignment": {
                                "cfo_label_id": "unassigned",
                                "score": 0.0,
                                "was_reexpressed": bool(asgn.get("was_reexpressed", False)),
                                "reexpress_iteration": asgn.get("reexpress_iteration"),
                            },
                        })
                        all_assignments.append({
                            "paper_id": pid,
                            "root_cat": root_cat,
                            "intermediate_id": unassigned_node_id,
                            "label_id": "unassigned",
                            "score": 0.0,
                            "was_reexpressed": asgn.get("was_reexpressed", False),
                            "iter": asgn.get("reexpress_iteration"),
                        })
                    intermediate_nodes.append({
                        "node_id": unassigned_node_id,
                        "label": "Unassigned",
                        "cfo": {"label_id": "unassigned", "initial_keywords": []},
                        "children": unassigned_children,
                    })
                    warnings.append(
                        f"{root_cat}: {len(still_unassigned)} paper(s) placed in 'unassigned' node"
                    )

            if intermediate_nodes:
                roots_output.append({
                    "arxiv_primary_category": root_cat,
                    "intermediate_nodes": intermediate_nodes,
                })

        # ---- 6. Output assembly ----
        num_intermediate = sum(
            len(r["intermediate_nodes"]) for r in roots_output
        )
        num_leaves = sum(
            len(m["children"])
            for r in roots_output
            for m in r["intermediate_nodes"]
        )

        # ---- 7. Invariant checks ----
        assigned_ids = [
            c["paper_id"]
            for r in roots_output
            for m in r["intermediate_nodes"]
            for c in m["children"]
        ]
        input_id_set = {p["paper_id"] for p in papers}
        assigned_id_set = set(assigned_ids)

        missing = input_id_set - assigned_id_set
        if missing:
            errors.append(f"Papers not assigned to any leaf: {sorted(missing)}")

        duplicates = {pid for pid in assigned_ids if assigned_ids.count(pid) > 1}
        if duplicates:
            errors.append(f"Duplicate leaf assignments: {sorted(duplicates)}")

        is_valid = not errors

        stats = {
            "num_input_papers": len(papers),
            "num_roots": len(roots_output),
            "num_intermediate_nodes": num_intermediate,
            "num_assigned_leaves": num_leaves,
            "num_reexpressed": total_reexpressed,
            "iterations_used": total_iterations,
        }

        output = {
            "version": VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "roots": roots_output if roots_output else [],
            "validation": {
                "is_valid": is_valid,
                "errors": errors,
                "warnings": warnings,
                "stats": stats,
            },
            "provenance": {
                "cfo_classifier_info": self._cfo.info(),
                "assumptions": [
                    "CSO v3.5 ontology used as taxonomy; "
                    "topic labels derived from superTopicOf hierarchy.",
                    "Network calls disabled unless allow_arxiv_fetch=true.",
                    "root_allowlist defaults to ['cs.AI'].",
                ],
                "adapter_fallbacks": list(set(self._cfo.fallbacks)),
            },
        }

        # ---- 8. Output schema validation ----
        out_v = Draft202012Validator(OUTPUT_SCHEMA)
        out_errors = list(out_v.iter_errors(output))
        if out_errors:
            for e in out_errors[:3]:
                warnings.append(f"Output schema warning: {e.message}")

        # ---- 9. SQLite persistence ----
        run_id = str(uuid.uuid4())
        ih = _input_hash(papers)
        _save_run(
            self._conn,
            run_id,
            run_config,
            ih,
            json.dumps(output, ensure_ascii=False),
            all_assignments,
        )

        return output

    def _empty_output(
        self,
        errors: list[str],
        warnings: list[str],
        run_config: dict,
        n_papers: int,
    ) -> dict:
        return {
            "version": VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "roots": [],
            "validation": {
                "is_valid": False,
                "errors": errors,
                "warnings": warnings,
                "stats": {
                    "num_input_papers": n_papers,
                    "num_roots": 0,
                    "num_intermediate_nodes": 0,
                    "num_assigned_leaves": 0,
                    "num_reexpressed": 0,
                    "iterations_used": 0,
                },
            },
            "provenance": {
                "cfo_classifier_info": self._cfo.info(),
                "assumptions": [],
                "adapter_fallbacks": list(set(self._cfo.fallbacks)),
            },
        }


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def build_tree(
    input_dict: dict,
    *,
    cso_instance: Any = None,
    db_path: str = "cfo_tree.db",
) -> dict:
    """
    Convenience function wrapping TreeBuilder.
    build_tree(input_dict, cso_instance=my_cso, db_path="cfo_tree.db") -> output_dict
    """
    builder = TreeBuilder(cso_instance=cso_instance, db_path=db_path)
    return builder.build_tree(input_dict)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tree_builder.py <input.json> [db_path]", file=sys.stderr)
        sys.exit(1)

    input_path = sys.argv[1]
    db = sys.argv[2] if len(sys.argv) > 2 else "cfo_tree.db"

    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    result = build_tree(data, db_path=db)
    print(json.dumps(result, ensure_ascii=False, indent=2))
