"""Tests for the memory event logger module."""

import os
import sqlite3
import tempfile

import pytest

from mem0_enhanced.memory_event_logger import MemoryEvent, MemoryEventLogger


@pytest.fixture
def logger_instance():
    """Create a memory event logger with a temporary database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    event_logger = MemoryEventLogger(db_path=db_path)
    yield event_logger
    os.unlink(db_path)


def _make_event(**kwargs) -> MemoryEvent:
    defaults = {
        "timestamp": "2026-02-26T12:00:00+00:00",
        "event_type": "memory_add",
        "agent_id": "test-project",
        "memory_id": "mem-1",
        "source": "core.add",
        "status": "success",
        "latency_ms": 25,
        "metadata": {"memory_type": "preference"},
    }
    defaults.update(kwargs)
    return MemoryEvent(**defaults)


class TestMemoryEventLogger:
    def test_basic_logging_and_query(self, logger_instance):
        """Log an event and query it back."""
        logger_instance.log(_make_event())

        events = logger_instance.get_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "memory_add"
        assert events[0]["agent_id"] == "test-project"
        assert events[0]["metadata"] == {"memory_type": "preference"}

    def test_log_event_convenience(self, logger_instance):
        """log_event should create and persist a timestamped event."""
        event = logger_instance.log_event(
            event_type="memory_search",
            agent_id="agent-a",
            source="core.search",
            metadata={"result_count": 3},
        )

        assert event.timestamp
        events = logger_instance.get_events(agent_id="agent-a")
        assert len(events) == 1
        assert events[0]["event_type"] == "memory_search"
        assert events[0]["metadata"]["result_count"] == 3

    def test_filters_by_agent_event_type_and_memory_id(self, logger_instance):
        """get_events should apply all supported filters."""
        logger_instance.log(_make_event(agent_id="agent-a", event_type="memory_add", memory_id="mem-1"))
        logger_instance.log(_make_event(agent_id="agent-a", event_type="memory_search", memory_id=None))
        logger_instance.log(_make_event(agent_id="agent-b", event_type="memory_add", memory_id="mem-2"))

        events = logger_instance.get_events(
            agent_id="agent-a",
            event_type="memory_add",
            memory_id="mem-1",
        )

        assert len(events) == 1
        assert events[0]["agent_id"] == "agent-a"
        assert events[0]["memory_id"] == "mem-1"

    def test_summary_aggregation(self, logger_instance):
        """Summary should aggregate totals, event types, statuses, and agents."""
        logger_instance.log(_make_event(agent_id="agent-a", event_type="memory_add", status="success"))
        logger_instance.log(_make_event(agent_id="agent-a", event_type="memory_search", status="success"))
        logger_instance.log(_make_event(agent_id="agent-b", event_type="memory_add", status="failure"))

        summary = logger_instance.get_summary()

        assert summary["totals"]["events"] == 3
        assert summary["totals"]["successes"] == 2
        assert summary["totals"]["failures"] == 1
        assert {row["event_type"]: row["events"] for row in summary["by_type"]} == {
            "memory_add": 2,
            "memory_search": 1,
        }
        assert {row["agent_id"]: row["events"] for row in summary["by_agent"]} == {
            "agent-a": 2,
            "agent-b": 1,
        }

    def test_track_logs_success_with_latency_and_mutations(self, logger_instance):
        """track should log success and include data added by the tracker."""
        with logger_instance.track("memory_add", "agent-a", source="core.add") as tracker:
            tracker.set_memory_id("mem-123")
            tracker.update_metadata(memory_type="durable_fact")

        events = logger_instance.get_events()
        assert len(events) == 1
        assert events[0]["status"] == "success"
        assert events[0]["memory_id"] == "mem-123"
        assert events[0]["latency_ms"] >= 0
        assert events[0]["metadata"] == {"memory_type": "durable_fact"}

    def test_track_logs_failure_and_reraises(self, logger_instance):
        """track should log failures without swallowing the original exception."""
        with pytest.raises(ValueError):
            with logger_instance.track("memory_add", "agent-a"):
                raise ValueError("write failed")

        events = logger_instance.get_events()
        assert len(events) == 1
        assert events[0]["status"] == "failure"
        assert events[0]["error"] == "write failed"

    def test_agent_filter_in_summary(self, logger_instance):
        """Summary filters should return only matching agent events."""
        logger_instance.log(_make_event(agent_id="agent-a"))
        logger_instance.log(_make_event(agent_id="agent-b"))
        logger_instance.log(_make_event(agent_id="agent-a"))

        summary = logger_instance.get_summary(agent_id="agent-a")

        assert summary["totals"]["events"] == 2
        assert summary["by_agent"] == [{"agent_id": "agent-a", "events": 2}]

    def test_failure_resilience(self, logger_instance):
        """SQLite write failures should not raise an exception."""
        logger_instance.db_path = "/nonexistent/path/db.sqlite"

        logger_instance.log(_make_event())

    def test_schema_created(self, logger_instance):
        """Initialization should create the expected table and indexes."""
        conn = sqlite3.connect(str(logger_instance.db_path))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
        conn.close()

        assert ("memory_events",) in tables
        assert ("idx_memory_events_agent",) in indexes
        assert ("idx_memory_events_type",) in indexes
        assert ("idx_memory_events_memory",) in indexes
