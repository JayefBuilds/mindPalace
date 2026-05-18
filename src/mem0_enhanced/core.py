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
- Graph extraction via our own LLM client (works with OAuth and API keys)
"""

import logging
import os
from typing import Optional
from datetime import datetime, timezone

import httpx
from mem0 import Memory
from qdrant_client import QdrantClient
from qdrant_client.models import PointVectors

from .config import EnhancedMemoryConfig
from .llm import LLMClient
from .query_rewriter import QueryRewriter
from .reranker import MemoryReranker
from .decay import DecayScorer, GarbageCollector
from .session_extractor import SessionExtractor
from .auto_typer import AutoTyper
from .token_logger import TokenLogger
from .memory_event_logger import MemoryEventLogger
from .graph_extractor import GraphExtractor
from .types import ScoredMemory
from .lifecycle import ARCHIVED, active_payload, inactive_payload, is_active, utc_now_iso

logger = logging.getLogger(__name__)


class EnhancedMemory:
    def __init__(self, config: Optional[EnhancedMemoryConfig] = None):
        self.config = config or EnhancedMemoryConfig.from_env()

        # Save whether graph was requested before any OAuth override.
        # We'll use this to initialize our own GraphExtractor independently of Mem0.
        _graph_requested = self.config.enable_graph

        # OAuth tokens don't support Anthropic tool-calling, which Mem0's internal
        # graph extraction requires. Disable graph for Mem0 when using OAuth —
        # our GraphExtractor handles it instead via plain-text prompts.
        # Always patch tool_choice string→dict coercion (mem0 sends "auto", API wants {"type":"auto"})
        self._patch_mem0_tool_choice()

        oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if oauth_token and not api_key:
            if self.config.enable_graph:
                self.config.enable_graph = False
            self._patch_mem0_anthropic_client(oauth_token)

        # Initialize Mem0
        self.mem0 = Memory.from_config(config_dict=self.config.to_mem0_config())

        # Direct Qdrant client for metadata updates (mem0's update() only handles text)
        self.qdrant = QdrantClient(url=self.config.qdrant_url)

        # Initialize token logger
        self.token_logger = TokenLogger()
        self.event_logger = MemoryEventLogger()

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

        # Custom graph extractor — uses our LLM client, works with OAuth and API keys alike.
        # Initialized whenever graph was originally requested, regardless of OAuth.
        self.graph_extractor = (
            GraphExtractor(self.llm, self.config.neo4j_url, self.config.neo4j_password)
            if _graph_requested
            else None
        )

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

    @staticmethod
    def _patch_mem0_tool_choice():
        """
        Patch Mem0's AnthropicLLM.generate_response to coerce string tool_choice
        values to the dict form the API requires. Applies unconditionally — mem0
        passes tool_choice='auto' (string) but Anthropic expects {'type': 'auto'}.
        """
        from mem0.llms import anthropic as mem0_anthropic_module

        if getattr(mem0_anthropic_module.AnthropicLLM, "_tool_choice_patched", False):
            return  # already patched

        _original_generate = mem0_anthropic_module.AnthropicLLM.generate_response

        def _patched_generate(self, messages, response_format=None, tools=None, tool_choice="auto", **kwargs):
            if isinstance(tool_choice, str):
                tool_choice = {"type": tool_choice}
            return _original_generate(self, messages, response_format, tools, tool_choice, **kwargs)

        mem0_anthropic_module.AnthropicLLM.generate_response = _patched_generate
        mem0_anthropic_module.AnthropicLLM._tool_choice_patched = True

    def list_agents(self) -> list[dict]:
        """
        List all agent_ids that have memories in Qdrant, with memory counts.
        Scrolls the entire mem0 collection and aggregates by agent_id payload field.
        """
        from qdrant_client.models import ScrollRequest

        agents: dict[str, int] = {}
        offset = None

        while True:
            results, next_offset = self.qdrant.scroll(
                collection_name="mem0",
                limit=500,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in results:
                payload = point.payload or {}
                aid = payload.get("agent_id") or payload.get("user_id")
                if aid:
                    agents[aid] = agents.get(aid, 0) + 1
            if next_offset is None:
                break
            offset = next_offset

        return [{"agent_id": k, "count": v} for k, v in sorted(agents.items())]

    def rename_agent(self, old_id: str, new_id: str, registry_path: Optional[str] = None) -> dict:
        """
        Migrate all memories from old_id to new_id.

        Steps:
        1. Fetch all memories for old_id (using original case for Qdrant query)
        2. Write each directly to mem0 under new_id (bypasses LLM dedup — safe for migration)
        3. Delete originals from Qdrant via mem0
        4. Update registry.json if path provided

        Returns a summary dict.
        """
        import json as _json

        new_id = new_id.lower()

        # Block only if old and new are literally the same string (already lowercase)
        if old_id == new_id:
            return {"migrated": 0, "deleted": 0, "message": "old_id and new_id are the same"}

        # Fetch all memories using original case (Qdrant stores agent_id as-is)
        raw = self.mem0.get_all(filters={"agent_id": old_id, "user_id": old_id})
        memories = [
            m for m in raw.get("results", [])
            if is_active(m)
        ]

        migrated = 0
        deleted = 0
        errors = []

        for mem in memories:
            metadata = dict(mem.get("metadata", {}))
            memory_type = metadata.get("memory_type", "durable_fact")
            # Rebuild clean metadata for the new entry
            new_metadata = {
                "memory_type": memory_type,
                "access_count": metadata.get("access_count", 0),
                "created_at": metadata.get("created_at", utc_now_iso()),
                **active_payload(),
            }
            if metadata.get("supersedes"):
                new_metadata["supersedes"] = metadata["supersedes"]

            try:
                # Embed directly via Ollama and write to Qdrant — bypasses mem0's LLM
                # dedup step entirely. Safe for migration since memories are already vetted.
                self._write_memory_direct(
                    text=mem["memory"],
                    agent_id=new_id,
                    metadata=new_metadata,
                )
                migrated += 1
            except Exception as e:
                errors.append({"id": mem["id"], "error": str(e)})
                continue

            try:
                self.mem0.delete(memory_id=mem["id"])
                deleted += 1
            except Exception as e:
                errors.append({"id": mem["id"], "delete_error": str(e)})

        # Update registry.json if path provided
        registry_updated = False
        if registry_path:
            try:
                with open(registry_path, "r") as f:
                    registry = _json.load(f)
                updated = False
                for path, aid in registry.items():
                    if aid.lower() == old_id.lower():
                        registry[path] = new_id
                        updated = True
                if updated:
                    with open(registry_path, "w") as f:
                        _json.dump(registry, f, indent=2)
                    registry_updated = True
            except Exception as e:
                errors.append({"registry_error": str(e)})

        logger.info(f"rename_agent: {old_id} → {new_id}: migrated={migrated}, deleted={deleted}")
        return {
            "old_id": old_id,
            "new_id": new_id,
            "migrated": migrated,
            "deleted": deleted,
            "registry_updated": registry_updated,
            "errors": errors,
        }

    def add(
        self,
        text: str,
        agent_id: str,
        user_id: Optional[str] = None,
        memory_type: Optional[str] = None,
        metadata: Optional[dict] = None,
        supersedes: Optional[list[str]] = None,
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
            "created_at": utc_now_iso(),
            **active_payload(),
        }
        if supersedes:
            enhanced_metadata["supersedes"] = supersedes

        agent_id = agent_id.lower()
        kwargs = {"agent_id": agent_id, "user_id": user_id or agent_id, "metadata": enhanced_metadata}

        result = self.mem0.add(text, **kwargs)
        logger.info(f"Stored memory for agent={agent_id}, type={memory_type}")

        memory_id = self._extract_result_memory_id(result)
        if memory_id and supersedes:
            self._archive_superseded(supersedes, memory_id)

        # Extract entities/relations and write to Neo4j using our own LLM client.
        if self.graph_extractor:
            if memory_id:
                self.graph_extractor.extract_and_store(text, agent_id, memory_id)
                self.event_logger.log_event(
                    event_type="graph_extracted",
                    agent_id=agent_id,
                    memory_id=memory_id,
                    source="core.add",
                )

        self.event_logger.log_event(
            event_type="memory_added",
            agent_id=agent_id,
            memory_id=memory_id,
            source="core.add",
            metadata={
                "memory_type": memory_type,
                "supersedes": supersedes or [],
            },
        )

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
        7. Take top-K
        8. Enrich with graph relations (if enabled)
        9. Increment access_count on returned memories
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
                results = self.mem0.search(
                    query=q,
                    filters={"agent_id": aid, "user_id": effective_user_id},
                    top_k=self.config.search_limit,
                )
                for mem in results.get("results", []):
                    mem["_source_agent_id"] = aid
                    mid = mem["id"]
                    if mid not in all_results or mem.get("score", 0) > all_results[mid].get("score", 0):
                        all_results[mid] = mem

        # Step 3: Filter inactive
        active = [
            m for m in all_results.values()
            if is_active(m)
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

        # Step 7: Enrich with graph relations
        if self.graph_extractor:
            for mem in top_results:
                mem["relations"] = self.graph_extractor.get_relations(mem["id"])

        # Step 8: Increment access counts (only for primary agent's memories)
        primary_results = [m for m in top_results if m.get("_source_agent_id") == agent_id]
        self._increment_access_counts(primary_results)

        # Step 9: Convert to ScoredMemory
        scored = [self._to_scored_memory(m, m.get("_source_agent_id", agent_id)) for m in top_results]
        self.event_logger.log_event(
            event_type="memory_searched",
            agent_id=agent_id,
            source="core.search",
            metadata={
                "query": query,
                "result_count": len(scored),
                "also_search": also_search or [],
            },
        )
        return scored

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
        context = header + "\n".join(lines)
        self.event_logger.log_event(
            event_type="memory_context_built",
            agent_id=agent_id,
            source="core.build_context",
            metadata={
                "query": query,
                "memory_count": len(lines),
                "token_budget": token_budget,
            },
        )
        return context

    def run_gc(self, agent_id: str, dry_run: bool = False) -> list[dict]:
        """Run garbage collection for a specific agent/project."""
        results = self.gc.collect(agent_id=agent_id, dry_run=dry_run)
        self.event_logger.log_event(
            event_type="memory_gc",
            agent_id=agent_id,
            source="core.run_gc",
            metadata={"dry_run": dry_run, "candidate_count": len(results)},
        )
        return results

    def health_status(self, agent_id: Optional[str] = None, scan_limit: int = 5000) -> dict:
        """
        Return operational health for backing services and memory metadata.

        This intentionally scans Qdrant payloads directly so it can diagnose
        records even when Mem0's higher-level API shape changes.
        """
        status = {
            "qdrant": {"ok": False, "error": None},
            "ollama": {"ok": False, "error": None, "embedding_model": self.config.embedding_model},
            "graph": {
                "enabled": self.graph_extractor is not None,
                "connected": bool(getattr(self.graph_extractor, "_driver", None)) if self.graph_extractor else False,
            },
            "memories": {
                "scanned": 0,
                "active": 0,
                "archived": 0,
                "pruned": 0,
                "legacy_inactive": 0,
                "missing_text": 0,
                "missing_vector": 0,
                "by_agent": {},
                "by_type": {},
                "truncated": False,
            },
        }

        try:
            for mem in self._scroll_qdrant_memories(
                agent_id=agent_id,
                scan_limit=scan_limit,
                with_vectors=True,
            ):
                payload = mem.get("metadata", {})
                lifecycle = payload.get("lifecycle")
                if lifecycle == "archived":
                    status["memories"]["archived"] += 1
                elif lifecycle == "pruned" or payload.get("status") == "inactive":
                    status["memories"]["pruned"] += 1
                    if lifecycle is None:
                        status["memories"]["legacy_inactive"] += 1
                else:
                    status["memories"]["active"] += 1

                if not mem.get("memory"):
                    status["memories"]["missing_text"] += 1
                if not mem.get("_has_vector"):
                    status["memories"]["missing_vector"] += 1

                aid = payload.get("agent_id") or payload.get("user_id") or "unknown"
                mtype = payload.get("memory_type", "unknown")
                by_agent = status["memories"]["by_agent"]
                by_type = status["memories"]["by_type"]
                by_agent[aid] = by_agent.get(aid, 0) + 1
                by_type[mtype] = by_type.get(mtype, 0) + 1
                status["memories"]["scanned"] += 1

            status["memories"]["truncated"] = status["memories"]["scanned"] >= scan_limit
            status["qdrant"]["ok"] = True
        except Exception as e:
            status["qdrant"]["error"] = str(e)

        try:
            resp = httpx.get(f"{self.config.ollama_url}/api/tags", timeout=3)
            resp.raise_for_status()
            models = [m.get("name") for m in resp.json().get("models", [])]
            status["ollama"]["ok"] = True
            status["ollama"]["models"] = models
            status["ollama"]["embedding_model_present"] = any(
                name == self.config.embedding_model or name.startswith(f"{self.config.embedding_model}:")
                for name in models
                if isinstance(name, str)
            )
        except Exception as e:
            status["ollama"]["error"] = str(e)

        self.event_logger.log_event(
            event_type="memory_health_checked",
            agent_id=agent_id or "all",
            source="core.health_status",
            metadata={
                "qdrant_ok": status["qdrant"]["ok"],
                "ollama_ok": status["ollama"]["ok"],
                "scanned": status["memories"]["scanned"],
            },
        )
        return status

    def reembed_memories(
        self,
        agent_id: Optional[str] = None,
        dry_run: bool = True,
        limit: Optional[int] = None,
    ) -> dict:
        """
        Recompute embeddings for active memories and update Qdrant vectors.

        Defaults to dry-run so operators can estimate blast radius first.
        """
        result = {
            "dry_run": dry_run,
            "agent_id": agent_id,
            "scanned": 0,
            "updated": 0,
            "failed": 0,
            "errors": [],
        }

        for mem in self._scroll_qdrant_memories(
            agent_id=agent_id,
            active_only=True,
            scan_limit=limit,
            with_vectors=False,
        ):
            result["scanned"] += 1
            text = mem.get("memory") or ""
            if not text:
                result["failed"] += 1
                result["errors"].append({"id": mem["id"], "error": "missing memory text"})
                continue
            if dry_run:
                continue

            try:
                vector = self._embed_text(text)
                self.qdrant.update_vectors(
                    collection_name="mem0",
                    points=[PointVectors(id=mem["id"], vector=vector)],
                )
                result["updated"] += 1
            except Exception as e:
                result["failed"] += 1
                result["errors"].append({"id": mem["id"], "error": str(e)})

        self.event_logger.log_event(
            event_type="memory_reembedded",
            agent_id=agent_id or "all",
            source="core.reembed_memories",
            metadata={
                "dry_run": dry_run,
                "scanned": result["scanned"],
                "updated": result["updated"],
                "failed": result["failed"],
            },
        )
        return result

    def run_consolidation(
        self,
        agent_id: str,
        dry_run: bool = True,
        max_memories: int = 150,
    ) -> dict:
        """Run proposer/adversary/judge consolidation for one agent."""
        from .consolidation import MemoryConsolidator

        result = MemoryConsolidator(self).run(
            agent_id=agent_id,
            dry_run=dry_run,
            max_memories=max_memories,
        )
        return result.to_dict()

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
        existing = self.mem0.get_all(filters={"agent_id": agent_id, "user_id": user_id or agent_id})
        existing_texts = [
            m["memory"] for m in existing.get("results", [])
            if is_active(m)
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
        self.event_logger.log_event(
            event_type="session_extracted",
            agent_id=agent_id,
            source="core.end_session",
            metadata={"stored_count": len(results)},
        )
        return results

    def _write_memory_direct(self, text: str, agent_id: str, metadata: dict):
        """
        Embed text via Ollama and write directly to Qdrant, bypassing mem0's LLM dedup.
        Used for safe bulk operations like agent rename/migration.
        """
        import uuid
        from qdrant_client.models import PointStruct

        # Embed via Ollama
        vector = self._embed_text(text)

        point_id = str(uuid.uuid4())
        payload = {
            "data": text,
            "memory": text,
            "agent_id": agent_id,
            "user_id": agent_id,
            **metadata,
        }

        self.qdrant.upsert(
            collection_name="mem0",
            points=[PointStruct(id=point_id, vector=vector, payload=payload)],
        )

    def _embed_text(self, text: str) -> list[float]:
        """Embed text using the configured local Ollama embedding model."""
        resp = httpx.post(
            f"{self.config.ollama_url}/api/embeddings",
            json={"model": self.config.embedding_model, "prompt": text},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]

    def _scroll_qdrant_memories(
        self,
        agent_id: Optional[str] = None,
        active_only: bool = False,
        scan_limit: Optional[int] = None,
        with_vectors: bool = False,
    ):
        """Yield normalized memory dicts from the Qdrant mem0 collection."""
        offset = None
        yielded = 0
        page_size = 500

        while True:
            if scan_limit is not None:
                remaining = scan_limit - yielded
                if remaining <= 0:
                    break
                page_size = min(500, remaining)

            points, next_offset = self.qdrant.scroll(
                collection_name="mem0",
                limit=page_size,
                offset=offset,
                with_payload=True,
                with_vectors=with_vectors,
            )

            for point in points:
                payload = point.payload or {}
                aid = payload.get("agent_id") or payload.get("user_id")
                if agent_id and aid != agent_id:
                    continue
                memory = {
                    "id": str(point.id),
                    "memory": payload.get("memory") or payload.get("data") or "",
                    "metadata": payload,
                    "_has_vector": bool(getattr(point, "vector", None)),
                }
                if active_only and not is_active(memory):
                    continue
                yield memory
                yielded += 1
                if scan_limit is not None and yielded >= scan_limit:
                    return

            if next_offset is None:
                break
            offset = next_offset

    @staticmethod
    def _extract_result_memory_id(result: dict) -> Optional[str]:
        """Best-effort extraction of the memory id from a Mem0 add result."""
        if not isinstance(result, dict):
            return None
        results_list = result.get("results", [])
        if results_list and isinstance(results_list[0], dict):
            return results_list[0].get("id")
        return None

    def _archive_superseded(self, memory_ids: list[str], superseded_by: str):
        """Archive memories replaced by a newer memory."""
        for memory_id in memory_ids:
            if not memory_id or memory_id == superseded_by:
                continue
            try:
                self.qdrant.set_payload(
                    collection_name="mem0",
                    payload=inactive_payload(
                        ARCHIVED,
                        superseded_by=superseded_by,
                    ),
                    points=[memory_id],
                )
                self.event_logger.log_event(
                    event_type="memory_archived",
                    agent_id="unknown",
                    memory_id=memory_id,
                    source="core._archive_superseded",
                    metadata={"superseded_by": superseded_by},
                )
            except Exception as e:
                logger.warning(f"Failed to archive superseded memory {memory_id}: {e}")

    def _increment_access_counts(self, memories: list[dict]):
        """Increment access_count metadata for retrieved memories."""
        for mem in memories:
            try:
                count = mem.get("metadata", {}).get("access_count", 0) + 1
                self.qdrant.set_payload(
                    collection_name="mem0",
                    payload={"access_count": count, "last_accessed_at": utc_now_iso()},
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
