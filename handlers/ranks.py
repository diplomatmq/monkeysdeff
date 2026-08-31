"""Система рангов с поддержкой множества чатов"""
import re
from typing import Tuple

from aiogram import F, Router
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

import database
from config import MESSAGES, RANKS, get_rank_level, has_permission
from keyboards import get_ranks_keyboard

router = Router()


async def sync_rank_with_telegram(message: Message, target_id: int, rank: str) -> None:
    try:
        me = await message.bot.get_me()
        bot_member = await message.chat.get_member(me.id)
        if bot_member.status not in ("creator", "administrator"):
            return
        if not getattr(bot_member, "can_promote_members", False):
            return
    except Exception:
        return

    target_status = "member"
    try:
        tm = await message.chat.get_member(target_id)
        target_status = tm.status
    except Exception:
        pass

    if target_status == "creator":
        return

    try:
        if rank in ("admin", "owner"):
            can_delete = True
            can_restrict = True
            can_manage_chat = True
            can_invite = True
            can_pin = True
            can_promote = True
            can_change_info = True
            await message.bot.promote_chat_member(
                chat_id=message.chat.id,
                user_id=target_id,
                can_delete_messages=can_delete,
                can_restrict_members=can_restrict,
                can_invite_users=can_invite,
                can_pin_messages=can_pin,
                can_promote_members=can_promote,
                can_manage_chat=can_manage_chat,
                can_change_info=can_change_info,
            )
        else:
            if target_status == "administrator":
                await message.bot.promote_chat_member(
                    chat_id=message.chat.id,
                    user_id=target_id,
                    can_delete_messages=False,
                    can_restrict_members=False,
                    can_invite_users=False,
                    can_pin_messages=False,
                    can_promote_members=False,
                    can_manage_chat=False,
                    can_change_info=False,
                )
    except (TelegramForbiddenError, TelegramBadRequest):
        pass
    except Exception:
        pass


def _resolve_target():
    from handlers.moderation import resolve_target as _rt
    return _rt


def _ensure_target_in_db():
    from handlers.moderation import ensure_target_in_db as _et
    return _et


def get_rank_display(rank: str) -> str:
    """Отображение ранга с эмодзи"""
    if rank in RANKS:
        from config import get_rank_display as _rank_display
        return _rank_display(rank)
    return "❓ Неизвестен"

