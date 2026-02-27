"""Инструмент просмотра задач планировщика."""

from __future__ import annotations

from typing import Any

from evo_agent.core.types import DangerLevel, ToolResult
from evo_agent.scheduler.store import SchedulerStore
from evo_agent.tools.base import BaseTool


class ListTasksTool(BaseTool):
    name = "list_tasks"
    description = "Показать список задач планировщика (по умолчанию только активные)."
    parameters = {
        "type": "object",
        "properties": {
            "only_mine": {"type": "boolean", "default": True},
            "include_done": {"type": "boolean", "default": False},
        },
        "required": [],
    }
    danger_level = DangerLevel.SAFE

    def __init__(self, store: SchedulerStore):
        self._store = store

    async def execute(self, **kwargs: Any) -> ToolResult:
        tid = str(kwargs.get("tool_call_id", ""))
        try:
            only_mine = bool(kwargs.get("only_mine", True))
            include_done = bool(kwargs.get("include_done", False))
            caller_user_id = str(kwargs.get("_caller_user_id", "")) if only_mine else None

            tasks = await self._store.list_tasks(user_id=caller_user_id, include_done=include_done)
            if not tasks:
                return self._ok("Задач нет.", tid)

            lines = ["Задачи планировщика:"]
            for t in tasks[:100]:
                lines.append(
                    f"- id={t.id} status={t.status} type={t.schedule_type} "
                    f"next={t.next_run_at_utc.isoformat()} tool={t.tool_name} runs={t.run_count}"
                )
            return self._ok("\n".join(lines), tid)
        except Exception as e:
            return self._fail(f"Ошибка list_tasks: {e}", tid)

