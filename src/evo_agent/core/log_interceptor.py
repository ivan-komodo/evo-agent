from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from evo_agent.core.action_journal import ActionJournal, JournalEntry

class LogInterceptor(logging.Handler):
    """Перехватчик логов для записи ошибок и предупреждений в ActionJournal."""

    def __init__(self, journal: ActionJournal):
        super().__init__()
        self._journal = journal
        # Устанавливаем уровень фильтрации для самого хендлера
        self.setLevel(logging.WARNING)

    def emit(self, record: logging.LogRecord) -> None:
        """Обработка записи лога."""
        try:
            # Игнорируем логи самого журнала и интерцептора, чтобы избежать рекурсии
            if record.name.startswith("evo_agent.core.action_journal") or \
               record.name.startswith("evo_agent.core.log_interceptor"):
                return

            # Игнорируем шумные библиотеки, если нужно
            if record.name.startswith(("httpx", "aiogram", "openai")):
                return

            from evo_agent.core.action_journal import JournalEntry

            event_type = "error" if record.levelno >= logging.ERROR else "warning"
            
            summary = record.getMessage()
            details = None
            
            if record.exc_info:
                import traceback
                details = "".join(traceback.format_exception(*record.exc_info))

            entry = JournalEntry(
                timestamp=datetime.fromtimestamp(record.created),
                event_type=event_type,
                summary=summary,
                details=details,
                user_id=None, # Логи обычно глобальные
            )
            
            self._journal.record(entry)
        except Exception:
            # Если упали при логировании — ничего не поделаешь, выводим в stderr
            self.handleError(record)
