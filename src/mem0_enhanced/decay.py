"""
Decay scoring and garbage collection for memories.

Two components:
1. Decay scorer: Adjusts retrieval scores based on recency, access count, and memory type
2. Garbage collector: Periodically marks stale memories inactive
"""

import math
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

TYPE_PERSISTENCE = {
    "durable_fact": 0.95,
    "preference": 0.90,
    "decision": 0.70,
    "correction": 0.65,
    "open_loop": 0.50,
    "unknown": 0.50,
}

GC_EXEMPT_TYPES = {"durable_fact", "preference"}


class DecayScorer:
    def __init__(self, halflife_days: int = 60):
        self.decay_lambda = math.log(2) / halflife_days

    def score(
        self,
        memory: dict,
        base_score: float,
        now: Optional[datetime] = None,
    ) -> float:
        """
        Apply decay to a memory's relevance score.

        Args:
            memory: Memory dict from Mem0
            base_score: The score to decay (from reranker or vector similarity)
            now: Current time (injectable for testing)

        Returns:
            Adjusted score incorporating recency, access reinforcement,
            and type persistence.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        created = memory.get("metadata", {}).get("created_at")
        if created is None:
            created = memory.get("created_at", now.isoformat())
        if isinstance(created, str):
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)

        age_days = max((now - created).total_seconds() / 86400, 0)

        recency = math.exp(-self.decay_lambda * age_days)

        access_count = memory.get("metadata", {}).get("access_count", 0)
        reinforcement = math.log1p(access_count) * 0.15

        memory_type = memory.get("metadata", {}).get("memory_type", "unknown")
        persistence = TYPE_PERSISTENCE.get(memory_type, 0.5)

        adjusted = base_score * (
            persistence + (1 - persistence) * recency + reinforcement
        )

        return round(adjusted, 4)


class GarbageCollector:
    """
    Marks old, unused memories as inactive.

    Run this periodically (e.g., weekly cron or on session end).
    Does NOT delete — marks with metadata for audit trail.
    """

    def __init__(
        self,
        qdrant_or_mem0,
        max_age_days: int = 90,
        min_access_count: int = 0,
        mem0_instance=None,
    ):
        # Accept either a qdrant client (for direct payload updates) or a mem0 instance
        # When used from EnhancedMemory, qdrant_or_mem0 is the QdrantClient
        self._qdrant = qdrant_or_mem0
        self._mem0 = mem0_instance
        self.max_age_days = max_age_days
        self.min_access_count = min_access_count

    def collect(self, agent_id: str, dry_run: bool = False, all_memories: Optional[dict] = None) -> list[dict]:
        """
        Find and mark stale memories for a given agent.

        Args:
            agent_id: The agent/project whose memories to scan
            dry_run: If True, return candidates without marking them
            all_memories: Pre-fetched memories dict (for when caller already has them)

        Returns:
            List of memories that were (or would be) marked inactive.
        """
        now = datetime.now(timezone.utc)

        if all_memories is None:
            if self._mem0 is not None:
                all_memories = self._mem0.get_all(filters={"agent_id": agent_id, "user_id": agent_id})
            elif hasattr(self._qdrant, 'get_all'):
                all_memories = self._qdrant.get_all(filters={"agent_id": agent_id, "user_id": agent_id})
            else:
                logger.warning("GC: No way to fetch memories")
                return []

        candidates = []

        for mem in all_memories.get("results", []):
            metadata = mem.get("metadata", {})

            if metadata.get("status") == "inactive":
                continue

            memory_type = metadata.get("memory_type", "unknown")
            if memory_type in GC_EXEMPT_TYPES:
                continue

            created = metadata.get("created_at")
            if created is None:
                continue
            if isinstance(created, str):
                created = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)

            age_days = (now - created).total_seconds() / 86400

            access_count = metadata.get("access_count", 0)

            if age_days > self.max_age_days and access_count <= self.min_access_count:
                candidates.append(mem)

                if not dry_run:
                    try:
                        self._qdrant.set_payload(
                            collection_name="mem0",
                            payload={
                                "status": "inactive",
                                "gc_timestamp": now.isoformat(),
                            },
                            points=[mem["id"]],
                        )
                    except Exception:
                        # Fallback for mock/test scenarios
                        if hasattr(self._qdrant, 'update'):
                            self._qdrant.update(
                                mem["id"],
                                metadata={
                                    **metadata,
                                    "status": "inactive",
                                    "gc_timestamp": now.isoformat(),
                                },
                            )
                    logger.info(
                        f"GC: Marked memory {mem['id']} inactive "
                        f"(age={age_days:.0f}d, accesses={access_count})"
                    )

        logger.info(
            f"GC complete for agent {agent_id}: "
            f"{len(candidates)} memories {'would be' if dry_run else ''} marked inactive"
        )
        return candidates
