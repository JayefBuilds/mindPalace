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
  <title>Mind Palace · Inspection Report</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;500;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #F5EFE4; --surface: #EDE4D3; --ink: #1C1A15; --body: #3A3528;
      --muted: #7A7060; --accent: #B8732A; --accent-deep: #96591D; --gold: #E8C88A;
      --border: #D4C8B0; --hairline: #E8E0CC;
      --serif: 'Playfair Display', Georgia, serif;
      --sans: 'Inter', system-ui, sans-serif;
      --mono: 'JetBrains Mono', 'Courier New', monospace;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      font-family: var(--sans); color: var(--body); margin: 0;
      background: var(--bg);
      background-image:
        radial-gradient(1200px 600px at 80% -10%, rgba(184,115,42,0.06), transparent 60%),
        linear-gradient(rgba(28,26,21,0.018) 1px, transparent 1px),
        linear-gradient(90deg, rgba(28,26,21,0.018) 1px, transparent 1px);
      background-size: 100% 100%, 32px 32px, 32px 32px;
      -webkit-font-smoothing: antialiased;
    }}
    .wrap {{ max-width: none; margin: 0 auto; padding: 64px clamp(40px, 5vw, 96px) 96px; }}

    /* Hero */
    .hero {{ position: relative; padding: 48px 0 40px; border-bottom: 1px solid var(--border); margin-bottom: 48px; }}
    .eyebrow {{ font-family: var(--mono); font-size: 12px; letter-spacing: 2px; text-transform: uppercase;
      color: var(--accent); margin: 0 0 16px; }}
    .eyebrow::before {{ content: "§ "; opacity: 0.7; }}
    h1 {{ font-family: var(--serif); font-weight: 700; font-size: 60px; line-height: 1.04;
      letter-spacing: -1px; color: var(--ink); margin: 0 0 12px; }}
    .tagline {{ font-family: var(--serif); font-weight: 400; font-style: italic; font-size: 22px;
      color: var(--muted); margin: 0 0 24px; }}
    .filter-pill {{ display: inline-flex; align-items: center; gap: 8px; font-family: var(--mono);
      font-size: 13px; color: var(--body); background: var(--surface); border: 1px solid var(--border);
      border-radius: 999px; padding: 6px 14px; }}
    .filter-pill b {{ color: var(--accent); font-weight: 500; }}

    h2 {{ font-family: var(--serif); font-weight: 700; font-size: 32px; letter-spacing: -0.5px;
      color: var(--ink); margin: 56px 0 4px; }}
    .section-label {{ font-family: var(--mono); font-size: 12px; letter-spacing: 2px; text-transform: uppercase;
      color: var(--muted); margin: 0 0 24px; }}
    .section-label::before {{ content: "§ "; color: var(--accent); }}

    /* Metrics */
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1px;
      background: var(--border); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; margin: 0; }}
    .metric {{ padding: 20px 18px; background: var(--surface); position: relative; transition: background 0.2s ease; }}
    .metric:hover {{ background: #F0E8D9; }}
    .metric span {{ font-family: var(--mono); font-size: 11px; letter-spacing: 1px; text-transform: uppercase;
      color: var(--muted); display: block; margin-bottom: 8px; }}
    .metric b {{ display: block; font-family: var(--serif); font-size: 34px; font-weight: 700; color: var(--ink); line-height: 1; }}
    .metric.is-ok b {{ color: var(--accent); }}
    .metric.is-bad b {{ color: #9b3a2a; }}

    /* Panels */
    .panel {{ border: 1px solid var(--border); border-radius: 12px; padding: 20px 22px; margin: 20px 0 0; background: var(--surface); }}
    .filters {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; align-items: end; }}
    label {{ display: grid; gap: 6px; font-family: var(--mono); font-size: 11px; font-weight: 500;
      letter-spacing: 0.5px; text-transform: uppercase; color: var(--muted); }}
    select, input {{ width: 100%; border: 1px solid var(--border); border-radius: 6px; padding: 9px 10px;
      font-family: var(--sans); font-size: 14px; color: var(--body); background: var(--bg);
      transition: border-color 0.15s ease, box-shadow 0.15s ease; }}
    select:focus, input:focus {{ outline: none; border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(184,115,42,0.12); }}
    button {{ border: 1px solid var(--accent); border-radius: 6px; padding: 9px 16px;
      font-family: var(--mono); font-size: 12px; letter-spacing: 0.5px; text-transform: uppercase;
      color: var(--accent); background: transparent; cursor: pointer; transition: all 0.15s ease; }}
    button:hover {{ background: var(--accent); color: var(--bg); }}
    .count {{ font-family: var(--mono); color: var(--muted); font-size: 12px; margin: 14px 0 0; }}
    .count b {{ color: var(--accent); font-weight: 500; }}

    /* Tables */
    table {{ width: 100%; border-collapse: collapse; margin: 20px 0 0; table-layout: fixed;
      border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }}
    thead {{ background: var(--ink); }}
    th {{ font-family: var(--mono); font-size: 11px; letter-spacing: 1px; text-transform: uppercase;
      color: var(--gold); padding: 14px 12px; text-align: left; font-weight: 500; }}
    td {{ border-bottom: 1px solid var(--hairline); padding: 13px 12px; vertical-align: top; text-align: left;
      font-size: 14px; line-height: 1.55; color: var(--body); }}
    tbody tr {{ background: var(--bg); transition: background 0.12s ease; }}
    tbody tr:nth-child(even) {{ background: #FAF6EC; }}
    tbody tr:hover {{ background: var(--gold); }}
    tbody tr:last-child td {{ border-bottom: none; }}
    code {{ font-family: var(--mono); font-size: 12px; color: var(--accent-deep);
      background: rgba(184,115,42,0.08); padding: 2px 6px; border-radius: 4px; }}
    pre {{ margin: 0; white-space: pre-wrap; font-family: var(--mono); font-size: 12px; color: var(--body); }}

    footer {{ margin-top: 72px; padding-top: 24px; border-top: 1px solid var(--border);
      font-family: var(--mono); font-size: 12px; color: var(--muted); display: flex;
      justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }}
    footer .mark {{ font-family: var(--serif); font-weight: 700; font-size: 16px; color: var(--accent); font-style: normal; }}
  </style>
</head>
<body>
  <div class="wrap">
  <header class="hero">
    <p class="eyebrow">Inspection Report</p>
    <h1>Mind Palace</h1>
    <p class="tagline">The palace has many rooms. Each one persists.</p>
    <span class="filter-pill">agent scope · <b>{esc(args.agent or 'all rooms')}</b></span>
  </header>

  <h2>Health</h2>
  <p class="section-label">System Vitals</p>
  <div class="grid">
    <div class="metric {esc('is-ok' if health['qdrant']['ok'] else 'is-bad')}"><span>Qdrant</span><b>{esc('ok' if health['qdrant']['ok'] else 'error')}</b></div>
    <div class="metric {esc('is-ok' if health['ollama']['ok'] else 'is-bad')}"><span>Ollama</span><b>{esc('ok' if health['ollama']['ok'] else 'error')}</b></div>
    <div class="metric {esc('is-ok' if health['graph']['connected'] else 'is-bad')}"><span>Graph</span><b>{esc('linked' if health['graph']['connected'] else 'off')}</b></div>
    <div class="metric"><span>Scanned</span><b>{esc(health['memories']['scanned'])}</b></div>
    <div class="metric"><span>Active</span><b>{esc(health['memories']['active'])}</b></div>
    <div class="metric"><span>Archived</span><b>{esc(health['memories']['archived'])}</b></div>
    <div class="metric"><span>Pruned</span><b>{esc(health['memories']['pruned'])}</b></div>
    <div class="metric"><span>No vector</span><b>{esc(health['memories']['missing_vector'])}</b></div>
  </div>

  <h2>Memories</h2>
  <p class="section-label">Stored Recollections</p>
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
  <p class="section-label">Activity Ledger</p>
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

  <footer>
    <span class="mark">Mind Palace</span>
    <span>Not magic — architecture.</span>
  </footer>
  </div>
</body>
</html>
""",
        encoding="utf-8",
    )
    print(output.resolve())


if __name__ == "__main__":
    main()
