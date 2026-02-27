#!/usr/bin/env python3.10
"""
Migrate memories from basic-memory and mcp-memory-bank into mem0_enhanced.

Sources:
  1. basic-memory markdown files  (~/basic-memory + ~/Documents/basic-memory)
  2. basic-memory SQLite DB        (~/.basic-memory/memory.db)
  3. mcp-memory-bank SQLite DB     (~/mcp-data/memory-keeper/context.db)

Usage:
  python scripts/migrate.py --dry-run          # preview what would be imported
  python scripts/migrate.py                    # run the migration
  python scripts/migrate.py --source basic     # only basic-memory
  python scripts/migrate.py --source mcp       # only mcp-memory-bank
  python scripts/migrate.py --agent-id myproj  # override agent_id for all imports
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

BASIC_MEMORY_DIRS = [
    Path.home() / "basic-memory",
    Path.home() / "Documents" / "basic-memory",
]
BASIC_MEMORY_DB = Path.home() / ".basic-memory" / "memory.db"
MCP_MEMORY_DB = Path.home() / "mcp-data" / "memory-keeper" / "context.db"

FOLDER_TO_TYPE = {
    "architecture": "durable_fact",
    "patterns": "durable_fact",
    "research": "durable_fact",
    "competitors": "durable_fact",
    "setup": "durable_fact",
    "tools": "durable_fact",
    "people": "durable_fact",
    "diagnostics": "durable_fact",
    "decisions": "decision",
    "bugs": "correction",
    "features": "durable_fact",
    "goals": "preference",
    "plans": "open_loop",
    "projects": "durable_fact",
    "reviews": "durable_fact",
    "settings-redesign": "durable_fact",
    "oto": "durable_fact",
}

MCP_CATEGORY_TO_TYPE = {
    "decision": "decision",
    "progress": "durable_fact",
    "error": "open_loop",
}

OBSERVATION_CATEGORY_TO_TYPE = {
    "preference": "preference",
    "tech": "durable_fact",
    "pattern": "durable_fact",
    "principle": "durable_fact",
    "config": "durable_fact",
    "product": "durable_fact",
    "requirement": "durable_fact",
    "vision": "preference",
    "goal": "preference",
    "strategy": "preference",
    "advantage": "durable_fact",
    "positioning": "durable_fact",
    "note": "durable_fact",
    "repo": "durable_fact",
}

MAX_MEMORY_CHARS = 8000


@dataclass
class MemoryItem:
    text: str
    agent_id: str
    memory_type: str
    source: str
    source_path: str = ""
    metadata: dict = field(default_factory=dict)


def infer_type_from_path(file_path: Path) -> str:
    parts = [p.lower() for p in file_path.parts]
    for folder, mem_type in FOLDER_TO_TYPE.items():
        if folder in parts:
            return mem_type
    return "durable_fact"


def infer_agent_from_path(file_path: Path, override: Optional[str] = None) -> str:
    if override:
        return override
    parts = [p.lower() for p in file_path.parts]
    if "adw" in parts:
        return "adw"
    if "oto" in parts:
        return "oto"
    if "opensesh" in parts:
        return "opensesh"
    if "ajax" in parts:
        return "ajax"
    return "general"


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Strip YAML frontmatter, return (metadata_dict, body)."""
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            fm_text = content[3:end].strip()
            body = content[end + 3:].strip()
            meta = {}
            for line in fm_text.split("\n"):
                if ":" in line:
                    key, _, val = line.partition(":")
                    meta[key.strip()] = val.strip()
            return meta, body
    return {}, content


