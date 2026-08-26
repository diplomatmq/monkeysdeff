"""Система рангов с поддержкой множества чатов"""
import re
from typing import Tuple

from aiogram import F, Router
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

import database
from config import MESSAGES, RANKS, get_rank_level, has_permission
from keyboards import get_ranks_keyboard

router = Router()

def get_rank_display(rank: str) -> str:
    """Отображение ранга с эмодзи"""
    if rank in RANKS:
        r = RANKS[rank]
        return f"{r['emoji']} {r['name']}"
    return "❓ Неизвестен"

async def check_promote_rights(message: Message) -> Tuple[bool, str]:
    """Проверка прав на повышение"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    try:
        member = await message.chat.get_member(user_id)
        if member.status == "creator":
            return True, "owner"
    except Exception:
        pass
    
    chat_member = await database.db.get_member(chat_id, user_id)
    if not chat_member:
        return False, "Не в базе"
    
    level = get_rank_level(chat_member.rank)
    
    if level < 4:  # Только админы и выше
        return False, MESSAGES["no_permission"]
    
    return True, chat_member.rank

@router.message(Command("promote"))
async def cmd_promote(message: Message):
    """Повышение ранга"""
    can_promote, user_rank = await check_promote_rights(message)
    if not can_promote:
        await message.answer(MESSAGES["no_permission"])
        return
    
    parts = message.text.split()
    
    # Определяем цель: reply, ID или username
    target_id = None
    target_username = None
    steps = 1  # По умолчанию на 1 ступень
    
    if message.reply_to_message and message.reply_to_message.from_user:
        # Ответ на сообщение
        target_id = message.reply_to_message.from_user.id
        target_username = message.reply_to_message.from_user.username
        
        # Проверяем число или слова "повысить"
        if len(parts) > 1:
            try:
                steps = int(parts[1])
                if steps < 1:
                    steps = 1
            except ValueError:
                # Считаем количество слов "повысить"
                for part in parts[1:]:
                    if part.lower() in ["повысить", "повыш"]:
                        steps += 1
                if steps == 0:
                    steps = 1
    elif len(parts) >= 2:
        # Указан ID или username
        target_arg = parts[1]
        
        # Проверяем, это ID или username
        try:
            target_id = int(target_arg)
        except ValueError:
            # Это username
            username_candidate = target_arg.lstrip("@")
            if re.fullmatch(r"[A-Za-z0-9_]{3,64}", username_candidate):
                target_username = username_candidate
                # Пытаемся найти пользователя в БД или через Telegram
                try:
                    chat = await message.bot.get_chat(f"@{username_candidate}")
                    target_id = chat.id
                except Exception:
                    db_member = await database.db.get_member_by_username(message.chat.id, username_candidate)
                    if db_member:
                        target_id = db_member.user_id
                    else:
                        await message.answer("❌ Пользователь не найден")
                        return
            else:
                await message.answer("❌ Неверный формат username")
                return
        
        # Проверяем число или слова "повысить"
        if len(parts) > 2:
            try:
                steps = int(parts[2])
                if steps < 1:
                    steps = 1
            except ValueError:
                # Считаем количество слов "повысить"
                for part in parts[2:]:
                    if part.lower() in ["повысить", "повыш"]:
                        steps += 1
                if steps == 0:
                    steps = 1
    else:
        await message.answer(
            "❌ /promote [id|@username|reply] [число|повысить...]\n\n"
            "Примеры:\n"
            "/promote @username 2  (повысить на 2 ступени)\n"
            "/promote @username повысить  (повысить на 1 ступень)\n"
            "/promote @username повысить повысить  (повысить на 2 ступени)\n"
            "/promote 12345 3\n"
            "/promote (в ответ на сообщение)"
        )
        return
    
    if target_id == message.from_user.id:
        await message.answer("❌ Нельзя повысить себя!")
        return
    
    # Получаем текущий ранг цели
    target_member = await database.db.get_member(message.chat.id, target_id)
    if not target_member:
        await message.answer("❌ Пользователь не найден в базе")
        return
    
    current_level = get_rank_level(target_member.rank)
    target_level = current_level + steps
    
    # Находим ранг с нужным уровнем
    target_rank_name = None
    for rank_name, rank_data in RANKS.items():
        if rank_data["level"] == target_level:
            target_rank_name = rank_name
            break
    
    if not target_rank_name:
        await message.answer("❌ Нельзя повысить выше (уже максимальный ранг)")
        return
    
    # Проверка: нельзя повысить до owner
    if target_rank_name == "owner":
        await message.answer("❌ Нельзя повысить до владельца!")
        return
    
    user_level = get_rank_level(user_rank)
    
    # Проверка прав
    if user_rank == "owner":
        if target_level >= 5:  # Нельзя повысить до owner
            await message.answer("❌ Нельзя повысить до владельца!")
            return
    elif target_level >= user_level:
        await message.answer("❌ Нельзя повысить до вашего уровня или выше!")
        return
    
    await database.db.update_member(message.chat.id, target_id, rank=target_rank_name)
    
    target = await database.db.get_member(message.chat.id, target_id)
    name = f"@{target.username}" if target and target.username else f"ID:{target_id}"
    rank_display = get_rank_display(target_rank_name)
    
    await message.answer(MESSAGES["promote_success"].format(user=name, rank=rank_display))

@router.message(Command("demote"))
async def cmd_demote(message: Message):
    """Понижение ранга"""
    can_demote, user_rank = await check_promote_rights(message)
    if not can_demote:
        await message.answer(MESSAGES["no_permission"])
        return
    
    parts = message.text.split()
    
    # Определяем цель: reply, ID или username
    target_id = None
    target_username = None
    steps = 1  # По умолчанию на 1 ступень
    
    if message.reply_to_message and message.reply_to_message.from_user:
        # Ответ на сообщение
        target_id = message.reply_to_message.from_user.id
        target_username = message.reply_to_message.from_user.username
        
        # Проверяем число или слова "понизить"
        if len(parts) > 1:
            try:
                steps = int(parts[1])
                if steps < 1:
                    steps = 1
            except ValueError:
                # Считаем количество слов "понизить"
                for part in parts[1:]:
                    if part.lower() in ["понизить", "пониж"]:
                        steps += 1
                if steps == 0:
                    steps = 1
    elif len(parts) >= 2:
        # Указан ID или username
        target_arg = parts[1]
        
        # Проверяем, это ID или username
        try:
            target_id = int(target_arg)
        except ValueError:
            # Это username
            username_candidate = target_arg.lstrip("@")
            if re.fullmatch(r"[A-Za-z0-9_]{3,64}", username_candidate):
                target_username = username_candidate
                # Пытаемся найти пользователя в БД или через Telegram
                try:
                    chat = await message.bot.get_chat(f"@{username_candidate}")
                    target_id = chat.id
                except Exception:
                    db_member = await database.db.get_member_by_username(message.chat.id, username_candidate)
                    if db_member:
                        target_id = db_member.user_id
                    else:
                        await message.answer("❌ Пользователь не найден")
                        return
            else:
                await message.answer("❌ Неверный формат username")
                return
        
        # Проверяем число или слова "понизить"
        if len(parts) > 2:
            try:
                steps = int(parts[2])
                if steps < 1:
                    steps = 1
            except ValueError:
                # Считаем количество слов "понизить"
                for part in parts[2:]:
                    if part.lower() in ["понизить", "пониж"]:
                        steps += 1
                if steps == 0:
                    steps = 1
    else:
        await message.answer(
            "❌ /demote [id|@username|reply] [число|понизить...]\n\n"
            "Примеры:\n"
            "/demote @username 2  (понизить на 2 ступени)\n"
            "/demote @username понизить  (понизить на 1 ступень)\n"
            "/demote @username понизить понизить  (понизить на 2 ступени)\n"
            "/demote 12345 3\n"
            "/demote (в ответ на сообщение)"
        )
        return
    
    if target_id == message.from_user.id:
        await message.answer("❌ Нельзя понизить себя!")
        return
    
    # Получаем текущий ранг цели
    target_member = await database.db.get_member(message.chat.id, target_id)
    if not target_member:
        await message.answer("❌ Пользователь не найден в базе")
        return
    
    current_level = get_rank_level(target_member.rank)
    target_level = current_level - steps
    
    # Находим ранг с нужным уровнем
    target_rank_name = None
    for rank_name, rank_data in RANKS.items():
        if rank_data["level"] == target_level:
            target_rank_name = rank_name
            break
    
    if not target_rank_name:
        await message.answer("❌ Нельзя понизить ниже (уже минимальный ранг)")
        return
    
    user_level = get_rank_level(user_rank)
    
    # Проверка прав
    if user_rank == "owner":
        if target_level >= 5:  # Нельзя понизить до owner
            await message.answer("❌ Нельзя понизить до владельца!")
            return
    elif target_level >= user_level:
        await message.answer("❌ Нельзя понизить до вашего уровня или выше!")
        return
    
    await database.db.update_member(message.chat.id, target_id, rank=target_rank_name)
    
    target = await database.db.get_member(message.chat.id, target_id)
    name = f"@{target.username}" if target and target.username else f"ID:{target_id}"
    rank_display = get_rank_display(target_rank_name)
    
    await message.answer(MESSAGES["demote_success"].format(user=name, rank=rank_display))

@router.message(Command("ranklist"))
async def cmd_ranklist(message: Message):
    """Список рангов"""
    await message.answer(MESSAGES["rank_list"])

@router.message(Command("rank"))
async def cmd_rank(message: Message):
    """Мой ранг"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    member = await database.db.get_member(chat_id, user_id)
    
    if not member:
        await message.answer("❌ Вы не зарегистрированы. /captcha")
        return
    
    rank_display = get_rank_display(member.rank)
    current_level = get_rank_level(member.rank)
    
    # Следующий ранг
    next_rank = None
    for r_name, r_data in RANKS.items():
        if r_data.level == current_level + 1:
            next_rank = get_rank_display(r_name)
            break
    
    text = f"⭐ <b>Ваш ранг:</b>\n\n{rank_display}\n"
    text += f"📊 Уровень: {current_level}\n"
    
    if member.warnings > 0:
        chat = await database.db.get_chat(chat_id)
        max_w = chat.warnings_to_ban if chat else 3
        text += f"⚠️ Варнов: {member.warnings}/{max_w}\n"
    
    if next_rank:
        text += f"\n📈 Следующий: {next_rank}"
    
    await message.answer(text)

