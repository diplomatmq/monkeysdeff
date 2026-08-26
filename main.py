"""Главный файл запуска бота"""
import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

from config import CAPTCHA_QUESTIONS
from database import Database
from handlers import captcha, antispam, moderation, ranks, settings, common

# Инициализация БД с правильным путём
import os
db_path = os.path.join(os.path.dirname(__file__), "data", "bot.db")
os.makedirs(os.path.dirname(db_path), exist_ok=True)
db = Database(db_path)

async def init_database():
    await db.init_db()

def load_token() -> str:
    """Загрузка токена"""
    env = Path(".env")
    if env.exists():
        with open(env, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("BOT_TOKEN="):
                    return line.split("=", 1)[1].strip()
    
    token = os.environ.get("BOT_TOKEN")
    if token:
        return token
    
    raise ValueError("BOT_TOKEN не найден! Создай .env файл с BOT_TOKEN=твой_токен")

async def main():
    """Запуск"""
    logger.info("🚀 Запуск бота...")
    
    await init_database()
    
    # aiogram 3.x использует DefaultBotProperties
    default = DefaultBotProperties(parse_mode="HTML")
    bot = Bot(token=load_token(), default=default)
    captcha.bot = bot
    dp = Dispatcher(storage=MemoryStorage())
    
    # Регистрация роутеров
    dp.include_router(common.router)  # Общие команды (start, help, me)
    dp.include_router(moderation.router)  # Команды модерации
    dp.include_router(ranks.router)  # Команды рангов
    dp.include_router(settings.router)  # Команды настроек
    dp.include_router(captcha.router)  # Капча
    dp.include_router(antispam.router)  # Антиспам
    
    # Фоновые задачи
    asyncio.create_task(antispam.cleanup_task())
    asyncio.create_task(captcha.cleanup_task())
    
    logger.info("✅ Бот запущен!")
    print("[DEBUG] Bot started, waiting for updates...")
    
    try:
        while True:
            try:
                await dp.start_polling(bot)
                break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"⚠️ Потеряно соединение с Telegram: {e}")
                logger.info("🔁 Повторная попытка запуска polling через 3 сек...")
                await asyncio.sleep(3)
    finally:
        await db.close()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Остановлен")
    except Exception as e:
        logger.error(f"❌ {e}")