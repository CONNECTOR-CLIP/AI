"""Build or inspect the optional local arXiv FTS sidecar."""

from __future__ import annotations

import argparse
import json

from .lexical_index import build_index, index_status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "status"))
    parser.add_argument("--source", help="arXiv SQLite DB; defaults to ARXIV_DB_PATH")
    parser.add_argument("--index", help="FTS sidecar; defaults to ARXIV_FTS_PATH or <source>.fts.sqlite3")
    parser.add_argument("--batch-size", type=int, default=1000)
    args = parser.parse_args()
    result = (build_index(args.source, args.index, batch_size=args.batch_size)
              if args.command == "build" else index_status(args.source, args.index))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
