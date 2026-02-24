"""Headless browser через Playwright (опциональная зависимость)."""

from __future__ import annotations

import logging
from typing import Any

from evo_agent.core.types import DangerLevel, ToolResult
from evo_agent.tools.base import BaseTool

logger = logging.getLogger(__name__)


class WebBrowserTool(BaseTool):
    name = "web_browser"
    description = (
        "Открыть веб-страницу в headless браузере (Playwright). "
        "Для JS-heavy страниц, которые не рендерятся через простой HTTP GET. "
        "Поддерживает навигацию, извлечение контента и скриншоты."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Действие: navigate, get_content, screenshot",
                "enum": ["navigate", "get_content", "screenshot"],
            },
            "url": {
                "type": "string",
                "description": "URL для навигации",
            },
            "screenshot_path": {
                "type": "string",
                "description": "Путь для сохранения скриншота",
            },
        },
        "required": ["action"],
    }
    danger_level = DangerLevel.MODERATE

    def __init__(self) -> None:
        self._browser = None
        self._page = None

    async def execute(self, **kwargs: Any) -> ToolResult:
        action: str = kwargs["action"]
        tid = kwargs.get("tool_call_id", "")

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return self._fail(
                "Playwright не установлен. Установите: pip install playwright && playwright install chromium",
                tid,
            )

        try:
            if action == "navigate":
                return await self._navigate(kwargs.get("url", ""), tid)
            elif action == "get_content":
                return await self._get_content(tid)
            elif action == "screenshot":
                return await self._screenshot(kwargs.get("screenshot_path", "screenshot.png"), tid)
            else:
                return self._fail(f"Неизвестное действие: {action}", tid)
        except Exception as e:
            return self._fail(f"Ошибка браузера: {e}", tid)

    async def _ensure_browser(self) -> None:
        if self._browser is None:
            from playwright.async_api import async_playwright
            pw = await async_playwright().start()
            self._browser = await pw.chromium.launch(headless=True)
            self._page = await self._browser.new_page()

    async def _navigate(self, url: str, tid: str) -> ToolResult:
        if not url:
            return self._fail("URL не указан", tid)
        await self._ensure_browser()
        await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        title = await self._page.title()
        return self._ok(f"Страница загружена: {title}\nURL: {url}", tid)

    async def _get_content(self, tid: str) -> ToolResult:
        if self._page is None:
            return self._fail("Сначала выполните navigate", tid)
        content = await self._page.content()
        from markdownify import markdownify as md
        text = md(content, heading_style="ATX", strip=["img", "script", "style"])
        if len(text) > 30_000:
            text = text[:30_000] + "\n... (обрезано)"
        return self._ok(text, tid)

    async def _screenshot(self, path: str, tid: str) -> ToolResult:
        if self._page is None:
            return self._fail("Сначала выполните navigate", tid)
        await self._page.screenshot(path=path, full_page=True)
        return self._ok(f"Скриншот сохранён: {path}", tid)

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
            self._page = None
