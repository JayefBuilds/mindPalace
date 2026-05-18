"""
JSON bridge between claudegram's TypeScript orchestration layer and MindPalace.

Usage:
  python -m mem0_enhanced.bridge_cli retrieve-context
  python -m mem0_enhanced.bridge_cli ingest-turn
  python -m mem0_enhanced.bridge_cli seed-project

Each command reads a JSON payload from stdin and writes a JSON object to stdout.
"""

from __future__ import annotations

import hashlib
import json
import sys
from typing import Any

from .config import EnhancedMemoryConfig
from .core import EnhancedMemory
from .lifecycle import is_active


def _load_payload() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Expected JSON object payload")
    return payload


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _extract_memory_id(result: dict[str, Any]) -> str | None:
    rows = result.get("results", [])
    if rows and isinstance(rows[0], dict):
      return rows[0].get("id")
    return None


def _format_context_block(project_canon: list[dict[str, Any]], active_threads: list[dict[str, Any]], relevant: list[dict[str, Any]]) -> str:
    sections = [
        ("Project Canon", project_canon),
        ("Active Threads", active_threads),
        ("Relevant Context", relevant),
    ]

    rendered: list[str] = []
    for title, items in sections:
        rendered.append(f"## {title}")
        if not items:
            rendered.append("- (none)")
            continue
        for item in items:
            rendered.append(f"- [{item['type']}] {item['text']}")
    return "\n".join(rendered)


def _retrieve_context(memory: EnhancedMemory, payload: dict[str, Any]) -> dict[str, Any]:
    namespace_id = payload["namespace_id"]
    user_id = payload["user_id"]
    query = payload["query"]
    token_budget = int(payload.get("token_budget", 1400))
    session_context = payload.get("session_context")

    memories = memory.search(
        query=query,
        agent_id=namespace_id,
        user_id=user_id,
        session_context=session_context,
    )

    project_canon: list[dict[str, Any]] = []
    active_threads: list[dict[str, Any]] = []
    relevant: list[dict[str, Any]] = []

    char_budget = token_budget * 4
    used_chars = 0

    for item in memories:
        rendered = {
            "id": item.id,
            "text": item.text,
            "type": item.memory_type,
            "score": item.decay_score,
            "createdAt": item.created_at.isoformat(),
        }
        candidate_cost = len(rendered["text"]) + 16
        if used_chars + candidate_cost > char_budget:
            continue

        if item.memory_type in {"durable_fact", "decision"}:
            project_canon.append(rendered)
        elif item.memory_type == "open_loop":
            active_threads.append(rendered)
        else:
            relevant.append(rendered)

        used_chars += candidate_cost

    raw_context = _format_context_block(project_canon, active_threads, relevant)
    token_count = _estimate_tokens(raw_context)
    injected_ids = [
        *[item["id"] for item in project_canon],
        *[item["id"] for item in active_threads],
        *[item["id"] for item in relevant],
    ]

    return {
        "projectCanon": project_canon,
        "activeThreads": active_threads,
        "relevantContext": relevant,
        "injectedIds": injected_ids,
        "tokenCount": token_count,
        "rawContext": raw_context,
    }


