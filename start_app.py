import asyncio
from pathlib import Path
import re
import asyncpg
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, User
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.redis import RedisStorage
from global_configs.telegram_configs import BOT_TOKEN, CHAT_ID
from global_configs.database_configs import DBMS_HOST, DBMS_PORT, DBMS_USER, DBMS_PASSWORD, DBMS_DATABASE, REDIS_HOST
from datetime import datetime
import inspect


# Путь к папке для хранения файлов
DOCS_DIR = Path(__file__).parent / "docs"
DOCS_DIR.mkdir(parents=True, exist_ok=True)

# Настройка Redis для FSM
storage = RedisStorage.from_url(REDIS_HOST)

# Настройки Telegram-бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)
chat = CHAT_ID


# Узнаю реальное время и дату
datetime_now_date = datetime.now().strftime(format="%d.%m.%Y")
datetime_now_time = datetime.now().strftime(format="%H:%M:%S")

# Определяем файл логов
log_file = 'log.log'

# Установка логов
logging.basicConfig(
    level=logging.DEBUG,                                    # Уровень логирования
    format='%(asctime)s - %(levelname)s - %(message)s',     # Формат сообщений
    filename=str(log_file),                                 # Имя файла для записи логов
    filemode='w'                                            # Режим записи
)


def sanitize_filename(name: str) -> str:
    return re.sub(r'[^\w\-_. ]', '_', name or "")


# Создание пула подключений к PostgreSQL
async def create_db_pool():
    return await asyncpg.create_pool(
        host=DBMS_HOST,
        port=DBMS_PORT,
        user=DBMS_USER,
        password=DBMS_PASSWORD,
        database=DBMS_DATABASE,
        timeout=3,
        command_timeout=3
    )


# Состояния FSM пользователя
class UserFSM(StatesGroup):
    # Общие состояния -------------------------------------------------------
    telegram_id = State()           # Телеграм ID пользователя
    telegram_username = State()     # Username пользователя

    # Состояния для заявки --------------------------------------------------
    entity_type_id = State()        # ID типа лица
    name_entity_type = State()      # Имя типа лица
    entity_types = State()          # Словарь всех типов лиц {'ID': 'name'}

    client_name = State()           # Имя клиента
    organization_name = State()     # Название организации

    other_information = State()     # Информация/Описание задачи

    feedback_id = State()           # ID способа связи
    name_feedback = State()         # Имя способа связи
    feedbacks = State()             # Словарь всех способов связи {'ID': 'name'}

    phone = State()                 # Телефон
    email = State()                 # Почта

    convenient_time_id = State()    # ID удобного времени
    convenient_time_name = State()  # Имя удобного времени
    convenient_times = State()      # Словарь всех удобных времен {'ID': 'name'}

    category_id = State()           # ID категории
    name_category = State()         # Имя категории
    categories = State()            # Словарь всех категорий {'ID': 'name'}

    subcategory_id = State()        # ID подкатегории
    name_subcategory = State()      # Имя подкатегории
    subcategories = State()         # Словарь всех подкатегорий {'ID': 'name'}

    documents = State()             # Пути к документам, куда вставил бот

    # Состояния для системных пользователей ----------------------------------
    check_status = State()          # Состояние того, что пользователь нашелся

    access_id = State()             # ID доступа
    access_name = State()           # Имя доступа
    access_reading = State()        # Доступ к чтению
    access_record = State()         # Доступ к записи
    access_removal = State()        # Доступ к удалению

    system_user_id = State()        # ID системного пользователя
    full_name = State()             # ФИО
    status = State()                # Статус системного пользователя
    description = State()           # Описание
    system_users = State()          # Все строки из таблицы системных пользователей

    # Состояния для управления заявками -------------------------------------
    application_management_full_info_application = State()  # Полная информация по заявке по ID
    download_file = State()


async def safe_fetch(pool: asyncpg.pool.Pool, query, *args, timeout=3):
    async def _inner():
        async with pool.acquire() as connection:
            return await connection.fetch(query, *args)
    return await asyncio.wait_for(_inner(), timeout=timeout)


async def safe_fetchrow(pool: asyncpg.pool.Pool, query, *args, timeout=3):
    async def _inner():
        async with pool.acquire() as connection:
            return await connection.fetchrow(query, *args)
    return await asyncio.wait_for(_inner(), timeout=timeout)


async def safe_execute(pool: asyncpg.pool.Pool, query, *args, timeout=3):
    async def _inner():
        async with pool.acquire() as connection:
            return await connection.execute(query, *args)
    return await asyncio.wait_for(_inner(), timeout=timeout)


async def get_search_system_users(pool: asyncpg.pool.Pool, telegram_id) -> bool:
    """
    Получить результат поиска пользователя из таблицы 'system_users_telegram_bot.System_users_for_telegram' по условию telegram_id.

    :param pool: Подключение к базе PostgreSQL. Тип: `asyncpg.pool.Pool`.
    :param telegram_id: ID пользователя телеграмма по которому будет выполняться условие поиска в таблице. Тип: `int`.
    :return: Bool значение - `True`: Если пользователь найден, `False`: Если пользователь не найден.
    """
    _search_user = await safe_fetch(pool,
                                    "SELECT telegram_id FROM system_users_telegram_bot.system_users_for_telegram WHERE telegram_id=$1;",
                                    telegram_id)

    logging.info(f"Функция 'get_search_system_users' - (ID пользователя: {telegram_id}) "
                 f"Return: {True if _search_user else False}\n")

    return True if _search_user else False


