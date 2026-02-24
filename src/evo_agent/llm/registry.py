"""Реестр LLM провайдеров."""

from __future__ import annotations

import logging
from typing import Any

from evo_agent.llm.base import LLMProvider
from evo_agent.llm.openai_compat import OpenAICompatProvider

logger = logging.getLogger(__name__)

_BUILTIN_FACTORIES: dict[str, type[LLMProvider]] = {
    "openai_compat": OpenAICompatProvider,
}


class LLMRegistry:
    """Управление LLM провайдерами."""

    def __init__(self) -> None:
        self._factories: dict[str, type[LLMProvider]] = dict(_BUILTIN_FACTORIES)
        self._instances: dict[str, LLMProvider] = {}

    def register(self, name: str, factory: type[LLMProvider]) -> None:
        self._factories[name] = factory
        logger.info("LLM провайдер зарегистрирован: %s", name)

    def create(self, config: dict[str, Any]) -> LLMProvider:
        """Создать провайдер из конфигурации."""
        provider_name = config.get("provider", "openai_compat")
        factory = self._factories.get(provider_name)
        if factory is None:
            raise ValueError(f"Неизвестный LLM провайдер: {provider_name}")

        init_kwargs = {k: v for k, v in config.items() if k != "provider"}
        instance = factory(**init_kwargs)
        self._instances[provider_name] = instance
        logger.info("LLM провайдер создан: %s (model=%s)", provider_name, config.get("model"))
        return instance

    async def close_all(self) -> None:
        for name, instance in self._instances.items():
            try:
                await instance.close()
            except Exception:
                logger.exception("Ошибка при закрытии LLM провайдера %s", name)
        self._instances.clear()
