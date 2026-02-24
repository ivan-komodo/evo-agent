"""Загрузка Python-навыков: парсинг type hints и docstrings в JSON Schema."""

from __future__ import annotations

import ast
import importlib.util
import inspect
import logging
from pathlib import Path
from typing import Any, Callable, get_type_hints

from evo_agent.core.types import DangerLevel, ToolResult
from evo_agent.tools.base import BaseTool

logger = logging.getLogger(__name__)

_TYPE_MAP = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "list": "array",
    "dict": "object",
}


class PythonSkillTool(BaseTool):
    """Обёртка для Python-функции как tool."""

    danger_level = DangerLevel.SAFE

    def __init__(self, func: Callable, schema: dict[str, Any]):
        self.name = func.__name__
        self.description = (func.__doc__ or "").strip().split("\n")[0]
        self.parameters = schema
        self._func = func

    async def execute(self, **kwargs: Any) -> ToolResult:
        tid = kwargs.pop("tool_call_id", "")
        try:
            result = self._func(**kwargs)
            if inspect.isawaitable(result):
                result = await result
            return self._ok(str(result), tid)
        except Exception as e:
            return self._fail(f"Ошибка skill {self.name}: {e}", tid)


class SkillLoader:
    """Загружает *.py из agent_data/skills/ и парсит в tools."""

    def __init__(self, skills_dir: Path):
        self._dir = skills_dir

    def load_all(self) -> list[BaseTool]:
        """Загрузить все Python skills."""
        if not self._dir.exists():
            return []

        tools = []
        for py_file in sorted(self._dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                loaded = self._load_file(py_file)
                tools.extend(loaded)
                logger.info("Skill загружен: %s (%d tools)", py_file.name, len(loaded))
            except Exception:
                logger.exception("Ошибка загрузки skill %s", py_file)

        return tools

    def _load_file(self, path: Path) -> list[BaseTool]:
        """Загрузить один Python-файл и извлечь tools из функций."""
        spec = importlib.util.spec_from_file_location(f"skill_{path.stem}", path)
        if not spec or not spec.loader:
            return []

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        tools = []
        for name, obj in inspect.getmembers(module, inspect.isfunction):
            if name.startswith("_"):
                continue
            schema = _function_to_schema(obj)
            if schema:
                tools.append(PythonSkillTool(func=obj, schema=schema))

        return tools


def _function_to_schema(func: Callable) -> dict[str, Any] | None:
    """Конвертировать type hints функции в JSON Schema."""
    try:
        sig = inspect.signature(func)
    except (ValueError, TypeError):
        return None

    hints = {}
    try:
        hints = get_type_hints(func)
    except Exception:
        pass

    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls", "tool_call_id"):
            continue

        type_hint = hints.get(param_name)
        type_name = _python_type_to_json(type_hint)

        prop: dict[str, Any] = {"type": type_name}

        if param.default is inspect.Parameter.empty:
            required.append(param_name)
        else:
            prop["default"] = param.default

        properties[param_name] = prop

    if not properties:
        return {"type": "object", "properties": {}}

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required

    return schema


def _python_type_to_json(type_hint: Any) -> str:
    """Конвертировать Python-тип в JSON Schema тип."""
    if type_hint is None:
        return "string"

    type_name = getattr(type_hint, "__name__", str(type_hint))
    return _TYPE_MAP.get(type_name, "string")
