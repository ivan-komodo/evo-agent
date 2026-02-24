"""Загрузка knowledge-файлов из agent_data/."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class KnowledgeLoader:
    """Загружает markdown-файлы и yaml-конфиг из agent_data/."""

    def __init__(self, agent_data_dir: Path):
        self._dir = agent_data_dir

    def load_file(self, filename: str) -> str | None:
        """Загрузить один файл по имени (agent.md, rules.md и т.д.)."""
        path = self._dir / filename
        if not path.exists():
            logger.warning("Knowledge файл не найден: %s", path)
            return None
        return path.read_text(encoding="utf-8")

    def load_agent(self) -> str:
        return self.load_file("agent.md") or ""

    def load_rules(self) -> str:
        return self.load_file("rules.md") or ""

    def load_memory(self) -> str:
        return self.load_file("memory.md") or ""

    def load_preferences(self) -> dict:
        """Загрузить preferences.yaml."""
        path = self._dir / "preferences.yaml"
        if not path.exists():
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            logger.exception("Ошибка чтения preferences.yaml")
            return {}

    def load_skills_md(self) -> list[tuple[str, str]]:
        """Загрузить все MD-навыки.

        Returns:
            Список кортежей (имя_файла, содержимое)
        """
        skills_dir = self._dir / "skills"
        if not skills_dir.exists():
            return []

        result = []
        for md_file in sorted(skills_dir.glob("*.md")):
            if md_file.name.startswith("_"):
                continue
            content = md_file.read_text(encoding="utf-8")
            result.append((md_file.stem, content))

        logger.info("Загружено %d MD-навыков", len(result))
        return result

    def list_all_files(self) -> list[str]:
        """Список всех файлов в agent_data/ (для интроспекции)."""
        if not self._dir.exists():
            return []
        return [
            str(p.relative_to(self._dir))
            for p in self._dir.rglob("*")
            if p.is_file()
        ]
