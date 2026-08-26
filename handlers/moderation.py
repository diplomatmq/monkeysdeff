"""Модерация с поддержкой множества чатов"""
import math
import re
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.types import Message, ChatPermissions
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

import database
from config import MESSAGES, has_permission, get_rank_level, RANKS, get_required_rank_for_permission, get_rank_display

router = Router()
GROUP_CHAT_TYPES = {"group", "supergroup"}
RUSSIAN_COMMAND_ALIASES = {
    "старт": "start",
    "помощь": "help",
    "хелп": "help",
    "я": "profile",
    "профиль": "profile",
    "парофиль": "profile",
    "варн": "warn",
    "снятьварн": "unwarn",
    "снять варн": "unwarn",
    "моиварны": "mywarnings",
    "мои варны": "mywarnings",
    "бан": "ban",
    "разбан": "unban",
    "разбанить": "unban",
    "размут": "unmute",
    "мут": "mute",
    "кик": "kick",
    "роль": "setrole",
    "повысить": "promote",
    "понизить": "demote",
    "ранги": "ranklist",
    "ранг": "rank",
    "инфо": "info",
    "настройки": "settings",
    "капча": "setcaptcha",
    "лимитстикеров": "setstickerlimit",
    "лимит стикеров": "setstickerlimit",
    "лимитварнов": "setwarnings",
    "лимит варнов": "setwarnings",
    "времямут": "setmutetime",
    "время мут": "setmutetime",
    "админпомощь": "help_admin",
    "админ помощь": "help_admin",
}


def _is_group_chat(message: Message) -> bool:
    return message.chat.type in GROUP_CHAT_TYPES


async def ensure_group_chat(message: Message) -> bool:
    if _is_group_chat(message):
        return True
    await message.answer("❌ Эта команда работает только в группах и супергруппах.")
    return False


async def ensure_bot_can_restrict(message: Message, action_label: str) -> bool:
    """Проверяет, что бот может ограничивать/банить участников и сообщает причину, если нет."""
    try:
        me = await message.bot.get_me()
        bot_member = await message.chat.get_member(me.id)
    except Exception:
        await message.answer("❌ Не удалось проверить права бота. Попробуйте ещё раз.")
        return False

    if bot_member.status == "creator":
        return True

    if bot_member.status != "administrator":
        await message.answer(
            f"❌ Для команды {action_label} бот должен быть администратором чата."
        )
        return False

    if not getattr(bot_member, "can_restrict_members", False):
        await message.answer(
            f"❌ Для команды {action_label} у бота нет права 'Блокировать пользователей'."
        )
        return False

    return True


def build_reason(parts: list[str], reply_target: bool, default: str = "Нарушение правил") -> str:
    """Причина без аргумента цели: после target для обычной команды, после алиаса при reply."""
    reason_parts = parts[1:] if reply_target else parts[2:]
    reason = " ".join(reason_parts).strip()
    return reason or default


def normalize_russian_alias_to_command(text: str | None) -> str | None:
    """Преобразует текстовый алиас в slash-команду: 'мут 1 10m' -> '/mute 1 10m'."""
    if not text:
        return None

    cleaned = text.strip()
    if not cleaned:
        return None

    tokens = cleaned.split()
    if not tokens:
        return None

    normalized_tokens = [tokens[0].lstrip("/")] + tokens[1:]

    candidates: list[tuple[str, int]] = []
    if len(normalized_tokens) >= 2:
        candidates.append((f"{normalized_tokens[0]} {normalized_tokens[1]}", 2))
    candidates.append((normalized_tokens[0], 1))

    for candidate, consumed in candidates:
        mapped = RUSSIAN_COMMAND_ALIASES.get(candidate.lower())
        if not mapped:
            continue

        suffix = " ".join(normalized_tokens[consumed:])
        return f"/{mapped} {suffix}".strip()

    return None