async def get_all_variables_system_users(pool: asyncpg.pool.Pool, telegram_id: int) -> (str, bool, int, str):
    """
    Получить значения из таблицы 'system_users_telegram_bot.System_users_for_telegram' по условию telegram_id.
    Предполагается что telegram_id введен правильно.

    :param pool: Подключение к базе PostgreSQL. Тип: `asyncpg.pool.Pool`.
    :param telegram_id: ID пользователя телеграмма по которому будет выполняться условие поиска в таблице. Тип: `int`.
    :return: Возвращает кортеж вида (`str`, `bool`, `int`, `str`)
    """
    row = await safe_fetch(pool,
                           "SELECT * FROM system_users_telegram_bot.System_users_for_telegram WHERE telegram_id=$1;",
                           telegram_id)
    _full_name = row[0]['full_name']
    _status = row[0]['status']
    _access_id = row[0]['access_id']
    _description = row[0]['description']
    return _full_name, _status, _access_id, _description


async def get_all_variables_access(pool: asyncpg.pool.Pool, access_id: int) -> (str, bool, bool, bool):
    """
    Получить значения из таблицы 'system_users_telegram_bot.access' по условию access_id.
    Предполагается что access_id введен правильно.

    :param pool: Подключение к базе PostgreSQL. Тип: `asyncpg.pool.Pool`.
    :param access_id: ID доступа по которому будет выполняться условие поиска в таблице. Тип: `int`.
    :return: Возвращает кортеж вида (`str`, `bool`, `bool`, `bool`)
    """
    row = await safe_fetch(pool,
                           f"SELECT * FROM system_users_telegram_bot.access WHERE access_id=$1;",
                           access_id)
    _access_name = row[0]['access_name']
    _access_reading = row[0]['access_reading']
    _access_record = row[0]['access_record']
    _access_removal = row[0]['access_removal']
    return _access_name, _access_reading, _access_record, _access_removal


async def updating_base_properties(state: FSMContext, user: User, pool: asyncpg.pool.Pool) -> None:
    """
    Обновить базовые свойства пользователя.

    Написал отдельную функцию, чтобы по несколько раз не писать одно и тоже.

    :param state: FSM. Тип: `FSMContext`.
    :param user: Объект сообщения Telegram. Тип: `types.User`.
    :param pool: Подключение к базе PostgreSQL. Тип: `asyncpg.pool.Pool`.
    :return: Возвращает `None`
    """
    await state.update_data(telegram_id=user.id, telegram_username=user.username)
    if await get_search_system_users(pool, user.id):
        # Пользователь найден в таблице системных пользователей
        await state.update_data(check_status=True)
        _full_name, _status, _access_id, _description = await get_all_variables_system_users(pool,
                                                                                             user.id)
        _access_name, _access_reading, _access_record, _access_removal = await get_all_variables_access(pool,
                                                                                                        _access_id)
        await state.update_data(full_name=_full_name, status=_status,
                                access_id=_access_id, description=_description,
                                access_name=_access_name, access_reading=_access_reading,
                                access_record=_access_record, access_removal=_access_removal)
    else:
        # Пользователь НЕ найден в таблице системных пользователей
        await state.update_data(check_status=False)


async def get_fsm_key(state: FSMContext, key: str):
    """
    Получить значение одного ключа из FSM context.

    Возвращает значение поля `key` из состояния FSM пользователя или `None`,
    если ключ отсутствует.

    :param state: Текущий FSMContext пользователя.
    :param key: Ключ для извлечения из словаря состояний.
    :return: Значение соответствующего ключа или `None`.
    """
    data = await state.get_data()
    return data.get(key)


# Блок для всех --------------------------------------------------------------------------------------------------------


# Команда /get_my_id - Отображение информации
@dp.message(Command("get_my_id"))
async def cmd_get_my_id(message: types.Message, state: FSMContext):
    await state.clear()
    await updating_base_properties(state=state, user=message.from_user, pool=dp["db_pool"])
    if await get_fsm_key(state, 'check_status') and await get_fsm_key(state, 'status'):
        await message.answer(
            f"Добро пожаловать {await get_fsm_key(state, 'full_name')}! Вы являетесь системным пользователем!\n\n"
            f"Ваши уровни доступа:\n\n"
            f"Уровень: {await get_fsm_key(state, 'access_name')}\n"
            f"Чтение: {await get_fsm_key(state, 'access_reading')}\n"
            f"Запись: {await get_fsm_key(state, 'access_record')}\n"
            f"Удаление: {await get_fsm_key(state, 'access_removal')}\n\n"
            f"ID пользователя: {message.from_user.id}\n"
            f"Пользователь: {message.from_user.full_name} (Username: @{message.from_user.username})"
        )
    else:
        await message.answer(
            f"ID пользователя: {message.from_user.id}\n"
            f"Пользователь: {message.from_user.full_name} (Username: @{message.from_user.username})"
        )
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {message.from_user.id}) "
                 f"(Пользователь: {message.from_user.full_name}) (Username: @{message.from_user.username})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


# Главная команда /start
async def cmd_start(state: FSMContext, user: User, send):
    await state.clear()
    await updating_base_properties(state=state, user=user, pool=dp["db_pool"])
    if await get_fsm_key(state, 'check_status') and await get_fsm_key(state, 'status'):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Статус заявок", callback_data="Статус заявок"),
                InlineKeyboardButton(text="Тест создания заявок", callback_data="Создать заявку")
            ],
            [
                InlineKeyboardButton(text="Управление заявками", callback_data="Управление заявками")
            ]
        ])
        await send(
            f"🤖 Доброго времени суток, {await get_fsm_key(state, "full_name")}!\n\n"
            "Выберите действие:\n\n",
            reply_markup=keyboard
        )
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Статус заявок", callback_data="Статус заявок"),
                InlineKeyboardButton(text="Создать заявку", callback_data="Создать заявку")
            ]
        ])
        await send(
            "🤖 Доброго времени суток!\n\n"
            "Я — ваш помощник в создании технического задания для ИТ-проектов. "
            "Я помогу собрать все необходимые данные шаг за шагом.\n\n",
            reply_markup=keyboard
        )
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {user.id}) "
                 f"(Пользователь: {user.full_name}) (Username: @{user.username})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


