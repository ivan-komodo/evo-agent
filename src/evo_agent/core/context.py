"""Сборка system prompt из knowledge, окружения и информации о пользователе."""

from __future__ import annotations

import platform
from pathlib import Path
from typing import Any

from evo_agent.core.types import Message, UserInfo
from evo_agent.knowledge.loader import KnowledgeLoader


class ContextBuilder:
    """Собирает system prompt для LLM из всех источников знаний."""

    def __init__(self, knowledge_loader: KnowledgeLoader, tool_names: list[str]):
        self._loader = knowledge_loader
        self._tool_names = tool_names

    def build_system_prompt(self, user_info: UserInfo | None = None) -> str:
        """Собрать полный system prompt."""
        sections: list[str] = []

        agent_md = self._loader.load_agent()
        if agent_md:
            sections.append(agent_md)

        rules_md = self._loader.load_rules()
        if rules_md:
            sections.append(rules_md)

        prefs = self._loader.load_preferences()
        if prefs:
            agent_prefs = prefs.get("agent", {})
            if agent_prefs:
                pref_lines = [
                    "# Текущие настройки",
                    f"- Имя: {agent_prefs.get('name', 'Evo')}",
                    f"- Язык: {agent_prefs.get('language', 'ru')}",
                    f"- Уровень автономности: {agent_prefs.get('autonomy_level', 1)}",
                    f"- Стиль: {agent_prefs.get('style', 'helpful')}",
                ]
                sections.append("\n".join(pref_lines))

        skills = self._loader.load_skills_md()
        if skills:
            skill_parts = ["# Навыки"]
            for name, content in skills:
                skill_parts.append(f"\n## Навык: {name}\n{content}")
            sections.append("\n".join(skill_parts))

        memory = self._loader.load_memory()
        if memory and memory.strip():
            sections.append(memory)

        env_info = _build_env_info(self._tool_names)
        sections.append(env_info)

        if user_info:
            user_section = _build_user_section(user_info)
            sections.append(user_section)

        return "\n\n---\n\n".join(sections)

    def build_messages(
        self,
        system_prompt: str,
        conversation_messages: list[Message],
    ) -> list[Message]:
        """Собрать полный список сообщений для LLM."""
        messages = [Message(role="system", content=system_prompt)]
        messages.extend(conversation_messages)
        return messages


def _build_env_info(tool_names: list[str]) -> str:
    """Информация об окружении."""
    lines = [
        "# Окружение",
        f"- ОС: {platform.system()} {platform.release()} ({platform.machine()})",
        f"- Python: {platform.python_version()}",
        f"- Рабочая директория: {Path.cwd()}",
        f"- Доступные инструменты: {', '.join(tool_names) if tool_names else 'нет'}",
    ]
    return "\n".join(lines)


def _build_user_section(user_info: UserInfo) -> str:
    """Секция о текущем пользователе."""
    lines = [
        "# Текущий пользователь",
        f"- ID: {user_info.user_id}",
    ]
    if user_info.name:
        lines.append(f"- Имя: {user_info.name}")
    lines.append(f"- Источник: {user_info.source_type}")
    return "\n".join(lines)
