import os
import sqlite3
import time
import telebot
from telebot import types

# ✅ ВСТАВ СВІЙ ТОКЕН (або лишай env, якщо хочеш)
TOKEN = "ВСТАВ_ТУТ_СВІЙ_ТОКЕН"

if not TOKEN or "ВСТАВ_ТУТ" in TOKEN:
    raise RuntimeError("TOKEN is missing")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# --- Налаштування ---
# Адміни (менеджери). Можеш вписати свій Telegram ID (цифри).
# Якщо не знаєш ID — тимчасово залиш пусто, тоді всі будуть мати доступ до нарахувань.
ADMIN_IDS = set()
# ADMIN_IDS = {123456789}  # приклад

# Причини нарахування
ADD_REASONS = [
    ("add_nv", 30, "Відсутність порушень (тиждень)"),
    ("add_nl", 30, "Відсутність запізнень (тиждень)"),
    ("add_pr", 2,  "Позитивний відгук"),
    ("add_spr", 5, "Супер позитивний відгук"),
    ("add_top", 5, "Продаж топ листа"),
]

# Причини зняття (приклади — скажеш свої і замінимо)
SUB_REASONS = [
    ("sub_late", -10, "Запізнення"),
    ("sub_violation", -10, "Порушення правил"),
    ("sub_complaint", -5, "Негативний відгук"),
]

# --- DB (щоб не обнулялось) ---
DB_PATH = "bot.db"