def _ingest_turn(memory: EnhancedMemory, payload: dict[str, Any]) -> dict[str, Any]:
    namespace_id = payload["namespace_id"]
    user_id = payload["user_id"]
    project_id = payload["project_id"]
    agent_id = payload["agent_id"]
    agent_version = int(payload["agent_version"])
    model = payload["model"]
    request_id = payload["request_id"]
    user_message = payload["user_message"]
    assistant_response = payload["assistant_response"]
    tool_outputs = payload.get("tool_outputs", [])
    write_policy = payload.get("write_policy", {})
    allowed_types = set(write_policy.get("allowTypes", [
        "preference",
        "durable_fact",
        "decision",
        "open_loop",
        "correction",
    ]))
    blocked_terms = [_normalize_text(term) for term in write_policy.get("blockedTerms", [])]
    max_writes = int(write_policy.get("maxWritesPerTurn", 5))

    transcript_lines = [
        f"User: {user_message}",
        f"Assistant: {assistant_response}",
    ]
    for output in tool_outputs:
        transcript_lines.append(f"Tool Output: {output}")
    transcript = "\n\n".join(transcript_lines)

    existing = memory.mem0.get_all(filters={"agent_id": namespace_id, "user_id": user_id})
    existing_texts = [
        item["memory"]
        for item in existing.get("results", [])
        if is_active(item)
    ]
    existing_fingerprints = {
        hashlib.sha256(_normalize_text(text).encode("utf-8")).hexdigest()
        for text in existing_texts
    }

    shards = memory.extractor.extract(
        conversation=transcript,
        existing_memories=existing_texts,
        agent_id=namespace_id,
    )

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for shard in shards:
        text = shard["text"].strip()
        memory_type = shard["type"]
        fingerprint = hashlib.sha256(_normalize_text(text).encode("utf-8")).hexdigest()

        if len(accepted) >= max_writes:
            rejected.append({
                "type": memory_type,
                "text": text,
                "reason": "write_budget_exceeded",
            })
            continue

        if memory_type not in allowed_types:
            rejected.append({
                "type": memory_type,
                "text": text,
                "reason": "type_blocked_by_policy",
            })
            continue

        normalized = _normalize_text(text)
        if any(term and term in normalized for term in blocked_terms):
            rejected.append({
                "type": memory_type,
                "text": text,
                "reason": "blocked_term",
            })
            continue

        if fingerprint in existing_fingerprints:
            rejected.append({
                "type": memory_type,
                "text": text,
                "reason": "duplicate_hash",
            })
            continue

        result = memory.add(
            text=text,
            agent_id=namespace_id,
            user_id=user_id,
            memory_type=memory_type,
            metadata={
                "project_id": project_id,
                "agent_slug": agent_id,
                "provenance": {
                    "request_id": request_id,
                    "agent_version": agent_version,
                    "model": model,
                },
            },
        )
        accepted.append({
            "memoryId": _extract_memory_id(result),
            "type": memory_type,
            "text": text,
        })
        existing_fingerprints.add(fingerprint)

    return {
        "accepted": accepted,
        "rejected": rejected,
    }


def _seed_project(memory: EnhancedMemory, payload: dict[str, Any]) -> dict[str, Any]:
    namespace_id = payload["namespace_id"]
    user_id = payload["user_id"]
    project_id = payload["project_id"]
    agent_id = payload["agent_id"]
    charter = payload["project_charter"].strip()

    result = memory.add(
        text=charter,
        agent_id=namespace_id,
        user_id=user_id,
        memory_type="durable_fact",
        metadata={
            "project_id": project_id,
            "agent_slug": agent_id,
            "seed": True,
        },
    )
    return {
        "accepted": [{
            "memoryId": _extract_memory_id(result),
            "type": "durable_fact",
            "text": charter,
        }],
        "rejected": [],
    }


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python -m mem0_enhanced.bridge_cli <command>")

    command = sys.argv[1]
    payload = _load_payload()
    config = EnhancedMemoryConfig.from_env()
    memory = EnhancedMemory(config)

    try:
        if command == "retrieve-context":
            result = _retrieve_context(memory, payload)
        elif command == "ingest-turn":
            result = _ingest_turn(memory, payload)
        elif command == "seed-project":
            result = _seed_project(memory, payload)
        else:
            raise ValueError(f"Unknown command: {command}")

        sys.stdout.write(json.dumps(result))
        sys.stdout.flush()
        return 0
    finally:
        try:
            memory.extractor.close()
        except Exception:
            pass
        try:
            memory.auto_typer.close()
        except Exception:
            pass
        try:
            memory.llm.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
