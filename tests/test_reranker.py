"""Tests for the reranker module."""

from unittest.mock import patch, MagicMock, PropertyMock
import numpy as np
import pytest

from mem0_enhanced.reranker import MemoryReranker


@pytest.fixture
def reranker():
    r = MemoryReranker()
    mock_model = MagicMock()
    r._model = mock_model
    return r


def _make_memories(texts: list[str]) -> list[dict]:
    return [{"id": str(i), "memory": t, "score": 0.5} for i, t in enumerate(texts)]


class TestReranker:
    def test_relevance_ordering(self, reranker):
        """Python memory should rank first for 'python debugging' query."""
        memories = _make_memories([
            "User enjoys cooking Italian food",
            "User is debugging a Python async issue with asyncio",
            "User has a garden with tomatoes",
        ])
        reranker._model.predict.return_value = np.array([0.1, 0.9, 0.05])

        results = reranker.rerank("python debugging", memories)

        assert results[0]["memory"] == "User is debugging a Python async issue with asyncio"
        assert results[0]["rerank_score"] == 0.9

    def test_top_k_limit(self, reranker):
        """Should return exactly top_k results."""
        memories = _make_memories([f"Memory {i}" for i in range(10)])
        reranker._model.predict.return_value = np.array([float(i) for i in range(10)])

        results = reranker.rerank("test", memories, top_k=3)

        assert len(results) == 3

    def test_empty_input(self, reranker):
        """Should return empty list for empty input."""
        results = reranker.rerank("test", [])
        assert results == []

    def test_score_attachment(self, reranker):
        """Each returned memory should have a rerank_score float."""
        memories = _make_memories(["test memory"])
        reranker._model.predict.return_value = np.array([0.75])

        results = reranker.rerank("test", memories)

        assert "rerank_score" in results[0]
        assert isinstance(results[0]["rerank_score"], float)
        assert results[0]["rerank_score"] == 0.75

    def test_preserves_metadata(self, reranker):
        """Original metadata should be preserved after reranking."""
        memories = [{"id": "1", "memory": "test", "score": 0.5, "metadata": {"custom": "data"}}]
        reranker._model.predict.return_value = np.array([0.8])

        results = reranker.rerank("test", memories)

        assert results[0]["metadata"]["custom"] == "data"
        assert results[0]["id"] == "1"
