"""Spawn & die: перезапуск агента после изменений core-кода.

Механизм:
1. Агент вносит изменения через self_modify
2. Git commit автоматически
3. Запуск нового процесса (subprocess)
4. Graceful shutdown текущего
5. Новый процесс подхватывает конфигурацию
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


class RestartController:
    """Управление перезапуском агента."""

    def __init__(
        self,
        project_root: Path,
        notify_callback: Callable[[str], Awaitable[None]] | None = None,
    ):
        self._root = project_root
        self._notify = notify_callback
        self._restarting = False

    @property
    def is_restarting(self) -> bool:
        return self._restarting

    async def spawn_and_die(self, reason: str = "core-код изменён") -> None:
        """Запустить новый процесс агента и завершить текущий.

        Args:
            reason: причина перезапуска (для уведомления)
        """
        if self._restarting:
            logger.warning("Перезапуск уже в процессе")
            return

        self._restarting = True
        logger.info("Spawn & die: %s", reason)

        if self._notify:
            try:
                await self._notify(f"🔄 Перезапускаюсь: {reason}")
            except Exception:
                logger.exception("Ошибка уведомления о перезапуске")

        await asyncio.sleep(1)

        try:
            env = os.environ.copy()
            env["EVO_RESTARTED"] = "1"

            new_process = subprocess.Popen(
                [sys.executable, "-m", "evo_agent"],
                cwd=str(self._root),
                env=env,
                start_new_session=True,
            )
            logger.info("Новый процесс запущен: PID=%d", new_process.pid)

        except Exception:
            logger.exception("Не удалось запустить новый процесс")
            self._restarting = False
            if self._notify:
                await self._notify("❌ Ошибка перезапуска, продолжаю работу")
            return

        logger.info("Завершение текущего процесса...")
        await asyncio.sleep(2)
        _graceful_exit()

    async def restart_if_needed(self, changed_files: list[str]) -> bool:
        """Проверить, нужен ли перезапуск (изменения в src/ или core/).

        Returns:
            True если перезапуск инициирован
        """
        needs_restart = any(
            f.startswith("src/") or f.startswith("src\\")
            for f in changed_files
        )
        if needs_restart:
            await self.spawn_and_die("изменены файлы ядра")
            return True
        return False

    @staticmethod
    def is_restarted_instance() -> bool:
        """Это перезапущенный экземпляр?"""
        return os.environ.get("EVO_RESTARTED") == "1"


def _graceful_exit() -> None:
    """Корректное завершение процесса."""
    try:
        os.kill(os.getpid(), signal.SIGTERM)
    except (OSError, AttributeError):
        sys.exit(0)
