"""Инструмент создания отложенных и повторяющихся задач."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from evo_agent.core.types import DangerLevel, ToolResult
from evo_agent.memory.people_db import PeopleDB
from evo_agent.scheduler.store import SchedulerStore
from evo_agent.tools.base import BaseTool


class ScheduleTaskTool(BaseTool):
    name = "schedule_task"
    description = (
        "Создать отложенную или повторяющуюся задачу. Поддерживает: one_time, every_n, "
        "daily_at, weekly_on, monthly_on."
    )
    parameters = {
        "type": "object",
        "properties": {
            "tool_name": {"type": "string", "description": "Имя инструмента для выполнения"},
            "args": {"type": "object", "description": "Аргументы инструмента"},
            "schedule_type": {
                "type": "string",
                "enum": ["one_time", "every_n", "daily_at", "weekly_on", "monthly_on"],
            },
            "delay_seconds": {"type": "integer", "description": "Запуск через N секунд"},
            "execute_at": {"type": "string", "description": "ISO дата-время запуска"},
            "interval_seconds": {"type": "integer", "description": "Интервал для every_n"},
            "time_of_day": {"type": "string", "description": "HH:MM для daily/weekly/monthly"},
            "weekdays": {"type": "array", "items": {"type": "integer"}, "description": "Дни недели 0..6"},
            "day_of_month": {"type": "integer", "description": "День месяца 1..31"},
            "timezone": {"type": "string", "description": "IANA timezone, например Europe/Moscow"},
        },
        "required": ["tool_name", "args", "schedule_type"],
    }
    danger_level = DangerLevel.DANGEROUS

    def __init__(self, store: SchedulerStore, people_db: PeopleDB):
        self._store = store
        self._people_db = people_db

    async def execute(self, **kwargs: Any) -> ToolResult:
        tid = str(kwargs.get("tool_call_id", ""))
        try:
            tool_name = str(kwargs.get("tool_name", "")).strip()
            args = kwargs.get("args") or {}
            schedule_type = str(kwargs.get("schedule_type", "")).strip()
            user_id = str(kwargs.get("_caller_user_id", ""))
            caller_source_type = str(kwargs.get("_caller_source_type", "telegram"))
            caller_source_id = str(kwargs.get("_caller_source_id", user_id))

            if not tool_name:
                return self._fail("Не указан tool_name", tid)
            if not isinstance(args, dict):
                return self._fail("args должен быть объектом", tid)

            timezone_name = await self._resolve_timezone(
                kwargs=kwargs,
                schedule_type=schedule_type,
                source_type=caller_source_type,
                source_id=caller_source_id,
            )
            if timezone_name is None:
                return self._fail(
                    "Не задана таймзона пользователя. Укажите timezone (например Europe/Moscow), "
                    "после этого я сохраню её и повторно создам задачу.",
                    tid,
                )

            next_run = self._compute_first_run(schedule_type=schedule_type, kwargs=kwargs, timezone_name=timezone_name)
            if next_run is None:
                return self._fail("Не удалось вычислить время первого запуска. Проверьте параметры.", tid)

            weekdays = kwargs.get("weekdays")
            weekday_mask = None
            if isinstance(weekdays, list):
                normalized = [str(int(x)) for x in weekdays if isinstance(x, int) and 0 <= int(x) <= 6]
                weekday_mask = ",".join(normalized)

            task_id = await self._store.create_task(
                user_id=user_id,
                tool_name=tool_name,
                args=args,
                schedule_type=schedule_type,
                interval_seconds=_to_int_or_none(kwargs.get("interval_seconds")),
                time_of_day=_to_str_or_none(kwargs.get("time_of_day")),
                weekday_mask=weekday_mask,
                day_of_month=_to_int_or_none(kwargs.get("day_of_month")),
                timezone_name=timezone_name,
                next_run_at_utc=next_run,
            )
            return self._ok(
                f"Задача создана: id={task_id}, type={schedule_type}, next={next_run.isoformat()}",
                tid,
            )
        except Exception as e:
            return self._fail(f"Ошибка schedule_task: {e}", tid)

    async def _resolve_timezone(
        self,
        *,
        kwargs: dict[str, Any],
        schedule_type: str,
        source_type: str,
        source_id: str,
    ) -> str | None:
        explicit = kwargs.get("timezone")
        if isinstance(explicit, str) and explicit.strip():
            tz_name = explicit.strip()
            ZoneInfo(tz_name)  # validation
            await self._people_db.set_timezone_by_source(source_type, source_id, tz_name)
            return tz_name

        # Для one_time через delay_seconds и every_n таймзона не критична
        if schedule_type in {"one_time", "every_n"} and kwargs.get("delay_seconds") is not None:
            return "UTC"

        stored = await self._people_db.get_timezone_by_source(source_type, source_id)
        if stored:
            ZoneInfo(stored)  # validation
            return stored
        return None

    def _compute_first_run(self, *, schedule_type: str, kwargs: dict[str, Any], timezone_name: str) -> datetime | None:
        now_utc = datetime.now(timezone.utc)
        if schedule_type == "one_time":
            delay_seconds = _to_int_or_none(kwargs.get("delay_seconds"))
            if delay_seconds is not None and delay_seconds >= 0:
                return now_utc + timedelta(seconds=delay_seconds)
            execute_at = kwargs.get("execute_at")
            if isinstance(execute_at, str) and execute_at.strip():
                dt = _parse_datetime(execute_at, timezone_name)
                return dt.astimezone(timezone.utc)
            return None

        if schedule_type == "every_n":
            interval = _to_int_or_none(kwargs.get("interval_seconds"))
            if interval is None or interval <= 0:
                return None
            return now_utc + timedelta(seconds=interval)

        tz = ZoneInfo(timezone_name)
        now_local = now_utc.astimezone(tz)
        hh, mm = _parse_hhmm(str(kwargs.get("time_of_day", "09:00")))

        if schedule_type == "daily_at":
            candidate = datetime.combine(now_local.date(), time(hh, mm), tzinfo=tz)
            if candidate <= now_local:
                candidate += timedelta(days=1)
            return candidate.astimezone(timezone.utc)

        if schedule_type == "weekly_on":
            weekdays = kwargs.get("weekdays")
            if not isinstance(weekdays, list) or not weekdays:
                return None
            valid_days = {int(x) for x in weekdays if isinstance(x, int) and 0 <= int(x) <= 6}
            if not valid_days:
                return None
            for shift in range(0, 14):
                d = now_local.date() + timedelta(days=shift)
                if d.weekday() not in valid_days:
                    continue
                candidate = datetime.combine(d, time(hh, mm), tzinfo=tz)
                if candidate > now_local:
                    return candidate.astimezone(timezone.utc)
            return None

        if schedule_type == "monthly_on":
            day = _to_int_or_none(kwargs.get("day_of_month"))
            if day is None or day < 1 or day > 31:
                return None
            year = now_local.year
            month = now_local.month
            for _ in range(0, 24):
                try:
                    candidate = datetime(year, month, day, hh, mm, tzinfo=tz)
                except ValueError:
                    candidate = None
                if candidate and candidate > now_local:
                    return candidate.astimezone(timezone.utc)
                month += 1
                if month > 12:
                    month = 1
                    year += 1
            return None

        return None


def _to_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _to_str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_hhmm(value: str) -> tuple[int, int]:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError("Ожидается формат HH:MM")
    return int(parts[0]), int(parts[1])


def _parse_datetime(value: str, timezone_name: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(timezone_name))
    return dt

