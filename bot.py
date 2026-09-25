import asyncio
import logging
import os
import random
import sqlite3
import json
import base64
import openai
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    WebAppInfo, 
    CallbackQuery, 
    BotCommand, 
    MenuButtonWebApp,
    BufferedInputFile
)
from fastapi import FastAPI, Request, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
import uvicorn
from pydantic import BaseModel
from typing import List

logging.basicConfig(level=logging.INFO)

raw_token = os.getenv("TOKEN", "891195735:AAG2kmk_YGK1tmF6RfrfWAX1J85MVlQ0JhA")
TOKEN = raw_token.replace('"', '').replace("'", "").strip()

# Инициализация OpenAI (ключ берется из переменных окружения Render)
openai.api_key = os.getenv("OPENAI_API_KEY", "")

# ID вашего общего рабочего чата (группы)
ADMIN_CHAT_ID = -5308446621

# Список ID администраторов
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT,
            user_id INTEGER,
            rating INTEGER,
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
            orders.append({
                "order_id": row["order_id"],
                "items": row["items"],
                "total": row["total"],
                "status": row["status"],
                "created_at": row["created_at"]
            })
            
        return {"success": True, "orders": orders}
    except Exception as e:
        logging.error(f"Error fetching orders: {e}")
        return {"success": False, "orders": [], "error": str(e)}

async def analyze_device_photo(file_bytes: bytes) -> str:
    """Анализирует фото с помощью OpenAI Vision API"""
    if not openai.api_key:
        return "Фото принято, точную стоимость назовет мастер после осмотра."
    
    try:
        base64_image = base64.b64encode(file_bytes).decode('utf-8')
        
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Ты профессиональный мастер по ремонту компьютеров и ноутбуков. Проанализируй фото повреждения или проблемы. Выдай короткий предварительный вердикт на русском языке: какая это поломка и примерный диапазон стоимости ремонта в рублях. Если фото размытое, не имеет отношения к технике или поломку невозможно определить, строго ответь: «Фото принято, точную стоимость назовет мастер после осмотра»."
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Оцени поломку по этому фото:"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=150
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"OpenAI Vision API Error: {e}")
        return "Фото принято, точную стоимость назовет мастер после осмотра."

