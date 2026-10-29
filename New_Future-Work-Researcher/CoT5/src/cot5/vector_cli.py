"""Build and inspect the optional full-corpus SPECTER2 index."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .vector_index import IndexUnavailable, build_index, index_status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "status"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--db", required=True, help="Path to local arXiv SQLite database")
        sub.add_argument("--index", help="Directory for the vector index (default: <db>.specter2)")
        if name == "build":
            sub.add_argument("--chunk-size", type=int, default=512)
    args = parser.parse_args()
    index = args.index or os.getenv("COT5_VECTOR_INDEX_DIR") or str(Path(args.db).expanduser()) + ".specter2"
    try:
        result = (
            build_index(args.db, index, chunk_size=args.chunk_size)
            if args.command == "build" else index_status(index, args.db)
        )
    except (IndexUnavailable, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
