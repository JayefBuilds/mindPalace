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


def attr(value) -> str:
    return esc(value).replace('"', "&quot;")


def memory_agent(memory: dict) -> str:
    meta = memory.get("metadata", {})
    return meta.get("agent_id") or meta.get("user_id") or "unknown"


def memory_module(memory: dict) -> str:
    meta = memory.get("metadata", {})
    return meta.get("source") or meta.get("module") or meta.get("created_by") or ""


def render_table_rows(memories: list[dict]) -> str:
    rows = []
    for mem in memories:
        meta = mem.get("metadata", {})
        agent = memory_agent(mem)
        lifecycle = lifecycle_of(mem)
        memory_type = meta.get("memory_type", "unknown")
        module = memory_module(mem)
        rows.append(
            "<tr "
            f'data-agent="{attr(agent)}" '
            f'data-lifecycle="{attr(lifecycle)}" '
            f'data-type="{attr(memory_type)}" '
            f'data-module="{attr(module)}" '
            f'data-search="{attr(" ".join([str(mem.get("id") or ""), str(agent), str(lifecycle), str(memory_type), str(module), str(mem.get("memory") or "")]).lower())}">'
            f"<td><code>{esc(mem.get('id'))}</code></td>"
            f"<td>{esc(agent)}</td>"
            f"<td>{esc(lifecycle)}</td>"
            f"<td>{esc(memory_type)}</td>"
            f"<td>{esc(module or '—')}</td>"
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
        agent = event.get("agent_id") or "unknown"
        event_type = event.get("event_type") or "unknown"
        source = event.get("source") or ""
        status = event.get("status") or "unknown"
        metadata = json.dumps(event.get("metadata"), indent=2) if event.get("metadata") else ""
        rows.append(
            "<tr "
            f'data-agent="{attr(agent)}" '
            f'data-event-type="{attr(event_type)}" '
            f'data-source="{attr(source)}" '
            f'data-status="{attr(status)}" '
            f'data-search="{attr(" ".join([str(event.get("timestamp") or ""), str(agent), str(event_type), str(source), str(event.get("memory_id") or ""), str(status), metadata]).lower())}">'
            f"<td>{esc(event.get('timestamp'))}</td>"
            f"<td>{esc(agent)}</td>"
            f"<td>{esc(event_type)}</td>"
            f"<td>{esc(source or '—')}</td>"
            f"<td><code>{esc(event.get('memory_id') or '')}</code></td>"
            f"<td>{esc(status)}</td>"
            f"<td><pre>{esc(metadata)}</pre></td>"
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
    .panel {{ border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; margin: 16px 0; background: #ffffff; }}
    .filters {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; align-items: end; }}
    label {{ display: grid; gap: 4px; font-size: 12px; font-weight: 600; color: #4b5563; }}
    select, input {{ width: 100%; box-sizing: border-box; border: 1px solid #d1d5db; border-radius: 6px; padding: 8px; font: inherit; background: white; }}
    button {{ border: 1px solid #d1d5db; border-radius: 6px; padding: 8px 10px; font: inherit; background: #f9fafb; cursor: pointer; }}
    button:hover {{ background: #f3f4f6; }}
    .count {{ color: #6b7280; font-size: 13px; margin: 8px 0 0; }}
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
  <div class="panel">
    <div class="filters" data-table="memories-table">
      <label>Agent<select data-filter="agent"><option value="">All agents</option></select></label>
      <label>Lifecycle<select data-filter="lifecycle"><option value="">All lifecycle states</option></select></label>
      <label>Type<select data-filter="type"><option value="">All memory types</option></select></label>
      <label>Module<select data-filter="module"><option value="">All modules</option></select></label>
      <label>Search<input data-filter="search" type="search" placeholder="Search memory text or ID" /></label>
      <button type="button" data-reset>Reset</button>
    </div>
    <p class="count"><span data-visible-count="memories-table">0</span> of <span data-total-count="memories-table">0</span> memories shown</p>
  </div>
  <table id="memories-table">
    <thead><tr><th>ID</th><th>Agent</th><th>Lifecycle</th><th>Type</th><th>Module</th><th>Access</th><th>Text</th></tr></thead>
    <tbody>{render_table_rows(memories)}</tbody>
  </table>

  <h2>Recent Events</h2>
  <div class="panel">
    <div class="filters" data-table="events-table">
      <label>Agent<select data-filter="agent"><option value="">All agents</option></select></label>
      <label>Event<select data-filter="eventType"><option value="">All event types</option></select></label>
      <label>Module/Source<select data-filter="source"><option value="">All sources</option></select></label>
      <label>Status<select data-filter="status"><option value="">All statuses</option></select></label>
      <label>Search<input data-filter="search" type="search" placeholder="Search event metadata or ID" /></label>
      <button type="button" data-reset>Reset</button>
    </div>
    <p class="count"><span data-visible-count="events-table">0</span> of <span data-total-count="events-table">0</span> events shown</p>
  </div>
  <table id="events-table">
    <thead><tr><th>Time</th><th>Agent</th><th>Type</th><th>Source</th><th>Memory</th><th>Status</th><th>Metadata</th></tr></thead>
    <tbody>{render_events(events)}</tbody>
  </table>
  <script>
    function uniqueValues(rows, key) {{
      const values = new Set();
      rows.forEach(row => {{
        const value = row.dataset[key] || "";
        if (value) values.add(value);
      }});
      return Array.from(values).sort((a, b) => a.localeCompare(b));
    }}

    function populateSelect(select, rows, key) {{
      uniqueValues(rows, key).forEach(value => {{
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        select.appendChild(option);
      }});
    }}

    function rowMatches(row, filters) {{
      for (const [key, value] of Object.entries(filters)) {{
        if (!value) continue;
        if (key === "search") {{
          if (!(row.dataset.search || "").includes(value.toLowerCase())) return false;
        }} else if ((row.dataset[key] || "") !== value) {{
          return false;
        }}
      }}
      return true;
    }}

    function applyFilters(panel) {{
      const tableId = panel.dataset.table;
      const table = document.getElementById(tableId);
      const rows = Array.from(table.querySelectorAll("tbody tr"));
      const filters = {{}};
      panel.querySelectorAll("[data-filter]").forEach(input => {{
        filters[input.dataset.filter] = input.value.trim();
      }});

      let visible = 0;
      rows.forEach(row => {{
        const matched = rowMatches(row, filters);
        row.style.display = matched ? "" : "none";
        if (matched) visible += 1;
      }});

      document.querySelector(`[data-visible-count="${{tableId}}"]`).textContent = visible;
      document.querySelector(`[data-total-count="${{tableId}}"]`).textContent = rows.length;
    }}

    document.querySelectorAll(".filters").forEach(panel => {{
      const table = document.getElementById(panel.dataset.table);
      const rows = Array.from(table.querySelectorAll("tbody tr"));

      panel.querySelectorAll("select[data-filter]").forEach(select => {{
        populateSelect(select, rows, select.dataset.filter);
      }});

      panel.querySelectorAll("[data-filter]").forEach(input => {{
        input.addEventListener("input", () => applyFilters(panel));
        input.addEventListener("change", () => applyFilters(panel));
      }});

      panel.querySelector("[data-reset]").addEventListener("click", () => {{
        panel.querySelectorAll("[data-filter]").forEach(input => {{
          input.value = "";
        }});
        applyFilters(panel);
      }});

      applyFilters(panel);
    }});
  </script>
</body>
</html>
""",
        encoding="utf-8",
    )
    print(output.resolve())


if __name__ == "__main__":
    main()
