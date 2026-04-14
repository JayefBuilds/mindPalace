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
            self._anthropic_lib = anthropic
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
            personal_api_key = os.environ.get("PERSONAL_ANTHROPIC_API_KEY", "")
            self._oauth_token = oauth_token
            self._personal_api_key = personal_api_key
            if api_key:
                # API key takes priority (may route through ANTHROPIC_BASE_URL if set)
                self._anthropic = anthropic.Anthropic(api_key=api_key)
            elif oauth_token:
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

    def _build_oauth_fallback_client(self):
        """Build a direct Anthropic OAuth client, bypassing any gateway (ANTHROPIC_BASE_URL)."""
        return self._anthropic_lib.Anthropic(
            auth_token=self._oauth_token,
            base_url="https://api.anthropic.com",
            default_headers={
                "anthropic-beta": "claude-code-20250219,oauth-2025-04-20",
            },
        )

    def _call_anthropic(
        self, prompt: str, source: str, agent_id: str,
        temperature: float, max_tokens: int,
    ) -> LLMResponse:
        try:
            return self._call_anthropic_client(
                self._anthropic, prompt, source, agent_id, temperature, max_tokens
            )
        except Exception as primary_err:
            # If we have an OAuth token, retry directly against Anthropic (bypasses gateway)
            if self._oauth_token:
                logger.warning(
                    f"Primary LLM call failed ({primary_err}), retrying via OAuth fallback"
                )
                try:
                    fallback = self._build_oauth_fallback_client()
                    return self._call_anthropic_client(
                        fallback, prompt, source, agent_id, temperature, max_tokens
                    )
                except Exception as fallback_err:
                    logger.error(f"OAuth fallback also failed: {fallback_err}")
                    # Final fallback: personal API key directly against Anthropic
                    if self._personal_api_key:
                        logger.warning("OAuth fallback failed, retrying via personal API key")
                        try:
                            final = self._anthropic_lib.Anthropic(
                                api_key=self._personal_api_key,
                                base_url="https://api.anthropic.com",
                            )
                            return self._call_anthropic_client(
                                final, prompt, source, agent_id, temperature, max_tokens
                            )
                        except Exception as final_err:
                            logger.error(f"Personal API key fallback also failed: {final_err}")
                            raise final_err
                    raise fallback_err
            # No OAuth token — try personal API key directly
            if self._personal_api_key:
                logger.warning(f"Primary LLM call failed ({primary_err}), retrying via personal API key")
                try:
                    final = self._anthropic_lib.Anthropic(
                        api_key=self._personal_api_key,
                        base_url="https://api.anthropic.com",
                    )
                    return self._call_anthropic_client(
                        final, prompt, source, agent_id, temperature, max_tokens
                    )
                except Exception as final_err:
                    logger.error(f"Personal API key fallback also failed: {final_err}")
                    raise final_err
            raise primary_err

    def _call_anthropic_client(
        self, client, prompt: str, source: str, agent_id: str,
        temperature: float, max_tokens: int,
    ) -> LLMResponse:
        start = time.time()
        response = client.messages.create(
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
