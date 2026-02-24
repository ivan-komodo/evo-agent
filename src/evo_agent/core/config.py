"""Загрузка и резолв конфигурации."""

from __future__ import annotations

import os
import re
import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_ENV_PATTERN = re.compile(r"\$\{(\w+)\}")


def load_config(config_path: Path | str = "config.yaml") -> dict[str, Any]:
    """Загрузить config.yaml с подстановкой переменных окружения."""
    config_path = Path(config_path)
    if not config_path.exists():
        logger.warning("Конфиг не найден: %s, используем значения по умолчанию", config_path)
        return {}

    with open(config_path, encoding="utf-8") as f:
        raw = f.read()

    resolved = _resolve_env_vars(raw)

    try:
        config = yaml.safe_load(resolved) or {}
    except yaml.YAMLError:
        logger.exception("Ошибка парсинга config.yaml")
        return {}

    return config


def _resolve_env_vars(text: str) -> str:
    """Заменить ${VAR_NAME} на значения из os.environ."""
    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        value = os.environ.get(var_name, "")
        if not value:
            logger.warning("Переменная окружения %s не задана", var_name)
        return value

    return _ENV_PATTERN.sub(replacer, text)


def get_project_root() -> Path:
    """Определить корень проекта (где лежит config.yaml или pyproject.toml)."""
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / "config.yaml").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()
