import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import uvicorn
import threading

# Токен твоего бота
TOKEN = "8911195735:AAG2kmk_YGKltmF6RfrfWAX1J85MVLqOJhA"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Настройка FastAPI
app = FastAPI()
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def serve_mini_app(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/book")
async def handle_booking(data: dict):
    user_id = data.get("user_id")
    service = data.get("service")
    client_name = data.get("name")
    phone = data.get("phone")
    
    summary_client = (
        "✅ <b>Заявка успешно оформлена!</b>\n\n"
        f"▪️ <b>Услуга:</b> {service}\n"
        f"▪️ <b>Имя:</b> {client_name}\n"
        f"▪️ <b>Контакт:</b> {phone}\n\n"
        "Мастер свяжется с вами в ближайшее время для подтверждения."
    )
    try:
        await bot.send_message(chat_id=user_id, text=summary_client, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Ошибка отправки сообщения: {e}")
        
    return {"status": "ok"}

# Главное меню с динамической ссылкой из окружения Render
def get_main_menu(webapp_url: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Открыть Мастерскую (Mini App)", web_app=WebAppInfo(url=webapp_url))],
        [InlineKeyboardButton(text="📍 Контакты и адрес", callback_data="contacts")]
    ])

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Render автоматически передает внешний адрес в переменную окружения RENDER_EXTERNAL_URL
    render_url = os.getenv("RENDER_EXTERNAL_URL", "https://example.com")
    await message.answer(
        f"Приветствуем, {message.from_user.first_name}!\n"
        "💻 <b>Компьютерная мастерская в пгт Ручеёк</b>\n"
        "Нажмите кнопку ниже, чтобы открыть каталог услуг и записаться:",
        parse_mode="HTML",
        reply_markup=get_main_menu(render_url)
    )

@dp.callback_query(F.data == "contacts")
async def show_contacts(callback: types.CallbackQuery):
    render_url = os.getenv("RENDER_EXTERNAL_URL", "https://example.com")
    text = (
        "<b>📍 Наши контакты:</b>\n\n"
        "▪️ <b>Адрес:</b> ПГТ Ручеёк, ул., д. 1 (Выезд на дом по договоренности)\n"
        "▪️ <b>Телефон / WhatsApp:</b> +7 (991) 868-60-17\n"
        "▪️ <b>Telegram мастера:</b> @IvanMiroshnicenkoo"
    )
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_home")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_kb)
    await callback.answer()

@dp.callback_query(F.data == "back_home")
async def back_home(callback: types.CallbackQuery):
    render_url = os.getenv("RENDER_EXTERNAL_URL", "https://example.com")
    await callback.message.edit_text("Главное меню мастерской:", parse_mode="HTML", reply_markup=get_main_menu(render_url))
    await callback.answer()

# Фоновый запуск бота, пока FastAPI работает как основной веб-сервис Render
async def run_bot():
    await dp.start_polling(bot)

@app.on_event("startup")
async def startup_event():
    # Запускаем телеграм-бота в фоне при старте веб-сервера FastAPI
    asyncio.create_task(run_bot())

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("bot:app", host="0.0.0.0", port=port)