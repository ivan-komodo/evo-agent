"""Базовые типы данных агента."""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum
from typing import Any

from pydantic import BaseModel, Field


class Role(str):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class DangerLevel(IntEnum):
    SAFE = 0
    MODERATE = 1
    DANGEROUS = 2


class AutonomyLevel(IntEnum):
    PARANOID = 0      # подтверждение на каждый tool call
    CAREFUL = 1       # подтверждение на danger_level >= 1
    BALANCED = 2      # подтверждение только на danger_level >= 2
    AUTONOMOUS = 3    # полная автономия


class ToolCall(BaseModel):
    """Запрос на вызов инструмента от LLM."""
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Результат выполнения инструмента."""
    tool_call_id: str
    name: str
    content: str
    success: bool = True


class Message(BaseModel):
    """Сообщение в диалоге."""
    role: str
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    timestamp: datetime = Field(default_factory=datetime.now)


class LLMResponse(BaseModel):
    """Ответ от LLM провайдера."""
    text: str | None = None
    tool_calls: list[ToolCall] | None = None
    usage: dict[str, int] | None = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class Conversation(BaseModel):
    """Диалог с пользователем."""
    user_id: str
    messages: list[Message] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    summary: str | None = None

    def add(self, message: Message) -> None:
        self.messages.append(message)

    def to_llm_messages(self) -> list[dict[str, Any]]:
        """Конвертация в формат OpenAI API."""
        result = []
        for msg in self.messages:
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
                            "arguments": __import__("json").dumps(tc.arguments),
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


class UserInfo(BaseModel):
    """Информация о текущем пользователе для контекста."""
    user_id: str
    name: str | None = None
    source_type: str = "telegram"
    source_id: str | None = None