@router.message(Command("info"))
async def cmd_info(message: Message):
    """Информация о пользователе"""
    chat_id = message.chat.id
    
    parts = message.text.split()
    
    if len(parts) < 2:
        target_id = message.from_user.id
    else:
        try:
            target_id = int(parts[1])
        except ValueError:
            await message.answer("❌ Некорректный ID")
            return
    
    # Данные из чата
    try:
        chat_member = await message.chat.get_member(target_id)
        name = chat_member.user.full_name
        username = f"@{chat_member.user.username}" if chat_member.user.username else "нет"
        status = chat_member.status
    except Exception:
        name = "Неизвестен"
        username = "нет"
        status = "unknown"
    
    # Данные из базы
    db_member = await database.db.get_member(chat_id, target_id)

    text = f"👤 <b>Информация:</b>\n\n"
    text += f"👨‍💼 Имя: {name}\n"
    text += f"🔗 @{username}\n"
    text += f"🆔 {target_id}\n"
    text += f"📊 Статус: {status}\n"

    if db_member:
        rank_display = get_rank_display(db_member.rank)
        text += f"\n⭐ Ранг: {rank_display}\n"
        text += f"🔐 Верифицирован: {'Да' if db_member.is_verified else 'Нет'}\n"
        text += f"🔇 Мут: {'Да' if db_member.is_muted else 'Нет'}\n"
        text += f"⚠️ Варнов: {db_member.warnings}\n"
    
    await message.answer(text)