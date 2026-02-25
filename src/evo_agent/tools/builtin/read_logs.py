from __future__ import annotations

import logging
from typing import Any
from pathlib import Path
from evo_agent.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

class ReadLogsTool(BaseTool):
    """Инструмент для чтения логов агента."""
    
    name = "read_logs"
    description = "Прочитать последние записи из логов агента. Используй для диагностики ошибок и проблем."
    parameters = {
        "lines": {"type": "integer", "default": 50, "description": "Количество строк"},
        "level": {"type": "string", "enum": ["all", "error", "warning"], "default": "all"},
        "search": {"type": "string", "description": "Фильтр по подстроке (опционально)"},
    }
    
    def __init__(self, log_file: Path):
        super().__init__()
        self._log_file = log_file

    async def execute(self, lines: int = 50, level: str = "all", search: str | None = None, **kwargs: Any) -> ToolResult:
        if not self._log_file.exists():
            return ToolResult(content=f"Файл лога не найден: {self._log_file}", success=False)
        
        try:
            with open(self._log_file, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
            
            # Фильтрация по уровню
            if level != "all":
                level_tag = f"[{level.upper()}]"
                all_lines = [line for line in all_lines if level_tag in line]
            
            # Фильтрация по поиску
            if search:
                all_lines = [line for line in all_lines if search.lower() in line.lower()]
            
            # Берем последние N строк
            result_lines = all_lines[-lines:]
            content = "".join(result_lines)
            
            if not content:
                return ToolResult(content="Записей не найдено по вашему запросу.")
                
            return ToolResult(content=content)
        except Exception as e:
            return ToolResult(content=f"Ошибка при чтении логов: {e}", success=False)
