from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any, Callable, Iterable

class HttpSearchEngineClient:
    """Small HTTP client for SearchEngine /search."""

    def __init__(self, base_url: str = "http://127.0.0.1:8000") -> None:
        self.base_url = base_url.rstrip("/")

    def search(self, *, query: str, size: int = 100) -> list[dict[str, Any]]:
        import requests

        response = requests.get(
            f"{self.base_url}/search",
            params={"query": query, "size": size, "page": 1},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("results", [])


class SearchEngineCSOAdapter:
    def __init__(
        self,
        *,
        db_path: str,
        tree_builder: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        search_client: Any | None = None,
        tree_builder_db_path: str | None = None,
    ) -> None:
        self.db_path = db_path
        self._tree_builder = tree_builder or self._default_tree_builder
        self._search_client = search_client or HttpSearchEngineClient()
        self.tree_builder_db_path = tree_builder_db_path or ":memory:"

    def run(self, *, query: str, size: int = 100, limit: int = 10) -> dict[str, Any]:
        if not query or not query.strip():
            raise ValueError("Search query must be non-empty.")
        raw_results = self._search_client.search(query=query.strip(), size=size)
        return self.build_from_search_results(query=query.strip(), raw_results=raw_results, limit=limit)

    def build_from_search_results(
        self,
        *,
        query: str,
        raw_results: Iterable[dict[str, Any]],
        limit: int = 10,
    ) -> dict[str, Any]:
        cso_input, metadata_map = self.normalize_search_results(raw_results)
        tree_output = self._tree_builder(cso_input)
        selected = self.select_first_leaf_papers(tree_output=tree_output, metadata_map=metadata_map, limit=limit)
        return {
            "query": query,
            "selected_papers": selected,
            "tree_output": tree_output,
            "input_papers": cso_input["input_papers"],
        }

    def normalize_search_results(self, raw_results: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        arxiv_ids: list[str] = []
        for result in raw_results:
            arxiv_id = str(result.get("arxiv_id") or "").strip()
            if not arxiv_id:
                continue
            arxiv_ids.append(arxiv_id)

        db_metadata = self._load_db_metadata(arxiv_ids)
        input_papers: list[dict[str, Any]] = []
        metadata_map: dict[str, dict[str, Any]] = {}
        for arxiv_id in arxiv_ids:
            if arxiv_id not in db_metadata:
                continue
            metadata = db_metadata[arxiv_id]
            input_papers.append(
                {
                    "paper_id": arxiv_id,
                    "title": metadata["title"],
                    "abstract": metadata["abstract"],
                    "arxiv_id": arxiv_id,
                    "arxiv_primary_category": metadata["arxiv_primary_category"],
                    "arxiv_categories": metadata["arxiv_categories"],
                    "authors": metadata["authors"],
                    "year": metadata["year"],
                    "source": "user_search",
                }
            )
            metadata_map[arxiv_id] = {
                "paper_id": arxiv_id,
                "arxiv_id": arxiv_id,
                "title": metadata["title"],
                "abstract": metadata["abstract"],
                "authors": metadata["authors"],
                "arxiv_primary_category": metadata["arxiv_primary_category"],
                "arxiv_categories": metadata["arxiv_categories"],
                "published": metadata["published"],
            }

        if not input_papers:
            raise ValueError("No DB-backed search results could be normalized for CSO input.")

        return {"input_papers": input_papers}, metadata_map

    def select_first_leaf_papers(
        self,
        *,
        tree_output: dict[str, Any],
        metadata_map: dict[str, dict[str, Any]],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        roots = sorted(tree_output.get("roots", []), key=lambda root: root.get("arxiv_primary_category") or "")
        for root in roots:
            for node in root.get("intermediate_nodes", []):
                for child in node.get("children", []):
                    paper_id = child["paper_id"]
                    if paper_id not in metadata_map:
                        continue
                    meta = metadata_map[paper_id]
                    selected.append(
                        {
                            "selection_index": len(selected) + 1,
                            "paper_id": paper_id,
                            "title": meta["title"] or child.get("title", ""),
                            "abstract": meta["abstract"],
                            "authors": meta["authors"],
                            "arxiv_primary_category": meta["arxiv_primary_category"],
                            "arxiv_categories": meta["arxiv_categories"],
                            "published": meta["published"],
                            "node_id": node["node_id"],
                            "cfo_label_id": child.get("assignment", {}).get("cfo_label_id"),
                        }
                    )
                    if len(selected) >= limit:
                        return selected
        return selected

    def _load_db_metadata(self, arxiv_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not arxiv_ids:
            return {}
        placeholders = ",".join("?" for _ in arxiv_ids)
        query = f"""
            SELECT arxiv_id, title, abstract, categories, primary_category, created_date
            FROM papers
            WHERE arxiv_id IN ({placeholders}) AND COALESCE(is_deleted, 0) = 0
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            paper_rows = conn.execute(query, arxiv_ids).fetchall()
            author_rows = conn.execute(
                f"""
                SELECT arxiv_id, position, keyname, forenames
                FROM authors
                WHERE arxiv_id IN ({placeholders})
                ORDER BY arxiv_id, position
                """,
                arxiv_ids,
            ).fetchall()

        authors_by_id: dict[str, list[str]] = {}
        for row in author_rows:
            full_name = " ".join(part for part in [row["forenames"], row["keyname"]] if part).strip()
            authors_by_id.setdefault(row["arxiv_id"], [])
            if full_name:
                authors_by_id[row["arxiv_id"]].append(full_name)

        metadata: dict[str, dict[str, Any]] = {}
        for row in paper_rows:
            created_date = row["created_date"]
            year = int(created_date[:4]) if created_date and len(created_date) >= 4 else None
            categories = [part for part in str(row["categories"] or "").split() if part]
            metadata[row["arxiv_id"]] = {
                "title": row["title"] or "",
                "abstract": row["abstract"] or "",
                "arxiv_primary_category": row["primary_category"],
                "arxiv_categories": categories,
                "authors": authors_by_id.get(row["arxiv_id"], []),
                "year": year,
                "published": created_date,
            }
        return metadata

    def _default_tree_builder(self, input_dict: dict[str, Any]) -> dict[str, Any]:
        repo_root = Path(__file__).resolve().parents[2]
        import sys

        cso_dir = repo_root / "CSO_CATEGORY"
        if str(cso_dir) not in sys.path:
            sys.path.insert(0, str(cso_dir))
        from tree_builder import build_tree  # type: ignore

        return build_tree(input_dict, db_path=self.tree_builder_db_path)
