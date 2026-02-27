"""Tests for the token logger module."""

import os
import tempfile
import pytest

from mem0_enhanced.token_logger import TokenLogger, TokenEvent


@pytest.fixture
def logger_instance():
    """Create a token logger with a temporary database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    tl = TokenLogger(db_path=db_path)
    yield tl
    os.unlink(db_path)


def _make_event(**kwargs) -> TokenEvent:
    defaults = {
        "timestamp": "2026-02-26T12:00:00+00:00",
        "provider": "ollama",
        "model": "phi3:mini",
        "source": "query_rewrite",
        "agent_id": "test-project",
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
        "latency_ms": 200,
        "estimated_cost_usd": 0.0,
    }
    defaults.update(kwargs)
    return TokenEvent(**defaults)


class TestTokenLogger:
    def test_basic_logging(self, logger_instance):
        """Log an event and query it back."""
        event = _make_event()
        logger_instance.log(event)

        summary = logger_instance.get_summary()
        assert summary["totals"]["calls"] == 1
        assert summary["totals"]["total_tokens"] == 150

    def test_context_manager_with_record(self, logger_instance):
        """track() with record() should log an event."""
        with logger_instance.track("ollama", "phi3:mini", "query_rewrite", "test") as t:
            t.record(100, 50)

        summary = logger_instance.get_summary()
        assert summary["totals"]["calls"] == 1
        assert summary["totals"]["input_tokens"] == 100
        assert summary["totals"]["output_tokens"] == 50

    def test_context_manager_without_record(self, logger_instance):
        """track() without record() should not log anything."""
        with logger_instance.track("ollama", "phi3:mini", "query_rewrite", "test"):
            pass

        summary = logger_instance.get_summary()
        assert summary["totals"]["calls"] == 0

    def test_anthropic_cost_estimation(self, logger_instance):
        """Anthropic cost should match known pricing."""
        cost = logger_instance.estimate_cost(
            "anthropic", "claude-sonnet-4-20250514", 1_000_000, 1_000_000
        )
        assert cost == pytest.approx(18.0, abs=0.01)

    def test_ollama_zero_cost(self, logger_instance):
        """Ollama calls should always have $0 cost."""
        cost = logger_instance.estimate_cost("ollama", "phi3:mini", 10000, 5000)
        assert cost == 0.0

    def test_summary_aggregation(self, logger_instance):
        """Log 10 events across 3 agents and verify totals."""
        for i in range(10):
            agent = f"agent-{i % 3}"
            event = _make_event(agent_id=agent, input_tokens=100, output_tokens=50)
            logger_instance.log(event)

        summary = logger_instance.get_summary()
        assert summary["totals"]["calls"] == 10
        assert summary["totals"]["total_tokens"] == 1500
        assert len(summary["by_agent"]) == 3

    def test_agent_filter(self, logger_instance):
        """Filter should return only matching agent events."""
        logger_instance.log(_make_event(agent_id="agent-a"))
        logger_instance.log(_make_event(agent_id="agent-b"))
        logger_instance.log(_make_event(agent_id="agent-a"))

        summary = logger_instance.get_summary(agent_id="agent-a")
        assert summary["totals"]["calls"] == 2

    def test_failure_resilience(self, logger_instance):
        """SQLite failure should not raise an exception."""
        logger_instance.db_path = "/nonexistent/path/db.sqlite"
        event = _make_event()
        logger_instance.log(event)  # Should not raise

    def test_log_ollama_call_convenience(self, logger_instance):
        """log_ollama_call should create a proper event."""
        logger_instance.log_ollama_call(
            model="phi3:mini",
            source="auto_type",
            agent_id="test",
            input_tokens=50,
            output_tokens=10,
        )

        summary = logger_instance.get_summary()
        assert summary["totals"]["calls"] == 1
        assert summary["by_provider"][0]["provider"] == "ollama"
