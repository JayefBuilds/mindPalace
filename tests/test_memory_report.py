"""Tests for the static memory report renderer."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import memory_report  # noqa: E402


def test_render_memory_rows_include_filter_data_attributes():
    rows = memory_report.render_table_rows([
        {
            "id": "mem-1",
            "memory": "User prefers concise summaries",
            "metadata": {
                "agent_id": "boop-agent",
                "memory_type": "preference",
                "lifecycle": "active",
                "source": "hook",
                "access_count": 3,
            },
        }
    ])

    assert 'data-agent="boop-agent"' in rows
    assert 'data-lifecycle="active"' in rows
    assert 'data-type="preference"' in rows
    assert 'data-module="hook"' in rows
    assert "User prefers concise summaries" in rows


def test_render_event_rows_include_source_filter_data_attribute():
    rows = memory_report.render_events([
        {
            "timestamp": "2026-05-18T12:00:00Z",
            "agent_id": "boop-agent",
            "event_type": "memory_context_built",
            "source": "core.build_context",
            "status": "success",
            "metadata": {"memory_count": 2},
        }
    ])

    assert 'data-agent="boop-agent"' in rows
    assert 'data-event-type="memory_context_built"' in rows
    assert 'data-source="core.build_context"' in rows
    assert 'data-status="success"' in rows
    assert "memory_count" in rows
