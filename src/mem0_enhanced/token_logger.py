"""
Token consumption logger.

Tracks every LLM call across the system with:
- Source (which component made the call)
- Provider (anthropic, ollama)
- Model name
- Input/output token counts
- Agent ID (which project)
- Latency
- Cost estimate (for Anthropic calls)

Storage: SQLite database (lightweight, no extra infra).
All logging is non-blocking — failures never affect the main pipeline.
"""

import sqlite3
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

logger = logging.getLogger(__name__)

ANTHROPIC_PRICING = {
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
}

OLLAMA_PRICING = {}


@dataclass
class TokenEvent:
    timestamp: str
    provider: str
    model: str
    source: str
    agent_id: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: int
    estimated_cost_usd: float
    metadata: Optional[str] = None


class TokenLogger:
    def __init__(self, db_path: str = "~/.mem0/token_usage.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._lock = threading.Lock()

    def _init_db(self):
        """Create the token_usage table if it doesn't exist."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                source TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                latency_ms INTEGER NOT NULL,
                estimated_cost_usd REAL NOT NULL,
                metadata TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_token_usage_agent
            ON token_usage(agent_id, timestamp)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_token_usage_date
            ON token_usage(timestamp)
        """)
        conn.commit()
        conn.close()

    def log(self, event: TokenEvent):
        """Log a token consumption event. Non-blocking."""
        try:
            with self._lock:
                conn = sqlite3.connect(str(self.db_path))
                conn.execute(
                    """INSERT INTO token_usage
                       (timestamp, provider, model, source, agent_id,
                        input_tokens, output_tokens, total_tokens,
                        latency_ms, estimated_cost_usd, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event.timestamp, event.provider, event.model,
                        event.source, event.agent_id,
                        event.input_tokens, event.output_tokens,
                        event.total_tokens, event.latency_ms,
                        event.estimated_cost_usd, event.metadata,
                    ),
                )
                conn.commit()
                conn.close()
        except Exception as e:
            logger.warning(f"Failed to log token event: {e}")

    def log_anthropic_call(
        self,
        model: str,
        source: str,
        agent_id: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int = 0,
    ):
        """Convenience method for logging Anthropic calls."""
        cost = self.estimate_cost("anthropic", model, input_tokens, output_tokens)
        self.log(TokenEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            provider="anthropic",
            model=model,
            source=source,
            agent_id=agent_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=cost,
        ))

    def log_ollama_call(
        self,
        model: str,
        source: str,
        agent_id: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int = 0,
    ):
        """Convenience method for logging Ollama calls."""
        self.log(TokenEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            provider="ollama",
            model=model,
            source=source,
            agent_id=agent_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=0.0,
        ))

    @contextmanager
    def track(self, provider: str, model: str, source: str, agent_id: str):
        """
        Context manager for tracking a single LLM call.

        Usage:
            with token_logger.track("ollama", "phi3:mini",
                                     "query_rewrite", "my-project") as tracker:
                response = ollama.generate(...)
                tracker.record(
                    response.get("prompt_eval_count", 0),
                    response.get("eval_count", 0),
                )
        """
        tracker = _Tracker(self, provider, model, source, agent_id)
        try:
            yield tracker
        finally:
            tracker.finalize()

    def estimate_cost(self, provider: str, model: str,
                      input_tokens: int, output_tokens: int) -> float:
        """Calculate estimated USD cost for a call."""
        if provider == "ollama":
            return 0.0

        pricing = ANTHROPIC_PRICING.get(model)
        if not pricing:
            return 0.0

        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        return round(input_cost + output_cost, 6)

    def get_summary(
        self,
        agent_id: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> dict:
        """Get aggregated token usage summary."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row

        where_clauses = []
        params = []
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

        row = conn.execute(
            f"""SELECT
                COUNT(*) as total_calls,
                SUM(input_tokens) as total_input,
                SUM(output_tokens) as total_output,
                SUM(total_tokens) as total_tokens,
                SUM(estimated_cost_usd) as total_cost,
                AVG(latency_ms) as avg_latency_ms
            FROM token_usage {where}""",
            params,
        ).fetchone()

        by_provider = conn.execute(
            f"""SELECT provider,
                COUNT(*) as calls,
                SUM(total_tokens) as tokens,
                SUM(estimated_cost_usd) as cost
            FROM token_usage {where}
            GROUP BY provider""",
            params,
        ).fetchall()

        by_source = conn.execute(
            f"""SELECT source,
                COUNT(*) as calls,
                SUM(total_tokens) as tokens,
                SUM(estimated_cost_usd) as cost
            FROM token_usage {where}
            GROUP BY source
            ORDER BY cost DESC""",
            params,
        ).fetchall()

        by_agent = conn.execute(
            f"""SELECT agent_id,
                COUNT(*) as calls,
                SUM(total_tokens) as tokens,
                SUM(estimated_cost_usd) as cost
            FROM token_usage {where}
            GROUP BY agent_id
            ORDER BY cost DESC""",
            params,
        ).fetchall()

        daily = conn.execute(
            f"""SELECT DATE(timestamp) as day,
                SUM(total_tokens) as tokens,
                SUM(estimated_cost_usd) as cost,
                COUNT(*) as calls
            FROM token_usage {where}
            GROUP BY DATE(timestamp)
            ORDER BY day DESC
            LIMIT 30""",
            params,
        ).fetchall()

        conn.close()

        return {
            "totals": {
                "calls": row["total_calls"],
                "input_tokens": row["total_input"] or 0,
                "output_tokens": row["total_output"] or 0,
                "total_tokens": row["total_tokens"] or 0,
                "estimated_cost_usd": round(row["total_cost"] or 0, 4),
                "avg_latency_ms": round(row["avg_latency_ms"] or 0, 1),
            },
            "by_provider": [dict(r) for r in by_provider],
            "by_source": [dict(r) for r in by_source],
            "by_agent": [dict(r) for r in by_agent],
            "daily_trend": [dict(r) for r in daily],
        }


class _Tracker:
    """Internal helper for the track() context manager."""

    def __init__(self, token_logger: TokenLogger, provider: str, model: str,
                 source: str, agent_id: str):
        self._logger = token_logger
        self._provider = provider
        self._model = model
        self._source = source
        self._agent_id = agent_id
        self._start_time = time.monotonic()
        self._input_tokens = 0
        self._output_tokens = 0
        self._recorded = False

    def record(self, input_tokens: int, output_tokens: int):
        """Record token counts from the LLM response."""
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self._recorded = True

    def finalize(self):
        """Called automatically by the context manager on exit."""
        if not self._recorded:
            return

        elapsed_ms = int((time.monotonic() - self._start_time) * 1000)
        total = self._input_tokens + self._output_tokens
        cost = self._logger.estimate_cost(
            self._provider, self._model,
            self._input_tokens, self._output_tokens,
        )

        self._logger.log(TokenEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            provider=self._provider,
            model=self._model,
            source=self._source,
            agent_id=self._agent_id,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            total_tokens=total,
            latency_ms=elapsed_ms,
            estimated_cost_usd=cost,
        ))
