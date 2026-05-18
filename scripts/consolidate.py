#!/usr/bin/env python3
"""Run memory consolidation for an agent."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main():
    parser = argparse.ArgumentParser(description="Run Mind Palace memory consolidation")
    parser.add_argument("agent_id", help="Agent/project ID to consolidate")
    parser.add_argument("--execute", action="store_true", help="Apply approved proposals; default is dry run")
    parser.add_argument("--max-memories", type=int, default=150)
    parser.add_argument("--json-output", action="store_true")
    args = parser.parse_args()

    from mem0_enhanced import EnhancedMemory

    memory = EnhancedMemory()
    result = memory.run_consolidation(
        agent_id=args.agent_id,
        dry_run=not args.execute,
        max_memories=args.max_memories,
    )

    if args.json_output:
        print(json.dumps(result, indent=2))
        return

    print(f"Consolidation for {args.agent_id} ({'dry run' if result['dry_run'] else 'execute'})")
    print(f"  scanned:   {result['memories_scanned']}")
    print(f"  proposals: {len(result['proposals'])}")
    print(f"  approved:  {sum(1 for d in result['decisions'] if d.get('approve'))}")
    print(f"  applied:   {len(result['applied'])}")
    print(f"  errors:    {len(result['errors'])}")
    if result.get("notes"):
        print(f"  notes:     {result['notes']}")


if __name__ == "__main__":
    main()
