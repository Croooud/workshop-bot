import asyncio
import logging
import os
import random
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, CallbackQuery, BotCommand
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List
import uvicorn

logging.basicConfig(level=logging.INFO)

raw_token = os.getenv("TOKEN", "891195735:AAG2kmk_YGK1tmF6RfrfWAX1J85MVlQ0JhA")
TOKEN = raw_token.replace('"', '').replace("'", "").strip()

ADMIN_ID = 1044338073

bot = Bot(token=TOKEN)
dp = Dispatcher()

app = FastAPI()

# Подключаем папку со статическими файлами (твоими иконками)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ---
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

class OrderItem(BaseModel):
    name: str
    price: int

class OrderRequest(BaseModel):
    chat_id: int
    items: List[OrderItem]
    total: int

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

@app.post("/api/order")
async def create_order(order: OrderRequest):
    order_id = f"#{random.randint(10000, 99999)}"
    client_link = f"tg://user?id={order.chat_id}"
    try:
        conn = sqlite3.connect("database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM users WHERE user_id = ?", (order.chat_id,))
        res = cursor.fetchone()
        if res and res[0]:
            client_link = f"https://t.me/{res[0]}"
            
        items_str = ", ".join([f"{item.name} ({item.price}₽)" for item in order.items])
        cursor.execute(
            "INSERT INTO orders (order_id, user_id, client_link, items, total) VALUES (?, ?, ?, ?, ?)",
            (order_id, order.chat_id, client_link, items_str, order.total)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"DB Error: {e}")

    receipt = f"🧾 <b>ЗАКАЗ {order_id} ПРИНЯТ</b>\n\n"
    receipt += "<blockquote>"
    for item in order.items:
        price_str = "Бесплатно" if item.price == 0 else f"{item.price:,} ₽".replace(',', ' ')
        receipt += f"▫️ {item.name}\n└ <i>{price_str}</i>\n\n"
    receipt += f"<b>ИТОГО: {order.total:,} ₽</b>".replace(',', ' ')
    receipt += "</blockquote>\n"
    receipt += "👨‍💻 <i>Мастер уже получил уведомление и скоро свяжется с вами.</i>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Написать мастеру", url="https://t.me/IvanMiroshnichenkoo")],
        [InlineKeyboardButton(text="❌ Отменить заказ", callback_data=f"cancel_order")]
    ])
    
    admin_receipt = (
        f"🔔 <b>НОВЫЙ ЗАКАЗ {order_id}</b>\n\n"
        f"👤 Клиент: <a href='{client_link}'>Открыть профиль</a> (ID: <code>{order.chat_id}</code>)\n"
        f"🛒 Состав:\n{items_str}\n\n"
        f"💳 <b>Сумма: {order.total:,} ₽</b>".replace(',', ' ')
    )
    
    try:
        await bot.send_message(chat_id=order.chat_id, text=receipt, parse_mode="HTML", reply_markup=kb)
        await bot.send_message(chat_id=ADMIN_ID, text=admin_receipt, parse_mode="HTML", disable_web_page_preview=True)
        return {"success": True}
    except Exception as e:
        logging.error(f"Telegram API Error: {str(e)}")
        return {"success": False, "error": str(e)}

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
        "👋 <b>Добро пожаловать в «Мастерскую Ручеёк»!</b>\n\n"
        "Мы занимаемся профессиональным ремонтом, обслуживанием и сборкой компьютерной техники.\n\n"
        "🔸 <i>Бесплатная диагностика</i>\n"
        "🔸 <i>Прозрачные цены</i>\n"
        "🔸 <i>Выезд на дом по договоренности</i>\n\n"
        "Выберите нужное действие в меню ниже 👇"
    )
    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data == "show_contacts")
async def process_contacts(callback: CallbackQuery):
    text = (
        "📍 <b>НАШИ КОНТАКТЫ</b>\n\n"
        "<b>Адрес:</b> ПГТ Ручейк, ул., д. 1\n"
        "<b>Телефон / WhatsApp:</b> <code>+7 (991) 888-60-17</code>\n"
        "<b>Telegram:</b> @IvanMiroshnichenkoo\n\n"
        "<i>Работаем по предварительной записи. Возможен выезд на дом.</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "show_faq")
async def process_faq(callback: CallbackQuery):
    text = (
        "❓ <b>ЧАСТЫЕ ВОПРОСЫ</b>\n\n"
        "<b>— Сколько длится диагностика?</b>\n"
        "Обычно от 1 до 3 часов в зависимости от сложности.\n\n"
        "<b>— Можно ли со своими запчастями?</b>\n"
        "Да, мы соберем ПК из ваших комплектующих.\n\n"
        "<b>— Даете ли гарантию?</b>\n"
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
        "👋 <b>Добро пожаловать в «Мастерскую Ручеёк»!</b>\n\n"
        "Мы занимаемся профессиональным ремонтом, обслуживанием и сборкой компьютерной техники.\n\n"
        "🔸 <i>Бесплатная диагностика</i>\n"
        "🔸 <i>Прозрачные цены</i>\n"
        "🔸 <i>Выезд на дом по договоренности</i>\n\n"
        "Выберите нужное действие в меню ниже 👇"
    )
    await callback.message.edit_text(welcome_text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "cancel_order")
async def process_cancel_order(callback: CallbackQuery):
    await callback.message.edit_text("❌ <i>Заявка отменена. Если передумаете, мы всегда на связи!</i>", parse_mode="HTML")
    await callback.answer("Заказ отменен")

async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="restart", description="Перезапустить бота")
    ]
    await bot.set_my_commands(commands)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await set_bot_commands(bot)
    asyncio.create_task(dp.start_polling(bot))
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)), log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
