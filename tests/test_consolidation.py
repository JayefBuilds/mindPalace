"""Tests for memory consolidation."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from mem0_enhanced.config import EnhancedMemoryConfig
from mem0_enhanced.core import EnhancedMemory
from mem0_enhanced.llm import LLMResponse


def _make_memory() -> EnhancedMemory:
    config = EnhancedMemoryConfig(
        enable_graph=False,
        enable_reranker=False,
        enable_rewriter=False,
        enable_decay=False,
    )
    with patch("mem0_enhanced.core.Memory") as MockMemory:
        MockMemory.from_config.return_value = MagicMock()
        memory = EnhancedMemory(config=config)
    memory.event_logger.log_event = MagicMock()
    return memory


def _mem(memory_id: str, text: str, memory_type: str = "durable_fact"):
    return {
        "id": memory_id,
        "memory": text,
        "metadata": {
            "memory_type": memory_type,
            "access_count": 0,
            "lifecycle": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def _response(payload: dict):
    return LLMResponse(
        text=json.dumps(payload),
        input_tokens=10,
        output_tokens=10,
        provider="anthropic",
        model="test",
    )


def test_consolidation_skips_small_memory_sets():
    memory = _make_memory()
    memory.mem0.get_all.return_value = {"results": [_mem("1", "one")]}

    result = memory.run_consolidation("agent", dry_run=True)

    assert result["notes"] == "not enough memories to consolidate"
    assert result["proposals"] == []


def test_consolidation_dry_run_generates_but_does_not_apply():
    memory = _make_memory()
    memory.mem0.get_all.return_value = {"results": [_mem(str(i), f"memory {i}") for i in range(6)]}
    memory.llm.generate = MagicMock(side_effect=[
        _response({"proposals": [{"type": "prune", "memoryId": "1", "reason": "duplicate"}]}),
        _response({"challenges": [{"proposalIndex": 0, "objection": None, "severity": "low"}]}),
        _response({"decisions": [{"proposalIndex": 0, "approve": True, "rationale": "clean"}]}),
    ])
    memory.qdrant.set_payload = MagicMock()

    result = memory.run_consolidation("agent", dry_run=True)

    assert len(result["proposals"]) == 1
    assert len(result["decisions"]) == 1
    assert result["applied"] == []
    memory.qdrant.set_payload.assert_not_called()


def test_consolidation_execute_prunes_approved_memory():
    memory = _make_memory()
    memory.mem0.get_all.return_value = {"results": [_mem(str(i), f"memory {i}") for i in range(6)]}
    memory.llm.generate = MagicMock(side_effect=[
        _response({"proposals": [{"type": "prune", "memoryId": "1", "reason": "stale"}]}),
        _response({"challenges": [{"proposalIndex": 0, "objection": None, "severity": "low"}]}),
        _response({"decisions": [{"proposalIndex": 0, "approve": True, "rationale": "clean"}]}),
    ])
    memory.qdrant.set_payload = MagicMock()

    result = memory.run_consolidation("agent", dry_run=False)

    assert result["applied"] == [{"proposalIndex": 0, "type": "prune", "memory_id": "1"}]
    payload = memory.qdrant.set_payload.call_args[1]["payload"]
    assert payload["lifecycle"] == "pruned"
    assert payload["status"] == "inactive"
