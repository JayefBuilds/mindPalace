"""
Auto Typer: Classifies memory text into typed categories.

Used in two places:
1. In EnhancedMemory.add() when memory_type is not explicitly set
2. As a batch migration tool for untyped existing memories
"""

import json
import logging

from .llm import LLMClient

logger = logging.getLogger(__name__)

CLASSIFY_PROMPT = """Classify this memory into exactly one type:
- preference: User likes/dislikes, style choices, tool preferences
- durable_fact: Stable facts about the user, projects, environment
- decision: A choice or conclusion that was reached
- open_loop: Something unfinished or to revisit
- correction: A fix to something previously wrong

Memory: "{text}"

Respond with ONLY the type name, nothing else."""

BATCH_CLASSIFY_PROMPT = """Classify each memory into exactly one type:
- preference: User likes/dislikes, style choices, tool preferences
- durable_fact: Stable facts about the user, projects, environment
- decision: A choice or conclusion that was reached
- open_loop: Something unfinished or to revisit
- correction: A fix to something previously wrong

Memories:
{memories}

Respond with ONLY a JSON array of type names in the same order. Nothing else.
Example: ["durable_fact", "preference", "decision"]"""

VALID_TYPES = {"preference", "durable_fact", "decision", "open_loop", "correction"}


class AutoTyper:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def classify(self, text: str, agent_id: str = "") -> str:
        try:
            prompt = CLASSIFY_PROMPT.format(text=text)
            resp = self.llm.generate(
                prompt=prompt,
                source="auto_type",
                agent_id=agent_id,
                temperature=0.0,
                max_tokens=20,
            )

            result = resp.text.lower()
            for valid_type in VALID_TYPES:
                if valid_type in result:
                    return valid_type

            logger.warning(f"Unrecognized type '{result}', defaulting to durable_fact")
            return "durable_fact"

        except Exception as e:
            logger.warning(f"Auto-typing failed, defaulting to durable_fact: {e}")
            return "durable_fact"

    def classify_batch(self, texts: list[str], agent_id: str = "") -> list[str]:
        if not texts:
            return []

        if len(texts) <= 3:
            return [self.classify(t, agent_id=agent_id) for t in texts]

        try:
            numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
            prompt = BATCH_CLASSIFY_PROMPT.format(memories=numbered)

            resp = self.llm.generate(
                prompt=prompt,
                source="auto_type",
                agent_id=agent_id,
                temperature=0.0,
                max_tokens=200,
            )

            raw = resp.text
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            types = json.loads(raw)

            if not isinstance(types, list) or len(types) != len(texts):
                raise ValueError(f"Expected {len(texts)} types, got {len(types) if isinstance(types, list) else 'non-list'}")

            return [
                t if t in VALID_TYPES else "durable_fact"
                for t in types
            ]

        except Exception as e:
            logger.warning(f"Batch classification failed, falling back to individual: {e}")
            return [self.classify(t, agent_id=agent_id) for t in texts]

    def close(self):
        self.llm.close()
