from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .idea import ResearchIdea
from .future_work import ideas_from_future_work, is_future_work_payload
from .pipeline import check_novelty


def main() -> None:
    parser = argparse.ArgumentParser(description="아이디어의 문헌 기반 신규성을 검증합니다.")
    parser.add_argument(
        "idea_json",
        help="README.md 4.1절 아이디어 JSON 또는 Future-Work-Researcher 결과 JSON 경로",
    )
    parser.add_argument("--config", default=None, help="config.yml 경로 (기본: 저장소 루트의 config.yml)")
    args = parser.parse_args()

    with open(args.idea_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    if is_future_work_payload(data):
        ideas = ideas_from_future_work(data)

        async def check_all():
            return [await check_novelty(idea, config_path=args.config) for idea in ideas]

        output = {"results": [result.as_dict() for result in asyncio.run(check_all())]}
    else:
        idea = ResearchIdea.from_dict(data)
        output = asyncio.run(check_novelty(idea, config_path=args.config)).as_dict()

    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
