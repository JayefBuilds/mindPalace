#!/usr/bin/env python3
"""Install Mind Palace hooks into local Codex and Claude Code settings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "bin" / "python"
HOOK_SCRIPT = ROOT / "scripts" / "mind_palace_hook.py"
CODEX_HOOKS = Path("~/.codex/hooks.json").expanduser()
CLAUDE_SETTINGS = Path("~/.claude/settings.json").expanduser()


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Mind Palace hooks.")
    parser.add_argument("--codex", action="store_true", help="Install Codex hooks.")
    parser.add_argument("--claude", action="store_true", help="Install Claude Code hooks.")
    parser.add_argument("--all", action="store_true", help="Install both Codex and Claude Code hooks.")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing.")
    args = parser.parse_args()

    install_codex = args.all or args.codex or not (args.codex or args.claude)
    install_claude = args.all or args.claude or not (args.codex or args.claude)

    results = {}
    if install_codex:
        results["codex"] = install_codex_hooks(dry_run=args.dry_run)
    if install_claude:
        results["claude"] = install_claude_hooks(dry_run=args.dry_run)

    print(json.dumps(results, indent=2))
    return 0


def install_codex_hooks(dry_run: bool = False) -> dict:
    data = read_json(CODEX_HOOKS, default={"hooks": {}})
    hooks = data.setdefault("hooks", {})
    user_command = f"MINDPALACE_HOOK_EVENT=UserPromptSubmit {PYTHON} {HOOK_SCRIPT}"
    stop_command = f"MINDPALACE_HOOK_EVENT=Stop MINDPALACE_HOOK_WRITE_MODE=signals {PYTHON} {HOOK_SCRIPT}"

    changed = False
    changed |= remove_obsolete_commands(hooks)
    changed |= ensure_hook_command(hooks, "UserPromptSubmit", user_command)
    changed |= ensure_hook_command(hooks, "Stop", stop_command)

    if changed and not dry_run:
        write_json(CODEX_HOOKS, data)
    return {"path": str(CODEX_HOOKS), "changed": changed, "dry_run": dry_run}


def install_claude_hooks(dry_run: bool = False) -> dict:
    data = read_json(CLAUDE_SETTINGS, default={})
    hooks = data.setdefault("hooks", {})
    user_command = f"MINDPALACE_HOOK_EVENT=UserPromptSubmit {PYTHON} {HOOK_SCRIPT}"
    stop_command = f"MINDPALACE_HOOK_EVENT=Stop MINDPALACE_HOOK_WRITE_MODE=signals {PYTHON} {HOOK_SCRIPT}"

    changed = False
    changed |= remove_obsolete_commands(hooks)
    changed |= ensure_hook_command(hooks, "UserPromptSubmit", user_command)
    changed |= ensure_hook_command(hooks, "Stop", stop_command)

    if changed and not dry_run:
        write_json(CLAUDE_SETTINGS, data)
    return {"path": str(CLAUDE_SETTINGS), "changed": changed, "dry_run": dry_run}


def ensure_hook_command(hooks: dict, event: str, command: str) -> bool:
    entries = hooks.setdefault(event, [])
    if command_exists(entries, command):
        return False
    entries.append({"hooks": [{"type": "command", "command": command}]})
    return True


def remove_obsolete_commands(hooks: dict) -> bool:
    changed = False
    obsolete = ("codex_memory_hook.py", "mindpalace_inject.py")
    for event, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        kept = [entry for entry in entries if not entry_contains_obsolete_command(entry, obsolete)]
        if len(kept) != len(entries):
            hooks[event] = kept
            changed = True
    return changed


def entry_contains_obsolete_command(value, obsolete: tuple[str, ...]) -> bool:
    if isinstance(value, dict):
        command = value.get("command")
        if isinstance(command, str) and any(item in command for item in obsolete):
            return True
        return any(entry_contains_obsolete_command(item, obsolete) for item in value.values())
    if isinstance(value, list):
        return any(entry_contains_obsolete_command(item, obsolete) for item in value)
    return False


def command_exists(value, command: str) -> bool:
    if isinstance(value, dict):
        if value.get("command") == command:
            return True
        return any(command_exists(item, command) for item in value.values())
    if isinstance(value, list):
        return any(command_exists(item, command) for item in value)
    return False


def read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
