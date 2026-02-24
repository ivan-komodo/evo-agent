"""ReAct fallback для LLM-провайдеров без поддержки function calling.

Описывает tools в system prompt текстом, парсит ответ в формате
Thought -> Action -> Action Input -> Observation.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from evo_agent.core.types import LLMResponse, Message, ToolCall
from evo_agent.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_REACT_SYSTEM_SUFFIX = """
Ты используешь инструменты в формате ReAct. Доступные инструменты:

{tools_description}

Для вызова инструмента используй СТРОГО следующий формат:

Thought: <твоё рассуждение>
Action: <имя_инструмента>
Action Input: <JSON аргументов>

Если инструмент не нужен и ты готов ответить пользователю:

Thought: <рассуждение>
Final Answer: <ответ пользователю>
"""


class ReActWrapper(LLMProvider):
    """Обёртка вокруг любого LLMProvider, добавляющая ReAct-парсинг.

    Используется когда провайдер не поддерживает native function calling.
    """

    name = "react_fallback"

    def __init__(self, inner: LLMProvider):
        self._inner = inner

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        if tools:
            tools_desc = _format_tools_for_prompt(tools)
            messages = _inject_react_prompt(messages, tools_desc)

        response = await self._inner.chat(messages, tools=None)

        if tools and response.text:
            parsed = _parse_react_response(response.text)
            if parsed:
                return parsed

        return response

    async def close(self) -> None:
        await self._inner.close()


def _format_tools_for_prompt(tools: list[dict[str, Any]]) -> str:
    """Форматировать tools в текстовое описание для system prompt."""
    lines = []
    for tool in tools:
        func = tool.get("function", {})
        name = func.get("name", "unknown")
        desc = func.get("description", "")
        params = func.get("parameters", {})
        props = params.get("properties", {})
        required = params.get("required", [])

        param_lines = []
        for pname, pinfo in props.items():
            req = " (обязательный)" if pname in required else ""
            ptype = pinfo.get("type", "string")
            pdesc = pinfo.get("description", "")
            param_lines.append(f"    - {pname} ({ptype}{req}): {pdesc}")

        lines.append(f"- **{name}**: {desc}")
        if param_lines:
            lines.append("  Параметры:")
            lines.extend(param_lines)

    return "\n".join(lines)


def _inject_react_prompt(messages: list[Message], tools_desc: str) -> list[Message]:
    """Добавить ReAct-инструкции в system prompt."""
    react_suffix = _REACT_SYSTEM_SUFFIX.format(tools_description=tools_desc)

    new_messages = list(messages)
    if new_messages and new_messages[0].role == "system":
        original = new_messages[0].content or ""
        new_messages[0] = Message(
            role="system",
            content=original + "\n\n" + react_suffix,
        )
    else:
        new_messages.insert(0, Message(role="system", content=react_suffix))

    return new_messages


def _parse_react_response(text: str) -> LLMResponse | None:
    """Извлечь Action и Action Input из ReAct-ответа."""
    final_match = re.search(r"Final Answer:\s*(.+)", text, re.DOTALL)
    if final_match:
        return LLMResponse(text=final_match.group(1).strip())

    action_match = re.search(r"Action:\s*(\S+)", text)
    input_match = re.search(r"Action Input:\s*(.+?)(?:\n(?:Thought|Action|$)|\Z)", text, re.DOTALL)

    if action_match:
        action_name = action_match.group(1).strip()
        arguments = {}

        if input_match:
            raw_input = input_match.group(1).strip()
            try:
                arguments = json.loads(raw_input)
            except json.JSONDecodeError:
                arguments = {"input": raw_input}

        thought = ""
        thought_match = re.search(r"Thought:\s*(.+?)(?:\nAction:|\Z)", text, re.DOTALL)
        if thought_match:
            thought = thought_match.group(1).strip()

        tool_call = ToolCall(
            id=f"react_{action_name}",
            name=action_name,
            arguments=arguments,
        )

        return LLMResponse(
            text=thought if thought else None,
            tool_calls=[tool_call],
        )

    return None
