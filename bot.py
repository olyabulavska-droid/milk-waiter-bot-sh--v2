import os
import time
import random
import sqlite3
from datetime import datetime, date
import telebot
from telebot import types

# =========================
# 1) НАЛАШТУВАННЯ
# =========================
TOKEN = "8367825042:AAGjlc9aNW9UVuY4B8O3I06LauefECR0VtU"  # <-- встав токен
ADMIN_IDS = {279217370, 7003021399}  # <-- менеджери (адміни), numeric id

# Куди слати повідомлення менеджерам (наприклад твій id або id групи менеджерів)
MANAGER_CHAT_ID = 279217370

# Куди слати підсумок місяця (можеш той самий чат менеджерів)
MONTHLY_ANNOUNCE_CHAT_ID = 279217370

DB_PATH = "bot.db"

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# =========================
# 2) ПРИЧИНИ (ЗАТВЕРДЖЕНІ)
# =========================
REASONS_ADD = [
    ("no_violations_week",       "✅ Відсутність порушень (тиждень)", 30),
    ("no_late_week",             "⏰ Відсутність запізнень (тиждень)", 30),
    ("positive_review",          "🙂 Позитивний відгук", 2),
    ("super_review",             "🔥 Супер позитивний відгук", 5),
    ("toplist_sale",             "🏆 Продаж топ листа", 5),

    ("look_standard",            "👔 Стандарт зовнішнього вигляду", 10),
    ("menu_knowledge",           "📋 Знання позиції меню", 5),
    ("manager_task",             "✅ Виконання доручення менеджера", 10),
    ("other_department_praise",  "🌟 Похвала старших іншого підрозділу", 15),
]

REASONS_SUB = [
    ("late",               "⏰ Запізнення", 10),
    ("no_uniform",         "👕 Відсутність стандарту форми", 5),
    ("guest_complaint",    "😕 Скарги гостя", 5),
    ("russian_language",   "🗣️ Спілкування російською в залі", 20),
    ("rude_communication", "⚠️ Нетактовне спілкування", 10),
    ("rules_break",        "🚫 Порушення базових правил роботи", 5),
]

# =========================
# 3) MAX FUN: Daily + Box + Levels
# =========================
DAILY_BONUS_POINTS = 5  # щоденний бонус
SECRET_BOX_COST = 80    # ціна боксу
# ("назва", bonus_points, chance%, needs_manager_approval)
SECRET_BOX = [
    ("☕ Напійх2", 0,   25, True),
    ("🍰 Десертх2", 0, 22, True),
    ("🎯 +20 балів", 20, 22, False),
    ("🍔 Страва без штату", 0, 14, True),
    ("🚀 +40 балів", 40, 12, False),
    ("💎 JACKPOT +120 балів", 120, 5, False),
]

# Рівні (за місячними балами)
LEVELS = [
    (0,   "Новачок 🥄"),
    (30,  "Впевнений офіціант 🍽️"),
    (80,  "Профі ⭐"),
    (150, "Топ 🔥"),
    (250, "Легенда 👑"),
]

