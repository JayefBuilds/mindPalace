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
- Token consumption tracking
"""

import logging
import os
from typing import Optional
from datetime import datetime, timezone

from mem0 import Memory
from qdrant_client import QdrantClient

from .config import EnhancedMemoryConfig
from .llm import LLMClient
from .query_rewriter import QueryRewriter
from .reranker import MemoryReranker
from .decay import DecayScorer, GarbageCollector
from .session_extractor import SessionExtractor
from .auto_typer import AutoTyper
from .token_logger import TokenLogger
from .types import ScoredMemory

logger = logging.getLogger(__name__)


class EnhancedMemory:
    def __init__(self, config: Optional[EnhancedMemoryConfig] = None):
        self.config = config or EnhancedMemoryConfig.from_env()

        # OAuth tokens (Claude.ai subscription) don't support custom function tools,
        # which graph memory requires. Auto-disable graph when using OAuth.
        oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
        if oauth_token:
            if self.config.enable_graph:
                logger.info("OAuth token detected: disabling graph memory (not supported with OAuth auth)")
                self.config.enable_graph = False
            self._patch_mem0_anthropic_client(oauth_token)

        # Initialize Mem0
        self.mem0 = Memory.from_config(config_dict=self.config.to_mem0_config())

        # Direct Qdrant client for metadata updates (mem0's update() only handles text)
        self.qdrant = QdrantClient(url=self.config.qdrant_url)

        # Initialize token logger
        self.token_logger = TokenLogger()

        # Initialize unified LLM client (Anthropic Haiku or Ollama)
        self.llm = LLMClient(
            provider=self.config.llm_provider,
            model=self.config.llm_model,
            ollama_url=self.config.ollama_url,
            token_logger=self.token_logger,
        )

        # Initialize enhanced components
        self.rewriter = (
            QueryRewriter(self.llm)
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
        self.gc = GarbageCollector(self.qdrant, mem0_instance=self.mem0)

        self.extractor = SessionExtractor(self.llm)
        self.auto_typer = AutoTyper(self.llm)

    @staticmethod
    def _patch_mem0_anthropic_client(oauth_token: str):
        """
        Patch Mem0's AnthropicLLM to use OAuth Bearer auth instead of x-api-key.
        Required because OAuth tokens (sk-ant-oat01-*) need special beta headers
        that Mem0's client doesn't know about.
        """
        import anthropic as _anthropic
        from mem0.llms import anthropic as mem0_anthropic_module

        _original_init = mem0_anthropic_module.AnthropicLLM.__init__

        _original_generate = mem0_anthropic_module.AnthropicLLM.generate_response

        def _patched_init(self, config=None):
            _original_init(self, config)
            raw_client = _anthropic.Anthropic(
                auth_token=oauth_token,
                default_headers={
                    "anthropic-beta": "claude-code-20250219,oauth-2025-04-20",
                },
            )

            # Wrap messages.create to strip None-valued params (top_p, etc.)
            # that Mem0 passes but OAuth-authenticated Claude rejects
            _orig_create = raw_client.messages.create

            def _create_without_nones(**kwargs):
                # Strip None values (e.g. top_p) that OAuth Claude rejects
                kwargs = {k: v for k, v in kwargs.items() if v is not None}
                if kwargs.get("tools"):
                    # Coerce string tool_choice to dict form Anthropic requires
                    tc = kwargs.get("tool_choice")
                    if isinstance(tc, str):
                        kwargs["tool_choice"] = {"type": tc}
                else:
                    kwargs.pop("tool_choice", None)
                    kwargs.pop("tools", None)
                return _orig_create(**kwargs)

            raw_client.messages.create = _create_without_nones
            self.client = raw_client

        def _patched_generate(self, messages, response_format=None, tools=None, tool_choice="auto", **kwargs):
            # OAuth models reject top_p alongside temperature — zero it out before params are built
            if hasattr(self, 'config') and hasattr(self.config, 'top_p'):
                self.config.top_p = None
            return _original_generate(self, messages, response_format, tools, tool_choice, **kwargs)

        mem0_anthropic_module.AnthropicLLM.__init__ = _patched_init
        mem0_anthropic_module.AnthropicLLM.generate_response = _patched_generate

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
        """
        if memory_type is None:
            memory_type = self.auto_typer.classify(text, agent_id=agent_id)
            logger.info(f"Auto-classified memory as '{memory_type}'")

        enhanced_metadata = {
            **(metadata or {}),
            "memory_type": memory_type,
            "access_count": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "active",
        }

        kwargs = {"agent_id": agent_id, "user_id": user_id or agent_id, "metadata": enhanced_metadata}

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
        1. Query rewriting (if enabled)
        2. Mem0 search for each query, across primary + read-only agent scopes
        3. Deduplicate by memory ID
        4. Filter out inactive memories
        5. Rerank with cross-encoder (if enabled)
        6. Apply decay scoring (if enabled)
        7. Sort by final score, return top-K
        8. Increment access_count on returned memories
        """
        final_limit = limit or self.config.final_limit

        # Step 1: Query rewriting
        if self.rewriter:
            rewritten = self.rewriter.rewrite(query, session_context, agent_id=agent_id)
            queries = rewritten.expanded
        else:
            queries = [query]

        # Step 2: Search Mem0 for each query, across all agent scopes
        all_agent_ids = [agent_id] + (also_search or [])
        all_results = {}
        effective_user_id = user_id or agent_id

        for q in queries:
            for aid in all_agent_ids:
                kwargs = {"agent_id": aid, "user_id": effective_user_id, "limit": self.config.search_limit}

                results = self.mem0.search(query=q, **kwargs)
                for mem in results.get("results", []):
                    mem["_source_agent_id"] = aid
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
                query=query,
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

        # Step 8: Convert to ScoredMemory
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
        Approximate token counting: 1 token ≈ 4 characters.
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

        This is the automatic memory pipeline. Call this when a session ends.
        """
        existing = self.mem0.get_all(agent_id=agent_id, user_id=user_id or agent_id)
        existing_texts = [
            m["memory"] for m in existing.get("results", [])
            if m.get("metadata", {}).get("status", "active") != "inactive"
        ]

        shards = self.extractor.extract(
            conversation=conversation,
            existing_memories=existing_texts,
            agent_id=agent_id,
        )

        if not shards:
            logger.info(f"No memories extracted from session for agent={agent_id}")
            return []

        results = []
        for shard in shards:
            result = self.add(
                text=shard["text"],
                agent_id=agent_id,
                user_id=user_id,
                memory_type=shard["type"],
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
                count = mem.get("metadata", {}).get("access_count", 0) + 1
                self.qdrant.set_payload(
                    collection_name="mem0",
                    payload={"access_count": count},
                    points=[mem["id"]],
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
