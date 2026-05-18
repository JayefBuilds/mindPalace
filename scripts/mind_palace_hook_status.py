#!/usr/bin/env python3
"""Show installed Mind Palace hook status for Codex and Claude Code."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = ROOT / "scripts" / "mind_palace_hook.py"
CODEX_HOOKS = Path("~/.codex/hooks.json").expanduser()
CLAUDE_SETTINGS = Path("~/.claude/settings.json").expanduser()

sys.path.insert(0, str(ROOT / "scripts"))

import mind_palace_hook  # noqa: E402


def main() -> int:
    status = {
        "hook_script": str(HOOK_SCRIPT),
        "hook_script_exists": HOOK_SCRIPT.exists(),
        "codex": config_status(CODEX_HOOKS),
        "claude": config_status(CLAUDE_SETTINGS),
        "queue": mind_palace_hook.queue_status(),
        "cache": {
            "path": str(mind_palace_hook.CACHE_PATH),
            "exists": mind_palace_hook.CACHE_PATH.exists(),
        },
        "schema_log": {
            "path": str(mind_palace_hook.SCHEMA_LOG_PATH),
            "exists": mind_palace_hook.SCHEMA_LOG_PATH.exists(),
        },
    }
    print(json.dumps(status, indent=2))
    return 0


def config_status(path: Path) -> dict:
    if not path.exists():
        return {"path": str(path), "exists": False, "installed": False, "commands": []}
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        return {"path": str(path), "exists": True, "installed": False, "error": str(exc)}

    commands = [
        command for command in extract_commands(data)
        if "mind_palace_hook.py" in command
    ]
    obsolete = [
        command for command in extract_commands(data)
        if "codex_memory_hook.py" in command or "mindpalace_inject.py" in command
    ]
    return {
        "path": str(path),
        "exists": True,
        "installed": bool(commands),
        "commands": commands,
        "obsolete_commands": obsolete,
    }


def extract_commands(value) -> list[str]:
    commands = []
    if isinstance(value, dict):
        command = value.get("command")
        if isinstance(command, str):
            commands.append(command)
        for item in value.values():
            commands.extend(extract_commands(item))
    elif isinstance(value, list):
        for item in value:
            commands.extend(extract_commands(item))
    return commands


if __name__ == "__main__":
    raise SystemExit(main())
