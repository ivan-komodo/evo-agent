"""Вычисление следующего запуска для calendar-style расписаний."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from evo_agent.scheduler.store import ScheduledTask


def compute_next_run(task: ScheduledTask) -> datetime | None:
    """Вычислить следующий запуск после task.next_run_at_utc."""
    if task.schedule_type == "one_time":
        return None

    current_utc = task.next_run_at_utc.astimezone(timezone.utc)
    tz = ZoneInfo(task.timezone or "UTC")
    current_local = current_utc.astimezone(tz)

    if task.schedule_type == "every_n":
        interval = int(task.interval_seconds or 0)
        if interval <= 0:
            return None
        return current_utc + timedelta(seconds=interval)

    hh, mm = _parse_hhmm(task.time_of_day or "09:00")

    if task.schedule_type == "daily_at":
        next_day = (current_local + timedelta(days=1)).date()
        local_dt = datetime.combine(next_day, time(hour=hh, minute=mm), tzinfo=tz)
        return local_dt.astimezone(timezone.utc)

    if task.schedule_type == "weekly_on":
        weekdays = _parse_weekday_mask(task.weekday_mask)
        if not weekdays:
            return None
        base_date = current_local.date()
        for shift in range(1, 15):
            candidate_date = base_date + timedelta(days=shift)
            if candidate_date.weekday() in weekdays:
                local_dt = datetime.combine(candidate_date, time(hour=hh, minute=mm), tzinfo=tz)
                return local_dt.astimezone(timezone.utc)
        return None

    if task.schedule_type == "monthly_on":
        day = int(task.day_of_month or 1)
        year = current_local.year
        month = current_local.month
        for _ in range(24):
            year, month = _inc_month(year, month)
            max_day = _days_in_month(year, month)
            use_day = min(day, max_day)
            local_dt = datetime(year, month, use_day, hh, mm, tzinfo=tz)
            return local_dt.astimezone(timezone.utc)
        return None

    return None


def _parse_hhmm(value: str) -> tuple[int, int]:
    parts = value.split(":")
    if len(parts) != 2:
        return 9, 0
    h = max(0, min(23, int(parts[0])))
    m = max(0, min(59, int(parts[1])))
    return h, m


def _parse_weekday_mask(value: str | None) -> set[int]:
    if not value:
        return set()
    result: set[int] = set()
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        day = int(token)
        if 0 <= day <= 6:
            result.add(day)
    return result


def _inc_month(year: int, month: int) -> tuple[int, int]:
    month += 1
    if month > 12:
        month = 1
        year += 1
    return year, month


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        next_month = datetime(year + 1, 1, 1)
    else:
        next_month = datetime(year, month + 1, 1)
    this_month = datetime(year, month, 1)
    return (next_month - this_month).days

