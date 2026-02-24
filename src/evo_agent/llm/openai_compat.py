"""OpenAI-совместимый LLM провайдер.

Покрывает: OpenAI, OpenRouter, Ollama, vLLM, LM Studio, LiteLLM --
любой endpoint с /v1/chat/completions.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from evo_agent.core.types import LLMResponse, Message, ToolCall
from evo_agent.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class OpenAICompatProvider(LLMProvider):
    """Провайдер для OpenAI-совместимых API."""

    name = "openai_compat"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o",
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ):
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        llm_messages = _convert_messages(messages)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": llm_messages,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        logger.debug("LLM запрос: model=%s, messages=%d, tools=%d",
                      self._model, len(llm_messages), len(tools or []))

        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        message = choice.message

        tool_calls: list[ToolCall] | None = None
        if message.tool_calls:
            tool_calls = []
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))

        usage = None
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return LLMResponse(
            text=message.content,
            tool_calls=tool_calls,
            usage=usage,
        )

    async def close(self) -> None:
        await self._client.close()


def _convert_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Конвертация внутренних Message в формат OpenAI API."""
    result = []
    for msg in messages:
        entry: dict[str, Any] = {"role": msg.role}

        if msg.content is not None:
            entry["content"] = msg.content

        if msg.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in msg.tool_calls
            ]

        if msg.tool_call_id:
            entry["tool_call_id"] = msg.tool_call_id

        if msg.name:
            entry["name"] = msg.name

        result.append(entry)
    return result
