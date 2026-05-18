"""
SQLite-backed memory event logger.

Records lifecycle events for memory operations without requiring external
infrastructure. Logging failures are intentionally swallowed so telemetry never
blocks memory operations.
"""

import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class MemoryEvent:
    timestamp: str
    event_type: str
    agent_id: str
    memory_id: Optional[str] = None
    source: Optional[str] = None
    status: str = "success"
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class MemoryEventLogger:
    def __init__(self, db_path: str = "~/.mem0/memory_events.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        """Create the memory_events table if it doesn't exist."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                memory_id TEXT,
                source TEXT,
                status TEXT NOT NULL,
                latency_ms INTEGER,
                error TEXT,
                metadata TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_events_agent
            ON memory_events(agent_id, timestamp)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_events_type
            ON memory_events(event_type, timestamp)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_events_memory
            ON memory_events(memory_id, timestamp)
        """)
        conn.commit()
        conn.close()

    def log(self, event: MemoryEvent):
        """Log a memory event. Failures never propagate to callers."""
        try:
            metadata = self._serialize_metadata(event.metadata)
            with self._lock:
                conn = sqlite3.connect(str(self.db_path))
                conn.execute(
                    """INSERT INTO memory_events
                       (timestamp, event_type, agent_id, memory_id, source,
                        status, latency_ms, error, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event.timestamp,
                        event.event_type,
                        event.agent_id,
                        event.memory_id,
                        event.source,
                        event.status,
                        event.latency_ms,
                        event.error,
                        metadata,
                    ),
                )
                conn.commit()
                conn.close()
        except Exception as e:
            logger.warning(f"Failed to log memory event: {e}")

    def log_event(
        self,
        event_type: str,
        agent_id: str,
        memory_id: Optional[str] = None,
        source: Optional[str] = None,
        status: str = "success",
        latency_ms: Optional[int] = None,
        error: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        timestamp: Optional[str] = None,
    ) -> MemoryEvent:
        """Create and log a memory event, returning the event object."""
        event = MemoryEvent(
            timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
            event_type=event_type,
            agent_id=agent_id,
            memory_id=memory_id,
            source=source,
            status=status,
            latency_ms=latency_ms,
            error=error,
            metadata=metadata,
        )
        self.log(event)
        return event

    @contextmanager
    def track(
        self,
        event_type: str,
        agent_id: str,
        memory_id: Optional[str] = None,
        source: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ):
        """Track operation latency and record success or failure."""
        start = time.monotonic()
        tracker = _MemoryEventTracker(metadata=metadata)
        try:
            yield tracker
        except Exception as e:
            self.log_event(
                event_type=event_type,
                agent_id=agent_id,
                memory_id=tracker.memory_id or memory_id,
                source=source,
                status="failure",
                latency_ms=int((time.monotonic() - start) * 1000),
                error=str(e),
                metadata=tracker.metadata,
            )
            raise
        else:
            self.log_event(
                event_type=event_type,
                agent_id=agent_id,
                memory_id=tracker.memory_id or memory_id,
                source=source,
                status="success",
                latency_ms=int((time.monotonic() - start) * 1000),
                metadata=tracker.metadata,
            )

    def get_events(
        self,
        agent_id: Optional[str] = None,
        event_type: Optional[str] = None,
        memory_id: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return recent events matching the provided filters."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row

        where_clauses = []
        params: list[Any] = []
        if agent_id:
            where_clauses.append("agent_id = ?")
            params.append(agent_id)
        if event_type:
            where_clauses.append("event_type = ?")
            params.append(event_type)
        if memory_id:
            where_clauses.append("memory_id = ?")
            params.append(memory_id)
        if since:
            where_clauses.append("timestamp >= ?")
            params.append(since)
        if until:
            where_clauses.append("timestamp <= ?")
            params.append(until)

        where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        rows = conn.execute(
            f"""SELECT * FROM memory_events
                {where}
                ORDER BY timestamp DESC, id DESC
                LIMIT ?""",
            [*params, limit],
        ).fetchall()
        conn.close()

        return [self._row_to_dict(row) for row in rows]

    def get_summary(
        self,
        agent_id: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> dict[str, Any]:
        """Get aggregate counts and latency for logged memory events."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row

        where_clauses = []
        params: list[Any] = []
        if agent_id:
            where_clauses.append("agent_id = ?")
            params.append(agent_id)
        if since:
            where_clauses.append("timestamp >= ?")
            params.append(since)
        if until:
            where_clauses.append("timestamp <= ?")
            params.append(until)

        where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        totals = conn.execute(
            f"""SELECT
                    COUNT(*) AS events,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successes,
                    SUM(CASE WHEN status = 'failure' THEN 1 ELSE 0 END) AS failures,
                    AVG(latency_ms) AS avg_latency_ms
                FROM memory_events {where}""",
            params,
        ).fetchone()

        by_type = conn.execute(
            f"""SELECT event_type, COUNT(*) AS events
                FROM memory_events {where}
                GROUP BY event_type
                ORDER BY events DESC, event_type ASC""",
            params,
        ).fetchall()

        by_status = conn.execute(
            f"""SELECT status, COUNT(*) AS events
                FROM memory_events {where}
                GROUP BY status
                ORDER BY events DESC, status ASC""",
            params,
        ).fetchall()

        by_agent = conn.execute(
            f"""SELECT agent_id, COUNT(*) AS events
                FROM memory_events {where}
                GROUP BY agent_id
                ORDER BY events DESC, agent_id ASC""",
            params,
        ).fetchall()
        conn.close()

        return {
            "totals": {
                "events": totals["events"],
                "successes": totals["successes"] or 0,
                "failures": totals["failures"] or 0,
                "avg_latency_ms": round(totals["avg_latency_ms"] or 0, 1),
            },
            "by_type": [dict(row) for row in by_type],
            "by_status": [dict(row) for row in by_status],
            "by_agent": [dict(row) for row in by_agent],
        }

    def _serialize_metadata(self, metadata: Optional[dict[str, Any]]) -> Optional[str]:
        if metadata is None:
            return None
        return json.dumps(metadata, sort_keys=True, default=str)

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        event = dict(row)
        metadata = event.get("metadata")
        event["metadata"] = json.loads(metadata) if metadata else None
        return event


class _MemoryEventTracker:
    def __init__(self, metadata: Optional[dict[str, Any]] = None):
        self.memory_id: Optional[str] = None
        self.metadata: dict[str, Any] = dict(metadata or {})

    def set_memory_id(self, memory_id: str):
        """Attach a memory ID discovered during the tracked operation."""
        self.memory_id = memory_id

    def update_metadata(self, **metadata: Any):
        """Merge additional metadata into the event before it is logged."""
        self.metadata.update(metadata)
