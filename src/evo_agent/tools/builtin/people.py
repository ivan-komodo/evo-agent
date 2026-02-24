"""Tool для работы с базой данных людей."""

from __future__ import annotations

import logging
from typing import Any

from evo_agent.core.types import DangerLevel, ToolResult
from evo_agent.memory.people_db import PeopleDB
from evo_agent.tools.base import BaseTool

logger = logging.getLogger(__name__)


class PeopleTool(BaseTool):
    name = "people"
    description = (
        "Управление базой данных людей. Создание, поиск, обновление записей о людях, "
        "добавление заметок и предпочтений. Все данные хранятся в SQLite."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "Действие: create, get, search, list, update, add_note, set_preference"
                ),
                "enum": [
                    "create", "get", "search", "list",
                    "update", "add_note", "set_preference",
                ],
            },
            "person_id": {
                "type": "integer",
                "description": "ID человека (для get, update, add_note, set_preference)",
            },
            "name": {
                "type": "string",
                "description": "Имя (для create, update)",
            },
            "source_type": {
                "type": "string",
                "description": "Тип источника: telegram, cli и т.д.",
            },
            "source_id": {
                "type": "string",
                "description": "ID в источнике (telegram user id и т.д.)",
            },
            "note": {
                "type": "string",
                "description": "Текст заметки (для add_note)",
            },
            "query": {
                "type": "string",
                "description": "Поисковый запрос (для search)",
            },
            "key": {
                "type": "string",
                "description": "Ключ предпочтения (для set_preference)",
            },
            "value": {
                "type": "string",
                "description": "Значение предпочтения (для set_preference)",
            },
        },
        "required": ["action"],
    }
    danger_level = DangerLevel.SAFE

    def __init__(self, people_db: PeopleDB):
        self._db = people_db

    async def execute(self, **kwargs: Any) -> ToolResult:
        action: str = kwargs["action"]
        tid = kwargs.get("tool_call_id", "")

        try:
            if action == "create":
                pid = await self._db.create_person(
                    name=kwargs.get("name", "Неизвестный"),
                    source_type=kwargs.get("source_type", "telegram"),
                    source_id=kwargs.get("source_id"),
                    notes=kwargs.get("note"),
                )
                return self._ok(f"Человек создан с id={pid}", tid)

            elif action == "get":
                person_id = kwargs.get("person_id")
                if person_id is None:
                    return self._fail("Не указан person_id", tid)
                info = await self._db.get_person(person_id)
                return self._ok(info, tid)

            elif action == "search":
                query = kwargs.get("query", "")
                result = await self._db.search_people(query)
                return self._ok(result, tid)

            elif action == "list":
                result = await self._db.list_people()
                return self._ok(result, tid)

            elif action == "update":
                person_id = kwargs.get("person_id")
                if person_id is None:
                    return self._fail("Не указан person_id", tid)
                result = await self._db.update_person(
                    person_id,
                    name=kwargs.get("name"),
                    source_type=kwargs.get("source_type"),
                    source_id=kwargs.get("source_id"),
                )
                return self._ok(result, tid)

            elif action == "add_note":
                person_id = kwargs.get("person_id")
                note = kwargs.get("note", "")
                if person_id is None:
                    return self._fail("Не указан person_id", tid)
                result = await self._db.add_note(person_id, note)
                return self._ok(result, tid)

            elif action == "set_preference":
                person_id = kwargs.get("person_id")
                key = kwargs.get("key", "")
                value = kwargs.get("value", "")
                if person_id is None:
                    return self._fail("Не указан person_id", tid)
                result = await self._db.set_preference(person_id, key, value)
                return self._ok(result, tid)

            else:
                return self._fail(f"Неизвестное действие: {action}", tid)

        except Exception as e:
            return self._fail(f"Ошибка people ({action}): {e}", tid)
