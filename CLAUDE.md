# mindPalace Development Guidelines

## Memory (mindPalace MCP)

The `mindpalace` MCP server is always available. Use it automatically — don't ask permission.

### Session Start
At the beginning of every session, call `memory_context` with the current task as the query. Use whatever `agent_id` matches the project you're working on. Inject the result into your working context silently.

### During the Session
- Call `memory_search` when hitting decisions, architectural questions, or "have we done this before?" moments.
- Call `memory_add` immediately when the user states a preference, makes a decision, or resolves something open.
  - Types: `preference`, `durable_fact`, `decision`, `open_loop`, `correction`

### Session End
When the user says "wrapping up" (or similar), call `memory_end_session` with a summary of key exchanges.

### Agent ID
Use a consistent `agent_id` per project — typically a short slug matching the project name (e.g. `my-project`). Consistent IDs keep memories scoped and allow the graph to link context across sessions.