@dp.message(Command("start"))
async def cmd_start_message(message: Message, state: FSMContext):
    await cmd_start(state, message.from_user, message.answer)


# Ответ на любые сообщения (Когда FSM состояние: None)
@dp.message(StateFilter(None))
async def other_message(message: Message, state: FSMContext):
    await state.clear()
    await updating_base_properties(state=state, user=message.from_user, pool=dp["db_pool"])
    if await get_fsm_key(state, 'check_status') and await get_fsm_key(state, 'status'):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Статус заявок", callback_data="Статус заявок"),
                InlineKeyboardButton(text="Тест создания заявок", callback_data="Создать заявку")
            ],
            [
                InlineKeyboardButton(text="Управление заявками", callback_data="Управление заявками")
            ]
        ])
        await message.answer(
            f"🤖 Доброго времени суток, {await get_fsm_key(state, "full_name")}!\n\n"
            "Выберите действие:\n\n",
            reply_markup=keyboard
        )
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Статус заявок", callback_data="Статус заявок"),
                InlineKeyboardButton(text="Создать заявку", callback_data="Создать заявку")
            ]
        ])
        await message.answer(
            "🤖 Доброго времени суток!\n\n"
            "Я не спроектирован для обработки простых сообщений.\n"
            "Пожалуйста, выберите один из представленных на выбор кнопок.\n\n",
            reply_markup=keyboard
        )
    await state.set_state(None)
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {message.from_user.id}) "
                 f"(Пользователь: {message.from_user.full_name}) (Username: @{message.from_user.username})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


# Статус заявки
@dp.callback_query(F.data.startswith('Статус заявок'))
async def application_status(callback_query: CallbackQuery, state: FSMContext):
    await state.clear()
    await updating_base_properties(state=state, user=callback_query.from_user, pool=dp["db_pool"])
    if await get_fsm_key(state, 'check_status') and await get_fsm_key(state, 'status'):
        query = """
                SELECT a.application_id, a.organization_name, a.client_name, a.created_at, s.name_status
                FROM applications.applications a JOIN applications.statuses s ON a.status_id = s.status_id
                ORDER BY a.created_at DESC;
                """
        rows = await safe_fetch(dp["db_pool"], query)
        if rows:
            response = "📋 Заявки:\n\n"
            for row in rows:
                response += (
                    f"🆔 Заявка №{row['application_id']}\n"
                    f'🏢 Организация: {row['organization_name']}\n👤 Клиент: {row['client_name']}\n'
                    f"📅 Дата создания: {row['created_at'].strftime('%d.%m.%Y %H:%M')}\n"
                    f"📌 Статус: {row['name_status']}\n\n"
                )
    else:
        query = """
                SELECT a.application_id, a.created_at, s.name_status FROM applications.applications a
                JOIN applications.statuses s ON a.status_id = s.status_id WHERE a.telegram_id = $1
                ORDER BY a.created_at DESC;
                """
        rows = await safe_fetch(dp["db_pool"], query, callback_query.from_user.id)
        if rows:
            response = "📋 Ваши заявки:\n\n"
            for row in rows:
                response += (
                    f"📅 Дата создания: {row['created_at'].strftime('%d.%m.%Y %H:%M')}\n"
                    f"📌 Статус: {row['name_status']}\n\n"
                )
    if not rows:
        await callback_query.message.edit_text("🤖 У вас нет заявок на данный момент.")
        await asyncio.sleep(1)
    else:
        await callback_query.message.edit_text(response, parse_mode="None")
        await asyncio.sleep(1)
    if await get_fsm_key(state, 'check_status') and await get_fsm_key(state, 'status'):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Статус заявок", callback_data="Статус заявок"),
                InlineKeyboardButton(text="Тест создания заявок", callback_data="Создать заявку")
            ],
            [
                InlineKeyboardButton(text="Управление заявками", callback_data="Управление заявками")
            ]
        ])
        await callback_query.message.answer(
            f"🤖 Доброго времени суток, {await get_fsm_key(state, "full_name")}!\n\n"
            "Выберите действие:\n\n",
            reply_markup=keyboard
        )
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Статус заявок", callback_data="Статус заявок"),
                InlineKeyboardButton(text="Создать заявку", callback_data="Создать заявку")
            ]
        ])
        await callback_query.message.answer(
            "🤖 Доброго времени суток!\n\n"
            "Я — ваш помощник в создании технического задания для ИТ-проектов. "
            "Я помогу собрать все необходимые данные шаг за шагом.\n\n",
            reply_markup=keyboard
        )
    await state.set_state(None)
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {callback_query.from_user.id}) "
                 f"(Пользователь: {callback_query.from_user.full_name}) (Username: @{callback_query.from_user.username})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


# Создать заявку - Начало
@dp.callback_query(F.data.startswith('Создать заявку'))
async def application_start(callback_query: CallbackQuery, state: FSMContext):
    await state.clear()
    await updating_base_properties(state=state, user=callback_query.from_user, pool=dp["db_pool"])
    query = "SELECT entity_type_id, name_entity_type FROM applications.entity_types;"
    rows = await safe_fetch(dp["db_pool"], query)
    entity_types = {row["entity_type_id"]: row["name_entity_type"] for row in rows}
    buttons = [[InlineKeyboardButton(text=name_entity_type, callback_data=str(entity_type_id))]
               for entity_type_id, name_entity_type in entity_types.items()]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await state.update_data(entity_types=entity_types)
    await callback_query.message.answer(
        "Вы обращаетесь как физическое лицо или юридическое?",
        reply_markup=keyboard
    )
    await state.set_state(UserFSM.entity_type_id)
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {callback_query.from_user.id}) "
                 f"(Пользователь: {callback_query.from_user.full_name}) (Username: @{callback_query.from_user.username})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


