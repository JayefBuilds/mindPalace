#!/usr/bin/env python3
"""Process queued Mind Palace hook Stop jobs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import mind_palace_hook  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Process queued Mind Palace hook jobs.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum jobs to process.")
    args = parser.parse_args()

    mind_palace_hook.load_dotenv(ROOT / ".env")
    result = mind_palace_hook.process_stop_queue(limit=args.limit)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
