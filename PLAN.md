# Enhanced Mem0 Memory System — Implementation Plan

## Agent Instructions

You are building an enhanced memory orchestration layer on top of a self-hosted Mem0 stack. The system adds six capabilities that Mem0 lacks out of the box: **query rewriting**, **reranking**, **automatic forgetfulness/decay**, **automatic session extraction**, **automatic memory typing**, and **scheduled garbage collection**. The result is a Python package called `mem0_enhanced` that wraps Mem0's API and exposes an MCP server for use by AI agents.

**Do not modify Mem0's source code.** Everything is a wrapper/orchestration layer on top of `mem0ai`'s public API.

---

## 1. System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    MCP Server (FastMCP)                  │
│         Exposes tools to Claude Code / agents            │
├─────────────────────────────────────────────────────────┤
│                  EnhancedMemory Class                    │
│  ┌───────────┐ ┌──────────┐ ┌───────────────────────┐  │
│  │  Query     │ │ Reranker │ │ Decay / Forget        │  │
│  │  Rewriter  │ │          │ │ Scoring + GC          │  │
│  └─────┬─────┘ └────┬─────┘ └────────┬──────────────┘  │
│  ┌───────────┐ ┌──────────┐                             │
│  │ Session   │ │ Auto     │  ← NEW: extracts memories   │
│  │ Extractor │ │ Typer    │    automatically             │
│  └─────┬─────┘ └────┬─────┘                             │
│        │             │                                   │
├────────┴─────────────┴──────────────────────────────────┤
│                  Mem0 Memory Class                        │
│         (unmodified mem0ai Python SDK)                    │
├──────────────────────────────────────────────────────────┤
│  Qdrant (vectors)  │  Neo4j (graph)  │  Ollama (LLM +   │
│  :6333             │  :7687          │  embeddings)      │
│                    │                 │  :11434           │
└────────────────────┴─────────────────┴───────────────────┘
```

---

## 2. Infrastructure Setup

### 2.1 Docker Compose

Create `docker-compose.yml` in the project root. This brings up all backing services.

```yaml
version: "3.8"

services:
  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "127.0.0.1:6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage
    restart: unless-stopped

  neo4j:
    image: neo4j:5
    ports:
      - "127.0.0.1:7474:7474"
      - "127.0.0.1:7687:7687"
    environment:
      NEO4J_AUTH: neo4j/mem0graph
      NEO4J_PLUGINS: '["apoc"]'
    volumes:
      - neo4j_data:/data
    restart: unless-stopped

  ollama:
    image: ollama/ollama:latest
    ports:
      - "127.0.0.1:11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    restart: unless-stopped
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]

volumes:
  qdrant_data:
  neo4j_data:
  ollama_data:
```

### 2.2 Ollama Model Setup

After `docker compose up -d`, pull the required models:

```bash
# Embedding model
docker exec ollama ollama pull nomic-embed-text

# Cheap/fast LLM for query rewriting and graph extraction
docker exec ollama ollama pull phi3:mini

# Alternative: if the machine has more RAM, use a better model
# docker exec ollama ollama pull llama3.1:8b
```

---

## 3. Project Structure

```
mem0_enhanced/
├── docker-compose.yml
├── pyproject.toml
├── README.md
├── src/
│   └── mem0_enhanced/
│       ├── __init__.py
│       ├── config.py              # Configuration + Mem0 config builder
│       ├── core.py                # EnhancedMemory main class
│       ├── query_rewriter.py      # Query expansion/rewriting
│       ├── reranker.py            # Cross-encoder reranking
│       ├── decay.py               # Decay scoring + garbage collection
│       ├── session_extractor.py   # End-of-session memory extraction
│       ├── auto_typer.py          # Automatic memory type classification
│       ├── token_logger.py        # Token consumption tracking + reporting
│       ├── types.py               # Shared types and dataclasses
│       └── mcp_server.py          # FastMCP server exposing tools
├── scripts/
│   ├── setup.sh                   # One-command setup (docker + models)
│   ├── gc.py                      # Standalone GC runner (for cron)
│   ├── token_report.py            # Generate token usage reports
│   └── migrate.py                 # Future: import from other systems
├── cron/
│   └── mem0-gc.cron               # Crontab entry for scheduled GC
└── tests/
    ├── test_query_rewriter.py
    ├── test_reranker.py
    ├── test_decay.py
    ├── test_session_extractor.py
    ├── test_auto_typer.py
    ├── test_token_logger.py
    └── test_core.py
```

---

## 4. Configuration (`config.py`)

This module defines all configuration and builds the Mem0 config dict.

```python
"""
Configuration for EnhancedMemory.

Environment variables:
  MEM0_AGENT_ID              - Default agent/project ID (no default — set per project)
  MEM0_OLLAMA_URL          - Ollama base URL (default: http://localhost:11434)
  MEM0_QDRANT_URL          - Qdrant URL (default: http://localhost:6333)
  MEM0_NEO4J_URL           - Neo4j bolt URL (default: bolt://localhost:7687)
  MEM0_NEO4J_PASSWORD      - Neo4j password (default: mem0graph)
  MEM0_REWRITER_MODEL      - Ollama model for query rewriting (default: phi3:mini)
  MEM0_EXTRACTION_MODEL    - Ollama model for memory extraction (default: phi3:mini)
  MEM0_EMBEDDING_MODEL     - Ollama embedding model (default: nomic-embed-text)
  MEM0_RERANKER_MODEL      - Cross-encoder model name (default: cross-encoder/ms-marco-MiniLM-L-6-v2)
  MEM0_ENABLE_GRAPH        - Enable graph memory (default: true)
  MEM0_ENABLE_RERANKER     - Enable reranking (default: true)
  MEM0_ENABLE_REWRITER     - Enable query rewriting (default: true)
  MEM0_ENABLE_DECAY        - Enable decay scoring (default: true)
  MEM0_SEARCH_LIMIT        - Max memories per search before reranking (default: 20)
  MEM0_FINAL_LIMIT         - Max memories returned after reranking (default: 5)
  MEM0_DECAY_HALFLIFE_DAYS - Half-life for decay in days (default: 60)
"""

from dataclasses import dataclass, field
from typing import Optional
import os


@dataclass
class EnhancedMemoryConfig:
    # Project identity
    default_agent_id: Optional[str] = None  # Set via MEM0_AGENT_ID per project

    # Infrastructure
    ollama_url: str = "http://localhost:11434"
    qdrant_url: str = "http://localhost:6333"
    neo4j_url: str = "bolt://localhost:7687"
    neo4j_password: str = "mem0graph"

    # Models
    rewriter_model: str = "phi3:mini"
    extraction_model: str = "phi3:mini"
    embedding_model: str = "nomic-embed-text"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # Feature flags
    enable_graph: bool = True
    enable_reranker: bool = True
    enable_rewriter: bool = True
    enable_decay: bool = True

    # Search tuning
    search_limit: int = 20       # Fetch this many from Mem0
    final_limit: int = 5         # Return this many to caller
    decay_halflife_days: int = 60

    @classmethod
    def from_env(cls) -> "EnhancedMemoryConfig":
        """Build config from environment variables."""
        return cls(
            default_agent_id=os.getenv("MEM0_AGENT_ID"),
            ollama_url=os.getenv("MEM0_OLLAMA_URL", cls.ollama_url),
            qdrant_url=os.getenv("MEM0_QDRANT_URL", cls.qdrant_url),
            neo4j_url=os.getenv("MEM0_NEO4J_URL", cls.neo4j_url),
            neo4j_password=os.getenv("MEM0_NEO4J_PASSWORD", cls.neo4j_password),
            rewriter_model=os.getenv("MEM0_REWRITER_MODEL", cls.rewriter_model),
            extraction_model=os.getenv("MEM0_EXTRACTION_MODEL", cls.extraction_model),
            embedding_model=os.getenv("MEM0_EMBEDDING_MODEL", cls.embedding_model),
            reranker_model=os.getenv("MEM0_RERANKER_MODEL", cls.reranker_model),
            enable_graph=os.getenv("MEM0_ENABLE_GRAPH", "true").lower() == "true",
            enable_reranker=os.getenv("MEM0_ENABLE_RERANKER", "true").lower() == "true",
            enable_rewriter=os.getenv("MEM0_ENABLE_REWRITER", "true").lower() == "true",
            enable_decay=os.getenv("MEM0_ENABLE_DECAY", "true").lower() == "true",
            search_limit=int(os.getenv("MEM0_SEARCH_LIMIT", "20")),
            final_limit=int(os.getenv("MEM0_FINAL_LIMIT", "5")),
            decay_halflife_days=int(os.getenv("MEM0_DECAY_HALFLIFE_DAYS", "60")),
        )

    def to_mem0_config(self) -> dict:
        """Build the config dict that Mem0's Memory.from_config() expects."""
        config = {
            "llm": {
                "provider": "ollama",
                "config": {
                    "model": self.extraction_model,
                    "ollama_base_url": self.ollama_url,
                },
            },
            "embedder": {
                "provider": "ollama",
                "config": {
                    "model": self.embedding_model,
                    "ollama_base_url": self.ollama_url,
                },
            },
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "url": self.qdrant_url,
                    "embedding_model_dims": 768,  # nomic-embed-text dimension
                },
            },
        }

        if self.enable_graph:
            config["graph_store"] = {
                "provider": "neo4j",
                "config": {
                    "url": self.neo4j_url,
                    "username": "neo4j",
                    "password": self.neo4j_password,
                },
            }

        return config