def parse_duration_to_minutes(value: str) -> int:
    """Парсинг строк вида 10m, 1h, 5d, 5 минут, 2h30m."""
    if not value:
        raise ValueError("Пустая длительность")

    text = value.strip().lower()
    if not text:
        raise ValueError("Пустая длительность")

    aliases = {
        "s": ["s", "sec", "secs", "second", "seconds", "сек", "секунд", "секунда", "секунды"],
        "m": ["m", "min", "mins", "minute", "minutes", "мин", "минут", "минута", "минуты"],
        "h": ["h", "hr", "hrs", "hour", "hours", "час", "часа", "часов"],
        "d": ["d", "day", "days", "день", "дня", "дней"],
    }

    normalized = text
    for unit_key, items in aliases.items():
        for alias in items:
            normalized = re.sub(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", unit_key, normalized)

    pattern = re.compile(r"(\d+)([smhd])", re.IGNORECASE)
    matches = pattern.findall(normalized)
    if not matches:
        raise ValueError(f"Неверный формат длительности: {value}")

    total_seconds = 0
    for amount, unit in matches:
        amount = int(amount)
        unit = unit.lower()
        if unit == "s":
            total_seconds += amount
        elif unit == "m":
            total_seconds += amount * 60
        elif unit == "h":
            total_seconds += amount * 3600
        elif unit == "d":
            total_seconds += amount * 86400

    if total_seconds <= 0:
        raise ValueError(f"Неверная длительность: {value}")

    return max(1, math.ceil(total_seconds / 60))


async def resolve_target(message: Message, raw: str | None = None) -> tuple[int | None, str | None] | None:
    """Возвращает target_id по reply / id / @username."""
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id, message.reply_to_message.from_user.username

    if raw:
        value = raw.strip()
        # Сначала пробуем разобрать как числовой ID.
        try:
            return int(value), None
        except ValueError:
            pass

        username_candidate = value.lstrip("@")
        if re.fullmatch(r"[A-Za-z0-9_]{3,64}", username_candidate):
            username = username_candidate
            try:
                chat = await message.bot.get_chat(f"@{username}")
                return chat.id, chat.username
            except Exception:
                db_member = await database.db.get_member_by_username(message.chat.id, username)
                if db_member:
                    return db_member.user_id, db_member.username
                db_member_global = await database.db.get_member_by_username_global(username)
                if db_member_global:
                    return db_member_global.user_id, db_member_global.username
                return None

        return None

    return None


def format_user_name(user_id: int, username: str = None, name: str = None) -> str:
    """Форматирование имени пользователя"""
    if username:
        return f"@{username}"
    elif name:
        return name
    return f"ID:{user_id}"

async def check_rights(message: Message, required_permission: str, target_id: int = None) -> tuple[bool, str]:
    """Проверка прав с подсказкой, какой уровень требуется."""
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

    rank = chat_member.rank
    level = get_rank_level(rank)

    if level >= 5:
        # Владелец может всё, но не может действовать на других владельцев
        if target_id:
            target_member = await database.db.get_member(chat_id, target_id)
            if target_member and get_rank_level(target_member.rank) >= 5:
                return False, "❌ Нельзя применять действие к владельцу."
        return True, rank

    required_rank = get_required_rank_for_permission(required_permission)
    required_level = get_rank_level(required_rank)
    required_rank_name = RANKS.get(required_rank, {}).get("name", required_rank)

    if not has_permission(rank, required_permission):
        return (
            False,
            f"❌ Недостаточно прав. Нужна роль {get_rank_display(required_rank)} "
            f"(уровень {required_level}) или выше."
        )

    # Проверка ранга цели
    if target_id:
        target_member = await database.db.get_member(chat_id, target_id)
        if target_member:
            target_level = get_rank_level(target_member.rank)
            if target_level >= level:
                return False, f"❌ Нельзя применять действие к пользователю с рангом {get_rank_display(target_member.rank)} или выше."

    return True, rank


async def ensure_target_in_db(message: Message, target_id: int, target_username: str | None = None):
    """Создаёт/обновляет цель в БД, чтобы мод-действия всегда имели запись участника."""
    first_name = None
    username = target_username

    try:
        target_chat_member = await message.chat.get_member(target_id)
        first_name = target_chat_member.user.full_name
        if target_chat_member.user.username:
            username = target_chat_member.user.username
    except Exception:
        pass

    await database.db.ensure_member(
        chat_id=message.chat.id,
        user_id=target_id,
        username=username,
        first_name=first_name,
        rank="user",
        is_verified=True,
    )

@router.message(Command("mute"))
async def cmd_mute(message: Message):
    """Мут пользователя: /mute [@username|id|reply] [10m|5m|1h|5d] [причина]"""
    if not await ensure_group_chat(message):
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    can_mute, reason = await check_rights(message, "mute")
    if not can_mute:
        await message.answer(reason)
        return

    parts = message.text.split()
    reply_target = message.reply_to_message is not None
    if len(parts) < 2 and not reply_target:
        await message.answer("❌ /mute [id|@user|reply] [10m|5m|1h|5d] [причина]\nПример: /mute @username 30m флуд")
        return

    target_arg = parts[1] if len(parts) > 1 and not reply_target else None
    if reply_target and len(parts) > 1:
        candidate = parts[1]
        if re.fullmatch(r"(\d+[smhd])+|\d+[smhd]|\d+\s*(s|m|h|d)|\d+\s*(сек|мин|час|день)", candidate.lower()):
            target_arg = None
            duration_arg = candidate
        else:
            target_arg = candidate
            duration_arg = None
    else:
        duration_arg = parts[2] if len(parts) > 2 and not reply_target else None

    if reply_target and duration_arg is None and len(parts) > 1 and parts[1] and not parts[1].startswith("@"):
        duration_arg = parts[1]

    target = await resolve_target(message, target_arg)
    if target is None:
        await message.answer("❌ Не удалось определить цель")
        return

    target_id, target_username = target
    if target_id == user_id:
        await message.answer(MESSAGES["mute_self"])
        return

    await ensure_target_in_db(message, target_id, target_username)

    can_mute, reason = await check_rights(message, "mute", target_id)
    if not can_mute:
        await message.answer(reason)
        return

    if not await ensure_bot_can_restrict(message, "/mute"):
        return

    try:
        chat_member = await message.chat.get_member(target_id)
        if chat_member.status in ["creator", "administrator"]:
            await message.answer("❌ Нельзя мутить администратора")
            return
    except Exception:
        pass

    raw_duration = duration_arg or "10m"
    try:
        minutes = parse_duration_to_minutes(raw_duration)
    except ValueError:
        await message.answer("❌ Неверный формат времени. Примеры: 10m, 30m, 1h, 5d, 5 минут")
        return

    reason_parts = parts[2:] if not reply_target else parts[2:] if duration_arg is not None else []
    if reply_target and duration_arg is None and len(parts) > 1 and not parts[1].startswith("@") and not parts[1].isdigit():
        reason_parts = parts[1:]
    if reply_target and duration_arg is None and len(parts) <= 1:
        reason_parts = []
    reason = " ".join(reason_parts) if reason_parts else "Нарушение правил"

    mute_until = await database.db.mute_user(chat_id, target_id, user_id, minutes, reason)

    try:
        await message.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=datetime.utcnow() + timedelta(minutes=minutes),
        )
    except TelegramForbiddenError:
        await message.answer("❌ Бот не может замутить пользователя: не хватает прав.")
        return
    except TelegramBadRequest as e:
        await message.answer(f"❌ Не удалось замутить пользователя: {e.message}")
        return

    target_member = await database.db.get_member(chat_id, target_id)
    name = format_user_name(target_id, target_member.username if target_member else None, message.from_user.full_name)

    await message.answer(MESSAGES["mute_success"].format(user=name, duration=minutes, reason=reason))

    try:
        await message.bot.send_message(
            target_id,
            MESSAGES["user_muted"].format(
                time=mute_until.strftime("%H:%M %d.%m.%Y"),
                reason=reason
            )
        )
    except Exception:
        pass

