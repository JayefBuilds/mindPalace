#!/usr/bin/env python3
"""Inspect the local Mind Palace memory event log."""

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mem0_enhanced.memory_event_logger import MemoryEventLogger


def since_for(period: str) -> str | None:
    if period == "today":
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00")
    if period == "week":
        return (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    if period == "month":
        return (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    return None


def main():
    parser = argparse.ArgumentParser(description="Inspect memory events")
    parser.add_argument("--agent", help="Filter by agent ID")
    parser.add_argument("--type", dest="event_type", help="Filter by event type")
    parser.add_argument("--memory-id", help="Filter by memory ID")
    parser.add_argument("--period", choices=["today", "week", "month", "all"], default="week")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--summary", action="store_true", help="Print aggregate summary")
    parser.add_argument("--json-output", action="store_true", help="Print raw JSON")
    args = parser.parse_args()

    logger = MemoryEventLogger()
    since = since_for(args.period)

    if args.summary:
        result = logger.get_summary(agent_id=args.agent, since=since)
    else:
        result = logger.get_events(
            agent_id=args.agent,
            event_type=args.event_type,
            memory_id=args.memory_id,
            since=since,
            limit=args.limit,
        )

    if args.json_output:
        print(json.dumps(result, indent=2))
        return

    if args.summary:
        totals = result["totals"]
        print(f"Memory events: {totals['events']} ({totals['successes']} success, {totals['failures']} failure)")
        for row in result["by_type"]:
            print(f"  {row['event_type']}: {row['events']}")
    else:
        for event in result:
            mid = f" {event['memory_id']}" if event.get("memory_id") else ""
            print(f"{event['timestamp']} {event['agent_id']} {event['event_type']}{mid} [{event['status']}]")


if __name__ == "__main__":
    main()
