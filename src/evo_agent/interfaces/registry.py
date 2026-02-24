"""Реестр интерфейсов ввода/вывода."""

from __future__ import annotations

import logging
from typing import Any

from evo_agent.interfaces.base import BaseInterface

logger = logging.getLogger(__name__)


class InterfaceRegistry:
    """Управление интерфейсами агента."""

    def __init__(self) -> None:
        self._interfaces: dict[str, BaseInterface] = {}

    def register(self, interface: BaseInterface) -> None:
        self._interfaces[interface.name] = interface
        logger.info("Интерфейс зарегистрирован: %s", interface.name)

    def get(self, name: str) -> BaseInterface | None:
        return self._interfaces.get(name)

    @property
    def all(self) -> list[BaseInterface]:
        return list(self._interfaces.values())

    async def stop_all(self) -> None:
        for name, iface in self._interfaces.items():
            try:
                await iface.stop()
            except Exception:
                logger.exception("Ошибка остановки интерфейса %s", name)
