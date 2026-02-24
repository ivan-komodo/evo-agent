"""Кросс-платформенное исполнение shell-команд."""

from __future__ import annotations

import asyncio
import logging
import platform
from typing import Any

from evo_agent.core.types import DangerLevel, ToolResult
from evo_agent.tools.base import BaseTool

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 60


class ShellTool(BaseTool):
    name = "shell"
    description = (
        "Выполнить команду в командной строке операционной системы. "
        "Возвращает stdout, stderr и код возврата. "
        "Поддерживает bash (Linux/Mac), cmd и powershell (Windows)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Команда для выполнения",
            },
            "shell": {
                "type": "string",
                "description": "Оболочка: bash, cmd, powershell. По умолчанию -- автоопределение по ОС.",
                "enum": ["bash", "cmd", "powershell"],
            },
            "timeout": {
                "type": "integer",
                "description": f"Таймаут в секундах (по умолчанию {_DEFAULT_TIMEOUT})",
            },
            "working_directory": {
                "type": "string",
                "description": "Рабочая директория для выполнения команды",
            },
        },
        "required": ["command"],
    }
    danger_level = DangerLevel.MODERATE

    def __init__(
        self,
        default_shell: str | None = None,
        default_timeout: int = _DEFAULT_TIMEOUT,
        default_cwd: str | None = None,
    ):
        self._default_shell = default_shell or _detect_shell()
        self._default_timeout = default_timeout
        self._default_cwd = default_cwd

    async def execute(self, **kwargs: Any) -> ToolResult:
        command: str = kwargs["command"]
        shell = kwargs.get("shell", self._default_shell)
        timeout = kwargs.get("timeout", self._default_timeout)
        cwd = kwargs.get("working_directory", self._default_cwd)
        tool_call_id = kwargs.get("tool_call_id", "")

        shell_cmd = _build_shell_command(command, shell)

        logger.info("Shell [%s]: %s (cwd=%s, timeout=%d)", shell, command, cwd, timeout)

        try:
            proc = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            stdout_str = stdout.decode("utf-8", errors="replace").strip()
            stderr_str = stderr.decode("utf-8", errors="replace").strip()

            parts = []
            if stdout_str:
                parts.append(f"STDOUT:\n{stdout_str}")
            if stderr_str:
                parts.append(f"STDERR:\n{stderr_str}")
            parts.append(f"EXIT CODE: {proc.returncode}")

            content = "\n\n".join(parts)
            success = proc.returncode == 0
            if success:
                return self._ok(content, tool_call_id)
            return self._fail(content, tool_call_id)

        except asyncio.TimeoutError:
            return self._fail(f"Таймаут: команда не завершилась за {timeout} секунд", tool_call_id)
        except Exception as e:
            return self._fail(f"Ошибка выполнения: {e}", tool_call_id)


def _detect_shell() -> str:
    system = platform.system().lower()
    if system == "windows":
        return "powershell"
    return "bash"


def _build_shell_command(command: str, shell: str) -> str:
    if shell == "powershell":
        return f'powershell -NoProfile -Command "{command}"'
    elif shell == "cmd":
        return f'cmd /c "{command}"'
    return command
