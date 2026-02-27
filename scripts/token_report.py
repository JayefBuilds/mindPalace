#!/usr/bin/env python3
"""
Token usage report generator.

Usage:
  python scripts/token_report.py                        # All-time summary
  python scripts/token_report.py --agent oto-dev        # Single agent
  python scripts/token_report.py --since 2026-02-01     # Since date
  python scripts/token_report.py --today                # Today only
  python scripts/token_report.py --json                 # JSON output
"""

import argparse
import json
from datetime import datetime, timezone, timedelta

from mem0_enhanced.token_logger import TokenLogger


def main():
    parser = argparse.ArgumentParser(description="Token usage report")
    parser.add_argument("--agent", help="Filter by agent ID")
    parser.add_argument("--since", help="Start date (ISO format)")
    parser.add_argument("--until", help="End date (ISO format)")
    parser.add_argument("--today", action="store_true", help="Today only")
    parser.add_argument("--week", action="store_true", help="Last 7 days")
    parser.add_argument("--month", action="store_true", help="Last 30 days")
    parser.add_argument("--json-output", action="store_true", help="JSON output")
    args = parser.parse_args()

    since = args.since
    until = args.until

    if args.today:
        since = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00")
    elif args.week:
        since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    elif args.month:
        since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    token_logger = TokenLogger()
    summary = token_logger.get_summary(agent_id=args.agent, since=since, until=until)

    if args.json_output:
        print(json.dumps(summary, indent=2))
        return

    t = summary["totals"]
    print(f"\n{'='*60}")
    print(f"  TOKEN USAGE REPORT")
    if args.agent:
        print(f"  Agent: {args.agent}")
    if since:
        print(f"  Since: {since}")
    print(f"{'='*60}\n")

    print(f"  Total calls:     {t['calls']:,}")
    print(f"  Input tokens:    {t['input_tokens']:,}")
    print(f"  Output tokens:   {t['output_tokens']:,}")
    print(f"  Total tokens:    {t['total_tokens']:,}")
    print(f"  Estimated cost:  ${t['estimated_cost_usd']:.4f}")
    print(f"  Avg latency:     {t['avg_latency_ms']:.0f}ms")

    if summary["by_provider"]:
        print(f"\n  By Provider:")
        for p in summary["by_provider"]:
            print(f"    {p['provider']:12s}  {p['tokens']:>10,} tokens  ${p['cost']:.4f}")

    if summary["by_source"]:
        print(f"\n  By Component:")
        for s in summary["by_source"]:
            print(f"    {s['source']:20s}  {s['tokens']:>10,} tokens  ${s['cost']:.4f}")

    if summary["by_agent"]:
        print(f"\n  By Agent:")
        for a in summary["by_agent"]:
            print(f"    {a['agent_id']:20s}  {a['tokens']:>10,} tokens  ${a['cost']:.4f}")

    if summary["daily_trend"]:
        print(f"\n  Daily Trend (last 30 days):")
        for d in summary["daily_trend"][:10]:
            bar = "█" * min(int(d['cost'] * 100), 50)
            print(f"    {d['day']}  {d['tokens']:>8,} tokens  ${d['cost']:.4f}  {bar}")

    print()


if __name__ == "__main__":
    main()
