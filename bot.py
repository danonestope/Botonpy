import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram.filters import CommandStart
from aiogram.enums import ChatType
import sqlite3
import time
from aiocache import cached, SimpleMemoryCache

TOKEN = "7854761975:AAGq6W3NTyVu73GUgb8WTyMsSUDojt2F2F4"
SUPPORT_CHAT_ID = -1002445881668
SPAM_LIMIT = 3
SPAM_TIMEFRAME = 10
MAX_MESSAGE_LENGTH = 500
DATABASE_NAME = "bot_database.db"

bot = Bot(token=TOKEN)
dp = Dispatcher()

def init_db():
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                spam_count INTEGER DEFAULT 0,
                last_message_time REAL,
                last_message_text TEXT,
                blacklisted INTEGER DEFAULT 0
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                message_id INTEGER PRIMARY KEY,
                user_id INTEGER,
                support_message_id INTEGER
            )
        ''')
        conn.commit()

init_db()

@cached(ttl=SPAM_TIMEFRAME, cache=SimpleMemoryCache)
async def check_spam(user_id: int):
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT spam_count, last_message_time, blacklisted
            FROM users
            WHERE user_id = ?
        ''', (user_id,))
        result = cursor.fetchone()
        if result:
            spam_count, last_message_time, blacklisted = result
            return spam_count, last_message_time, bool(blacklisted)
        return 0, 0, False

@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer("Привет! Отправь мне сообщение, и я передам его в поддержку.")

@dp.message(lambda message: message.chat.type == ChatType.PRIVATE)
async def forward_to_support(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    current_time = time.time()

    spam_count, last_message_time, blacklisted = await check_spam(user_id)
    if blacklisted:
        await message.answer("Вы заблокированы за спам. Попробуйте позже.")
        return

    if current_time - last_message_time > SPAM_TIMEFRAME:
        spam_count = 0

    spam_count += 1

    if spam_count > SPAM_LIMIT:
        with sqlite3.connect(DATABASE_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users
                SET blacklisted = 1
                WHERE user_id = ?
            ''', (user_id,))
            conn.commit()
        await message.answer("Вы временно заблокированы за спам. Подождите несколько минут.")
        return

    if message.text == (await get_last_message(user_id)):
        await message.answer("Не надо дублировать одно и то же сообщение.")
        return

    if len(message.text) > MAX_MESSAGE_LENGTH:
        await message.answer("Ваше сообщение слишком длинное. Сократите его.")
        return

    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, username, spam_count, last_message_time, last_message_text)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, spam_count, current_time, message.text))
        conn.commit()

    if username:
        user_info = f"@{username} (ID: {user_id})"
    else:
        user_info = f"Пользователь {user_id}"

    forwarded_message = await bot.send_message(
        SUPPORT_CHAT_ID,
        f"От {user_info}:\n{message.text}"
    )

    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO messages (message_id, user_id, support_message_id)
            VALUES (?, ?, ?)
        ''', (message.message_id, user_id, forwarded_message.message_id))
        conn.commit()

async def get_last_message(user_id: int):
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT last_message_text
            FROM users
            WHERE user_id = ?
        ''', (user_id,))
        result = cursor.fetchone()
        return result[0] if result else None

@dp.message(lambda message: message.chat.id == SUPPORT_CHAT_ID and message.reply_to_message)
async def reply_from_support(message: Message):
    reply_to_msg = message.reply_to_message
    with sqlite3.connect(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT user_id
            FROM messages
            WHERE support_message_id = ?
        ''', (reply_to_msg.message_id,))
        result = cursor.fetchone()
        if result:
            user_id = result[0]
            await bot.send_message(user_id, f"Ответ от поддержки:\n{message.text}")

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