```

---

## 5. Shared Types (`types.py`)

```python
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
    original_score: float          # Raw similarity from Mem0/Qdrant
    rerank_score: Optional[float]  # Cross-encoder score (None if reranker disabled)
    decay_score: float             # Final score after decay applied
    access_count: int
    memory_type: str               # preference, durable_fact, decision, open_loop, correction
    metadata: dict = field(default_factory=dict)
    relations: list = field(default_factory=list)  # Graph relations if available


@dataclass
class RewrittenQuery:
    """Result of query rewriting."""
    original: str
    expanded: list[str]            # 2-3 rewritten queries
    session_context_used: bool
```

---

## 6. Query Rewriter (`query_rewriter.py`)

### Purpose
Turn a single user query into 2-3 expanded search queries to improve recall. Handles vague references like "that auth thing" by expanding with context.

### Implementation Spec

```python
"""
Query rewriter that expands user queries for better memory retrieval.

Uses a local Ollama model to generate 2-3 search-optimized queries
from a single (possibly vague) user message.

Design decisions:
- Always returns the original query as one of the search queries
- Caps at 3 expanded queries to control latency
- Falls back to [original_query] if LLM call fails
- Uses session context (last few messages) if available to resolve pronouns/references
"""

import json
import logging
from typing import Optional

import httpx

from .types import RewrittenQuery

logger = logging.getLogger(__name__)

REWRITE_PROMPT = """You are a search query optimizer. Given a user message and optional conversation context, generate 2-3 search queries that would find relevant memories in a personal knowledge store.

Rules:
- Each query should be 3-8 words
- Focus on concrete nouns, names, technologies, decisions
- Expand vague references ("that thing", "it", "the project") into specific terms using context
- Include at least one query that captures the main topic
- Return ONLY a JSON array of strings, nothing else

Context (recent messages):
{context}

User message: {query}

JSON array of search queries:"""


class QueryRewriter:
    def __init__(self, ollama_url: str, model: str):
        self.ollama_url = ollama_url
        self.model = model
        self.client = httpx.Client(timeout=10.0)

    def rewrite(
        self, query: str, session_context: Optional[str] = None
    ) -> RewrittenQuery:
        """
        Expand a query into multiple search queries.

        Args:
            query: The user's raw message/query
            session_context: Optional string of recent conversation for context

        Returns:
            RewrittenQuery with original + expanded queries

        On any failure, returns just the original query (never blocks).
        """
        try:
            prompt = REWRITE_PROMPT.format(
                context=session_context or "(no context)",
                query=query,
            )

            response = self.client.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 150},
                },
            )
            response.raise_for_status()

            raw = response.json()["response"].strip()
            # Parse JSON array from response, handling markdown fences
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            queries = json.loads(raw)
            if not isinstance(queries, list) or len(queries) == 0:
                raise ValueError("Invalid response format")

            # Always include original, cap at 3 expanded
            expanded = [query] + [q for q in queries[:3] if q != query]
            return RewrittenQuery(
                original=query,
                expanded=expanded,
                session_context_used=session_context is not None,
            )

        except Exception as e:
            logger.warning(f"Query rewrite failed, using original: {e}")
            return RewrittenQuery(
                original=query,
                expanded=[query],
                session_context_used=False,
            )

    def close(self):
        self.client.close()
```

### Test Cases (`test_query_rewriter.py`)

Test the following scenarios:
1. **Vague query with context**: Input "what did we decide about that?" with context mentioning authentication → should produce queries containing "authentication" or "auth"
2. **Already specific query**: Input "StoreKit 2 implementation" → should return near-identical queries
3. **LLM failure**: Mock Ollama returning error → should gracefully return `[original_query]`
4. **Malformed LLM response**: Mock Ollama returning non-JSON → should gracefully return `[original_query]`
5. **Empty context**: Should still produce reasonable expansions

---

## 7. Reranker (`reranker.py`)

### Purpose
Take the combined results from multiple Mem0 searches and rerank them using a cross-encoder model for higher precision.

### Implementation Spec

```python
"""
Cross-encoder reranker for memory search results.

Uses a local cross-encoder model (via sentence-transformers) to rerank
memory results by their actual semantic relevance to the query.

Vector similarity (from Qdrant) is fast but approximate. A cross-encoder
sees both query and document together and produces a more accurate
relevance score, at the cost of being slower (hence we only rerank top-K).

Design decisions:
- Model loaded lazily on first use
- Model runs on CPU by default (fast enough for <50 items)
- Returns items sorted by cross-encoder score descending
- Preserves all original metadata
"""

import logging
from typing import Optional

from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)


class MemoryReranker:
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.model_name = model_name
        self._model: Optional[CrossEncoder] = None

    @property
    def model(self) -> CrossEncoder:
        """Lazy-load the cross-encoder model."""
        if self._model is None:
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

        # Build query-document pairs
        pairs = [(query, mem["memory"]) for mem in memories]

        # Score all pairs
        scores = self.model.predict(pairs)

        # Attach scores and sort
        for mem, score in zip(memories, scores):
            mem["rerank_score"] = float(score)

        ranked = sorted(memories, key=lambda m: m["rerank_score"], reverse=True)
        return ranked[:top_k]
```

### Dependencies
Add to `pyproject.toml`:
```toml
dependencies = [
    "sentence-transformers>=3.0",
]
```

The cross-encoder model (`ms-marco-MiniLM-L-6-v2`) is ~80MB, downloads automatically on first use, and runs on CPU in <50ms for 20 items.

### Test Cases (`test_reranker.py`)

1. **Relevance ordering**: Given a query "python debugging" and memories about Python, cooking, and gardening → Python memory should rank first
2. **Top-k limit**: Given 10 memories and top_k=3 → should return exactly 3
3. **Empty input**: Should return empty list
4. **Score attachment**: Each returned memory should have a `rerank_score` float

---

## 8. Decay Scoring (`decay.py`)

### Purpose
Implement time-based decay and importance scoring so that old, unused memories naturally fade, while frequently accessed and important memories persist.

### Implementation Spec

```python
"""
Decay scoring and garbage collection for memories.

Two components:
1. Decay scorer: Adjusts retrieval scores based on recency, access count, and memory type
2. Garbage collector: Periodically marks stale memories inactive

Design decisions:
- Decay is applied AFTER reranking (it modifies final scores, not retrieval)
- Uses exponential decay with configurable half-life
- Memory types have different base persistence weights
- Access count provides reinforcement (frequently useful memories persist)
- GC runs as a separate scheduled process, not inline with queries
- GC never deletes — it marks memories with metadata {"status": "inactive"}
- Durable facts and preferences are NEVER garbage collected
"""

import math
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# How resistant each memory type is to decay (0.0 = decays fast, 1.0 = never decays)
TYPE_PERSISTENCE = {
    "durable_fact": 0.95,
    "preference": 0.90,
    "decision": 0.70,
    "correction": 0.65,
    "open_loop": 0.50,
    "unknown": 0.50,
}

# Types that are never garbage collected
GC_EXEMPT_TYPES = {"durable_fact", "preference"}