@router.message(Command("unmute"))
async def cmd_unmute(message: Message):
    """Размут: /unmute [id|@user|reply]"""
    if not await ensure_group_chat(message):
        return

    chat_id = message.chat.id

    can_unmute, reason = await check_rights(message, "unmute")
    if not can_unmute:
        await message.answer(reason)
        return

    parts = message.text.split()
    target_arg = parts[1] if len(parts) > 1 else None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_arg = None

    if target_arg is None and not message.reply_to_message:
        await message.answer("❌ /unmute [id|@user|reply]")
        return

    target = await resolve_target(message, target_arg)
    if target is None:
        await message.answer("❌ Не удалось определить цель")
        return

    target_id, target_username = target

    await ensure_target_in_db(message, target_id, target_username)
    success = await database.db.unmute_user(chat_id, target_id)

    if success:
        if not await ensure_bot_can_restrict(message, "/unmute"):
            return

        try:
            await message.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=target_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                    can_invite_users=True,
                ),
            )
        except TelegramForbiddenError:
            await message.answer("❌ Бот не может размутить пользователя: не хватает прав.")
            return
        except TelegramBadRequest as e:
            await message.answer(f"❌ Не удалось размутить пользователя: {e.message}")
            return

        target_member = await database.db.get_member(chat_id, target_id)
        name = format_user_name(target_id, target_member.username if target_member else None)
        await message.answer(MESSAGES["unmute_success"].format(user=name))
    else:
        await message.answer(MESSAGES["user_not_found"])

