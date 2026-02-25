"""Telegram-интерфейс через aiogram 3."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable, Awaitable

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message as TGMessage,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from evo_agent.core.types import UserInfo
from evo_agent.interfaces.base import BaseInterface, MessageHandler

logger = logging.getLogger(__name__)

_TG_MAX_MESSAGE_LENGTH = 4096


class TelegramInterface(BaseInterface):
    """Telegram бот на aiogram 3 с long polling."""

    name = "telegram"

    def __init__(self, token: str, allowed_users: list[int] | None = None):
        self._token = token
        self._allowed_users = set(allowed_users) if allowed_users else None
        self._bot: Bot | None = None
        self._dp: Dispatcher | None = None
        self._on_message: MessageHandler | None = None
        self._pending_approvals: dict[str, asyncio.Future[bool]] = {}
        self._polling_task: asyncio.Task | None = None

    def update_allowed_users(self, allowed_users: list[int] | None) -> None:
        """Обновить список разрешенных пользователей без рестарта."""
        self._allowed_users = set(allowed_users) if allowed_users else None
        logger.info("Список разрешенных пользователей обновлен: %s", self._allowed_users)

    async def start(self, on_message: MessageHandler) -> None:
        self._on_message = on_message
        self._bot = Bot(
            token=self._token,
            default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
        )
        self._dp = Dispatcher()
        self._register_handlers()

        logger.info("Telegram бот запускается...")
        self._polling_task = asyncio.create_task(self._run_polling())

    async def _run_polling(self) -> None:
        try:
            await self._dp.start_polling(self._bot)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Ошибка в Telegram polling")

    async def stop(self) -> None:
        if self._dp:
            self._dp.shutdown()
        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
        if self._bot:
            await self._bot.session.close()
        logger.info("Telegram бот остановлен")

    async def send_message(self, user_id: str, text: str, **kwargs: Any) -> bool:
        if not self._bot:
            return False
        chat_id = int(user_id)
        chunks = _split_message(text)
        success = True
        
        # Если в kwargs нет parse_mode, используем MARKDOWN по умолчанию
        # Но если MARKDOWN падает, пробуем без него
        current_kwargs = kwargs.copy()
        if "parse_mode" not in current_kwargs:
            current_kwargs["parse_mode"] = ParseMode.MARKDOWN

        for chunk in chunks:
            try:
                await self._bot.send_message(chat_id, chunk, **current_kwargs)
            except Exception as e:
                logger.warning("Ошибка отправки с parse_mode: %s. Пробую без разметки.", e)
                try:
                    await self._bot.send_message(chat_id, chunk, parse_mode=None)
                except Exception:
                    logger.exception("Не удалось отправить сообщение в %s даже без разметки", user_id)
                    success = False
        return success

    async def ask_approval(self, user_id: str, question: str) -> bool:
        if not self._bot:
            return True

        approval_id = str(uuid.uuid4())[:8]
        future: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
        self._pending_approvals[approval_id] = future

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve:{approval_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{approval_id}"),
            ]
        ])

        chat_id = int(user_id)
        try:
            # Для подтверждений всегда plain text: в аргументах часто спецсимволы.
            await self._bot.send_message(chat_id, question, reply_markup=keyboard, parse_mode=None)
        except Exception:
            logger.exception("Ошибка отправки запроса подтверждения")
            self._pending_approvals.pop(approval_id, None)
            return True

        try:
            return await asyncio.wait_for(future, timeout=300)
        except asyncio.TimeoutError:
            self._pending_approvals.pop(approval_id, None)
            await self._bot.send_message(chat_id, "⏰ Таймаут подтверждения, действие отклонено.")
            return False

    def _register_handlers(self) -> None:
        assert self._dp is not None

        @self._dp.message(F.text.startswith("/"))
        async def handle_command(message: TGMessage) -> None:
            if not self._check_access(message):
                return
            text = message.text or ""
            cmd = text.split()[0].lower()

            if cmd == "/start":
                await message.answer(
                    "👋 Привет! Я **Evo** -- самомодифицирующийся AI-агент.\n\n"
                    "Команды:\n"
                    "/autonomy <0-3> -- уровень автономности\n"
                    "/status -- текущий статус\n"
                    "/health -- отчёт о состоянии\n"
                    "/reload -- перезагрузить инструменты и конфиг\n"
                    "/skills -- список навыков\n"
                    "/memory -- просмотр памяти\n\n"
                    "Просто пиши мне -- я готов помогать!"
                )
            elif cmd == "/autonomy":
                parts = text.split()
                if len(parts) < 2:
                    await message.answer("Использование: /autonomy <0-3>")
                    return
                try:
                    level = int(parts[1])
                    if 0 <= level <= 3:
                        if self._on_message:
                            await self._on_message(
                                f"__set_autonomy:{level}", self._make_user_info(message)
                            )
                        await message.answer(f"Уровень автономности установлен: {level}")
                    else:
                        await message.answer("Уровень должен быть от 0 до 3")
                except ValueError:
                    await message.answer("Неверный формат. Использование: /autonomy <0-3>")
            elif cmd == "/status":
                if self._on_message:
                    await self._on_message("__get_status", self._make_user_info(message))
            elif cmd == "/health":
                if self._on_message:
                    await self._on_message("__get_health", self._make_user_info(message))
            elif cmd == "/reload":
                if self._on_message:
                    await self._on_message("__reload_config", self._make_user_info(message))
            elif cmd == "/skills":
                if self._on_message:
                    await self._on_message("__list_skills", self._make_user_info(message))
            elif cmd == "/memory":
                if self._on_message:
                    await self._on_message("__show_memory", self._make_user_info(message))
            else:
                if self._on_message:
                    await self._on_message(text, self._make_user_info(message))

        @self._dp.message(F.text)
        async def handle_text(message: TGMessage) -> None:
            if not self._check_access(message):
                return
            if self._on_message and message.text:
                await self._on_message(message.text, self._make_user_info(message))

        @self._dp.message(F.document)
        async def handle_document(message: TGMessage) -> None:
            if not self._check_access(message):
                return
            if self._on_message and self._bot and message.document:
                file = await self._bot.get_file(message.document.file_id)
                caption = message.caption or f"Получен файл: {message.document.file_name}"
                text = f"{caption}\n[Файл: {message.document.file_name}, path: {file.file_path}]"
                await self._on_message(text, self._make_user_info(message))

        @self._dp.callback_query(F.data.startswith("approve:"))
        async def handle_approve(callback: CallbackQuery) -> None:
            approval_id = callback.data.split(":")[1]
            future = self._pending_approvals.pop(approval_id, None)
            if future and not future.done():
                future.set_result(True)
            if callback.message:
                edited_text = (callback.message.text or "") + "\n\n[OK] Одобрено"
                try:
                    await callback.message.edit_text(edited_text)
                except Exception:
                    try:
                        await callback.message.edit_text(edited_text, parse_mode=None)
                    except Exception:
                        logger.exception("Не удалось отредактировать сообщение approve")
            await callback.answer("Одобрено")

        @self._dp.callback_query(F.data.startswith("reject:"))
        async def handle_reject(callback: CallbackQuery) -> None:
            approval_id = callback.data.split(":")[1]
            future = self._pending_approvals.pop(approval_id, None)
            if future and not future.done():
                future.set_result(False)
            if callback.message:
                edited_text = (callback.message.text or "") + "\n\n[X] Отклонено"
                try:
                    await callback.message.edit_text(edited_text)
                except Exception:
                    try:
                        await callback.message.edit_text(edited_text, parse_mode=None)
                    except Exception:
                        logger.exception("Не удалось отредактировать сообщение reject")
            await callback.answer("Отклонено")

    def _check_access(self, message: TGMessage) -> bool:
        if self._allowed_users is None:
            return True
        if not self._allowed_users:
            return True
        user_id = message.from_user.id if message.from_user else 0
        if user_id not in self._allowed_users:
            logger.warning("Неавторизованный доступ: user_id=%d", user_id)
            return False
        return True

    def _make_user_info(self, message: TGMessage) -> UserInfo:
        user = message.from_user
        name = None
        if user:
            name = user.full_name or user.username
        
        # Обработка пересланных сообщений
        text_prefix = ""
        if message.forward_from:
            f_user = message.forward_from
            f_name = f_user.full_name or f_user.username
            text_prefix = f"[ПЕРЕСЛАНО ОТ {f_name} (ID: {f_user.id})]:\n"
        elif message.forward_from_chat:
            f_chat = message.forward_from_chat
            text_prefix = f"[ПЕРЕСЛАНО ИЗ ЧАТА {f_chat.title} (ID: {f_chat.id})]:\n"
        elif message.forward_sender_name:
            text_prefix = f"[ПЕРЕСЛАНО ОТ {message.forward_sender_name}]:\n"

        if text_prefix and message.text:
            message.text = text_prefix + message.text

        return UserInfo(
            user_id=str(message.chat.id),
            name=name,
            source_type="telegram",
            source_id=str(user.id) if user else None,
        )


def _split_message(text: str) -> list[str]:
    """Разбить длинное сообщение на части."""
    if len(text) <= _TG_MAX_MESSAGE_LENGTH:
        return [text]
    chunks = []
    while text:
        if len(text) <= _TG_MAX_MESSAGE_LENGTH:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, _TG_MAX_MESSAGE_LENGTH)
        if split_at == -1:
            split_at = _TG_MAX_MESSAGE_LENGTH
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks
