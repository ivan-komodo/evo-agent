"""Управление историей диалогов -- JSONL хранение, загрузка, суммаризация."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from evo_agent.core.types import Message

logger = logging.getLogger(__name__)


class ConversationStore:
    """Хранение диалогов в JSONL-файлах.

    Каждый пользователь -- отдельный файл в data/conversations/{user_id}.jsonl.
    Поддерживает загрузку последних N сообщений и суммаризацию.
    """

    def __init__(
        self,
        conversations_dir: Path,
        max_messages: int = 50,
        auto_summarize_after: int = 30,
    ):
        self._dir = conversations_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max_messages = max_messages
        self._auto_summarize_after = auto_summarize_after

    def _user_file(self, user_id: str) -> Path:
        safe_id = user_id.replace("/", "_").replace("\\", "_")
        return self._dir / f"{safe_id}.jsonl"

    async def save_message(self, user_id: str, message: Message) -> None:
        """Сохранить одно сообщение в JSONL."""
        path = self._user_file(user_id)
        entry = {
            "role": message.role,
            "content": message.content,
            "timestamp": message.timestamp.isoformat(),
        }
        if message.tool_calls:
            entry["tool_calls"] = [tc.model_dump() for tc in message.tool_calls]
        if message.tool_call_id:
            entry["tool_call_id"] = message.tool_call_id
        if message.name:
            entry["name"] = message.name

        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    async def save_conversation(self, user_id: str, messages: list[Message]) -> None:
        """Сохранить все сообщения диалога (append)."""
        for msg in messages:
            await self.save_message(user_id, msg)

    async def load_recent(self, user_id: str, limit: int | None = None) -> list[Message]:
        """Загрузить последние N сообщений пользователя."""
        path = self._user_file(user_id)
        if not path.exists():
            return []

        limit = limit or self._max_messages
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        recent_lines = lines[-limit:]

        messages = []
        for line in recent_lines:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                msg = Message(
                    role=data["role"],
                    content=data.get("content"),
                    tool_call_id=data.get("tool_call_id"),
                    name=data.get("name"),
                    timestamp=datetime.fromisoformat(data["timestamp"]),
                )
                messages.append(msg)
            except (json.JSONDecodeError, KeyError):
                logger.warning("Повреждённая запись в %s", path)
                continue

        return messages

    async def get_message_count(self, user_id: str) -> int:
        """Количество сообщений пользователя."""
        path = self._user_file(user_id)
        if not path.exists():
            return 0
        return sum(1 for line in path.read_text(encoding="utf-8").strip().split("\n") if line)

    async def needs_summarization(self, user_id: str) -> bool:
        """Нужна ли суммаризация (превышен порог сообщений)."""
        count = await self.get_message_count(user_id)
        return count > self._auto_summarize_after

    async def apply_summary(self, user_id: str, summary: str, keep_recent: int = 10) -> None:
        """Применить суммаризацию: заменить старые сообщения на summary.

        Оставляет keep_recent последних сообщений, остальное заменяет на
        одно system-сообщение с summary.
        """
        path = self._user_file(user_id)
        if not path.exists():
            return

        lines = path.read_text(encoding="utf-8").strip().split("\n")
        recent = lines[-keep_recent:]

        summary_entry = {
            "role": "system",
            "content": f"[Сводка предыдущего разговора]\n{summary}",
            "timestamp": datetime.now().isoformat(),
        }

        with path.open("w", encoding="utf-8") as f:
            f.write(json.dumps(summary_entry, ensure_ascii=False) + "\n")
            for line in recent:
                f.write(line + "\n")

        logger.info("Суммаризация применена для user=%s: %d -> %d+1 сообщений",
                     user_id, len(lines), len(recent))

    async def clear(self, user_id: str) -> None:
        """Очистить историю пользователя."""
        path = self._user_file(user_id)
        if path.exists():
            path.unlink()
