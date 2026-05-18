#!/usr/bin/env python3
"""Print Mind Palace backend and memory metadata health."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main():
    parser = argparse.ArgumentParser(description="Inspect Mind Palace health")
    parser.add_argument("--agent", help="Optional agent ID filter")
    parser.add_argument("--scan-limit", type=int, default=5000, help="Max Qdrant records to scan")
    parser.add_argument("--json-output", action="store_true", help="Print raw JSON")
    args = parser.parse_args()

    from mem0_enhanced import EnhancedMemory

    memory = EnhancedMemory()
    status = memory.health_status(agent_id=args.agent, scan_limit=args.scan_limit)

    if args.json_output:
        print(json.dumps(status, indent=2))
        return

    memories = status["memories"]
    print("Mind Palace health")
    print(f"  Qdrant: {'ok' if status['qdrant']['ok'] else 'error'}")
    if status["qdrant"]["error"]:
        print(f"    {status['qdrant']['error']}")
    print(f"  Ollama: {'ok' if status['ollama']['ok'] else 'error'}")
    if status["ollama"]["error"]:
        print(f"    {status['ollama']['error']}")
    print(f"  Graph:  {'connected' if status['graph']['connected'] else 'disabled/error'}")
    print()
    print(f"  Memories scanned: {memories['scanned']}")
    print(f"    active:          {memories['active']}")
    print(f"    archived:        {memories['archived']}")
    print(f"    pruned:          {memories['pruned']}")
    print(f"    legacy inactive: {memories['legacy_inactive']}")
    print(f"    missing text:    {memories['missing_text']}")
    print(f"    missing vector:  {memories['missing_vector']}")
    if memories["truncated"]:
        print(f"    truncated at scan limit {args.scan_limit}")


if __name__ == "__main__":
    main()