@router.message(Command("ban"))
async def cmd_ban(message: Message):
    """Бан пользователя: /ban [id|@user|reply] [причина]"""
    if not await ensure_group_chat(message):
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    can_ban, reason = await check_rights(message, "ban")
    if not can_ban:
        await message.answer(reason)
        return

    parts = message.text.split()
    reply_target = message.reply_to_message is not None
    if len(parts) < 2 and not reply_target:
        await message.answer("❌ /ban [id|@user|reply] [причина]\nПример: /ban @username спам")
        return

    target_arg = parts[1] if len(parts) > 1 and not reply_target else None
    target = await resolve_target(message, target_arg)
    if target is None:
        await message.answer("❌ Не удалось определить цель")
        return

    target_id, target_username = target
    if target_id == user_id:
        await message.answer(MESSAGES["ban_self"])
        return

    await ensure_target_in_db(message, target_id, target_username)

    can_ban, reason = await check_rights(message, "ban", target_id)
    if not can_ban:
        await message.answer(reason)
        return

    if not await ensure_bot_can_restrict(message, "/ban"):
        return

    try:
        target_member = await message.chat.get_member(target_id)
        if target_member.status in ["creator", "administrator"]:
            await message.answer("❌ Нельзя банить администратора")
            return
    except Exception:
        pass

    reason = build_reason(parts, reply_target)

    await database.db.ban_user(chat_id, target_id, user_id, reason)

    try:
        await message.bot.ban_chat_member(chat_id=chat_id, user_id=target_id)
    except TelegramForbiddenError:
        await message.answer("❌ Бот не может забанить пользователя: не хватает прав.")
        return
    except TelegramBadRequest as e:
        await message.answer(f"❌ Не удалось забанить пользователя: {e.message}")
        return

    target_db = await database.db.get_member(chat_id, target_id)
    name = format_user_name(target_id, target_db.username if target_db else None)

    await message.answer(MESSAGES["ban_success"].format(user=name, reason=reason))

