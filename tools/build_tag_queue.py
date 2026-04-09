#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


MANIFEST_PATH = Path("/home/sarel/facts/data/manifest.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=0, help="How many incomplete months to emit. Default: half of remaining months.")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST_PATH.read_text())
    remaining = sorted(
        (
            value["total_facts"] - value["tagged_facts"],
            value["total_facts"],
            key,
        )
        for key, value in manifest["months"].items()
        if not value.get("tags")
    )

    count = args.count if args.count > 0 else len(remaining) // 2
    for _, _, key in remaining[:count]:
        print(key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
