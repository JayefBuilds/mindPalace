"""Tests for health and re-embedding operations."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mem0_enhanced.config import EnhancedMemoryConfig
from mem0_enhanced.core import EnhancedMemory


def _make_memory() -> EnhancedMemory:
    config = EnhancedMemoryConfig(
        enable_graph=False,
        enable_reranker=False,
        enable_rewriter=False,
        enable_decay=False,
    )
    with patch("mem0_enhanced.core.Memory") as MockMemory:
        MockMemory.from_config.return_value = MagicMock()
        return EnhancedMemory(config=config)


def _point(point_id: str, payload: dict, vector=None):
    return SimpleNamespace(id=point_id, payload=payload, vector=vector)


def test_health_status_counts_lifecycles_and_vectors():
    memory = _make_memory()
    memory.qdrant.scroll = MagicMock(return_value=([
        _point("1", {"memory": "active", "agent_id": "a", "memory_type": "preference", "lifecycle": "active"}, [0.1]),
        _point("2", {"memory": "archived", "agent_id": "a", "memory_type": "decision", "lifecycle": "archived"}, [0.2]),
        _point("3", {"memory": "old", "agent_id": "b", "status": "inactive"}, None),
    ], None))

    with patch("mem0_enhanced.core.httpx.get") as mock_get:
        mock_get.return_value.json.return_value = {"models": [{"name": "nomic-embed-text:latest"}]}
        mock_get.return_value.raise_for_status.return_value = None
        status = memory.health_status()

    assert status["qdrant"]["ok"] is True
    assert status["ollama"]["ok"] is True
    assert status["ollama"]["embedding_model_present"] is True
    assert status["memories"]["active"] == 1
    assert status["memories"]["archived"] == 1
    assert status["memories"]["pruned"] == 1
    assert status["memories"]["legacy_inactive"] == 1
    assert status["memories"]["missing_vector"] == 1
    assert status["memories"]["by_agent"] == {"a": 2, "b": 1}


def test_reembed_dry_run_does_not_update_vectors():
    memory = _make_memory()
    memory.qdrant.scroll = MagicMock(return_value=([
        _point("1", {"memory": "active", "agent_id": "a", "lifecycle": "active"}),
    ], None))
    memory.qdrant.update_vectors = MagicMock()

    result = memory.reembed_memories(agent_id="a", dry_run=True)

    assert result["scanned"] == 1
    assert result["updated"] == 0
    memory.qdrant.update_vectors.assert_not_called()


def test_reembed_execute_updates_vectors():
    memory = _make_memory()
    memory.qdrant.scroll = MagicMock(return_value=([
        _point("1", {"memory": "active", "agent_id": "a", "lifecycle": "active"}),
    ], None))
    memory.qdrant.update_vectors = MagicMock()

    with patch.object(memory, "_embed_text", return_value=[0.1, 0.2]):
        result = memory.reembed_memories(agent_id="a", dry_run=False)

    assert result["scanned"] == 1
    assert result["updated"] == 1
    memory.qdrant.update_vectors.assert_called_once()
