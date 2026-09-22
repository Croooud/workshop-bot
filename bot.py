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

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Токен твоего бота (лучше использовать переменные окружения, но можно вставить строку)
TOKEN = os.getenv("TOKEN", "891195735:AAG2kmk_YGK1tmF6RfrfWAX1J85MVlQ0JhA")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Инициализация FastAPI
app = FastAPI()

# Указываем папку с HTML шаблонами
templates = Jinja2Templates(directory="templates")


# --- FastAPI Маршруты для Mini App ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    # Рендерим файл index.html из папки templates
    return templates.TemplateResponse("index.html", {"request": request})


# --- Telegram Бот ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Кнопка для открытия мини-приложения
    # ЗАМЕНИ "https://tvoiservise.onrender.com" на твою реальную ссылку с Render!
    web_app_url = "https://workshop-bot-q85s.onrender.com" 
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть мини-приложение",
                    web_app=WebAppInfo(url=web_app_url)
                )
            ]
        ]
    )
    
    await message.answer(
        "Привет! Нажми кнопку ниже, чтобы открыть мини-приложение:",
        reply_markup=keyboard
    )


# --- Функция одновременного запуска бота и сервера ---

async def main():
    # Запускаем поллинг Telegram-бота в фоне
    asyncio.create_task(dp.start_polling(bot))
    
    # Запускаем FastAPI через uvicorn
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)), log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
