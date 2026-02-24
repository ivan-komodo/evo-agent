"""SQLite-движок для хранения данных о людях."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'telegram',
    source_id TEXT,
    created_at TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    UNIQUE(source_type, source_id)
);

CREATE TABLE IF NOT EXISTS people_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (person_id) REFERENCES people(id)
);

CREATE TABLE IF NOT EXISTS people_preferences (
    person_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (person_id, key),
    FOREIGN KEY (person_id) REFERENCES people(id)
);
"""


class PeopleDB:
    """Управление базой данных людей (SQLite)."""

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    async def init(self) -> None:
        """Инициализация схемы БД."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()
        logger.info("People DB инициализирована: %s", self._db_path)

    async def create_person(
        self, name: str, source_type: str = "telegram", source_id: str | None = None,
        notes: str | None = None,
    ) -> int:
        """Создать запись о человеке. Возвращает ID."""
        now = datetime.now().isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "INSERT OR IGNORE INTO people (name, source_type, source_id, created_at, last_seen) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, source_type, source_id, now, now),
            )
            await db.commit()
            person_id = cursor.lastrowid

            if not person_id:
                row = await db.execute_fetchall(
                    "SELECT id FROM people WHERE source_type = ? AND source_id = ?",
                    (source_type, source_id),
                )
                person_id = row[0][0] if row else 0

            if notes and person_id:
                await db.execute(
                    "INSERT INTO people_notes (person_id, note, created_at) VALUES (?, ?, ?)",
                    (person_id, notes, now),
                )
                await db.commit()

        logger.info("Человек создан/найден: %s (id=%d)", name, person_id)
        return person_id

    async def get_person(self, person_id: int) -> str:
        """Получить информацию о человеке (форматированный текст)."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            row = await db.execute_fetchall(
                "SELECT * FROM people WHERE id = ?", (person_id,)
            )
            if not row:
                return f"Человек с id={person_id} не найден."

            p = dict(row[0])
            notes = await db.execute_fetchall(
                "SELECT note, created_at FROM people_notes WHERE person_id = ? ORDER BY created_at",
                (person_id,),
            )
            prefs = await db.execute_fetchall(
                "SELECT key, value FROM people_preferences WHERE person_id = ?",
                (person_id,),
            )

        lines = [
            f"**{p['name']}**",
            f"- Источник: {p['source_type']} ({p['source_id'] or 'N/A'})",
            f"- Создан: {p['created_at']}",
            f"- Последний контакт: {p['last_seen']}",
        ]

        if prefs:
            lines.append("\nНастройки:")
            for pref in prefs:
                lines.append(f"  - {pref[0]}: {pref[1]}")

        if notes:
            lines.append("\nЗаметки:")
            for note in notes:
                lines.append(f"  - [{note[1][:10]}] {note[0]}")

        return "\n".join(lines)

    async def get_person_by_source(self, source_type: str, source_id: str) -> str | None:
        """Найти человека по source_type + source_id."""
        async with aiosqlite.connect(self._db_path) as db:
            rows = await db.execute_fetchall(
                "SELECT id FROM people WHERE source_type = ? AND source_id = ?",
                (source_type, source_id),
            )
            if rows:
                return await self.get_person(rows[0][0])
            return None

    async def add_note(self, person_id: int, note: str) -> str:
        """Добавить заметку о человеке."""
        now = datetime.now().isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO people_notes (person_id, note, created_at) VALUES (?, ?, ?)",
                (person_id, note, now),
            )
            await db.commit()
        return f"Заметка добавлена для person_id={person_id}"

    async def update_person(self, person_id: int, **kwargs: Any) -> str:
        """Обновить поля человека (name, source_type, source_id)."""
        allowed = {"name", "source_type", "source_id"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return "Нечего обновлять."

        updates["last_seen"] = datetime.now().isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [person_id]

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(f"UPDATE people SET {set_clause} WHERE id = ?", values)
            await db.commit()

        return f"Человек id={person_id} обновлён: {', '.join(updates.keys())}"

    async def touch_last_seen(self, source_type: str, source_id: str) -> None:
        """Обновить last_seen по source."""
        now = datetime.now().isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE people SET last_seen = ? WHERE source_type = ? AND source_id = ?",
                (now, source_type, source_id),
            )
            await db.commit()

    async def search_people(self, query: str) -> str:
        """Поиск людей по имени или заметкам."""
        pattern = f"%{query}%"
        async with aiosqlite.connect(self._db_path) as db:
            rows = await db.execute_fetchall(
                "SELECT DISTINCT p.id, p.name, p.source_type "
                "FROM people p "
                "LEFT JOIN people_notes n ON p.id = n.person_id "
                "WHERE p.name LIKE ? OR n.note LIKE ? "
                "LIMIT 20",
                (pattern, pattern),
            )

        if not rows:
            return f"Никого не найдено по запросу '{query}'"

        lines = [f"Результаты поиска: '{query}'"]
        for r in rows:
            lines.append(f"  - [{r[0]}] {r[1]} ({r[2]})")
        return "\n".join(lines)

    async def list_people(self) -> str:
        """Краткий список всех людей."""
        async with aiosqlite.connect(self._db_path) as db:
            rows = await db.execute_fetchall(
                "SELECT id, name, source_type, last_seen FROM people ORDER BY last_seen DESC"
            )

        if not rows:
            return "Список людей пуст."

        lines = ["Все люди:"]
        for r in rows:
            lines.append(f"  - [{r[0]}] {r[1]} ({r[2]}, последний контакт: {r[3][:10]})")
        return "\n".join(lines)

    async def set_preference(self, person_id: int, key: str, value: str) -> str:
        """Установить предпочтение для человека."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO people_preferences (person_id, key, value) VALUES (?, ?, ?)",
                (person_id, key, value),
            )
            await db.commit()
        return f"Предпочтение '{key}' установлено для person_id={person_id}"
