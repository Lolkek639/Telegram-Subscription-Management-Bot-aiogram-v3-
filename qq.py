import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ChatJoinRequest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ================= НАСТРОЙКИ =================
BOT_TOKEN = "8832524372:AAFxdFUyPwkUVrepYgMJipaMOkSAJuZCiBQ"
GROUP_ID = -1003769853391          # ID твоего канала/группы (обязательно с -100)
ADMIN_ID = 8554888993               # Твой личный Telegram ID
ADMIN_USERNAME = "KavkazMedia13"    # Юзернейм админа для связи (без @)

# Ссылка, которую бот будет выдавать после одобрения оплаты
CHANNEL_LINK = "https://t.me/+wXf7pZAAeoRkOWZi"

# Реквизиты для вывода пользователю
REQUISITES_RU = "Сбербанк: 2202 2067 0714 8842 (Sofia.P.)"
REQUISITES_KZ = "Freedom Bank: 5269 8800 5086 5294 (Magamed.)"

# Тариф 1: 5 месяцев
PRICE_5M_RUB = 450
PRICE_5M_KZT = 3500
DAYS_5M = 150

# Тариф 2: Навсегда
PRICE_FOREVER_RUB = 2000
PRICE_FOREVER_KZT = 15000  # Примерный эквивалент для вечного доступа

# Метка бесконечной подписки в БД
FOREVER_DATE = "2099-12-31 23:59:59"
# =============================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

DB_NAME = "subscribers_v5.db"  # Обновили версию БД, так как логика тарифов изменилась
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

