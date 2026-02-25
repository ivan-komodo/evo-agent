from __future__ import annotations
import logging
from typing import Any
from evo_agent.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

class TelegramSendTool(BaseTool):
    """Инструмент для отправки сообщений в Telegram любому пользователю."""
    
    name = "telegram_send"
    description = "Отправить текстовое сообщение пользователю Telegram по его ID. Используй этот инструмент, если нужно написать кому-то, кто не является текущим собеседником."
    danger_level = 1  # Требует подтверждения на уровне Careful
    
    parameters = {
        "chat_id": {"type": "string", "description": "ID чата или пользователя (например, '216437118')"},
        "text": {"type": "string", "description": "Текст сообщения"},
    }
    
    def __init__(self, interface: Any):
        super().__init__()
        self._interface = interface

    async def execute(self, chat_id: str, text: str, **kwargs: Any) -> ToolResult:
        """Отправить сообщение в Telegram.
        Возвращает ToolResult с заполненными полями name и tool_call_id через базовые методы.
        """
        try:
            if not hasattr(self._interface, "send_message"):
                return self._fail("Текущий интерфейс не поддерживает отправку сообщений в Telegram")
            success = await self._interface.send_message(chat_id, text)
            if success:
                return self._ok(f"Сообщение успешно отправлено в чат {chat_id}")
            else:
                return self._fail(f"Не удалось отправить сообщение в чат {chat_id}")
        except Exception as e:
            return self._fail(f"Ошибка при отправке через Telegram: {e}")
