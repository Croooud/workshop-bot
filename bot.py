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

ADMIN_ID = 1044338073

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

# Структуры данных для приёма JSON из опросника
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
    
    # Сохраняем в БД
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

    # Формируем красивый чек для админа
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
    
    try:
        # Уведомляем админа
        await bot.send_message(chat_id=ADMIN_ID, text=admin_receipt, parse_mode="HTML")
        
        # Благодарим клиента
        reply_text = "✅ Ваша заявка принята! Если у вас есть фото поломки или ошибки на экране, просто отправьте их прямо сейчас в этот чат."
        await bot.send_message(chat_id=order.chat_id, text=reply_text, parse_mode="HTML")
        
        return {"success": True}
    except Exception as e:
        logging.error(f"Error sending messages: {e}")
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

    # Настройка системной кнопки меню (слева от поля ввода в чате)
    web_app_url = "https://workshop-bot-dcyv.onrender.com"
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="Прайс и Заказ",
            web_app=WebAppInfo(url=web_app_url)
        )
    )

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await set_bot_commands(bot)
    asyncio.create_task(dp.start_polling(bot))
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)), log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
