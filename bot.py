import asyncio
import logging
import os
import random
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, CallbackQuery
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List
import uvicorn

logging.basicConfig(level=logging.INFO)

# Очистка токена
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

# --- API ЭНДПОИНТ (ПРИЕМ ЗАКАЗА) ---
@app.post("/api/order")
async def create_order(order: OrderRequest):
    # Генерируем красивый номер заказа
    order_id = f"#{random.randint(10000, 99999)}"
    
    # Формируем премиальный чек с использованием цитирования (blockquote)
    receipt = f"🧾 <b>ЗАКАЗ {order_id} ПРИНЯТ</b>\n\n"
    receipt += "<blockquote>"
    
    for item in order.items:
        price_str = "Бесплатно" if item.price == 0 else f"{item.price:,} ₽".replace(',', ' ')
        receipt += f"▫️ {item.name}\n└ <i>{price_str}</i>\n\n"

    receipt += f"<b>ИТОГО: {order.total:,} ₽</b>".replace(',', ' ')
    receipt += "</blockquote>\n"
    receipt += "👨‍💻 <i>Мастер уже получил уведомление и скоро свяжется с вами для уточнения деталей.</i>"

    # Кнопки под чеком для удобства
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Написать мастеру", url="https://t.me/IvanMiroshnichenkoo")],
        [InlineKeyboardButton(text="❌ Отменить заказ", callback_data=f"cancel_order")]
    ])
    
    try:
        await bot.send_message(chat_id=order.chat_id, text=receipt, parse_mode="HTML", reply_markup=kb)
        return {"success": True}
    except Exception as e:
        logging.error(f"Telegram API Error: {str(e)}")
        return {"success": False, "error": str(e)}

# --- ЛОГИКА TELEGRAM БОТА ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    web_app_url = "https://workshop-bot-dcyv.onrender.com"
    
    # Многоуровневая клавиатура
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚡️ ОТКРЫТЬ ПРАЙС И ЗАКАЗАТЬ",
                    web_app=WebAppInfo(url=web_app_url)
                )
            ],
            [
                InlineKeyboardButton(text="📍 Контакты", callback_data="show_contacts"),
                InlineKeyboardButton(text="❓ Частые вопросы", callback_data="show_faq")
            ]
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


# Обработка нажатия на кнопку "Контакты"
@dp.callback_query(F.data == "show_contacts")
async def process_contacts(callback: CallbackQuery):
    text = (
        "📍 <b>НАШИ КОНТАКТЫ</b>\n\n"
        "<b>Адрес:</b> ПГТ Ручейк, ул., д. 1\n"
        "<b>Телефон / WhatsApp:</b> <code>+7 (991) 888-60-17</code>\n"
        "<b>Telegram:</b> @IvanMiroshnichenkoo\n\n"
        "<i>Работаем по предварительной записи. Возможен выезд на дом.</i>"
    )
    
    # Кнопка "Назад"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main")]
    ])
    
    # Меняем текущее сообщение, чтобы не спамить в чат
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# Обработка нажатия на кнопку "FAQ"
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


# Обработка возврата в главное меню
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


# Простая обработка отмены заказа-заглушка
@dp.callback_query(F.data == "cancel_order")
async def process_cancel_order(callback: CallbackQuery):
    await callback.message.edit_text("❌ <i>Заявка отменена. Если передумаете, мы всегда на связи!</i>", parse_mode="HTML")
    await callback.answer("Заказ отменен")


async def main():
    # Принудительно удаляем старый вебхук перед запуском поллинга
    await bot.delete_webhook(drop_pending_updates=True)
    
    asyncio.create_task(dp.start_polling(bot))
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)), log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
