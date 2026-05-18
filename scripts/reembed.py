#!/usr/bin/env python3
"""Recompute Qdrant vectors for active memories."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main():
    parser = argparse.ArgumentParser(description="Re-embed active Mind Palace memories")
    parser.add_argument("--agent", help="Optional agent ID filter")
    parser.add_argument("--limit", type=int, help="Max active memories to process")
    parser.add_argument("--execute", action="store_true", help="Actually update vectors; default is dry run")
    parser.add_argument("--json-output", action="store_true", help="Print raw JSON")
    args = parser.parse_args()

    from mem0_enhanced import EnhancedMemory

    memory = EnhancedMemory()
    result = memory.reembed_memories(
        agent_id=args.agent,
        dry_run=not args.execute,
        limit=args.limit,
    )

    if args.json_output:
        print(json.dumps(result, indent=2))
        return

    action = "Would re-embed" if result["dry_run"] else "Re-embedded"
    count = result["scanned"] if result["dry_run"] else result["updated"]
    print(f"{action} {count} active memories")
    if result["failed"]:
        print(f"Failed: {result['failed']}")
        for error in result["errors"][:10]:
            print(f"  - {error['id']}: {error['error']}")


if __name__ == "__main__":
    main()
