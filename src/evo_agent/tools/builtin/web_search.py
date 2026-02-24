"""Поиск в вебе через API (Brave Search, SearXNG, Google Custom Search)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from evo_agent.core.types import DangerLevel, ToolResult
from evo_agent.tools.base import BaseTool

logger = logging.getLogger(__name__)


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Поиск информации в интернете. Возвращает список результатов: "
        "заголовок, URL и краткое описание. "
        "Полезно для поиска документации, решений проблем, актуальной информации."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Поисковый запрос",
            },
            "max_results": {
                "type": "integer",
                "description": "Максимальное количество результатов (по умолчанию 5)",
            },
        },
        "required": ["query"],
    }
    danger_level = DangerLevel.SAFE

    def __init__(
        self,
        provider: str = "brave",
        api_key: str = "",
        searxng_url: str = "",
    ):
        self._provider = provider
        self._api_key = api_key
        self._searxng_url = searxng_url

    async def execute(self, **kwargs: Any) -> ToolResult:
        query: str = kwargs["query"]
        max_results: int = kwargs.get("max_results", 5)
        tid = kwargs.get("tool_call_id", "")

        logger.info("WebSearch [%s]: %s", self._provider, query)

        try:
            if self._provider == "brave":
                return await self._search_brave(query, max_results, tid)
            elif self._provider == "searxng":
                return await self._search_searxng(query, max_results, tid)
            else:
                return self._fail(f"Неизвестный провайдер поиска: {self._provider}", tid)
        except Exception as e:
            return self._fail(f"Ошибка поиска: {e}", tid)

    async def _search_brave(self, query: str, max_results: int, tid: str) -> ToolResult:
        if not self._api_key:
            return self._fail("API ключ Brave Search не задан", tid)

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": max_results},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self._api_key,
                },
            )
            resp.raise_for_status()

        data = resp.json()
        results = data.get("web", {}).get("results", [])
        return self._format_results(results, query, tid)

    async def _search_searxng(self, query: str, max_results: int, tid: str) -> ToolResult:
        if not self._searxng_url:
            return self._fail("URL SearXNG не задан", tid)

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self._searxng_url}/search",
                params={"q": query, "format": "json", "pageno": 1},
            )
            resp.raise_for_status()

        data = resp.json()
        results = data.get("results", [])[:max_results]

        formatted = [f"Результаты поиска: **{query}**\n"]
        for i, r in enumerate(results, 1):
            formatted.append(
                f"{i}. **{r.get('title', 'Без заголовка')}**\n"
                f"   URL: {r.get('url', '')}\n"
                f"   {r.get('content', '')}\n"
            )

        if not results:
            return self._ok("Ничего не найдено", tid)
        return self._ok("\n".join(formatted), tid)

    def _format_results(self, results: list[dict], query: str, tid: str) -> ToolResult:
        formatted = [f"Результаты поиска: **{query}**\n"]
        for i, r in enumerate(results, 1):
            formatted.append(
                f"{i}. **{r.get('title', 'Без заголовка')}**\n"
                f"   URL: {r.get('url', '')}\n"
                f"   {r.get('description', '')}\n"
            )
        if not results:
            return self._ok("Ничего не найдено", tid)
        return self._ok("\n".join(formatted), tid)
