"""Антиспам с поддержкой множества чатов"""
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List

from aiogram import F, Router
from aiogram.types import Message, ChatPermissions
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

import database
from config import MESSAGES, ALERT
from handlers.captcha import check_verified, check_mute
from handlers.moderation import ensure_bot_can_restrict

router = Router()


async def apply_telegram_mute(message: Message, user_id: int, minutes: int) -> bool:
    if not await ensure_bot_can_restrict(message, "антиспам"):
        return False
    try:
        await message.bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=datetime.utcnow() + timedelta(minutes=minutes),
        )
        return True
    except TelegramForbiddenError:
        return False
    except TelegramBadRequest:
        return False

# Трекеры спама
sticker_trackers: Dict[int, Dict[int, List[datetime]]] = defaultdict(lambda: defaultdict(list))
repeat_trackers: Dict[int, Dict[int, List[tuple[str, datetime]]]] = defaultdict(lambda: defaultdict(list))
message_trackers: Dict[int, Dict[int, List[datetime]]] = defaultdict(lambda: defaultdict(list))

async def cleanup_task():
    """Очистка устаревших трекеров"""
    while True:
        now = datetime.utcnow()
        timeout = 15  # секунды
        
        for chat_id in list(sticker_trackers.keys()):
            for user_id in list(sticker_trackers[chat_id].keys()):
                sticker_trackers[chat_id][user_id] = [
                    t for t in sticker_trackers[chat_id][user_id]
                    if (now - t).total_seconds() <= timeout
                ]
                if not sticker_trackers[chat_id][user_id]:
                    del sticker_trackers[chat_id][user_id]
            if not sticker_trackers[chat_id]:
                del sticker_trackers[chat_id]
        
        for chat_id in list(repeat_trackers.keys()):
            for user_id in list(repeat_trackers[chat_id].keys()):
                repeat_trackers[chat_id][user_id] = [
                    (msg, t) for msg, t in repeat_trackers[chat_id][user_id]
                    if (now - t).total_seconds() <= timeout
                ]
                if not repeat_trackers[chat_id][user_id]:
                    del repeat_trackers[chat_id][user_id]
            if not repeat_trackers[chat_id]:
                del repeat_trackers[chat_id]
        
        for chat_id in list(message_trackers.keys()):
            for user_id in list(message_trackers[chat_id].keys()):
                message_trackers[chat_id][user_id] = [
                    t for t in message_trackers[chat_id][user_id]
                    if (now - t).total_seconds() <= timeout
                ]
                if not message_trackers[chat_id][user_id]:
                    del message_trackers[chat_id][user_id]
            if not message_trackers[chat_id]:
                del message_trackers[chat_id]
        
        await asyncio.sleep(10)

@router.message(F.sticker)
async def handle_sticker(message: Message):
    """Обработка стикеров"""
    if message.chat.type in {"private", "channel"}:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id
    
    print(f"[DEBUG] Sticker detected: chat={chat_id}, user={user_id}")
    
    # Проверка верификации и мута
    if not await check_verified(chat_id, user_id):
        print(f"[DEBUG] User not verified: {user_id}")
        try:
            await message.delete()
        except Exception:
            pass
        return
    
    is_muted, _ = await check_mute(chat_id, user_id)
    if is_muted:
        print(f"[DEBUG] User already muted: {user_id}")
        try:
            await message.delete()
        except Exception:
            pass
        return
    
    # Убеждаемся, что пользователь есть в БД
    await database.db.ensure_member(
        chat_id=chat_id,
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.full_name,
        is_verified=True,
    )
    
    # Настройки чата - создаем если нет
    chat = await database.db.get_or_create_chat(chat_id, message.chat.title)
    
    print(f"[DEBUG] Chat settings: sticker_limit={chat.sticker_limit}, sticker_timeout={chat.sticker_timeout}")
    
    now = datetime.utcnow()
    sticker_trackers[chat_id][user_id].append(now)
    
    recent = [
        t for t in sticker_trackers[chat_id][user_id]
        if (now - t).total_seconds() <= chat.sticker_timeout
    ]
    
    print(f"[DEBUG] Recent stickers: {len(recent)} (limit: {chat.sticker_limit})")
    
    if len(recent) >= chat.sticker_limit:
        try:
            chat_member = await message.chat.get_member(user_id)
            if chat_member.status in ["creator", "administrator"]:
                sticker_trackers[chat_id][user_id] = []
                return
        except Exception:
            pass

        # Спам стикерами
        print(f"[DEBUG] SPAM DETECTED! Muting user {user_id}")
        await database.db.log_spam(chat_id, user_id, "sticker", len(recent), "mute")

        minutes = chat.sticker_mute_duration
        await database.db.mute_user(
            chat_id, user_id, 0,
            minutes,
            f"Спам стикерами ({len(recent)} шт)"
        )

        await apply_telegram_mute(message, user_id, minutes)

        user = await database.db.get_member(chat_id, user_id)
        name = f"@{user.username}" if user and user.username else message.from_user.full_name

        await message.answer(
            MESSAGES["spam_stickers"].format(
                user=name,
                count=len(recent),
                duration=minutes
            )
        )

        sticker_trackers[chat_id][user_id] = []

        try:
            await message.delete()
        except Exception:
            pass

