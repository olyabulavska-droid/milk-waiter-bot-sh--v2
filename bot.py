import time
import sqlite3
import random
from datetime import datetime
import telebot
from telebot import types

# =========================
# 1) НАЛАШТУВАННЯ
# =========================
TOKEN = "8367825042:AAGJrAvcFGWWdxGWjxUXi6iuF4boYD7ZJKg"

# ТІЛЬКИ менеджери (адміни) можуть нараховувати/знімати + бачити повний рейтинг
ADMIN_IDS = {279217370, 7003021399}  # <-- впиши ID менеджерів

# Куди слати підсумок місяця (можеш лишити свій ID або зробити id групи)
MONTHLY_ANNOUNCE_CHAT_ID = 279217370

DB_PATH = "bot.db"
bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# =========================
# 2) ПРИЧИНИ (затверджені)
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
# 2.1) МАГАЗИН: 1 БОКС 50
# =========================
BOX_KEY = "secret_box_50"
BOX_TITLE = "🎁 Секретний бокс"
BOX_PRICE = 50

# Призи (відредагуй під себе)
BOX_REWARDS = [
    # (назва, вага/ймовірність)
    ("🥤 Безкоштовний напій", 20),
    ("🍰 Десерт ", 15),
    ("🍕 Страва без штату", 15),
    ("💎 +20 балів бонусом", 10),
    ("💎 +40 балів бонусом", 5),
    ("🎁 Секретний міні-подарунок", 12),
    ("😈 Нічого 😅 Але повага +100%", 15),
]

# =========================
# 3) DB
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
            updated_ts INTEGER
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
    cur.execute(
        "INSERT INTO meta(k,v) VALUES(?,?) "
        "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
        (key, value)
    )
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
    cur.execute(
        "UPDATE users SET points = points + ?, updated_ts=? WHERE uid=?",
        (delta, int(time.time()), uid)
    )
    con.commit()
    cur.execute("SELECT points FROM users WHERE uid=?", (uid,))
    row = cur.fetchone()
    con.close()
    return int(row[0]) if row else 0

def get_all_users_sorted(limit: int = 50):
    con = db()
    cur = con.cursor()
    cur.execute(
        "SELECT uid, name, username, points FROM users "
        "ORDER BY points DESC, updated_ts ASC LIMIT ?",
        (limit,)
    )
    rows = cur.fetchall()
    con.close()
    return rows

def get_all_users_for_picker(limit: int = 40):
    con = db()
    cur = con.cursor()
    cur.execute(
        "SELECT uid, name, username, points FROM users "
        "ORDER BY name COLLATE NOCASE ASC LIMIT ?",
        (limit,)
    )
    rows = cur.fetchall()
    con.close()
    return rows

def reset_points_all():
    con = db()
    cur = con.cursor()
    cur.execute("UPDATE users SET points=0")
    con.commit()
    con.close()

# =========================
# 4) МІСЯЧНЕ ЗАКРИТТЯ + ОБНУЛЕННЯ
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
# 5) UI
# =========================
def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def main_menu_inline(uid: int):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📊 Мій баланс", callback_data="act:bal"))
    kb.add(types.InlineKeyboardButton("🏆 Рейтинг", callback_data="act:rate"))
    kb.add(types.InlineKeyboardButton("🛍 Магазин", callback_data="act:shop"))
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

def shop_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(f"🛒 Купити {BOX_TITLE} — {BOX_PRICE} балів", callback_data=f"shop:buy:{BOX_KEY}"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back:menu"))
    return kb

def confirm_buy_kb(item_key: str):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Так, купую", callback_data=f"shop:confirm:{item_key}"),
        types.InlineKeyboardButton("❌ Скасувати", callback_data="shop:cancel"),
    )
    return kb

def pick_reward():
    names = [r[0] for r in BOX_REWARDS]
    weights = [r[1] for r in BOX_REWARDS]
    return random.choices(names, weights=weights, k=1)[0]

