"""Клавиатуры бота"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

def get_captcha_keyboard() -> InlineKeyboardMarkup:
    """Кнопка начала капчи"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔐 Пройти капчу", callback_data="start_captcha"))
    builder.adjust(1)
    return builder.as_markup()

def get_captcha_answer_keyboard(captcha_id: int) -> InlineKeyboardMarkup:
    """Кнопка отмены капчи"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel_captcha:{captcha_id}"))
    builder.adjust(1)
    return builder.as_markup()

def get_ranks_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура рангов для повышения"""
    builder = InlineKeyboardBuilder()
    ranks = [
        ("👤 Пользователь", "rank:user"),
        ("🤝 Доверенный", "rank:trusted"),
        ("🛡️ Модератор", "rank:moderator"),
        ("⚡ Администратор", "rank:admin"),
    ]
    for text, cb in ranks:
        builder.add(InlineKeyboardButton(text=text, callback_data=cb))
    builder.adjust(1)
    return builder.as_markup()

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📚 Помощь", callback_data="menu:help"))
    builder.add(InlineKeyboardButton(text="⭐ Ранги", callback_data="menu:ranks"))
    builder.add(InlineKeyboardButton(text="🔐 Капча", callback_data="menu:captcha"))
    builder.adjust(1)
    return builder.as_markup()