"""Суммаризация истории диалога через LLM."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from evo_agent.memory.conversation import ConversationStore
    from evo_agent.llm.base import LLMProvider
    from evo_agent.core.types import Message

logger = logging.getLogger(__name__)


class ConversationSummarizer:
    """Суммаризация истории диалога через LLM."""

    SUMMARY_PROMPT = """
Ниже история диалога. Сделай краткую выжимку (5-10 предложений):
что обсуждалось, какие задачи выполнены, какие важные факты о пользователе.
Пиши от третьего лица ("Пользователь спросил...", "Агент выполнил...").
"""

    def __init__(
        self,
        store: ConversationStore,
        llm: LLMProvider,
        keep_recent: int = 10,
    ):
        self._store = store
        self._llm = llm
        self._keep_recent = keep_recent

    async def maybe_summarize(self, user_id: str) -> bool:
        """Суммаризировать если нужно. Возвращает True если запустилась."""
        if not await self._store.needs_summarization(user_id):
            return False

        logger.info("Запуск суммаризации для user=%s", user_id)
        messages = await self._store.load_recent(user_id)
        if not messages:
            return False

        summary = await self._call_llm(messages)
        if summary:
            await self._store.apply_summary(user_id, summary, keep_recent=self._keep_recent)
            return True
        return False

    async def _call_llm(self, messages: list[Message]) -> str:
        """Вызов LLM для получения сводки."""
        from evo_agent.core.types import Message as InternalMessage

        history_text = ""
        for msg in messages:
            role_name = msg.role.upper()
            content = msg.content or ""
            if msg.tool_calls:
                content += f" [CALL: {', '.join(tc.name for tc in msg.tool_calls)}]"
            history_text += f"{role_name}: {content}\n"

        prompt = f"{self.SUMMARY_PROMPT}\n\nИСТОРИЯ:\n{history_text}"
        
        try:
            response = await self._llm.chat([
                InternalMessage(role="system", content=prompt)
            ])
            return response.text or ""
        except Exception:
            logger.exception("Ошибка при вызове LLM для суммаризации")
            return ""