def open_box_effect(chat_id: int):
    """
    Комбо: "анімація" (імітація прогресом) + конфеті + результат
    """
    msg = bot.send_message(chat_id, "🔒 <b>Починаємо відкривати бокс...</b>\n\n⏳ [          ]")
    mid = msg.message_id

    steps = [
        "🔓 <b>Підбираю ключ...</b>\n\n⏳ [██        ]",
        "🎁 <b>Бокс тремтить...</b>\n\n⏳ [█████     ]",
        "✨ <b>Майже!</b>\n\n⏳ [████████  ]",
        "💥 <b>ВІДКРИТО!</b>\n\n⏳ [██████████]",
    ]
    for s in steps:
        time.sleep(0.7)
        try:
            bot.edit_message_text(s, chat_id, mid)
        except Exception:
            pass

    # "конфеті"
    time.sleep(0.3)
    bot.send_message(chat_id, "🎉🎉🎉🎉🎉\n✨🎊✨🎊✨🎊✨\n🎉🎉🎉🎉🎉")
    time.sleep(0.3)

# =========================
# 6) HANDLERS
# =========================
init_db()

@bot.message_handler(commands=["start"])
def start(m):
    month_reset_if_needed()

    uid = m.from_user.id
    name = (m.from_user.full_name or "").strip()
    username = (m.from_user.username or "").strip()

    upsert_user(uid, name, username)

    bot.send_message(m.chat.id, "Меню ✅", reply_markup=main_menu_inline(uid))

