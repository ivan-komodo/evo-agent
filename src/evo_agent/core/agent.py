"""Главный цикл агента (think -> act -> observe)."""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Any

from evo_agent.core.action_journal import ActionJournal, JournalEntry
from evo_agent.core.autonomy import AutonomyManager
from evo_agent.core.context import ContextBuilder
from evo_agent.core.monitor import AgentMonitor
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
from evo_agent.memory.summarizer import ConversationSummarizer
from evo_agent.scheduler.store import ScheduledTask, SchedulerStore
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
        summarizer: ConversationSummarizer | None = None,
        monitor: AgentMonitor | None = None,
        journal: ActionJournal | None = None,
        scheduler_store: SchedulerStore | None = None,
        max_iterations: int = 25,
    ):
        self._llm = llm
        self._tools = tool_registry
        self._knowledge_loader = knowledge_loader
        self._knowledge_manager = knowledge_manager
        self._autonomy = autonomy
        self._interface = interface
        self._conversation_store = conversation_store
        self._summarizer = summarizer
        self._monitor = monitor
        self._journal = journal
        self._scheduler_store = scheduler_store
        self._max_iterations = max_iterations

        self._context_builder = ContextBuilder(
            knowledge_loader=knowledge_loader,
            tool_registry=tool_registry,
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

    async def reload_tools(self) -> str:
        """Перезагрузить инструменты без рестарта агента."""
        count = self._tools.full_reload()
        return f"Инструменты перезагружены: {count} штук ({', '.join(self._tools.list_names())})"

    async def reload_config(self) -> str:
        """Перезагрузить конфигурацию и обновить компоненты."""
        from evo_agent.core.config import load_config, get_project_root
        project_root = get_project_root()
        config = load_config(project_root / "config.yaml")
        
        # Обновляем список разрешенных пользователей в Telegram
        if self._interface.name == "telegram":
            tg_config = config.get("interfaces", {}).get("telegram", {})
            allowed = tg_config.get("allowed_users", [])
            # Используем динамический вызов метода, если он есть
            if hasattr(self._interface, "update_allowed_users"):
                self._interface.update_allowed_users(allowed or None)
        
        # Перезагружаем инструменты с новым конфигом
        agent_data_dir = project_root / "agent_data"
        # Нам нужно передать актуальный people_db, но он уже есть в registry если был настроен
        self._tools.configure(
            config=config,
            extensions_dir=project_root / "extensions",
            skills_dir=agent_data_dir / "skills",
            project_root=project_root,
            people_db=self._tools._people_db, # Сохраняем ссылку на БД
            journal=self._journal,
            interface=self._interface,
            scheduler_store=self._scheduler_store,
        )
        self._tools.full_reload()
        
        return "Конфигурация и список пользователей обновлены."

    async def _handle_message(self, text: str, user_info: UserInfo) -> None:
        """Обработка входящего сообщения с полной обработкой ошибок."""
        user_id = user_info.user_id
        if self._monitor:
            self._monitor.record_message()

        # Автоматическая регистрация пользователя в PeopleDB при первом контакте
        try:
            if self._tools.get("people"):
                # Мы не можем вызвать tool напрямую легко, но можем через PeopleDB если она есть
                # В __main__ мы прокидываем people_db в registry._people_db
                people_db = getattr(self._tools, "_people_db", None)
                if people_db:
                    await people_db.create_person(
                        name=user_info.name or f"User_{user_id}",
                        source_type=user_info.source_type,
                        source_id=user_info.source_id or user_id
                    )
        except Exception:
            logger.exception("Ошибка авто-регистрации пользователя %s", user_id)

        try:
            await self._process_message(text, user_info)
        except Exception as e:
            if self._monitor:
                self._monitor.record_error()
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

        if text == "__reload_tools":
            msg = await self.reload_tools()
            await self._interface.send_message(user_id, msg)
            return

        if text == "__reload_config":
            msg = await self.reload_config()
            await self._interface.send_message(user_id, msg)
            return

        if text == "__get_health":
            if self._monitor:
                report = self._monitor.build_report(len(self._conversations))
                await self._interface.send_message(user_id, report)
            else:
                await self._interface.send_message(user_id, "Мониторинг не активен.")
            return

        if text == "__scheduler_status":
            if self._scheduler_store:
                tasks = await self._scheduler_store.list_tasks(user_id=user_id, include_done=False)
                await self._interface.send_message(
                    user_id,
                    f"Scheduler активен. Активных задач: {len(tasks)}",
                )
            else:
                await self._interface.send_message(user_id, "Scheduler не активен.")
            return

        if text == "__list_tasks":
            if self._scheduler_store:
                tasks = await self._scheduler_store.list_tasks(user_id=user_id, include_done=True)
                if not tasks:
                    await self._interface.send_message(user_id, "Задач нет.")
                else:
                    lines = ["Ваши задачи:"]
                    for t in tasks[:100]:
                        lines.append(
                            f"- id={t.id} status={t.status} type={t.schedule_type} "
                            f"next={t.next_run_at_utc.isoformat()} tool={t.tool_name}"
                        )
                    await self._interface.send_message(user_id, "\n".join(lines))
            else:
                await self._interface.send_message(user_id, "Scheduler не активен.")
            return

        if text.startswith("__cancel_task:"):
            if not self._scheduler_store:
                await self._interface.send_message(user_id, "Scheduler не активен.")
                return
            raw = text.split(":", 1)[1].strip()
            try:
                task_id = int(raw)
            except ValueError:
                await self._interface.send_message(user_id, "Неверный id задачи.")
                return
            ok = await self._scheduler_store.cancel_task(task_id=task_id, user_id=user_id)
            if ok:
                await self._interface.send_message(user_id, f"Задача {task_id} отменена.")
            else:
                await self._interface.send_message(user_id, f"Задача {task_id} не найдена или уже неактивна.")
            return

        logger.info("Сообщение от %s (%s): %s",
                     user_info.name or "?", user_id, text[:100])

        conversation = self._conversations.setdefault(user_id, [])
        user_msg = Message(role="user", content=text)
        conversation.append(user_msg)

        if self._conversation_store:
            await self._conversation_store.save_message(user_id, user_msg)

        # -- Суммаризация перед циклом --
        if self._summarizer:
            try:
                summarized = await self._summarizer.maybe_summarize(user_id)
                if summarized:
                    logger.info("Суммаризация применена для user=%s", user_id)
            except Exception:
                logger.exception("Ошибка суммаризации для user=%s", user_id)

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
            # -- Инъекция восприятия (ActionJournal) --
            perception = self._journal.format_for_llm(user_id) if self._journal else None
            if perception:
                # Добавляем как системное сообщение непосредственно перед генерацией
                conversation.append(Message(role="system", content=perception))
                if self._conversation_store:
                    await self._conversation_store.save_message(user_id, conversation[-1])

            messages = self._context_builder.build_messages(system_prompt, conversation)

            try:
                response = await self._llm.chat(messages, tools_schema if tools_schema else None)
                if self._monitor:
                    self._monitor.record_llm_call(response.usage)
            except Exception as e:
                if self._monitor:
                    self._monitor.record_error()
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
                    result = await self._execute_tool(
                        user_id,
                        tool_call,
                        user_info=user_info,
                    )
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
                
                delivered = await self._interface.send_message(user_id, response.text)
                if self._journal:
                    from datetime import datetime
                    self._journal.record(JournalEntry(
                        timestamp=datetime.now(),
                        event_type="delivery_ok" if delivered else "delivery_fail",
                        summary=f"Сообщение доставлено пользователю {user_id}" if delivered else f"НЕ удалось доставить сообщение пользователю {user_id}",
                        user_id=user_id,
                    ))
                return

            await self._interface.send_message(user_id, "(пустой ответ от LLM)")
            return

        await self._interface.send_message(
            user_id, f"[!] Достигнут лимит итераций ({self._max_iterations})"
        )

    async def _execute_tool(
        self,
        user_id: str,
        tool_call: ToolCall,
        *,
        user_info: UserInfo | None = None,
        skip_approval: bool = False,
    ) -> ToolResult:
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

        if not skip_approval:
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
            enriched_args = dict(tool_call.arguments)
            if user_info:
                enriched_args.setdefault("_caller_user_id", user_info.user_id)
                enriched_args.setdefault("_caller_source_type", user_info.source_type)
                enriched_args.setdefault("_caller_source_id", user_info.source_id or user_info.user_id)
            result = await tool.execute(tool_call_id=tool_call.id, **enriched_args)
            
            # Обогащаем результат префиксами
            if result.success:
                result.content = f"[OK] {result.content}"
            else:
                result.content = f"[ОШИБКА] {result.content}"

            # Записываем в ActionJournal
            if self._journal:
                from datetime import datetime
                self._journal.record(JournalEntry(
                    timestamp=datetime.now(),
                    event_type="tool_ok" if result.success else "tool_fail",
                    summary=f"Инструмент {tool_call.name}: {'успех' if result.success else 'ошибка'}",
                    details=result.content[:500],
                    user_id=user_id,
                ))

            if self._monitor and result.success:
                self._monitor.record_tool_call(tool_call.name)
            log_level = logging.INFO if result.success else logging.WARNING
            logger.log(log_level, "Tool %s: success=%s, len=%d",
                       tool_call.name, result.success, len(result.content))
            return result
        except Exception as e:
            logger.exception("Ошибка выполнения tool %s", tool_call.name)
            err_msg = f"Ошибка выполнения: {type(e).__name__}: {e}"
            
            if self._journal:
                from datetime import datetime
                self._journal.record(JournalEntry(
                    timestamp=datetime.now(),
                    event_type="tool_fail",
                    summary=f"Инструмент {tool_call.name}: критическая ошибка",
                    details=err_msg,
                    user_id=user_id,
                ))

            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=f"[ОШИБКА] {err_msg}",
                success=False,
            )

    async def execute_scheduled_task(self, task: ScheduledTask) -> tuple[bool, str]:
        """Исполнить задачу планировщика через общий пайплайн инструментов."""
        synthetic_call = ToolCall(
            id=f"sched-{task.id}-{int(datetime.now(timezone.utc).timestamp())}",
            name=task.tool_name,
            arguments=task.args,
        )
        user_info = UserInfo(user_id=task.user_id, source_type="scheduler", source_id=task.user_id)
        result = await self._execute_tool(
            task.user_id,
            synthetic_call,
            user_info=user_info,
            skip_approval=True,
        )
        return result.success, result.content

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
