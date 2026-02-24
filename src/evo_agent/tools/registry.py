"""Реестр инструментов с авто-обнаружением."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

from evo_agent.tools.base import BaseTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Управление инструментами агента.

    Загружает builtin tools, extensions/tools/, skills/*.py.
    Поддерживает hot-reload.
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    @property
    def tools(self) -> dict[str, BaseTool]:
        return dict(self._tools)

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool
        logger.info("Tool зарегистрирован: %s (danger=%d)", tool.name, tool.danger_level)

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_names(self) -> list[str]:
        return list(self._tools.keys())

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Все tools в формате OpenAI function calling."""
        return [tool.to_openai_schema() for tool in self._tools.values()]

    def load_builtin(self, config: dict[str, Any] | None = None) -> None:
        """Загрузить встроенные инструменты."""
        from evo_agent.tools.builtin.shell import ShellTool
        from evo_agent.tools.builtin.file_ops import FileOpsTool
        from evo_agent.tools.builtin.web_fetch import WebFetchTool

        cfg = config or {}
        tools_cfg = cfg.get("tools", {})

        shell_cfg = tools_cfg.get("shell", {})
        self.register(ShellTool(
            default_shell=shell_cfg.get("default_shell"),
            default_timeout=shell_cfg.get("timeout", 60),
            default_cwd=shell_cfg.get("working_directory"),
        ))

        web_cfg = tools_cfg.get("web_fetch", {})
        self.register(WebFetchTool(
            user_agent=web_cfg.get("user_agent", "EvoAgent/1.0"),
            default_timeout=web_cfg.get("timeout", 30),
        ))

        self.register(FileOpsTool())

        self._load_optional_builtin(tools_cfg)

    def load_extensions(self, extensions_dir: Path) -> None:
        """Загрузить пользовательские tools из extensions/tools/."""
        tools_dir = extensions_dir / "tools"
        if not tools_dir.exists():
            return

        for py_file in tools_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"ext_tool_{py_file.stem}", py_file
                )
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    if hasattr(module, "register"):
                        for tool in module.register():
                            self.register(tool)
                        logger.info("Extension загружен: %s", py_file.name)
            except Exception:
                logger.exception("Ошибка загрузки extension %s", py_file)

    def _load_optional_builtin(self, tools_cfg: dict[str, Any]) -> None:
        """Загрузить опциональные builtin tools на основе конфигурации."""
        web_search_cfg = tools_cfg.get("web_search", {})
        if web_search_cfg.get("enabled"):
            from evo_agent.tools.builtin.web_search import WebSearchTool
            self.register(WebSearchTool(
                provider=web_search_cfg.get("provider", "brave"),
                api_key=web_search_cfg.get("api_key", ""),
                searxng_url=web_search_cfg.get("searxng_url", ""),
            ))

        web_browser_cfg = tools_cfg.get("web_browser", {})
        if web_browser_cfg.get("enabled"):
            try:
                from evo_agent.tools.builtin.web_browser import WebBrowserTool
                self.register(WebBrowserTool())
            except ImportError:
                logger.warning("Playwright не установлен, web_browser недоступен")

    def load_self_modify(self, project_root: Path) -> None:
        """Загрузить tool самомодификации."""
        from evo_agent.tools.builtin.self_modify import SelfModifyTool
        self.register(SelfModifyTool(project_root=project_root))

    def load_people_tool(self, people_db: Any) -> None:
        """Загрузить tool для работы с людьми."""
        from evo_agent.tools.builtin.people import PeopleTool
        self.register(PeopleTool(people_db=people_db))

    def load_skills(self, skills_dir: Path) -> None:
        """Загрузить Python skills из agent_data/skills/."""
        from evo_agent.knowledge.skill_loader import SkillLoader
        loader = SkillLoader(skills_dir)
        for tool in loader.load_all():
            self.register(tool)

    def reload(
        self,
        config: dict[str, Any] | None = None,
        extensions_dir: Path | None = None,
        skills_dir: Path | None = None,
    ) -> None:
        """Полная перезагрузка реестра."""
        self._tools.clear()
        self.load_builtin(config)
        if extensions_dir:
            self.load_extensions(extensions_dir)
        if skills_dir:
            self.load_skills(skills_dir)
        logger.info("Tool реестр перезагружен: %d tools", len(self._tools))
