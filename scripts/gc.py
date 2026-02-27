#!/usr/bin/env python3
"""
Standalone garbage collection runner.

Usage:
  python scripts/gc.py <agent_id>              # Dry run
  python scripts/gc.py <agent_id> --execute    # Actually mark inactive
  python scripts/gc.py --all                   # Dry run all agents
  python scripts/gc.py --all --execute         # Execute for all agents

Intended to be run via cron or systemd timer.
"""

import sys
import argparse
import logging

from mem0_enhanced.core import EnhancedMemory

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Run memory garbage collection")
    parser.add_argument("agent_id", nargs="?", help="Agent ID to clean up")
    parser.add_argument("--all", action="store_true", help="Run for all known agents")
    parser.add_argument("--execute", action="store_true", help="Actually mark inactive (default is dry run)")
    parser.add_argument("--max-age", type=int, default=90, help="Max age in days for GC eligibility (default: 90)")
    args = parser.parse_args()

    if not args.agent_id and not args.all:
        parser.error("Provide an agent_id or use --all")

    memory = EnhancedMemory()
    memory.gc.max_age_days = args.max_age
    dry_run = not args.execute

    if args.all:
        print("--all requires a registry of agent IDs. Implement per your setup.")
        sys.exit(1)
    else:
        results = memory.run_gc(agent_id=args.agent_id, dry_run=dry_run)
        action = "Would mark" if dry_run else "Marked"
        print(f"{action} {len(results)} memories inactive for agent '{args.agent_id}'")
        for r in results:
            print(f"  - {r['id']}: {r['memory'][:80]}...")


if __name__ == "__main__":
    main()
