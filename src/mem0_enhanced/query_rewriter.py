"""
Query rewriter that expands user queries for better memory retrieval.

Uses LLM (Anthropic Haiku or Ollama) to generate 2-3 search-optimized
queries from a single (possibly vague) user message.
"""

import json
import logging
from typing import Optional

from .llm import LLMClient
from .types import RewrittenQuery

logger = logging.getLogger(__name__)

REWRITE_PROMPT = """You are a search query optimizer. Given a user message and optional conversation context, generate 2-3 search queries that would find relevant memories in a personal knowledge store.

Rules:
- Each query should be 3-8 words
- Focus on concrete nouns, names, technologies, decisions
- Expand vague references ("that thing", "it", "the project") into specific terms using context
- Include at least one query that captures the main topic
- Return ONLY a JSON array of strings, nothing else

Context (recent messages):
{context}

User message: {query}

JSON array of search queries:"""


class QueryRewriter:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def rewrite(
        self, query: str, session_context: Optional[str] = None, agent_id: str = ""
    ) -> RewrittenQuery:
        try:
            prompt = REWRITE_PROMPT.format(
                context=session_context or "(no context)",
                query=query,
            )

            resp = self.llm.generate(
                prompt=prompt,
                source="query_rewrite",
                agent_id=agent_id,
                temperature=0.3,
                max_tokens=150,
            )

            raw = resp.text
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            queries = json.loads(raw)
            if not isinstance(queries, list) or len(queries) == 0:
                raise ValueError("Invalid response format")

            expanded = [query] + [q for q in queries[:3] if q != query]
            return RewrittenQuery(
                original=query,
                expanded=expanded,
                session_context_used=session_context is not None,
            )

        except Exception as e:
            logger.warning(f"Query rewrite failed, using original: {e}")
            return RewrittenQuery(
                original=query,
                expanded=[query],
                session_context_used=False,
            )

    def close(self):
        self.llm.close()
