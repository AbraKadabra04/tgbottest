import random
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.command import Command
import psycopg2

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен бота
API_TOKEN = 'YOU TOKEN'

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Настройки подключения к PostgreSQL
DB_CONFIG = {
    "dbname": "name",  # Замените на имя вашей базы данных
    "user": "user",  # Замените на имя пользователя PostgreSQL
    "password": "password",  # Замените на ваш пароль
    "host": "localhost",  # Хост базы данных
    "port": "5432"  # Порт PostgreSQL
}

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

# ID администратора (замените на ваш ID)
ADMIN_ID = 123456789

def is_admin(user_id):
    return user_id == ADMIN_ID

# Генерация клавиатуры с основным меню
def get_main_menu_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Старт квиз")],
            [KeyboardButton(text="Добавить слово")],
            [KeyboardButton(text="Удалить слово")],
            [KeyboardButton(text="Помощь")]
        ],
        resize_keyboard=True
    )
    return keyboard

# Приветственное сообщение
@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    await message.answer(
        'Привет! Я бот, который поможет тебе учить слова. Вот что я умею:\n'
        '/quiz - учить слова\n'
        '/add_word - добавить слово\n'
        '/delete_word - удалить слово\n'
        '/list_words - список ваших слов\n'
        '/stats - статистика ответов\n'
        '/help - помощь',
        reply_markup=get_main_menu_keyboard()
    )

# Команда помощи
@dp.message(Command("help"))
async def send_help(message: types.Message):
    await message.answer(
        'Команды:\n'
        '/quiz - учить слова\n'
        '/add_word - добавлять свои слова\n'
        '/delete_word - удалять свои слова\n'
        '/list_words - список ваших слов\n'
        '/stats - статистика ответов\n',
        reply_markup=get_main_menu_keyboard()
    )

# Обработчик текстовых команд из меню
@dp.message(lambda message: message.text in ["Старт квиз", "Добавить слово", "Удалить слово", "Помощь"])
async def handle_menu_commands(message: types.Message):
    if message.text == "Старт квиз":
        await quiz_word(message)
    elif message.text == "Добавить слово":
        await add_word(message)
    elif message.text == "Удалить слово":
        await delete_word(message)
    elif message.text == "Помощь":
        await send_help(message)

# Команда "quiz" — начало викторины
@dp.message(Command("quiz"))
async def quiz_word(message: types.Message):
    user_id = message.from_user.id
    await ask_question(message, user_id)

# Функция для задания нового вопроса
async def ask_question(message: types.Message, user_id: int):
    cursor = conn.cursor()
    try:
        # Загружаем доступные слова (общие + пользовательские)
        cursor.execute('SELECT word, translation FROM global_words')
        global_words = cursor.fetchall()
        cursor.execute('SELECT word, translation FROM user_words WHERE user_id = %s', (user_id,))
        user_words = cursor.fetchall()
        words = global_words + user_words
        if not words:
            await message.answer('У вас пока нет слов для изучения. Добавьте свои с помощью команды /add_word.')
            return
        # Выбираем случайное слово
        quiz_word, correct_translation = random.choice(words)
        # Создаём варианты перевода (1 правильный + 3 случайных)
        translations = [correct_translation]
        words_pool = [word[1] for word in words if word[1] != correct_translation]
        if len(words_pool) < 3:
            await message.answer('Недостаточно слов для викторины. Добавьте больше слов с помощью команды /add_word.')
            return
        fake_translations = random.sample(words_pool, 3)
        translations.extend(fake_translations)
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

# Генерация инлайн-клавиатуры с вариантами ответов и кнопкой "Закончить викторину"
def get_answer_keyboard(translations):
    answer_buttons = [
        InlineKeyboardButton(text=translation, callback_data=f"answer_{translation}")
        for translation in translations
    ]
    stop_button = [InlineKeyboardButton(text="⏹ Закончить викторину", callback_data="stop_quiz")]
    markup = InlineKeyboardMarkup(inline_keyboard=[answer_buttons, stop_button])
    return markup

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

# Команда для добавления нового слова
@dp.message(Command("add_word"))
async def add_word(message: types.Message):
    try:
        text = message.text.strip()
        if ':' not in text:
            await message.answer('Введите слово на английском и его перевод через двоеточие. Например:\ncat:кот')
            return

        word, translation = text.split(':', 1)
        word = word.strip().lower()
        translation = translation.strip().lower()

        if not word or not translation:
            raise ValueError("Слово или перевод пустые.")

        user_id = message.from_user.id

        cursor = conn.cursor()
        try:
            cursor.execute('''
            INSERT INTO user_words (user_id, word, translation)
            VALUES (%s, %s, %s)
            ''', (user_id, word, translation))
            conn.commit()
            await message.answer(f'Слово "{word}" с переводом "{translation}" успешно добавлено!')
        finally:
            cursor.close()
    except ValueError as ve:
        await message.answer(f'Ошибка: {ve}')
    except Exception as e:
        logger.error(f"Ошибка при добавлении слова: {e}")
        await message.answer(f'Произошла ошибка: {e}')

# Команда для просмотра списка слов пользователя
@dp.message(Command("list_words"))
async def list_user_words(message: types.Message):
    user_id = message.from_user.id
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT word, translation FROM user_words WHERE user_id = %s', (user_id,))
        words = cursor.fetchall()
        if not words:
            await message.answer('У вас пока нет добавленных слов.')
            return
        word_list = "\n".join([f"{word} - {translation}" for word, translation in words])
        await message.answer(f'Ваши слова:\n{word_list}')
    finally:
        cursor.close()

# Команда для просмотра статистики
@dp.message(Command("stats"))
async def show_stats(message: types.Message):
    user_id = message.from_user.id
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT correct_answers, wrong_answers FROM user_stats WHERE user_id = %s', (user_id,))
        stats = cursor.fetchone()
        if not stats:
            await message.answer('У вас пока нет статистики.')
            return
        correct, wrong = stats
        await message.answer(f'Ваша статистика:\nПравильных ответов: {correct}\nНеправильных ответов: {wrong}')
    finally:
        cursor.close()

# Основная точка запуска бота
async def main():
    print("Бот запущен...")
    initialize_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())