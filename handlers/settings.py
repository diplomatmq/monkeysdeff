"""Настройки чата"""
from typing import Tuple

from aiogram import F, Router
from aiogram.types import Message
from aiogram.filters import Command

import database
from config import MESSAGES

router = Router()

async def check_owner_rights(message: Message) -> Tuple[bool, str]:
    """Проверка прав владельца"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    try:
        member = await message.chat.get_member(user_id)
        if member.status == "creator":
            return True, "owner"
    except Exception:
        pass
    
    chat_member = await database.db.get_member(chat_id, user_id)
    if chat_member and get_rank_level(chat_member.rank) >= 5:
        return True, chat_member.rank
    
    await message.answer(MESSAGES["no_permission"])
    return False, ""

def get_rank_level(rank: str) -> int:
    """Уровень ранга"""
    from config import RANKS
    if rank in RANKS:
        return RANKS[rank].level
    return -1

@router.message(Command("settings"))
async def cmd_settings(message: Message):
    """Показать настройки чата"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверка прав
    try:
        member = await message.chat.get_member(user_id)
        if member.status != "creator":
            await message.answer(MESSAGES["no_permission"])
            return
    except Exception:
        await message.answer(MESSAGES["no_permission"])
        return
    
    chat = await database.db.get_or_create_chat(chat_id, message.chat.title)
    
    text = "⚙️ <b>Настройки чата:</b>\n\n"
    text += f"🔐 Капча: {'ВКЛ' if chat.captcha_enabled else 'ВЫКЛ'}\n"
    text += f"⏱️ Таймаут капчи: {chat.captcha_timeout} сек\n"
    text += f"📝 Попыток капчи: {chat.captcha_attempts}\n\n"
    text += f"📊 Лит стикеров: {chat.sticker_limit}\n"
    text += f"⏱️ Таймаут стикеров: {chat.sticker_timeout} сек\n"
    text += f"🔇 Мут за стикеры: {chat.sticker_mute_duration} мин\n\n"
    text += f"🔁 Лимит повторов: {chat.repeat_limit}\n"
    text += f"⏱️ Таймаут повторов: {chat.repeat_timeout} сек\n\n"
    text += f"⚠️ Варнов до бана: {chat.warnings_to_ban}\n"
    text += f"🔇 Время мута: {chat.default_mute_duration} мин\n"
    
    await message.answer(text)

@router.message(Command("setcaptcha"))
async def cmd_set_captcha(message: Message):
    """Настройка капчи"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    try:
        member = await message.chat.get_member(user_id)
        if member.status != "creator":
            await message.answer(MESSAGES["no_permission"])
            return
    except Exception:
        await message.answer(MESSAGES["no_permission"])
        return
    
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "❌ /setcaptcha on|off\n"
            "   /setcaptcha_timeout [секунды]\n"
            "   /setcaptcha_attempts [число]"
        )
        return
    
    param = parts[1].lower()
    
    if param == "on":
        await database.db.update_chat(chat_id, captcha_enabled=True)
        await message.answer("✅ Капча включена")
    elif param == "off":
        await database.db.update_chat(chat_id, captcha_enabled=False)
        await message.answer("✅ Капча выключена")
    elif param == "timeout":
        try:
            timeout = int(parts[2])
            await database.db.update_chat(chat_id, captcha_timeout=timeout)
            await message.answer(f"✅ Таймаут капчи: {timeout} сек")
        except (ValueError, IndexError):
            await message.answer("❌ Укажите число")
    elif param == "attempts":
        try:
            attempts = int(parts[2])
            await database.db.update_chat(chat_id, captcha_attempts=attempts)
            await message.answer(f"✅ Попыток капчи: {attempts}")
        except (ValueError, IndexError):
            await message.answer("❌ Укажите число")

@router.message(Command("setstickerlimit"))
async def cmd_set_sticker_limit(message: Message):
    """Лимит стикеров"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    try:
        member = await message.chat.get_member(user_id)
        if member.status != "creator":
            await message.answer(MESSAGES["no_permission"])
            return
    except Exception:
        await message.answer(MESSAGES["no_permission"])
        return
    
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ /setstickerlimit [число]")
        return
    
    try:
        limit = int(parts[1])
        await database.db.update_chat(chat_id, sticker_limit=limit)
        await message.answer(f"✅ Лимит стикеров: {limit}")
    except ValueError:
        await message.answer("❌ Укажите число")

@router.message(Command("setwarnings"))
async def cmd_set_warnings(message: Message):
    """Варнов до бана"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    try:
        member = await message.chat.get_member(user_id)
        if member.status != "creator":
            await message.answer(MESSAGES["no_permission"])
            return
    except Exception:
        await message.answer(MESSAGES["no_permission"])
        return
    
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ /setwarnings [число]")
        return
    
    try:
        count = int(parts[1])
        await database.db.update_chat(chat_id, warnings_to_ban=count)
        await message.answer(f"✅ Варнов до бана: {count}")
    except ValueError:
        await message.answer("❌ Укажите число")

@router.message(Command("setmutetime"))
async def cmd_set_mute_time(message: Message):
    """Время мута"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    try:
        member = await message.chat.get_member(user_id)
        if member.status != "creator":
            await message.answer(MESSAGES["no_permission"])
            return
    except Exception:
        await message.answer(MESSAGES["no_permission"])
        return
    
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ /setmutetime [минуты]")
        return
    
    try:
        minutes = int(parts[1])
        await database.db.update_chat(chat_id, default_mute_duration=minutes)
        await message.answer(f"✅ Время мута: {minutes} мин")
    except ValueError:
        await message.answer("❌ Укажите число")

@router.message(Command("help_admin"))
async def cmd_help_admin(message: Message):
    """Помощь по настройкам"""
    await message.answer(MESSAGES["settings_help"])