# Создать заявку - После выбора типа лица
@dp.callback_query(StateFilter(UserFSM.entity_type_id))
async def handle_entity_type(callback_query: CallbackQuery, state: FSMContext):
    await updating_base_properties(state=state, user=callback_query.from_user, pool=dp["db_pool"])
    entity_types = await get_fsm_key(state, 'entity_types')
    await state.update_data(entity_type_id=int(callback_query.data), name_entity_type=entity_types.get(callback_query.data))
    match await get_fsm_key(state, 'name_entity_type'):
        case 'Юридическое лицо':
            query = "SELECT category_id, name_category FROM applications.categories;"
            rows = await safe_fetch(dp["db_pool"], query)
            categories = {row["category_id"]: row["name_category"] for row in rows}
            buttons = [[InlineKeyboardButton(text=name_category, callback_data=str(category_id))]
                       for category_id, name_category in categories.items()]
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            await state.update_data(categories=categories)
            await callback_query.message.edit_text(
                "🤖 Пожалуйста, выберите категорию:",
                reply_markup=keyboard
            )
            await state.set_state(UserFSM.category_id)
        case 'Физическое лицо':
            await callback_query.message.edit_text("🤖 Пожалуйста, напишите, как к вам обращаться:")
            await state.set_state(UserFSM.client_name)
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {callback_query.from_user.id}) "
                 f"(Пользователь: {callback_query.from_user.full_name}) (Username: @{callback_query.from_user.username})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


# Создать заявку - Выбор категории. Условие: Юридическое лицо
@dp.callback_query(StateFilter(UserFSM.category_id))
async def handle_category(callback_query: CallbackQuery, state: FSMContext):
    await updating_base_properties(state=state, user=callback_query.from_user, pool=dp["db_pool"])
    categories = await get_fsm_key(state, 'categories')
    await state.update_data(category_id=int(callback_query.data), name_category=categories.get(callback_query.data))
    query = "SELECT subcategory_id, name_subcategory FROM applications.subcategories WHERE category_id = $1;"
    rows = await safe_fetch(dp["db_pool"], query, int(callback_query.data))
    subcategories = {row["subcategory_id"]: row["name_subcategory"] for row in rows}
    buttons = [[InlineKeyboardButton(text=name_subcategory, callback_data=str(subcategory_id))]
               for subcategory_id, name_subcategory in subcategories.items()]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await state.update_data(subcategories=subcategories)
    await callback_query.message.edit_text(
        "🤖 Пожалуйста, выберите подкатегорию:",
        reply_markup=keyboard
    )
    await state.set_state(UserFSM.subcategory_id)
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {callback_query.from_user.id}) "
                 f"(Пользователь: {callback_query.from_user.full_name}) (Username: @{callback_query.from_user.username})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


# Создать заявку - Выбор подкатегории. Условие: Юридическое лицо
@dp.callback_query(StateFilter(UserFSM.subcategory_id))
async def handle_subcategory(callback_query: CallbackQuery, state: FSMContext):
    await updating_base_properties(state=state, user=callback_query.from_user, pool=dp["db_pool"])
    subcategories = await get_fsm_key(state, 'subcategories')
    await state.update_data(subcategory_id=int(callback_query.data), name_subcategory=subcategories.get(callback_query.data))
    await callback_query.message.edit_text("🤖 Пожалуйста, напишите, как к вам обращаться:")
    await state.set_state(UserFSM.client_name)
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {callback_query.from_user.id}) "
                 f"(Пользователь: {callback_query.from_user.full_name}) (Username: @{callback_query.from_user.username})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


# Создать заявку - Ввод имени и запрос имени организации (Условие: Юридическое лицо)
@dp.message(F.text, StateFilter(UserFSM.client_name))
async def handle_name(message: Message, state: FSMContext):
    await updating_base_properties(state=state, user=message.from_user, pool=dp["db_pool"])
    await state.update_data(client_name=message.text)
    if await get_fsm_key(state, "name_entity_type") == "Юридическое лицо":
        await message.answer("🤖 Пожалуйста, напишите, как называется ваша организация:")
        await state.set_state(UserFSM.organization_name)
    elif await get_fsm_key(state, "name_entity_type") == "Физическое лицо":
        await message.answer(
            "🤖 Пожалуйста, опишите вашу задачу или проблему. Вы можете также добавить "
            "любую дополнительную информацию. Напишите всё, что считаете важным.\n\n"
            "Если вы хотите завершить ввод, отправьте сообщение \"Далее\"."
        )
        await state.set_state(UserFSM.other_information)
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {message.from_user.id}) "
                 f"(Пользователь: {message.from_user.full_name}) (Username: @{message.from_user.username})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


# Создать заявку - Ввод название организации и запрос у пользователя дополнительной информации
@dp.message(F.text, StateFilter(UserFSM.organization_name))
async def handle_organization(message: Message, state: FSMContext):
    await updating_base_properties(state=state, user=message.from_user, pool=dp["db_pool"])
    await state.update_data(organization_name=message.text)
    await message.answer(
        "🤖 Пожалуйста, опишите вашу задачу или проблему. Вы можете также добавить "
        "любую дополнительную информацию. Напишите всё, что считаете важным.\n\n"
        "Если вы хотите завершить ввод, отправьте сообщение \"Далее\"."
    )
    await state.set_state(UserFSM.other_information)
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {message.from_user.id}) "
                 f"(Пользователь: {message.from_user.full_name}) (Username: @{message.from_user.username})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


