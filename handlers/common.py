"""Общие команды"""
from datetime import datetime

from aiogram import F, Router
from aiogram.types import Message
from aiogram.filters import Command

import database
from config import MESSAGES, get_rank_display
from keyboards import get_main_menu_keyboard

router = Router()

ROLE_LABELS = {
    "creator": "Владелец",
    "administrator": "Администратор",
    "member": "Участник",
    "restricted": "Ограничен",
    "left": "Вышел",
    "kicked": "Исключён",
}


def build_member_profile_text(user_name: str, username: str | None, member, chat_role: str = "member", chat_title: str | None = None) -> str:
    """Формирует короткий профиль участника для конкретного чата."""
    role = ROLE_LABELS.get(chat_role, "Участник")
    rank = get_rank_display(getattr(member, "rank", "user") or "user")
    messages_count = getattr(member, "messages_count", 0) or 0
    warnings = getattr(member, "warnings", 0) or 0
    created_at = getattr(member, "created_at", None) or datetime.utcnow()
    joined_days = max(0, (datetime.utcnow() - created_at).days)
    verified = "✅" if getattr(member, "is_verified", False) else "❌"
    muted = "✅" if getattr(member, "is_muted", False) else "❌"

    text = "👤 <b>Профиль участника</b>\n\n"
    text += f"👨‍💼 {user_name}\n"
    if username:
        text += f"@{username}\n"
    if chat_title:
        text += f"💬 Чат: {chat_title}\n"
    text += f"⭐ Ранг: {rank}\n"
    text += f"🛡️ Роль: {role}\n"
    text += f"💬 Сообщений: {messages_count}\n"
    text += f"📅 В чате: {joined_days} дней\n"
    text += f"⚠️ Варнов: {warnings}\n"
    text += f"🔐 Верифицирован: {verified}\n"
    text += f"🔇 Мут: {muted}\n"
    return text


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("👋 Привет! Я бот для защиты чата.")


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(MESSAGES["help"])


@router.message(Command("me"))
@router.message(Command("profile"))
@router.message(Command("parofil"))
async def cmd_me(message: Message):
    chat_id = message.chat.id
    
    # Если ответ на сообщение, показываем профиль того, на кого ответили
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        user_id = target_user.id
        username = target_user.username
        full_name = target_user.full_name
    else:
        user_id = message.from_user.id
        username = message.from_user.username
        full_name = message.from_user.full_name

    # Определяем ранг на основе статуса в чате
    chat_role = "member"
    rank = "user"
    try:
        chat_member = await message.chat.get_member(user_id)
        chat_role = getattr(chat_member, "status", "member") or "member"
        if chat_role == "creator":
            rank = "owner"
        elif chat_role == "administrator":
            rank = "admin"
    except Exception:
        pass

    member = await database.db.ensure_member(
        chat_id=chat_id,
        user_id=user_id,
        username=username,
        first_name=full_name,
        rank=rank,
        is_verified=True,
    )

    text = build_member_profile_text(
        user_name=full_name,
        username=username,
        member=member,
        chat_role=chat_role,
        chat_title=getattr(message.chat, "title", None),
    )

    await message.answer(text)


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    """Главное меню бота"""
    await message.answer(
        "📋 <b>Меню бота</b>\n\nВыберите раздел ниже:",
        reply_markup=get_main_menu_keyboard(),
    )