@router.message(Command("unban"))
async def cmd_unban(message: Message):
    """Разбан: /unban [id|@user|reply]"""
    if not await ensure_group_chat(message):
        return

    chat_id = message.chat.id

    can_unban, reason = await check_rights(message, "unban")
    if not can_unban:
        await message.answer(reason)
        return

    parts = message.text.split()
    target_arg = parts[1] if len(parts) > 1 else None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_arg = None

    if target_arg is None and not message.reply_to_message:
        await message.answer("❌ /unban [id|@user|reply]")
        return

    target = await resolve_target(message, target_arg)
    if target is None:
        await message.answer("❌ Не удалось определить цель")
        return

    target_id, target_username = target

    await ensure_target_in_db(message, target_id, target_username)
    success = await database.db.unban_user(chat_id, target_id)

    if success:
        if not await ensure_bot_can_restrict(message, "/unban"):
            return

        try:
            await message.bot.unban_chat_member(chat_id=chat_id, user_id=target_id)
        except TelegramForbiddenError:
            await message.answer("❌ Бот не может разбанить пользователя: не хватает прав.")
            return
        except TelegramBadRequest as e:
            await message.answer(f"❌ Не удалось разбанить пользователя: {e.message}")
            return

        target_member = await database.db.get_member(chat_id, target_id)
        name = format_user_name(target_id, target_member.username if target_member else None)
        await message.answer(f"✅ Пользователь {name} разбанен!")
    else:
        await message.answer(MESSAGES["user_not_found"])

@router.message(Command("warn"))
async def cmd_warn(message: Message):
    """Выдать предупреждение: /warn [id|@user|reply] [причина]"""
    if not await ensure_group_chat(message):
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    can_warn, reason = await check_rights(message, "warn")
    if not can_warn:
        await message.answer(reason)
        return

    parts = message.text.split()
    reply_target = message.reply_to_message is not None
    if len(parts) < 2 and not reply_target:
        await message.answer("❌ /warn [id|@user|reply] [причина]")
        return

    target_arg = parts[1] if len(parts) > 1 and not reply_target else None
    target = await resolve_target(message, target_arg)
    if target is None:
        await message.answer("❌ Не удалось определить цель")
        return

    target_id, target_username = target
    if target_id == user_id:
        await message.answer("❌ Нельзя варнить себя!")
        return

    await ensure_target_in_db(message, target_id, target_username)

    reason = build_reason(parts, reply_target)

    await database.db.add_warning(chat_id, target_id, user_id, reason)

    target_member = await database.db.get_member(chat_id, target_id)
    chat = await database.db.get_chat(chat_id)

    warnings_count = (target_member.warnings + 1) if target_member else 1
    max_warnings = chat.warnings_to_ban if chat else 3

    name = format_user_name(target_id, target_member.username if target_member else None)

    await message.answer(MESSAGES["warn_success"].format(user=name, count=warnings_count, reason=reason))

    if warnings_count >= max_warnings:
        await database.db.ban_user(chat_id, target_id, 0, "Достигнут лимит предупреждений")

        try:
            await message.bot.ban_chat_member(chat_id=chat_id, user_id=target_id)
        except Exception:
            await message.answer("❌ Не удалось выдать автобан: проверьте права бота.")

        await message.answer(MESSAGES["ban_limit"].format(user=name))


