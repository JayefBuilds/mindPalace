"""Shared types used across the package."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ScoredMemory:
    """A memory result with enhanced scoring metadata."""
    id: str
    text: str
    agent_id: str
    created_at: datetime
    original_score: float
    rerank_score: Optional[float]
    decay_score: float
    access_count: int
    memory_type: str
    metadata: dict = field(default_factory=dict)
    relations: list = field(default_factory=list)


@dataclass
class RewrittenQuery:
    """Result of query rewriting."""
    original: str
    expanded: list[str]
    session_context_used: bool
