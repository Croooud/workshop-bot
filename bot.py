import asyncio
import logging
import os
import random
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    WebAppInfo, 
    CallbackQuery, 
    BotCommand, 
    MenuButtonWebApp
)
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
import uvicorn
from pydantic import BaseModel
from typing import List

logging.basicConfig(level=logging.INFO)

raw_token = os.getenv("TOKEN", "891195735:AAG2kmk_YGK1tmF6RfrfWAX1J85MVlQ0JhA")
TOKEN = raw_token.replace('"', '').replace("'", "").strip()

# ID вашего общего рабочего чата (группы)
ADMIN_CHAT_ID = -5308446621

# Список ID администраторов (твой и товарища)
ADMIN_IDS = [1044338073, 602535191] 

bot = Bot(token=TOKEN)
dp = Dispatcher()

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def init_db():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            profile_link TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            user_id INTEGER,
            client_link TEXT,
            items TEXT,
            total INTEGER,
            status TEXT DEFAULT 'Новый',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/admin/download-db")
async def download_database(key: str = ""):
    if key != "ruch_secret_123":
        return {"error": "Unauthorized access"}
    db_path = "database.db"
    if os.path.exists(db_path):
        return FileResponse(db_path, media_type="application/octet-stream", filename="database.db")
    return {"error": "Database file not found"}

# Эндпоинт для получения истории заказов пользователя в личный кабинет
@app.get("/api/orders/{chat_id}")
async def get_user_orders(chat_id: int):
    try:
        conn = sqlite3.connect("database.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT order_id, items, total, status, created_at FROM orders WHERE user_id = ? ORDER BY created_at DESC",
            (chat_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        
        orders = []
        for row in rows:
            status_text = row["status"]
            if status_text == "Новый":
                status_formatted = "🕒 В обработке"
            elif status_text == "В работе":
                status_formatted = "🛠 В работе"
            elif status_text == "Готово":
                status_formatted = "✅ Готово"
            elif status_text == "Отменен":
                status_formatted = "❌ Отменен"
            else:
                status_formatted = f"📌 {status_text}"

            orders.append({
                "order_id": row["order_id"],
                "items": row["items"],
                "total": row["total"],
                "status": status_formatted,
                "created_at": row["created_at"]
            })
            
        return {"success": True, "orders": orders}
    except Exception as e:
        logging.error(f"Error fetching orders: {e}")
        return {"success": False, "orders": [], "error": str(e)}

class OrderItem(BaseModel):
    name: str
    price: int

class OrderRequest(BaseModel):
    chat_id: int
    items: List[OrderItem]
    total: int
    device: str
    problem: str
    phone: str

# Обработка отправки заявки
@app.post("/api/order")
async def api_order(order: OrderRequest):
    order_id = f"#{random.randint(10000, 99999)}"
    client_link = f"tg://user?id={order.chat_id}"
    
    try:
        conn = sqlite3.connect("database.db")
        cursor = conn.cursor()
        items_str = ", ".join([f"{item.name} ({item.price}₽)" for item in order.items])
        cursor.execute(
            "INSERT INTO orders (order_id, user_id, client_link, items, total) VALUES (?, ?, ?, ?, ?)",
            (order_id, order.chat_id, client_link, items_str, order.total)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"DB Error: {e}")

    items_list_str = ""
    for item in order.items:
        p_str = "Бесплатно" if item.price == 0 else f"{item.price:,} ₽".replace(',', ' ')
        items_list_str += f"▫️ {item.name} — *{p_str}*\n"
    
    total_str = f"{order.total:,} ₽".replace(',', ' ')

    admin_receipt = (
        f"🔔 **НОВЫЙ ЗАКАЗ {order_id}**\n\n"
        f"👤 Клиент: [ID {order.chat_id}]({client_link})\n"
        f"📱 Телефон: `{order.phone}`\n"
        f"💻 Тип устройства: {order.device}\n"
        f"⚠️ Проблема: {order.problem}\n\n"
        f"🛒 Состав заказа:\n{items_list_str}\n"
        f"💳 **Сумма: {total_str}**"
    )
    
    # Инлайн-кнопки для управления статусом в рабочем чате
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🛠 В работу", callback_data=f"status:in_progress:{order_id}"),
            InlineKeyboardButton(text="✅ Готово", callback_data=f"status:done:{order_id}"),
            InlineKeyboardButton(text="❌ Отменен", callback_data=f"status:cancelled:{order_id}")
        ]
    ])
    
    try:
        # Отправляем в общий рабочий чат мастеров
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_receipt, reply_markup=admin_kb, parse_mode="HTML")
        
        # Уведомляем клиента
        reply_text = "✅ Ваша заявка принята! Вы можете отслеживать её статус в «Личном кабинете» внутри мини-приложения."
        await bot.send_message(chat_id=order.chat_id, text=reply_text, parse_mode="HTML")
        
        return {"success": True}
    except Exception as e:
        logging.error(f"Error sending messages: {e}")
        return {"success": False, "error": str(e)}

