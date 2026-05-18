"""Memory consolidation: propose, review, judge, and apply cleanup actions."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from qdrant_client.models import PointVectors

from .lifecycle import PRUNED, inactive_payload, is_active

logger = logging.getLogger(__name__)


PROPOSER_PROMPT = """You are a memory-consolidation proposer.

Given active memories for one agent, find conservative cleanup proposals:
- merge: duplicate facts should become one clearer memory
- supersede: a newer/correction memory replaces older conflicting memories
- prune: a memory is redundant, stale, or clearly wrong

Return STRICT JSON only:
{"proposals":[
  {"type":"merge","keep":"memory-id","absorb":["memory-id"],"rewriteContent":"single clear sentence"},
  {"type":"supersede","newer":"memory-id","older":["memory-id"]},
  {"type":"prune","memoryId":"memory-id","reason":"short reason"}
]}

Rules:
- Be conservative. Similar but distinct facts stay separate.
- Never merge corrections into non-corrections.
- Prefer supersede for explicit corrections.
- If no changes are needed, return {"proposals":[]}.
"""

ADVERSARY_PROMPT = """You are a memory-consolidation adversary.

Review each proposal for possible information loss, over-aggressive pruning,
bad supersession, or conflating distinct facts.

Return STRICT JSON only:
{"challenges":[
  {"proposalIndex":0,"objection":"reason or null","severity":"low|medium|high"}
]}

Include one challenge object per proposal. Use null objection for clean proposals.
"""

JUDGE_PROMPT = """You are a memory-consolidation judge.

Approve or reject each proposal after weighing the adversary objections.

Return STRICT JSON only:
{"decisions":[
  {"proposalIndex":0,"approve":true,"rationale":"short rationale"}
]}

