"""База данных с поддержкой множества чатов"""
import asyncio
import datetime
from typing import Optional, List, Dict, Any
from collections import defaultdict
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, BigInteger, Float, select, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker

Base = declarative_base()

class Chat(Base):
    """Чат (поддержка множества чатов)"""
    __tablename__ = "chats"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=True)
    
    # Настройки чата
    captcha_enabled = Column(Boolean, default=True)
    captcha_timeout = Column(Integer, default=300)
    captcha_attempts = Column(Integer, default=3)
    
    sticker_limit = Column(Integer, default=5)
    sticker_timeout = Column(Integer, default=10)
    sticker_mute_duration = Column(Integer, default=10)
    
    repeat_limit = Column(Integer, default=3)
    repeat_timeout = Column(Integer, default=10)
    
    warnings_to_ban = Column(Integer, default=3)
    default_mute_duration = Column(Integer, default=10)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class ChatMember(Base):
    """Участник чата с рангом"""
    __tablename__ = "chat_members"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    
    # Информация о пользователе
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    
    # Статус в чате
    rank = Column(String(50), default="user")
    is_verified = Column(Boolean, default=False)
    is_muted = Column(Boolean, default=False)
    mute_until = Column(DateTime, nullable=True)
    mute_reason = Column(Text, nullable=True)
    warnings = Column(Integer, default=0)
    messages_count = Column(Integer, default=0)
    captcha_attempts = Column(Integer, default=0)
    
    # Активность
    last_activity = Column(DateTime, default=datetime.datetime.utcnow)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    
    # Составной уникальный индекс
    __table_args__ = (
        {"sqlite_autoincrement": True},
    )

class Warning(Base):
    """Предупреждения"""
    __tablename__ = "warnings"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    moderator_id = Column(BigInteger, nullable=False)
    reason = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class MuteRecord(Base):
    """Записи о мутах"""
    __tablename__ = "mute_records"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    moderator_id = Column(BigInteger, nullable=False)
    duration = Column(Integer, nullable=False)  # минуты
    reason = Column(Text, nullable=True)
    is_expired = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)