# Обработчик нажатия на кнопки статусов в рабочем чате
@dp.callback_query(F.data.startswith("status:"))
async def process_status_change(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет прав для изменения статуса.", show_alert=True)
        return

    parts = callback.data.split(":")
    action = parts[1]
    order_id = parts[2]

    status_map = {
        "in_progress": "В работе",
        "done": "Готово",
        "cancelled": "Отменен"
    }
    
    new_status = status_map.get(action, "Новый")

    # Обновляем статус в БД и находим chat_id клиента для отправки личного сообщения
    client_chat_id = None
    try:
        conn = sqlite3.connect("database.db")
        cursor = conn.cursor()
        
        cursor.execute("SELECT user_id FROM orders WHERE order_id = ?", (order_id,))
        row = cursor.fetchone()
        if row:
            client_chat_id = row[0]

        cursor.execute("UPDATE orders SET status = ? WHERE order_id = ?", (new_status, order_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"DB Update Error: {e}")
        await callback.answer("Ошибка при обновлении базы данных.", show_alert=True)
        return

    master_name = callback.from_user.full_name
    
    updated_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🛠 В работу", callback_data=f"status:in_progress:{order_id}"),
            InlineKeyboardButton(text="✅ Готово", callback_data=f"status:done:{order_id}"),
            InlineKeyboardButton(text="❌ Отменен", callback_data=f"status:cancelled:{order_id}")
        ]
    ])

    raw_text = callback.message.text
    if "\n\n📌 **" in raw_text:
        base_text = raw_text.split("\n\n📌 **")[0]
    else:
        base_text = raw_text

    updated_text = base_text + f"\n\n📌 **Текущий статус: {new_status}** (изменил {master_name})"
    
    try:
        await callback.message.edit_text(text=updated_text, parse_mode="HTML", reply_markup=updated_kb)
    except Exception:
        pass

    # Отправляем прямое сообщение клиенту в ЛС
    if client_chat_id:
        try:
            if action == "in_progress":
                client_msg = f"👨‍🔧 Ваш заказ **{order_id}** взят в работу мастером."
            elif action == "done":
                client_msg = f"✅ **Готово!** Ваш заказ **{order_id}** выполнен и ждет вас."
            elif action == "cancelled":
                client_msg = f"❌ Статус вашего заказа **{order_id}** изменен на: **Отменен**."
            else:
                client_msg = f"📌 Статус вашего заказа **{order_id}** обновлен: {new_status}."

            await bot.send_message(chat_id=client_chat_id, text=client_msg, parse_mode="HTML")
        except Exception as e:
            logging.error(f"Failed to send direct message to client {client_chat_id}: {e}")

    await callback.answer(f"Статус заказа {order_id} изменен на «{new_status}»!")