# Создать заявку - Получаем дополнительную информацию
@dp.message(F.text, StateFilter(UserFSM.other_information))
async def message_other_information(message: Message, state: FSMContext):
    await updating_base_properties(state=state, user=message.from_user, pool=dp["db_pool"])
    if message.text.lower() == 'далее':
        await message.answer(
            "🤖 Спасибо за предоставленную информацию!\n "
            "Можете отправить документы (файлы, сканы или инструкции), если они есть. "
            "Это поможет нам быстрее и точнее обработать вашу заявку.\n\n"
            "Важно! Документ не должен превышать 20 МБ!"
        )
        await state.set_state(UserFSM.documents)
    else:
        new_text = message.text
        old_text = await get_fsm_key(state, "other_information") or ""
        await state.update_data(other_information=f"{old_text}\n{new_text}".strip())
        await message.answer("🤖 Информация добавлена. Если хотите завершить, отправьте сообщение \"Далее\".")
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {message.from_user.id}) "
                 f"(Пользователь: {message.from_user.full_name}) (Username: @{message.from_user.username})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


# Создать заявку - Перестать отправлять документы
@dp.message(F.text, StateFilter(UserFSM.documents))
async def handle_document_text(message: types.Message, state: FSMContext):
    await updating_base_properties(state=state, user=message.from_user, pool=dp["db_pool"])
    if message.text.lower() == 'далее':
        query = "SELECT feedback_id, name_feedback FROM applications.feedback;"
        rows = await safe_fetch(dp["db_pool"], query)
        feedbacks = {row["feedback_id"]: row["name_feedback"] for row in rows}
        buttons = [[InlineKeyboardButton(text=name_feedback, callback_data=str(feedback_id))]
                   for feedback_id, name_feedback in feedbacks.items()]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await state.update_data(feedbacks=feedbacks)
        await message.answer(
            "🤖 Спасибо за предоставленную информацию!\n "
            "Как с вами связаться?",
            reply_markup=keyboard
        )
        await state.set_state(UserFSM.feedback_id)
    else:
        await message.answer('🤖 Если вы закончили, отправьте сообщение "Далее"')
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {message.from_user.id}) "
                 f"(Пользователь: {message.from_user.full_name}) (Username: @{message.from_user.username})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


# Создать заявку - Получаем документы
@dp.message(F.document, StateFilter(UserFSM.documents))
async def handle_document(message: types.Message, state: FSMContext):
    await updating_base_properties(state=state, user=message.from_user, pool=dp["db_pool"])
    document = message.document
    file_info = await bot.get_file(document.file_id)
    user_id = str(message.from_user.id)
    client_name = sanitize_filename(await get_fsm_key(state, "client_name"))
    org_name = sanitize_filename(await get_fsm_key(state, "organization_name"))
    entity_type = await get_fsm_key(state, "name_entity_type")
    datetime_folder = f"{datetime.now().strftime(format="%d.%m.%Y")}__{datetime.now().strftime(format="%H-%M-%S")}"
    if entity_type == "Юридическое лицо" and org_name:
        save_dir = DOCS_DIR / "Юридическое лицо" / org_name / client_name / datetime_folder
    else:
        save_dir = DOCS_DIR / "Физическое лицо" / client_name / datetime_folder
    save_dir.mkdir(parents=True, exist_ok=True)
    file_path = save_dir / f"{user_id}_{document.file_name}"
    await bot.download_file(file_info.file_path, destination=file_path)
    await message.answer(
        f'✅ Файл {document.file_name} успешно сохранён! Если вы закончили, отправьте сообщение "Далее"')
    docs = await get_fsm_key(state, "documents") or []
    docs.append(str(file_path))
    await state.update_data(documents=docs)
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {message.from_user.id}) "
                 f"(Пользователь: {message.from_user.full_name}) (Username: @{message.from_user.username})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


# Создать заявку - Выбор способа связи
@dp.callback_query(StateFilter(UserFSM.feedback_id))
async def handle_feedback(callback_query: CallbackQuery, state: FSMContext):
    await updating_base_properties(state=state, user=callback_query.from_user, pool=dp["db_pool"])
    feedbacks = await get_fsm_key(state, 'feedbacks')
    await state.update_data(feedback_id=int(callback_query.data), name_feedback=feedbacks.get(callback_query.data))
    await callback_query.message.edit_text("🤖 Напишите ваш контактный номер телефона.")
    await state.set_state(UserFSM.phone)
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {callback_query.from_user.id}) "
                 f"(Пользователь: {callback_query.from_user.full_name}) (Username: @{callback_query.from_user.username})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


# Создать заявку - Ввод номера телефона
@dp.message(F.text, StateFilter(UserFSM.phone))
async def handle_phone(message: Message, state: FSMContext):
    await updating_base_properties(state=state, user=message.from_user, pool=dp["db_pool"])
    await state.update_data(phone=message.text)
    await message.answer("🤖 Напишите ваш контактный адрес почты.")
    await state.set_state(UserFSM.email)
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {message.from_user.id}) "
                 f"(Пользователь: {message.from_user.full_name}) (Username: @{message.from_user.username})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


# Создать заявку - Ввод адреса почты
@dp.message(F.text, StateFilter(UserFSM.email))
async def handle_email(message: Message, state: FSMContext):
    await updating_base_properties(state=state, user=message.from_user, pool=dp["db_pool"])
    await state.update_data(email=message.text)
    query = "SELECT convenient_time_id, convenient_time_name FROM applications.convenient_time;"
    rows = await safe_fetch(dp["db_pool"], query)
    convenient_times = {row["convenient_time_id"]: row["convenient_time_name"] for row in rows}
    buttons = [[InlineKeyboardButton(text=convenient_time_name, callback_data=str(convenient_time_id))]
               for convenient_time_id, convenient_time_name in convenient_times.items()]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await state.update_data(convenient_times=convenient_times)
    await message.answer("🤖 Укажите удобное для вас время:", reply_markup=keyboard)
    await state.set_state(UserFSM.convenient_time_id)
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {message.from_user.id}) "
                 f"(Пользователь: {message.from_user.full_name}) (Username: @{message.from_user.username})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