@app.post("/api/order")
async def api_order(
    chat_id: int = Form(...),
    items: str = Form(...),
    total: int = Form(...),
    device: str = Form(...),
    problem: str = Form(...),
    phone: str = Form(...),
    photo: UploadFile = File(None)
):
    order_id = f"#{random.randint(10000, 99999)}"
    client_link = f"tg://user?id={chat_id}"
    
    try:
        items_list = json.loads(items)
    except:
        items_list = []

    ai_analysis_text = "Фото не загружалось"
    file_bytes = None

    if photo:
        file_bytes = await photo.read()
        ai_analysis_text = await analyze_device_photo(file_bytes)

    try:
        conn = sqlite3.connect("database.db")
        cursor = conn.cursor()
        items_str = ", ".join([f"{item['name']} ({item['price']}₽)" for item in items_list])
        cursor.execute(
            "INSERT INTO orders (order_id, user_id, client_link, items, total) VALUES (?, ?, ?, ?, ?)",
            (order_id, chat_id, client_link, items_str, total)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"DB Error: {e}")

    items_list_str = ""
    for item in items_list:
        p_str = "Бесплатно" if item['price'] == 0 else f"{item['price']:,} ₽".replace(',', ' ')
        items_list_str += f"▫️ {item['name']} — *{p_str}*\n"
    
    total_str = f"{total:,} ₽".replace(',', ' ')

    admin_receipt = (
        f"🔔 **НОВЫЙ ЗАКАЗ {order_id}**\n\n"
        f"👤 Клиент: [ID {chat_id}]({client_link})\n"
        f"📱 Телефон: `{phone}`\n"
        f"💻 Тип устройства: {device}\n"
        f"⚠️ Проблема: {problem}\n"
        f"🤖 **AI-оценка по фото:** {ai_analysis_text}\n\n"
        f"🛒 Состав заказа:\n{items_list_str}\n"
        f"💳 **Сумма: {total_str}**"
    )
    
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🛠 В работу", callback_data=f"status:in_progress:{order_id}"),
            InlineKeyboardButton(text="✅ Готово", callback_data=f"status:done:{order_id}"),
            InlineKeyboardButton(text="❌ Отменен", callback_data=f"status:cancelled:{order_id}")
        ]
    ])
    
    try:
        if photo and file_bytes:
            photo_file = BufferedInputFile(file_bytes, filename=photo.filename or "problem.jpg")
            await bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=photo_file,
                caption=admin_receipt,
                reply_markup=admin_kb,
                parse_mode="HTML"
            )
        else:
            await bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_receipt,
                reply_markup=admin_kb,
                parse_mode="HTML"
            )
        
        reply_text = (
            f"✅ Ваша заявка **{order_id}** принята!\n\n"
            f"🤖 **Предварительный анализ вашей фотографии:**\n"
            f"*{ai_analysis_text}*\n\n"
            f"Вы можете отслеживать статус заказа в «Личном кабинете»."
        )
        await bot.send_message(chat_id=chat_id, text=reply_text, parse_mode="HTML")
        
        return {"success": True, "ai_analysis": ai_analysis_text}
    except Exception as e:
        logging.error(f"Error sending messages: {e}")
        return {"success": False, "error": str(e)}

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("У вас нет прав для просмотра статистики.")
        return

    try:
        conn = sqlite3.connect("database.db")
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM orders")
        total_orders = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'В работе'")
        in_progress_orders = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'Готово'")
        done_orders = cursor.fetchone()[0]

        cursor.execute("SELECT SUM(total) FROM orders WHERE status = 'Готово'")
        result_revenue = cursor.fetchone()[0]
        total_revenue = result_revenue if result_revenue else 0

        conn.close()

        revenue_str = f"{total_revenue:,}".replace(',', ' ')

        stats_text = (
            f"📊 **Аналитика мастерской «Ручеёк»**\n\n"
            f"📦 Всего заказов создано: **{total_orders}**\n"
            f"🛠 Сейчас в работе: **{in_progress_orders}**\n"
            f"✅ Выполнено заказов: **{done_orders}**\n"
            f"💰 Общая выручка: **{revenue_str} ₽**"
        )

        await message.answer(stats_text, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Stats error: {e}")
        await message.answer("⚠️ Ошибка при подсчете статистики.")

async def schedule_review_request(client_chat_id: int, order_id: str):
    await asyncio.sleep(86400) # 24 часа

    try:
        conn = sqlite3.connect("database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM orders WHERE order_id = ?", (order_id,))
        row = cursor.fetchone()
        conn.close()

        if not row or row[0] != "Готово":
            return

        review_kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="⭐ 1", callback_data=f"review:1:{order_id}"),
                InlineKeyboardButton(text="⭐ 2", callback_data=f"review:2:{order_id}"),
                InlineKeyboardButton(text="⭐ 3", callback_data=f"review:3:{order_id}"),
                InlineKeyboardButton(text="⭐ 4", callback_data=f"review:4:{order_id}"),
                InlineKeyboardButton(text="⭐ 5", callback_data=f"review:5:{order_id}")
            ]
        ])

        msg_text = (
            f"👋 Привет! Прошли сутки с момента завершения ремонта в **«Мастерской Ручеёк»** (заказ **{order_id}**).\n\n"
            f"Как работает техника? Оцените, пожалуйста, качество обслуживания от 1 до 5 звезд 👇"
        )
        await bot.send_message(chat_id=client_chat_id, text=msg_text, reply_markup=review_kb, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Error sending review request: {e}")

@dp.callback_query(F.data.startswith("review:"))
async def process_review_rating(callback: CallbackQuery):
    parts = callback.data.split(":")
    rating = parts[1]
    order_id = parts[2]
    user_id = callback.from_user.id
    user_name = callback.from_user.full_name
    username = callback.from_user.username
    user_link = f"https://t.me/{username}" if username else f"tg://user?id={user_id}"

    try:
        conn = sqlite3.connect("database.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO reviews (order_id, user_id, rating) VALUES (?, ?, ?)", (order_id, user_id, int(rating)))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"DB Review save error: {e}")

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    stars = "⭐" * int(rating)
    await callback.answer("Спасибо за вашу оценку!", show_alert=True)
    await callback.message.edit_text(f"Спасибо за ваш отзыв! Вы поставили нам оценку: **{stars} ({rating}/5)**.", parse_mode="HTML")

    admin_notification = (
        f"⭐ **НОВЫЙ ОТЗЫВ КЛИЕНТА**\n\n"
        f"📦 Заказ: **{order_id}**\n"
        f"👤 Клиент: [{user_name}]({user_link})\n"
        f"📊 Оценка: **{stars} ({rating} из 5)**"
    )
    await bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_notification, parse_mode="HTML")

