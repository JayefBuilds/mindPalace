#!/usr/bin/env python3
"""Generate a static HTML inspection report for Mind Palace memories."""

import argparse
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def render_table_rows(memories: list[dict]) -> str:
    rows = []
    for mem in memories:
        meta = mem.get("metadata", {})
        rows.append(
            "<tr>"
            f"<td><code>{esc(mem.get('id'))}</code></td>"
            f"<td>{esc(meta.get('agent_id') or meta.get('user_id') or 'unknown')}</td>"
            f"<td>{esc(lifecycle_of(mem))}</td>"
            f"<td>{esc(meta.get('memory_type', 'unknown'))}</td>"
            f"<td>{esc(meta.get('access_count', 0))}</td>"
            f"<td>{esc(mem.get('memory'))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def lifecycle_of(memory: dict) -> str:
    meta = memory.get("metadata", {})
    if meta.get("lifecycle"):
        return meta["lifecycle"]
    if meta.get("status") == "inactive":
        return "pruned"
    return "active"


def render_events(events: list[dict]) -> str:
    rows = []
    for event in events:
        rows.append(
            "<tr>"
            f"<td>{esc(event.get('timestamp'))}</td>"
            f"<td>{esc(event.get('agent_id'))}</td>"
            f"<td>{esc(event.get('event_type'))}</td>"
            f"<td><code>{esc(event.get('memory_id') or '')}</code></td>"
            f"<td>{esc(event.get('status'))}</td>"
            f"<td><pre>{esc(json.dumps(event.get('metadata'), indent=2) if event.get('metadata') else '')}</pre></td>"
            "</tr>"
        )
    return "\n".join(rows)


def main():
    parser = argparse.ArgumentParser(description="Generate a Mind Palace inspection report")
    parser.add_argument("--agent", help="Optional agent ID filter")
    parser.add_argument("--limit", type=int, default=500, help="Max memories to include")
    parser.add_argument("--events", type=int, default=100, help="Max recent events to include")
    parser.add_argument("--output", default="snapshots/mindpalace-report.html")
    args = parser.parse_args()

    from mem0_enhanced import EnhancedMemory

    memory = EnhancedMemory()
    health = memory.health_status(agent_id=args.agent, scan_limit=max(args.limit, 1))
    memories = list(memory._scroll_qdrant_memories(agent_id=args.agent, scan_limit=args.limit, with_vectors=False))
    events = memory.event_logger.get_events(agent_id=args.agent, limit=args.events)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Mind Palace Inspection Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #1f2937; }}
    h1, h2 {{ margin-bottom: 8px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 20px 0; }}
    .metric {{ border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; background: #f9fafb; }}
    .metric b {{ display: block; font-size: 24px; }}
    table {{ width: 100%; border-collapse: collapse; margin: 16px 0 32px; table-layout: fixed; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 8px; vertical-align: top; text-align: left; }}
    th {{ font-size: 12px; text-transform: uppercase; color: #6b7280; }}
    code {{ font-size: 12px; }}
    pre {{ margin: 0; white-space: pre-wrap; font-size: 12px; }}
  </style>
</head>
<body>
  <h1>Mind Palace Inspection Report</h1>
  <p>Agent filter: <code>{esc(args.agent or 'all')}</code></p>

  <h2>Health</h2>
  <div class="grid">
    <div class="metric"><span>Qdrant</span><b>{esc('ok' if health['qdrant']['ok'] else 'error')}</b></div>
    <div class="metric"><span>Ollama</span><b>{esc('ok' if health['ollama']['ok'] else 'error')}</b></div>
    <div class="metric"><span>Graph</span><b>{esc('connected' if health['graph']['connected'] else 'off/error')}</b></div>
    <div class="metric"><span>Scanned</span><b>{esc(health['memories']['scanned'])}</b></div>
    <div class="metric"><span>Active</span><b>{esc(health['memories']['active'])}</b></div>
    <div class="metric"><span>Archived</span><b>{esc(health['memories']['archived'])}</b></div>
    <div class="metric"><span>Pruned</span><b>{esc(health['memories']['pruned'])}</b></div>
    <div class="metric"><span>Missing vector</span><b>{esc(health['memories']['missing_vector'])}</b></div>
  </div>

  <h2>Memories</h2>
  <table>
    <thead><tr><th>ID</th><th>Agent</th><th>Lifecycle</th><th>Type</th><th>Access</th><th>Text</th></tr></thead>
    <tbody>{render_table_rows(memories)}</tbody>
  </table>

  <h2>Recent Events</h2>
  <table>
    <thead><tr><th>Time</th><th>Agent</th><th>Type</th><th>Memory</th><th>Status</th><th>Metadata</th></tr></thead>
    <tbody>{render_events(events)}</tbody>
  </table>
</body>
</html>
""",
        encoding="utf-8",
    )
    print(output.resolve())


if __name__ == "__main__":
    main()
