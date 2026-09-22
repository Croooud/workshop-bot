import asyncio
import logging
import os
import json
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
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

# --- FastAPI Маршруты ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse(request, "index.html")


# --- Telegram Бот ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Твоя ссылка на Render
    web_app_url = "https://workshop-bot-q85s.onrender.com" 
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть прайс-лист",
                    web_app=WebAppInfo(url=web_app_url)
                )
            ]
        ]
    )
    
    await message.answer(
        "👋 **Мастерская Ручеёк**\n\n"
        "Профессиональный ремонт и обслуживание компьютерной техники.\n"
        "Нажмите кнопку ниже, чтобы выбрать услуги и оформить заявку:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

# Обработчик данных, пришедших из Mini App
@dp.message(F.web_app_data)
async def web_app_data_handler(message: types.Message):
    try:
        data = json.loads(message.web_app_data.data)
        services = data.get("items", [])
        total = data.get("total", 0)

        if not services:
            await message.answer("Корзина пуста.")
            return

        receipt_text = "🧾 **Ваша заявка принята!**\n\n**Выбранные услуги:**\n"
        for idx, item in enumerate(services, 1):
            price_text = "Бесплатно" if item['price'] == 0 else f"{item['price']} ₽"
            receipt_text += f"{idx}. {item['name']} — {price_text}\n"
        
        receipt_text += f"\n💰 **Итого к оплате:** {total} ₽\n\n"
        receipt_text += "Скоро с вами свяжется мастер для уточнения деталей."

        await message.answer(receipt_text, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Error parsing web app data: {e}")
        await message.answer("Произошла ошибка при обработке заказа.")


# --- Запуск ---

async def main():
    asyncio.create_task(dp.start_polling(bot))
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)), log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
