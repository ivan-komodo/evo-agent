"""Абстракция LLM провайдера."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from evo_agent.core.types import LLMResponse, Message


class LLMProvider(ABC):
    """Базовый интерфейс для всех LLM провайдеров."""

    name: str

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Отправить диалог в LLM и получить ответ.

        Args:
            messages: история диалога
            tools: описания инструментов в формате OpenAI function calling

        Returns:
            LLMResponse с текстом или tool_calls
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Освободить ресурсы."""
        ...
