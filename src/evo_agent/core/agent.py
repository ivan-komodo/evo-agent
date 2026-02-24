"""Главный цикл агента (think -> act -> observe)."""

from __future__ import annotations

import logging
import traceback
from typing import Any

from evo_agent.core.autonomy import AutonomyManager
from evo_agent.core.context import ContextBuilder
from evo_agent.core.types import (
    AutonomyLevel,
    Message,
    ToolCall,
    ToolResult,
    UserInfo,
)
from evo_agent.interfaces.base import BaseInterface
from evo_agent.knowledge.loader import KnowledgeLoader
from evo_agent.knowledge.manager import KnowledgeManager
from evo_agent.llm.base import LLMProvider
from evo_agent.memory.conversation import ConversationStore
from evo_agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class Agent:
    """Главный агент -- оркестрирует все компоненты."""

    def __init__(
        self,
        llm: LLMProvider,
        tool_registry: ToolRegistry,
        knowledge_loader: KnowledgeLoader,
        knowledge_manager: KnowledgeManager,
        autonomy: AutonomyManager,
        interface: BaseInterface,
        conversation_store: ConversationStore | None = None,
        max_iterations: int = 25,
    ):
        self._llm = llm
        self._tools = tool_registry
        self._knowledge_loader = knowledge_loader
        self._knowledge_manager = knowledge_manager
        self._autonomy = autonomy
        self._interface = interface
        self._conversation_store = conversation_store
        self._max_iterations = max_iterations

        self._context_builder = ContextBuilder(
            knowledge_loader=knowledge_loader,
            tool_names=tool_registry.list_names(),
        )

        self._conversations: dict[str, list[Message]] = {}

    async def start(self) -> None:
        """Запустить агента."""

        async def _approval_callback(user_id: str, tool_call: ToolCall) -> bool:
            tool = self._tools.get(tool_call.name)
            danger = tool.danger_level if tool else 0
            question = self._autonomy.format_approval_message(tool_call, danger)
            return await self._interface.ask_approval(user_id, question)

        self._autonomy.set_approval_callback(_approval_callback)
        await self._interface.start(on_message=self._handle_message)
        logger.info("Агент запущен")

    async def stop(self) -> None:
        """Остановить агента."""
        if self._conversation_store:
            for user_id, msgs in self._conversations.items():
                try:
                    await self._conversation_store.save_conversation(user_id, msgs)
                except Exception:
                    logger.exception("Ошибка сохранения диалога user=%s", user_id)

        await self._interface.stop()
        logger.info("Агент остановлен")

    async def _handle_message(self, text: str, user_info: UserInfo) -> None:
        """Обработка входящего сообщения с полной обработкой ошибок."""
        user_id = user_info.user_id

        try:
            await self._process_message(text, user_info)
        except Exception as e:
            logger.exception("Необработанная ошибка при обработке сообщения от %s", user_id)
            try:
                await self._interface.send_message(
                    user_id,
                    f"Произошла внутренняя ошибка. Подробности в логах.\n`{type(e).__name__}: {e}`",
                )
            except Exception:
                logger.exception("Не удалось даже отправить сообщение об ошибке")

    async def _process_message(self, text: str, user_info: UserInfo) -> None:
        """Логика обработки (без верхнего try/catch)."""
        user_id = user_info.user_id

        if text.startswith("__set_autonomy:"):
            level = int(text.split(":")[1])
            self._autonomy.level = level
            self._knowledge_manager.update_preferences({"agent": {"autonomy_level": level}})
            return

        if text == "__get_status":
            status = self._build_status()
            await self._interface.send_message(user_id, status)
            return

        if text == "__list_skills":
            skills = self._knowledge_loader.load_skills_md()
            if skills:
                lines = ["**Навыки:**"]
                for name, _ in skills:
                    lines.append(f"- {name}")
                await self._interface.send_message(user_id, "\n".join(lines))
            else:
                await self._interface.send_message(user_id, "Навыков пока нет.")
            return

        if text == "__show_memory":
            memory = self._knowledge_loader.load_memory()
            await self._interface.send_message(user_id, memory or "Память пуста.")
            return

        logger.info("Сообщение от %s (%s): %s",
                     user_info.name or "?", user_id, text[:100])

        conversation = self._conversations.setdefault(user_id, [])
        user_msg = Message(role="user", content=text)
        conversation.append(user_msg)

        if self._conversation_store:
            await self._conversation_store.save_message(user_id, user_msg)

        await self._run_agent_loop(user_id, user_info, conversation)

    async def _run_agent_loop(
        self,
        user_id: str,
        user_info: UserInfo,
        conversation: list[Message],
    ) -> None:
        """Цикл think-act-observe."""
        system_prompt = self._context_builder.build_system_prompt(user_info)
        tools_schema = self._tools.to_openai_tools()

        for iteration in range(self._max_iterations):
            messages = self._context_builder.build_messages(system_prompt, conversation)

            try:
                response = await self._llm.chat(messages, tools_schema if tools_schema else None)
            except Exception as e:
                logger.exception("Ошибка LLM на итерации %d", iteration)
                await self._interface.send_message(
                    user_id,
                    f"Ошибка при обращении к LLM: `{type(e).__name__}: {e}`\n"
                    "Попробуйте ещё раз или проверьте конфигурацию.",
                )
                return

            if response.has_tool_calls:
                assistant_msg = Message(
                    role="assistant",
                    content=response.text,
                    tool_calls=response.tool_calls,
                )
                conversation.append(assistant_msg)

                if self._conversation_store:
                    await self._conversation_store.save_message(user_id, assistant_msg)

                for tool_call in response.tool_calls:
                    result = await self._execute_tool(user_id, tool_call)
                    tool_msg = Message(
                        role="tool",
                        content=result.content,
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                    )
                    conversation.append(tool_msg)

                    if self._conversation_store:
                        await self._conversation_store.save_message(user_id, tool_msg)
                continue

            if response.text:
                assistant_msg = Message(role="assistant", content=response.text)
                conversation.append(assistant_msg)
                if self._conversation_store:
                    await self._conversation_store.save_message(user_id, assistant_msg)
                await self._interface.send_message(user_id, response.text)
                return

            await self._interface.send_message(user_id, "(пустой ответ от LLM)")
            return

        await self._interface.send_message(
            user_id, f"⚠️ Достигнут лимит итераций ({self._max_iterations})"
        )

    async def _execute_tool(self, user_id: str, tool_call: ToolCall) -> ToolResult:
        """Выполнить инструмент с проверкой автономности."""
        tool = self._tools.get(tool_call.name)
        if tool is None:
            logger.warning("Инструмент не найден: %s", tool_call.name)
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=f"Инструмент '{tool_call.name}' не найден. "
                        f"Доступные: {', '.join(self._tools.list_names())}",
                success=False,
            )

        approved = await self._autonomy.request_approval(
            user_id, tool_call, tool.danger_level
        )
        if not approved:
            logger.info("Tool %s отклонён пользователем", tool_call.name)
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content="Действие отклонено пользователем. Попробуй другой подход.",
                success=False,
            )

        logger.info("Выполняю tool: %s(%s)", tool_call.name,
                     ", ".join(f"{k}={v!r}" for k, v in list(tool_call.arguments.items())[:3]))
        try:
            result = await tool.execute(tool_call_id=tool_call.id, **tool_call.arguments)
            log_level = logging.INFO if result.success else logging.WARNING
            logger.log(log_level, "Tool %s: success=%s, len=%d",
                       tool_call.name, result.success, len(result.content))
            return result
        except Exception as e:
            logger.exception("Ошибка выполнения tool %s", tool_call.name)
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=f"Ошибка выполнения: {type(e).__name__}: {e}",
                success=False,
            )

    def _build_status(self) -> str:
        """Сформировать статус агента."""
        prefs = self._knowledge_loader.load_preferences()
        agent_prefs = prefs.get("agent", {})
        tools = self._tools.list_names()
        skills = self._knowledge_loader.load_skills_md()

        return (
            f"**Статус Evo-Agent**\n"
            f"- Имя: {agent_prefs.get('name', 'Evo')}\n"
            f"- Автономность: {self._autonomy.level.value} ({self._autonomy.level.name})\n"
            f"- Инструменты ({len(tools)}): {', '.join(tools)}\n"
            f"- Навыки: {len(skills)}\n"
            f"- Активных диалогов: {len(self._conversations)}\n"
            f"- Макс. итераций: {self._max_iterations}\n"
        )
