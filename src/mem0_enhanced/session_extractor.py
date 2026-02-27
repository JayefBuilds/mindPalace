"""
Session Extractor: Distills conversations into typed memory shards.

Called at end of session (explicit signal, timeout, or MCP tool call).
Takes a conversation transcript and produces a list of compact memory
shards, each typed and ready for storage.
"""

import json
import logging
from typing import Optional

from .llm import LLMClient

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are a memory extraction system. Analyze this conversation and extract discrete, durable facts worth remembering for future sessions.

Rules:
- Extract 0-10 memory shards (only what's genuinely worth remembering)
- Each shard: 1-3 sentences, self-contained, no references to "this conversation"
- Classify each shard with a type:
  - preference: User likes/dislikes, style preferences, tool choices
  - durable_fact: Stable facts about the user, their projects, environment
  - decision: A choice that was made and should be remembered
  - open_loop: Something unfinished, to revisit later
  - correction: Something previously wrong that was corrected
- Skip: greetings, small talk, transient questions, things already obvious
- Be concrete: "User chose PostgreSQL over MongoDB for the auth service" not "User discussed databases"
- If nothing worth remembering, return an empty array

Return ONLY a JSON array of objects with "text" and "type" fields. No other output.

Example output:
[
  {{"text": "User is building a speech-to-text iOS app using SwiftUI and AVFoundation.", "type": "durable_fact"}},
  {{"text": "User prefers short, direct responses without excessive caveats.", "type": "preference"}},
  {{"text": "Decided to use StoreKit 2 for in-app purchases instead of RevenueCat.", "type": "decision"}},
  {{"text": "Still needs to implement the onboarding flow — blocked on final copy.", "type": "open_loop"}}
]

Conversation:
{conversation}

JSON array of memory shards:"""


class SessionExtractor:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def extract(
        self,
        conversation: str,
        existing_memories: Optional[list[str]] = None,
        agent_id: str = "",
    ) -> list[dict]:
        try:
            prompt = EXTRACTION_PROMPT.format(conversation=conversation)

            if existing_memories:
                dedup_block = "\n".join(f"- {m}" for m in existing_memories[:20])
                prompt += f"\n\nAlready stored (do NOT extract duplicates of these):\n{dedup_block}"

            resp = self.llm.generate(
                prompt=prompt,
                source="session_extract",
                agent_id=agent_id,
                temperature=0.2,
                max_tokens=1000,
            )

            raw = resp.text
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            shards = json.loads(raw)

            if not isinstance(shards, list):
                raise ValueError("Expected JSON array")

            valid = []
            for shard in shards:
                if (
                    isinstance(shard, dict)
                    and "text" in shard
                    and "type" in shard
                    and shard["type"] in {
                        "preference", "durable_fact", "decision",
                        "open_loop", "correction",
                    }
                ):
                    valid.append(shard)
                else:
                    logger.warning(f"Skipping invalid shard: {shard}")

            logger.info(f"Extracted {len(valid)} memory shards from session")
            return valid

        except Exception as e:
            logger.warning(f"Session extraction failed: {e}")
            return []

    def close(self):
        self.llm.close()