@router.message(F.text)
async def handle_message(message: Message):
    """Обработка текстовых сообщений"""
    if message.chat.type in {"private", "channel"}:
        return

    if message.text and message.text.startswith("/"):
        return

    chat_id = message.chat.id
    user_id = message.from_user.id
    
    print(f"[DEBUG] Text message detected: chat={chat_id}, user={user_id}")
    
    # Проверка верификации
    if not await check_verified(chat_id, user_id):
        print(f"[DEBUG] User not verified: {user_id}")
        try:
            await message.delete()
        except Exception:
            pass
        return
    
    # Проверка мута
    is_muted, _ = await check_mute(chat_id, user_id)
    if is_muted:
        print(f"[DEBUG] User already muted: {user_id}")
        try:
            await message.delete()
        except Exception:
            pass
        return
    
    # Убеждаемся, что пользователь есть в БД
    await database.db.ensure_member(
        chat_id=chat_id,
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.full_name,
        is_verified=True,
    )
    
    # Настройки чата - создаем если нет
    chat = await database.db.get_or_create_chat(chat_id, message.chat.title)

    print(f"[DEBUG] Chat settings: repeat_limit={chat.repeat_limit}, repeat_timeout={chat.repeat_timeout}")

    now = datetime.utcnow()

    # Проверка частоты сообщений (флуд)
    message_trackers[chat_id][user_id].append(now)
    recent_messages = [
        t for t in message_trackers[chat_id][user_id]
        if (now - t).total_seconds() <= chat.repeat_timeout
    ]

    print(f"[DEBUG] Recent messages: {len(recent_messages)} (flood limit: 5)")

    if len(recent_messages) >= 5:
        try:
            chat_member = await message.chat.get_member(user_id)
            if chat_member.status in ["creator", "administrator"]:
                message_trackers[chat_id][user_id] = []
                return
        except Exception:
            pass

        # Флуд
        print(f"[DEBUG] FLOOD DETECTED! Muting user {user_id}")
        await database.db.log_spam(chat_id, user_id, "flood", len(recent_messages), "mute")

        minutes = chat.default_mute_duration
        await database.db.mute_user(
            chat_id, user_id, 0,
            minutes,
            f"Флуд ({len(recent_messages)} сообщений)"
        )

        await apply_telegram_mute(message, user_id, minutes)

        user = await database.db.get_member(chat_id, user_id)
        name = f"@{user.username}" if user and user.username else message.from_user.full_name

        await message.answer(
            f"{ALERT} <b>{name}</b>: {len(recent_messages)} сообщений → мут {minutes} мин"
        )

        message_trackers[chat_id][user_id] = []

        try:
            await message.delete()
        except Exception:
            pass
        return

    # Увеличиваем счётчик сообщений (если не спам)
    try:
        await database.db.increment_message_count(chat_id, user_id)
    except Exception:
        pass
    
    text = message.text.lower() if message.text else ""
    
    # Проверка повторов
    recent = [
        (msg, t) for msg, t in repeat_trackers[chat_id][user_id]
        if (now - t).total_seconds() <= chat.repeat_timeout
    ]
    
    if text in [msg for msg, _ in recent]:
        repeat_trackers[chat_id][user_id].append((text, now))
        
        count = len([1 for msg, _ in repeat_trackers[chat_id][user_id] if msg == text])
        
        print(f"[DEBUG] Repeat count: {count} (limit: {chat.repeat_limit})")
        
        if count >= chat.repeat_limit:
            try:
                chat_member = await message.chat.get_member(user_id)
                if chat_member.status in ["creator", "administrator"]:
                    repeat_trackers[chat_id][user_id] = []
                    return
            except Exception:
                pass

            # Спам повторами
            print(f"[DEBUG] REPEAT SPAM DETECTED! Muting user {user_id}")
            await database.db.log_spam(chat_id, user_id, "repeat", count, "mute")

            minutes = chat.default_mute_duration
            await database.db.mute_user(
                chat_id, user_id, 0,
                minutes,
                f"Повторяющиеся сообщения ({count} раз)"
            )

            await apply_telegram_mute(message, user_id, minutes)

            user = await database.db.get_member(chat_id, user_id)
            name = f"@{user.username}" if user and user.username else message.from_user.full_name

            await message.answer(
                MESSAGES["spam_repeat"].format(
                    user=name,
                    duration=minutes
                )
            )

            repeat_trackers[chat_id][user_id] = []

            try:
                await message.delete()
            except Exception:
                pass
    else:
        # Добавляем сообщение
        repeat_trackers[chat_id][user_id] = [
            (msg, t) for msg, t in repeat_trackers[chat_id][user_id]
            if (now - t).total_seconds() <= chat.repeat_timeout
        ]
        repeat_trackers[chat_id][user_id].append((text, now))