@dp.callback_query(F.data.startswith("status:"))
async def process_status_change(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет прав.", show_alert=True)
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
        logging.error(f"DB Error: {e}")
        return

    if action == "done" and client_chat_id:
        asyncio.create_task(schedule_review_request(client_chat_id, order_id))

    master_name = callback.from_user.full_name
    updated_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🛠 В работу", callback_data=f"status:in_progress:{order_id}"),
            InlineKeyboardButton(text="✅ Готово", callback_data=f"status:done:{order_id}"),
            InlineKeyboardButton(text="❌ Отменен", callback_data=f"status:cancelled:{order_id}")
        ]
    ])

    raw_text = callback.message.text if callback.message.text else (callback.message.caption or "")
    base_text = raw_text.split("\n\n📌 **")[0] if "\n\n📌 **" in raw_text else raw_text
    updated_text = base_text + f"\n\n📌 **Текущий статус: {new_status}** (изменил {master_name})"

    try:
        if callback.message.photo:
            await callback.message.edit_caption(caption=updated_text, parse_mode="HTML", reply_markup=updated_kb)
        else:
            await callback.message.edit_text(text=updated_text, parse_mode="HTML", reply_markup=updated_kb)
    except Exception:
        pass

    if client_chat_id:
        try:
            if action == "in_progress":
                client_msg = f"👨‍🔧 Ваш заказ **{order_id}** взят в работу мастером."
            elif action == "done":
                client_msg = f"✅ **Готово!** Ваш заказ **{order_id}** выполнен и ждет вас."
            elif action == "cancelled":
                client_msg = f"❌ Статус вашего заказа **{order_id}** изменен на: **Отменен**."
            else:
                client_msg = f"📌 Статус заказа **{order_id}** обновлен: {new_status}."

            await bot.send_message(chat_id=client_chat_id, text=client_msg, parse_mode="HTML")
        except Exception as e:
            logging.error(f"DM error: {e}")

    await callback.answer(f"Статус изменен на «{new_status}»!")

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
        logging.error(f"User error: {e}")

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
        "Профессиональный ремонт и обслуживание компьютерной техники."
    )
    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data == "show_contacts")
async def process_contacts(callback: CallbackQuery):
    text = (
        "📍 **НАШИ КОНТАКТЫ**\n\n"
        "**Адрес:** ПГТ Ручейк, ул., д. 1\n"
        "**Телефон:** `+7 (991) 888-60-17`\n"
        "**Telegram:** @IvanMiroshnichenkoo"
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
        "**— Диагностика платная?**\nБесплатно при последующем ремонте.\n\n"
        "**— Даете гарантию?**\nДа, на все виды работ."
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
        "Профессиональный ремонт и обслуживание компьютерной техники."
    )
    await callback.message.edit_text(welcome_text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="restart", description="Перезапустить бота"),
        BotCommand(command="stats", description="Статистика и выручка (для мастеров)")
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
        logging.error(f"Menu error: {e}")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await set_bot_commands(bot)
    asyncio.create_task(dp.start_polling(bot))
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)), log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