Reject proposals with likely information loss. Approve clean conservative proposals.
"""


@dataclass
class ConsolidationResult:
    agent_id: str
    dry_run: bool
    memories_scanned: int
    proposals: list[dict[str, Any]]
    challenges: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    applied: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "dry_run": self.dry_run,
            "memories_scanned": self.memories_scanned,
            "proposals": self.proposals,
            "challenges": self.challenges,
            "decisions": self.decisions,
            "applied": self.applied,
            "errors": self.errors,
            "notes": self.notes,
        }


class MemoryConsolidator:
    def __init__(self, memory):
        self.memory = memory

    def run(
        self,
        agent_id: str,
        dry_run: bool = True,
        max_memories: int = 150,
        min_memories: int = 6,
    ) -> ConsolidationResult:
        memories = self._load_active(agent_id, max_memories)
        if len(memories) < min_memories:
            result = ConsolidationResult(
                agent_id=agent_id,
                dry_run=dry_run,
                memories_scanned=len(memories),
                proposals=[],
                challenges=[],
                decisions=[],
                applied=[],
                errors=[],
                notes="not enough memories to consolidate",
            )
            self._log(result)
            return result

        payload = self._format_memories(memories)
        proposals_json = self._call_json(PROPOSER_PROMPT, payload, agent_id, "consolidation_proposer")
        proposals = proposals_json.get("proposals", [])
        if not proposals:
            result = ConsolidationResult(
                agent_id=agent_id,
                dry_run=dry_run,
                memories_scanned=len(memories),
                proposals=[],
                challenges=[],
                decisions=[],
                applied=[],
                errors=[],
                notes="no proposals",
            )
            self._log(result)
            return result

        proposals_block = "\n".join(
            f"#{i}: {json.dumps(p, sort_keys=True)}" for i, p in enumerate(proposals)
        )
        adversary_payload = f"Proposals:\n{proposals_block}\n\nMemories:\n{payload}"
        challenges_json = self._call_json(
            ADVERSARY_PROMPT,
            adversary_payload,
            agent_id,
            "consolidation_adversary",
        )
        challenges = challenges_json.get("challenges", [])

        judge_payload = (
            f"Proposals:\n{proposals_block}\n\n"
            f"Adversary challenges:\n{json.dumps(challenges, indent=2)}\n\n"
            f"Memories:\n{payload}"
        )
        decisions_json = self._call_json(JUDGE_PROMPT, judge_payload, agent_id, "consolidation_judge")
        decisions = decisions_json.get("decisions", [])

        approved = {
            d.get("proposalIndex")
            for d in decisions
            if isinstance(d, dict) and d.get("approve") is True
        }
        applied: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        by_id = {m["id"]: m for m in memories}

        if not dry_run:
            for idx, proposal in enumerate(proposals):
                if idx not in approved:
                    continue
                try:
                    applied_item = self._apply(proposal, by_id)
                    if applied_item:
                        applied.append({"proposalIndex": idx, **applied_item})
                except Exception as e:
                    logger.warning("Consolidation apply failed: %s", e)
                    errors.append({"proposalIndex": idx, "error": str(e), "proposal": proposal})

        result = ConsolidationResult(
            agent_id=agent_id,
            dry_run=dry_run,
            memories_scanned=len(memories),
            proposals=proposals,
            challenges=challenges,
            decisions=decisions,
            applied=applied,
            errors=errors,
        )
        self._log(result)
        return result

    def _load_active(self, agent_id: str, max_memories: int) -> list[dict[str, Any]]:
        raw = self.memory.mem0.get_all(filters={"agent_id": agent_id, "user_id": agent_id})
        active = [m for m in raw.get("results", []) if is_active(m)]
        return active[:max_memories]

    def _format_memories(self, memories: list[dict[str, Any]]) -> str:
        lines = []
        for mem in memories:
            meta = mem.get("metadata", {})
            lines.append(
                "- [{id}] ({memory_type}, access={access_count}) {text}".format(
                    id=mem["id"],
                    memory_type=meta.get("memory_type", "unknown"),
                    access_count=meta.get("access_count", 0),
                    text=mem.get("memory", ""),
                )
            )
        return "\n".join(lines)

    def _call_json(self, system_prompt: str, user_payload: str, agent_id: str, source: str) -> dict:
        response = self.memory.llm.generate(
            prompt=f"{system_prompt}\n\n{user_payload}",
            source=source,
            agent_id=agent_id,
            temperature=0.1,
            max_tokens=1200,
        )
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        match_start = raw.find("{")
        match_end = raw.rfind("}")
        if match_start == -1 or match_end == -1:
            return {}
        return json.loads(raw[match_start:match_end + 1])

    def _apply(self, proposal: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
        ptype = proposal.get("type")
        if ptype == "merge":
            keep_id = proposal.get("keep")
            absorb = [m for m in proposal.get("absorb", []) if m != keep_id]
            text = proposal.get("rewriteContent")
            if not keep_id or not absorb or not text or keep_id not in by_id:
                return None
            vector = self.memory._embed_text(text)
            self.memory.qdrant.set_payload(
                collection_name="mem0",
                payload={"memory": text, "data": text, "supersedes": absorb},
                points=[keep_id],
            )
            self.memory.qdrant.update_vectors(
                collection_name="mem0",
                points=[PointVectors(id=keep_id, vector=vector)],
            )
            self.memory._archive_superseded(absorb, keep_id)
            return {"type": "merge", "memory_id": keep_id, "absorbed": absorb}

        if ptype == "supersede":
            newer = proposal.get("newer")
            older = [m for m in proposal.get("older", []) if m != newer]
            if not newer or not older:
                return None
            self.memory.qdrant.set_payload(
                collection_name="mem0",
                payload={"supersedes": older},
                points=[newer],
            )
            self.memory._archive_superseded(older, newer)
            return {"type": "supersede", "memory_id": newer, "superseded": older}

        if ptype == "prune":
            memory_id = proposal.get("memoryId")
            if not memory_id:
                return None
            self.memory.qdrant.set_payload(
                collection_name="mem0",
                payload=inactive_payload(PRUNED, prune_reason=proposal.get("reason", "")),
                points=[memory_id],
            )
            return {"type": "prune", "memory_id": memory_id}

        return None

    def _log(self, result: ConsolidationResult):
        self.memory.event_logger.log_event(
            event_type="memory_consolidated",
            agent_id=result.agent_id,
            source="consolidation.run",
            metadata=result.to_dict(),
        )
