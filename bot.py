import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import uvicorn

# Настройка логирования
logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TOKEN", "891195735:AAG2kmk_YGK1tmF6RfrfWAX1J85MVlQ0JhA")

bot = Bot(token=TOKEN)
dp = Dispatcher()

app = FastAPI()
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse(request, "index.html")


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Укажи свою актуальную ссылку с Render
    web_app_url = "https://workshop-bot-q85s.onrender.com" 
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛍 Открыть каталог магазина",
                    web_app=WebAppInfo(url=web_app_url)
                )
            ]
        ]
    )
    
    await message.answer(
        "🎮 **Добро пожаловать в игровой маркетплейс!**\n\n"
        "Огромный выбор игр, подписок и пополнений баланса. "
        "Нажми кнопку ниже, чтобы открыть каталог:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


async def main():
    asyncio.create_task(dp.start_polling(bot))
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)), log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
