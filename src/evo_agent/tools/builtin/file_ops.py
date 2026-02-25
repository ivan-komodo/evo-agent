"""Операции с файловой системой."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from evo_agent.core.types import DangerLevel, ToolResult
from evo_agent.tools.base import BaseTool

logger = logging.getLogger(__name__)


class FileOpsTool(BaseTool):
    name = "file_ops"
    description = (
        "Операции с файловой системой: чтение, запись, добавление, "
        "листинг директорий и поиск файлов."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Действие: read, write, append, list_dir, search",
                "enum": ["read", "write", "append", "list_dir", "search"],
            },
            "path": {
                "type": "string",
                "description": "Путь к файлу или директории",
            },
            "content": {
                "type": "string",
                "description": "Содержимое для записи (action=write/append)",
            },
            "pattern": {
                "type": "string",
                "description": "Glob-паттерн для поиска (action=search)",
            },
        },
        "required": ["action", "path"],
    }
    danger_level = DangerLevel.MODERATE

    async def execute(self, **kwargs: Any) -> ToolResult:
        action: str = kwargs["action"]
        path_str: str = kwargs["path"]
        tool_call_id = kwargs.get("tool_call_id", "")
        path = Path(path_str)

        try:
            if action == "read":
                return await self._read(path, tool_call_id)
            elif action == "write":
                return await self._write(path, kwargs.get("content", ""), tool_call_id)
            elif action == "append":
                return await self._append(path, kwargs.get("content", ""), tool_call_id)
            elif action == "list_dir":
                return await self._list_dir(path, tool_call_id)
            elif action == "search":
                pattern = kwargs.get("pattern", "*")
                return await self._search(path, pattern, tool_call_id)
            else:
                return self._fail(f"Неизвестное действие: {action}", tool_call_id)
        except Exception as e:
            return self._fail(f"Ошибка file_ops ({action}): {e}", tool_call_id)

    async def _read(self, path: Path, tid: str) -> ToolResult:
        if not path.exists():
            return self._fail(f"Файл не найден: {path}", tid)
        content = path.read_text(encoding="utf-8")
        if len(content) > 50_000:
            content = content[:50_000] + "\n\n... (обрезано, файл слишком большой)"
        return self._ok(content, tid)

    async def _write(self, path: Path, content: str, tid: str) -> ToolResult:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        logger.info("Файл записан: %s (%d символов)", path, len(content))
        return self._ok(f"Файл записан: {path} ({len(content)} символов)", tid)

    async def _append(self, path: Path, content: str, tid: str) -> ToolResult:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(content)
        logger.info("Дописано в файл: %s (%d символов)", path, len(content))
        return self._ok(f"Дописано в файл: {path} ({len(content)} символов)", tid)

    async def _list_dir(self, path: Path, tid: str) -> ToolResult:
        if not path.exists():
            return self._fail(f"Директория не найдена: {path}", tid)
        entries = []
        for entry in sorted(path.iterdir()):
            prefix = "[DIR]  " if entry.is_dir() else "[FILE] "
            entries.append(f"{prefix}{entry.name}")
        if not entries:
            return self._ok("(пустая директория)", tid)
        return self._ok("\n".join(entries), tid)

    async def _search(self, path: Path, pattern: str, tid: str) -> ToolResult:
        if not path.exists():
            return self._fail(f"Директория не найдена: {path}", tid)
        matches = list(path.rglob(pattern))
        if not matches:
            return self._ok(f"Ничего не найдено по паттерну '{pattern}'", tid)
        lines = [str(m.relative_to(path)) for m in matches[:100]]
        result = "\n".join(lines)
        if len(matches) > 100:
            result += f"\n\n... и ещё {len(matches) - 100} файлов"
        return self._ok(result, tid)
