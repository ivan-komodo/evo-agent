"""Управление уровнями автономности агента."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Awaitable

from evo_agent.core.types import AutonomyLevel, DangerLevel, ToolCall

logger = logging.getLogger(__name__)

ApprovalCallback = Callable[[str, ToolCall], Awaitable[bool]]


class AutonomyManager:
    """Определяет, нужно ли подтверждение для конкретного tool call.

    Уровни:
    - 0 (Paranoid): подтверждение на каждый tool call
    - 1 (Careful): подтверждение на danger_level >= 1
    - 2 (Balanced): подтверждение только на danger_level >= 2
    - 3 (Autonomous): полная автономия
    """

    def __init__(self, level: AutonomyLevel = AutonomyLevel.CAREFUL):
        self._level = level
        self._approval_callback: ApprovalCallback | None = None
        self._pending_approvals: dict[str, asyncio.Future[bool]] = {}

    @property
    def level(self) -> AutonomyLevel:
        return self._level

    @level.setter
    def level(self, value: int) -> None:
        self._level = AutonomyLevel(value)
        logger.info("Уровень автономности изменён на %d (%s)", value, self._level.name)

    def set_approval_callback(self, callback: ApprovalCallback) -> None:
        """Установить callback для запроса подтверждения (inline-кнопки и т.п.)."""
        self._approval_callback = callback

    def needs_approval(self, danger_level: DangerLevel) -> bool:
        """Нужно ли подтверждение для данного danger_level?"""
        if self._level == AutonomyLevel.PARANOID:
            return True
        if self._level == AutonomyLevel.CAREFUL:
            return danger_level >= DangerLevel.MODERATE
        if self._level == AutonomyLevel.BALANCED:
            return danger_level >= DangerLevel.DANGEROUS
        return False

    async def request_approval(
        self,
        user_id: str,
        tool_call: ToolCall,
        danger_level: DangerLevel,
    ) -> bool:
        """Запросить подтверждение у пользователя.

        Не блокирует event loop -- другие сообщения продолжают обрабатываться.
        """
        if not self.needs_approval(danger_level):
            return True

        if self._approval_callback is None:
            logger.warning(
                "Нет callback для подтверждения, автоматически одобряем: %s", tool_call.name
            )
            return True

        logger.info(
            "Запрос подтверждения: tool=%s, user=%s, danger=%d",
            tool_call.name, user_id, danger_level,
        )
        return await self._approval_callback(user_id, tool_call)

    def format_approval_message(self, tool_call: ToolCall, danger_level: DangerLevel) -> str:
        """Сформировать сообщение для подтверждения."""
        danger_labels = {
            DangerLevel.SAFE: "безопасно",
            DangerLevel.MODERATE: "[!] умеренный риск",
            DangerLevel.DANGEROUS: "[!!!] опасно",
        }
        label = danger_labels.get(danger_level, "неизвестно")
        args_str = _format_tool_args(tool_call.arguments)
        return (
            f"Запрос на выполнение:\n"
            f"[tool] {tool_call.name}({args_str})\n"
            f"Уровень риска: {label}\n\n"
            f"Одобрить выполнение?"
        )


def _format_tool_args(arguments: dict[str, Any], max_items: int = 5) -> str:
    """Компактно форматировать аргументы tool call для UI подтверждения."""
    if not arguments:
        return ""

    parts: list[str] = []
    items = list(arguments.items())
    for key, value in items[:max_items]:
        parts.append(f"{key}={_format_arg_value(value)}")

    if len(items) > max_items:
        parts.append(f"... +{len(items) - max_items} арг.")
    return ", ".join(parts)


def _format_arg_value(value: Any, max_len: int = 120) -> str:
    """Безопасное и короткое отображение значения аргумента."""
    if isinstance(value, str):
        compact = " ".join(value.split())
        if len(compact) > max_len:
            preview = compact[:max_len]
            return f"'{preview}...'(len={len(compact)})"
        return repr(compact)

    if isinstance(value, (int, float, bool)) or value is None:
        return repr(value)

    if isinstance(value, dict):
        return f"<dict keys={list(value.keys())[:5]}>"

    if isinstance(value, list):
        return f"<list len={len(value)}>"

    text = repr(value)
    if len(text) > max_len:
        return f"{text[:max_len]}...(len={len(text)})"
    return text
