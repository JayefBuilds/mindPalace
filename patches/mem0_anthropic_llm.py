import os
import sys
import time
from typing import Dict, List, Optional, Union

try:
    import anthropic
except ImportError:
    raise ImportError("The 'anthropic' library is required. Please install it using 'pip install anthropic'.")

from mem0.configs.llms.anthropic import AnthropicConfig
from mem0.configs.llms.base import BaseLlmConfig
from mem0.llms.base import LLMBase

# Reach back into the mem0_enhanced package for the token logger.
# bridge_cli puts the source dir on sys.path so this import works at runtime.
try:
    from mem0_enhanced.token_logger import TokenLogger
    _token_logger = TokenLogger()
except Exception:
    _token_logger = None


class AnthropicLLM(LLMBase):
    def __init__(self, config: Optional[Union[BaseLlmConfig, AnthropicConfig, Dict]] = None):
        # Convert to AnthropicConfig if needed
        if config is None:
            config = AnthropicConfig()
        elif isinstance(config, dict):
            config = AnthropicConfig(**config)
        elif isinstance(config, BaseLlmConfig) and not isinstance(config, AnthropicConfig):
            # Convert BaseLlmConfig to AnthropicConfig
            config = AnthropicConfig(
                model=config.model,
                temperature=config.temperature,
                api_key=config.api_key,
                max_tokens=config.max_tokens,
                top_p=config.top_p,
                top_k=config.top_k,
                enable_vision=config.enable_vision,
                vision_details=config.vision_details,
                http_client_proxies=config.http_client,
            )

        super().__init__(config)

        if not self.config.model:
            self.config.model = "claude-3-5-sonnet-20240620"

        api_key = self.config.api_key or os.getenv("ANTHROPIC_API_KEY")
        self.client = anthropic.Anthropic(api_key=api_key)

    def generate_response(
        self,
        messages: List[Dict[str, str]],
        response_format=None,
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        **kwargs,
    ):
        """
        Generate a response based on the given messages using Anthropic.

        Args:
            messages (list): List of message dicts containing 'role' and 'content'.
            response_format (str or object, optional): Format of the response. Defaults to "text".
            tools (list, optional): List of tools that the model can call. Defaults to None.
            tool_choice (str, optional): Tool choice method. Defaults to "auto".
            **kwargs: Additional Anthropic-specific parameters.

        Returns:
            str: The generated response.
        """
        # Separate system message from other messages
        system_message = ""
        filtered_messages = []
        for message in messages:
            if message["role"] == "system":
                system_message = message["content"]
            else:
                filtered_messages.append(message)

        params = self._get_supported_params(messages=messages, **kwargs)
        params.update(
            {
                "model": self.config.model,
                "messages": filtered_messages,
                "system": system_message,
            }
        )
        # Anthropic rejects requests with both temperature and top_p
        if "temperature" in params and "top_p" in params:
            del params["top_p"]

        if tools:  # TODO: Remove tools if no issues found with new memory addition logic
            # Convert OpenAI-style function tools to Anthropic custom tool format
            converted_tools = []
            for tool in tools:
                if tool.get("type") == "function" and "function" in tool:
                    fn = tool["function"]
                    converted_tools.append({
                        "type": "custom",
                        "name": fn["name"],
                        "description": fn.get("description", ""),
                        "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                    })
                else:
                    converted_tools.append(tool)
            params["tools"] = converted_tools
            params["tool_choice"] = tool_choice if isinstance(tool_choice, dict) else {"type": tool_choice}

        _t0 = time.time()
        response = self.client.messages.create(**params)
        _latency_ms = int((time.time() - _t0) * 1000)

        # Log mem0-internal call to the shared token DB (source="mem0_internal")
        if _token_logger is not None:
            try:
                _agent_id = os.getenv("MEM0_AGENT_ID", "unknown")
                _token_logger.log_anthropic_call(
                    model=self.config.model,
                    source="mem0_internal",
                    agent_id=_agent_id,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    latency_ms=_latency_ms,
                )
            except Exception:
                pass  # never block on logging

        # If tools were used and the response contains tool_use blocks, return in OpenAI-compatible format
        if tools and response.content:
            tool_calls = []
            text_parts = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_calls.append({
                        "name": block.name,
                        "arguments": block.input,
                    })
                elif hasattr(block, "text"):
                    text_parts.append(block.text)
            if tool_calls:
                return {"tool_calls": tool_calls, "content": " ".join(text_parts)}
        # If tools were requested but no tool_use blocks returned, return empty dict
        # so callers expecting {"tool_calls": [...]} don't crash on .get()
        if tools:
            return {}
        return response.content[0].text