def truncate_for_memory(text: str, max_chars: int = MAX_MEMORY_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[... truncated for memory storage ...]"


def collect_basic_memory_markdown() -> list[MemoryItem]:
    """Collect markdown files from basic-memory directories."""
    items = []
    for base_dir in BASIC_MEMORY_DIRS:
        if not base_dir.exists():
            logger.info(f"Skipping {base_dir} (not found)")
            continue
        for md_file in sorted(base_dir.rglob("*.md")):
            content = md_file.read_text(encoding="utf-8", errors="replace")
            meta, body = parse_frontmatter(content)
            if not body.strip():
                continue

            rel_path = md_file.relative_to(base_dir)
            mem_type = infer_type_from_path(rel_path)
            agent_id = infer_agent_from_path(rel_path)
            title = meta.get("title", md_file.stem)
            tags = meta.get("tags", "")

            text = truncate_for_memory(body)

            items.append(MemoryItem(
                text=text,
                agent_id=agent_id,
                memory_type=mem_type,
                source="basic-memory-markdown",
                source_path=str(md_file),
                metadata={
                    "title": title,
                    "tags": tags,
                    "original_permalink": meta.get("permalink", ""),
                    "migrated_from": "basic-memory",
                },
            ))
    return items


def collect_basic_memory_observations() -> list[MemoryItem]:
    """Collect observations from basic-memory SQLite database."""
    if not BASIC_MEMORY_DB.exists():
        logger.info(f"Skipping basic-memory DB (not found at {BASIC_MEMORY_DB})")
        return []

    items = []
    conn = sqlite3.connect(str(BASIC_MEMORY_DB))
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT o.content, o.category, o.context, o.tags,
               e.title as entity_title, e.entity_type, e.file_path,
               p.name as project_name
        FROM observation o
        JOIN entity e ON o.entity_id = e.id
        JOIN project p ON o.project_id = p.id
        ORDER BY o.id
    """).fetchall()

    for row in rows:
        category = row["category"] or "note"
        mem_type = OBSERVATION_CATEGORY_TO_TYPE.get(category, "durable_fact")

        project = (row["project_name"] or "general").lower()
        agent_id = project if project in ("oto", "adw") else "general"

        entity_title = row["entity_title"] or ""
        text = row["content"]
        if entity_title:
            text = f"[{entity_title}] {text}"

        items.append(MemoryItem(
            text=text,
            agent_id=agent_id,
            memory_type=mem_type,
            source="basic-memory-observation",
            source_path=row["file_path"] or "",
            metadata={
                "entity": entity_title,
                "category": category,
                "migrated_from": "basic-memory",
            },
        ))

    conn.close()
    return items


def collect_basic_memory_relations() -> list[MemoryItem]:
    """Collect relations from basic-memory SQLite database as fact memories."""
    if not BASIC_MEMORY_DB.exists():
        return []

    items = []
    conn = sqlite3.connect(str(BASIC_MEMORY_DB))
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT r.relation_type, r.context,
               e1.title as from_title,
               COALESCE(e2.title, r.to_name) as to_title,
               p.name as project_name
        FROM relation r
        JOIN entity e1 ON r.from_id = e1.id
        LEFT JOIN entity e2 ON r.to_id = e2.id
        JOIN project p ON r.project_id = p.id
        ORDER BY r.id
    """).fetchall()

    for row in rows:
        rel_type = row["relation_type"].replace("_", " ")
        text = f"{row['from_title']} {rel_type} {row['to_title']}"
        if row["context"]:
            text += f" — {row['context']}"

        project = (row["project_name"] or "general").lower()
        agent_id = project if project in ("oto", "adw") else "general"

        items.append(MemoryItem(
            text=text,
            agent_id=agent_id,
            memory_type="durable_fact",
            source="basic-memory-relation",
            metadata={
                "relation_type": row["relation_type"],
                "migrated_from": "basic-memory",
            },
        ))

    conn.close()
    return items