# Создать заявку - Выбор удобного времени
@dp.callback_query(StateFilter(UserFSM.convenient_time_id))
async def handle_convenient_time(callback_query: CallbackQuery, state: FSMContext):
    await updating_base_properties(state=state, user=callback_query.from_user, pool=dp["db_pool"])
    convenient_times = await get_fsm_key(state, 'convenient_times')
    await state.update_data(convenient_time_id=int(callback_query.data), convenient_time_name=convenient_times.get(callback_query.data))
    processing_message = await callback_query.message.edit_text("Обработка заявки...")
    await asyncio.sleep(1)
    match await get_fsm_key(state, 'name_entity_type'):
        case "Физическое лицо":
            application_info = (
                f"📋 НОВАЯ ЗАЯВКА!\n\n"
                f"👤 Имя: {await get_fsm_key(state, 'client_name')} \nID: {await get_fsm_key(state, 'telegram_id')}, Username: @{await get_fsm_key(state, 'telegram_username')})\n\n"
                f"🏢 Тип лица: {await get_fsm_key(state, 'name_entity_type')}\n\n\n"
                f"📝 Описание задачи: \n{await get_fsm_key(state, 'other_information')}\n\n\n"
                f"📞 Способ связи: {await get_fsm_key(state, 'name_feedback')}\n"
                f"📞 Телефон: {await get_fsm_key(state, 'phone')}\n"
                f"📞 Почта: {await get_fsm_key(state, 'email')}\n\n"
                f"⏰ Удобное время:\n{await get_fsm_key(state, 'convenient_time_name')}\n"
            )
            query = ("INSERT INTO applications.applications(telegram_id, client_name, phone, email, other_information, "
                     "entity_type_id, feedback_id, convenient_time_id)\nVALUES($1,$2,$3,$4,$5,$6,$7,$8) "
                     "RETURNING application_id, created_at;")
            row = await safe_fetchrow(dp["db_pool"], query,
                               await get_fsm_key(state, 'telegram_id'),
                               await get_fsm_key(state, 'client_name'),
                               await get_fsm_key(state, 'phone'),
                               await get_fsm_key(state, 'email'),
                               await get_fsm_key(state, 'other_information'),
                               await get_fsm_key(state, 'entity_type_id'),
                               await get_fsm_key(state, 'feedback_id'),
                               await get_fsm_key(state, 'convenient_time_id'),
                               )
            await bot.send_message(CHAT_ID, application_info, parse_mode="None")
        case "Юридическое лицо":
            application_info = (
                f"📋 НОВАЯ ЗАЯВКА!\n\n"
                f"👤 Имя: {await get_fsm_key(state, 'client_name')} \nID: {await get_fsm_key(state, 'telegram_id')}, Username: @{await get_fsm_key(state, 'telegram_username')})\n\n"
                f"🏢 Тип лица: {await get_fsm_key(state, 'name_entity_type')}\n"
                f"🏢 Организация: {await get_fsm_key(state, 'organization_name')}\n\n"
                f"* Категория задачи:\n{await get_fsm_key(state, 'name_category')}\n"
                f"* Подкатегория задачи:\n{await get_fsm_key(state, 'name_subcategory')}\n\n\n"
                f"📝 Описание задачи: \n{await get_fsm_key(state, 'other_information')}\n\n\n"
                f"📞 Способ связи: {await get_fsm_key(state, 'name_feedback')}\n"
                f"📞 Телефон: {await get_fsm_key(state, 'phone')}\n"
                f"📞 Почта: {await get_fsm_key(state, 'email')}\n\n"
                f"⏰ Удобное время:\n{await get_fsm_key(state, 'convenient_time_name')}\n"
            )
            query = ("INSERT INTO applications.applications(telegram_id, client_name, organization_name, phone, email, "
                     "other_information, entity_type_id, feedback_id, convenient_time_id, category_id, subcategory_id)"
                     "\nVALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING application_id, created_at;")
            row = await safe_fetchrow(dp["db_pool"], query,
                                      await get_fsm_key(state, 'telegram_id'),
                                      await get_fsm_key(state, 'client_name'),
                                      await get_fsm_key(state, 'organization_name'),
                                      await get_fsm_key(state, 'phone'),
                                      await get_fsm_key(state, 'email'),
                                      await get_fsm_key(state, 'other_information'),
                                      await get_fsm_key(state, 'entity_type_id'),
                                      await get_fsm_key(state, 'feedback_id'),
                                      await get_fsm_key(state, 'convenient_time_id'),
                                      await get_fsm_key(state, 'category_id'),
                                      await get_fsm_key(state, 'subcategory_id')
                               )
            await bot.send_message(CHAT_ID, application_info, parse_mode="None")
    application_id = row["application_id"]
    uploaded_at = row["created_at"]
    docs = await get_fsm_key(state, "documents") or []
    for file_path in docs:
        query = ("INSERT INTO applications.documents (application_id, file_path, original_name, uploaded_at)"
                 "VALUES ($1,$2,$3,$4)")
        await safe_execute(dp["db_pool"],
                           query,
                           application_id,
                           file_path,
                           Path(file_path).name,
                           uploaded_at)


    await processing_message.edit_text("🤖 Спасибо за предоставленную информацию!"
                                       " Ваша заявка отправлена. Мы свяжемся с вами в ближайшее время.")
    await asyncio.sleep(1)
    await state.set_state(None)
    await cmd_start(state, callback_query.from_user, callback_query.message.answer)
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {callback_query.from_user.id}) "
                 f"(Пользователь: {callback_query.from_user.full_name}) (Username: @{callback_query.from_user.username})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


