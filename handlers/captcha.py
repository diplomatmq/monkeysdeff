"""Капча с restrict_chat_member"""
import asyncio
import random
from datetime import datetime, timedelta
from typing import Dict
from aiogram import Bot, F, Router
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated, ChatPermissions
from aiogram.filters import ChatMemberUpdatedFilter
from aiogram.filters.command import Command
from aiogram.fsm.state import State, StatesGroup

import database
from config import CAPTCHA_QUESTIONS, MESSAGES

router = Router()
bot: Bot | None = None


def get_bot() -> Bot | None:
    """Возвращает текущий экземпляр бота aiogram."""
    return bot


class CaptchaStates(StatesGroup):
    solving = State()

# Активные капчи: {chat_id: {user_id: data}}
active_captchas: Dict[int, Dict[int, dict]] = {}
admin_cache: Dict[tuple[int, int], tuple[bool, datetime]] = {}
captcha_locks: Dict[tuple[int, int], asyncio.Lock] = {}

def get_captcha_keyboard(question_idx: int, options: list, captcha_id: str):
    """Клавиатура с 4 кнопками"""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = []
    for i, opt in enumerate(options):
        keyboard.append([InlineKeyboardButton(text=opt.text, callback_data=f"captcha:{captcha_id}:{i}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_restricted_permissions():
    """Права, которые остаются у пользователя при модерировании"""
    return ChatPermissions(
        can_send_messages=False,
        can_send_media_messages=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_change_info=False,
        can_invite_users=True,
        can_pin_messages=False,
        can_manage_topics=False
    )

def get_full_permissions():
    """Полные права после прохождения капчи"""
    return ChatPermissions(
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_change_info=False,
        can_invite_users=True,
        can_pin_messages=False,
        can_manage_topics=False
    )

async def is_chat_owner_or_admin(chat_id: int, user_id: int) -> bool:
    """Проверяет, является ли пользователь владельцем или администратором текущего чата."""
    cache_key = (chat_id, user_id)
    cached = admin_cache.get(cache_key)
    if cached and cached[1] > datetime.utcnow():
        return cached[0]

    bot = get_bot()
    if bot is None:
        return False
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        result = chat_member.status in ["creator", "administrator"]
        admin_cache[cache_key] = (result, datetime.utcnow() + timedelta(seconds=60))
        return result
    except Exception:
        return False


async def get_chat_member_status(chat_id: int, user_id: int) -> str:
    """Возвращает статус пользователя в чате: creator, administrator или member."""
    bot = get_bot()
    if bot is None:
        return "member"
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        return chat_member.status
    except Exception:
        return "member"


async def start_captcha(chat_id: int, user_id: int, name: str, username: str = None):
    """Начало капчи - сразу ограничиваем права и отправляем вопрос."""
    bot = get_bot()
    if bot is None:
        print("[DEBUG] No active bot instance for captcha")
        return

    lock_key = (chat_id, user_id)
    lock = captcha_locks.setdefault(lock_key, asyncio.Lock())
    async with lock:
        chat_status = await get_chat_member_status(chat_id, user_id)
        
        if chat_status == "creator":
            await database.db.ensure_member(
                chat_id=chat_id,
                user_id=user_id,
                username=username,
                first_name=name,
                rank="owner",
                is_verified=True,
            )
            return
        elif chat_status == "administrator":
            await database.db.ensure_member(
                chat_id=chat_id,
                user_id=user_id,
                username=username,
                first_name=name,
                rank="admin",
                is_verified=True,
            )
            return

        chat = await database.db.get_chat(chat_id)
        if chat and not chat.captcha_enabled:
            await database.db.ensure_member(
                chat_id=chat_id,
                user_id=user_id,
                username=username,
                first_name=name,
                is_verified=True,
            )
            return

        member = await database.db.get_or_create_member(chat_id, user_id, username, name)
        if member and member.is_verified:
            return

        existing = active_captchas.get(chat_id, {}).get(user_id)
        now = datetime.utcnow()
        if existing and existing.get("expires_at") and existing["expires_at"] > now:
            print(f"[DEBUG] captcha already active: chat={chat_id}, user={user_id}")
            return
        if existing:
            old = existing.get("message_id")
            if old:
                try:
                    await bot.delete_message(chat_id, old)
                except Exception:
                    pass

        try:
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=get_restricted_permissions()
            )
        except Exception:
            try:
                await bot.restrict_chat_member(chat_id=chat_id, user_id=user_id, can_send_messages=False)
            except Exception:
                pass

        captcha_id = f"{chat_id}_{user_id}_{int(datetime.utcnow().timestamp())}"
        question_idx = random.randint(0, len(CAPTCHA_QUESTIONS) - 1)
        question = CAPTCHA_QUESTIONS[question_idx]
        options = question.options.copy()
        random.shuffle(options)
        correct_idx = next(i for i, opt in enumerate(options) if opt.is_correct)
        timeout = chat.captcha_timeout if chat else 300
        captcha_data = {
            "id": captcha_id,
            "question_idx": question_idx,
            "correct_idx": correct_idx,
            "expires_at": datetime.utcnow() + timedelta(seconds=timeout),
            "message_id": None,
            "chat_id": chat_id,
            "user_id": user_id,
            "name": name
        }
        active_captchas.setdefault(chat_id, {})[user_id] = captcha_data
        keyboard = get_captcha_keyboard(question_idx, options, captcha_id)

        try:
            print(f"[DEBUG] Sending captcha to chat {chat_id}")
            msg = await bot.send_message(
                chat_id,
                MESSAGES["welcome_new"].format(name=name) + "\n\n" +
                MESSAGES["captcha_title"] + "\n\n" +
                question.question + "\n\n" +
                MESSAGES["captcha_time"].format(seconds=timeout),
                reply_markup=keyboard
            )
            captcha_data["message_id"] = msg.message_id
            print(f"[DEBUG] Captcha sent, message_id={msg.message_id}")
        except Exception as e:
            active_captchas.get(chat_id, {}).pop(user_id, None)
            print(f"[DEBUG] Error sending captcha: {e}")

async def cleanup_task():
    """Очистка истекших капч"""
    while True:
        try:
            bot = get_bot()
            now = datetime.utcnow()
            expired = []

            for chat_id, users in active_captchas.items():
                for user_id, data in users.items():
                    if data["expires_at"] <= now:
                        expired.append((chat_id, user_id, data))

            for chat_id, user_id, data in expired:
                if bot is not None:
                    if data.get("message_id"):
                        try:
                            await bot.delete_message(chat_id, data["message_id"])
                        except Exception:
                            pass

                    try:
                        await bot.ban_chat_member(chat_id, user_id)
                        await bot.send_message(chat_id, MESSAGES["captcha_kick"].format(name=data["name"]))
                    except Exception:
                        pass

                if chat_id in active_captchas and user_id in active_captchas[chat_id]:
                    del active_captchas[chat_id][user_id]

        except Exception:
            pass

        await asyncio.sleep(10)

@router.message(F.new_chat_members)
async def on_new_chat_members(message: Message):
    """Запуск капчи при входе нового участника в чат."""
    if message.chat.type not in {"group", "supergroup"}:
        return

    chat_id = message.chat.id
    print(f"[DEBUG] new_chat_members event: chat={chat_id}, members={[m.id for m in message.new_chat_members]}")

    for member in message.new_chat_members:
        if member.is_bot:
            continue

        await start_captcha(chat_id, member.id, member.full_name, member.username)


@router.chat_member()
async def on_chat_member_update(event: ChatMemberUpdated):
    """Запуск капчи при изменении статуса участника чата."""
    if event.chat.type not in {"group", "supergroup"}:
        return

    chat_id = event.chat.id
    user = event.new_chat_member.user
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    print(f"[DEBUG] chat_member event: chat={chat_id}, user={user.id if user else None}, {old_status}->{new_status}")

    if user is None or user.is_bot:
        return

    if old_status in ["left", "kicked"] and new_status in ["member", "restricted"]:
        await start_captcha(chat_id, user.id, user.full_name, user.username)


@router.message(F.text)
async def on_user_message_before_captcha(message: Message):
    """Удаляем сообщения новых участников до прохождения капчи."""
    if message.chat.type not in {"group", "supergroup"}:
        return

    if message.from_user is None or message.sender_chat is not None:
        return

    # Не обрабатываем команды
    if message.text and message.text.startswith("/"):
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    # Убеждаемся, что пользователь есть в БД
    chat_status = await get_chat_member_status(chat_id, user_id)
    rank = None
    if chat_status == "creator":
        rank = "owner"
    elif chat_status == "administrator":
        rank = "admin"
    
    if rank:
        await database.db.ensure_member(
            chat_id=chat_id,
            user_id=user_id,
            username=message.from_user.username,
            first_name=message.from_user.full_name,
            rank=rank,
            is_verified=True,
        )
    else:
        await database.db.ensure_member(
            chat_id=chat_id,
            user_id=user_id,
            username=message.from_user.username,
            first_name=message.from_user.full_name,
            is_verified=True,
        )

    # Счётчик сообщений нужен для профиля пользователя внутри конкретного чата.
    try:
        await database.db.increment_message_count(chat_id, user_id)
    except Exception:
        pass

    if await is_chat_owner_or_admin(chat_id, user_id):
        return

    if await check_verified(chat_id, user_id):
        return

    if chat_id in active_captchas and user_id in active_captchas[chat_id]:
        try:
            await message.delete()
        except Exception:
            pass


@router.my_chat_member()
async def on_bot_chat_member_update(event: ChatMemberUpdated):
    """Проверяем права бота в чате."""
    bot = get_bot()
    if bot is None:
        return

    me = await bot.get_me()
    if event.new_chat_member.user.id != me.id:
        return

    if event.new_chat_member.status in ["administrator", "member"]:
        try:
            chat_member = await bot.get_chat_member(event.chat.id, me.id)
            print(f"[DEBUG] bot member status in chat={event.chat.id}, can_restrict_members={getattr(chat_member, 'can_restrict_members', None)}")
            if chat_member and chat_member.can_restrict_members is False:
                print("[WARN] Bot lacks can_restrict_members permission in chat:", event.chat.id)
        except Exception as e:
            print(f"[WARN] cannot check bot permissions: {e}")


@router.callback_query(F.data.startswith("captcha:"))
async def on_captcha_answer(callback: CallbackQuery):
    """Ответ на капчу"""
    data = callback.data.split(":")
    captcha_id = data[1]
    answer_idx = int(data[2])
    
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    # Проверяем, что капча существует для этого пользователя
    if chat_id not in active_captchas or user_id not in active_captchas[chat_id]:
        await callback.answer("Эта капча не для вас", show_alert=True)
        return
    
    captcha = active_captchas[chat_id][user_id]
    
    # Проверяем, что captcha_id совпадает (защита от повторных нажатий)
    if captcha["id"] != captcha_id:
        await callback.answer()
        return
    
    # Дополнительная проверка: user_id из captcha_id должен совпадать с нажавшим
    captcha_id_parts = captcha_id.split("_")
    if len(captcha_id_parts) >= 3:
        captcha_user_id = int(captcha_id_parts[1])
        if captcha_user_id != user_id:
            await callback.answer("Эта капча не для вас", show_alert=True)
            return
    
    # Удаляем сообщение
    try:
        await callback.message.delete()
    except Exception:
        pass
    
    if answer_idx == captcha["correct_idx"]:
        # Правильно!
        if chat_id in active_captchas and user_id in active_captchas[chat_id]:
            del active_captchas[chat_id][user_id]

        await database.db.update_member(chat_id, user_id, is_verified=True, rank="user")

        # Снимаем ограничения
        try:
            await callback.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=get_full_permissions()
            )
            await callback.bot.send_message(
                chat_id,
                f"{callback.from_user.full_name} {MESSAGES['captcha_success']}"
            )
        except Exception as e:
            print(f"[DEBUG] Error removing restrictions: {e}")
    else:
        # Неправильно
        if chat_id in active_captchas and user_id in active_captchas[chat_id]:
            del active_captchas[chat_id][user_id]

        try:
            await callback.bot.ban_chat_member(chat_id, user_id)
            await callback.bot.send_message(
                chat_id,
                f"{callback.from_user.full_name}, {MESSAGES['captcha_wrong']}\n\n" +
                MESSAGES["captcha_kick"].format(name=callback.from_user.full_name)
            )
        except Exception as e:
            print(f"[DEBUG] Error banning failed captcha user: {e}")
    
    await callback.answer()

async def check_verified(chat_id: int, user_id: int) -> bool:
    """Проверка верификации. Для каждого чата верификация хранится отдельно."""
    member = await database.db.get_member(chat_id, user_id)
    if member and member.is_verified:
        return True

    if chat_id in active_captchas and user_id in active_captchas[chat_id]:
        return False

    chat_status = await get_chat_member_status(chat_id, user_id)
    rank = None
    if chat_status == "creator":
        rank = "owner"
    elif chat_status == "administrator":
        rank = "admin"

    if await is_chat_owner_or_admin(chat_id, user_id):
        await database.db.ensure_member(
            chat_id=chat_id,
            user_id=user_id,
            rank=rank,
            is_verified=True,
        )
        return True

    if member is None:
        await database.db.ensure_member(
            chat_id=chat_id,
            user_id=user_id,
            is_verified=True,
        )
        return True

    # Для существующих участников без активной капчи считаем первый контакт верификацией.
    await database.db.ensure_member(
        chat_id=chat_id,
        user_id=user_id,
        is_verified=True,
    )
    return True

async def check_mute(chat_id: int, user_id: int):
    """Проверка мута"""
    return await database.db.check_mute(chat_id, user_id)