@dp.message(Command("start", "restart"))
async def cmd_start(message: types.Message):
    user = message.from_user
    username = user.username or ""
    profile_link = f"https://t.me/{username}" if username else f"tg://user?id={user.id}"
    
    try:
        conn = sqlite3.connect("database.db")
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (user_id, username, full_name, profile_link) 
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET 
                username=excluded.username, 
                full_name=excluded.full_name, 
                profile_link=excluded.profile_link
        """, (user.id, username, user.full_name, profile_link))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"User save error: {e}")

    web_app_url = "https://workshop-bot-dcyv.onrender.com"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚡️ ОТКРЫТЬ ПРАЙС И ЗАКАЗАТЬ", web_app=WebAppInfo(url=web_app_url))],
            [InlineKeyboardButton(text="📍 Контакты", callback_data="show_contacts"),
             InlineKeyboardButton(text="❓ Частые вопросы", callback_data="show_faq")]
        ]
    )
    welcome_text = (
        "👋 **Добро пожаловать в «Мастерскую Ручеёк»!**\n\n"
        "Мы занимаемся профессиональным ремонтом, обслуживанием и сборкой компьютерной техники.\n\n"
        "🔸 *Бесплатная диагностика*\n"
        "🔸 *Прозрачные цены*\n"
        "🔸 *Выезд на дом по договоренности*\n\n"
        "Выберите нужное действие в меню ниже 👇"
    )
    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data == "show_contacts")
async def process_contacts(callback: CallbackQuery):
    text = (
        "📍 **НАШИ КОНТАКТЫ**\n\n"
        "**Адрес:** ПГТ Ручейк, ул., д. 1\n"
        "**Телефон / WhatsApp:** `+7 (991) 888-60-17`\n"
        "**Telegram:** @IvanMiroshnichenkoo\n\n"
        "*Работаем по предварительной записи. Возможен выезд на дом.*"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "show_faq")
async def process_faq(callback: CallbackQuery):
    text = (
        "❓ **ЧАСТЫЕ ВОПРОСЫ**\n\n"
        "**— Сколько длится диагностика?**\n"
        "Обычно от 1 до 3 часов в зависимости от сложности.\n\n"
        "**— Можно ли со своими запчастями?**\n"
        "Да, мы соберем ПК из ваших комплектующих.\n\n"
        "**— Даете ли гарантию?**\n"
        "Да, на все виды работ предоставляется техническая гарантия."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "back_to_main")
async def process_back(callback: CallbackQuery):
    web_app_url = "https://workshop-bot-dcyv.onrender.com"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚡️ ОТКРЫТЬ ПРАЙС И ЗАКАЗАТЬ", web_app=WebAppInfo(url=web_app_url))],
            [InlineKeyboardButton(text="📍 Контакты", callback_data="show_contacts"),
             InlineKeyboardButton(text="❓ Частые вопросы", callback_data="show_faq")]
        ]
    )
    welcome_text = (
        "👋 **Добро пожаловать в «Мастерскую Ручеёк»!**\n\n"
        "Мы занимаемся профессиональным ремонтом, обслуживанием и сборкой компьютерной техники.\n\n"
        "🔸 *Бесплатная диагностика*\n"
        "🔸 *Прозрачные цены*\n"
        "🔸 *Выезд на дом по договоренности*\n\n"
        "Выберите нужное действие в меню ниже 👇"
    )
    await callback.message.edit_text(welcome_text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="restart", description="Перезапустить бота")
    ]
    await bot.set_my_commands(commands)

    try:
        web_app_url = "https://workshop-bot-dcyv.onrender.com"
        menu_button = MenuButtonWebApp(
            text="Прайс и Заказ",
            web_app=WebAppInfo(url=web_app_url)
        )
        await bot.set_chat_menu_button(menu_button=menu_button)
    except Exception as e:
        logging.error(f"Menu button setup error: {e}")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await set_bot_commands(bot)
    asyncio.create_task(dp.start_polling(bot))
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)), log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