@bot.callback_query_handler(func=lambda c: True)
def cb(c):
    month_reset_if_needed()

    uid = c.from_user.id
    name = (c.from_user.full_name or "").strip()
    username = (c.from_user.username or "").strip()
    upsert_user(uid, name, username)

    data = c.data or ""

    # прибрати "loading"
    try:
        bot.answer_callback_query(c.id, "Ок")
    except Exception:
        pass

    if data == "noop":
        return

    # ====== БАЛАНС ======
    if data == "act:bal":
        p = get_points(uid)
        bot.send_message(c.message.chat.id, f"📊 Твій баланс: <b>{p}</b> балів", reply_markup=main_menu_inline(uid))
        return

    # ====== РЕЙТИНГ: офіціант бачить лише своє місце, адмін — весь список ======
    if data == "act:rate":
        rows = get_all_users_sorted(limit=200)
        if not rows:
            bot.send_message(c.message.chat.id, "Поки що немає учасників.", reply_markup=main_menu_inline(uid))
            return

        if is_admin(uid):
            text = "🏆 <b>Рейтинг (повний список)</b>\n\n"
            for i, (u, n, un, pts) in enumerate(rows, start=1):
                label = n or (f"@{un}" if un else str(u))
                text += f"{i}. {label} — <b>{pts}</b>\n"
            bot.send_message(c.message.chat.id, text, reply_markup=main_menu_inline(uid))
            return

        # не адмін: показуємо лише місце + сусідів
        idx = None
        for i, (u, n, un, pts) in enumerate(rows):
            if u == uid:
                idx = i
                break
        if idx is None:
            bot.send_message(c.message.chat.id, "Тебе ще нема в рейтингу. Натисни /start.", reply_markup=main_menu_inline(uid))
            return

        my_pts = rows[idx][3]
        my_place = idx + 1
        total = len(rows)

        # покажемо 1 рядок вище і 1 нижче (якщо є)
        around = []
        for j in [idx - 1, idx, idx + 1]:
            if 0 <= j < total:
                u, n, un, pts = rows[j]
                label = n or (f"@{un}" if un else str(u))
                prefix = "➡️ " if j == idx else "   "
                around.append(f"{prefix}{j+1}. {label} — <b>{pts}</b>")

        text = (
            "🏆 <b>Твій рейтинг</b>\n\n"
            f"Твоє місце: <b>{my_place}</b> з <b>{total}</b>\n"
            f"Твої бали: <b>{my_pts}</b>\n\n"
            + "\n".join(around)
        )
        bot.send_message(c.message.chat.id, text, reply_markup=main_menu_inline(uid))
        return

    # ====== МЕНЮ АДМІНА: НАРАХУВАТИ / ЗНЯТИ ======
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

        manager_label = name or (f"@{username}" if username else str(uid))

        try:
            if mode == "add":
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
            f"Готово ✅\nЗміна: <b>{delta}</b>\nПричина: <i>{title}</i>\nНовий баланс: <b>{new_balance}</b>",
            reply_markup=main_menu_inline(uid)
        )
        return

    # ====== МАГАЗИН (1 бокс за 80) + підтвердження + ефекти ======
    if data == "act:shop":
        bot.send_message(
            c.message.chat.id,
            f"🛍 <b>Магазин</b>\n\nДоступно:\n{BOX_TITLE} — <b>{BOX_PRICE}</b> балів",
            reply_markup=shop_kb()
        )
        return

    if data.startswith("shop:buy:"):
        item_key = data.split(":", 2)[2]
        if item_key != BOX_KEY:
            bot.send_message(c.message.chat.id, "Товар не знайдено.", reply_markup=main_menu_inline(uid))
            return

        p = get_points(uid)
        warn = (
            f"⚠️ <b>Підтвердження покупки</b>\n\n"
            f"Товар: {BOX_TITLE}\n"
            f"Ціна: <b>{BOX_PRICE}</b> балів\n"
            f"Твій баланс: <b>{p}</b> балів\n\n"
            f"Точно купуєш?"
        )
        bot.send_message(c.message.chat.id, warn, reply_markup=confirm_buy_kb(item_key))
        return

    if data == "shop:cancel":
        bot.send_message(c.message.chat.id, "Скасовано ✅", reply_markup=main_menu_inline(uid))
        return

    if data.startswith("shop:confirm:"):
        item_key = data.split(":", 2)[2]
        if item_key != BOX_KEY:
            bot.send_message(c.message.chat.id, "Товар не знайдено.", reply_markup=main_menu_inline(uid))
            return

        p = get_points(uid)
        if p < BOX_PRICE:
            bot.send_message(
                c.message.chat.id,
                f"❌ Недостатньо балів.\nПотрібно: <b>{BOX_PRICE}</b>\nУ тебе: <b>{p}</b>",
                reply_markup=main_menu_inline(uid)
            )
            return

        # списуємо 80
        new_balance = apply_points(uid, -BOX_PRICE)

        # ефект відкриття (анімація-прогрес + конфеті)
        open_box_effect(c.message.chat.id)

        # результат
        reward = pick_reward()

        # якщо виграв бонус-бали — додаємо
        bonus = 0
        if reward == "💎 +10 балів бонусом":
            bonus = 10
        elif reward == "💎 +20 балів бонусом":
            bonus = 20

        if bonus:
            new_balance = apply_points(uid, bonus)

        result_text = (
            f"🎁 <b>{BOX_TITLE} відкрито!</b>\n\n"
            f"✨ Тобі випало: <b>{reward}</b>\n\n"
            f"📊 Баланс зараз: <b>{new_balance}</b> балів"
        )
        bot.send_message(c.message.chat.id, result_text, reply_markup=main_menu_inline(uid))
        return

    # ====== BACK ======
    if data.startswith("back:"):
        parts = data.split(":")
        if parts[1] == "menu":
            bot.send_message(c.message.chat.id, "Меню ✅", reply_markup=main_menu_inline(uid))
            return
        if parts[1] == "reasons":
            mode = parts[2]
            bot.send_message(c.message.chat.id, "Обери причину:", reply_markup=reasons_keyboard(mode))
            return

# Запуск
print("BOT STARTED")
bot.infinity_polling()
