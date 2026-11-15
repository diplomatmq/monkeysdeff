"""Топ участников чата по количеству сообщений: топ сутки / топ неделя / топ вся."""
import html
import re
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Router
from aiogram.filters import BaseFilter, Command
from aiogram.types import Message

import database

router = Router()

TOP_LIMIT = 10
MEDALS = ("🥇", "🥈", "🥉")

PERIOD_TITLES = {
    "day": "📊 <b>Топ за сутки</b>",
    "week": "📊 <b>Топ за неделю</b>",
    "all": "📊 <b>Топ за всё время</b>",
}

PERIOD_ALIASES = {
    "сутки": "day", "суток": "day", "день": "day", "за сутки": "day",
    "за день": "day", "day": "day", "today": "day",
    "неделя": "week", "неделю": "week", "недели": "week",
    "за неделю": "week", "week": "week",
    "вся": "all", "всё": "all", "все": "all", "all": "all",
    "за всё": "all", "за все": "all", "всё время": "all", "все время": "all",
}

TOP_PHRASE_PATTERN = re.compile(r"^/?\s*(?:топ|top)(?:\s+(.+?))?\s*$", re.IGNORECASE)


def parse_top_period(raw: Optional[str]) -> str:
    """Определяет период топа. По умолчанию — за всё время."""
    if not raw:
        return "all"
    return PERIOD_ALIASES.get(raw.strip().lower(), "all")


def _user_display(row: dict) -> str:
    """Имя участника с гиперссылкой на username."""
    user_id = row["user_id"]
    username = row.get("username")
    first_name = row.get("first_name")

    if first_name:
        name = html.escape(first_name)
    elif username:
        name = f"@{html.escape(username)}"
    else:
        name = f"ID:{user_id}"

    if username:
        return f'<a href="https://t.me/{html.escape(username)}">{name}</a>'
    return name


class TopPhraseFilter(BaseFilter):
    """Пропускает сообщения вида 'топ', 'топ сутки', 'топ неделя', 'топ вся'."""

    async def __call__(self, message: Message) -> bool:
        if not message.text or message.from_user is None or message.from_user.is_bot:
            return False
        return TOP_PHRASE_PATTERN.match(message.text.strip()) is not None


async def _send_top(message: Message, raw_period: Optional[str]) -> None:
    chat_id = message.chat.id
    period = parse_top_period(raw_period)

    # Сбрасываем буфер счётчиков, чтобы топ был актуальным.
    try:
        await database.db.flush_pending()
    except Exception:
        pass

    if period == "day":
        since = datetime.utcnow().date()
        rows = await database.db.get_top_messages(chat_id, since_date=since, limit=TOP_LIMIT)
    elif period == "week":
        since = datetime.utcnow().date() - timedelta(days=6)
        rows = await database.db.get_top_messages(chat_id, since_date=since, limit=TOP_LIMIT)
    else:
        rows = await database.db.get_top_all_time(chat_id, limit=TOP_LIMIT)

    lines = [PERIOD_TITLES[period], ""]
    if not rows:
        lines.append("Пока нет данных.")
    else:
        for index, row in enumerate(rows, start=1):
            prefix = MEDALS[index - 1] if index <= len(MEDALS) else f"{index}."
            lines.append(f"{prefix} {_user_display(row)} — {row['count']}")

    await message.reply("\n".join(lines))


@router.message(Command("top"))
async def cmd_top(message: Message):
    """Топ участников: /top [сутки|неделя|вся]"""
    parts = (message.text or "").split(maxsplit=1)
    raw_period = parts[1] if len(parts) > 1 else None
    await _send_top(message, raw_period)


@router.message(TopPhraseFilter())
async def cmd_top_phrase(message: Message):
    """Русские варианты: 'топ', 'топ сутки', 'топ неделя', 'топ вся'."""
    match = TOP_PHRASE_PATTERN.match((message.text or "").strip())
    raw_period = match.group(1) if match else None
    await _send_top(message, raw_period)
