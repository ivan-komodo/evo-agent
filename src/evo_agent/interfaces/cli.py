"""CLI-интерфейс для локального использования без Telegram."""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from evo_agent.core.types import UserInfo
from evo_agent.interfaces.base import BaseInterface, MessageHandler

logger = logging.getLogger(__name__)


def _safe_print(text: str) -> None:
    """Безопасный вывод в консоль с полной поддержкой UTF-8."""
    try:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
    except UnicodeEncodeError:
        encoded = text.encode("utf-8", errors="replace")
        sys.stdout.buffer.write(encoded + b"\n")
        sys.stdout.buffer.flush()


def _safe_input(prompt: str) -> str:
    """Безопасный ввод с полной поддержкой UTF-8."""
    try:
        sys.stdout.write(prompt)
        sys.stdout.flush()
    except UnicodeEncodeError:
        sys.stdout.buffer.write(prompt.encode("utf-8", errors="replace"))
        sys.stdout.buffer.flush()
    return input()


class CLIInterface(BaseInterface):
    """Консольный интерфейс для прямого взаимодействия."""

    name = "cli"

    def __init__(self, user_name: str = "user"):
        self._user_name = user_name
        self._on_message: MessageHandler | None = None
        self._running = False
        self._input_task: asyncio.Task | None = None

    async def start(self, on_message: MessageHandler) -> None:
        self._on_message = on_message
        self._running = True
        self._input_task = asyncio.create_task(self._input_loop())
        logger.info("CLI интерфейс запущен")

    async def stop(self) -> None:
        self._running = False
        if self._input_task:
            self._input_task.cancel()
            try:
                await self._input_task
            except asyncio.CancelledError:
                pass
        logger.info("CLI интерфейс остановлен")

    async def send_message(self, user_id: str, text: str, **kwargs: Any) -> bool:
        _safe_print(f"\n[Evo]: {text}\n")
        return True

    async def ask_approval(self, user_id: str, question: str) -> bool:
        _safe_print(f"\n[!] {question}")
        loop = asyncio.get_event_loop()
        answer = await loop.run_in_executor(None, lambda: _safe_input("(y/n): ").strip().lower())
        return answer in ("y", "yes", "да", "д")

    async def _input_loop(self) -> None:
        """Цикл чтения ввода из stdin."""
        loop = asyncio.get_event_loop()
        user_info = UserInfo(
            user_id="cli_user",
            name=self._user_name,
            source_type="cli",
        )

        _safe_print("=" * 50)
        _safe_print("Evo-Agent CLI. Введите сообщение (Ctrl+C для выхода).")
        _safe_print("Команды: /status, /skills, /memory, /autonomy <N>, /quit")
        _safe_print("=" * 50)

        while self._running:
            try:
                text = await loop.run_in_executor(
                    None,
                    lambda: _safe_input(f"\n[{self._user_name}]: "),
                )
                text = text.strip()
                if not text:
                    continue

                if text in ("/quit", "/exit", "/q"):
                    self._running = False
                    break

                if self._on_message:
                    await self._on_message(text, user_info)

            except (EOFError, KeyboardInterrupt):
                self._running = False
                break
            except asyncio.CancelledError:
                break
