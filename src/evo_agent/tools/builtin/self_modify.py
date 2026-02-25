"""Самомодификация -- чтение/запись собственного кода, git, extensions."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from evo_agent.core.types import DangerLevel, ToolResult
from evo_agent.tools.base import BaseTool

logger = logging.getLogger(__name__)


class SelfModifyTool(BaseTool):
    name = "self_modify"
    description = (
        "Самомодификация агента. Позволяет читать и изменять собственный код, "
        "создавать extensions, обновлять knowledge-файлы. "
        "Все изменения автоматически коммитятся в git."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "Действие: read_source, write_source, list_structure, "
                    "create_extension, update_knowledge, restart"
                ),
                "enum": [
                    "read_source", "write_source", "list_structure",
                    "create_extension", "update_knowledge", "restart",
                ],
            },
            "path": {
                "type": "string",
                "description": "Путь к файлу (относительно корня проекта)",
            },
            "content": {
                "type": "string",
                "description": "Содержимое для записи",
            },
            "extension_type": {
                "type": "string",
                "description": "Тип extension: tools, adapters, scripts",
                "enum": ["tools", "adapters", "scripts"],
            },
            "name": {
                "type": "string",
                "description": "Имя файла (без расширения)",
            },
        },
        "required": ["action"],
    }
    danger_level = DangerLevel.DANGEROUS

    def __init__(self, project_root: Path | None = None):
        self._root = project_root or Path.cwd()

    async def execute(self, **kwargs: Any) -> ToolResult:
        action: str = kwargs["action"]
        tid = kwargs.get("tool_call_id", "")

        try:
            if action == "read_source":
                return await self._read_source(kwargs.get("path", ""), tid)
            elif action == "write_source":
                return await self._write_source(
                    kwargs.get("path", ""), kwargs.get("content", ""), tid
                )
            elif action == "list_structure":
                return await self._list_structure(tid)
            elif action == "create_extension":
                return await self._create_extension(
                    kwargs.get("extension_type", "tools"),
                    kwargs.get("name", "unnamed"),
                    kwargs.get("content", ""),
                    tid,
                )
            elif action == "update_knowledge":
                return await self._update_knowledge(
                    kwargs.get("path", ""), kwargs.get("content", ""), tid
                )
            elif action == "restart":
                return await self._request_restart(tid)
            else:
                return self._fail(f"Неизвестное действие: {action}", tid)
        except Exception as e:
            return self._fail(f"Ошибка self_modify ({action}): {e}", tid)

    async def _read_source(self, rel_path: str, tid: str) -> ToolResult:
        path = self._root / rel_path
        if not path.exists():
            return self._fail(f"Файл не найден: {rel_path}", tid)
        if not path.is_file():
            return self._fail(f"Не файл: {rel_path}", tid)
        content = path.read_text(encoding="utf-8")
        if len(content) > 50_000:
            content = content[:50_000] + "\n... (обрезано)"
        return self._ok(content, tid)

    async def _write_source(self, rel_path: str, content: str, tid: str) -> ToolResult:
        if not rel_path:
            return self._fail("Не указан путь", tid)
        path = self._root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        logger.info("Записан файл: %s (%d символов)", rel_path, len(content))

        self._git_commit(f"self-modify: update {rel_path}")
        return self._ok(f"Файл записан: {rel_path} ({len(content)} символов)", tid)

    async def _list_structure(self, tid: str) -> ToolResult:
        lines = []
        for path in sorted(self._root.rglob("*")):
            if any(part.startswith(".") for part in path.parts):
                continue
            if "__pycache__" in str(path):
                continue
            if "node_modules" in str(path):
                continue
            rel = path.relative_to(self._root)
            indent = "  " * (len(rel.parts) - 1)
            prefix = "[DIR] " if path.is_dir() else "[FILE] "
            lines.append(f"{indent}{prefix}{rel.name}")

        return self._ok("\n".join(lines[:200]) if lines else "(пусто)", tid)

    async def _create_extension(
        self, ext_type: str, name: str, content: str, tid: str
    ) -> ToolResult:
        ext_dir = self._root / "extensions" / ext_type
        ext_dir.mkdir(parents=True, exist_ok=True)
        path = ext_dir / f"{name}.py"
        path.write_text(content, encoding="utf-8")
        logger.info("Extension создан: %s/%s.py", ext_type, name)

        self._git_commit(f"self-modify: create extension {ext_type}/{name}")
        return self._ok(
            f"Extension создан: extensions/{ext_type}/{name}.py ({len(content)} символов)", tid
        )

    async def _update_knowledge(self, rel_path: str, content: str, tid: str) -> ToolResult:
        if not rel_path:
            return self._fail("Не указан путь", tid)
        path = self._root / "agent_data" / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        logger.info("Knowledge обновлён: %s", rel_path)

        self._git_commit(f"self-modify: update knowledge {rel_path}")
        return self._ok(f"Knowledge обновлён: agent_data/{rel_path}", tid)

    async def _request_restart(self, tid: str) -> ToolResult:
        return self._ok(
            "Для перезапуска используйте механизм spawn & die (Phase 3). "
            "Сейчас перезапуск требует ручного действия.",
            tid,
        )

    def _git_commit(self, message: str) -> None:
        """Авто-коммит изменений."""
        try:
            import git
            repo = git.Repo(self._root)
            repo.git.add(A=True)
            if repo.is_dirty(untracked_files=True):
                repo.index.commit(message)
                logger.info("Git commit: %s", message)
        except ImportError:
            logger.warning("gitpython не установлен, коммит пропущен")
        except Exception:
            logger.exception("Ошибка git commit")
