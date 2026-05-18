"""Tests for the Mind Palace hook runner."""

from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import mind_palace_hook as hook  # noqa: E402


@pytest.fixture(autouse=True)
def disable_hook_logging(monkeypatch):
    monkeypatch.setattr(hook, "log_hook_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(hook, "log_hook_error", lambda *args, **kwargs: None)
    monkeypatch.setenv("MINDPALACE_RECORD_PAYLOAD_SCHEMAS", "false")
    monkeypatch.setenv("MINDPALACE_AUTOSTART_WORKER", "false")


class FakeMemory:
    def __init__(self, context: str = ""):
        self.context = context
        self.build_context_calls = []
        self.end_session_calls = []

    def build_context(self, **kwargs):
        self.build_context_calls.append(kwargs)
        return self.context

    def end_session(self, **kwargs):
        self.end_session_calls.append(kwargs)
        return [{"id": "stored"}]


def test_extracts_prompt_from_nested_payload():
    payload = {
        "hook_event_name": "UserPromptSubmit",
        "payload": {
            "messages": [
                {"role": "system", "content": "ignore"},
                {"role": "user", "text": "Please implement automatic memory recall."},
            ]
        },
    }

    assert hook.extract_event_name(payload) == "UserPromptSubmit"
    assert hook.extract_text(payload) == "Please implement automatic memory recall."


def test_event_can_come_from_environment(monkeypatch):
    monkeypatch.setenv("MINDPALACE_HOOK_EVENT", "UserPromptSubmit")
    fake = FakeMemory(context="## Relevant Memories\n- [durable_fact] Env event works")

    response = hook.handle_payload(
        {"prompt": "Please continue implementation without an event field."},
        memory_factory=lambda: fake,
    )

    assert "hookSpecificOutput" in response
    assert fake.build_context_calls


def test_user_prompt_submit_returns_additional_context(monkeypatch):
    monkeypatch.setenv("MINDPALACE_CODEX_AGENT_ID", "Test Agent")
    fake = FakeMemory(context="## Relevant Memories\n- [preference] User likes concise updates")

    response = hook.handle_payload(
        {
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Please continue the implementation work from the repo.",
        },
        memory_factory=lambda: fake,
    )

    assert "hookSpecificOutput" in response
    additional = response["hookSpecificOutput"]["additionalContext"]
    assert "Mind Palace retrieved" in additional
    assert "User likes concise updates" in additional
    assert fake.build_context_calls[0]["agent_id"] == "test-agent"


def test_user_prompt_submit_skips_trivial_prompt(monkeypatch):
    monkeypatch.delenv("MINDPALACE_CODEX_AGENT_ID", raising=False)
    fake = FakeMemory(context="should not be used")

    response = hook.handle_payload(
        {"hook_event_name": "UserPromptSubmit", "prompt": "ok"},
        memory_factory=lambda: fake,
    )

    assert response == {}
    assert fake.build_context_calls == []


def test_resolve_agent_id_prefers_hook_specific_env(monkeypatch):
    monkeypatch.setenv("MINDPALACE_CODEX_AGENT_ID", "Boop Agent")
    monkeypatch.setenv("MEM0_AGENT_ID", "agentforge")

    assert hook.resolve_agent_id({"cwd": "/tmp/other"}) == "boop-agent"


def test_resolve_agent_id_falls_back_to_cwd(monkeypatch):
    monkeypatch.delenv("MINDPALACE_CODEX_AGENT_ID", raising=False)
    monkeypatch.delenv("MINDPALACE_AGENT_ID", raising=False)
    monkeypatch.setenv("MEM0_AGENT_ID", "agentforge")

    assert hook.resolve_agent_id({"cwd": "/workspace/Mind Palace"}) == "mind-palace"


def test_resolve_agent_id_uses_project_agent_file(monkeypatch, tmp_path):
    monkeypatch.delenv("MINDPALACE_CODEX_AGENT_ID", raising=False)
    monkeypatch.delenv("MINDPALACE_AGENT_ID", raising=False)
    project = tmp_path / "worktree"
    nested = project / "src"
    nested.mkdir(parents=True)
    (project / ".mindpalace-agent").write_text("Shared Agent")

    assert hook.resolve_agent_id({"cwd": str(nested)}) == "shared-agent"


def test_resolve_agent_id_uses_project_registry(monkeypatch, tmp_path):
    monkeypatch.delenv("MINDPALACE_CODEX_AGENT_ID", raising=False)
    monkeypatch.delenv("MINDPALACE_AGENT_ID", raising=False)
    project = tmp_path / "boop-agent"
    nested = project / "feature"
    nested.mkdir(parents=True)
    registry = tmp_path / "registry.json"
    registry.write_text(f'{{"{project}": "boop-shared"}}')
    monkeypatch.setattr(hook, "PROJECT_REGISTRY_PATH", registry)
    monkeypatch.setattr(hook, "LEGACY_CLAUDE_REGISTRY_PATH", tmp_path / "missing.json")

    assert hook.resolve_agent_id({"cwd": str(nested)}) == "boop-shared"


def test_redacts_common_secrets():
    text = "token=sk-ant-abcdefghijklmnopqrstuvwxyz123456 and password=hunter2"

    redacted = hook.redact_sensitive_text(text)

    assert "sk-ant" not in redacted
    assert "hunter2" not in redacted
    assert "REDACTED" in redacted


def test_recall_cache_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(hook, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setenv("MINDPALACE_ENABLE_CACHE", "true")

    key = hook.recall_cache_key("agent", "prompt")
    hook.write_recall_cache(key, "cached context")

    assert hook.read_recall_cache(key) == "cached context"


def test_stop_signals_mode_queues_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("MINDPALACE_AGENT_ID", "Test Agent")
    monkeypatch.setenv("MINDPALACE_HOOK_WRITE_MODE", "signals")
    monkeypatch.setattr(hook, "QUEUE_DB_PATH", tmp_path / "queue.db")

    response = hook.handle_payload(
        {
            "hook_event_name": "Stop",
            "conversation": "User: remember I prefer pytest\nAssistant: noted",
        },
    )

    assert response == {}
    status = hook.queue_status()
    assert status["counts"]["pending"] == 1


def test_process_stop_queue(monkeypatch, tmp_path):
    monkeypatch.setattr(hook, "QUEUE_DB_PATH", tmp_path / "queue.db")
    fake = FakeMemory()
    hook.enqueue_stop_job(
        agent_id="test-agent",
        conversation="User: remember this durable thing",
        mode="signals",
        payload={"hook_event_name": "Stop"},
    )

    result = hook.process_stop_queue(limit=5, memory_factory=lambda: fake)

    assert result == {"processed": 1, "stored": 1, "failed": 0}
    assert fake.end_session_calls[0]["agent_id"] == "test-agent"
    assert hook.queue_status()["counts"]["done"] == 1


def test_stop_does_not_write_by_default(monkeypatch):
    monkeypatch.setenv("MINDPALACE_CODEX_AGENT_ID", "Test Agent")
    monkeypatch.delenv("MINDPALACE_CODEX_HOOK_WRITE_MODE", raising=False)
    fake = FakeMemory()

    response = hook.handle_payload(
        {
            "hook_event_name": "Stop",
            "conversation": "User: remember I prefer pytest\nAssistant: noted",
        },
        memory_factory=lambda: fake,
    )

    assert response == {}
    assert fake.end_session_calls == []


def test_stop_signals_mode_writes_when_signal_present(monkeypatch):
    monkeypatch.setenv("MINDPALACE_CODEX_AGENT_ID", "Test Agent")
    monkeypatch.setenv("MINDPALACE_CODEX_HOOK_WRITE_MODE", "signals")
    fake = FakeMemory()

    response = hook.handle_payload(
        {
            "hook_event_name": "Stop",
            "conversation": "User: remember I prefer pytest\nAssistant: noted",
        },
        memory_factory=lambda: fake,
    )

    assert response == {}
    assert fake.end_session_calls[0]["agent_id"] == "test-agent"
