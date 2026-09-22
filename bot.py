import asyncio
import logging
import os
import json
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import uvicorn

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TOKEN", "891195735:AAG2kmk_YGK1tmF6RfrfWAX1J85MVlQ0JhA")
bot = Bot(token=TOKEN)
dp = Dispatcher()

app = FastAPI()
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Укажи свой актуальный URL Render
    web_app_url = "https://workshop-bot-q85s.onrender.com"
    
    # Используем ReplyKeyboardMarkup вместо InlineKeyboardMarkup
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="📱 Открыть приложение",
                    web_app=WebAppInfo(url=web_app_url)
                )
            ]
        ],
        resize_keyboard=True
    )
    
    await message.answer(
        "⚡️ **Мастерская Ручеёк**\n\n"
        "Ремонт, обслуживание и настройка компьютерной техники.\n"
        "Нажмите кнопку «📱 Открыть приложение» на клавиатуре ниже, чтобы выбрать услуги:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@dp.message(F.web_app_data)
async def web_app_data_handler(message: types.Message):
    try:
        data = json.loads(message.web_app_data.data)
        services = data.get("items", [])
        total = data.get("total", 0)

        if not services:
            return

        receipt = "📋 **НОВАЯ ЗАЯВКА**\n\n"
        for item in services:
            price_str = "Бесплатно" if item['price'] == 0 else f"{item['price']:,} ₽".replace(',', ' ')
            receipt += f"• {item['name']} — {price_str}\n"
        
        receipt += f"\n💳 **Итого: {total:,} ₽**".replace(',', ' ')
        receipt += "\n\nСпасибо! Мы получили вашу заявку. Мастер скоро свяжется с вами."

        await message.answer(receipt, parse_mode="Markdown")
        
    except Exception as e:
        logging.error(f"Error: {e}")
        await message.answer("Произошла ошибка. Попробуйте еще раз.")

async def main():
    asyncio.create_task(dp.start_polling(bot))
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)), log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