def collect_mcp_memory_bank() -> list[MemoryItem]:
    """Collect context items from mcp-memory-bank SQLite database."""
    if not MCP_MEMORY_DB.exists():
        logger.info(f"Skipping mcp-memory-bank (not found at {MCP_MEMORY_DB})")
        return []

    items = []
    conn = sqlite3.connect(str(MCP_MEMORY_DB))
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT ci.key, ci.value, ci.category, ci.priority,
               s.name as session_name, s.working_directory
        FROM context_items ci
        JOIN sessions s ON ci.session_id = s.id
        ORDER BY ci.created_at
    """).fetchall()

    for row in rows:
        category = row["category"] or "progress"
        mem_type = MCP_CATEGORY_TO_TYPE.get(category, "durable_fact")

        workdir = row["working_directory"] or ""
        if "echo_v2" in workdir:
            agent_id = "oto"
        elif "adw" in workdir:
            agent_id = "adw"
        else:
            agent_id = "general"

        text = truncate_for_memory(row["value"])

        items.append(MemoryItem(
            text=text,
            agent_id=agent_id,
            memory_type=mem_type,
            source="mcp-memory-bank",
            source_path=row["key"],
            metadata={
                "session": row["session_name"] or "",
                "priority": row["priority"] or "normal",
                "migrated_from": "mcp-memory-bank",
            },
        ))

    conn.close()
    return items


def print_summary(items: list[MemoryItem]):
    """Print a summary of what will be migrated."""
    by_source: dict[str, int] = {}
    by_agent: dict[str, int] = {}
    by_type: dict[str, int] = {}

    for item in items:
        by_source[item.source] = by_source.get(item.source, 0) + 1
        by_agent[item.agent_id] = by_agent.get(item.agent_id, 0) + 1
        by_type[item.memory_type] = by_type.get(item.memory_type, 0) + 1

    print(f"\n{'='*60}")
    print(f"  Migration Summary: {len(items)} memories to import")
    print(f"{'='*60}")

    print(f"\n  By source:")
    for src, count in sorted(by_source.items()):
        print(f"    {src:<30} {count:>4}")

    print(f"\n  By agent_id:")
    for agent, count in sorted(by_agent.items()):
        print(f"    {agent:<30} {count:>4}")

    print(f"\n  By memory_type:")
    for mtype, count in sorted(by_type.items()):
        print(f"    {mtype:<30} {count:>4}")

    print()


CHECKPOINT_FILE = Path(__file__).parent.parent / ".migration_checkpoint.json"


def load_checkpoint() -> set[str]:
    """Load the set of already-migrated source_paths."""
    if CHECKPOINT_FILE.exists():
        data = json.loads(CHECKPOINT_FILE.read_text())
        return set(data.get("completed", []))
    return set()


def save_checkpoint(completed: set[str]):
    CHECKPOINT_FILE.write_text(json.dumps({"completed": sorted(completed)}, indent=2))


def log(msg: str):
    print(msg, flush=True)


def run_migration(items: list[MemoryItem], dry_run: bool = True):
    """Execute the migration."""
    if dry_run:
        log("\n  [DRY RUN] No memories will be stored.\n")
        for i, item in enumerate(items):
            preview = item.text[:100].replace("\n", " ")
            log(f"  {i+1:>4}. [{item.agent_id}/{item.memory_type}] {preview}...")
        log(f"\n  Total: {len(items)} memories would be imported.")
        log("  Run without --dry-run to execute.\n")
        return

    from mem0_enhanced import EnhancedMemory

    completed = load_checkpoint()
    if completed:
        log(f"\n  Resuming migration — {len(completed)} items already done.")

    log("\n  Initializing EnhancedMemory...")
    memory = EnhancedMemory()
    log("  Ready. Starting import...\n")

    success = 0
    failed = 0
    deduplicated = 0
    skipped = 0
    start_time = time.time()

    for i, item in enumerate(items):
        checkpoint_key = f"{item.source}::{item.source_path or item.text[:80]}"
        if checkpoint_key in completed:
            skipped += 1
            continue

        try:
            item_start = time.time()
            result = memory.add(
                text=item.text,
                agent_id=item.agent_id,
                memory_type=item.memory_type,
                metadata=item.metadata,
            )

            events = result.get("results", [])
            added = any(e.get("event") == "ADD" for e in events)
            elapsed_item = time.time() - item_start

            if added:
                success += 1
                status = "ADDED"
            else:
                deduplicated += 1
                status = "DEDUP"

            done = success + deduplicated + failed + skipped
            elapsed_total = time.time() - start_time
            remaining = len(items) - done
            rate = elapsed_total / max(done - skipped, 1)
            eta_min = (remaining * rate) / 60

            preview = item.text[:70].replace("\n", " ")
            log(f"  [{status}] {done}/{len(items)} ({elapsed_item:.0f}s) "
                f"[{item.agent_id}/{item.memory_type}] {preview}... "
                f"(ETA: {eta_min:.0f}min)")

            completed.add(checkpoint_key)
            if done % 5 == 0:
                save_checkpoint(completed)

        except Exception as e:
            failed += 1
            log(f"  [FAIL] {i+1}/{len(items)} [{item.agent_id}/{item.memory_type}]: {e}")
            completed.add(checkpoint_key)

    save_checkpoint(completed)

    elapsed_total = time.time() - start_time
    log(f"\n{'='*60}")
    log(f"  Migration Complete ({elapsed_total/60:.1f} minutes)")
    log(f"{'='*60}")
    log(f"    Added:        {success}")
    log(f"    Deduplicated: {deduplicated}")
    log(f"    Failed:       {failed}")
    log(f"    Skipped:      {skipped} (already imported)")
    log(f"    Total:        {len(items)}")
    log()


def main():
    parser = argparse.ArgumentParser(description="Migrate memories into mem0_enhanced")
    parser.add_argument("--dry-run", action="store_true", help="Preview without importing")
    parser.add_argument("--source", choices=["all", "basic", "mcp"], default="all",
                        help="Which source to migrate (default: all)")
    parser.add_argument("--agent-id", type=str, default=None,
                        help="Override agent_id for all imports")
    args = parser.parse_args()

    all_items: list[MemoryItem] = []

    if args.source in ("all", "basic"):
        logger.info("Collecting basic-memory markdown files...")
        md_items = collect_basic_memory_markdown()
        logger.info(f"  Found {len(md_items)} markdown files")

        logger.info("Collecting basic-memory observations...")
        obs_items = collect_basic_memory_observations()
        logger.info(f"  Found {len(obs_items)} observations")

        logger.info("Collecting basic-memory relations...")
        rel_items = collect_basic_memory_relations()
        logger.info(f"  Found {len(rel_items)} relations")

        all_items.extend(md_items)
        all_items.extend(obs_items)
        all_items.extend(rel_items)

    if args.source in ("all", "mcp"):
        logger.info("Collecting mcp-memory-bank context items...")
        mcp_items = collect_mcp_memory_bank()
        logger.info(f"  Found {len(mcp_items)} context items")
        all_items.extend(mcp_items)

    if args.agent_id:
        for item in all_items:
            item.agent_id = args.agent_id

    if not all_items:
        print("No memories found to migrate.")
        return

    print_summary(all_items)
    run_migration(all_items, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