def db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    con = db()
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            uid INTEGER PRIMARY KEY,
            name TEXT,
            points INTEGER NOT NULL DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid INTEGER NOT NULL,
            delta INTEGER NOT NULL,
            reason TEXT NOT NULL,
            manager_id INTEGER NOT NULL,
            ts INTEGER NOT NULL
        )
    """)
    con.commit()
    con.close()

def upsert_user(uid: int, name: str):
    con = db()
    cur = con.cursor()
    cur.execute("INSERT INTO users(uid, name, points) VALUES(?, ?, 0) ON CONFLICT(uid) DO UPDATE SET name=excluded.name",
                (uid, name))
    con.commit()
    con.close()

def get_points(uid: int) -> int:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT points FROM users WHERE uid=?", (uid,))
    row = cur.fetchone()
    con.close()
    return int(row[0]) if row else 0

def add_points(uid: int, delta: int, reason: str, manager_id: int):
    con = db()
    cur = con.cursor()
    cur.execute("INSERT INTO users(uid, name, points) VALUES(?, ?, 0) ON CONFLICT(uid) DO NOTHING", (uid, "",))
    cur.execute("UPDATE users SET points = points + ? WHERE uid=?", (delta, uid))
    cur.execute("INSERT INTO logs(uid, delta, reason, manager_id, ts) VALUES(?,?,?,?,?)",
                (uid, delta, reason, manager_id, int(time.time())))
    con.commit()
    con.close()

def top_users(limit=10):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT uid, name, points FROM users ORDER BY points DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    con.close()
    return rows

def all_users():
    con = db()
    cur = con.cursor()
    cur.execute("SELECT uid, name, points FROM users ORDER BY name")
    rows = cur.fetchall()
    con.close()
    return rows

def is_admin(uid: int) -> bool:
    if not ADMIN_IDS:
        return True  # тимчасово всі можуть
    return uid in ADMIN_IDS

# pending action: manager_id -> (delta, reason)
pending = {}

def main_menu(for_user_id: int):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📊 Мій баланс", callback_data="bal"),
        types.InlineKeyboardButton("🏆 Рейтинг", callback_data="rate"),
    )
    if is_admin(for_user_id):
        kb.add(
            types.InlineKeyboardButton("➕ Нарахувати", callback_data="give"),
            types.InlineKeyboardButton("➖ Зняти", callback_data="take"),
        )
    return kb

def choose_reason_kb(kind: str):
    kb = types.InlineKeyboardMarkup(row_width=1)
    arr = ADD_REASONS if kind == "give" else SUB_REASONS
    for code, pts, title in arr:
        sign = "+" if pts > 0 else ""
        kb.add(types.InlineKeyboardButton(f"{sign}{pts} — {title}", callback_data=f"reason:{code}"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
    return kb

def choose_user_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    rows = all_users()
    if not rows:
        kb.add(types.InlineKeyboardButton("Поки нікого нема. Нехай співробітники натиснуть /start", callback_data="noop"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
        return kb

    for uid, name, pts in rows[:30]:  # щоб не було дуже багато
        label = name.strip() if name and name.strip() else str(uid)
        kb.add(types.InlineKeyboardButton(f"{label} (бал: {pts})", callback_data=f"to:{uid}"))

    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
    return kb

init_db()

@bot.message_handler(commands=["start"])
def start(msg):
    name = msg.from_user.full_name or ""
    upsert_user(msg.from_user.id, name)
    bot.send_message(msg.chat.id, "Меню ✅", reply_markup=main_menu(msg.from_user.id))

@bot.callback_query_handler(func=lambda c: True)
def cb(c):
    uid = c.from_user.id

    # завжди оновлюємо ім’я
    upsert_user(uid, c.from_user.full_name or "")

    if c.data == "noop":
        bot.answer_callback_query(c.id)
        return

    if c.data == "back":
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "Меню ✅", reply_markup=main_menu(uid))
        return

    if c.data == "bal":
        p = get_points(uid)
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, f"📊 Баланс: <b>{p}</b>")
        return

    if c.data == "rate":
        bot.answer_callback_query(c.id)
        rows = top_users(10)
        if not rows:
            bot.send_message(c.message.chat.id, "Поки пусто")
            return
        txt = "🏆 <b>Рейтинг</b>\n\n"
        for i, (u, name, pts) in enumerate(rows, start=1):
            label = name.strip() if name and name.strip() else str(u)
            txt += f"{i}. {label} — <b>{pts}</b>\n"
        bot.send_message(c.message.chat.id, txt)
        return

    if c.data == "give":
        if not is_admin(uid):
            bot.answer_callback_query(c.id, "Нема доступу", show_alert=True)
            return
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "➕ Обери причину нарахування:", reply_markup=choose_reason_kb("give"))
        return

    if c.data == "take":
        if not is_admin(uid):
            bot.answer_callback_query(c.id, "Нема доступу", show_alert=True)
            return
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "➖ Обери причину зняття:", reply_markup=choose_reason_kb("take"))
        return

    if c.data.startswith("reason:"):
        if not is_admin(uid):
            bot.answer_callback_query(c.id, "Нема доступу", show_alert=True)
            return

        code = c.data.split(":", 1)[1]
        all_reasons = {x[0]: (x[1], x[2]) for x in (ADD_REASONS + SUB_REASONS)}
        if code not in all_reasons:
            bot.answer_callback_query(c.id, "Невідома причина", show_alert=True)
            return

        delta, reason = all_reasons[code]
        pending[uid] = (delta, reason)

        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, f"Кому застосувати <b>{delta:+d}</b> за: <i>{reason}</i> ?", reply_markup=choose_user_kb())
        return

    if c.data.startswith("to:"):
        if not is_admin(uid):
            bot.answer_callback_query(c.id, "Нема доступу", show_alert=True)
            return
        if uid not in pending:
            bot.answer_callback_query(c.id, "Спочатку обери причину", show_alert=True)
            return

        to_uid = int(c.data.split(":", 1)[1])
        delta, reason = pending.pop(uid)

        add_points(to_uid, delta, reason, uid)
        new_balance = get_points(to_uid)

        bot.answer_callback_query(c.id, "Готово ✅")
        bot.send_message(c.message.chat.id, f"✅ Застосовано <b>{delta:+d}</b> для <code>{to_uid}</code>\nПричина: <i>{reason}</i>\nНовий баланс: <b>{new_balance}</b>")

        # повідомлення співробітнику
        try:
            manager_name = c.from_user.full_name or "Менеджер"
            bot.send_message(
                to_uid,
                f"⭐ <b>Тобі нарахували/зняли бали</b>\n\n"
                f"👤 Менеджер: {manager_name}\n"
                f"🔁 Зміна: <b>{delta:+d}</b>\n"
                f"📝 {reason}\n\n"
                f"📊 Новий баланс: <b>{new_balance}</b>"
            )
        except Exception:
            pass

        return

bot.infinity_polling()
