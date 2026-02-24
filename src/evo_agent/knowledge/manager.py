"""CRUD-менеджер для knowledge-файлов."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class KnowledgeManager:
    """Управление knowledge-файлами агента (CRUD)."""

    def __init__(self, agent_data_dir: Path):
        self._dir = agent_data_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def update_memory(self, content: str, append: bool = True) -> None:
        """Обновить memory.md. По умолчанию дописывает в конец."""
        path = self._dir / "memory.md"
        if append and path.exists():
            existing = path.read_text(encoding="utf-8")
            content = existing.rstrip() + "\n\n" + content
        path.write_text(content, encoding="utf-8")
        logger.info("memory.md обновлён")

    def update_rules(self, content: str) -> None:
        """Перезаписать rules.md."""
        path = self._dir / "rules.md"
        path.write_text(content, encoding="utf-8")
        logger.info("rules.md обновлён")

    def add_skill_md(self, name: str, content: str) -> Path:
        """Создать или обновить MD-навык."""
        skills_dir = self._dir / "skills"
        skills_dir.mkdir(exist_ok=True)
        path = skills_dir / f"{name}.md"
        path.write_text(content, encoding="utf-8")
        logger.info("Навык создан/обновлён: %s", path)
        return path

    def remove_skill(self, name: str) -> bool:
        """Удалить навык (MD или PY)."""
        skills_dir = self._dir / "skills"
        for ext in (".md", ".py"):
            path = skills_dir / f"{name}{ext}"
            if path.exists():
                path.unlink()
                logger.info("Навык удалён: %s", path)
                return True
        return False

    def update_preferences(self, updates: dict) -> None:
        """Обновить отдельные поля в preferences.yaml."""
        path = self._dir / "preferences.yaml"
        current = {}
        if path.exists():
            with open(path, encoding="utf-8") as f:
                current = yaml.safe_load(f) or {}

        _deep_merge(current, updates)

        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(current, f, allow_unicode=True, default_flow_style=False)
        logger.info("preferences.yaml обновлён")

    def read_file(self, relative_path: str) -> str | None:
        """Прочитать любой файл из agent_data/."""
        path = self._dir / relative_path
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def write_file(self, relative_path: str, content: str) -> Path:
        """Записать файл в agent_data/."""
        path = self._dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path


def _deep_merge(base: dict, override: dict) -> None:
    """Рекурсивный мерж словарей."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
