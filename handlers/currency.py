"""Курсы валют: пользователь пишет сумму с валютой (например 1g) и получает
эквивалент в долларах, Telegram Stars, белорусских рублях, российских рублях и Gram (TON)."""
import re
import time
from typing import Optional, Tuple

import aiohttp
from aiogram import Router
from aiogram.filters import BaseFilter
from aiogram.types import Message

router = Router()

# Стоимость одной Telegram Star в долларах
STARS_USD = 0.015

# Итоговый список валют, который всегда показываем (в этом порядке)
DISPLAY_CODES = ("usd", "stars", "byn", "rub", "gram")

DISPLAY_LABELS = {
    "usd": "🇺🇸 Доллары",
    "stars": "⭐ Telegram Stars",
    "byn": "🇧🇾 Белорусские рубли",
    "rub": "🇷🇺 Российские рубли",
    "gram": "💎 Gram (TON)",
}

CURRENCY_TITLES = {
    "usd": "Доллар (USD)",
    "stars": "Telegram Stars",
    "byn": "Белорусский рубль (BYN)",
    "rub": "Российский рубль (RUB)",
    "gram": "Gram (TON)",
}

SUFFIX_SYMBOLS = {
    "usd": " $",
    "rub": " ₽",
    "byn": " BYN",
    "gram": " G",
    "stars": "",
}

# Алиасы ввода -> код валюты
CURRENCY_ALIASES = {
    # Gram / TON
    "g": "gram", "gram": "gram", "gramm": "gram", "ton": "gram", "toncoin": "gram",
    "тон": "gram", "грам": "gram", "грамм": "gram", "граммов": "gram",
    # Доллар
    "usd": "usd", "usdt": "usd", "$": "usd", "доллар": "usd", "доллары": "usd",
    "долларов": "usd", "бакс": "usd", "баксов": "usd", "баксы": "usd",
    # Белорусский рубль
    "byn": "byn", "br": "byn", "белруб": "byn", "белрубль": "byn", "белрубля": "byn",
    "белрублей": "byn", "белорусскийрубль": "byn", "белорусскиерубли": "byn",
    # Российский рубль
    "rub": "rub", "rur": "rub", "ruble": "rub", "rubles": "rub", "₽": "rub",
    "руб": "rub", "рубль": "rub", "рубля": "rub", "рублей": "rub",
    # Telegram Stars
    "stars": "stars", "star": "stars", "звезда": "stars", "звезды": "stars",
    "звёзды": "stars", "звезд": "stars", "звёзд": "stars", "⭐": "stars",
}

AMOUNT_PATTERN = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*([A-Za-zА-Яа-яЁё$₽⭐]+)\s*$")

# Кэш курсов: {timestamp, usd_per}
_rates_cache = {"ts": 0.0, "usd_per": None}


def _fmt(value: float) -> str:
    """Красивое форматирование числа в зависимости от величины."""
    value = float(value)
    absolute = abs(value)
    if absolute >= 1000:
        return f"{value:,.2f}"
    if absolute >= 1:
        return f"{value:.2f}"
    if absolute >= 0.01:
        return f"{value:.4f}"
    if absolute >= 0.0001:
        return f"{value:.6f}"
    return f"{value:.8f}"


def parse_currency_query(text: Optional[str]) -> Optional[Tuple[float, str]]:
    """Разбирает запрос вида '1g', '100 rub', '5 stars'. Возвращает (сумма, код) или None."""
    if not text:
        return None

    cleaned = text.strip().strip(".!?,")
    match = AMOUNT_PATTERN.match(cleaned)
    if not match:
        return None

    try:
        amount = float(match.group(1).replace(",", "."))
    except ValueError:
        return None

    code = CURRENCY_ALIASES.get(match.group(2).lower().strip(".!?,"))
    if code is None:
        return None

    return amount, code


class CurrencyQueryFilter(BaseFilter):
    """Пропускает только сообщения-запросы курса валют."""

    async def __call__(self, message: Message) -> bool:
        if not message.text:
            return False
        if message.from_user is None or message.from_user.is_bot:
            return False
        return parse_currency_query(message.text) is not None


async def _fetch_rates() -> dict:
    """Загружает курсы и возвращает словарь {код: цена_в_USD} с кэшем на 10 минут."""
    now = time.time()
    cached = _rates_cache["usd_per"]
    if cached and now - _rates_cache["ts"] < 600:
        return cached

    usd_per = {"usd": 1.0, "stars": STARS_USD}
    timeout = aiohttp.ClientTimeout(total=10)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(
            "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json"
        ) as resp:
            data = await resp.json(content_type=None)
        usd = data.get("usd", {})
        usd_per["rub"] = 1.0 / float(usd["rub"])
        usd_per["byn"] = 1.0 / float(usd["byn"])

        async with session.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd"
        ) as resp:
            cg = await resp.json(content_type=None)
        ton_usd = cg.get("the-open-network", {}).get("usd")
        if ton_usd:
            usd_per["gram"] = float(ton_usd)
        else:
            usd_per["gram"] = 1.0 / float(usd["ton"])

    _rates_cache["ts"] = now
    _rates_cache["usd_per"] = usd_per
    return usd_per


@router.message(CurrencyQueryFilter())
async def cmd_currency(message: Message):
    """Конвертация: '1g', '1usd', '100rub', '5 stars' и т.п."""
    parsed = parse_currency_query(message.text)
    if parsed is None:
        return

    amount, code = parsed

    try:
        rates = await _fetch_rates()
    except Exception as e:
        print(f"[DEBUG] Currency rates error: {e}")
        await message.reply("❌ Не удалось получить курсы валют. Попробуй позже.")
        return

    usd_value = amount * rates[code]

    lines = [f"💱 <b>{_fmt(amount)} {CURRENCY_TITLES[code]}</b> это:", ""]
    for target in DISPLAY_CODES:
        if target == code:
            continue
        converted = usd_value / rates[target]
        lines.append(f"{DISPLAY_LABELS[target]}: <b>{_fmt(converted)}{SUFFIX_SYMBOLS[target]}</b>")

    await message.reply("\n".join(lines))
