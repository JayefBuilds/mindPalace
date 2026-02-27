"""Tests for the core EnhancedMemory orchestrator."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from mem0_enhanced.config import EnhancedMemoryConfig
from mem0_enhanced.core import EnhancedMemory
from mem0_enhanced.types import ScoredMemory


def _make_config(**overrides) -> EnhancedMemoryConfig:
    """Create a test config with sensible defaults and all features disabled unless overridden."""
    defaults = dict(
        ollama_url="http://localhost:11434",
        qdrant_url="http://localhost:6333",
        neo4j_url="bolt://localhost:7687",
        neo4j_password="test",
        enable_graph=False,
        enable_reranker=False,
        enable_rewriter=False,
        enable_decay=False,
    )
    defaults.update(overrides)
    return EnhancedMemoryConfig(**defaults)


@pytest.fixture
def mock_mem0():
    """Return a mocked Mem0 Memory instance."""
    mock = MagicMock()
    mock.add.return_value = {"results": [{"id": "test-id", "memory": "test"}]}
    mock.search.return_value = {"results": []}
    mock.get_all.return_value = {"results": []}
    return mock


@pytest.fixture
def enhanced_memory(mock_mem0):
    """Create EnhancedMemory with mocked Mem0 backend."""
    config = _make_config()
    with patch("mem0_enhanced.core.Memory") as MockMemory:
        MockMemory.from_config.return_value = mock_mem0
        em = EnhancedMemory(config=config)
    return em


class TestAdd:
    def test_add_with_explicit_type(self, enhanced_memory, mock_mem0):
        """add() with explicit type should not auto-classify."""
        enhanced_memory.add("Test memory", agent_id="test", memory_type="preference")

        mock_mem0.add.assert_called_once()
        call_kwargs = mock_mem0.add.call_args
        metadata = call_kwargs[1]["metadata"]
        assert metadata["memory_type"] == "preference"
        assert metadata["status"] == "active"
        assert metadata["access_count"] == 0

    def test_add_without_type_auto_classifies(self, enhanced_memory, mock_mem0):
        """add() without type should auto-classify."""
        with patch.object(enhanced_memory.auto_typer, "classify", return_value="durable_fact"):
            enhanced_memory.add("User is a developer", agent_id="test")

        call_kwargs = mock_mem0.add.call_args
        metadata = call_kwargs[1]["metadata"]
        assert metadata["memory_type"] == "durable_fact"


class TestSearch:
    def test_search_returns_scored_memories(self, enhanced_memory, mock_mem0):
        """search() should return ScoredMemory objects."""
        mock_mem0.search.return_value = {
            "results": [{
                "id": "1",
                "memory": "Test fact",
                "score": 0.9,
                "metadata": {
                    "memory_type": "durable_fact",
                    "access_count": 0,
                    "status": "active",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            }]
        }

        results = enhanced_memory.search("test", agent_id="test")

        assert len(results) == 1
        assert isinstance(results[0], ScoredMemory)
        assert results[0].text == "Test fact"
        assert results[0].memory_type == "durable_fact"

    def test_search_filters_inactive(self, enhanced_memory, mock_mem0):
        """search() should filter out inactive memories."""
        mock_mem0.search.return_value = {
            "results": [
                {
                    "id": "1",
                    "memory": "Active",
                    "score": 0.9,
                    "metadata": {"status": "active", "created_at": datetime.now(timezone.utc).isoformat()},
                },
                {
                    "id": "2",
                    "memory": "Inactive",
                    "score": 0.8,
                    "metadata": {"status": "inactive", "created_at": datetime.now(timezone.utc).isoformat()},
                },
            ]
        }

        results = enhanced_memory.search("test", agent_id="test")

        assert len(results) == 1
        assert results[0].text == "Active"

    def test_search_empty_results(self, enhanced_memory, mock_mem0):
        """search() should return empty list when no results."""
        mock_mem0.search.return_value = {"results": []}

        results = enhanced_memory.search("test", agent_id="test")

        assert results == []


class TestEndSession:
    def test_end_session_extracts_and_stores(self, enhanced_memory, mock_mem0):
        """end_session() should extract shards and store them."""
        mock_mem0.get_all.return_value = {"results": []}
        mock_shards = [
            {"text": "User prefers dark mode", "type": "preference"},
            {"text": "Using SwiftUI for iOS", "type": "durable_fact"},
        ]
        with patch.object(enhanced_memory.extractor, "extract", return_value=mock_shards):
            results = enhanced_memory.end_session(
                agent_id="test",
                conversation="User: test\nAssistant: test",
            )

        assert len(results) == 2
        assert mock_mem0.add.call_count == 2

    def test_end_session_empty_extraction(self, enhanced_memory, mock_mem0):
        """end_session() with nothing to extract returns empty list."""
        mock_mem0.get_all.return_value = {"results": []}
        with patch.object(enhanced_memory.extractor, "extract", return_value=[]):
            results = enhanced_memory.end_session(
                agent_id="test",
                conversation="User: hi\nAssistant: hello",
            )

        assert results == []
        mock_mem0.add.assert_not_called()


class TestBuildContext:
    def test_build_context_formats_memories(self, enhanced_memory, mock_mem0):
        """build_context() should return formatted memory string."""
        mock_mem0.search.return_value = {
            "results": [{
                "id": "1",
                "memory": "User prefers dark mode",
                "score": 0.9,
                "metadata": {
                    "memory_type": "preference",
                    "access_count": 5,
                    "status": "active",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            }]
        }

        context = enhanced_memory.build_context(agent_id="test", query="preferences")

        assert "Relevant Memories" in context
        assert "dark mode" in context
        assert "[preference]" in context

    def test_build_context_empty(self, enhanced_memory, mock_mem0):
        """build_context() should return empty string when no memories."""
        mock_mem0.search.return_value = {"results": []}

        context = enhanced_memory.build_context(agent_id="test", query="test")

        assert context == ""


class TestGC:
    def test_run_gc_delegates_to_collector(self, enhanced_memory):
        """run_gc() should delegate to the garbage collector."""
        with patch.object(enhanced_memory.gc, "collect", return_value=[]) as mock_collect:
            enhanced_memory.run_gc(agent_id="test", dry_run=True)

        mock_collect.assert_called_once_with(agent_id="test", dry_run=True)
