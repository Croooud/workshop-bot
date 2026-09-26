import asyncio
import logging
import os
import random
import sqlite3
import json
import re
from google import genai
from google.genai import types
from aiogram import Bot, Dispatcher, types as aiogram_types, F
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

gemini_api_key = os.getenv("GEMINI_API_KEY", "")
gemini_client = genai.Client(api_key=gemini_api_key) if gemini_api_key else None

ADMIN_CHAT_ID = -5308446621
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

async def analyze_device_photo(file_bytes: bytes, mime_type: str) -> str:
    if not gemini_client:
        return "Ключ API не настроен."
    
    try:
        prompt = (
            "Ты профессиональный мастер по ремонту компьютеров и ноутбуков. "
            "Проанализируй фото повреждения или проблемы. Выдай короткий предварительный вердикт на русском языке: "
            "какая это поломка и примерный диапазон стоимости ремонта в рублях. "
            "Если фото размытое, не имеет отношения к технике или поломку невозможно определить, "
            "строго ответь: «Фото принято, точную стоимость назовет мастер после осмотра»."
        )
        
        response = await gemini_client.aio.models.generate_content(
            model='gemini-3.8-flash',
            contents=[
                types.Part.from_bytes(
                    data=file_bytes,
                    mime_type=mime_type,
                ),
                prompt
            ]
        )
        raw_text = response.text.strip()
        html_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', raw_text, flags=re.DOTALL)
        return html_text
    except Exception as e:
        logging.error(f"Gemini API Vision Error: {e}")
        return f"❌ Техническая ошибка ИИ: {e}"

@app.post("/api/upsell")
async def api_upsell(items: str = Form(...), is_b2b: str = Form("false")):
    fallback_rec = "<b>Регулярное обслуживание</b> продлевает срок службы техники. Обращайтесь к профессионалам!"
    
    if not gemini_client:
        return {"success": True, "recommendation": fallback_rec}
        
    try:
        items_list = json.loads(items)
        if not items_list:
            return {"success": True, "recommendation": fallback_rec}
            
        cart_names = [item['name'] for item in items_list]
        cart_str = ", ".join(cart_names)
        
        price_list_b2c = """
        1. Диагностика компьютера
        2. Комплексная чистка ПК + замена термопасты
        3. Чистка ноутбука от пыли и перегрева
        4. Установка Windows (с активацией)
        5. Установка пакета Microsoft Office
        6. Сборка ПК из комплектующих
        7. Оптимизация и чистка от вирусов
        8. Замена матрицы / экрана
        9. Ремонт после залития
        10. Восстановление данных
        """

        price_list_b2b = """
        1. Организация рабочего места под ключ
        2. Настройка локальной сети и серверов
        3. IT-аутсорсинг офиса
        4. Легализация и установка корпоративного ПО
        5. Настройка систем резервного копирования
        6. Модернизация корпоративного парка ПК
        """

        active_price = price_list_b2b if is_b2b == "true" else price_list_b2c
        client_type = "Бизнес-клиент" if is_b2b == "true" else "Частный клиент"
        
        prompt = (
            f"{client_type} добавил в корзину: {cart_str}.\n"
            f"Наш актуальный прайс-лист:\n{active_price}\n"
            "Выступи в роли опытного ИТ-инженера. Посоветуй ТОЛЬКО ОДНУ дополнительную услугу из прайса, "
            "которая логично дополнит этот заказ. НЕ предлагай то, что уже есть в корзине.\n"
            "Напиши коротко (1-2 предложения). "
            "Начни сразу с текста. Выдели название предлагаемой услуги жирным шрифтом с помощью Markdown (**)."
        )
        
        response = await gemini_client.aio.models.generate_content(
            model='gemini-3.8-flash',
            contents=[prompt]
        )
        
        raw_text = response.text.strip()
        html_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', raw_text, flags=re.DOTALL)
        
        if not html_text:
            html_text = fallback_rec
            
        return {"success": True, "recommendation": html_text}
    except Exception as e:
        logging.error(f"Upsell Error: {e}")
        return {"success": True, "recommendation": fallback_rec}

