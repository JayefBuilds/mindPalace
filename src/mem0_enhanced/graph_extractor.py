"""
GraphExtractor: Custom graph extraction using our LLM client.

Bypasses Mem0's internal graph extraction, which uses Anthropic tool-calling
and is incompatible with OAuth tokens. Instead, this module uses our patched
LLMClient to extract entities and relations via a plain text prompt, then
writes directly to Neo4j.

Result: graph memory works whether you're on OAuth or a direct API key.
"""

import json
import logging
from typing import Optional

from .llm import LLMClient

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are an entity and relationship extraction system. Given a memory statement, extract key entities and the relationships between them.

Rules:
- Entities: named things (people, projects, tools, technologies, concepts, decisions)
- Relations: directional triples describing how entities connect
- Keep entity names short and canonical (e.g. "StoreKit 2" not "Apple's StoreKit version 2")
- Relations should be concise verb phrases: "uses", "decided against", "built with", "depends on"
- Only extract relations that are clearly stated — do not infer
- If nothing meaningful to extract, return empty arrays

Return ONLY a JSON object with:
  "entities": array of strings
  "relations": array of objects with "subject", "relation", "object"

No explanation, no markdown, just the JSON.

Example:
Input: "Decided to use StoreKit 2 for in-app purchases in oto instead of RevenueCat."
Output:
{{
  "entities": ["StoreKit 2", "oto", "RevenueCat", "in-app purchases"],
  "relations": [
    {{"subject": "oto", "relation": "uses", "object": "StoreKit 2"}},
    {{"subject": "oto", "relation": "decided against", "object": "RevenueCat"}},
    {{"subject": "StoreKit 2", "relation": "handles", "object": "in-app purchases"}}
  ]
}}

Memory statement:
{text}

JSON:"""


class GraphExtractor:
    """
    Extracts entities and relations from memory text using our LLM client,
    then writes them directly to Neo4j — no Anthropic tool-calling required.
    """

    def __init__(self, llm: LLMClient, neo4j_url: str, neo4j_password: str):
        self.llm = llm
        self._neo4j_url = neo4j_url
        self._neo4j_password = neo4j_password
        self._driver = None
        self._connect()

    def _connect(self):
        try:
            from neo4j import GraphDatabase
            self._driver = GraphDatabase.driver(
                self._neo4j_url,
                auth=("neo4j", self._neo4j_password),
            )
            logger.info("GraphExtractor connected to Neo4j")
        except Exception as e:
            logger.warning(f"GraphExtractor: could not connect to Neo4j: {e}")
            self._driver = None

    def extract_and_store(self, text: str, agent_id: str, memory_id: str) -> list[dict]:
        """
        Extract entities/relations from memory text and persist to Neo4j.
        Returns the list of relation dicts that were stored.
        """
        if not self._driver:
            return []

        try:
            prompt = EXTRACTION_PROMPT.format(text=text)
            resp = self.llm.generate(
                prompt=prompt,
                source="graph_extract",
                agent_id=agent_id,
                temperature=0.1,
                max_tokens=500,
            )

            raw = resp.text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            data = json.loads(raw)
            entities = [e for e in data.get("entities", []) if isinstance(e, str) and e.strip()]
            relations = [
                r for r in data.get("relations", [])
                if isinstance(r, dict)
                and r.get("subject", "").strip()
                and r.get("relation", "").strip()
                and r.get("object", "").strip()
            ]

            if not entities and not relations:
                return []

            self._write(agent_id, memory_id, entities, relations)
            logger.info(
                f"Graph: stored {len(entities)} entities, {len(relations)} relations "
                f"for memory {memory_id[:8]}"
            )
            return relations

        except Exception as e:
            logger.warning(f"Graph extraction failed for memory {memory_id}: {e}")
            return []

    def _write(
        self,
        agent_id: str,
        memory_id: str,
        entities: list[str],
        relations: list[dict],
    ):
        with self._driver.session() as session:
            # Upsert entity nodes
            for name in entities:
                session.run(
                    "MERGE (e:Entity {name: $name, agent_id: $agent_id})",
                    name=name.strip(),
                    agent_id=agent_id,
                )

            # Upsert memory node
            session.run(
                "MERGE (m:Memory {id: $memory_id, agent_id: $agent_id})",
                memory_id=memory_id,
                agent_id=agent_id,
            )

            # Link memory → entities
            for name in entities:
                session.run(
                    """
                    MATCH (m:Memory {id: $memory_id})
                    MATCH (e:Entity {name: $name, agent_id: $agent_id})
                    MERGE (m)-[:MENTIONS]->(e)
                    """,
                    memory_id=memory_id,
                    name=name.strip(),
                    agent_id=agent_id,
                )

            # Create relation edges (generic RELATION type, relation stored as property)
            for rel in relations:
                subj = rel["subject"].strip()
                obj = rel["object"].strip()
                relation_type = rel["relation"].strip()
                session.run(
                    """
                    MERGE (s:Entity {name: $subj, agent_id: $agent_id})
                    MERGE (o:Entity {name: $obj, agent_id: $agent_id})
                    MERGE (s)-[r:RELATION {type: $relation_type, memory_id: $memory_id}]->(o)
                    """,
                    subj=subj,
                    obj=obj,
                    agent_id=agent_id,
                    relation_type=relation_type,
                    memory_id=memory_id,
                )

    def get_relations(self, memory_id: str) -> list[str]:
        """Return human-readable relation strings for a given memory ID."""
        if not self._driver:
            return []
        try:
            with self._driver.session() as session:
                result = session.run(
                    """
                    MATCH (s:Entity)-[r:RELATION]->(o:Entity)
                    WHERE r.memory_id = $memory_id
                    RETURN s.name AS subject, r.type AS relation, o.name AS object
                    """,
                    memory_id=memory_id,
                )
                return [
                    f"{row['subject']} {row['relation']} {row['object']}"
                    for row in result
                ]
        except Exception as e:
            logger.warning(f"Failed to get relations for memory {memory_id}: {e}")
            return []

    def close(self):
        if self._driver:
            self._driver.close()
