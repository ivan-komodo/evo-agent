"""Лёгкий in-memory монитор метрик агента."""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class AgentMonitor:
    """Мониторинг метрик и состояния агента."""

    def __init__(self):
        self._start_time = datetime.now()
        self._llm_calls: int = 0
        self._total_tokens: int = 0
        self._prompt_tokens: int = 0
        self._completion_tokens: int = 0
        self._tool_calls: Counter[str] = Counter()
        self._errors: int = 0
        self._messages_processed: int = 0

    def record_llm_call(self, usage: dict[str, int] | None = None):
        """Записать вызов LLM и токены."""
        self._llm_calls += 1
        if usage:
            self._prompt_tokens += usage.get("prompt_tokens", 0)
            self._completion_tokens += usage.get("completion_tokens", 0)
            self._total_tokens += usage.get("total_tokens", 0)

    def record_tool_call(self, tool_name: str):
        """Записать вызов инструмента."""
        self._tool_calls[tool_name] += 1

    def record_error(self):
        """Записать ошибку."""
        self._errors += 1

    def record_message(self):
        """Записать входящее сообщение."""
        self._messages_processed += 1

    def build_report(self, active_conversations: int) -> str:
        """Сформировать текстовый отчёт."""
        uptime = datetime.now() - self._start_time
        # Убираем микросекунды для красоты
        uptime_str = str(uptime).split(".")[0]

        top_tools_list = self._tool_calls.most_common(5)
        top_tools_str = ", ".join(f"{name}({count})" for name, count in top_tools_list) or "нет"

        return (
            f"**Отчёт о состоянии Evo-Agent**\n\n"
            f"⏱ **Uptime:** {uptime_str}\n"
            f"💬 **Сообщений:** {self._messages_processed}\n"
            f"👥 **Активных диалогов:** {active_conversations}\n"
            f"🤖 **Вызовов LLM:** {self._llm_calls}\n"
            f"🎟 **Токенов:** {self._total_tokens} (P: {self._prompt_tokens}, C: {self._completion_tokens})\n"
            f"🔧 **Инструменты:** {top_tools_str}\n"
            f"❌ **Ошибок:** {self._errors}"
        )