# Блок для системных пользователей -------------------------------------------------------------------------------------


# Команда /status - Отображение информации о системе
@dp.message(Command("status"))
async def cmd_status(message: types.Message, state: FSMContext):
    await state.clear()
    await updating_base_properties(state=state, user=message.from_user, pool=dp["db_pool"])

    db_status = None
    if await get_fsm_key(state, 'check_status') and await get_fsm_key(state, 'status'):
        db_status = "Подключено"
        try:
            await safe_execute(dp["db_pool"], "SELECT 1;")
        except Exception:
            db_status = "Ошибка"
        await message.answer("Вы являйтесь системным пользователем!")
        await message.answer(
            f"Инициализирована проверка работы Telegram-бота!\n"
            f"Статус: Работает\n"
            f"Бот запущен: {datetime_now_date} {datetime_now_time}\n"
            f"Статус подключения к базе данных: {db_status}"
        )
    else:
        await message.answer('У вас нет доступа к этой функции.')
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {message.from_user.id}) "
                 f"(Пользователь: {message.from_user.full_name}) (Username: @{message.from_user.username}) "
                 f"(Статус: Работает) (Бот запущен: {datetime_now_date} {datetime_now_time}) (Статус подключения к базе данных: {db_status})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


# Управление заявками - Старт
@dp.callback_query(F.data.startswith('Управление заявками'))
async def application_management_start(callback_query: CallbackQuery, state: FSMContext):
    await state.clear()
    await updating_base_properties(state=state, user=callback_query.from_user, pool=dp["db_pool"])
    if await get_fsm_key(state, 'check_status') and await get_fsm_key(state, 'status'):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Список заявок", callback_data="Список заявок")
            ],
            [
                InlineKeyboardButton(text="Вся информация о заявке по ID",
                                     callback_data="Вся информация о заявки по ID")
            ],
            [
                InlineKeyboardButton(text="Вернуться в стартовое меню", callback_data="Вернуться в стартовое меню")
            ]
        ])
        await callback_query.message.answer("🤖 Выберите действие:", reply_markup=keyboard)
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {callback_query.from_user.id}) "
                 f"(Пользователь: {callback_query.from_user.full_name}) (Username: @{callback_query.from_user.username})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


# Управление заявками - Список заявок
@dp.callback_query(F.data.startswith('Список заявок'))
async def application_management_list_applications(callback_query: CallbackQuery, state: FSMContext):
    await state.clear()
    await updating_base_properties(state=state, user=callback_query.from_user, pool=dp["db_pool"])
    if await get_fsm_key(state, 'check_status') and await get_fsm_key(state, 'status'):
        query = ("SELECT a.application_id, a.organization_name, a.client_name, a.created_at, s.name_status "
                 "FROM applications.applications a JOIN applications.statuses s "
                 "ON a.status_id = s.status_id ORDER BY a.created_at DESC;")
        rows = await safe_fetch(dp["db_pool"], query)
        if not rows:
            await callback_query.message.edit_text("🤖 Нет заявок на данный момент.")
            await asyncio.sleep(1)
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="Список заявок", callback_data="Список заявок")
                ],
                [
                    InlineKeyboardButton(text="Вся информация о заявке по ID",
                                         callback_data="Вся информация о заявки по ID")
                ],
                [
                    InlineKeyboardButton(text="Вернуться в стартовое меню", callback_data="Вернуться в стартовое меню")
                ]
            ])
            await callback_query.message.answer(
                "🤖 Выберите действие:",
                reply_markup=keyboard
            )
            return
        response = "📋 Заявки:\n\n"
        for row in rows:
            response += (
                f"🆔 Заявка №{row['application_id']}\n"
                f'🏢 Организация: {row['organization_name']}\n👤 Клиент: {row['client_name']}\n'
                f"📅 Дата создания: {row['created_at'].strftime('%d.%m.%Y %H:%M')}\n"
                f"📌 Статус: {row['name_status']}\n\n"
            )
        await callback_query.message.edit_text(response, parse_mode="None")
        await asyncio.sleep(1)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Список заявок", callback_data="Список заявок")
            ],
            [
                InlineKeyboardButton(text="Вся информация о заявке по ID",
                                     callback_data="Вся информация о заявки по ID")
            ],
            [
                InlineKeyboardButton(text="Вернуться в стартовое меню", callback_data="Вернуться в стартовое меню")
            ]
        ])
        await callback_query.message.answer(
            "🤖 Выберите действие:",
            reply_markup=keyboard
        )
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {callback_query.from_user.id}) "
                 f"(Пользователь: {callback_query.from_user.full_name}) (Username: @{callback_query.from_user.username})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


# Управление заявками - Пользователь выбрал кнопку "Вся информация о заявки по ID"
@dp.callback_query(F.data.startswith('Вся информация о заявки по ID'))
async def application_management_full_info_application_input_id(callback_query: CallbackQuery, state: FSMContext):
    await state.clear()
    await updating_base_properties(state=state, user=callback_query.from_user, pool=dp["db_pool"])
    await callback_query.message.answer("🤖 Введите ID заявки:")
    await state.set_state(UserFSM.application_management_full_info_application)
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {callback_query.from_user.id}) "
                 f"(Пользователь: {callback_query.from_user.full_name}) (Username: @{callback_query.from_user.username})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


