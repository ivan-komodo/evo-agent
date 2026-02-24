"""Абстрактный интерфейс ввода/вывода."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Awaitable

from evo_agent.core.types import UserInfo


MessageHandler = Callable[[str, UserInfo], Awaitable[None]]


class BaseInterface(ABC):
    """Базовый интерфейс для взаимодействия с пользователем."""

    name: str

    @abstractmethod
    async def start(self, on_message: MessageHandler) -> None:
        """Запустить интерфейс и начать принимать сообщения.

        Args:
            on_message: callback (text, user_info) -> None
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Остановить интерфейс."""
        ...

    @abstractmethod
    async def send_message(self, user_id: str, text: str, **kwargs: Any) -> None:
        """Отправить сообщение пользователю."""
        ...

    @abstractmethod
    async def ask_approval(
        self, user_id: str, question: str
    ) -> bool:
        """Запросить подтверждение (да/нет) от пользователя.

        Не блокирует обработку других сообщений.
        """
        ...