@router.message(Command("kick"))
async def cmd_kick(message: Message):
    """Кик пользователя: /kick [id|@user|reply] [причина]"""
    if not await ensure_group_chat(message):
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    can_kick, reason = await check_rights(message, "kick")
    if not can_kick:
        await message.answer(reason)
        return

    parts = message.text.split()
    reply_target = message.reply_to_message is not None
    if len(parts) < 2 and not reply_target:
        await message.answer("❌ /kick [id|@user|reply] [причина]")
        return

    target_arg = parts[1] if len(parts) > 1 and not reply_target else None
    target = await resolve_target(message, target_arg)
    if target is None:
        await message.answer("❌ Не удалось определить цель")
        return

    target_id, target_username = target
    if target_id == user_id:
        await message.answer(MESSAGES["kick_self"])
        return

    await ensure_target_in_db(message, target_id, target_username)

    can_kick, reason = await check_rights(message, "kick", target_id)
    if not can_kick:
        await message.answer(reason)
        return

    if not await ensure_bot_can_restrict(message, "/kick"):
        return

    reason = build_reason(parts, reply_target)

    try:
        target_member = await message.chat.get_member(target_id)
        if target_member.status in ["creator", "administrator"]:
            await message.answer("❌ Нельзя кикать администратора")
            return
    except Exception:
        pass

    try:
        await message.bot.ban_chat_member(chat_id=chat_id, user_id=target_id, revoke_messages=True)
    except TelegramForbiddenError:
        await message.answer("❌ Бот не может кикнуть пользователя: не хватает прав.")
        return
    except TelegramBadRequest as e:
        await message.answer(f"❌ Не удалось кикнуть пользователя: {e.message}")
        return

    target_db = await database.db.get_member(chat_id, target_id)
    name = format_user_name(target_id, target_db.username if target_db else None)
    await message.answer(MESSAGES["kick_success"].format(user=name, reason=reason))


@router.message(Command("setrole"))
async def cmd_setrole(message: Message):
    """Назначить роль"""
    if not await ensure_group_chat(message):
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    can_set, reason = await check_rights(message, "setrole")
    if not can_set:
        await message.answer(reason)
        return

    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("❌ /setrole [id|@user|reply] [user|moderator|admin]\nПример: /setrole @username moderator")
        return

    target = await resolve_target(message, parts[1])
    if target is None:
        await message.answer("❌ Не удалось определить цель")
        return

    target_id, target_username = target
    await ensure_target_in_db(message, target_id, target_username)
    role = parts[2].lower()
    valid_roles = ["user", "moderator", "admin"]
    if role not in valid_roles:
        await message.answer(MESSAGES["role_set_error"])
        return

    try:
        actor_member = await message.chat.get_member(user_id)
        if actor_member.status not in ["creator", "administrator"]:
            actor_db = await database.db.get_member(chat_id, user_id)
            if not actor_db or get_rank_level(actor_db.rank) < 4:
                await message.answer(MESSAGES["no_permission"])
                return
    except Exception:
        actor_db = await database.db.get_member(chat_id, user_id)
        if not actor_db or get_rank_level(actor_db.rank) < 4:
            await message.answer(MESSAGES["no_permission"])
            return

    await database.db.update_member(chat_id, target_id, rank=role)
    target_db = await database.db.get_member(chat_id, target_id)
    name = format_user_name(target_id, target_db.username if target_db else None)
    await message.answer(MESSAGES["role_set_success"].format(user=name, role=role))

@router.message(Command("unwarn"))
async def cmd_unwarn(message: Message):
    """Снять предупреждение"""
    if not await ensure_group_chat(message):
        return

    chat_id = message.chat.id
    
    can_unwarn, reason = await check_rights(message, "warn")
    if not can_unwarn:
        await message.answer(reason)
        return
    
    parts = message.text.split()
    reply_target = message.reply_to_message is not None
    target_arg = parts[1] if len(parts) > 1 and not reply_target else None

    if target_arg is None and not reply_target:
        await message.answer("❌ /unwarn [id|@user|reply]")
        return

    target = await resolve_target(message, target_arg)
    if target is None:
        await message.answer("❌ Не удалось определить цель")
        return

    target_id, target_username = target
    await ensure_target_in_db(message, target_id, target_username)
    
    removed = await database.db.remove_last_warning(chat_id, target_id)
    if not removed:
        await message.answer("❌ У пользователя нет предупреждений")
        return
    
    target = await database.db.get_member(chat_id, target_id)
    chat = await database.db.get_chat(chat_id)
    
    warnings_count = target.warnings if target else 0
    max_warnings = chat.warnings_to_ban if chat else 3
    
    name = format_user_name(target_id, target.username if target else None)
    
    await message.answer(
        MESSAGES["unwarn_success"].format(user=name, count=max(0, warnings_count), max=max_warnings)
    )