async def check_promote_rights(message: Message, target_id: int = None) -> Tuple[bool, str]:
    """Проверка прав на повышение"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    try:
        member = await message.chat.get_member(user_id)
        if member.status == "creator":
            return True, "owner"
        if member.status == "administrator":
            return True, "admin"
    except Exception:
        pass
    
    chat_member = await database.db.get_member(chat_id, user_id)
    if not chat_member:
        return False, "❌ У вас нет прав для этой команды. Сначала пройдите капчу или получите роль в чате."
    
    level = get_rank_level(chat_member.rank)
    
    if target_id:
        target_member = await database.db.get_member(chat_id, target_id)
        if target_member and get_rank_level(target_member.rank) >= level and level < 5:
            return False, f"❌ Нельзя действовать на пользователя с рангом {get_rank_display(target_member.rank)} или выше."
    
    if level < 4:
        return False, MESSAGES["no_permission"]
    
    return True, chat_member.rank

async def _get_target_full_name(message: Message, target_id: int) -> Tuple[str | None, str | None]:
    """Получает username и full_name цели через Telegram API (для ensure_target_in_db)."""
    username = None
    full_name = None
    try:
        cm = await message.chat.get_member(target_id)
        if cm and cm.user:
            username = cm.user.username
            full_name = cm.user.full_name
    except Exception:
        pass
    return username, full_name

@router.message(Command("promote"))
async def cmd_promote(message: Message):
    """Повышение ранга: /promote [id|@username|reply] [число|повысить...]"""
    if message.chat.type not in {"group", "supergroup"}:
        await message.answer("❌ Эта команда работает только в группах.")
        return

    parts = message.text.split()
    reply_target = message.reply_to_message is not None
    
    # Определяем аргументы: может быть "повысить @username 2" или "повысить 2 @username"
    target_arg = None
    steps_arg = None
    
    if reply_target:
        # Если ответ на сообщение, то первый аргумент после команды - это количество шагов
        if len(parts) > 1:
            try:
                steps_arg = parts[1]
            except ValueError:
                pass
    else:
        # Если не ответ, нужно определить что username, а что число
        if len(parts) >= 2:
            # Проверяем второй аргумент
            try:
                # Если это число, значит формат: /promote [число] [@username]
                steps_arg = parts[1]
                target_arg = parts[2] if len(parts) > 2 else None
            except ValueError:
                # Если не число, значит формат: /promote [@username] [число]
                target_arg = parts[1]
                steps_arg = parts[2] if len(parts) > 2 else None
    
    target = await _resolve_target()(message, target_arg)
    if target is None:
        if len(parts) < 2 and not reply_target:
            await message.answer(
                "❌ /promote [id|@username|reply] [число|повысить...]\n\n"
                "Примеры:\n"
                "/promote @username 2\n"
                "/promote 2 @username\n"
                "/promote (в ответ на сообщение)"
            )
        else:
            await message.answer("❌ Не удалось определить цель. Используйте ответ на сообщение, ID или @username.")
        return

    target_id, target_username = target
    if target_id == message.from_user.id:
        await message.answer("❌ Нельзя повысить себя!")
        return

    username_from_chat, full_name_from_chat = await _get_target_full_name(message, target_id)
    await _ensure_target_in_db()(
        message,
        target_id,
        target_username or username_from_chat,
    )

    can_promote, user_rank = await check_promote_rights(message, target_id)
    if not can_promote:
        await message.answer(user_rank if isinstance(user_rank, str) and user_rank.startswith("❌") else MESSAGES["no_permission"])
        return

    # Парсим количество шагов
    steps = 1
    if steps_arg:
        try:
            steps = max(1, int(steps_arg))
        except ValueError:
            # Если не число, проверяем на слова "повысить"
            for p in parts[1:]:
                if p.lower() in {"повысить", "повыш"}:
                    steps += 1

    target_member = await database.db.get_member(message.chat.id, target_id)
    current_rank = target_member.rank if target_member else "user"
    current_level = get_rank_level(current_rank)
    target_level = current_level + steps
    
    target_rank_name = None
    for rank_name, rank_data in RANKS.items():
        if rank_data["level"] == target_level:
            target_rank_name = rank_name
            break
    
    if not target_rank_name:
        await message.answer("❌ Нельзя повысить выше (уже максимальный ранг)")
        return
    
    if target_rank_name == "owner":
        await message.answer("❌ Нельзя повысить до владельца!")
        return
    
    user_level = get_rank_level(user_rank)
    if user_rank != "owner" and target_level >= user_level:
        await message.answer("❌ Нельзя повысить до вашего уровня или выше!")
        return

    await database.db.update_member(message.chat.id, target_id, rank=target_rank_name)
    await sync_rank_with_telegram(message, target_id, target_rank_name)

    target = await database.db.get_member(message.chat.id, target_id)
    final_username = (target and target.username) or target_username or username_from_chat
    name = f"@{final_username}" if final_username else f"ID:{target_id}"
    rank_display = get_rank_display(target_rank_name)

    await message.answer(MESSAGES["promote_success"].format(user=name, rank=rank_display))

@router.message(Command("demote"))
async def cmd_demote(message: Message):
    """Понижение ранга: /demote [id|@username|reply] [число|понизить...]"""
    if message.chat.type not in {"group", "supergroup"}:
        await message.answer("❌ Эта команда работает только в группах.")
        return

    parts = message.text.split()
    reply_target = message.reply_to_message is not None

    # Определяем аргументы: может быть "понизить @username 2" или "понизить 2 @username"
    target_arg = None
    steps_arg = None
    
    if reply_target:
        # Если ответ на сообщение, то первый аргумент после команды - это количество шагов
        if len(parts) > 1:
            try:
                steps_arg = parts[1]
            except ValueError:
                pass
    else:
        # Если не ответ, нужно определить что username, а что число
        if len(parts) >= 2:
            # Проверяем второй аргумент
            try:
                # Если это число, значит формат: /demote [число] [@username]
                steps_arg = parts[1]
                target_arg = parts[2] if len(parts) > 2 else None
            except ValueError:
                # Если не число, значит формат: /demote [@username] [число]
                target_arg = parts[1]
                steps_arg = parts[2] if len(parts) > 2 else None

    target = await _resolve_target()(message, target_arg)
    if target is None:
        if len(parts) < 2 and not reply_target:
            await message.answer(
                "❌ /demote [id|@username|reply] [число|понизить...]\n\n"
                "Примеры:\n"
                "/demote @username 2\n"
                "/demote 2 @username\n"
                "/demote (в ответ на сообщение)"
            )
        else:
            await message.answer("❌ Не удалось определить цель. Используйте ответ на сообщение, ID или @username.")
        return

    target_id, target_username = target
    if target_id == message.from_user.id:
        await message.answer("❌ Нельзя понизить себя!")
        return

    username_from_chat, full_name_from_chat = await _get_target_full_name(message, target_id)
    await _ensure_target_in_db()(
        message,
        target_id,
        target_username or username_from_chat,
    )

    can_demote, user_rank = await check_promote_rights(message, target_id)
    if not can_demote:
        await message.answer(user_rank if isinstance(user_rank, str) and user_rank.startswith("❌") else MESSAGES["no_permission"])
        return

    # Парсим количество шагов
    steps = 1
    if steps_arg:
        try:
            steps = max(1, int(steps_arg))
        except ValueError:
            # Если не число, проверяем на слова "понизить"
            for p in parts[1:]:
                if p.lower() in {"понизить", "пониж"}:
                    steps += 1

    target_member = await database.db.get_member(message.chat.id, target_id)
    current_rank = target_member.rank if target_member else "user"
    current_level = get_rank_level(current_rank)
    target_level = current_level - steps
    
    target_rank_name = None
    for rank_name, rank_data in RANKS.items():
        if rank_data["level"] == target_level:
            target_rank_name = rank_name
            break
    
    if not target_rank_name:
        await message.answer("❌ Нельзя понизить ниже (уже минимальный ранг)")
        return

    user_level = get_rank_level(user_rank)
    if user_rank != "owner" and target_level >= user_level:
        await message.answer("❌ Нельзя понизить пользователя до вашего уровня или выше!")
        return

    await database.db.update_member(message.chat.id, target_id, rank=target_rank_name)
    await sync_rank_with_telegram(message, target_id, target_rank_name)

    target = await database.db.get_member(message.chat.id, target_id)
    final_username = (target and target.username) or target_username or username_from_chat
    name = f"@{final_username}" if final_username else f"ID:{target_id}"
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
    
    next_rank = None
    for r_name, r_data in RANKS.items():
        if r_data["level"] == current_level + 1:
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
    """Информация о пользователе: /info [id|@username|reply]"""
    chat_id = message.chat.id
    
    parts = message.text.split()
    reply_target = message.reply_to_message is not None
    target_arg = parts[1] if len(parts) > 1 and not reply_target else None
    
    if len(parts) < 2 and not reply_target:
        target_id = message.from_user.id
        target_username = message.from_user.username
    else:
        target = await _resolve_target()(message, target_arg)
        if target is None:
            await message.answer("❌ Не удалось определить цель. Используйте /info [id|@username|reply]")
            return
        target_id, target_username = target

    username_from_chat, full_name_from_chat = await _get_target_full_name(message, target_id)
    await _ensure_target_in_db()(
        message,
        target_id,
        target_username or username_from_chat,
    )

    try:
        chat_member = await message.chat.get_member(target_id)
        name = chat_member.user.full_name
        username = chat_member.user.username
        status = chat_member.status
    except Exception:
        name = full_name_from_chat or "Неизвестен"
        username = target_username or username_from_chat
        status = "unknown"
    
    db_member = await database.db.get_member(chat_id, target_id)

    text = f"👤 <b>Информация:</b>\n\n"
    text += f"👨‍💼 Имя: {name}\n"
    if username:
        text += f"🔗 @{username}\n"
    text += f"🆔 {target_id}\n"
    text += f"📊 Статус: {status}\n"

    if db_member:
        rank_display = get_rank_display(db_member.rank)
        text += f"\n⭐ Ранг: {rank_display}\n"
        text += f"🔐 Верифицирован: {'Да' if db_member.is_verified else 'Нет'}\n"
        text += f"🔇 Мут: {'Да' if db_member.is_muted else 'Нет'}\n"
        text += f"⚠️ Варнов: {db_member.warnings}\n"
        text += f"💬 Сообщений: {db_member.messages_count or 0}\n"
    
    await message.answer(text)