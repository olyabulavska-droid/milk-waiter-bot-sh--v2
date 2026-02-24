import os
import telebot
from telebot import types

TOKEN = "8367825042:AAE8_ald1btNX8kQHu0UVscStrJBefx_HKM"

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

users = {}  # тимчасово в памʼяті (потім підключимо БД/таблицю)

def get_points(uid: int) -> int:
    return int(users.get(uid, 0))

@bot.message_handler(commands=["start"])
def start(m):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Мій баланс", callback_data="bal"))
    kb.add(types.InlineKeyboardButton("Рейтинг", callback_data="rate"))
    bot.send_message(m.chat.id, "Меню ✅", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: True)
def cb(c):
    bot.answer_callback_query(c.id)  # прибирає “Loading…”

    if c.data == "bal":
        p = get_points(c.from_user.id)
        bot.send_message(c.message.chat.id, f"Баланс: {p}")
        return

    if c.data == "rate":
        if not users:
            bot.send_message(c.message.chat.id, "Поки пусто")
            return

        sorted_users = sorted(users.items(), key=lambda x: x[1], reverse=True)
        txt = "🏆 Рейтинг\n\n"
        for i, (uid, p) in enumerate(sorted_users[:10]):
            txt += f"{i+1}. {uid} — {p}\n"
        bot.send_message(c.message.chat.id, txt)
        return

bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
