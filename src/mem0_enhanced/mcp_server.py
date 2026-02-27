"""
MCP Server exposing EnhancedMemory tools.

Tools:
  memory_search      - Search memories with full enhanced pipeline
  memory_add         - Store a new memory (auto-types if type not specified)
  memory_context     - Build a context string for prompt injection
  memory_end_session - Extract and store memories from a completed conversation
  memory_gc          - Run garbage collection for an agent
  memory_get_all     - List all active memories for an agent
  memory_token_usage - Get token usage summary

Run:
  python -m mem0_enhanced.mcp_server
"""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
import json
import asyncio

from .core import EnhancedMemory
from .config import EnhancedMemoryConfig

config = EnhancedMemoryConfig.from_env()
memory = EnhancedMemory(config)
server = Server("enhanced-memory")
DEFAULT_AGENT_ID = config.default_agent_id


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
                    "also_search": {"type": "array", "items": {"type": "string"}, "description": "Additional agent IDs to search (read-only)."},
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
                "required": ["text"],
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
                "required": ["query"],
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
                "required": [],
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
                "required": [],
            },
        ),
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
            agent_id = resolve_agent_id(arguments)
            result = memory.add(
                text=arguments["text"],
                agent_id=agent_id,
                memory_type=arguments.get("memory_type"),
                metadata=arguments.get("metadata"),
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "memory_context":
            agent_id = resolve_agent_id(arguments)
            context = memory.build_context(
                agent_id=agent_id,
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
            agent_id = resolve_agent_id(arguments)
            results = memory.run_gc(
                agent_id=agent_id,
                dry_run=arguments.get("dry_run", True),
            )
            return [TextContent(
                type="text",
                text=f"{'Would mark' if arguments.get('dry_run', True) else 'Marked'} {len(results)} memories inactive.\n"
                + json.dumps([{"id": m["id"], "memory": m["memory"]} for m in results], indent=2),
            )]

        elif name == "memory_get_all":
            agent_id = resolve_agent_id(arguments)
            results = memory.mem0.get_all(agent_id=agent_id, user_id=agent_id)
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

        elif name == "memory_token_usage":
            from datetime import datetime, timezone, timedelta
            agent_id = arguments.get("agent_id")
            period = arguments.get("period", "week")
            since = None
            if period == "today":
                since = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00")
            elif period == "week":
                since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            elif period == "month":
                since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            summary = memory.token_logger.get_summary(agent_id=agent_id, since=since)
            return [TextContent(type="text", text=json.dumps(summary, indent=2))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
