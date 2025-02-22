# bot.py

import random
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.command import Command
import psycopg2

# Импорт настроек из config.py
from config import API_TOKEN, ADMIN_ID, DB_CONFIG

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Глобальная переменная для подключения к базе данных
conn = None

# Функция для инициализации базы данных
def initialize_db():
    global conn
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # Создание таблиц
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS global_words (
            id SERIAL PRIMARY KEY,
            word TEXT NOT NULL,
            translation TEXT NOT NULL
        )
        ''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_words (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            word TEXT NOT NULL,
            translation TEXT NOT NULL
        )
        ''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_stats (
            user_id BIGINT PRIMARY KEY,
            correct_answers INTEGER DEFAULT 0,
            wrong_answers INTEGER DEFAULT 0
        )
        ''')

        # Заполнение базовых слов
        cursor.execute('SELECT COUNT(*) FROM global_words')
        count = cursor.fetchone()[0]
        if count == 0:
            default_words = [
                ('red', 'красный'),
                ('green', 'зелёный'),
                ('blue', 'синий'),
                ('yellow', 'жёлтый'),
                ('he', 'он'),
                ('she', 'она'),
                ('it', 'оно'),
                ('we', 'мы'),
                ('you', 'вы'),
                ('they', 'они')
            ]
            cursor.executemany('INSERT INTO global_words (word, translation) VALUES (%s, %s)', default_words)

        conn.commit()
        cursor.close()
    except Exception as e:
        logger.error(f"Ошибка при инициализации базы данных: {e}")
        raise

# Переменная для хранения состояния пользователей
state = {}

# Проверка прав администратора
def is_admin(user_id):
    return user_id == ADMIN_ID

# Генерация инлайн-клавиатуры с вариантами ответов и кнопкой "Закончить викторину"
def get_answer_keyboard(translations):
    answer_buttons = [
        InlineKeyboardButton(text=translation, callback_data=f"answer_{translation}")
        for translation in translations
    ]
    stop_button = [InlineKeyboardButton(text="⏹ Закончить викторину", callback_data="stop_quiz")]
    markup = InlineKeyboardMarkup(inline_keyboard=[answer_buttons, stop_button])
    return markup

# Команда "quiz" — начало викторины
@dp.message(Command("quiz"))
async def quiz_word(message: types.Message):
    user_id = message.from_user.id
    await ask_question(message, user_id)

# Оптимизированная функция для задания нового вопроса
async def ask_question(message: types.Message, user_id: int):
    cursor = conn.cursor()
    try:
        # Выбираем случайное слово из глобальных и пользовательских слов
        cursor.execute('''
        SELECT word, translation FROM (
            SELECT word, translation FROM global_words
            UNION ALL
            SELECT word, translation FROM user_words WHERE user_id = %s
        ) AS all_words
        ORDER BY RANDOM() LIMIT 1
        ''', (user_id,))
        result = cursor.fetchone()

        if not result:
            await message.answer('У вас пока нет слов для изучения. Добавьте свои с помощью команды /add_word.')
            return

        quiz_word, correct_translation = result

        # Выбираем случайные переводы для вариантов ответов
        cursor.execute('''
        SELECT translation FROM (
            SELECT translation FROM global_words
            UNION ALL
            SELECT translation FROM user_words WHERE user_id = %s
        ) AS all_translations
        WHERE translation != %s
        ORDER BY RANDOM() LIMIT 3
        ''', (user_id, correct_translation))
        fake_translations = [row[0] for row in cursor.fetchall()]

        if len(fake_translations) < 3:
            await message.answer('Недостаточно слов для викторины. Добавьте больше слов с помощью команды /add_word.')
            return

        # Формируем варианты ответов
        translations = [correct_translation] + fake_translations
        random.shuffle(translations)

        # Сохраняем правильный перевод в состоянии пользователя
        state[user_id] = correct_translation

        # Отправляем вопрос с инлайн-кнопками
        await message.answer(
            f'Выберите правильный перевод слова: {quiz_word}',
            reply_markup=get_answer_keyboard(translations)
        )
    finally:
        cursor.close()

# Обработчик выбора ответа
@dp.callback_query(lambda query: query.data.startswith("answer_") or query.data == "stop_quiz")
async def check_answer(query: types.CallbackQuery):
    user_id = query.from_user.id

    if query.data == "stop_quiz":
        await query.message.answer('Викторина завершена. Спасибо за участие!')
        state.pop(user_id, None)
        return

    selected_translation = query.data.split("_")[1]
    correct_translation = state.get(user_id)
    if correct_translation is None:
        await query.message.answer('Используйте команду /quiz, чтобы начать викторину.')
        return

    cursor = conn.cursor()
    try:
        if selected_translation.lower() == correct_translation.lower():
            cursor.execute('''
            INSERT INTO user_stats (user_id, correct_answers, wrong_answers)
            VALUES (%s, 1, 0)
            ON CONFLICT (user_id) DO UPDATE SET correct_answers = user_stats.correct_answers + 1
            ''', (user_id,))
            conn.commit()
            await query.message.answer('Правильно! 🎉')
        else:
            cursor.execute('''
            INSERT INTO user_stats (user_id, correct_answers, wrong_answers)
            VALUES (%s, 0, 1)
            ON CONFLICT (user_id) DO UPDATE SET wrong_answers = user_stats.wrong_answers + 1
            ''', (user_id,))
            conn.commit()
            await query.message.answer('Неправильно. Попробуйте ещё раз.')

        await ask_question(query.message, user_id)
    finally:
        cursor.close()

# Основная точка запуска бота
async def main():
    print("Бот запущен...")
    initialize_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())