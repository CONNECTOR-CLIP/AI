from __future__ import annotations

import argparse
import json
import sys

from .idea import ResearchIdea
from .future_work import ideas_from_future_work, is_future_work_payload
from .pipeline import CoT4Pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="아이디어의 기술적 실현가능성을 검증합니다.")
    parser.add_argument(
        "idea_json",
        help="README.md 5.1절 아이디어 JSON 또는 Future-Work-Researcher 결과 JSON 경로",
    )
    args = parser.parse_args()

    with open(args.idea_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    pipeline = CoT4Pipeline()
    if is_future_work_payload(data):
        output = {"results": [pipeline.check(idea).as_dict() for idea in ideas_from_future_work(data)]}
    else:
        output = pipeline.check(ResearchIdea.from_dict(data)).as_dict()

    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