@router.message(Command("mywarnings"))
async def cmd_mywarnings(message: Message):
    """Мои предупреждения"""
    if not await ensure_group_chat(message):
        return

    chat_id = message.chat.id
    user_id = message.from_user.id
    
    warnings = await database.db.get_warnings(chat_id, user_id)
    chat = await database.db.get_chat(chat_id)
    
    count = len(warnings)
    max_w = chat.warnings_to_ban if chat else 3
    
    if count == 0:
        await message.answer(MESSAGES["warn_info"].format(count=count, max=max_w))
        return
    
    text = f"⚠️ <b>Ваши предупреждения ({count}/{max_w}):</b>\n\n"
    
    for i, w in enumerate(warnings[:10], 1):
        text += f"{i}. {w.reason}\n"
        text += f"   📅 {w.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
    
    await message.answer(text)


@router.message(F.text.regexp(r"(?i)^/?(старт|помощь|хелп|я|профиль|парофиль|варн|снятьварн|снять|моиварны|мои|бан|разбан|размут|мут|кик|роль|повысить|понизить|ранги|ранг|инфо|настройки|капча|лимитстикеров|лимитварнов|лимит|времямут|время|админпомощь|админ)\b"))
async def cmd_russian_alias(message: Message):
    """Текстовые алиасы команд на русском без / (например: 'мут @user 10m флуд')."""
    normalized = normalize_russian_alias_to_command(message.text)
    if not normalized:
        return

    command_name = normalized.split(maxsplit=1)[0].lstrip("/").lower()
    mapped_message = message.model_copy(update={"text": normalized})

    if command_name == "profile":
        from handlers.common import cmd_me
        await cmd_me(mapped_message)
        return

    if command_name == "start":
        from handlers.common import cmd_start
        await cmd_start(mapped_message)
        return

    if command_name == "help":
        from handlers.common import cmd_help
        await cmd_help(mapped_message)
        return

    if command_name == "promote":
        from handlers.ranks import cmd_promote
        await cmd_promote(mapped_message)
        return

    if command_name == "demote":
        from handlers.ranks import cmd_demote
        await cmd_demote(mapped_message)
        return

    if command_name == "ranklist":
        from handlers.ranks import cmd_ranklist
        await cmd_ranklist(mapped_message)
        return

    if command_name == "rank":
        from handlers.ranks import cmd_rank
        await cmd_rank(mapped_message)
        return

    if command_name == "info":
        from handlers.ranks import cmd_info
        await cmd_info(mapped_message)
        return

    if command_name == "settings":
        from handlers.settings import cmd_settings
        await cmd_settings(mapped_message)
        return

    if command_name == "setcaptcha":
        from handlers.settings import cmd_set_captcha
        await cmd_set_captcha(mapped_message)
        return

    if command_name == "setstickerlimit":
        from handlers.settings import cmd_set_sticker_limit
        await cmd_set_sticker_limit(mapped_message)
        return

    if command_name == "setwarnings":
        from handlers.settings import cmd_set_warnings
        await cmd_set_warnings(mapped_message)
        return

    if command_name == "setmutetime":
        from handlers.settings import cmd_set_mute_time
        await cmd_set_mute_time(mapped_message)
        return

    if command_name == "help_admin":
        from handlers.settings import cmd_help_admin
        await cmd_help_admin(mapped_message)
        return

    handlers_map = {
        "warn": cmd_warn,
        "unwarn": cmd_unwarn,
        "mywarnings": cmd_mywarnings,
        "ban": cmd_ban,
        "unban": cmd_unban,
        "unmute": cmd_unmute,
        "mute": cmd_mute,
        "kick": cmd_kick,
        "setrole": cmd_setrole,
    }
    handler = handlers_map.get(command_name)
    if handler:
        await handler(mapped_message)