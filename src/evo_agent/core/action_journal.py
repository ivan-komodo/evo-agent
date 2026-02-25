from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)

@dataclass
class JournalEntry:
    timestamp: datetime
    event_type: str       # "delivery_ok", "delivery_fail", "tool_ok", "tool_fail", "error", "warning"
    summary: str          # краткое описание
    details: str | None = None   # полные детали (traceback и т.п.)
    user_id: str | None = None   # к какому диалогу относится (None = глобальное)

class ActionJournal:
    """Кольцевой буфер событий для само-восприятия агента."""

    def __init__(self, max_entries: int = 200):
        self._entries: deque[JournalEntry] = deque(maxlen=max_entries)
        self._last_seen_by_user: dict[str, datetime] = {}

    def record(self, entry: JournalEntry) -> None:
        """Записать новое событие."""
        self._entries.append(entry)
        # Если это критическая ошибка, дублируем в лог (но LogInterceptor сам это сделает, если мы пишем через logger)
        if entry.event_type in ("error", "delivery_fail", "tool_fail"):
            logger.warning("Journal record [%s]: %s", entry.event_type, entry.summary)

    def get_recent_errors(self, since: datetime | None = None, limit: int = 10) -> list[JournalEntry]:
        """Получить последние ошибки."""
        errors = [e for e in self._entries if e.event_type in ("error", "warning", "delivery_fail", "tool_fail")]
        if since:
            errors = [e for e in errors if e.timestamp > since]
        return errors[-limit:]

    def get_for_user(self, user_id: str, limit: int = 5) -> list[JournalEntry]:
        """Получить события, специфичные для пользователя или глобальные."""
        events = [e for e in self._entries if e.user_id is None or e.user_id == user_id]
        return events[-limit:]

    def format_for_llm(self, user_id: str) -> str | None:
        """Сформировать текстовый блок для инъекции в контекст LLM.
        
        Возвращает None, если новых важных событий с момента последнего вызова не было.
        """
        last_seen = self._last_seen_by_user.get(user_id, datetime.min)
        
        # Берем ошибки и важные уведомления, которые пользователь еще не "видел" в контексте
        new_events = [
            e for e in self._entries 
            if e.timestamp > last_seen and (e.user_id is None or e.user_id == user_id)
            and e.event_type in ("error", "warning", "delivery_fail", "tool_fail")
        ]
        
        if not new_events:
            return None

        # Обновляем время последнего просмотра
        self._last_seen_by_user[user_id] = datetime.now()

        lines = ["[СИСТЕМНОЕ УВЕДОМЛЕНИЕ О СОСТОЯНИИ]"]
        lines.append("За последнее время произошли следующие важные события, требующие твоего внимания:")
        
        for e in new_events:
            time_str = e.timestamp.strftime("%H:%M:%S")
            prefix = f"- [{e.event_type.upper()} {time_str}]"
            lines.append(f"{prefix} {e.summary}")
            if e.details and e.event_type in ("error", "tool_fail"):
                # Ограничиваем детали, чтобы не раздувать контекст
                details = e.details[:200] + "..." if len(e.details) > 200 else e.details
                lines.append(f"  Детали: {details}")

        lines.append("\nПожалуйста, учти эту информацию при ответе пользователю. "
                     "Если действие не удалось, сообщи об этом и предложи альтернативу.")
        
        return "\n".join(lines)
