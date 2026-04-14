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

## Quick Start

**Prerequisites:** Docker, Ollama running natively on macOS

```bash
# Pull the embedding model
ollama pull nomic-embed-text

# Start Qdrant + Neo4j + MCP server
cp .env.example .env   # add your ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN
docker compose up -d
```

**Quick test:**
```bash
python -c "from mem0_enhanced import EnhancedMemory"
```

## Agent ID Convention

All projects in the agentForge ecosystem use a single unified agent ID: **`agentforge`** (or a project-specific ID like `oto_build`, `yt-recon`). Set `MEM0_AGENT_ID` in your `.env` or per-session via the MCP `agent_id` parameter. Using consistent IDs means the graph can link memories across sessions.

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

The system wraps Mem0's API. Components:

| Module | Purpose |
|--------|---------|
| `config.py` | Configuration via environment variables |
| `core.py` | Main orchestrator — wires all components together |
| `mcp_server.py` | MCP server exposing tools to AI agents |
| `query_rewriter.py` | Expands vague queries before search |
| `reranker.py` | Local cross-encoder reranking |
| `decay.py` | Time-based decay + garbage collection |
| `session_extractor.py` | Auto-extracts memories from conversations |
| `auto_typer.py` | Classifies memories into typed categories |
| `token_logger.py` | SQLite-based token cost tracking |

**Infrastructure:**
| Service | Role |
|---------|------|
| Qdrant | Vector store — semantic similarity search |
| Neo4j | Graph store — entity/relationship traversal |
| Ollama | Local embeddings (`nomic-embed-text`) + reranker model |
| Anthropic Haiku | LLM for extraction, rewriting, typing |

**Patches** (`patches/mem0_anthropic_llm.py`): applied at build time to fix upstream mem0ai incompatibilities with the current Anthropic API (tool format, tool_choice dict, temperature+top_p conflict, tool_use response parsing).

---

## MCP Server Setup

Add to your Claude Code `.mcp.json` (or equivalent):

```json
{
  "mcpServers": {
    "memory": {
      "command": "python",
      "args": ["-m", "mem0_enhanced.mcp_server"],
      "env": {
        "MEM0_AGENT_ID": "my-project-name"
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

---

## Authentication

The LLM provider is Anthropic (Claude Haiku 4.5). Two auth options:

**Option A — API key** (pay-per-token, from [console.anthropic.com](https://console.anthropic.com)):
```bash
export ANTHROPIC_API_KEY=sk-ant-api03-...
```

**Option B — OAuth token** (uses your Claude.ai subscription, free of per-token charges):
```bash
claude setup-token   # run on any machine logged into Claude Code
export CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...
```

`CLAUDE_CODE_OAUTH_TOKEN` takes priority over `ANTHROPIC_API_KEY` if both are set.

---

## Configuration

Key environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MEM0_AGENT_ID` | — | Default agent/project ID (required for MCP) |
| `CLAUDE_CODE_OAUTH_TOKEN` | — | Claude.ai subscription OAuth token (preferred) |
| `ANTHROPIC_API_KEY` | — | Anthropic API key (fallback if no OAuth token) |
| `MEM0_LLM_PROVIDER` | `anthropic` | LLM provider: `anthropic` or `ollama` |
| `MEM0_LLM_MODEL` | `claude-haiku-4-5-20251001` | LLM model for all tasks |
| `MEM0_OLLAMA_URL` | `http://localhost:11434` | Ollama base URL |
| `MEM0_QDRANT_URL` | `http://localhost:6333` | Qdrant URL |
| `MEM0_NEO4J_URL` | `bolt://localhost:7687` | Neo4j bolt URL |
| `MEM0_NEO4J_PASSWORD` | `mem0graph` | Neo4j password |
| `MEM0_EMBEDDING_MODEL` | `nomic-embed-text` | Ollama embedding model |
| `MEM0_RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Cross-encoder model |
| `MEM0_ENABLE_GRAPH` | `true` | Enable Neo4j graph memory |
| `MEM0_ENABLE_RERANKER` | `true` | Enable reranking |
| `MEM0_ENABLE_REWRITER` | `true` | Enable query rewriting |
| `MEM0_ENABLE_DECAY` | `true` | Enable decay scoring |
| `MEM0_SEARCH_LIMIT` | `20` | Max memories before reranking |
| `MEM0_FINAL_LIMIT` | `5` | Max memories returned |
| `MEM0_DECAY_HALFLIFE_DAYS` | `60` | Half-life for decay |

---

## MCP vs CLI

mindPalace is intentionally MCP-only. Here's why.

**Token efficiency:** Marginal difference. The real token cost is in memory payloads — text sent and received — not the transport layer. MCP adds a small overhead for tool schemas in context, but that's negligible. The only place CLI wins is that you can discard the response (e.g. `memory_add` doesn't need to return anything into context) — with MCP, tool results always land in context. Not a meaningful enough reason to switch.

**Data safety:** Zero risk. Qdrant and Neo4j are the actual stores — fully independent of transport. Switching from MCP to CLI would touch nothing in either database.

**Why MCP is the right choice:** The killer feature is mid-conversation tool use. Claude can call `memory_search` inline while reasoning, then call `memory_add` immediately after a decision is made — without you lifting a finger. A CLI would require external orchestration to decide *when* to call memory, pipe the transcript somewhere, and inject results back in. You'd lose the seamless, autonomous loop that makes this actually useful.

---

## Running Tests

```bash
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
python scripts/gc.py <agent_id> --execute    # Actually mark inactive
```

Intended for cron (see `cron/mem0-gc.cron` for examples).

---

## Mac Mini Deployment

The entire stack runs in Docker, making it easy to move to a Mac Mini or any other machine.

### 1. Install prerequisites on the Mac Mini

```bash
# Docker Desktop
brew install --cask docker

# Ollama (runs natively for Apple Silicon GPU access)
brew install ollama
ollama pull nomic-embed-text
ollama serve
```

### 2. Copy the project

```bash
# On your Mac Mini — clone the repo or copy just these two files:
git clone <your-repo-url>
cd memory
```

### 3. Create your .env file

```bash
cp .env.example .env
# Edit .env and set CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY
```

Generate a fresh OAuth token on any machine with Claude Code:

```bash
claude setup-token
# Copy the sk-ant-oat01-... value into .env
```

### 4. Start the stack

```bash
docker compose up -d
```

That's it. Qdrant, Neo4j, and the MCP server all start automatically.

### 5. Point Claude Code at the Mac Mini

In your `.mcp.json` on your laptop, change the MCP server to connect over the network instead of running locally. Expose the Mac Mini via **Tailscale** for secure remote access:

```json
{
  "mcpServers": {
    "memory": {
      "command": "ssh",
      "args": ["mac-mini", "docker exec -i memory-mcp-1 python -m mem0_enhanced.mcp_server"],
      "env": {
        "MEM0_AGENT_ID": "my-project"
      }
    }
  }
}
```

Or bind the MCP container to a port and connect directly if you prefer TCP.

### Multi-device access

To expose Qdrant/Neo4j to other devices (e.g. for direct access via Tailscale), change the port bindings in `docker-compose.yml` from `127.0.0.1:PORT:PORT` to `0.0.0.0:PORT:PORT`. Only do this on a trusted network or behind Tailscale.
