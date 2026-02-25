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
        args_str = ", ".join(f"{k}={v!r}" for k, v in tool_call.arguments.items())
        return (
            f"Запрос на выполнение:\n"
            f"[tool] **{tool_call.name}**({args_str})\n"
            f"Уровень риска: {label}\n\n"
            f"Одобрить выполнение?"
        )