class DecayScorer:
    def __init__(self, halflife_days: int = 60):
        # Convert half-life to decay constant: score = e^(-λt)
        # At t = halflife_days, score = 0.5
        # 0.5 = e^(-λ * halflife) → λ = ln(2) / halflife
        self.decay_lambda = math.log(2) / halflife_days

    def score(
        self,
        memory: dict,
        base_score: float,
        now: Optional[datetime] = None,
    ) -> float:
        """
        Apply decay to a memory's relevance score.

        Args:
            memory: Memory dict from Mem0. Expected metadata keys:
                    - created_at or timestamp (ISO string or datetime)
                    - access_count (int, default 0)
                    - memory_type (str, default "unknown")
            base_score: The score to decay (from reranker or vector similarity)
            now: Current time (injectable for testing)

        Returns:
            Adjusted score incorporating recency, access reinforcement,
            and type persistence.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        # Parse timestamp
        created = memory.get("metadata", {}).get("created_at")
        if created is None:
            created = memory.get("created_at", now.isoformat())
        if isinstance(created, str):
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)

        age_days = max((now - created).total_seconds() / 86400, 0)

        # Components
        recency = math.exp(-self.decay_lambda * age_days)

        access_count = memory.get("metadata", {}).get("access_count", 0)
        reinforcement = math.log1p(access_count) * 0.15  # Diminishing returns

        memory_type = memory.get("metadata", {}).get("memory_type", "unknown")
        persistence = TYPE_PERSISTENCE.get(memory_type, 0.5)

        # Final score: base relevance * weighted combination
        # persistence acts as a floor — durable_facts barely decay
        adjusted = base_score * (
            persistence + (1 - persistence) * recency + reinforcement
        )

        return round(adjusted, 4)


class GarbageCollector:
    """
    Marks old, unused memories as inactive.

    Run this periodically (e.g., weekly cron or on session end).
    Does NOT delete — marks with metadata for audit trail.
    """

    def __init__(
        self,
        mem0_instance,
        max_age_days: int = 90,
        min_access_count: int = 0,
    ):
        self.mem0 = mem0_instance
        self.max_age_days = max_age_days
        self.min_access_count = min_access_count

    def collect(self, agent_id: str, dry_run: bool = False) -> list[dict]:
        """
        Find and mark stale memories for a given agent.

        Args:
            agent_id: The agent/project whose memories to scan
            dry_run: If True, return candidates without marking them

        Returns:
            List of memories that were (or would be) marked inactive.
        """
        now = datetime.now(timezone.utc)
        all_memories = self.mem0.get_all(agent_id=agent_id)
        candidates = []

        for mem in all_memories.get("results", []):
            metadata = mem.get("metadata", {})

            # Skip already inactive
            if metadata.get("status") == "inactive":
                continue

            # Skip exempt types
            memory_type = metadata.get("memory_type", "unknown")
            if memory_type in GC_EXEMPT_TYPES:
                continue

            # Check age
            created = metadata.get("created_at")
            if created is None:
                continue
            if isinstance(created, str):
                created = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)

            age_days = (now - created).total_seconds() / 86400

            # Check access count
            access_count = metadata.get("access_count", 0)

            if age_days > self.max_age_days and access_count <= self.min_access_count:
                candidates.append(mem)

                if not dry_run:
                    self.mem0.update(
                        mem["id"],
                        metadata={
                            **metadata,
                            "status": "inactive",
                            "gc_timestamp": now.isoformat(),
                        },
                    )
                    logger.info(
                        f"GC: Marked memory {mem['id']} inactive "
                        f"(age={age_days:.0f}d, accesses={access_count})"
                    )

        logger.info(
            f"GC complete for agent {agent_id}: "
            f"{len(candidates)} memories {'would be' if dry_run else ''} marked inactive"
        )
        return candidates
```

### Test Cases (`test_decay.py`)

1. **Fresh memory**: Created today, access_count=0 → score ≈ base_score
2. **Old memory, no accesses**: 180 days old, access_count=0 → score significantly reduced
3. **Old memory, many accesses**: 180 days old, access_count=50 → score partially preserved
4. **Durable fact persistence**: Type "durable_fact", 365 days old → score barely reduced
5. **Open loop decay**: Type "open_loop", 90 days old → score heavily reduced
6. **GC exempt types**: durable_fact and preference should never be collected
7. **GC dry run**: Should return candidates but not modify anything

---

## 9. Session Extractor (`session_extractor.py`)

### Purpose
Automatically extract durable memory shards from a conversation when a session ends. This is the critical piece that makes memory truly automatic — the agent doesn't have to decide what to remember.

### Implementation Spec

```python
"""
Session Extractor: Distills conversations into typed memory shards.

Called at end of session (explicit signal, timeout, or MCP tool call).
Takes a conversation transcript and produces a list of compact memory
shards, each typed and ready for storage.

Design decisions:
- Uses Ollama local LLM for extraction (same model as Mem0 extraction)
- Produces 1-3 sentence shards, not summaries
- Each shard is independently meaningful (no "as discussed" references)
- Deduplicates against existing memories before storing
- Session detection: caller decides when session ends (timeout, explicit, hook)
- Extraction prompt is the most important prompt in the system — tune carefully
"""

import json
import logging
from typing import Optional
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are a memory extraction system. Analyze this conversation and extract discrete, durable facts worth remembering for future sessions.

Rules:
- Extract 0-10 memory shards (only what's genuinely worth remembering)
- Each shard: 1-3 sentences, self-contained, no references to "this conversation"
- Classify each shard with a type:
  - preference: User likes/dislikes, style preferences, tool choices
  - durable_fact: Stable facts about the user, their projects, environment
  - decision: A choice that was made and should be remembered
  - open_loop: Something unfinished, to revisit later
  - correction: Something previously wrong that was corrected
- Skip: greetings, small talk, transient questions, things already obvious
- Be concrete: "User chose PostgreSQL over MongoDB for the auth service" not "User discussed databases"
- If nothing worth remembering, return an empty array

Return ONLY a JSON array of objects with "text" and "type" fields. No other output.

Example output:
[
  {"text": "User is building a speech-to-text iOS app using SwiftUI and AVFoundation.", "type": "durable_fact"},
  {"text": "User prefers short, direct responses without excessive caveats.", "type": "preference"},
  {"text": "Decided to use StoreKit 2 for in-app purchases instead of RevenueCat.", "type": "decision"},
  {"text": "Still needs to implement the onboarding flow — blocked on final copy.", "type": "open_loop"}
]

Conversation:
{conversation}

JSON array of memory shards:"""


