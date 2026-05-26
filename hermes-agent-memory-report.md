# hermes-agent Memory System Report

*Explored: 2026-05-26*

---

## Architecture

**Two-tier system:**
1. **Built-in `MemoryStore`** (`tools/memory_tool.py`) — file-backed, no external deps
2. **External Providers** — plugin interface (`MemoryProvider` ABC) supporting Honcho, Hindsight, Mem0, and others

**Orchestrated by `MemoryManager`** (`agent/memory_manager.py`) which routes tool calls and coordinates prefetch/sync.

---

## Data Model

Two parallel flat-file stores:

| Store | File | Char Limit | Contains |
|-------|------|------------|----------|
| Agent memory | `~/.hermes/memories/MEMORY.md` | 2,200 chars | Facts, conventions, tool quirks, lessons |
| User profile | `~/.hermes/memories/USER.md` | 1,375 chars | Name, role, preferences, habits |

Entries are multiline text blocks separated by `\n§\n`. No ID system — replace/remove use substring matching.

---

## Per-Turn Flow

1. **Session start** — load both files, freeze a snapshot for the system prompt
2. **Pre-turn prefetch** — `prefetch_all(query)` called with the user's message; built-in does substring match, external providers do semantic search
3. **Context injection** — prefetch results wrapped in `<memory-context>` fences, injected into the *user message* (not system prompt) to preserve prefix cache stability
4. **Tool loop** — `StreamingContextScrubber` strips fences from streaming output; prefetch cache reused across the entire tool loop
5. **Turn end** — `sync_all(user_msg, assistant_msg)` fires; external providers mirror writes to their backends

---

## Writes

The agent writes via the `memory()` tool (action: add/replace/remove). Writes go through:
- Injection/exfiltration threat scanning (regex + invisible unicode detection)
- File locking + atomic rename for concurrent-session safety
- External drift detection — if another session wrote content that wouldn't round-trip, the write is refused and a `.bak.<timestamp>` snapshot is created

---

## Scoping

| Scope | Mechanism |
|-------|-----------|
| Profile isolation | `~/.hermes/profiles/<name>/memories/` |
| Session tagging | UUID per conversation |
| Multi-user | `user_id` from gateway platform |
| Agent context | `"primary"` / `"subagent"` / `"cron"` — non-primary contexts skip writes |

Only one external provider can be registered at a time.

---

## Per-Turn Architecture Diagram

```
Turn Start
├─ on_turn_start() — lifecycle hook
└─ prefetch_all(query)
   ├─ Built-in: substring match (fast)
   └─ External: semantic search (async)
      Result: cached for entire tool loop

API Call Prep
├─ Wrap prefetch in <memory-context> fence
└─ Inject into user message (not system prompt)

Tool Loop
├─ StreamingContextScrubber strips fences
│  (prevents memory leaks in streaming)
└─ Cache reused (prefetch_all called once)

Turn End
├─ sync_all(user_msg, assistant_msg)
│  ├─ Built-in: write to MEMORY.md/USER.md
│  └─ External: send to provider backend
├─ queue_prefetch_all() for next turn
└─ on_memory_write() hook fired
```

---

## Key Files

| File | Role |
|------|------|
| `agent/memory_manager.py` | Orchestrator — registration, prefetch, sync, tool routing |
| `agent/memory_provider.py` | Plugin ABC defining the provider interface |
| `tools/memory_tool.py` | Built-in file store with char budgeting + injection scanning |
| `agent/system_prompt.py:277-286` | Snapshot injection into system prompt volatile tier |
| `agent/conversation_loop.py:654-659` | Pre-turn prefetch call |
| `agent/conversation_loop.py:830-839` | Context injection into user message |
| `agent/agent_init.py:1058-1143` | MemoryManager + MemoryStore initialization |
| `plugins/memory/` | External provider plugins (Honcho, Hindsight, Mem0, etc.) |

---

## External Provider Interface

Lifecycle hooks a provider must implement:

```python
initialize(session_id, **kwargs)
is_available() -> bool
system_prompt_block() -> str
prefetch(query, session_id) -> str
queue_prefetch(query, session_id) -> None
sync_turn(user_content, assistant_content, session_id) -> None
get_tool_schemas() -> List[Dict]
handle_tool_call(tool_name, args, **kwargs) -> str
shutdown() -> None
on_turn_start(turn_number, message, **kwargs)
on_session_end(messages)
on_session_switch(new_session_id, parent_session_id, reset, **kwargs)
on_pre_compress(messages) -> str
on_memory_write(action, target, content, metadata)
on_delegation(task, result, child_session_id, **kwargs)
```

---

## Notable Design Decisions

- **Prefix cache stability** — system prompt snapshot frozen at session load, never mutated mid-turn. Fresh per-turn context arrives via user message injection instead.
- **Character budgeting** — limits are in chars, not tokens, for model independence.
- **One external provider** — the manager blocks registration of a second non-builtin provider.
- **Streaming safety** — `StreamingContextScrubber` is a state machine that handles split `<memory-context>` tags across chunk boundaries, buffering partial tags and discarding unterminated spans.