# =========================
# 4) DB
# =========================
def db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    con = db()
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            uid INTEGER PRIMARY KEY,
            name TEXT,
            username TEXT,
            points INTEGER NOT NULL DEFAULT 0,
            joined_ts INTEGER,
            updated_ts INTEGER,
            last_daily_date TEXT DEFAULT '',
            last_box_date TEXT DEFAULT '',
            last_menu_msg_id INTEGER DEFAULT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS actions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER,
            admin_id INTEGER,
            admin_name TEXT,
            target_id INTEGER,
            target_name TEXT,
            delta INTEGER,
            reason TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS meta(
            k TEXT PRIMARY KEY,
            v TEXT
        )
    """)
    con.commit()
    con.close()

def meta_get(key: str, default: str = "") -> str:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT v FROM meta WHERE k=?", (key,))
    row = cur.fetchone()
    con.close()
    return row[0] if row else default

def meta_set(key: str, value: str):
    con = db()
    cur = con.cursor()
    cur.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, value))
    con.commit()
    con.close()

def upsert_user(uid: int, name: str, username: str):
    now = int(time.time())
    con = db()
    cur = con.cursor()
    cur.execute("SELECT uid FROM users WHERE uid=?", (uid,))
    exists = cur.fetchone() is not None
    if not exists:
        cur.execute(
            "INSERT INTO users(uid,name,username,points,joined_ts,updated_ts) VALUES(?,?,?,?,?,?)",
            (uid, name, username, 0, now, now)
        )
    else:
        cur.execute(
            "UPDATE users SET name=?, username=?, updated_ts=? WHERE uid=?",
            (name, username, now, uid)
        )
    con.commit()
    con.close()

def get_user(uid: int):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT uid, name, username, points, last_daily_date, last_box_date, last_menu_msg_id FROM users WHERE uid=?", (uid,))
    row = cur.fetchone()
    con.close()
    return row

def set_last_menu_msg(uid: int, msg_id: int):
    con = db()
    cur = con.cursor()
    cur.execute("UPDATE users SET last_menu_msg_id=? WHERE uid=?", (msg_id, uid))
    con.commit()
    con.close()

def get_points(uid: int) -> int:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT points FROM users WHERE uid=?", (uid,))
    row = cur.fetchone()
    con.close()
    return int(row[0]) if row else 0

def apply_points(uid: int, delta: int) -> int:
    con = db()
    cur = con.cursor()
    cur.execute("UPDATE users SET points = points + ?, updated_ts=? WHERE uid=?", (delta, int(time.time()), uid))
    con.commit()
    cur.execute("SELECT points FROM users WHERE uid=?", (uid,))
    row = cur.fetchone()
    con.close()
    return int(row[0]) if row else 0

def log_action(admin_id, admin_name, target_id, target_name, delta, reason):
    con = db()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO actions(ts,admin_id,admin_name,target_id,target_name,delta,reason) VALUES(?,?,?,?,?,?,?)",
        (int(time.time()), admin_id, admin_name, target_id, target_name, delta, reason)
    )
    con.commit()
    con.close()

def get_all_users_sorted(limit: int = 50):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT uid, name, username, points FROM users ORDER BY points DESC, updated_ts ASC LIMIT ?", (limit,))
    rows = cur.fetchall()
    con.close()
    return rows

def get_all_users_for_picker(limit: int = 40):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT uid, name, username, points FROM users ORDER BY name COLLATE NOCASE ASC LIMIT ?", (limit,))
    rows = cur.fetchall()
    con.close()
    return rows

def reset_points_all():
    con = db()
    cur = con.cursor()
    cur.execute("UPDATE users SET points=0")
    con.commit()
    con.close()

def set_user_daily(uid: int, d: str):
    con = db()
    cur = con.cursor()
    cur.execute("UPDATE users SET last_daily_date=? WHERE uid=?", (d, uid))
    con.commit()
    con.close()

def set_user_box(uid: int, d: str):
    con = db()
    cur = con.cursor()
    cur.execute("UPDATE users SET last_box_date=? WHERE uid=?", (d, uid))
    con.commit()
    con.close()

# =========================
# 5) МІСЯЧНЕ ЗАКРИТТЯ + ОБНУЛЕННЯ
# =========================
def current_month_key():
    return datetime.now().strftime("%Y-%m")

def month_reset_if_needed():
    last = meta_get("last_reset_month", "")
    nowm = current_month_key()
    if last == "":
        meta_set("last_reset_month", nowm)
        return
    if last != nowm:
        announce_month_winner_and_reset(last)
        meta_set("last_reset_month", nowm)

def announce_month_winner_and_reset(month_key: str):
    rows = get_all_users_sorted(limit=10)

    if not rows:
        text = f"📅 <b>Підсумок місяця {month_key}</b>\n\nНемає учасників."
    else:
        winner_uid, winner_name, winner_username, winner_pts = rows[0]
        winner_label = winner_name or (f"@{winner_username}" if winner_username else str(winner_uid))

        text = f"🏆 <b>Переможець місяця {month_key}</b>\n"
        text += f"👑 {winner_label} — <b>{winner_pts}</b> балів\n\n"
        text += "📊 <b>Топ-10:</b>\n"
        for i, (uid, name, username, pts) in enumerate(rows, start=1):
            label = name or (f"@{username}" if username else str(uid))
            text += f"{i}. {label} — <b>{pts}</b>\n"

    try:
        bot.send_message(MONTHLY_ANNOUNCE_CHAT_ID, text)
    except Exception:
        pass

    reset_points_all()

# =========================
# 6) HELPERS / UI
# =========================
def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def user_label(uid: int, name: str, username: str) -> str:
    n = (name or "").strip()
    u = (username or "").strip()
    if n:
        return n
    if u:
        return f"@{u}"
    return str(uid)

def normalize_name(u):
    name = (u.full_name or "").strip()
    username = (u.username or "").strip()
    return name, username

def get_level(points: int):
    lvl = LEVELS[0][1]
    next_threshold = None
    for threshold, title in LEVELS:
        if points >= threshold:
            lvl = title
        else:
            next_threshold = threshold
            break
    return lvl, next_threshold

def main_menu_inline(uid: int):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📊 Мій баланс", callback_data="act:bal"))
    kb.add(types.InlineKeyboardButton("🏅 Мій рівень", callback_data="act:level"))
    kb.add(types.InlineKeyboardButton("🎯 Daily bonus", callback_data="act:daily"))
    kb.add(types.InlineKeyboardButton("🎁 Secret Box", callback_data="act:box"))
    kb.add(types.InlineKeyboardButton("🏆 Рейтинг", callback_data="act:rate"))
    if is_admin(uid):
        kb.add(
            types.InlineKeyboardButton("➕ Нарахувати", callback_data="act:add"),
            types.InlineKeyboardButton("➖ Зняти", callback_data="act:sub"),
        )
    return kb

def reasons_keyboard(mode: str):
    kb = types.InlineKeyboardMarkup()
    lst = REASONS_ADD if mode == "add" else REASONS_SUB
    for key, title, pts in lst:
        kb.add(types.InlineKeyboardButton(f"{title} ({pts})", callback_data=f"reason:{mode}:{key}"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back:menu"))
    return kb

def users_keyboard(mode: str, reason_key: str):
    kb = types.InlineKeyboardMarkup()
    rows = get_all_users_for_picker(limit=40)

    if not rows:
        kb.add(types.InlineKeyboardButton("Немає офіціантів. Нехай натиснуть /start", callback_data="noop"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"back:reasons:{mode}"))
        return kb

    for uid, name, username, pts in rows:
        label = name or (f"@{username}" if username else str(uid))
        kb.add(types.InlineKeyboardButton(f"{label} (бал: {pts})", callback_data=f"user:{mode}:{reason_key}:{uid}"))

    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"back:reasons:{mode}"))
    return kb

def find_reason(mode: str, reason_key: str):
    lst = REASONS_ADD if mode == "add" else REASONS_SUB
    for k, title, pts in lst:
        if k == reason_key:
            return title, pts
    return None, None

def safe_edit_menu(chat_id: int, uid: int, text: str):
    """
    Щоб чат не захаращувався — ми редагуємо одне "головне" повідомлення.
    Якщо редагування неможливе — створюємо нове і запам'ятовуємо id.
    """
    u = get_user(uid)
    last_msg_id = u[6] if u else None  # last_menu_msg_id
    kb = main_menu_inline(uid)

    if last_msg_id:
        try:
            bot.edit_message_text(text, chat_id, last_msg_id, reply_markup=kb)
            return
        except Exception:
            pass

    m = bot.send_message(chat_id, text, reply_markup=kb)
    try:
        set_last_menu_msg(uid, m.message_id)
    except Exception:
        pass

# =========================
# 7) Рейтинг логіка
# =========================
def get_rank_of_user(uid: int):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT uid, points FROM users ORDER BY points DESC, updated_ts ASC")
    rows = cur.fetchall()
    con.close()
    rank = None
    total = len(rows)
    pts = 0
    for i, (u, p) in enumerate(rows, start=1):
        if u == uid:
            rank = i
            pts = int(p or 0)
            break
    return rank, total, pts

def build_top10_text():
    rows = get_all_users_sorted(limit=10)
    if not rows:
        return "Поки що немає учасників."
    text = "🏆 <b>ТОП-10</b>\n\n"
    for i, (u, n, un, pts) in enumerate(rows, start=1):
        label = n or (f"@{un}" if un else str(u))
        text += f"{i}. {label} — <b>{pts}</b>\n"
    return text

# =========================
# 8) Daily bonus + Secret box (max)
# =========================
def today_str():
    return date.today().isoformat()

def open_secret_box(uid: int, chat_id: int, manager_label: str):
    row = get_user(uid)
    points = int(row[3]) if row else 0
    last_box = (row[5] or "") if row else ""

    if last_box == today_str():
        bot.send_message(chat_id, "🎁 Ти вже відкривав(ла) Secret Box сьогодні.\nСпробуй завтра 😉")
        return

    if points < SECRET_BOX_COST:
        bot.send_message(chat_id, f"❌ Потрібно <b>{SECRET_BOX_COST}</b> балів.\nУ тебе: <b>{points}</b>")
        return

    # списали
    apply_points(uid, -SECRET_BOX_COST)
    set_user_box(uid, today_str())

    # “анімація”
    msg = bot.send_message(chat_id, "🎁 Відкриваю бокс…")
    time.sleep(1.1)

    r = random.randint(1, 100)
    s = 0
    prize = None
    for name, bonus, chance, needs_manager in SECRET_BOX:
        s += chance
        if r <= s:
            prize = (name, bonus, needs_manager)
            break
    if not prize:
        prize = ("🎯 +10 балів", 10, False)

    name, bonus, needs_manager = prize

    if bonus > 0:
        newbal = apply_points(uid, bonus)
        bot.edit_message_text(
            f"🎉 <b>Бокс відкрито!</b>\n\n🏆 Виграш: <b>{name}</b>\n📊 Баланс: <b>{newbal}</b>",
            chat_id, msg.message_id
        )
        return

    # приз “фізичний” → просимо менеджера видати
    bot.edit_message_text(
        f"🎉 <b>Бокс відкрито!</b>\n\n🏆 Виграш: <b>{name}</b>\n\n✅ Я повідомив менеджера. Забереш у нього 🙂",
        chat_id, msg.message_id
    )
    try:
        bot.send_message(
            MANAGER_CHAT_ID,
            f"🎁 <b>Secret Box</b>\n"
            f"👤 Офіціант: <b>{manager_label}</b>\n"
            f"🏆 Виграш: <b>{name}</b>\n"
            f"📌 Видай нагороду вручну."
        )
    except Exception:
        pass

def take_daily_bonus(uid: int, chat_id: int):
    row = get_user(uid)
    last_daily = (row[4] or "") if row else ""
    if last_daily == today_str():
        bot.send_message(chat_id, "🎯 Daily bonus вже забраний сьогодні. Спробуй завтра 🙂")
        return
    set_user_daily(uid, today_str())
    newbal = apply_points(uid, DAILY_BONUS_POINTS)
    bot.send_message(chat_id, f"🎯 +<b>{DAILY_BONUS_POINTS}</b> балів!\n📊 Баланс: <b>{newbal}</b>")

# =========================
# 9) HANDLERS
# =========================
init_db()

@bot.message_handler(commands=["start"])
def start(m):
    month_reset_if_needed()
    uid = m.from_user.id
    name, username = normalize_name(m.from_user)
    upsert_user(uid, name, username)
    safe_edit_menu(m.chat.id, uid, "Меню ✅")

@bot.callback_query_handler(func=lambda c: True)
def cb(c):
    month_reset_if_needed()

    uid = c.from_user.id
    name, username = normalize_name(c.from_user)
    upsert_user(uid, name, username)
    label = user_label(uid, name, username)

    data = c.data or ""

    # прибрати “Loading…”
    try:
        bot.answer_callback_query(c.id, "Ок")
    except Exception:
        pass

    if data == "noop":
        return

    # BACK
    if data == "back:menu":
        safe_edit_menu(c.message.chat.id, uid, "Меню ✅")
        return

    if data.startswith("back:reasons:"):
        mode = data.split(":")[2]
        bot.edit_message_text(
            "Обери причину:",
            c.message.chat.id,
            c.message.message_id,
            reply_markup=reasons_keyboard(mode)
        )
        return

    # MENU ACTIONS
    if data == "act:bal":
        p = get_points(uid)
        bot.send_message(c.message.chat.id, f"📊 Твій баланс: <b>{p}</b> балів")
        return

    if data == "act:level":
        p = get_points(uid)
        lvl, nxt = get_level(p)
        if nxt is None:
            bot.send_message(c.message.chat.id, f"👑 Твій рівень: <b>{lvl}</b>\n🔥 Ти на максимумі!")
        else:
            bot.send_message(c.message.chat.id, f"🏅 Твій рівень: <b>{lvl}</b>\nДо наступного: <b>{nxt - p}</b> балів")
        return

    if data == "act:daily":
        take_daily_bonus(uid, c.message.chat.id)
        return

    if data == "act:box":
        open_secret_box(uid, c.message.chat.id, label)
        return

    if data == "act:rate":
        if is_admin(uid):
            bot.send_message(c.message.chat.id, build_top10_text())
        else:
            rank, total, pts = get_rank_of_user(uid)
            if rank is None:
                bot.send_message(c.message.chat.id, "Поки що тебе немає в рейтингу. Натисни /start 🙂")
            else:
                bot.send_message(
                    c.message.chat.id,
                    f"🏆 <b>Твоє місце:</b> {rank} з {total}\n📊 Бали: <b>{pts}</b>"
                )
        return

    if data == "act:add":
        if not is_admin(uid):
            bot.send_message(c.message.chat.id, "⛔ Тільки менеджери можуть нараховувати.")
            return
        bot.send_message(c.message.chat.id, "➕ Обери причину нарахування:", reply_markup=reasons_keyboard("add"))
        return

    if data == "act:sub":
        if not is_admin(uid):
            bot.send_message(c.message.chat.id, "⛔ Тільки менеджери можуть знімати.")
            return
        bot.send_message(c.message.chat.id, "➖ Обери причину списання:", reply_markup=reasons_keyboard("sub"))
        return

    # REASONS
    if data.startswith("reason:"):
        if not is_admin(uid):
            bot.send_message(c.message.chat.id, "⛔ Нема доступу.")
            return
        _, mode, reason_key = data.split(":", 2)
        title, pts = find_reason(mode, reason_key)
        if title is None:
            bot.send_message(c.message.chat.id, "Не знайдено причину.")
            return

        bot.send_message(
            c.message.chat.id,
            f"Кому {'нарахувати' if mode=='add' else 'зняти'} <b>{pts}</b> за:\n<i>{title}</i>?",
            reply_markup=users_keyboard(mode, reason_key)
        )
        return

    # PICK USER
    if data.startswith("user:"):
        if not is_admin(uid):
            bot.send_message(c.message.chat.id, "⛔ Нема доступу.")
            return

        _, mode, reason_key, target_uid_str = data.split(":", 3)
        target_uid = int(target_uid_str)

        title, pts = find_reason(mode, reason_key)
        if title is None:
            bot.send_message(c.message.chat.id, "Не знайдено причину.")
            return

        delta = pts if mode == "add" else -pts
        new_balance = apply_points(target_uid, delta)

        manager_label = label
        target_row = get_user(target_uid)
        t_name = target_row[1] if target_row else ""
        t_user = target_row[2] if target_row else ""
        target_label = user_label(target_uid, t_name, t_user)

        log_action(uid, manager_label, target_uid, target_label, delta, title)

        # Повідомлення офіціанту (працює тільки якщо він натиснув /start колись)
        try:
            if delta > 0:
                msg_staff = (
                    "⭐ <b>Тобі нарахували бали</b>\n\n"
                    f"👤 Менеджер: {manager_label}\n"
                    f"➕ +{pts} балів\n"
                    f"📝 {title}\n\n"
                    f"📊 Твій баланс: <b>{new_balance}</b>"
                )
            else:
                msg_staff = (
                    "⚠️ <b>Знято бали</b>\n\n"
                    f"👤 Менеджер: {manager_label}\n"
                    f"➖ -{pts} балів\n"
                    f"📝 {title}\n\n"
                    f"📊 Твій баланс: <b>{new_balance}</b>"
                )
            bot.send_message(target_uid, msg_staff)
        except Exception:
            pass

        bot.send_message(
            c.message.chat.id,
            f"✅ Готово\n"
            f"👤 {target_label}\n"
            f"Δ <b>{delta}</b>\n"
            f"📝 <i>{title}</i>\n"
            f"📊 Баланс: <b>{new_balance}</b>"
        )
        return

# =========================
# 10) RUN
# =========================
print("BOT STARTED")
bot.infinity_polling()
