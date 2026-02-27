"""
Cross-encoder reranker for memory search results.

Uses a local cross-encoder model (via sentence-transformers) to rerank
memory results by their actual semantic relevance to the query.
"""

import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)


class MemoryReranker:
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.model_name = model_name
        self._model: Optional["CrossEncoder"] = None

    @property
    def model(self) -> "CrossEncoder":
        """Lazy-load the cross-encoder model."""
        if self._model is None:
            from sentence_transformers import CrossEncoder
            logger.info(f"Loading reranker model: {self.model_name}")
            self._model = CrossEncoder(self.model_name)
        return self._model

    def rerank(
        self,
        query: str,
        memories: list[dict],
        top_k: int = 5,
    ) -> list[dict]:
        """
        Rerank memory results using cross-encoder scoring.

        Args:
            query: The original user query (not the rewritten ones)
            memories: List of memory dicts from Mem0 search results.
                      Each must have a "memory" key with the text.
            top_k: Number of results to return after reranking.

        Returns:
            Top-k memories sorted by cross-encoder score, with
            "rerank_score" added to each dict.
        """
        if not memories:
            return []

        pairs = [(query, mem["memory"]) for mem in memories]
        scores = self.model.predict(pairs)

        for mem, score in zip(memories, scores):
            mem["rerank_score"] = float(score)

        ranked = sorted(memories, key=lambda m: m["rerank_score"], reverse=True)
        return ranked[:top_k]
