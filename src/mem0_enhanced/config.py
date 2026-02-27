"""
Configuration for EnhancedMemory.

Environment variables:
  MEM0_AGENT_ID              - Default agent/project ID (no default — set per project)
  MEM0_OLLAMA_URL          - Ollama base URL (default: http://localhost:11434)
  MEM0_QDRANT_URL          - Qdrant URL (default: http://localhost:6333)
  MEM0_NEO4J_URL           - Neo4j bolt URL (default: bolt://localhost:7687)
  MEM0_NEO4J_PASSWORD      - Neo4j password (default: mem0graph)
  MEM0_LLM_PROVIDER        - LLM provider: "anthropic" or "ollama" (default: anthropic)
  MEM0_LLM_MODEL           - LLM model for all tasks (default: claude-haiku-4-5-20251001)
  MEM0_EMBEDDING_MODEL     - Ollama embedding model (default: nomic-embed-text)
  MEM0_RERANKER_MODEL      - Cross-encoder model name (default: cross-encoder/ms-marco-MiniLM-L-6-v2)
  MEM0_ENABLE_GRAPH        - Enable graph memory (default: true)
  MEM0_ENABLE_RERANKER     - Enable reranking (default: true)
  MEM0_ENABLE_REWRITER     - Enable query rewriting (default: true)
  MEM0_ENABLE_DECAY        - Enable decay scoring (default: true)
  MEM0_SEARCH_LIMIT        - Max memories per search before reranking (default: 20)
  MEM0_FINAL_LIMIT         - Max memories returned after reranking (default: 5)
  MEM0_DECAY_HALFLIFE_DAYS - Half-life for decay in days (default: 60)
  ANTHROPIC_API_KEY        - Anthropic API key (required if llm_provider is anthropic and no OAuth token set)
  CLAUDE_CODE_OAUTH_TOKEN  - OAuth token from `claude setup-token` (uses Claude.ai subscription instead of API credits)
"""

from dataclasses import dataclass
from typing import Optional
import os


@dataclass
class EnhancedMemoryConfig:
    # Project identity
    default_agent_id: Optional[str] = None

    # Infrastructure
    ollama_url: str = "http://localhost:11434"
    qdrant_url: str = "http://localhost:6333"
    neo4j_url: str = "bolt://localhost:7687"
    neo4j_password: str = "mem0graph"

    # LLM provider ("anthropic" or "ollama")
    llm_provider: str = "anthropic"
    llm_model: str = "claude-haiku-4-5-20251001"

    # Embeddings always run on Ollama (local, free, must stay consistent)
    embedding_model: str = "nomic-embed-text"

    # Reranker
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # Feature flags
    enable_graph: bool = True
    enable_reranker: bool = True
    enable_rewriter: bool = True
    enable_decay: bool = True

    # Search tuning
    search_limit: int = 20
    final_limit: int = 5
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
            llm_provider=os.getenv("MEM0_LLM_PROVIDER", cls.llm_provider),
            llm_model=os.getenv("MEM0_LLM_MODEL", cls.llm_model),
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
        if self.llm_provider == "anthropic":
            llm_config = {
                "provider": "anthropic",
                "config": {
                    "model": self.llm_model,
                    "temperature": 0.1,
                    "max_tokens": 2000,
                },
            }
        else:
            llm_config = {
                "provider": "ollama",
                "config": {
                    "model": self.llm_model,
                    "ollama_base_url": self.ollama_url,
                },
            }

        config = {
            "llm": llm_config,
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
                    "embedding_model_dims": 768,
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
