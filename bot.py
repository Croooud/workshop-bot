import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List
import uvicorn

logging.basicConfig(level=logging.INFO)

# Очистка токена от скрытых символов или кавычек (частая проблема при деплое)
raw_token = os.getenv("TOKEN", "891195735:AAG2kmk_YGK1tmF6RfrfWAX1J85MVlQ0JhA")
TOKEN = raw_token.replace('"', '').replace("'", "").strip()

bot = Bot(token=TOKEN)
dp = Dispatcher()

app = FastAPI()
templates = Jinja2Templates(directory="templates")

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

@app.post("/api/order")
async def create_order(order: OrderRequest):
    receipt = "📋 <b>НОВАЯ ЗАЯВКА</b>\n\n"
    for item in order.items:
        price_str = "Бесплатно" if item.price == 0 else f"{item.price:,} ₽".replace(',', ' ')
        receipt += f"• {item.name} — {price_str}\n"

    receipt += f"\n💳 <b>Итого: {order.total:,} ₽</b>".replace(',', ' ')
    receipt += "\n\nСпасибо! Мы получили вашу заявку. Мастер скоро свяжется с вами."
    
    try:
        # Используем встроенный метод aiogram, так как он уже 100% авторизован
        await bot.send_message(chat_id=order.chat_id, text=receipt, parse_mode="HTML")
        return {"success": True}
    except Exception as e:
        logging.error(f"Error sending message: {e}")
        return {"success": False, "error": str(e)}

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    web_app_url = "https://workshop-bot-q85s.onrender.com"
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть приложение",
                    web_app=WebAppInfo(url=web_app_url)
                )
            ]
        ]
    )
    
    await message.answer(
        "⚡️ <b>Мастерская Ручеёк</b>\n\n"
        "Ремонт, обслуживание и настройка компьютерной техники.\n"
        "Нажмите кнопку ниже, чтобы выбрать услуги:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

async def main():
    asyncio.create_task(dp.start_polling(bot))
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)), log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