class BanRecord(Base):
    """Записи о банах"""
    __tablename__ = "ban_records"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    moderator_id = Column(BigInteger, nullable=False)
    reason = Column(Text, nullable=True)
    is_unbanned = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class SpamLog(Base):
    """Логи спама"""
    __tablename__ = "spam_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    spam_type = Column(String(50), nullable=False)  # sticker, repeat, flood
    count = Column(Integer, default=1)
    action = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class CaptchaAttempt(Base):
    """Попытки капчи"""
    __tablename__ = "captcha_attempts"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    attempt_number = Column(Integer, default=1)
    is_completed = Column(Boolean, default=False)
    is_failed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Database:
    """Класс работы с БД"""

    def __init__(self, db_path: str = "bot.db"):
        self.async_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
        self.async_session = async_sessionmaker(
            self.async_engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        self.sync_engine = create_engine(f"sqlite:///{db_path}", echo=False)
        self.sync_session = sessionmaker(bind=self.sync_engine)

        # Буфер для инкрементов сообщений (для оптимизации при высокой нагрузке)
        self.message_increment_buffer = defaultdict(int)
        self._flush_task = None
    
    async def init_db(self):
        """Инициализация БД"""
        async with self.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Включаем WAL-режим для лучшей производительности
            await conn.exec_driver_sql("PRAGMA journal_mode=WAL;")

        await self._migrate_missing_columns()

        # Запускаем фоновую задачу для сброса буфера сообщений
        self._flush_task = asyncio.create_task(self._flush_message_buffer_loop())

    async def _migrate_missing_columns(self):
        """Добавляет отсутствующие колонки в старые SQLite-базы."""
        async with self.async_engine.begin() as conn:
            result = await conn.exec_driver_sql("PRAGMA table_info(chat_members)")
            columns = [row[1] for row in result]

        for column_name, column_type, default_value in [
            ("captcha_attempts", "INTEGER DEFAULT 0", "0"),
            ("messages_count", "INTEGER DEFAULT 0", "0"),
        ]:
            if column_name not in columns:
                async with self.async_engine.begin() as conn:
                    await conn.exec_driver_sql(
                        f"ALTER TABLE chat_members ADD COLUMN {column_name} {column_type}"
                    )

    async def _flush_message_buffer_loop(self):
        """Фоновая задача для периодического сброса буфера сообщений в БД"""
        while True:
            try:
                await asyncio.sleep(5)  # Сброс каждые 5 секунд
                await self._flush_message_buffer()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[ERROR] Error flushing message buffer: {e}")

    async def _flush_message_buffer(self):
        """Сбрасывает накопленные инкременты сообщений в БД"""
        if not self.message_increment_buffer:
            return

        buffer_copy = dict(self.message_increment_buffer)
        self.message_increment_buffer.clear()

        async with self.async_session() as session:
            for (chat_id, user_id), count in buffer_copy.items():
                try:
                    result = await session.execute(
                        select(ChatMember)
                        .where(ChatMember.chat_id == chat_id)
                        .where(ChatMember.user_id == user_id)
                    )
                    member = result.scalar_one_or_none()
                    if member:
                        member.messages_count = (member.messages_count or 0) + count
                        member.last_activity = datetime.datetime.utcnow()
                except Exception as e:
                    print(f"[ERROR] Error incrementing message count for {chat_id}:{user_id}: {e}")

            await session.commit()
    
    # === CHATS ===
    async def get_chat(self, chat_id: int) -> Optional[Chat]:
        """Получение чата"""
        async with self.async_session() as session:
            result = await session.execute(
                Chat.__table__.select().where(Chat.chat_id == chat_id)
            )
            row = result.fetchone()
            if row:
                return Chat(**dict(row._mapping))
            return None
    
    async def create_chat(self, chat_id: int, title: str = None) -> Chat:
        """Создание чата"""
        async with self.async_session() as session:
            chat = Chat(chat_id=chat_id, title=title)
            session.add(chat)
            await session.commit()
            await session.refresh(chat)
            return chat
    
    async def update_chat(self, chat_id: int, **kwargs) -> Optional[Chat]:
        """Обновление настроек чата"""
        async with self.async_session() as session:
            result = await session.execute(
                select(Chat).where(Chat.chat_id == chat_id)
            )
            chat = result.scalar_one_or_none()
            if not chat:
                return None

            for key, value in kwargs.items():
                if hasattr(chat, key):
                    setattr(chat, key, value)

            await session.commit()
            await session.refresh(chat)
            return chat
    
    async def get_or_create_chat(self, chat_id: int, title: str = None) -> Chat:
        """Получение или создание чата"""
        chat = await self.get_chat(chat_id)
        if not chat:
            chat = await self.create_chat(chat_id, title)
        return chat
    
    # === CHAT MEMBERS ===
    async def get_member(self, chat_id: int, user_id: int) -> Optional[ChatMember]:
        """Получение участника чата"""
        async with self.async_session() as session:
            result = await session.execute(
                ChatMember.__table__.select()
                .where(ChatMember.chat_id == chat_id)
                .where(ChatMember.user_id == user_id)
            )
            row = result.fetchone()
            if row:
                return ChatMember(**dict(row._mapping))
            return None
    
    async def create_member(self, chat_id: int, user_id: int, 
                           username: str = None, first_name: str = None) -> ChatMember:
        """Создание участника"""
        async with self.async_session() as session:
            member = ChatMember(
                chat_id=chat_id,
                user_id=user_id,
                username=username,
                first_name=first_name,
                rank="newbie",
                is_verified=False,
                messages_count=0,
                captcha_attempts=0
            )
            session.add(member)
            await session.commit()
            await session.refresh(member)
            return member
    
    async def update_member(self, chat_id: int, user_id: int, **kwargs) -> Optional[ChatMember]:
        """Обновление участника"""
        async with self.async_session() as session:
            result = await session.execute(
                select(ChatMember)
                .where(ChatMember.chat_id == chat_id)
                .where(ChatMember.user_id == user_id)
            )
            member = result.scalar_one_or_none()
            if not member:
                return None

            for key, value in kwargs.items():
                if hasattr(member, key):
                    setattr(member, key, value)

            await session.commit()
            await session.refresh(member)
            return member
    
    async def get_or_create_member(self, chat_id: int, user_id: int,
                                   username: str = None, first_name: str = None) -> ChatMember:
        """Получение или создание участника"""
        member = await self.get_member(chat_id, user_id)
        if not member:
            member = await self.create_member(chat_id, user_id, username, first_name)
        return member

    async def ensure_member(
        self,
        chat_id: int,
        user_id: int,
        username: str = None,
        first_name: str = None,
        rank: str = None,
        is_verified: bool | None = None,
    ) -> ChatMember:
        """Создаёт участника при отсутствии и обновляет ключевые поля при наличии.

        Особенность: rank='user' не перезаписывает явно установленные ранги
        (moderator, trusted, admin, owner), чтобы promote/setrole не откатывались
        обратно при обычных ensure_member вызовах из profile/антиспама.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(ChatMember)
                .where(ChatMember.chat_id == chat_id)
                .where(ChatMember.user_id == user_id)
            )
            member = result.scalar_one_or_none()

            if not member:
                member = ChatMember(
                    chat_id=chat_id,
                    user_id=user_id,
                    username=username,
                    first_name=first_name,
                    rank=rank or "user",
                    is_verified=bool(is_verified),
                    messages_count=0,
                    captcha_attempts=0,
                    created_at=datetime.datetime.utcnow(),
                )
                session.add(member)
            else:
                if username is not None:
                    member.username = username
                if first_name is not None:
                    member.first_name = first_name
                if rank is not None:
                    # Only update rank if explicitly set to a non-default value
                    # or if the current rank is "newbie" or not set
                    if rank != "user":
                        member.rank = rank
                    elif (not member.rank) or member.rank in ("newbie",):
                        member.rank = "user"
                if is_verified is not None:
                    member.is_verified = is_verified
                member.last_activity = datetime.datetime.utcnow()

            await session.commit()
            await session.refresh(member)
            return member
    
    async def get_chat_members(self, chat_id: int, rank: str = None) -> List[ChatMember]:
        """Получение участников чата"""
        async with self.async_session() as session:
            query = ChatMember.__table__.select().where(ChatMember.chat_id == chat_id)
            if rank:
                query = query.where(ChatMember.rank == rank)
            
            result = await session.execute(query)
            rows = result.fetchall()
            return [ChatMember(**dict(row._mapping)) for row in rows]

    async def get_member_by_username(self, chat_id: int, username: str) -> Optional[ChatMember]:
        """Поиск участника чата по username (без @, регистронезависимо)."""
        if not username:
            return None

        normalized = username.lstrip("@").lower()
        async with self.async_session() as session:
            result = await session.execute(
                select(ChatMember)
                .where(ChatMember.chat_id == chat_id)
                .where(ChatMember.username.isnot(None))
                .where(func.lower(ChatMember.username) == normalized)
                .order_by(ChatMember.updated_at.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def get_member_by_username_global(self, username: str) -> Optional[ChatMember]:
        """Поиск пользователя по username среди всех известных чатов."""
        if not username:
            return None

        normalized = username.lstrip("@").lower()
        async with self.async_session() as session:
            result = await session.execute(
                select(ChatMember)
                .where(ChatMember.username.isnot(None))
                .where(func.lower(ChatMember.username) == normalized)
                .order_by(ChatMember.updated_at.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def increment_message_count(self, chat_id: int, user_id: int) -> Optional[ChatMember]:
        """Увеличивает счётчик сообщений пользователя в данном чате с буферизацией."""
        # Добавляем в буфер вместо прямого обращения к БД
        self.message_increment_buffer[(chat_id, user_id)] += 1
        return None
    
    # === WARNINGS ===
    async def add_warning(self, chat_id: int, user_id: int, moderator_id: int, reason: str) -> Warning:
        """Добавление предупреждения"""
        async with self.async_session() as session:
            warning = Warning(
                chat_id=chat_id,
                user_id=user_id,
                moderator_id=moderator_id,
                reason=reason
            )
            session.add(warning)

            result = await session.execute(
                select(ChatMember)
                .where(ChatMember.chat_id == chat_id)
                .where(ChatMember.user_id == user_id)
            )
            member = result.scalar_one_or_none()
            if member:
                member.warnings += 1

            await session.commit()
            await session.refresh(warning)
            return warning
    
    async def get_warnings(self, chat_id: int, user_id: int) -> List[Warning]:
        """Получение предупреждений пользователя"""
        async with self.async_session() as session:
            result = await session.execute(
                Warning.__table__.select()
                .where(Warning.chat_id == chat_id)
                .where(Warning.user_id == user_id)
                .order_by(Warning.created_at.desc())
            )
            rows = result.fetchall()
            return [Warning(**dict(row._mapping)) for row in rows]
    
    async def remove_last_warning(self, chat_id: int, user_id: int) -> Optional[Warning]:
        """Снятие последнего предупреждения"""
        async with self.async_session() as session:
            result = await session.execute(
                select(Warning)
                .where(Warning.chat_id == chat_id)
                .where(Warning.user_id == user_id)
                .order_by(Warning.created_at.desc())
                .limit(1)
            )
            warning = result.scalar_one_or_none()
            if not warning:
                return None

            await session.delete(warning)

            member_result = await session.execute(
                select(ChatMember)
                .where(ChatMember.chat_id == chat_id)
                .where(ChatMember.user_id == user_id)
            )
            member = member_result.scalar_one_or_none()
            if member and member.warnings > 0:
                member.warnings -= 1

            await session.commit()
            return warning
    
    async def clear_warnings(self, chat_id: int, user_id: int):
        """Очистка предупреждений"""
        async with self.async_session() as session:
            await session.execute(
                Warning.__table__.delete()
                .where(Warning.chat_id == chat_id)
                .where(Warning.user_id == user_id)
            )

            member_result = await session.execute(
                select(ChatMember)
                .where(ChatMember.chat_id == chat_id)
                .where(ChatMember.user_id == user_id)
            )
            member = member_result.scalar_one_or_none()
            if member:
                member.warnings = 0

            await session.commit()
    
    # === MUTES ===
    async def mute_user(self, chat_id: int, user_id: int, moderator_id: int,
                       duration_minutes: int, reason: str = None) -> Optional[datetime]:
        """Мут пользователя"""
        mute_until = datetime.datetime.utcnow() + datetime.timedelta(minutes=duration_minutes)
        
        async with self.async_session() as session:
            # Запись о муте
            mute_record = MuteRecord(
                chat_id=chat_id,
                user_id=user_id,
                moderator_id=moderator_id,
                duration=duration_minutes,
                reason=reason,
                expires_at=mute_until
            )
            session.add(mute_record)
            
            # Обновление участника
            result = await session.execute(
                select(ChatMember)
                .where(ChatMember.chat_id == chat_id)
                .where(ChatMember.user_id == user_id)
            )
            member = result.scalar_one_or_none()
            if member:
                member.is_muted = True
                member.mute_until = mute_until
                member.mute_reason = reason
            
            await session.commit()
            return mute_until
    
    async def unmute_user(self, chat_id: int, user_id: int) -> bool:
        """Размут"""
        async with self.async_session() as session:
            result = await session.execute(
                select(ChatMember)
                .where(ChatMember.chat_id == chat_id)
                .where(ChatMember.user_id == user_id)
            )
            member = result.scalar_one_or_none()
            if member:
                member.is_muted = False
                member.mute_until = None
                member.mute_reason = None
                await session.commit()
                return True
            return False
    
    async def check_mute(self, chat_id: int, user_id: int) -> tuple[bool, datetime]:
        """Проверка мута"""
        member = await self.get_member(chat_id, user_id)
        if not member or not member.is_muted:
            return False, None
        
        if member.mute_until and member.mute_until < datetime.datetime.utcnow():
            await self.unmute_user(chat_id, user_id)
            return False, None
        
        return True, member.mute_until
    
    async def get_active_mutes(self, chat_id: int) -> List[MuteRecord]:
        """Активные муты"""
        async with self.async_session() as session:
            result = await session.execute(
                MuteRecord.__table__.select()
                .where(MuteRecord.chat_id == chat_id)
                .where(MuteRecord.is_expired == False)
                .order_by(MuteRecord.created_at.desc())
            )
            rows = result.fetchall()
            return [MuteRecord(**dict(row._mapping)) for row in rows]
    
    # === BANS ===
    async def ban_user(self, chat_id: int, user_id: int, moderator_id: int, 
                      reason: str = None) -> BanRecord:
        """Бан пользователя"""
        async with self.async_session() as session:
            ban_record = BanRecord(
                chat_id=chat_id,
                user_id=user_id,
                moderator_id=moderator_id,
                reason=reason
            )
            session.add(ban_record)
            
            # Обновление участника
            result = await session.execute(
                select(ChatMember)
                .where(ChatMember.chat_id == chat_id)
                .where(ChatMember.user_id == user_id)
            )
            member = result.scalar_one_or_none()
            if member:
                member.is_verified = False
                member.rank = "banned"
            
            await session.commit()
            await session.refresh(ban_record)
            return ban_record
    
    async def unban_user(self, chat_id: int, user_id: int) -> bool:
        """Разбан"""
        async with self.async_session() as session:
            result = await session.execute(
                select(BanRecord)
                .where(BanRecord.chat_id == chat_id)
                .where(BanRecord.user_id == user_id)
                .where(BanRecord.is_unbanned == False)
                .order_by(BanRecord.created_at.desc())
                .limit(1)
            )
            ban_record = result.scalar_one_or_none()
            if not ban_record:
                return False

            ban_record.is_unbanned = True

            member_result = await session.execute(
                select(ChatMember)
                .where(ChatMember.chat_id == chat_id)
                .where(ChatMember.user_id == user_id)
            )
            member = member_result.scalar_one_or_none()
            if member:
                member.is_verified = True
                member.rank = "user"
            
            await session.commit()
            return True
    
    async def is_banned(self, chat_id: int, user_id: int) -> bool:
        """Проверка бана"""
        async with self.async_session() as session:
            result = await session.execute(
                BanRecord.__table__.select()
                .where(BanRecord.chat_id == chat_id)
                .where(BanRecord.user_id == user_id)
                .where(BanRecord.is_unbanned == False)
            )
            return result.fetchone() is not None
    
    # === SPAM LOGS ===
    async def log_spam(self, chat_id: int, user_id: int, spam_type: str, 
                      count: int = 1, action: str = None):
        """Логирование спама"""
        async with self.async_session() as session:
            log = SpamLog(
                chat_id=chat_id,
                user_id=user_id,
                spam_type=spam_type,
                count=count,
                action=action
            )
            session.add(log)
            await session.commit()
    
    async def get_spam_logs(self, chat_id: int, user_id: int = None, 
                           limit: int = 50) -> List[SpamLog]:
        """Получение логов спама"""
        async with self.async_session() as session:
            query = SpamLog.__table__.select().where(SpamLog.chat_id == chat_id)
            if user_id:
                query = query.where(SpamLog.user_id == user_id)
            query = query.order_by(SpamLog.created_at.desc()).limit(limit)
            
            result = await session.execute(query)
            rows = result.fetchall()
            return [SpamLog(**dict(row._mapping)) for row in rows]
    
    async def close(self):
        """Закрытие"""
        await self.async_engine.dispose()

db = None


def set_database(instance: Database):
    global db
    db = instance


async def init_database():
    if db is None:
        raise RuntimeError("Database instance not set. Call set_database() first.")
    await db.init_db()