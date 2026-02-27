"""Tests for the decay scoring and garbage collection modules."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
import pytest

from mem0_enhanced.decay import DecayScorer, GarbageCollector, GC_EXEMPT_TYPES


@pytest.fixture
def scorer():
    return DecayScorer(halflife_days=60)


@pytest.fixture
def now():
    return datetime(2026, 2, 26, 12, 0, 0, tzinfo=timezone.utc)


def _make_memory(
    created_at: datetime,
    access_count: int = 0,
    memory_type: str = "unknown",
    status: str = "active",
    memory_id: str = "test-id",
    text: str = "test memory",
) -> dict:
    return {
        "id": memory_id,
        "memory": text,
        "metadata": {
            "created_at": created_at.isoformat(),
            "access_count": access_count,
            "memory_type": memory_type,
            "status": status,
        },
    }


class TestDecayScorer:
    def test_fresh_memory(self, scorer, now):
        """Created today, access_count=0 → score ≈ base_score."""
        mem = _make_memory(created_at=now, access_count=0)
        result = scorer.score(mem, base_score=1.0, now=now)
        assert result == pytest.approx(1.0, abs=0.05)

    def test_old_memory_no_accesses(self, scorer, now):
        """180 days old, access_count=0 → score significantly reduced."""
        created = now - timedelta(days=180)
        mem = _make_memory(created_at=created, access_count=0)
        result = scorer.score(mem, base_score=1.0, now=now)
        assert result < 0.7

    def test_old_memory_many_accesses(self, scorer, now):
        """180 days old, access_count=50 → score partially preserved."""
        created = now - timedelta(days=180)
        mem_no_access = _make_memory(created_at=created, access_count=0)
        mem_many_access = _make_memory(created_at=created, access_count=50)
        score_none = scorer.score(mem_no_access, base_score=1.0, now=now)
        score_many = scorer.score(mem_many_access, base_score=1.0, now=now)
        assert score_many > score_none

    def test_durable_fact_persistence(self, scorer, now):
        """Type 'durable_fact', 365 days old → score barely reduced."""
        created = now - timedelta(days=365)
        mem = _make_memory(created_at=created, memory_type="durable_fact")
        result = scorer.score(mem, base_score=1.0, now=now)
        assert result > 0.9

    def test_open_loop_decay(self, scorer, now):
        """Type 'open_loop', 90 days old → score heavily reduced."""
        created = now - timedelta(days=90)
        mem_open = _make_memory(created_at=created, memory_type="open_loop")
        mem_durable = _make_memory(created_at=created, memory_type="durable_fact")
        score_open = scorer.score(mem_open, base_score=1.0, now=now)
        score_durable = scorer.score(mem_durable, base_score=1.0, now=now)
        assert score_open < score_durable


class TestGarbageCollector:
    def test_gc_exempt_types(self):
        """durable_fact and preference should never be collected."""
        now = datetime(2026, 2, 26, 12, 0, 0, tzinfo=timezone.utc)
        old = now - timedelta(days=200)

        mock_mem0 = MagicMock()
        mock_mem0.get_all.return_value = {
            "results": [
                _make_memory(created_at=old, memory_type="durable_fact", memory_id="1"),
                _make_memory(created_at=old, memory_type="preference", memory_id="2"),
                _make_memory(created_at=old, memory_type="decision", memory_id="3"),
            ]
        }

        gc = GarbageCollector(mock_mem0, max_age_days=90)
        candidates = gc.collect("test-agent", dry_run=True)

        collected_ids = [c["id"] for c in candidates]
        assert "1" not in collected_ids
        assert "2" not in collected_ids
        assert "3" in collected_ids

    def test_gc_dry_run(self):
        """Dry run should return candidates without modifying anything."""
        now = datetime(2026, 2, 26, 12, 0, 0, tzinfo=timezone.utc)
        old = now - timedelta(days=200)

        mock_mem0 = MagicMock()
        mock_mem0.get_all.return_value = {
            "results": [
                _make_memory(created_at=old, memory_type="decision", memory_id="1"),
            ]
        }

        gc = GarbageCollector(mock_mem0, max_age_days=90)
        candidates = gc.collect("test-agent", dry_run=True)

        assert len(candidates) == 1
        mock_mem0.update.assert_not_called()

    def test_gc_execute(self):
        """Non-dry-run should call set_payload with inactive status."""
        now = datetime(2026, 2, 26, 12, 0, 0, tzinfo=timezone.utc)
        old = now - timedelta(days=200)

        mock_qdrant = MagicMock()
        mock_mem0 = MagicMock()
        mock_mem0.get_all.return_value = {
            "results": [
                _make_memory(created_at=old, memory_type="open_loop", memory_id="1"),
            ]
        }

        gc = GarbageCollector(mock_qdrant, max_age_days=90, mem0_instance=mock_mem0)
        candidates = gc.collect("test-agent", dry_run=False)

        assert len(candidates) == 1
        mock_qdrant.set_payload.assert_called_once()
        call_args = mock_qdrant.set_payload.call_args
        assert call_args[1]["payload"]["status"] == "inactive"

    def test_skips_already_inactive(self):
        """Already inactive memories should be skipped."""
        now = datetime(2026, 2, 26, 12, 0, 0, tzinfo=timezone.utc)
        old = now - timedelta(days=200)

        mock_mem0 = MagicMock()
        mock_mem0.get_all.return_value = {
            "results": [
                _make_memory(created_at=old, memory_type="decision", status="inactive", memory_id="1"),
            ]
        }

        gc = GarbageCollector(mock_mem0, max_age_days=90)
        candidates = gc.collect("test-agent", dry_run=True)

        assert len(candidates) == 0
