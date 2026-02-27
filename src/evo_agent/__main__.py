"""Entry point: python -m evo_agent [--cli]."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import platform
import signal
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from evo_agent.core.config import load_config, get_project_root
from evo_agent.core.types import AutonomyLevel
from evo_agent.core.autonomy import AutonomyManager
from evo_agent.core.agent import Agent
from evo_agent.core.monitor import AgentMonitor
from evo_agent.core.action_journal import ActionJournal
from evo_agent.core.log_interceptor import LogInterceptor
from evo_agent.core.restart import RestartController
from evo_agent.llm.registry import LLMRegistry
from evo_agent.tools.registry import ToolRegistry
from evo_agent.knowledge.loader import KnowledgeLoader
from evo_agent.knowledge.manager import KnowledgeManager
from evo_agent.memory.people_db import PeopleDB
from evo_agent.memory.conversation import ConversationStore
from evo_agent.memory.summarizer import ConversationSummarizer
from evo_agent.scheduler.loop import SchedulerLoop
from evo_agent.scheduler.store import SchedulerStore
from evo_agent.interfaces.base import BaseInterface


def _ensure_utf8_console() -> None:
    """Переключить консоль на UTF-8 (Windows: chcp 65001)."""
    if platform.system() == "Windows":
        try:
            subprocess.run(
                ["chcp", "65001"],
                shell=True, check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["PYTHONUTF8"] = "1"


def setup_logging(log_dir: Path, journal: ActionJournal | None = None) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    stream_handler = logging.StreamHandler(stream=sys.stdout)
    stream_handler.setStream(sys.stdout)
    handlers: list[logging.Handler] = [
        stream_handler,
        logging.FileHandler(log_dir / "evo_agent.log", encoding="utf-8"),
    ]
    if journal:
        handlers.append(LogInterceptor(journal))
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.WARNING)


def create_interface(mode: str, config: dict) -> BaseInterface:
    """Создать интерфейс по выбранному режиму."""
    if mode == "cli":
        from evo_agent.interfaces.cli import CLIInterface
        return CLIInterface()

    from evo_agent.interfaces.telegram import TelegramInterface
    tg_config = config.get("interfaces", {}).get("telegram", {})
    token = tg_config.get("token", "")
    if not token:
        logging.getLogger("evo_agent").error(
            "TELEGRAM_BOT_TOKEN не задан! Укажите в .env или config.yaml, "
            "либо используйте --cli для консольного режима."
        )
        sys.exit(1)
    allowed = tg_config.get("allowed_users", [])
    return TelegramInterface(token=token, allowed_users=allowed or None)


async def run(mode: str = "telegram") -> None:
    project_root = get_project_root()
    load_dotenv(project_root / ".env")
    
    # -- Journal & Perception --
    journal = ActionJournal(max_entries=200)
    setup_logging(project_root / "logs", journal=journal)

    config = load_config(project_root / "config.yaml")
    logger = logging.getLogger("evo_agent")

    if RestartController.is_restarted_instance():
        logger.info("Запущен как перезапущенный экземпляр (spawn & die)")

    logger.info("Корень проекта: %s", project_root)
    logger.info("Режим интерфейса: %s", mode)

    # -- LLM --
    llm_registry = LLMRegistry()
    llm_config = config.get("llm", {})
    llm = llm_registry.create(llm_config)

    # -- Tools --
    tool_registry = ToolRegistry()
    tool_registry.load_builtin(config)
    tool_registry.load_self_modify(project_root)
    tool_registry.load_extensions(project_root / "extensions")
    
    # -- Interface --
    interface = create_interface(mode, config)

    # -- Perception Tools --
    from evo_agent.tools.builtin.read_logs import ReadLogsTool
    from evo_agent.tools.builtin.check_status import CheckStatusTool
    from evo_agent.tools.builtin.telegram_send import TelegramSendTool
    tool_registry.register(ReadLogsTool(project_root / "logs" / "evo_agent.log"))
    tool_registry.register(CheckStatusTool(journal))
    tool_registry.register(TelegramSendTool(interface))

    # -- People DB --
    people_db = PeopleDB(project_root / "data" / "people.db")
    await people_db.init()
    tool_registry.load_people_tool(people_db)

    # -- Scheduler DB --
    scheduler_store = SchedulerStore(project_root / "data" / "scheduler.db")
    await scheduler_store.init()

    # -- Scheduler Tools --
    from evo_agent.tools.builtin.schedule_task import ScheduleTaskTool
    from evo_agent.tools.builtin.list_tasks import ListTasksTool
    from evo_agent.tools.builtin.cancel_task import CancelTaskTool
    tool_registry.register(ScheduleTaskTool(scheduler_store, people_db))
    tool_registry.register(ListTasksTool(scheduler_store))
    tool_registry.register(CancelTaskTool(scheduler_store))

    # -- Python Skills --
    agent_data_dir = project_root / "agent_data"
    tool_registry.load_skills(agent_data_dir / "skills")

    # -- Configure for hot-reload --
    tool_registry.configure(
        config=config,
        extensions_dir=project_root / "extensions",
        skills_dir=agent_data_dir / "skills",
        project_root=project_root,
        people_db=people_db,
        journal=journal,
        interface=interface,
        scheduler_store=scheduler_store,
    )

    logger.info("Загружено инструментов: %d (%s)",
                len(tool_registry.tools), ", ".join(tool_registry.list_names()))

    # -- Knowledge --
    knowledge_loader = KnowledgeLoader(agent_data_dir)
    knowledge_manager = KnowledgeManager(agent_data_dir)

    # -- Conversation Store --
    mem_config = config.get("memory", {})
    conversation_store = ConversationStore(
        conversations_dir=project_root / "data" / "conversations",
        max_messages=mem_config.get("max_conversation_messages", 50),
        auto_summarize_after=mem_config.get("auto_summarize_after", 30),
    )

    # -- Summarizer --
    summarizer = ConversationSummarizer(
        store=conversation_store,
        llm=llm,
        keep_recent=mem_config.get("summarization_keep_recent", 10),
    )

    # -- Autonomy --
    prefs = knowledge_loader.load_preferences()
    autonomy_level = prefs.get("agent", {}).get("autonomy_level", 1)
    autonomy = AutonomyManager(level=AutonomyLevel(autonomy_level))

    # -- Monitor --
    monitor = AgentMonitor()

    # -- Restart Controller --
    restart_controller = RestartController(project_root=project_root)

    # -- Agent --
    max_iter = prefs.get("agent", {}).get("max_iterations", 25)
    agent = Agent(
        llm=llm,
        tool_registry=tool_registry,
        knowledge_loader=knowledge_loader,
        knowledge_manager=knowledge_manager,
        autonomy=autonomy,
        interface=interface,
        conversation_store=conversation_store,
        summarizer=summarizer,
        monitor=monitor,
        journal=journal,
        scheduler_store=scheduler_store,
        max_iterations=max_iter,
    )

    scheduler_loop = SchedulerLoop(
        store=scheduler_store,
        executor=agent,
        journal=journal,
    )

    # -- Запуск --
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Получен сигнал остановки")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    await agent.start()
    await scheduler_loop.start()
    logger.info("Evo-Agent запущен и готов к работе!")

    try:
        await stop_event.wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("Остановка агента...")
        await scheduler_loop.stop()
        await agent.stop()
        await llm_registry.close_all()
        logger.info("Evo-Agent остановлен")


def main() -> None:
    _ensure_utf8_console()

    parser = argparse.ArgumentParser(description="Evo-Agent: самомодифицирующийся AI-агент")
    parser.add_argument(
        "--cli", action="store_true",
        help="Запустить в консольном режиме (без Telegram)",
    )
    parser.add_argument(
        "--interface", choices=["telegram", "cli"], default=None,
        help="Выбор интерфейса (по умолчанию telegram)",
    )
    args = parser.parse_args()

    mode = "cli" if args.cli else (args.interface or "telegram")

    try:
        asyncio.run(run(mode=mode))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
