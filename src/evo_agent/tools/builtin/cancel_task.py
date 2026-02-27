"""Инструмент отмены задач планировщика."""

from __future__ import annotations

from typing import Any

from evo_agent.core.types import DangerLevel, ToolResult
from evo_agent.scheduler.store import SchedulerStore
from evo_agent.tools.base import BaseTool


class CancelTaskTool(BaseTool):
    name = "cancel_task"
    description = "Отменить задачу планировщика по id."
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "integer"},
        },
        "required": ["task_id"],
    }
    danger_level = DangerLevel.MODERATE

    def __init__(self, store: SchedulerStore):
        self._store = store

    async def execute(self, **kwargs: Any) -> ToolResult:
        tid = str(kwargs.get("tool_call_id", ""))
        try:
            task_id = int(kwargs.get("task_id"))
            caller_user_id = str(kwargs.get("_caller_user_id", ""))
            cancelled = await self._store.cancel_task(task_id=task_id, user_id=caller_user_id or None)
            if not cancelled:
                return self._fail(f"Задача id={task_id} не найдена или уже неактивна", tid)
            return self._ok(f"Задача id={task_id} отменена", tid)
        except Exception as e:
            return self._fail(f"Ошибка cancel_task: {e}", tid)

