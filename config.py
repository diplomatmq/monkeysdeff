"""Конфигурация бота с капчей из 4 кнопок"""
from dataclasses import dataclass
from typing import List, Dict
import os

USE_CUSTOM_EMOJI = os.environ.get("USE_CUSTOM_EMOJI", "1") == "1"


def emoji(custom_emoji_id: str, fallback: str) -> str:
    if USE_CUSTOM_EMOJI and custom_emoji_id:
        return f'<tg-emoji emoji-id="{custom_emoji_id}">{fallback}</tg-emoji>'
    return fallback


@dataclass
class CaptchaOption:
    """Вариант ответа"""
    text: str
    is_correct: bool

@dataclass
class CaptchaQuestion:
    """Вопрос капчи"""
    question: str
    options: List[CaptchaOption]

# Капча с 4 вариантами ответов (1 правильный)
CAPTCHA_QUESTIONS = [
    # Математика
    CaptchaQuestion(
        question="Сколько будет 5 + 8?",
        options=[
            CaptchaOption("10", False),
            CaptchaOption("13", True),  # ✓
            CaptchaOption("15", False),
            CaptchaOption("12", False),
        ]
    ),
    CaptchaQuestion(
        question="Сколько будет 7 × 6?",
        options=[
            CaptchaOption("42", True),  # ✓
            CaptchaOption("36", False),
            CaptchaOption("48", False),
            CaptchaOption("40", False),
        ]
    ),
    CaptchaQuestion(
        question="Сколько будет 15 - 7?",
        options=[
            CaptchaOption("6", False),
            CaptchaOption("7", False),
            CaptchaOption("9", False),
            CaptchaOption("8", True),  # ✓
        ]
    ),
    CaptchaQuestion(
        question="Сколько будет 9 + 9?",
        options=[
            CaptchaOption("16", False),
            CaptchaOption("18", True),  # ✓
            CaptchaOption("20", False),
            CaptchaOption("17", False),
        ]
    ),
    
    # География
    CaptchaQuestion(
        question="Столица Франции?",
        options=[
            CaptchaOption("Лондон", False),
            CaptchaOption("Берлин", False),
            CaptchaOption("Париж", True),  # ✓
            CaptchaOption("Мадрид", False),
        ]
    ),
    CaptchaQuestion(
        question="Столица США?",
        options=[
            CaptchaOption("Нью-Йорк", False),
            CaptchaOption("Вашингтон", True),  # ✓
            CaptchaOption("Лос-Анджелес", False),
            CaptchaOption("Чикаго", False),
        ]
    ),
    CaptchaQuestion(
        question="Столица Японии?",
        options=[
            CaptchaOption("Сеул", False),
            CaptchaOption("Пекин", False),
            CaptchaOption("Токио", True),  # ✓
            CaptchaOption("Бангкок", False),
        ]
    ),
    CaptchaQuestion(
        question="Столица Германии?",
        options=[
            CaptchaOption("Мюнхен", False),
            CaptchaOption("Гамбург", False),
            CaptchaOption("Берлин", True),  # ✓
            CaptchaOption("Франкфурт", False),
        ]
    ),
    
    # Общие знания
    CaptchaQuestion(
        question="Сколько дней в году?",
        options=[
            CaptchaOption("365", True),  # ✓
            CaptchaOption("364", False),
            CaptchaOption("366", False),
            CaptchaOption("360", False),
        ]
    ),
    CaptchaQuestion(
        question="Какой океан самый большой?",
        options=[
            CaptchaOption("Атлантический", False),
            CaptchaOption("Индийский", False),
            CaptchaOption("Тихий", True),  # ✓
            CaptchaOption("Северный Ледовитый", False),
        ]
    ),
]

ALERT_EMOJI_ID = "5391195988213898388"
ALERT = emoji(ALERT_EMOJI_ID, "🚨")

RANKS = {
    "newbie": {"name": "Маленькая обезьянка", "level": 0, "permissions": ["captcha"], "emoji": "👶", "custom_emoji": "5341564243789487821"},
    "user": {"name": "Обезьяна", "level": 1, "permissions": ["captcha", "write"], "emoji": "👤", "custom_emoji": "5974048815789903111"},
    "trusted": {"name": "Доверенная обезьяна", "level": 2, "permissions": ["captcha", "write", "warn"], "emoji": "🤝", "custom_emoji": "5395732581780040886"},
    "moderator": {"name": "Обезьяний защитник", "level": 3, "permissions": ["captcha", "write", "warn", "mute", "info"], "emoji": "🛡️", "custom_emoji": "5467810048631658566"},
    "admin": {"name": "Старшая обезьяна", "level": 4, "permissions": ["captcha", "write", "warn", "mute", "unmute", "kick", "ban", "unban", "setrole", "promote", "demote", "info", "settings"], "emoji": "⚡", "custom_emoji": "6129805886383723340"},
    "owner": {"name": "Король обезьян", "level": 5, "permissions": ["captcha", "write", "warn", "mute", "unmute", "kick", "ban", "unban", "setrole", "promote", "demote", "info", "settings", "delete", "all"], "emoji": "👑", "custom_emoji": "6003614086460346468"},
}


