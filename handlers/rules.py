"""Правила чата: установка и просмотр через команду +rules.

Формат установки — команда и текст правил в одном сообщении, текст с новой строки:
    +rules
    1. Будь вежлив
    2. Без спама <кастомный эмодзи>

Просмотр — отправить +rules без текста.

Устанавливать правила могут владелец чата и старшая обезьяна (ранг admin и выше).
"""
import re
from bisect import bisect_left
from collections import defaultdict
from html import escape as html_escape

from aiogram import F, Router
from aiogram.types import Message

import database
from config import MESSAGES, get_rank_level

router = Router()

# Команда в начале сообщения
RULE_FILTER_RE = r"(?i)^\+rules\b"
RULE_COMMAND_RE = re.compile(r"(?i)^\+rules\b[ \t]*")

# Простые теги форматирования
_SIMPLE_TAGS = {
    "bold": ("<b>", "</b>"),
    "italic": ("<i>", "</i>"),
    "underline": ("<u>", "</u>"),
    "strikethrough": ("<s>", "</s>"),
    "spoiler": ("<tg-spoiler>", "</tg-spoiler>"),
    "code": ("<code>", "</code>"),
    "blockquote": ("<blockquote>", "</blockquote>"),
    "expandable_blockquote": ("<blockquote expandable>", "</blockquote>"),
}


def _utf16_prefix(text: str) -> list:
    """Префиксные суммы длин в UTF-16 (offsets в Telegram считаются в UTF-16)."""
    prefix = [0] * (len(text) + 1)
    for i, ch in enumerate(text):
        prefix[i + 1] = prefix[i] + (2 if ord(ch) > 0xFFFF else 1)
    return prefix


def _utf16_to_index(prefix: list, offset: int) -> int:
    """Переводит UTF-16 смещение в индекс Python-строки."""
    idx = bisect_left(prefix, offset)
    return min(idx, len(prefix) - 1)


def _entity_tags(entity) -> tuple:
    """Возвращает (открывающий, закрывающий) HTML-теги для entity."""
    etype = entity.type
    if etype == "custom_emoji":
        emoji_id = getattr(entity, "custom_emoji_id", None)
        if emoji_id:
            return f'<tg-emoji emoji-id="{emoji_id}">', "</tg-emoji>"
        return "", ""
    if etype in _SIMPLE_TAGS:
        return _SIMPLE_TAGS[etype]
    if etype == "pre":
        language = getattr(entity, "language", None)
        if language:
            return f'<pre><code class="language-{html_escape(language, quote=True)}">', "</code></pre>"
        return "<pre>", "</pre>"
    if etype == "text_link":
        url = getattr(entity, "url", None)
        if url:
            return f'<a href="{html_escape(url, quote=True)}">', "</a>"
        return "", ""
    if etype == "text_mention":
        user = getattr(entity, "user", None)
        if user:
            return f'<a href="tg://user?id={user.id}">', "</a>"
        return "", ""
    return "", ""


def build_rules_html(text: str, entities, start_index: int) -> str:
    """Собирает HTML тела правил (без команды +rules), сохраняя кастомные эмодзи."""
    body = text[start_index:]
    if not body:
        return ""
    if not entities:
        return html_escape(body, quote=False)

    full_prefix = _utf16_prefix(text)
    body_prefix = _utf16_prefix(body)
    body_start_u16 = full_prefix[start_index]

    opens = defaultdict(list)
    closes = defaultdict(list)

    for index, entity in enumerate(entities):
        open_tag, close_tag = _entity_tags(entity)
        if not open_tag and not close_tag:
            continue

        start_u16 = entity.offset - body_start_u16
        if start_u16 < 0:
            continue
        end_u16 = start_u16 + entity.length

        start_py = _utf16_to_index(body_prefix, start_u16)
        end_py = _utf16_to_index(body_prefix, end_u16)
        if start_py >= end_py or end_py > len(body):
            continue

        opens[start_py].append((index, end_py, open_tag))
        closes[end_py].append((index, start_py, close_tag))

    # Порядок тегов для корректной вложенности
    for items in opens.values():
        items.sort(key=lambda item: (-item[1], item[0]))
    for items in closes.values():
        items.sort(key=lambda item: (-item[1], -item[0]))

    parts = []
    for i in range(len(body)):
        for _, _, tag in closes.get(i, []):
            parts.append(tag)
        for _, _, tag in opens.get(i, []):
            parts.append(tag)
        parts.append(html_escape(body[i], quote=False))

    for _, _, tag in closes.get(len(body), []):
        parts.append(tag)
    for _, _, tag in opens.get(len(body), []):
        parts.append(tag)

    return "".join(parts)


async def can_manage_rules(message: Message) -> bool:
    """Владелец чата и старшая обезьяна (admin, уровень 4) могут задавать правила."""
    chat_id = message.chat.id
    user_id = message.from_user.id

    try:
        member = await message.chat.get_member(user_id)
        if member.status in ("creator", "administrator"):
            return True
    except Exception:
        pass

    db_member = await database.db.get_member(chat_id, user_id)
    return bool(db_member and get_rank_level(db_member.rank) >= 4)


@router.message(F.text.regexp(RULE_FILTER_RE))
async def cmd_rules(message: Message):
    """+rules — задать правила (владелец/старшая обезьяна) или показать их."""
    if message.from_user is None or message.from_user.is_bot:
        return

    raw = message.text or ""
    match = RULE_COMMAND_RE.match(raw)
    if not match:
        return

    start_index = match.end()
    while start_index < len(raw) and raw[start_index] == "\n":
        start_index += 1

    body = raw[start_index:]
    chat_id = message.chat.id

    # Показ правил
    if not body.strip():
        chat = await database.db.get_chat(chat_id)
        rules = chat.rules_text if chat else None
        if not rules:
            await message.reply("📜 Правила ещё не установлены.")
            return
        try:
            await message.reply(rules)
        except Exception as e:
            print(f"[DEBUG] rules send error: {e}")
            await message.reply("❌ Не удалось отправить правила.")
        return

    # Установка правил
    if not await can_manage_rules(message):
        await message.reply(MESSAGES["no_permission"])
        return

    html = build_rules_html(raw, message.entities or [], start_index)
    if not html.strip():
        await message.reply("❌ Пустые правила.")
        return

    await database.db.get_or_create_chat(chat_id, message.chat.title)
    await database.db.update_chat(chat_id, rules_text=html)

    await message.reply("✅ Правила обновлены. Посмотреть: +rules")
