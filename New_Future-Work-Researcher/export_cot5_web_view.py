"""Export a successful-web-results-only presentation view; preserve raw logs."""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
from pathlib import Path


def build_web_view(payload: dict) -> dict:
    rows = []
    for index, result in enumerate(payload.get("results", []), 1):
        web = result.get("overlaps", {}).get("web", {})
        if web.get("status") not in ("\uacb9\uce68", "\uc5c6\uc74c") or web.get("error"):
            continue
        rows.append({"candidate_index": index, "idea_title": result.get("idea_title", ""),
                     "web": deepcopy(web)})
    return {"view_scope": "successful_web_results_only", "displayed_count": len(rows),
            "results": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("Presentation output must not overwrite raw results")
    data = json.loads(args.input.read_text(encoding="utf-8"))
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(build_web_view(data), stream, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