class AdminStates(StatesGroup):
    broadcast_message = State()
    ban_user_id = State()

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, expires_at TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS all_users (
            user_id INTEGER PRIMARY KEY, username TEXT
        )
    ''')
    conn.commit()
    conn.close()

# Фоновый кик истекших пользователей (работает 1 раз в час)
async def check_and_kick_expired_users():
    now_str = datetime.now().strftime(DATE_FORMAT)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username FROM users WHERE expires_at < ? AND expires_at != ?", (now_str, FOREVER_DATE))
    expired = cursor.fetchall()
    
    for user_id, username in expired:
        try:
            await bot.ban_chat_member(chat_id=GROUP_ID, user_id=user_id)
            await bot.unban_chat_member(chat_id=GROUP_ID, user_id=user_id)
            cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            conn.commit()
            await bot.send_message(user_id, "❌ Срок вашей подписки истек. Вы были удалены из канала.\nДля продления доступа используйте меню: /start")
        except Exception as e:
            logging.error(f"Ошибка кика {user_id}: {e}")
    conn.close()

# Фоновое уведомление за 3 дня и за 1 день (работает 1 раз в день)
async def notification_before_expiry():
    now = datetime.now()
    three_days_later = (now + timedelta(days=3)).strftime("%Y-%m-%d")
    one_day_later = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Проверка тех, у кого осталось 3 дня (исключая вечную подписку)
    cursor.execute("SELECT user_id FROM users WHERE expires_at LIKE ? AND expires_at != ?", (f"{three_days_later}%", FOREVER_DATE))
    for (user_id,) in cursor.fetchall():
        try:
            await bot.send_message(user_id, "⚠️ **Внимание!** До окончания вашей подписки осталось **3 дня**.\nВы можете продлить её заранее через меню: /start")
        except Exception:
            pass
            
    # Проверка тех, у кого остался 1 день (исключая вечную подписку)
    cursor.execute("SELECT user_id FROM users WHERE expires_at LIKE ? AND expires_at != ?", (f"{one_day_later}%", FOREVER_DATE))
    for (user_id,) in cursor.fetchall():
        try:
            await bot.send_message(user_id, "🚨 **Важно!** Ваша подписка истекает через **24 часа**.\nУспейте продлить доступ, чтобы бот не удалил вас из канала: /start")
        except Exception:
            pass
            
    conn.close()

# --- АВТО-ОДОБРЕНИЕ ЗАЯВОК НА ВСТУПЛЕНИЕ ---
@dp.chat_join_request()
async def handle_join_request(update: ChatJoinRequest):
    user_id = update.from_user.id
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT expires_at FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    
    if res:
        if res[0] == FOREVER_DATE:
            await update.approve()
            logging.info(f"Заявка пользователя {user_id} одобрена автоматически (Вечная подписка).")
            return
            
        expires_at = datetime.strptime(res[0], DATE_FORMAT)
        if expires_at > datetime.now():
            await update.approve()
            logging.info(f"Заявка пользователя {user_id} одобрена автоматически.")
            return

    await update.decline()
    logging.info(f"Заявка пользователя {user_id} отклонена (нет оплаты).")

# Главное меню
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or "без_юзернейма"
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO all_users (user_id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()
    conn.close()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=" Tarifs / Тарифы ", callback_data="view_tariffs")],
        [InlineKeyboardButton(text="👤 Мой Профиль", callback_data="view_profile")]
    ])
    await message.answer(
        "👋 **Добро пожаловать!**\n\n"
        "🔥 **Кавказ Группа** — приватный архив, где собрано около **70 тысяч видео**.\n\n"
        "Выберите интересующий раздел меню ниже:", reply_markup=kb
    )

# Меню выбора тарифов
@dp.callback_query(F.data == "view_tariffs")
async def process_view_tariffs(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📋 5 месяцев — {PRICE_5M_RUB}₽ / {PRICE_5M_KZT}₸", callback_data="choose_5m")],
        [InlineKeyboardButton(text=f"💎 Навсегда (VIP) — {PRICE_FOREVER_RUB}₽ / {PRICE_FOREVER_KZT}₸", callback_data="choose_forever")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text(
        "выберите тариф для получения доступа к **Кавказ Группе**:",
        reply_markup=kb
    )
    await callback.answer()

# Выбор способа оплаты для 5 месяцев
@dp.callback_query(F.data == "choose_5m")
async def process_choose_5m(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Сбербанк (РФ)", callback_data="pay_sber_5m")],
        [InlineKeyboardButton(text="💳 Freedom Bank (КЗ)", callback_data="pay_freedom_5m")],
        [InlineKeyboardButton(text="⬅️ Назад к тарифам", callback_data="view_tariffs")]
    ])
    await callback.message.edit_text("Вы выбрали доступ на **5 месяцев**.\nВыберите удобный банк для оплаты:", reply_markup=kb)
    await callback.answer()

# Выбор способа оплаты для вечной подписки
@dp.callback_query(F.data == "choose_forever")
async def process_choose_forever(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Сбербанк (РФ)", callback_data="pay_sber_forever")],
        [InlineKeyboardButton(text="💳 Freedom Bank (КЗ)", callback_data="pay_freedom_forever")],
        [InlineKeyboardButton(text="⬅️ Назад к тарифам", callback_data="view_tariffs")]
    ])
    await callback.message.edit_text("Вы выбрали доступ **Навсегда**.\nВыберите удобный банк для оплаты:", reply_markup=kb)
    await callback.answer()

# Экран с реквизитами
@dp.callback_query(F.data.startswith("pay_"))
async def process_payment_screen(callback: types.CallbackQuery):
    data = callback.data
    
    if "5m" in data:
        duration = "5m"
        if "sber" in data:
            text = f"💵 Сумма к оплате: **{PRICE_5M_RUB} ₽**\n📌 Реквизиты Сбербанк:\n`{REQUISITES_RU}`"
        else:
            text = f"💵 Сумма к оплате: **{PRICE_5M_KZT} ₸**\n📌 Реквизиты Freedom Bank:\n`{REQUISITES_KZ}`"
    else:
        duration = "forever"
        if "sber" in data:
            text = f"💵 Сумма к оплате: **{PRICE_FOREVER_RUB} ₽**\n📌 Реквизиты Сбербанк:\n`{REQUISITES_RU}`"
        else:
            text = f"💵 Сумма к оплате: **{PRICE_FOREVER_KZT} ₸**\n📌 Реквизиты Freedom Bank:\n`{REQUISITES_KZ}`"
            
    text += "\n\n⚠️ **После перевода обязательно пришлите скриншот чека в этот чат!** Бот автоматически передаст его администрации на проверку."
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨‍💻 Связаться с админом", url=f"https://t.me/{ADMIN_USERNAME}")],
        [InlineKeyboardButton(text="⬅️ Изменить тариф", callback_data="view_tariffs")]
    ])
    
    # Вшиваем информацию о выбранном периоде в callback_data кнопок, чтобы админ видел, что куплено
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    # Сохраняем во временном контексте тип выбранной подписки, перехватывая отправку фото
    await callback.answer()

# Просмотр профиля пользователем
@dp.callback_query(F.data == "view_profile")
async def process_view_profile(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT expires_at FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    
    if res:
        if res[0] == FOREVER_DATE:
            text = f"👤 **Ваш профиль:**\n\n✅ Подписка: **Активна (VIP)**\n📅 Действует до: `Навсегда`"
        else:
            expires_at = datetime.strptime(res[0], DATE_FORMAT)
            if expires_at > datetime.now():
                text = f"👤 **Ваш профиль:**\n\n✅ Подписка: **Активна**\n📅 Действует до: `{expires_at.strftime('%d.%m.%Y %H:%M')}`"
            else:
                text = "👤 **Ваш профиль:**\n\n❌ Подписка: **Истекла**\nДля возобновления доступа выберите тариф в меню /start"
    else:
        text = "👤 **Ваш профиль:**\n\n❌ Подписка: **Не оформлена**\nВы можете приобрести доступ через меню /start"
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "back_to_menu")
async def process_back_to_menu(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=" Tarifs / Тарифы ", callback_data="view_tariffs")],
        [InlineKeyboardButton(text="👤 Мой Профиль", callback_data="view_profile")]
    ])
    await callback.message.edit_text(
        "👋 **Главное меню**\n\n🔥 **Кавказ Группа** — приватный архив, где собрано около **70 тысяч видео**.\n\nВыберите нужный пункт:", reply_markup=kb
    )
    await callback.answer()

# Прием скриншота чека от пользователя
@dp.message(F.photo)
async def handle_receipt(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or "без_юзернейма"
    photo_id = message.photo[-1].file_id
    
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить на 5 мес", callback_data=f"app_5m_{user_id}_{username}"),
            InlineKeyboardButton(text="💎 Одобрить НАВСЕГДА", callback_data=f"app_for_{user_id}_{username}")
        ],
        [
            InlineKeyboardButton(text="❌ Отклонить чек", callback_data=f"decline_{user_id}")
        ]
    ])
    
    await bot.send_photo(
        chat_id=ADMIN_ID,
        photo=photo_id,
        caption=f"🔔 **Новый чек на проверку!**\n👤 От: @{username} (ID: {user_id})\nПожалуйста, посмотрите какую подписку заказывал пользователь и выберите кнопку ниже:",
        reply_markup=admin_kb
    )
    await message.answer("⏳ **Ваш чек отправлен на проверку.** Ожидайте, администратор проверит трансляцию и бот выдаст рабочую ссылку.")

# Решение админа: Одобрение подписки
@dp.callback_query(F.data.startswith("app_"))
async def admin_approve(callback: types.CallbackQuery):
    try:
        data_parts = callback.data.split("_", maxsplit=3)
        tariff_type = data_parts[1]
        user_id = int(data_parts[2])
        username = data_parts[3]
        
        if tariff_type == "5m":
            expires_at = datetime.now() + timedelta(days=DAYS_5M)
            expires_str = expires_at.strftime(DATE_FORMAT)
            display_date = expires_at.strftime('%d.%m.%Y %H:%M')
        else:
            expires_str = FOREVER_DATE
            display_date = "Навсегда (VIP)"
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO users (user_id, username, expires_at) VALUES (?, ?, ?)", 
                       (user_id, username, expires_str))
        conn.commit()
        conn.close()
        
        await bot.send_message(
            chat_id=user_id,
            text=f"Оплата успешно подтверждена! ✅\n"
                 f"📅 Срок действия подписки: **{display_date}**\n\n"
                 f"Ваша индивидуальная ссылка для вступления:\n{CHANNEL_LINK}"
        )
        await callback.message.edit_caption(caption=callback.message.caption + f"\n\n🟢 **Одобрено! Выдан тариф: {display_date}.**")
    except Exception as e:
        logging.error(f"Ошибка в admin_approve: {e}")
        await callback.message.answer(f"❌ Ошибка: {e}")
    await callback.answer()

# Решение админа: Отклонение
@dp.callback_query(F.data.startswith("decline_"))
async def admin_decline(callback: types.CallbackQuery):
    try:
        user_id = int(callback.data.split("_")[1])
        await bot.send_message(chat_id=user_id, text="❌ **Ваш чек был отклонен.** Если это недоразумение, напишите владельцу.")
        await callback.message.edit_caption(caption=callback.message.caption + "\n\n🔴 **Отклонено администратором.**")
    except Exception as e:
        logging.error(f"Ошибка в admin_decline: {e}")
        await callback.message.answer(f"❌ Ошибка: {e}")
    await callback.answer()


# ================= 🛠️ ИНТЕРАКТИВНАЯ АДМИН-ПАНЕЛЬ =================

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика бота", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 Сделать рассылку", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🚫 Удалить пользователя (Бан)", callback_data="admin_kick_user")]
    ])
    await message.answer("🛠️ **Панель администратора**\nВыберите действие:", reply_markup=kb)

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Считаем активных временных + вечников
    now_str = datetime.now().strftime(DATE_FORMAT)
    cursor.execute("SELECT COUNT(*) FROM users WHERE expires_at > ? OR expires_at = ?", (now_str, FOREVER_DATE))
    active_count = cursor.fetchone()[0]
    
    # Считаем вообще всех в боте
    cursor.execute("SELECT COUNT(*) FROM all_users")
    all_count = cursor.fetchone()[0]
    
    conn.close()
    
    text = (
        f"📊 **Статистика проекта:**\n\n"
        f"👥 Всего пользователей в базе: **{all_count}**\n"
        f"💳 Активных подписчиков (с доступом): **{active_count}**"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад в админку", callback_data="back_to_admin")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "back_to_admin")
async def back_to_admin(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика бота", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 Сделать рассылку", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🚫 Удалить пользователя (Бан)", callback_data="admin_kick_user")]
    ])
    await callback.message.edit_text("🛠️ **Панель администратора**\nВыберите действие:", reply_markup=kb)
    await callback.answer()

# --- СЦЕНАРИЙ РАССЫЛКИ ---
@dp.callback_query(F.data == "admin_broadcast")
async def start_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_admin")]
    ])
    await callback.message.edit_text(
        "📢 **Режим рассылки**\n\nОтправьте сообщение для рассылки.", reply_markup=kb
    )
    await state.set_state(AdminStates.broadcast_message)
    await callback.answer()

@dp.message(AdminStates.broadcast_message)
async def process_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM all_users")
    users = cursor.fetchall()
    conn.close()
    
    await message.answer(f"⏳ Начинаю рассылку для {len(users)} пользователей...")
    
    success = 0
    failed = 0
    
    for (user_id,) in users:
        try:
            await message.copy_to(chat_id=user_id)
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
            
    await state.clear()
    await message.answer(f"✅ **Рассылка завершена!**\n\n🟢 Успешно: {success}\n🔴 Не удалось: {failed}")

# --- СЦЕНАРИЙ РУЧНОГО БАНА ---
@dp.callback_query(F.data == "admin_kick_user")
async def start_kick_user(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_admin")]
    ])
    await callback.message.edit_text("🚫 Введите **Telegram ID** пользователя для его полного удаления:", reply_markup=kb)
    await state.set_state(AdminStates.ban_user_id)
    await callback.answer()

@dp.message(AdminStates.ban_user_id)
async def process_kick_user(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    try:
        target_id = int(message.text.strip())
        await bot.ban_chat_member(chat_id=GROUP_ID, user_id=target_id)
        await bot.unban_chat_member(chat_id=GROUP_ID, user_id=target_id)
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE user_id = ?", (target_id,))
        conn.commit()
        conn.close()
        
        try:
            await bot.send_message(target_id, "❌ Ваша подписка была аннулирована администратором.")
        except Exception:
            pass
            
        await message.answer(f"✅ Пользователь `{target_id}` успешно удален.")
    except ValueError:
        await message.answer("❌ Ошибка: ID должен состоять только из цифр.")
        return
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        
    await state.clear()


# ================= ЗАПУСК БОТА =================

async def main():
    init_db()
    scheduler.add_job(check_and_kick_expired_users, "interval", hours=1)
    scheduler.add_job(notification_before_expiry, "interval", hours=24)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
