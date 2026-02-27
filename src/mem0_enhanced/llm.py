"""
Unified LLM interface supporting both Anthropic and Ollama backends.

All three modules (query_rewriter, session_extractor, auto_typer) use this
so the provider switch is in one place.
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Optional

import os

import httpx

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    provider: str
    model: str


class LLMClient:
    """Unified client for Anthropic and Ollama."""

    def __init__(
        self,
        provider: str = "anthropic",
        model: str = "claude-haiku-4-5-20251001",
        ollama_url: str = "http://localhost:11434",
        token_logger=None,
    ):
        self.provider = provider
        self.model = model
        self.ollama_url = ollama_url
        self.token_logger = token_logger

        if provider == "anthropic":
            import anthropic
            oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
            if oauth_token:
                # OAuth token (from `claude setup-token`) — requires special beta headers
                self._anthropic = anthropic.Anthropic(
                    auth_token=oauth_token,
                    default_headers={
                        "anthropic-beta": "claude-code-20250219,oauth-2025-04-20",
                    },
                )
            else:
                self._anthropic = anthropic.Anthropic()
        else:
            self._http = httpx.Client(timeout=30.0)

    def generate(
        self,
        prompt: str,
        source: str = "",
        agent_id: str = "",
        temperature: float = 0.2,
        max_tokens: int = 1000,
    ) -> LLMResponse:
        if self.provider == "anthropic":
            return self._call_anthropic(prompt, source, agent_id, temperature, max_tokens)
        else:
            return self._call_ollama(prompt, source, agent_id, temperature, max_tokens)

    def _call_anthropic(
        self, prompt: str, source: str, agent_id: str,
        temperature: float, max_tokens: int,
    ) -> LLMResponse:
        start = time.time()
        response = self._anthropic.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        latency_ms = int((time.time() - start) * 1000)

        text = response.content[0].text.strip()
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens

        if self.token_logger and agent_id:
            self.token_logger.log_anthropic_call(
                model=self.model,
                source=source,
                agent_id=agent_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
            )

        return LLMResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider="anthropic",
            model=self.model,
        )

    def _call_ollama(
        self, prompt: str, source: str, agent_id: str,
        temperature: float, max_tokens: int,
    ) -> LLMResponse:
        response = self._http.post(
            f"{self.ollama_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            },
        )
        response.raise_for_status()
        resp_json = response.json()
        text = resp_json["response"].strip()
        input_tokens = resp_json.get("prompt_eval_count", 0)
        output_tokens = resp_json.get("eval_count", 0)

        if self.token_logger and agent_id:
            self.token_logger.log_ollama_call(
                model=self.model,
                source=source,
                agent_id=agent_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

        return LLMResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider="ollama",
            model=self.model,
        )

    def close(self):
        if hasattr(self, '_http'):
            self._http.close()
