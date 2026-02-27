# mem0_enhanced

Enhanced memory orchestration layer on top of [Mem0](https://github.com/mem0ai/mem0). Wraps Mem0's API without modifying it, adding:

- **Query rewriting** — Expands vague queries using a local LLM
- **Cross-encoder reranking** — Improves search precision
- **Decay / forgetfulness** — Time-based scoring and garbage collection
- **Automatic session extraction** — Extracts memories from completed conversations
- **Memory typing** — Classifies memories (preference, durable_fact, decision, open_loop, correction)
- **Garbage collection** — Marks stale, low-access memories inactive
- **Token logging** — SQLite-based token tracking for cost visibility

---

## Quick Start

**Prerequisites:** Docker, Python 3.10+

```bash
docker compose up -d
pip install -e .
```

This brings up Qdrant and Neo4j. Ollama must be running natively on macOS for Apple Silicon GPU access.

**Quick test:**
```bash
python -c "from mem0_enhanced import EnhancedMemory"
```

---

## Architecture

The system wraps Mem0's API. Components:

| Module | Purpose |
|--------|---------|
| `config.py` | Configuration via environment variables |
| `query_rewriter.py` | Expands vague queries using local LLM |
| `reranker.py` | Cross-encoder reranking for precision |
| `decay.py` | Time-based decay + garbage collection |
| `session_extractor.py` | Auto-extracts memories from conversations |
| `auto_typer.py` | Classifies memories into types |
| `token_logger.py` | SQLite-based token tracking |
| `core.py` | Main orchestrator wiring everything together |
| `mcp_server.py` | MCP server exposing tools to AI agents |

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
