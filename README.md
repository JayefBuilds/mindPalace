# mindPalace

Persistent memory backend for AI agents. Built on [Mem0](https://github.com/mem0ai/mem0) with a full retrieval pipeline and Neo4j graph layer.

**How it works:** memories are stored as vectors (Qdrant, embedded locally via Ollama) and as a knowledge graph (Neo4j). On retrieval, both are queried and merged — vector search finds semantically similar memories, graph traversal finds *related* memories via entity relationships. A local cross-encoder reranks the combined results.

**Cost:** embeddings and reranking are 100% local. The only API spend is Haiku for memory extraction/rewriting — roughly $0.01–0.05 per session.

Features:
- **Graph memory** — Neo4j entity/relationship extraction on every memory add
- **Query rewriting** — expands vague queries before search
- **Cross-encoder reranking** — local model rescores results by true relevance
- **Memory typing** — classifies as `preference`, `durable_fact`, `decision`, `open_loop`, `correction`
- **Decay scoring** — time-based relevance decay with garbage collection
- **Session extraction** — auto-extracts memories from completed conversations
- **Token logging** — SQLite-based cost tracking

---

## Prerequisites

**Required — install before anything else:**

| Dependency | Purpose | Install |
|------------|---------|---------|
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | Runs Qdrant, Neo4j, and the MCP server | `brew install --cask docker` |
| [Ollama](https://ollama.com) | Local embeddings (runs natively on macOS for Apple Silicon GPU) | `brew install ollama` |
| `nomic-embed-text` | Embedding model used for vector search | `ollama pull nomic-embed-text` |
| Anthropic API key | Powers memory extraction, query rewriting, and typing (Claude Haiku) | [console.anthropic.com](https://console.anthropic.com) |

**Optional:**
- Claude Code with `claude setup-token` — lets you use your Claude.ai subscription instead of a paid API key

---

## Quick Start

```bash
# 1. Make sure Ollama is running with the embedding model
ollama serve
ollama pull nomic-embed-text

# 2. Configure your environment
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY and MEM0_AGENT_ID at minimum

# 3. Start the stack (Qdrant + Neo4j + MCP server)
docker compose up -d
```

**Verify it's working:**
```bash
python -c "from mem0_enhanced import EnhancedMemory; print('OK')"
```

---

## Authentication

Two options for the Anthropic LLM:

**Option A — API key** (pay-per-token, from [console.anthropic.com](https://console.anthropic.com)):
```bash
export ANTHROPIC_API_KEY=sk-ant-api03-...
```

**Option B — OAuth token** (uses your Claude.ai subscription, no per-token charges):
```bash
claude setup-token   # run on any machine logged into Claude Code
export CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...
```

> **Note:** It's unclear whether using a Claude.ai OAuth token for programmatic/agent use is permitted under Anthropic's Terms of Service. Use at your own discretion — Option A (API key) is the safe choice.

`ANTHROPIC_API_KEY` takes priority over `CLAUDE_CODE_OAUTH_TOKEN` if both are set.

---

## MCP Server Setup

Add to your Claude Code `.mcp.json`:

```json
{
  "mcpServers": {
    "mindpalace": {
      "command": "docker",
      "args": ["exec", "-i", "mindpalace-mcp-1", "python", "-m", "mem0_enhanced.mcp_server"],
      "env": {
        "MEM0_AGENT_ID": "my-project"
      }
    }
  }
}
```

---

## Available MCP Tools

| Tool | Description |
|------|-------------|
| `memory_search` | Search memories with full pipeline (rewrite, rerank, decay) |
| `memory_add` | Store a new memory (auto-types if type not specified) |
| `memory_context` | Build a formatted context block for prompt injection |
| `memory_end_session` | Extract and store memories from a completed conversation |
| `memory_gc` | Run garbage collection (dry run or execute) |
| `memory_get_all` | List all active memories for an agent |
| `memory_token_usage` | Get token usage summary by period |
| `memory_list_agents` | List all agent IDs in the store with memory counts |
| `memory_rename_agent` | Rename an agent ID, migrating all its memories |

---

## Retrieval Pipeline

```
query
  → rewriter (Haiku)        # expand vague queries
  → embedder (Ollama)       # local vector embedding
  → Qdrant search           # semantic similarity
  → Neo4j graph traversal   # entity relationship traversal
  → merge + dedup
  → reranker (local)        # cross-encoder rescoring
  → top N results
```

---

## Architecture

| Module | Purpose |
|--------|---------|
| `config.py` | Configuration via environment variables |
| `core.py` | Main orchestrator — wires all components together |
| `mcp_server.py` | MCP server exposing tools to AI agents |
| `bridge_cli.py` | JSON bridge for programmatic/TypeScript integration |
| `query_rewriter.py` | Expands vague queries before search |
| `reranker.py` | Local cross-encoder reranking |
| `decay.py` | Time-based decay + garbage collection |
| `session_extractor.py` | Auto-extracts memories from conversations |
| `auto_typer.py` | Classifies memories into typed categories |
| `graph_extractor.py` | Custom Neo4j extraction (works with OAuth + API key) |
| `token_logger.py` | SQLite-based token cost tracking |

**Infrastructure:**

| Service | Role |
|---------|------|
| Qdrant | Vector store — semantic similarity search |
| Neo4j | Graph store — entity/relationship traversal |
| Ollama | Local embeddings (`nomic-embed-text`) + reranker model |
| Anthropic Haiku | LLM for extraction, rewriting, typing |

**Patches** (`patches/mem0_anthropic_llm.py`): applied at Docker build time to fix upstream mem0ai incompatibilities with the current Anthropic API (tool format, tool_choice dict, temperature+top_p conflict, tool_use response parsing).

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MEM0_AGENT_ID` | — | Default agent/project ID (required) |
| `ANTHROPIC_API_KEY` | — | Anthropic API key (priority auth) |
| `CLAUDE_CODE_OAUTH_TOKEN` | — | Claude.ai subscription OAuth token (fallback) |
| `MEM0_LLM_PROVIDER` | `anthropic` | LLM provider: `anthropic` or `ollama` |
| `MEM0_LLM_MODEL` | `claude-haiku-4-5-20251001` | LLM model for all tasks |
| `MEM0_OLLAMA_URL` | `http://localhost:11434` | Ollama base URL |
| `MEM0_QDRANT_URL` | `http://localhost:6333` | Qdrant URL |
| `MEM0_NEO4J_URL` | `bolt://localhost:7687` | Neo4j bolt URL |
| `MEM0_NEO4J_PASSWORD` | `mem0graph` | Neo4j password |
| `MEM0_EMBEDDING_MODEL` | `nomic-embed-text` | Ollama embedding model |
| `MEM0_RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Cross-encoder reranker model |
| `MEM0_ENABLE_GRAPH` | `false` | Enable Neo4j graph memory |
| `MEM0_ENABLE_RERANKER` | `true` | Enable reranking |
| `MEM0_ENABLE_REWRITER` | `true` | Enable query rewriting |
| `MEM0_ENABLE_DECAY` | `true` | Enable decay scoring |
| `MEM0_SEARCH_LIMIT` | `20` | Max memories fetched before reranking |
| `MEM0_FINAL_LIMIT` | `5` | Max memories returned |
| `MEM0_DECAY_HALFLIFE_DAYS` | `60` | Half-life for decay scoring |

---

## MCP vs CLI

mindPalace is intentionally MCP-only. Here's why.

**Token efficiency:** Marginal difference. The real token cost is in memory payloads — text sent and received — not the transport layer. MCP adds a small overhead for tool schemas in context, but that's negligible.

**Why MCP is the right choice:** The killer feature is mid-conversation tool use. Claude can call `memory_search` inline while reasoning, then call `memory_add` immediately after a decision is made — without external orchestration. A CLI would require you to decide *when* to call memory, pipe the transcript somewhere, and inject results back in. You'd lose the seamless, autonomous loop.

---

## Running Tests

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```

---

## Token Reports

```bash
python scripts/token_report.py --today
python scripts/token_report.py --agent my-project --week
python scripts/token_report.py --since 2026-02-01 --json-output
```

---

## Garbage Collection

```bash
python scripts/gc.py <agent_id>              # Dry run
python scripts/gc.py <agent_id> --execute    # Mark stale memories inactive
```

Intended for cron — see `cron/mem0-gc.cron` for examples.

---

## Mac Mini / Remote Deployment

The entire stack runs in Docker, making it easy to move to a dedicated machine.

### 1. Install prerequisites

```bash
brew install --cask docker
brew install ollama
ollama pull nomic-embed-text
ollama serve
```

### 2. Clone and configure

```bash
git clone https://github.com/JayefBuild/mindPalace.git
cd mindPalace
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY and MEM0_AGENT_ID
```

### 3. Start the stack

```bash
docker compose up -d
```

### 4. Point Claude Code at the remote machine

Use [Tailscale](https://tailscale.com) for secure access, then in your laptop's `.mcp.json`:

```json
{
  "mcpServers": {
    "mindpalace": {
      "command": "ssh",
      "args": ["mac-mini", "docker exec -i mindpalace-mcp-1 python -m mem0_enhanced.mcp_server"],
      "env": {
        "MEM0_AGENT_ID": "my-project"
      }
    }
  }
}
```

### Multi-device access

To expose Qdrant/Neo4j to other devices on the network, change port bindings in `docker-compose.yml` from `127.0.0.1:PORT:PORT` to `0.0.0.0:PORT:PORT`. Only do this on a trusted network or behind Tailscale.
