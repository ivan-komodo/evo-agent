"""HTTP GET с парсингом HTML в markdown."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as md

from evo_agent.core.types import DangerLevel, ToolResult
from evo_agent.tools.base import BaseTool

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30
_MAX_CONTENT_LENGTH = 30_000


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = (
        "Загрузить веб-страницу по URL и вернуть содержимое в формате markdown. "
        "Полезно для чтения документации, статей и другого текстового контента."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL страницы для загрузки",
            },
            "timeout": {
                "type": "integer",
                "description": f"Таймаут в секундах (по умолчанию {_DEFAULT_TIMEOUT})",
            },
        },
        "required": ["url"],
    }
    danger_level = DangerLevel.SAFE

    def __init__(
        self,
        user_agent: str = "EvoAgent/1.0",
        default_timeout: int = _DEFAULT_TIMEOUT,
    ):
        self._user_agent = user_agent
        self._default_timeout = default_timeout

    async def execute(self, **kwargs: Any) -> ToolResult:
        url: str = kwargs["url"]
        timeout = kwargs.get("timeout", self._default_timeout)
        tool_call_id = kwargs.get("tool_call_id", "")

        logger.info("WebFetch: %s", url)

        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": self._user_agent},
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")

            if "text/html" in content_type:
                text = _html_to_markdown(resp.text)
            else:
                text = resp.text

            if len(text) > _MAX_CONTENT_LENGTH:
                text = text[:_MAX_CONTENT_LENGTH] + "\n\n... (обрезано)"

            return self._ok(f"URL: {url}\n\n{text}", tool_call_id)

        except httpx.HTTPStatusError as e:
            return self._fail(f"HTTP ошибка {e.response.status_code}: {url}", tool_call_id)
        except Exception as e:
            return self._fail(f"Ошибка загрузки {url}: {e}", tool_call_id)


def _html_to_markdown(html: str) -> str:
    """Конвертация HTML в чистый markdown."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    text = md(str(soup), heading_style="ATX", strip=["img"])

    lines = text.split("\n")
    cleaned = []
    blank_count = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            blank_count += 1
            if blank_count <= 2:
                cleaned.append("")
        else:
            blank_count = 0
            cleaned.append(line)

    return "\n".join(cleaned).strip()
