from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING
from evo_agent.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from evo_agent.core.action_journal import ActionJournal

logger = logging.getLogger(__name__)

class CheckStatusTool(BaseTool):
    """Инструмент для проверки статуса последних действий через ActionJournal."""
    
    name = "check_status"
    description = "Проверить статус последних действий: доставки сообщений, ошибки, результаты вызовов инструментов."
    parameters = {
        "scope": {"type": "string", "enum": ["my_errors", "all_errors", "deliveries", "full"], "default": "full"},
        "limit": {"type": "integer", "default": 10},
    }
    
    def __init__(self, journal: ActionJournal):
        super().__init__()
        self._journal = journal

    async def execute(self, scope: str = "full", limit: int = 10, user_id: str | None = None, **kwargs: Any) -> ToolResult:
        tool_call_id = str(kwargs.get("tool_call_id", ""))
        try:
            if scope == "my_errors":
                # Ошибки текущего пользователя (если передан user_id)
                events = self._journal.get_recent_errors(limit=limit)
                if user_id:
                    events = [e for e in events if e.user_id == user_id]
            elif scope == "all_errors":
                events = self._journal.get_recent_errors(limit=limit)
            elif scope == "deliveries":
                events = [e for e in self._journal._entries if "delivery" in e.event_type]
                if user_id:
                    events = [e for e in events if e.user_id == user_id]
                events = events[-limit:]
            else: # full
                if user_id:
                    events = self._journal.get_for_user(user_id, limit=limit)
                else:
                    events = list(self._journal._entries)[-limit:]

            if not events:
                return self._ok("Событий не найдено.", tool_call_id=tool_call_id)

            lines = []
            for e in events:
                time_str = e.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                user_str = f" [User: {e.user_id}]" if e.user_id else ""
                lines.append(f"[{time_str}] {e.event_type.upper()}: {e.summary}{user_str}")
                if e.details and scope == "full":
                    lines.append(f"  Details: {e.details[:200]}")

            return self._ok("\n".join(lines), tool_call_id=tool_call_id)
        except Exception as e:
            return self._fail(f"Ошибка при получении статуса: {e}", tool_call_id=tool_call_id)
