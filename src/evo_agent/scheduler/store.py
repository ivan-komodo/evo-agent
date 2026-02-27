"""SQLite store для отложенных/повторяющихся задач."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    args_json TEXT NOT NULL,
    schedule_type TEXT NOT NULL,
    interval_seconds INTEGER,
    time_of_day TEXT,
    weekday_mask TEXT,
    day_of_month INTEGER,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    next_run_at_utc TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_error TEXT,
    run_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_due
ON scheduled_tasks(status, next_run_at_utc);

CREATE TABLE IF NOT EXISTS task_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    success INTEGER NOT NULL,
    error TEXT,
    FOREIGN KEY (task_id) REFERENCES scheduled_tasks(id)
);
"""


@dataclass
class ScheduledTask:
    id: int
    user_id: str
    tool_name: str
    args: dict[str, Any]
    schedule_type: str
    interval_seconds: int | None
    time_of_day: str | None
    weekday_mask: str | None
    day_of_month: int | None
    timezone: str
    next_run_at_utc: datetime
    status: str
    created_at: str
    updated_at: str
    last_error: str | None
    run_count: int


class SchedulerStore:
    """Персистентное хранилище задач планировщика."""

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    async def init(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()
        logger.info("Scheduler DB инициализирована: %s", self._db_path)

    async def create_task(
        self,
        *,
        user_id: str,
        tool_name: str,
        args: dict[str, Any],
        schedule_type: str,
        next_run_at_utc: datetime,
        timezone_name: str = "UTC",
        interval_seconds: int | None = None,
        time_of_day: str | None = None,
        weekday_mask: str | None = None,
        day_of_month: int | None = None,
    ) -> int:
        now = _utc_now_iso()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO scheduled_tasks (
                    user_id, tool_name, args_json, schedule_type,
                    interval_seconds, time_of_day, weekday_mask, day_of_month,
                    timezone, next_run_at_utc, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    user_id,
                    tool_name,
                    json.dumps(args, ensure_ascii=False),
                    schedule_type,
                    interval_seconds,
                    time_of_day,
                    weekday_mask,
                    day_of_month,
                    timezone_name,
                    _to_utc_iso(next_run_at_utc),
                    now,
                    now,
                ),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def fetch_due_tasks(self, limit: int = 50) -> list[ScheduledTask]:
        now = _utc_now_iso()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                """
                SELECT * FROM scheduled_tasks
                WHERE status = 'active' AND next_run_at_utc <= ?
                ORDER BY next_run_at_utc ASC
                LIMIT ?
                """,
                (now, limit),
            )
        return [self._row_to_task(r) for r in rows]

    async def list_tasks(self, user_id: str | None = None, include_done: bool = False) -> list[ScheduledTask]:
        clauses = []
        params: list[Any] = []
        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)
        if not include_done:
            clauses.append("status = 'active'")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM scheduled_tasks {where} ORDER BY next_run_at_utc ASC"

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(query, tuple(params))
        return [self._row_to_task(r) for r in rows]

    async def cancel_task(self, task_id: int, user_id: str | None = None) -> bool:
        now = _utc_now_iso()
        params: list[Any] = [now, task_id]
        user_clause = ""
        if user_id:
            user_clause = "AND user_id = ?"
            params.append(user_id)

        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                f"""
                UPDATE scheduled_tasks
                SET status = 'cancelled', updated_at = ?
                WHERE id = ? AND status = 'active' {user_clause}
                """,
                tuple(params),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def complete_run(
        self,
        task: ScheduledTask,
        *,
        success: bool,
        next_run_at_utc: datetime | None,
        error: str | None = None,
    ) -> None:
        started_at = _utc_now_iso()
        finished_at = started_at
        status = "done" if task.schedule_type == "one_time" and next_run_at_utc is None else "active"
        if not success and task.schedule_type == "one_time":
            status = "failed"

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO task_runs (task_id, started_at, finished_at, success, error)
                VALUES (?, ?, ?, ?, ?)
                """,
                (task.id, started_at, finished_at, 1 if success else 0, error),
            )
            await db.execute(
                """
                UPDATE scheduled_tasks
                SET
                    next_run_at_utc = COALESCE(?, next_run_at_utc),
                    status = ?,
                    updated_at = ?,
                    last_error = ?,
                    run_count = run_count + 1
                WHERE id = ?
                """,
                (
                    _to_utc_iso(next_run_at_utc) if next_run_at_utc else None,
                    status,
                    finished_at,
                    error,
                    task.id,
                ),
            )
            await db.commit()

    async def get_task(self, task_id: int) -> ScheduledTask | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT * FROM scheduled_tasks WHERE id = ?",
                (task_id,),
            )
        if not rows:
            return None
        return self._row_to_task(rows[0])

    def _row_to_task(self, row: aiosqlite.Row) -> ScheduledTask:
        return ScheduledTask(
            id=int(row["id"]),
            user_id=str(row["user_id"]),
            tool_name=str(row["tool_name"]),
            args=json.loads(row["args_json"] or "{}"),
            schedule_type=str(row["schedule_type"]),
            interval_seconds=row["interval_seconds"],
            time_of_day=row["time_of_day"],
            weekday_mask=row["weekday_mask"],
            day_of_month=row["day_of_month"],
            timezone=str(row["timezone"] or "UTC"),
            next_run_at_utc=datetime.fromisoformat(str(row["next_run_at_utc"])).astimezone(timezone.utc),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            last_error=row["last_error"],
            run_count=int(row["run_count"] or 0),
        )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()