class SessionExtractor:
    def __init__(self, ollama_url: str, model: str):
        self.ollama_url = ollama_url
        self.model = model
        self.client = httpx.Client(timeout=30.0)  # Extraction can take a moment

    def extract(
        self,
        conversation: str,
        existing_memories: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        Extract memory shards from a conversation transcript.

        Args:
            conversation: The full conversation text (or last N exchanges).
                          Format: "User: ...\nAssistant: ...\n" etc.
            existing_memories: Optional list of existing memory texts for
                               this agent, used to avoid duplicates.

        Returns:
            List of dicts with "text" and "type" keys.
            Returns empty list on any failure (never blocks).
        """
        try:
            prompt = EXTRACTION_PROMPT.format(conversation=conversation)

            # If we have existing memories, add dedup context
            if existing_memories:
                dedup_block = "\n".join(f"- {m}" for m in existing_memories[:20])
                prompt += f"\n\nAlready stored (do NOT extract duplicates of these):\n{dedup_block}"

            response = self.client.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": 1000},
                },
            )
            response.raise_for_status()

            raw = response.json()["response"].strip()

            # Parse JSON, handling markdown fences
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            shards = json.loads(raw)

            if not isinstance(shards, list):
                raise ValueError("Expected JSON array")

            # Validate each shard
            valid = []
            for shard in shards:
                if (
                    isinstance(shard, dict)
                    and "text" in shard
                    and "type" in shard
                    and shard["type"] in {
                        "preference", "durable_fact", "decision",
                        "open_loop", "correction",
                    }
                ):
                    valid.append(shard)
                else:
                    logger.warning(f"Skipping invalid shard: {shard}")

            logger.info(f"Extracted {len(valid)} memory shards from session")
            return valid

        except Exception as e:
            logger.warning(f"Session extraction failed: {e}")
            return []

    def close(self):
        self.client.close()
```

### Test Cases (`test_session_extractor.py`)

1. **Normal conversation**: Provide a 10-exchange conversation about a coding project → should extract 2-5 typed shards
2. **Empty/trivial conversation**: "Hi" / "Hello, how can I help?" → should return empty list
3. **Deduplication**: Provide existing memories that overlap with conversation content → extracted shards should not duplicate them
4. **All types represented**: Craft a conversation that should produce at least one of each type → verify correct classification
5. **LLM failure**: Mock Ollama error → should return empty list gracefully
6. **Malformed response**: Mock Ollama returning non-JSON → should return empty list

---

## 10. Auto Typer (`auto_typer.py`)

### Purpose
When memories are added without an explicit type (e.g., via Mem0's built-in extraction or manual `add()` with no type), classify them automatically so that decay scoring works properly.

### Implementation Spec

```python
"""
Auto Typer: Classifies memory text into typed categories.

Used in two places:
1. In EnhancedMemory.add() when memory_type is not explicitly set
2. As a batch migration tool for untyped existing memories

Design decisions:
- Single LLM call per memory (cheap, ~10 tokens output)
- Falls back to "durable_fact" on any failure (safe default)
- Can batch-classify for efficiency during migration
- Classification prompt is intentionally simple — complex logic
  belongs in the extraction step, not here
"""

import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

CLASSIFY_PROMPT = """Classify this memory into exactly one type:
- preference: User likes/dislikes, style choices, tool preferences
- durable_fact: Stable facts about the user, projects, environment
- decision: A choice or conclusion that was reached
- open_loop: Something unfinished or to revisit
- correction: A fix to something previously wrong

Memory: "{text}"

Respond with ONLY the type name, nothing else."""

BATCH_CLASSIFY_PROMPT = """Classify each memory into exactly one type:
- preference: User likes/dislikes, style choices, tool preferences
- durable_fact: Stable facts about the user, projects, environment
- decision: A choice or conclusion that was reached
- open_loop: Something unfinished or to revisit
- correction: A fix to something previously wrong

Memories:
{memories}

Respond with ONLY a JSON array of type names in the same order. Nothing else.
Example: ["durable_fact", "preference", "decision"]"""

VALID_TYPES = {"preference", "durable_fact", "decision", "open_loop", "correction"}


class AutoTyper:
    def __init__(self, ollama_url: str, model: str):
        self.ollama_url = ollama_url
        self.model = model
        self.client = httpx.Client(timeout=10.0)

    def classify(self, text: str) -> str:
        """
        Classify a single memory text into a type.

        Args:
            text: The memory content to classify

        Returns:
            One of: preference, durable_fact, decision, open_loop, correction.
            Defaults to "durable_fact" on any failure.
        """
        try:
            prompt = CLASSIFY_PROMPT.format(text=text)

            response = self.client.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.0, "num_predict": 20},
                },
            )
            response.raise_for_status()

            result = response.json()["response"].strip().lower()

            # Extract the type from response (LLM might add extra words)
            for valid_type in VALID_TYPES:
                if valid_type in result:
                    return valid_type

            logger.warning(f"Unrecognized type '{result}', defaulting to durable_fact")
            return "durable_fact"

        except Exception as e:
            logger.warning(f"Auto-typing failed, defaulting to durable_fact: {e}")
            return "durable_fact"

    def classify_batch(self, texts: list[str]) -> list[str]:
        """
        Classify multiple memories in a single LLM call.
        More efficient for migrating existing untyped memories.

        Args:
            texts: List of memory texts to classify

        Returns:
            List of type strings, same length as input.
            Unclassifiable items default to "durable_fact".
        """
        if not texts:
            return []

        # For small batches, just classify individually
        if len(texts) <= 3:
            return [self.classify(t) for t in texts]

        try:
            numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
            prompt = BATCH_CLASSIFY_PROMPT.format(memories=numbered)

            response = self.client.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.0, "num_predict": 200},
                },
            )
            response.raise_for_status()

            raw = response.json()["response"].strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            types = json.loads(raw)

            if not isinstance(types, list) or len(types) != len(texts):
                raise ValueError(f"Expected {len(texts)} types, got {len(types) if isinstance(types, list) else 'non-list'}")

            # Validate each type
            return [
                t if t in VALID_TYPES else "durable_fact"
                for t in types
            ]

        except Exception as e:
            logger.warning(f"Batch classification failed, falling back to individual: {e}")
            return [self.classify(t) for t in texts]

    def close(self):
        self.client.close()
```

### Test Cases (`test_auto_typer.py`)

1. **Clear preference**: "User prefers dark mode in all IDEs" → "preference"
2. **Clear fact**: "User is an iOS developer using SwiftUI" → "durable_fact"
3. **Clear decision**: "Decided to use PostgreSQL instead of SQLite" → "decision"
4. **Open loop**: "Still needs to set up CI/CD pipeline" → "open_loop"
5. **Correction**: "User's timezone is actually PST, not EST as previously stored" → "correction"
6. **Batch classification**: 5 mixed memories → all classified correctly, same length
7. **LLM failure**: Mock error → returns "durable_fact"
8. **Ambiguous text**: Test something borderline → should return a valid type (any valid type is acceptable)

---

## 11. Token Logger (`token_logger.py`)

### Purpose
Track all token consumption across the system — both Anthropic API calls (which cost money) and Ollama local calls (free but useful for performance monitoring). Logs to SQLite for querying and reporting.

### Implementation Spec

```python
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

Design decisions:
- SQLite, not Postgres — this is observability, not critical path
- Async writes via a background thread to avoid blocking
- Cost estimation uses hardcoded rates (update when pricing changes)
- Provides both a Python API and a CLI report script
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

# Anthropic pricing per million tokens (update as needed)
ANTHROPIC_PRICING = {
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    # Add other models as needed
}

# Ollama is free/local but we track for performance
OLLAMA_PRICING = {}  # All zeros — free


@dataclass
class TokenEvent:
    timestamp: str                  # ISO format
    provider: str                   # "anthropic" or "ollama"
    model: str                      # e.g. "claude-sonnet-4-20250514" or "phi3:mini"
    source: str                     # Component: "agent_chat", "query_rewrite",
                                    # "session_extract", "auto_type", "mem0_internal"
    agent_id: str                   # Project scope
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: int                 # Round-trip time in milliseconds
    estimated_cost_usd: float       # 0.0 for Ollama
    metadata: Optional[str] = None  # JSON string for extra context


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
        """
        Log a token consumption event. Non-blocking — silently
        drops on failure to avoid disrupting the main pipeline.
        """
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

    @contextmanager
    def track(self, provider: str, model: str, source: str, agent_id: str):
        """
        Context manager for tracking a single LLM call.

        Usage:
            with token_logger.track("anthropic", "claude-sonnet-4-20250514",
                                     "agent_chat", "oto-dev") as tracker:
                response = client.messages.create(...)
                tracker.record(response.usage.input_tokens,
                               response.usage.output_tokens)

        Or for Ollama:
            with token_logger.track("ollama", "phi3:mini",
                                     "query_rewrite", "oto-dev") as tracker:
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

    # ── Reporting queries ──────────────────────────────────────────

    def get_summary(
        self,
        agent_id: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> dict:
        """
        Get aggregated token usage summary.

        Args:
            agent_id: Filter by agent (None = all agents)
            since: Start date ISO string (None = all time)
            until: End date ISO string (None = now)

        Returns:
            Dict with totals by provider, model, source, and agent.
        """
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

        # Totals
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

        # By provider
        by_provider = conn.execute(
            f"""SELECT provider,
                COUNT(*) as calls,
                SUM(total_tokens) as tokens,
                SUM(estimated_cost_usd) as cost
            FROM token_usage {where}
            GROUP BY provider""",
            params,
        ).fetchall()

        # By source component
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

        # By agent
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

        # Daily trend (last 30 days)
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

    def __init__(self, logger: TokenLogger, provider: str, model: str,
                 source: str, agent_id: str):
        self._logger = logger
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
            return  # Nothing to log if record() wasn't called

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
```

### `scripts/token_report.py`

```python
#!/usr/bin/env python3
"""
Token usage report generator.

Usage:
  python scripts/token_report.py                        # All-time summary
  python scripts/token_report.py --agent oto-dev        # Single agent
  python scripts/token_report.py --since 2026-02-01     # Since date
  python scripts/token_report.py --today                # Today only
  python scripts/token_report.py --json                 # JSON output
"""

import argparse
import json
from datetime import datetime, timezone, timedelta

from mem0_enhanced.token_logger import TokenLogger


def main():
    parser = argparse.ArgumentParser(description="Token usage report")
    parser.add_argument("--agent", help="Filter by agent ID")
    parser.add_argument("--since", help="Start date (ISO format)")
    parser.add_argument("--until", help="End date (ISO format)")
    parser.add_argument("--today", action="store_true", help="Today only")
    parser.add_argument("--week", action="store_true", help="Last 7 days")
    parser.add_argument("--month", action="store_true", help="Last 30 days")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    since = args.since
    until = args.until

    if args.today:
        since = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00")
    elif args.week:
        since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    elif args.month:
        since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    logger = TokenLogger()
    summary = logger.get_summary(agent_id=args.agent, since=since, until=until)

    if args.json:
        print(json.dumps(summary, indent=2))
        return

    # Pretty print
    t = summary["totals"]
    print(f"\n{'='*60}")
    print(f"  TOKEN USAGE REPORT")
    if args.agent:
        print(f"  Agent: {args.agent}")
    if since:
        print(f"  Since: {since}")
    print(f"{'='*60}\n")

    print(f"  Total calls:     {t['calls']:,}")
    print(f"  Input tokens:    {t['input_tokens']:,}")
    print(f"  Output tokens:   {t['output_tokens']:,}")
    print(f"  Total tokens:    {t['total_tokens']:,}")
    print(f"  Estimated cost:  ${t['estimated_cost_usd']:.4f}")
    print(f"  Avg latency:     {t['avg_latency_ms']:.0f}ms")

    if summary["by_provider"]:
        print(f"\n  By Provider:")
        for p in summary["by_provider"]:
            print(f"    {p['provider']:12s}  {p['tokens']:>10,} tokens  ${p['cost']:.4f}")

    if summary["by_source"]:
        print(f"\n  By Component:")
        for s in summary["by_source"]:
            print(f"    {s['source']:20s}  {s['tokens']:>10,} tokens  ${s['cost']:.4f}")

    if summary["by_agent"]:
        print(f"\n  By Agent:")
        for a in summary["by_agent"]:
            print(f"    {a['agent_id']:20s}  {a['tokens']:>10,} tokens  ${a['cost']:.4f}")

    if summary["daily_trend"]:
        print(f"\n  Daily Trend (last 30 days):")
        for d in summary["daily_trend"][:10]:
            bar = "█" * min(int(d['cost'] * 100), 50)
            print(f"    {d['day']}  {d['tokens']:>8,} tokens  ${d['cost']:.4f}  {bar}")

    print()


if __name__ == "__main__":
    main()
```

### Integration Points

The token logger needs to be wired into these locations:

**In `mem0_enhanced/query_rewriter.py`** — wrap the Ollama call:
```python
with self.token_logger.track("ollama", self.model, "query_rewrite", agent_id) as t:
    response = self.client.post(...)
    t.record(response.json().get("prompt_eval_count", 0),
             response.json().get("eval_count", 0))
```

**In `mem0_enhanced/session_extractor.py`** — wrap the extraction call:
```python
with self.token_logger.track("ollama", self.model, "session_extract", agent_id) as t:
    response = self.client.post(...)
    t.record(response.json().get("prompt_eval_count", 0),
             response.json().get("eval_count", 0))
```

**In `mem0_enhanced/auto_typer.py`** — wrap classification calls:
```python
with self.token_logger.track("ollama", self.model, "auto_type", agent_id) as t:
    response = self.client.post(...)
    t.record(response.json().get("prompt_eval_count", 0),
             response.json().get("eval_count", 0))
```

**In `agent_runner/agent.py`** — wrap Anthropic API calls:
```python
with self.token_logger.track("anthropic", self.config.model,
                              "agent_chat", self.config.agent_id) as t:
    response = self.client.messages.create(...)
    t.record(response.usage.input_tokens, response.usage.output_tokens)
```

The `token_logger` instance should be created once in `EnhancedMemory.__init__()` and passed
to each component. For the agent runner, share the same logger instance.

### MCP Tool

Add a `memory_token_usage` tool to the MCP server so agents can self-report:

```python
Tool(
    name="memory_token_usage",
    description="Get token usage summary. Shows consumption by provider, component, and agent.",
    inputSchema={
        "type": "object",
        "properties": {
            "agent_id": {"type": "string", "description": "Filter by agent ID (optional)"},
            "period": {"type": "string", "enum": ["today", "week", "month", "all"], "default": "week"},
        },
    },
),
```

### Test Cases (`test_token_logger.py`)

1. **Basic logging**: Log an event → query it back from SQLite → verify all fields
2. **Context manager**: Use `track()` with `record()` → verify event logged with correct latency
3. **Context manager without record**: Use `track()` without calling `record()` → verify nothing logged
4. **Cost estimation**: Verify Anthropic cost calculation matches known pricing
5. **Ollama zero cost**: Verify Ollama calls always have $0.00 cost
6. **Summary aggregation**: Log 10 events across 3 agents → verify `get_summary()` totals are correct
7. **Filtering**: Log events for two agents → verify agent filter returns only matching events
8. **Failure resilience**: Mock SQLite write failure → verify no exception raised

## 12. Scheduled Garbage Collection

### `scripts/gc.py`

```python
#!/usr/bin/env python3
"""
Standalone garbage collection runner.

Usage:
  python scripts/gc.py <agent_id>              # Dry run
  python scripts/gc.py <agent_id> --execute    # Actually mark inactive
  python scripts/gc.py --all                   # Dry run all agents
  python scripts/gc.py --all --execute         # Execute for all agents

Intended to be run via cron or systemd timer.
"""

import sys
import argparse
import logging

from mem0_enhanced.core import EnhancedMemory
from mem0_enhanced.config import EnhancedMemoryConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Run memory garbage collection")
    parser.add_argument("agent_id", nargs="?", help="Agent ID to clean up")
    parser.add_argument("--all", action="store_true", help="Run for all known agents")
    parser.add_argument("--execute", action="store_true", help="Actually mark inactive (default is dry run)")
    parser.add_argument("--max-age", type=int, default=90, help="Max age in days for GC eligibility (default: 90)")
    args = parser.parse_args()

    if not args.agent_id and not args.all:
        parser.error("Provide an agent_id or use --all")

    memory = EnhancedMemory()
    dry_run = not args.execute

    if args.all:
        # Get all unique agent_ids from Qdrant
        # This requires a custom query — implement based on your Qdrant setup
        # For now, you'd maintain a list or query the vector store
        print("--all requires a registry of agent IDs. Implement per your setup.")
        sys.exit(1)
    else:
        results = memory.run_gc(agent_id=args.agent_id, dry_run=dry_run)
        action = "Would mark" if dry_run else "Marked"
        print(f"{action} {len(results)} memories inactive for agent '{args.agent_id}'")
        for r in results:
            print(f"  - {r['id']}: {r['memory'][:80]}...")


if __name__ == "__main__":
    main()
```

### `cron/mem0-gc.cron`

```cron
# Run garbage collection weekly on Sunday at 3am
# Adjust agent IDs to match your projects
# Dry run first week, then switch to --execute when confident

# Example for a single project:
# 0 3 * * 0 cd /path/to/mem0_enhanced && python scripts/gc.py my-project --execute >> /var/log/mem0-gc.log 2>&1

# Example for multiple projects:
# 0 3 * * 0 cd /path/to/mem0_enhanced && python scripts/gc.py project-a --execute >> /var/log/mem0-gc.log 2>&1
# 5 3 * * 0 cd /path/to/mem0_enhanced && python scripts/gc.py project-b --execute >> /var/log/mem0-gc.log 2>&1
```

### Installation

```bash
# Install crontab entry
crontab -l > /tmp/crontab.bak
cat cron/mem0-gc.cron >> /tmp/crontab.bak
crontab /tmp/crontab.bak

# Or use systemd timer (preferred on Linux)
# See README for systemd unit file example
```

---

## 13. Core Orchestrator (`core.py`)

### Purpose
The main `EnhancedMemory` class that wires everything together. This is the single entry point for all memory operations.

### Implementation Spec

```python
"""
EnhancedMemory: The main orchestrator class.

Wraps Mem0's Memory class and adds:
- Query rewriting before search
- Cross-encoder reranking of results
- Decay scoring on final results
- Access count tracking on retrieval
- Automatic memory type classification
- End-of-session memory extraction
- Garbage collection scheduling

Usage:
    from mem0_enhanced import EnhancedMemory

    memory = EnhancedMemory()  # Uses env vars for config
    memory = EnhancedMemory(config=EnhancedMemoryConfig(...))  # Explicit config

    # Store (auto-types if memory_type not provided)
    memory.add("User prefers dark mode", agent_id="my-project")

    # Search (enhanced pipeline)
    results = memory.search("what are the user preferences?", agent_id="my-project")

    # Build context (for prompt injection)
    context = memory.build_context(agent_id="my-project", query="help with auth",
                                    token_budget=2000)

    # End of session — extract and store memories automatically
    memory.end_session(agent_id="my-project", conversation="User: ...\nAssistant: ...")
"""

import logging
from typing import Optional
from datetime import datetime, timezone

from mem0 import Memory

from .config import EnhancedMemoryConfig
from .query_rewriter import QueryRewriter
from .reranker import MemoryReranker
from .decay import DecayScorer, GarbageCollector
from .session_extractor import SessionExtractor
from .auto_typer import AutoTyper
from .types import ScoredMemory

logger = logging.getLogger(__name__)


class EnhancedMemory:
    def __init__(self, config: Optional[EnhancedMemoryConfig] = None):
        self.config = config or EnhancedMemoryConfig.from_env()

        # Initialize Mem0
        self.mem0 = Memory.from_config(config_dict=self.config.to_mem0_config())

        # Initialize enhanced components
        self.rewriter = (
            QueryRewriter(self.config.ollama_url, self.config.rewriter_model)
            if self.config.enable_rewriter
            else None
        )
        self.reranker = (
            MemoryReranker(self.config.reranker_model)
            if self.config.enable_reranker
            else None
        )
        self.decay_scorer = (
            DecayScorer(self.config.decay_halflife_days)
            if self.config.enable_decay
            else None
        )
        self.gc = GarbageCollector(self.mem0)

        # New V1 components
        self.extractor = SessionExtractor(
            self.config.ollama_url, self.config.extraction_model
        )
        self.auto_typer = AutoTyper(
            self.config.ollama_url, self.config.extraction_model
        )

    def add(
        self,
        text: str,
        agent_id: str,
        user_id: Optional[str] = None,
        memory_type: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        Store a memory with enhanced metadata.
        If memory_type is not provided, auto-classifies using the local LLM.

        Args:
            text: The memory content
            agent_id: Project/agent scope
            user_id: Optional user scope within the agent
            memory_type: One of: preference, durable_fact, decision, open_loop, correction.
                         If None, auto-classified by the local LLM.
            metadata: Additional metadata dict

        Returns:
            Mem0 add() result
        """
        # Auto-classify if no type provided
        if memory_type is None:
            memory_type = self.auto_typer.classify(text)
            logger.info(f"Auto-classified memory as '{memory_type}'")

        enhanced_metadata = {
            **(metadata or {}),
            "memory_type": memory_type,
            "access_count": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "active",
        }

        kwargs = {"agent_id": agent_id, "metadata": enhanced_metadata}
        if user_id:
            kwargs["user_id"] = user_id

        result = self.mem0.add(text, **kwargs)
        logger.info(f"Stored memory for agent={agent_id}, type={memory_type}")
        return result

    def search(
        self,
        query: str,
        agent_id: str,
        also_search: Optional[list[str]] = None,
        user_id: Optional[str] = None,
        session_context: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[ScoredMemory]:
        """
        Enhanced memory search pipeline.

        Pipeline:
        1. Query rewriting (if enabled) → expand to 2-3 queries
        2. Mem0 search for each query, across primary + read-only agent scopes
        3. Deduplicate by memory ID
        4. Filter out inactive memories
        5. Rerank with cross-encoder (if enabled)
        6. Apply decay scoring (if enabled)
        7. Sort by final score, return top-K
        8. Increment access_count on returned memories

        Args:
            query: User's raw query
            agent_id: Primary project/agent scope (read + write)
            also_search: Additional agent IDs to search (read-only).
                         Results are merged and ranked together, but
                         access_count is only incremented for primary agent.
            user_id: Optional user scope
            session_context: Recent conversation for query rewriting context
            limit: Override final_limit from config

        Returns:
            List of ScoredMemory objects, sorted by relevance
        """
        final_limit = limit or self.config.final_limit

        # Step 1: Query rewriting
        if self.rewriter:
            rewritten = self.rewriter.rewrite(query, session_context)
            queries = rewritten.expanded
        else:
            queries = [query]

        # Step 2: Search Mem0 for each query, across all agent scopes
        all_agent_ids = [agent_id] + (also_search or [])
        all_results = {}
        for q in queries:
            for aid in all_agent_ids:
                kwargs = {"agent_id": aid, "limit": self.config.search_limit}
                if user_id:
                    kwargs["user_id"] = user_id

                results = self.mem0.search(query=q, **kwargs)
                for mem in results.get("results", []):
                    # Tag with source agent for tracking
                    mem["_source_agent_id"] = aid
                    # Deduplicate by ID, keep highest score
                    mid = mem["id"]
                    if mid not in all_results or mem.get("score", 0) > all_results[mid].get("score", 0):
                        all_results[mid] = mem

        # Step 3: Filter inactive
        active = [
            m for m in all_results.values()
            if m.get("metadata", {}).get("status", "active") != "inactive"
        ]

        if not active:
            return []

        # Step 4: Rerank
        if self.reranker:
            ranked = self.reranker.rerank(
                query=query,  # Use original query for reranking, not rewritten
                memories=active,
                top_k=min(len(active), self.config.search_limit),
            )
        else:
            ranked = sorted(active, key=lambda m: m.get("score", 0), reverse=True)

        # Step 5: Decay scoring
        if self.decay_scorer:
            for mem in ranked:
                base = mem.get("rerank_score", mem.get("score", 0.5))
                mem["decay_score"] = self.decay_scorer.score(mem, base)
            ranked = sorted(ranked, key=lambda m: m["decay_score"], reverse=True)

        # Step 6: Take top-K
        top_results = ranked[:final_limit]

        # Step 7: Increment access counts (only for primary agent's memories)
        primary_results = [m for m in top_results if m.get("_source_agent_id") == agent_id]
        self._increment_access_counts(primary_results)

        # Step 8: Convert to ScoredMemory (tag source agent for transparency)
        return [self._to_scored_memory(m, m.get("_source_agent_id", agent_id)) for m in top_results]

    def build_context(
        self,
        agent_id: str,
        query: str,
        token_budget: int = 2000,
        user_id: Optional[str] = None,
        session_context: Optional[str] = None,
    ) -> str:
        """
        Build a context string for prompt injection.

        Retrieves relevant memories and formats them into a string
        that fits within the token budget.

        Approximate token counting: 1 token ≈ 4 characters.

        Args:
            agent_id: Project/agent scope
            query: Current user query
            token_budget: Max tokens for the memory context block
            user_id: Optional user scope
            session_context: Recent conversation for rewriter

        Returns:
            Formatted string of relevant memories for prompt injection.
        """
        char_budget = token_budget * 4
        memories = self.search(
            query=query,
            agent_id=agent_id,
            user_id=user_id,
            session_context=session_context,
        )

        lines = []
        used = 0
        for mem in memories:
            line = f"- [{mem.memory_type}] {mem.text}"
            if mem.relations:
                line += f" (related: {', '.join(str(r) for r in mem.relations[:3])})"
            if used + len(line) > char_budget:
                break
            lines.append(line)
            used += len(line)

        if not lines:
            return ""

        header = "## Relevant Memories\n"
        return header + "\n".join(lines)

    def run_gc(self, agent_id: str, dry_run: bool = False) -> list[dict]:
        """Run garbage collection for a specific agent/project."""
        return self.gc.collect(agent_id=agent_id, dry_run=dry_run)

    def end_session(
        self,
        agent_id: str,
        conversation: str,
        user_id: Optional[str] = None,
    ) -> list[dict]:
        """
        End a session: extract memories from the conversation and store them.

        This is the automatic memory pipeline. Call this when a session ends
        (timeout, explicit signal, or agent hook). It:
        1. Fetches existing memories for deduplication
        2. Extracts typed shards from the conversation
        3. Stores each shard with proper metadata

        Args:
            agent_id: Project/agent scope
            conversation: The conversation transcript.
                          Format: "User: ...\nAssistant: ...\n" etc.
            user_id: Optional user scope

        Returns:
            List of Mem0 add() results for each extracted shard.
        """
        # Get existing memories for dedup
        existing = self.mem0.get_all(agent_id=agent_id)
        existing_texts = [
            m["memory"] for m in existing.get("results", [])
            if m.get("metadata", {}).get("status", "active") != "inactive"
        ]

        # Extract shards
        shards = self.extractor.extract(
            conversation=conversation,
            existing_memories=existing_texts,
        )

        if not shards:
            logger.info(f"No memories extracted from session for agent={agent_id}")
            return []

        # Store each shard
        results = []
        for shard in shards:
            result = self.add(
                text=shard["text"],
                agent_id=agent_id,
                user_id=user_id,
                memory_type=shard["type"],  # Already typed by extractor
            )
            results.append(result)

        logger.info(
            f"End of session for agent={agent_id}: "
            f"extracted and stored {len(results)} memories"
        )
        return results

    def _increment_access_counts(self, memories: list[dict]):
        """Increment access_count metadata for retrieved memories."""
        for mem in memories:
            try:
                metadata = mem.get("metadata", {})
                count = metadata.get("access_count", 0) + 1
                self.mem0.update(
                    mem["id"],
                    metadata={**metadata, "access_count": count},
                )
            except Exception as e:
                logger.warning(f"Failed to update access count for {mem['id']}: {e}")

    def _to_scored_memory(self, mem: dict, agent_id: str) -> ScoredMemory:
        """Convert a raw Mem0 result dict to a ScoredMemory."""
        metadata = mem.get("metadata", {})
        created = metadata.get("created_at")
        if isinstance(created, str):
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        else:
            created = datetime.now(timezone.utc)

        return ScoredMemory(
            id=mem["id"],
            text=mem["memory"],
            agent_id=agent_id,
            created_at=created,
            original_score=mem.get("score", 0.0),
            rerank_score=mem.get("rerank_score"),
            decay_score=mem.get("decay_score", mem.get("score", 0.0)),
            access_count=metadata.get("access_count", 0),
            memory_type=metadata.get("memory_type", "unknown"),
            metadata=metadata,
            relations=mem.get("relations", []),
        )
```

---

## 14. MCP Server (`mcp_server.py`)

### Purpose
Expose the EnhancedMemory system as an MCP server so Claude Code and other MCP-capable agents can use it directly.

### Implementation Spec

```python
"""
MCP Server exposing EnhancedMemory tools.

Tools:
  memory_search      - Search memories for an agent with full enhanced pipeline
  memory_add         - Store a new memory (auto-types if type not specified)
  memory_context     - Build a context string for prompt injection
  memory_end_session - Extract and store memories from a completed conversation
  memory_gc          - Run garbage collection for an agent
  memory_get_all     - List all active memories for an agent

Run:
  python -m mem0_enhanced.mcp_server

Configure in Claude Code .mcp.json:
  {
    "mcpServers": {
      "enhanced-memory": {
        "command": "python",
        "args": ["-m", "mem0_enhanced.mcp_server"],
        "env": {
          "MEM0_AGENT_ID": "my-project-name",
          "MEM0_OLLAMA_URL": "http://localhost:11434",
          "MEM0_QDRANT_URL": "http://localhost:6333",
          "MEM0_NEO4J_URL": "bolt://localhost:7687",
          "MEM0_NEO4J_PASSWORD": "mem0graph"
        }
      }
    }
  }

  When MEM0_AGENT_ID is set, all tools default to that agent_id.
  The agent_id parameter becomes optional — only needed if you want
  to override the default (e.g., cross-project queries).
"""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
import json
import asyncio

from .core import EnhancedMemory
from .config import EnhancedMemoryConfig

# Initialize once
config = EnhancedMemoryConfig.from_env()
memory = EnhancedMemory(config)
server = Server("enhanced-memory")
DEFAULT_AGENT_ID = config.default_agent_id  # From MEM0_AGENT_ID env var


def resolve_agent_id(arguments: dict) -> str:
    """Get agent_id from arguments or fall back to configured default."""
    agent_id = arguments.get("agent_id") or DEFAULT_AGENT_ID
    if not agent_id:
        raise ValueError(
            "agent_id is required. Either pass it in the tool call or set MEM0_AGENT_ID env var."
        )
    return agent_id


@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="memory_search",
            description="Search memories for a specific project/agent. Returns relevant memories ranked by relevance, recency, and importance. Can optionally search additional agent scopes as read-only (for cross-project context).",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for"},
                    "agent_id": {"type": "string", "description": "Project/agent ID. Optional if MEM0_AGENT_ID env var is set."},
                    "also_search": {"type": "array", "items": {"type": "string"}, "description": "Additional agent IDs to search (read-only). Results are merged and ranked together."},
                    "session_context": {"type": "string", "description": "Recent conversation context to help resolve vague references"},
                    "limit": {"type": "integer", "description": "Max results (default 5)", "default": 5},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="memory_add",
            description="Store a new memory for a project/agent. Memories are automatically extracted and indexed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The memory content (1-3 sentences, concrete and durable)"},
                    "agent_id": {"type": "string", "description": "Project/agent ID"},
                    "memory_type": {
                        "type": "string",
                        "description": "Type of memory",
                        "enum": ["preference", "durable_fact", "decision", "open_loop", "correction"],
                        "default": "durable_fact",
                    },
                    "metadata": {"type": "object", "description": "Optional additional metadata"},
                },
                "required": ["text", "agent_id"],
            },
        ),
        Tool(
            name="memory_context",
            description="Build a formatted context block of relevant memories for prompt injection. Use this at the start of a task to load project context.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Current task/query to find relevant context for"},
                    "agent_id": {"type": "string", "description": "Project/agent ID"},
                    "token_budget": {"type": "integer", "description": "Max tokens for context (default 2000)", "default": 2000},
                    "session_context": {"type": "string", "description": "Recent conversation context"},
                },
                "required": ["query", "agent_id"],
            },
        ),
        Tool(
            name="memory_end_session",
            description="Extract and store memories from a completed conversation. Call this when a work session ends to automatically capture important facts, decisions, and preferences. The system deduplicates against existing memories.",
            inputSchema={
                "type": "object",
                "properties": {
                    "conversation": {"type": "string", "description": "The conversation transcript. Format: 'User: ...\\nAssistant: ...'"},
                    "agent_id": {"type": "string", "description": "Project/agent ID. Optional if MEM0_AGENT_ID env var is set."},
                },
                "required": ["conversation"],
            },
        ),
        Tool(
            name="memory_gc",
            description="Run garbage collection to clean up stale, unused memories for a project. Use dry_run=true to preview what would be removed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Project/agent ID"},
                    "dry_run": {"type": "boolean", "description": "Preview only, don't actually mark inactive", "default": True},
                },
                "required": ["agent_id"],
            },
        ),
        Tool(
            name="memory_get_all",
            description="List all active memories for a project/agent.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Project/agent ID"},
                },
                "required": ["agent_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    try:
        if name == "memory_search":
            agent_id = resolve_agent_id(arguments)
            results = memory.search(
                query=arguments["query"],
                agent_id=agent_id,
                also_search=arguments.get("also_search"),
                session_context=arguments.get("session_context"),
                limit=arguments.get("limit", 5),
            )
            return [TextContent(
                type="text",
                text=json.dumps([{
                    "id": r.id,
                    "text": r.text,
                    "type": r.memory_type,
                    "score": r.decay_score,
                    "source_agent": r.agent_id,
                    "relations": r.relations,
                } for r in results], indent=2),
            )]

        elif name == "memory_add":
            result = memory.add(
                text=arguments["text"],
                agent_id=arguments["agent_id"],
                memory_type=arguments.get("memory_type", "durable_fact"),
                metadata=arguments.get("metadata"),
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "memory_context":
            context = memory.build_context(
                agent_id=arguments["agent_id"],
                query=arguments["query"],
                token_budget=arguments.get("token_budget", 2000),
                session_context=arguments.get("session_context"),
            )
            return [TextContent(type="text", text=context or "(no relevant memories found)")]

        elif name == "memory_end_session":
            agent_id = resolve_agent_id(arguments)
            results = memory.end_session(
                agent_id=agent_id,
                conversation=arguments["conversation"],
            )
            return [TextContent(
                type="text",
                text=f"Extracted and stored {len(results)} memories for agent '{agent_id}'.\n"
                + json.dumps([{
                    "text": r.get("results", [{}])[0].get("memory", "unknown") if isinstance(r, dict) else str(r)
                } for r in results], indent=2),
            )]

        elif name == "memory_gc":
            results = memory.run_gc(
                agent_id=arguments["agent_id"],
                dry_run=arguments.get("dry_run", True),
            )
            return [TextContent(
                type="text",
                text=f"{'Would mark' if arguments.get('dry_run', True) else 'Marked'} {len(results)} memories inactive.\n"
                + json.dumps([{"id": m["id"], "memory": m["memory"]} for m in results], indent=2),
            )]

        elif name == "memory_get_all":
            results = memory.mem0.get_all(agent_id=arguments["agent_id"])
            active = [
                m for m in results.get("results", [])
                if m.get("metadata", {}).get("status", "active") != "inactive"
            ]
            return [TextContent(
                type="text",
                text=json.dumps([{
                    "id": m["id"],
                    "memory": m["memory"],
                    "type": m.get("metadata", {}).get("memory_type", "unknown"),
                    "access_count": m.get("metadata", {}).get("access_count", 0),
                } for m in active], indent=2),
            )]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 15. Setup Script (`scripts/setup.sh`)

```bash
#!/bin/bash
set -e

echo "=== Enhanced Mem0 Setup ==="

# 1. Start infrastructure
echo "Starting Docker services..."
docker compose up -d

# 2. Wait for services
echo "Waiting for services to be ready..."
sleep 5

# Check Qdrant
until curl -s http://localhost:6333/healthz > /dev/null 2>&1; do
    echo "  Waiting for Qdrant..."
    sleep 2
done
echo "  ✓ Qdrant ready"

# Check Neo4j
until curl -s http://localhost:7474 > /dev/null 2>&1; do
    echo "  Waiting for Neo4j..."
    sleep 2
done
echo "  ✓ Neo4j ready"

# Check Ollama
until curl -s http://localhost:11434/api/tags > /dev/null 2>&1; do
    echo "  Waiting for Ollama..."
    sleep 2
done
echo "  ✓ Ollama ready"

# 3. Pull models
echo "Pulling Ollama models..."
docker exec ollama ollama pull nomic-embed-text
docker exec ollama ollama pull phi3:mini

# 4. Install Python package
echo "Installing mem0_enhanced..."
pip install -e ".[dev]"

echo ""
echo "=== Setup Complete ==="
echo "Infrastructure: Qdrant :6333 | Neo4j :7474/:7687 | Ollama :11434"
echo ""
echo "Quick test:"
echo "  python -c \"from mem0_enhanced import EnhancedMemory; m = EnhancedMemory(); print('OK')\""
echo ""
echo "Start MCP server:"
echo "  python -m mem0_enhanced.mcp_server"
```

---

## 16. pyproject.toml

```toml
[project]
name = "mem0-enhanced"
version = "0.1.0"
description = "Enhanced memory layer with query rewriting, reranking, and decay on top of Mem0"
requires-python = ">=3.10"

dependencies = [
    "mem0ai>=1.0",
    "sentence-transformers>=3.0",
    "httpx>=0.27",
    "mcp>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends._legacy:_Backend"

[tool.setuptools.packages.find]
where = ["src"]
```

---

## 17. Build Order

Execute in this order. Each step should be independently testable before moving on.

### Phase 1: Infrastructure (30 min)
1. Create project directory structure
2. Write `docker-compose.yml`
3. Write `scripts/setup.sh`
4. Run setup, verify all three services are healthy
5. Write `pyproject.toml`, install in editable mode

### Phase 2: Config + Types (15 min)
6. Implement `config.py` with env var loading
7. Implement `types.py` dataclasses
8. Verify: instantiate `EnhancedMemoryConfig.from_env()` and `to_mem0_config()`

### Phase 3: Mem0 Baseline (15 min)
9. Write a minimal test script that creates a `Memory.from_config()` using the generated config
10. Test `add()` and `search()` with a simple example
11. Test graph memory by adding a relational fact and querying it

### Phase 4: Query Rewriter (30 min)
12. Implement `query_rewriter.py`
13. Write `test_query_rewriter.py`
14. Test against running Ollama: verify vague queries get expanded

### Phase 5: Reranker (20 min)
15. Implement `reranker.py`
16. Write `test_reranker.py`
17. Verify cross-encoder model downloads and scores correctly

### Phase 6: Decay (30 min)
18. Implement `decay.py` (both DecayScorer and GarbageCollector)
19. Write `test_decay.py`
20. Test decay scoring with mocked timestamps
21. Test GC dry run

### Phase 7: Auto Typer (20 min)
22. Implement `auto_typer.py`
23. Write `test_auto_typer.py`
24. Test single classification and batch classification against Ollama

### Phase 8: Session Extractor (30 min)
25. Implement `session_extractor.py`
26. Write `test_session_extractor.py`
27. Test with a realistic multi-turn conversation transcript
28. Verify deduplication works when existing memories are provided

### Phase 9: Token Logger (25 min)
29. Implement `token_logger.py` (SQLite storage, context manager, reporting queries)
30. Implement `scripts/token_report.py` CLI tool
31. Write `test_token_logger.py`
32. Test: log events, query summaries, verify cost calculations

### Phase 10: Core Orchestrator (30 min)
33. Implement `core.py` — wire all components together including token_logger
34. Write `test_core.py` — integration test using real services
35. Test full pipeline: add memories → search with rewriting → verify reranking → verify decay
36. Test `end_session()`: provide a conversation → verify shards extracted and stored with correct types
37. Test auto-typing: call `add()` without a type → verify it gets classified
38. Verify token events are being logged for each Ollama call

### Phase 11: MCP Server (20 min)
39. Implement `mcp_server.py` with all 7 tools (including memory_token_usage)
40. Test by running the server and calling tools via MCP inspector or Claude Code
41. Write Claude Code `.mcp.json` config

### Phase 12: Scheduled GC (10 min)
42. Implement `scripts/gc.py` standalone runner
43. Write `cron/mem0-gc.cron` crontab entry
44. Test: run `python scripts/gc.py <agent_id>` dry run

### Phase 13: Integration Test (20 min)
45. Create a test scenario simulating real usage:
    - Create two agents with different IDs (e.g. "project-a" and "project-b")
    - Add 10+ memories to each with different types
    - Search from agent A → verify no agent B memories leak
    - Search from agent A with `also_search=["project-b"]` → verify cross-agent read works
    - Search with vague queries → verify rewriter helps
    - Call `end_session()` with a conversation → verify automatic extraction + typing
    - Wait (or mock time) → verify decay scoring changes rankings
    - Run GC → verify only eligible memories marked inactive
    - Verify durable_facts and preferences survive GC regardless of age
    - Run `python scripts/token_report.py` → verify all calls were logged with correct sources

---

## 18. Deploying to a New Project

The system is project-agnostic. To add memory to any repo:

### Option A: Shared Infrastructure (Recommended)

Run the Docker stack once on your dev machine. Each project just configures a unique `agent_id` in its `.mcp.json`:

```jsonc
// <project-repo>/.mcp.json
{
  "mcpServers": {
    "memory": {
      "command": "python",
      "args": ["-m", "mem0_enhanced.mcp_server"],
      "env": {
        "MEM0_AGENT_ID": "my-project-name"  // unique per project
      }
    }
  }
}
```

The `MEM0_AGENT_ID` env var is the only thing that changes between projects. All memories are scoped to it. The backing services (Qdrant, Neo4j, Ollama) are shared but data is isolated.

### Option B: Self-Contained per Project

If you want total isolation (e.g., different decay settings per project), copy the `docker-compose.yml` into the project repo and run a dedicated stack. Use different port mappings to avoid conflicts.

### Agent ID Convention

Pick any string. Keep it short, lowercase, hyphenated. Examples:
- `my-ios-app`
- `marketing-site`
- `side-project-x`

The system doesn't enforce naming — it's just a partition key.

---

## 19. Multi-Device Access

The memory stack runs on one machine and is accessible from any other device on your network. This means your laptop and Mac Mini (or any future devices) share the same memory.

### 18.1 Choose a Host Machine

Pick the machine that's always on. The Mac Mini is ideal — it stays powered, sits on your desk, and has the storage for Docker volumes.

All three containers (Qdrant, Neo4j, Ollama) run here.

### 18.2 Bind to Network Interface

Update `docker-compose.yml` to expose services on the LAN instead of localhost only:

```yaml
services:
  qdrant:
    ports:
      - "0.0.0.0:6333:6333"    # Was 127.0.0.1:6333:6333
  neo4j:
    ports:
      - "0.0.0.0:7474:7474"
      - "0.0.0.0:7687:7687"
  ollama:
    ports:
      - "0.0.0.0:11434:11434"
```

Using `0.0.0.0` binds to all interfaces. If you prefer to lock it to a specific
network interface, use the host machine's LAN IP instead (e.g., `192.168.1.50`).

### 18.3 Configure Client Devices

On the host machine (Mac Mini), the `.mcp.json` stays the same — localhost works.

On other devices (laptop), point to the host machine's IP:

```jsonc
// laptop: <project-repo>/.mcp.json
{
  "mcpServers": {
    "memory": {
      "command": "python",
      "args": ["-m", "mem0_enhanced.mcp_server"],
      "env": {
        "MEM0_AGENT_ID": "my-project",
        "MEM0_QDRANT_URL": "http://192.168.1.50:6333",
        "MEM0_NEO4J_URL": "bolt://192.168.1.50:7687",
        "MEM0_OLLAMA_URL": "http://192.168.1.50:11434"
      }
    }
  }
}
```

The `mem0_enhanced` Python package still needs to be installed on each client
device, but all data lives on the host. The client just runs the thin orchestration
layer locally and talks to the remote services.

### 18.4 Remote Access via Tailscale (Outside Home Network)

When you're away from your home network (laptop at a coffee shop, traveling, etc.),
your LAN IPs won't work. Use Tailscale to create a mesh VPN:

```bash
# Install on both machines
# Mac Mini (host):
brew install tailscale

# Laptop (client):
brew install tailscale
```

After signing in on both devices, Tailscale assigns each a stable IP (e.g., `100.x.y.z`)
that works from anywhere — no port forwarding, no firewall config, no dynamic DNS.

Update your laptop's `.mcp.json` to use the Tailscale IP:

```jsonc
{
  "env": {
    "MEM0_QDRANT_URL": "http://100.x.y.z:6333",
    "MEM0_NEO4J_URL": "bolt://100.x.y.z:7687",
    "MEM0_OLLAMA_URL": "http://100.x.y.z:11434"
  }
}
```

Tailscale IPs are stable across reboots and network changes, so you set this once.

### 18.5 Security Considerations

Since the services are exposed on the network:

1. **Firewall**: Ensure your host machine's firewall only allows connections from
   trusted IPs or your Tailscale network. On macOS, the built-in firewall handles this.
   If using `0.0.0.0` binding, anyone on your LAN can reach the services.

2. **Neo4j credentials**: The default password (`mem0graph`) is fine for local-only,
   but change it if exposing to a network. Update both `docker-compose.yml` and
   `MEM0_NEO4J_PASSWORD` env var on all clients.

3. **Tailscale is encrypted**: Traffic between Tailscale nodes is end-to-end encrypted
   (WireGuard), so your memory data is safe in transit even over public WiFi.

4. **No auth on Qdrant/Ollama by default**: These services don't have built-in auth.
   Relying on network-level security (firewall + Tailscale) is the practical approach
   for a personal setup. Don't expose these ports to the public internet.

### 18.6 Optional: Centralized Config

To avoid duplicating connection URLs across every project's `.mcp.json`, create a
shared env file on each device:

```bash
# ~/.mem0env (on each device)
export MEM0_QDRANT_URL="http://100.x.y.z:6333"    # Tailscale IP of host
export MEM0_NEO4J_URL="bolt://100.x.y.z:7687"
export MEM0_NEO4J_PASSWORD="mem0graph"
export MEM0_OLLAMA_URL="http://100.x.y.z:11434"
```

Then source it in your shell profile (`~/.zshrc`):
```bash
source ~/.mem0env
```

Now each project's `.mcp.json` only needs the agent ID — connection URLs
are picked up from the environment automatically:

```jsonc
{
  "mcpServers": {
    "memory": {
      "command": "python",
      "args": ["-m", "mem0_enhanced.mcp_server"],
      "env": {
        "MEM0_AGENT_ID": "my-project"
      }
    }
  }
}
```

---

## 20. Future Enhancements (Not in V1)

- **Memory compaction**: Merge similar memories to reduce volume
- **Cross-agent memory sharing**: Controlled sharing of specific memory types
- **Dashboard**: Web UI to browse/manage memories per agent