# Управление заявками - Пользователь выбрал ID заявки, который будет просматривать
@dp.message(F.text, StateFilter(UserFSM.application_management_full_info_application))
async def application_management_full_info_application_search_id(message: Message, state: FSMContext):
    await updating_base_properties(state=state, user=message.from_user, pool=dp["db_pool"])
    try:
        application_id = int(message.text)
        if await get_fsm_key(state, 'check_status') and await get_fsm_key(state, 'status'):
            query = ("SELECT a.application_id, a.telegram_id, a.organization_name, a.client_name, a.phone, a.email, "
                     "c.name_category AS category, sc.name_subcategory AS subcategory, a.other_information, "
                     "s.name_status AS status, a.created_at, et.name_entity_type AS entity_type, "
                     "f.name_feedback AS feedback, ct.convenient_time_name AS convenient_time "
                     "FROM applications.applications a "
                     "LEFT JOIN applications.categories c ON a.category_id = c.category_id "
                     "LEFT JOIN applications.subcategories sc ON a.subcategory_id = sc.subcategory_id "
                     "LEFT JOIN applications.statuses s  ON a.status_id = s.status_id "
                     "LEFT JOIN applications.entity_types et ON a.entity_type_id = et.entity_type_id "
                     "LEFT JOIN applications.feedback f  ON a.feedback_id = f.feedback_id "
                     "LEFT JOIN applications.convenient_time ct ON a.convenient_time_id = ct.convenient_time_id "
                     "WHERE a.application_id = $1;")
            row = await safe_fetchrow(dp["db_pool"], query, application_id)
            if not row:
                await message.answer("❌ Такой заявки нет.")
                await asyncio.sleep(1)
                await state.clear()
                await updating_base_properties(state=state, user=message.from_user, pool=dp["db_pool"])
                if await get_fsm_key(state, 'check_status') and await get_fsm_key(state, 'status'):
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [
                            InlineKeyboardButton(text="Список заявок", callback_data="Список заявок")
                        ],
                        [
                            InlineKeyboardButton(text="Вся информация о заявке по ID",
                                                 callback_data="Вся информация о заявки по ID")
                        ],
                        [
                            InlineKeyboardButton(text="Вернуться в стартовое меню",
                                                 callback_data="Вернуться в стартовое меню")
                        ]
                    ])
                    await message.answer("🤖 Выберите действие:", reply_markup=keyboard)
            full_info = (f"ID: {row['application_id']}\n\n"
                          f"Имя клиента: {row['client_name']}\n"
                          f"Тип лица: {row['entity_type']}\n"
                          f"Организация: {row['organization_name']}\n\n"
                          f"Номер телефона: {row['phone']}\n"
                          f"Почтовый адрес: {row['email']}\n\n"
                          f"Категория: {row['category']}\n"
                          f"Подкатегория: {row['subcategory']}\n\n"
                          f"Информация:\n{row['other_information']}\n\n"
                          f"Статус: {row['status']}\n\n"
                          f"Дата создания заявки: {row['created_at']}\n\n"
                          f"Предпочтительный способ связи: {row['feedback']}\n"
                          f"Предпочтительное время для связи: {row['convenient_time']}\n\n"
                          f"Telegram ID: {row['telegram_id']}\n")

            documents = await safe_fetch(dp["db_pool"],"SELECT document_id, application_id, file_path, "
                                                       "original_name, uploaded_at FROM applications.documents "
                                                       "WHERE application_id = $1 ORDER BY uploaded_at ASC;", application_id)
            if not documents:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Вернуться в стартовое меню",
                                             callback_data="Вернуться в стартовое меню")
                    ]
                ])
                await message.answer(full_info, reply_markup=keyboard)
            else:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Скачать документы", callback_data=str(application_id))
                    ],
                    [
                        InlineKeyboardButton(text="Вернуться в стартовое меню", callback_data="Вернуться в стартовое меню")
                    ]
                ])
                await message.answer(full_info, reply_markup=keyboard)
                await state.set_state(UserFSM.download_file)
    except ValueError:
        await message.answer("🤖 Введите ID заявки:")
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {message.from_user.id}) "
                 f"(Пользователь: {message.from_user.full_name}) (Username: @{message.from_user.username})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


# Управление заявками - Скачать документы
@dp.callback_query(StateFilter(UserFSM.download_file))
async def download_documents(callback_query: CallbackQuery, state: FSMContext):
    await updating_base_properties(state=state, user=callback_query.from_user, pool=dp["db_pool"])
    query = ("SELECT file_path, original_name "
             "FROM applications.documents "
             "WHERE application_id = $1 "
             "ORDER BY uploaded_at ASC;")
    documents = await safe_fetch(dp["db_pool"], query, int(callback_query.data))
    if not documents:
        await callback_query.message.answer("❌ Для этой заявки нет документов.")
        await state.clear()
        return
    for doc in documents:
        try:
            file = FSInputFile(doc["file_path"], filename=doc["original_name"])
            await bot.send_document(
                chat_id=callback_query.from_user.id,
                document=file,
                caption=f"📄 {doc['original_name']}"
            )
        except Exception as e:
            await callback_query.message.answer(
                f"⚠ Не удалось отправить файл {doc['original_name']}: {e}"
            )
    await state.clear()
    logging.info(f"Функция '{inspect.currentframe().f_code.co_name}' - (ID пользователя: {callback_query.from_user.id}) "
                 f"(Пользователь: {callback_query.from_user.full_name}) (Username: @{callback_query.from_user.username})\n"
                 f"Data: {await state.get_data()}\n"
                 f"Текущее состояние: {await state.get_state()}")


# Общий блок -----------------------------------------------------------------------------------------------------------
@dp.callback_query(F.data.startswith("Вернуться в стартовое меню"))
async def cmd_start_callback(callback: CallbackQuery, state: FSMContext):
    await cmd_start(state, callback.from_user, callback.message.answer)


# Запуск бота
async def main():
    logging.info('Запуск системы')
    db_pool = await create_db_pool()
    dp["db_pool"] = db_pool
    try:
        await dp.start_polling(bot)
    finally:
        await db_pool.close()


if __name__ == "__main__":
    asyncio.run(main())
