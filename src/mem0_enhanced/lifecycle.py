"""Memory lifecycle helpers.

The older metadata contract used ``status=active|inactive``. New code uses a
more explicit lifecycle while preserving the old status field for compatibility.
"""

from __future__ import annotations

from datetime import datetime, timezone

ACTIVE = "active"
ARCHIVED = "archived"
PRUNED = "pruned"

INACTIVE_LIFECYCLES = {ARCHIVED, PRUNED}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def lifecycle_of(memory: dict) -> str:
    """Return a memory's lifecycle, mapping legacy status where needed."""
    metadata = memory.get("metadata", {}) or {}
    lifecycle = metadata.get("lifecycle")
    if lifecycle:
        return lifecycle
    if metadata.get("status") == "inactive":
        return PRUNED
    return ACTIVE


def is_active(memory: dict) -> bool:
    """Return True if a memory should participate in active retrieval."""
    return lifecycle_of(memory) == ACTIVE


def active_payload() -> dict:
    """Metadata payload for newly active memories."""
    return {
        "lifecycle": ACTIVE,
        "status": "active",
    }


def inactive_payload(lifecycle: str = PRUNED, **extra: object) -> dict:
    """Metadata payload for memories leaving active retrieval."""
    payload = {
        "lifecycle": lifecycle,
        "status": "inactive",
        "archived_at": utc_now_iso(),
    }
    payload.update(extra)
    return payload