def get_messages():
    alert = ALERT
    return {
        "welcome_new": "👋 <b>Привет, {name}!</b>\n\nЧтобы получить доступ к чату, пройди капчу.\n\n⏱️ У тебя 5 минут.",
        "welcome_return": "👋 <b>С возвращением, {name}!</b>\n\nДобро пожаловать обратно! 🎉",
        "captcha_title": "🔐 <b>Проверка на бота</b>",
        "captcha_question": "{question}",
        "captcha_time": "⏱️ Осталось {seconds} сек",
        "captcha_wrong": "❌ <b>Неправильно!</b>\n\nПопробуй ещё раз.",
        "captcha_success": "✅ <b>Капча пройдена!</b>\n\nДобро пожаловать в чат! 🎉",
        "captcha_timeout": "❌ <b>Время вышло!</b>\n\nКапча не пройдена.",
        "captcha_kick": "🚪 {name} не прошёл капчу и был исключён.",
        "mute_self": "❌ Нельзя замутить себя.",
        "ban_self": "❌ Нельзя забанить себя.",
        "kick_self": "❌ Нельзя кикнуть себя.",
        "user_muted": f"{alert} Ты замьючен до {{time}}.\nПричина: {{reason}}",
        "user_not_found": "❌ Пользователь не найден.",
        "mute_success": f"{alert} <b>{{user}}</b> замьючен на {{duration}} мин.\n📝 {{reason}}",
        "unmute_success": "🔊 <b>{user}</b> размьючен!",
        "ban_success": "🚫 <b>{user}</b> забанен.\n📝 {reason}",
        "ban_limit": "🚫 <b>{user}</b> забанен (лимит варнов).",
        "warn_success": "⚠️ <b>{user}</b> +1 варн (#{count}).\n📝 {reason}",
        "warn_info": "⚠️ У тебя {count}/{max} варнов",
        "unwarn_success": "✅ У <b>{user}</b> снято предупреждение. Сейчас: {count}/{max}",
        "kick_success": "🚪 <b>{user}</b> исключён из чата.\n📝 {reason}",
        "role_set_success": "⭐ <b>{user}</b> получил роль: {role}",
        "role_set_error": "❌ Неверная роль. Доступно: user, moderator, admin",

        "spam_stickers": f"{alert} <b>{{user}}</b>: {{count}} стикеров → мут {{duration}} мин",
        "spam_repeat": f"{alert} <b>{{user}}</b>: повторы → мут {{duration}} мин",

        "no_permission": "❌ Нет прав",
        "promote_success": "⬆️ <b>{user}</b> → {rank}",
        "demote_success": "⬇️ <b>{user}</b> → {rank}",
        "settings_help": (
            "⚙️ <b>Настройки чата:</b>\n\n"
            "/settings\n"
            "/setcaptcha on|off\n"
            "/setcaptcha_timeout [сек]\n"
            "/setstickerlimit [число]\n"
            "/setwarnings [число]\n"
            "/setmutetime [минуты]"
        ),
        
        "help": (
            "📚 <b>Команды:</b>\n\n"
            "⚠️ /warn [id|@user|reply] [причина]\n"
            "/unwarn [id|@user|reply]\n"
            "/mywarnings\n\n"
            "🚨 /mute [id|@user|reply] [1h|30m|10s] [причина]\n"
            "/unmute [id|@user|reply]\n\n"
            "🚫 /ban [id|@user|reply] [причина]\n"
            "/unban [id|@user|reply]\n\n"
            "🚪 /kick [id|@user|reply] [причина]\n\n"
            "⭐ /setrole [id|@user|reply] [user|moderator|admin]\n"
            "/promote [id] [ранг]\n"
            "/demote [id] [ранг]\n"
            "/ranklist\n\n"
            "ℹ️ /info [id|@user|reply]\n"
            "/help"
        ),
        "rank_list": (
            "⭐ <b>Ранги:</b>\n\n"
            f"{emoji(RANKS['newbie']['custom_emoji'], '👶')} Маленькая обезьянка\n"
            f"{emoji(RANKS['user']['custom_emoji'], '👤')} Обезьяна\n"
            f"{emoji(RANKS['trusted']['custom_emoji'], '🤝')} Доверенная обезьяна\n"
            f"{emoji(RANKS['moderator']['custom_emoji'], '🛡️')} Обезьяний защитник\n"
            f"{emoji(RANKS['admin']['custom_emoji'], '⚡')} Старшая обезьяна\n"
            f"{emoji(RANKS['owner']['custom_emoji'], '👑')} Король обезьян"
        ),
        "settings": (
            "⚙️ <b>Настройки:</b>\n\n"
            "/settings\n"
            "/setcaptcha on|off\n"
            "/setcaptcha_timeout [сек]\n"
            "/setstickerlimit [число]\n"
            "/setwarnings [число]\n"
            "/setmutetime [минуты]"
        ),
    }


MESSAGES = get_messages()

PERMISSION_REQUIREMENTS = {
    "warn": "trusted",
    "mute": "moderator",
    "unmute": "admin",
    "kick": "admin",
    "ban": "admin",
    "unban": "admin",
    "setrole": "admin",
    "promote": "admin",
    "demote": "admin",
    "info": "user",
    "settings": "admin",
}


def has_permission(rank: str, perm: str) -> bool:
    if rank not in RANKS:
        return False
    return perm in RANKS[rank]["permissions"] or "all" in RANKS[rank]["permissions"]


def get_required_rank_for_permission(perm: str) -> str:
    return PERMISSION_REQUIREMENTS.get(perm, "user")


def get_rank_level(rank: str) -> int:
    return RANKS.get(rank, {}).get("level", -1)


def get_rank_display(rank: str) -> str:
    if rank in RANKS:
        custom_emoji = RANKS[rank].get('custom_emoji')
        return f"{emoji(custom_emoji, RANKS[rank]['emoji'])} {RANKS[rank]['name']}"
    return "❓"