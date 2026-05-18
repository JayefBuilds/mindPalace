#!/usr/bin/env python3
"""Run a local Mind Palace hook payload test."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import mind_palace_hook  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Exercise the Mind Palace hook locally.")
    parser.add_argument("--event", default="UserPromptSubmit", choices=["UserPromptSubmit", "Stop"])
    parser.add_argument("--cwd", default=str(Path.cwd()))
    parser.add_argument("--prompt", default="")
    parser.add_argument("--conversation", default="")
    parser.add_argument("--session-id", default="manual-test")
    parser.add_argument("--write-mode", choices=["off", "signals", "session"], default=None)
    parser.add_argument("--inline-stop", action="store_true", help="Process Stop extraction inline.")
    args = parser.parse_args()

    if args.write_mode:
        import os

        os.environ["MINDPALACE_HOOK_WRITE_MODE"] = args.write_mode
    if args.inline_stop:
        import os

        os.environ["MINDPALACE_HOOK_STOP_PROCESSING"] = "inline"

    payload = {
        "hook_event_name": args.event,
        "session_id": args.session_id,
        "cwd": args.cwd,
    }
    if args.event == "UserPromptSubmit":
        payload["prompt"] = args.prompt
    else:
        payload["conversation"] = args.conversation or args.prompt

    mind_palace_hook.load_dotenv(ROOT / ".env")
    response = mind_palace_hook.handle_payload(payload)
    print(json.dumps(response, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
