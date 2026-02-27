"""Фоновый loop исполнения запланированных задач."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Protocol

from evo_agent.core.action_journal import ActionJournal, JournalEntry
from evo_agent.scheduler.engine import compute_next_run
from evo_agent.scheduler.store import ScheduledTask, SchedulerStore

logger = logging.getLogger(__name__)


class ScheduledTaskExecutor(Protocol):
    async def execute_scheduled_task(self, task: ScheduledTask) -> tuple[bool, str]:
        """Выполнить отложенную задачу и вернуть (success, detail)."""


class SchedulerLoop:
    """Планировщик с догоном пропущенных задач и ограничением скорости."""

    def __init__(
        self,
        store: SchedulerStore,
        executor: ScheduledTaskExecutor,
        journal: ActionJournal | None = None,
        tick_seconds: float = 2.0,
        batch_size: int = 10,
        max_exec_per_minute: int = 30,
    ):
        self._store = store
        self._executor = executor
        self._journal = journal
        self._tick_seconds = tick_seconds
        self._batch_size = batch_size
        self._max_exec_per_minute = max_exec_per_minute
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._rate_bucket: deque[datetime] = deque()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="scheduler-loop")
        logger.info("Scheduler loop запущен")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Scheduler loop остановлен")

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:
                logger.exception("Ошибка в scheduler tick")
            await asyncio.sleep(self._tick_seconds)

    async def _tick(self) -> None:
        due = await self._store.fetch_due_tasks(limit=self._batch_size * 3)
        if not due:
            return

        executed = 0
        for task in due:
            if executed >= self._batch_size:
                break
            if not self._can_execute_now():
                break

            success, detail = await self._executor.execute_scheduled_task(task)
            next_run = compute_next_run(task)
            await self._store.complete_run(
                task,
                success=success,
                next_run_at_utc=next_run,
                error=None if success else detail,
            )
            executed += 1
            self._touch_bucket()
            self._record_event(task, success, detail, next_run)

    def _record_event(self, task: ScheduledTask, success: bool, detail: str, next_run: datetime | None) -> None:
        if not self._journal:
            return
        event_type = "tool_ok" if success else "tool_fail"
        summary = (
            f"Scheduler task#{task.id} выполнена: {task.tool_name}"
            if success
            else f"Scheduler task#{task.id} ошибка: {task.tool_name}"
        )
        if next_run:
            summary += f" (next={next_run.isoformat()})"
        self._journal.record(
            JournalEntry(
                timestamp=datetime.now(timezone.utc),
                event_type=event_type,
                summary=summary,
                details=detail[:500] if detail else None,
                user_id=task.user_id,
            )
        )

    def _can_execute_now(self) -> bool:
        now = datetime.now(timezone.utc)
        while self._rate_bucket and (now - self._rate_bucket[0]).total_seconds() > 60:
            self._rate_bucket.popleft()
        return len(self._rate_bucket) < self._max_exec_per_minute

    def _touch_bucket(self) -> None:
        self._rate_bucket.append(datetime.now(timezone.utc))

