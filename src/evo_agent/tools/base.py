"""Базовый класс инструмента."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from evo_agent.core.types import DangerLevel, ToolResult


class BaseTool(ABC):
    """Абстрактный инструмент агента.

    Каждый tool предоставляет:
    - name/description/parameters для LLM (формат OpenAI function calling)
    - danger_level для Autonomy Manager
    - async execute() для выполнения
    """

    name: str
    description: str
    parameters: dict[str, Any]
    danger_level: DangerLevel = DangerLevel.SAFE

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Выполнить инструмент с переданными аргументами."""
        ...

    def to_openai_schema(self) -> dict[str, Any]:
        """Конвертация в формат OpenAI function calling."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def _ok(self, content: str, tool_call_id: str = "") -> ToolResult:
        return ToolResult(tool_call_id=tool_call_id, name=self.name, content=content, success=True)

    def _fail(self, content: str, tool_call_id: str = "") -> ToolResult:
        return ToolResult(
            tool_call_id=tool_call_id, name=self.name, content=content, success=False
        )