@app.post("/api/order")
async def api_order(
    chat_id: int = Form(...),
    items: str = Form(...),
    total: int = Form(...),
    device: str = Form(...),
    phone: str = Form(...),
    photo: UploadFile = File(None),
    is_b2b: str = Form("false"),
    problem: str = Form(None),
    workplaces: str = Form(None),
    office_info: str = Form(None)
):
    order_id = f"#{random.randint(10000, 99999)}"
    client_link = f"tg://user?id={chat_id}"
    
    try:
        items_list = json.loads(items)
    except:
        items_list = []

    ai_analysis_text = "Без фото"
    file_bytes = None

    if photo:
        file_bytes = await photo.read()
        mime_type = photo.content_type or "image/jpeg"
        ai_analysis_text = await analyze_device_photo(file_bytes, mime_type)

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
        p_str = "По договоренности" if item['price'] == 0 else f"{item['price']:,} ₽".replace(',', ' ')
        items_list_str += f"▫️ {item['name']} — <i>{p_str}</i>\n"
    
    total_str = f"{total:,} ₽".replace(',', ' ')

    # Маршрутизация B2B / B2C
    if is_b2b == "true":
        header = f"💼 <b>НОВЫЙ КОРПОРАТИВНЫЙ ЗАКАЗ {order_id}</b>"
        problem_block = f"🏢 Рабочих мест: <b>{workplaces or 'Не указано'}</b>\n📍 Офис/Площадь: <b>{office_info or 'Не указано'}</b>"
    else:
        header = f"🔔 <b>НОВЫЙ ЗАКАЗ {order_id}</b>"
        problem_block = f"⚠️ Проблема: {problem or 'Не указано'}"

    admin_receipt = (
        f"{header}\n\n"
        f"👤 Клиент: <a href='{client_link}'>ID {chat_id}</a>\n"
        f"📱 Телефон: <code>{phone}</code>\n"
        f"💻 Тип устройства: {device}\n"
        f"{problem_block}\n"
        f"🤖 <b>Скрытая AI-оценка:</b>\n{ai_analysis_text}\n\n"
        f"🛒 Состав заказа:\n{items_list_str}\n"
        f"💳 <b>Сумма: {total_str}</b>"
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
            f"✅ Ваша заявка <b>{order_id}</b> принята!\n\n"
            f"Мастер скоро свяжется с вами. Вы можете отслеживать статус заказа в «Личном кабинете»."
        )
        await bot.send_message(chat_id=chat_id, text=reply_text, parse_mode="HTML")
        
        return {"success": True} 
    except Exception as e:
        logging.error(f"Error sending messages: {e}")
        return {"success": False, "error": str(e)}

@dp.message(Command("stats"))
async def cmd_stats(message: aiogram_types.Message):
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
            f"📊 <b>Аналитика мастерской «Ручеёк»</b>\n\n"
            f"📦 Всего заказов создано: <b>{total_orders}</b>\n"
            f"🛠 Сейчас в работе: <b>{in_progress_orders}</b>\n"
            f"✅ Выполнено заказов: <b>{done_orders}</b>\n"
            f"💰 Общая выручка: <b>{revenue_str} ₽</b>"
        )

        await message.answer(stats_text, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Stats error: {e}")
        await message.answer("⚠️ Ошибка при подсчете статистики.")

async def schedule_review_request(client_chat_id: int, order_id: str):
    await asyncio.sleep(86400)

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
            f"👋 Привет! Прошли сутки с момента завершения ремонта в <b>«Мастерской Ручеёк»</b> (заказ <b>{order_id}</b>).\n\n"
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
    await callback.message.edit_text(f"Спасибо за ваш отзыв! Вы поставили нам оценку: <b>{stars} ({rating}/5)</b>.", parse_mode="HTML")

    admin_notification = (
        f"⭐ <b>НОВЫЙ ОТЗЫВ КЛИЕНТА</b>\n\n"
        f"📦 Заказ: <b>{order_id}</b>\n"
        f"👤 Клиент: <a href='{user_link}'>{user_name}</a>\n"
        f"📊 Оценка: <b>{stars} ({rating} из 5)</b>"
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
    base_text = raw_text.split("\n\n📌 <b>")[0] if "\n\n📌 <b>" in raw_text else raw_text
    updated_text = base_text + f"\n\n📌 <b>Текущий статус: {new_status}</b> (изменил {master_name})"

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
                client_msg = f"👨‍🔧 Ваш заказ <b>{order_id}</b> взят в работу мастером."
            elif action == "done":
                client_msg = f"✅ <b>Готово!</b> Ваш заказ <b>{order_id}</b> выполнен и ждет вас."
            elif action == "cancelled":
                client_msg = f"❌ Статус вашего заказа <b>{order_id}</b> изменен на: <b>Отменен</b>."
            else:
                client_msg = f"📌 Статус заказа <b>{order_id}</b> обновлен: {new_status}."

            await bot.send_message(chat_id=client_chat_id, text=client_msg, parse_mode="HTML")
        except Exception as e:
            logging.error(f"DM error: {e}")

    await callback.answer(f"Статус изменен на «{new_status}»!")

@dp.message(Command("start", "restart"))
async def cmd_start(message: aiogram_types.Message):
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
        "👋 <b>Добро пожаловать в «Мастерскую Ручеёк»!</b>\n\n"
        "Профессиональный ремонт и обслуживание компьютерной техники для дома и бизнеса."
    )
    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data == "show_contacts")
async def process_contacts(callback: CallbackQuery):
    text = (
        "📍 <b>НАШИ КОНТАКТЫ</b>\n\n"
        "<b>Адрес:</b> ПГТ Ручейк, ул., д. 1\n"
        "<b>Телефон:</b> <code>+7 (991) 888-60-17</code>\n"
        "<b>Telegram:</b> @IvanMiroshnichenkoo"
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
        "<b>— Диагностика платная?</b>\nБесплатно при последующем ремонте.\n\n"
        "<b>— Даете гарантию?</b>\nДа, на все виды работ."
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
        "Профессиональный ремонт и обслуживание компьютерной техники для дома и бизнеса."
    )
    await callback.message.edit_text(welcome_text, reply_markup=kb, parse_mode="HTML")
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
