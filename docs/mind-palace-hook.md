# Mind Palace Hook

Mind Palace Hook is the shared automatic-memory hook for Codex and Claude Code.

## Installed Hooks

Global Codex config: `~/.codex/hooks.json`

- `UserPromptSubmit`: runs `scripts/mind_palace_hook.py` and injects relevant memories as `additionalContext`.
- `Stop`: runs the same hook with `MINDPALACE_HOOK_WRITE_MODE=signals`.

Global Claude Code config: `~/.claude/settings.json`

- `UserPromptSubmit`: runs `scripts/mind_palace_hook.py`.
- `Stop`: runs the same hook with `MINDPALACE_HOOK_WRITE_MODE=signals`.

Existing Orca hooks remain installed. Mind Palace Hook is an additional command, not a replacement.

## Runtime Behavior

On each meaningful prompt, the hook:

1. Reads the agent hook payload from stdin.
2. Infers a project-scoped agent ID.
3. Redacts obvious secrets from the prompt.
4. Checks the short-lived recall cache.
5. Searches Mind Palace with a cheap recall profile.
6. Returns context through `hookSpecificOutput.additionalContext`.

Trivial prompts such as `ok`, `thanks`, and very short replies are skipped.

## Project Identity

Agent ID resolution order:

1. `MINDPALACE_AGENT_ID`
2. `MINDPALACE_HOOK_AGENT_ID`
3. `MINDPALACE_CODEX_AGENT_ID`
4. `.mindpalace-agent` in the current workspace or a parent directory
5. Registry match from `~/.mem0/mind_palace_projects.json`
6. Legacy Claude registry match from `~/.claude/hooks/user_prompt_submit/registry.json`
7. Current workspace folder name
8. `MEM0_AGENT_ID`

Registry files are JSON objects:

```json
{
  "/path/to/boop-agent": "boop-agent"
}
```

## Stop Writes

The installed Stop hooks use `signals` mode. That means the hook only captures a Stop job when the conversation contains durable-memory language such as `remember`, `I prefer`, `we decided`, `todo`, or `correction`.

Stop jobs are queued by default in `~/.mem0/mind_palace_hook_queue.db`; extraction does not block the agent hook. Process queued jobs with:

```sh
.venv/bin/python scripts/process_mind_palace_hook_queue.py --limit 10
```

By default, the Stop hook also starts that worker in the background after queueing a job. Disable that with:

```sh
MINDPALACE_AUTOSTART_WORKER=false
```

For synchronous testing only:

```sh
MINDPALACE_HOOK_STOP_PROCESSING=inline .venv/bin/python scripts/mind_palace_hook.py
```

## Utilities

Install or repair hook config:

```sh
.venv/bin/python scripts/install_mind_palace_hooks.py --all
```

Show hook status, active commands, queue counts, cache path, and schema log path:

```sh
.venv/bin/python scripts/mind_palace_hook_status.py
```

Run a local recall test:

```sh
.venv/bin/python scripts/test_mind_palace_hook.py \
  --event UserPromptSubmit \
  --cwd /path/to/boop-agent \
  --prompt "Continue the implementation work."
```

Run a local Stop queue test:

```sh
.venv/bin/python scripts/test_mind_palace_hook.py \
  --event Stop \
  --write-mode signals \
  --conversation "User: remember I prefer pytest for this repo"
```

## Cost Controls

Hook recall defaults are intentionally cheaper than the MCP server:

- `MINDPALACE_ENABLE_REWRITER=false`
- `MINDPALACE_ENABLE_RERANKER=false`
- `MINDPALACE_ENABLE_GRAPH=false`
- `MINDPALACE_ENABLE_DECAY=true`

Recall cache defaults:

- `MINDPALACE_ENABLE_CACHE=true`
- `MINDPALACE_CACHE_TTL_SECONDS=90`

Queue worker defaults:

- `MINDPALACE_AUTOSTART_WORKER=true`
- `MINDPALACE_WORKER_LIMIT=5`

Payload schema logging defaults to on and records only field names/types, not values:

- `MINDPALACE_RECORD_PAYLOAD_SCHEMAS=true`
- `MINDPALACE_HOOK_SCHEMA_LOG=~/.mem0/mind_palace_payload_schemas.jsonl`

## Privacy

Before recall or queued extraction, the hook redacts common token/password patterns and truncates large conversations. Tune with:

- `MINDPALACE_MAX_PROMPT_CHARS=6000`
- `MINDPALACE_MAX_CONVERSATION_CHARS=12000`

The hook suppresses third-party stdout and stderr during memory calls so Codex and Claude Code receive only hook protocol JSON.

The older `MINDPALACE_CODEX_*` variables are still supported for backward compatibility.
