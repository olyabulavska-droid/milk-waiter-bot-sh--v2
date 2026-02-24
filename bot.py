import time
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import threading

import telebot
from telebot import types

# =========================
# 1) НАЛАШТУВАННЯ
# =========================
TOKEN = "8367825042:AAGJrAvcFGWWdxGWjxUXi6iuF4boYD7ZJKg"  # <-- твій токен тут (як ти просила)

# ТІЛЬКИ менеджери можуть нараховувати/знімати
ADMIN_IDS = {279217370, 7003021399}  # <-- впиши своїх менеджерів

# Куди слати підсумок місяця (може бути твій id або id групи)
MONTHLY_ANNOUNCE_CHAT_ID = 279217370

# ===== ТИЖНЕВИЙ РЕЙТИНГ =====
WEEKLY_ANNOUNCE_CHAT_ID = 279217370  # куди слати рейтинг тижня (може бути група)
KYIV_TZ = ZoneInfo("Europe/Kyiv")
WEEKLY_WEEKDAY = 6   # 0=Пн ... 6=Нд
WEEKLY_HOUR = 22     # 20:00
WEEKLY_MINUTE = 0

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
        CREATE TABLE IF NOT EXISTS actions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER,
            admin_id INTEGER,
            admin_name TEXT,
            target_id INTEGER,
            target_name TEXT,
            delta INTEGER,
            reason_key TEXT,
            reason_title TEXT
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

def log_action(admin_id, admin_name, target_id, target_name, delta, reason_key, reason_title):
    con = db()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO actions(ts,admin_id,admin_name,target_id,target_name,delta,reason_key,reason_title) VALUES(?,?,?,?,?,?,?,?)",
        (int(time.time()), admin_id, admin_name, target_id, target_name, delta, reason_key, reason_title)
    )
    con.commit()
    con.close()

def get_actions_for_user(target_id: int, limit: int = 10):
    con = db()
    cur = con.cursor()
    cur.execute(
        "SELECT ts, delta, reason_title, admin_name FROM actions WHERE target_id=? ORDER BY ts DESC LIMIT ?",
        (target_id, limit)
    )
    rows = cur.fetchall()
    con.close()
    return rows

def get_actions_log(limit: int = 15):
    con = db()
    cur = con.cursor()
    cur.execute(
        "SELECT ts, admin_name, target_name, delta, reason_title FROM actions ORDER BY ts DESC LIMIT ?",
        (limit,)
    )
    rows = cur.fetchall()
    con.close()
    return rows


# =========================
# 4) РЕЙТИНГИ
# =========================
def label_user(name: str, username: str, uid: int) -> str:
    if name:
        return name
    if username:
        return f"@{username}"
    return str(uid)

def get_user_rank(uid: int):
    """
    Повертає (rank, total, points, label)
    """
    con = db()
    cur = con.cursor()
    cur.execute("SELECT uid, name, username, points FROM users ORDER BY points DESC, updated_ts ASC")
    rows = cur.fetchall()
    con.close()

    total = len(rows)
    if total == 0:
        return (0, 0, 0, "")

    for i, (u, name, username, pts) in enumerate(rows, start=1):
        if int(u) == int(uid):
            return (i, total, int(pts or 0), label_user(name, username, u))

    return (0, total, 0, "")

def build_leaderboard_text(limit: int = 10) -> str:
    rows = get_all_users_sorted(limit=limit)
    if not rows:
        return "Поки що немає учасників."

    text = "🏆 <b>Рейтинг (ТОП)</b>\n\n"
    for i, (u, n, un, pts) in enumerate(rows, start=1):
        label = label_user(n, un, u)
        medal = "🥇" if i == 1 else ("🥈" if i == 2 else ("🥉" if i == 3 else "•"))
        text += f"{medal} {i}. {label} — <b>{pts}</b>\n"
    return text

def build_weekly_leaderboard(days: int = 7, limit: int = 10) -> str:
    con = db()
    cur = con.cursor()
    since_ts = int(time.time()) - days * 24 * 60 * 60

    cur.execute("""
        SELECT target_id, target_name, SUM(delta) as score
        FROM actions
        WHERE ts >= ?
        GROUP BY target_id, target_name
        ORDER BY score DESC
        LIMIT ?
    """, (since_ts, limit))

    rows = cur.fetchall()
    con.close()

    if not rows:
        return f"🏆 <b>Рейтинг тижня</b>\n\nПоки що немає дій за останні {days} днів."

    text = f"🏆 <b>Рейтинг тижня</b> (останні {days} днів)\n\n"
    for i, (_, name, score) in enumerate(rows, start=1):
        medal = "🥇" if i == 1 else ("🥈" if i == 2 else ("🥉" if i == 3 else "•"))
        text += f"{medal} {i}. {name} — <b>{score}</b>\n"
    return text


# =========================
# 5) МІСЯЧНЕ ЗАКРИТТЯ + ОБНУЛЕННЯ
# =========================
def current_month_key():
    return datetime.now(KYIV_TZ).strftime("%Y-%m")

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
        winner_label = label_user(winner_name, winner_username, winner_uid)

        text = f"🏆 <b>Переможець місяця {month_key}</b>\n"
        text += f"🥇 {winner_label} — <b>{winner_pts}</b> балів\n\n"
        text += "📊 <b>Топ-10:</b>\n"
        for i, (uid, name, username, pts) in enumerate(rows, start=1):
            label = label_user(name, username, uid)
            mark = "🥇" if i == 1 else ("🥈" if i == 2 else ("🥉" if i == 3 else "•"))
            text += f"{mark} {i}. {label} — <b>{pts}</b>\n"

    try:
        bot.send_message(MONTHLY_ANNOUNCE_CHAT_ID, text)
    except Exception:
        pass

    reset_points_all()


# =========================
# 6) ТИЖНЕВИЙ ТРИГЕР (фон)
# =========================
def weekly_send_if_needed():
    now = datetime.now(KYIV_TZ)

    if now.weekday() != WEEKLY_WEEKDAY:
        return
    if not (now.hour == WEEKLY_HOUR and now.minute == WEEKLY_MINUTE):
        return

    week_key = now.strftime("%G-W%V")  # 2026-W08
    last = meta_get("last_weekly_sent", "")
    if last == week_key:
        return

    text = build_weekly_leaderboard(days=7, limit=10)
    try:
        bot.send_message(WEEKLY_ANNOUNCE_CHAT_ID, text)
    except Exception:
        pass

    meta_set("last_weekly_sent", week_key)

def start_weekly_worker():
    def loop():
        while True:
            try:
                weekly_send_if_needed()
            except Exception:
                pass
            time.sleep(30)
    threading.Thread(target=loop, daemon=True).start()


# =========================
# 7) UI
# =========================
def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def main_menu_inline(uid: int):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📊 Мій баланс", callback_data="act:bal"))
    kb.add(types.InlineKeyboardButton("🏆 Рейтинг", callback_data="act:rate"))
    kb.add(types.InlineKeyboardButton("📜 Моя історія", callback_data="act:hist"))
    kb.add(types.InlineKeyboardButton("📅 Рейтинг тижня", callback_data="act:weekly"))

    if is_admin(uid):
        kb.add(
            types.InlineKeyboardButton("➕ Нарахувати", callback_data="act:add"),
            types.InlineKeyboardButton("➖ Зняти", callback_data="act:sub"),
        )
        kb.add(types.InlineKeyboardButton("📋 Лог дій", callback_data="act:log"))
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
        label = label_user(name, username, uid)
        kb.add(types.InlineKeyboardButton(f"{label} (бал: {pts})", callback_data=f"user:{mode}:{reason_key}:{uid}"))

    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"back:reasons:{mode}"))
    return kb

def find_reason(mode: str, reason_key: str):
    lst = REASONS_ADD if mode == "add" else REASONS_SUB
    for k, title, pts in lst:
        if k == reason_key:
            return title, pts
    return None, None

# "Чистий чат": редагуємо одне повідомлення-екран
def show_screen(chat_id: int, text: str, reply_markup=None, c=None):
    if c and c.message:
        try:
            bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=c.message.message_id,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=reply_markup)


# =========================
# 8) HANDLERS
# =========================
init_db()
start_weekly_worker()

@bot.message_handler(commands=["start"])
def start(m):
    # /start не чіпаємо: просто відкриває меню
    month_reset_if_needed()
    uid = m.from_user.id
    name = (m.from_user.full_name or "").strip()
    username = (m.from_user.username or "").strip()
    upsert_user(uid, name, username)
    bot.send_message(m.chat.id, "Меню ✅", reply_markup=main_menu_inline(uid))

@bot.message_handler(func=lambda m: True, content_types=["text"])
def ignore_spam(m):
    # Ігноруємо будь-які тексти, щоб ніхто не засмічував бот
    # (всі дії тільки через кнопки + /start)
    return

@bot.callback_query_handler(func=lambda c: True)
def cb(c):
    month_reset_if_needed()

    uid = c.from_user.id
    name = (c.from_user.full_name or "").strip()
    username = (c.from_user.username or "").strip()
    upsert_user(uid, name, username)

    data = c.data or ""

    # прибрати loading
    try:
        bot.answer_callback_query(c.id)
    except Exception:
        pass

    if not c.message:
        return
    chat_id = c.message.chat.id

    if data == "noop":
        return

    if data == "back:menu":
        show_screen(chat_id, "Меню ✅", reply_markup=main_menu_inline(uid), c=c)
        return

    # ===== Баланс =====
    if data == "act:bal":
        p = get_points(uid)
        show_screen(chat_id, f"📊 Твій баланс: <b>{p}</b> балів", reply_markup=main_menu_inline(uid), c=c)
        return

    # ===== Рейтинг (офіціант: тільки своє місце / менеджер: ТОП) =====
    if data == "act:rate":
        if is_admin(uid):
            show_screen(chat_id, build_leaderboard_text(limit=10), reply_markup=main_menu_inline(uid), c=c)
            return

        rank, total, pts, label = get_user_rank(uid)
        if total == 0 or rank == 0:
            show_screen(chat_id, "Поки що немає рейтингу. Натисни /start 😊", reply_markup=main_menu_inline(uid), c=c)
            return

        text = (
            "🏆 <b>Твоє місце в рейтингу</b>\n\n"
            f"👤 {label}\n"
            f"📍 Місце: <b>{rank}</b> з <b>{total}</b>\n"
            f"⭐ Бали: <b>{pts}</b>"
        )
        show_screen(chat_id, text, reply_markup=main_menu_inline(uid), c=c)
        return

    # ===== Рейтинг тижня (видно всім) =====
    if data == "act:weekly":
        text = build_weekly_leaderboard(days=7, limit=10)
        show_screen(chat_id, text, reply_markup=main_menu_inline(uid), c=c)
        return

    # ===== Історія офіціанта =====
    if data == "act:hist":
        rows = get_actions_for_user(uid, limit=10)
        if not rows:
            show_screen(chat_id, "📜 Поки що немає дій по тобі.", reply_markup=main_menu_inline(uid), c=c)
            return
        text = "📜 <b>Моя історія (останні 10)</b>\n\n"
        for ts, delta, reason_title, admin_name in rows:
            dt = datetime.fromtimestamp(ts, KYIV_TZ).strftime("%d.%m %H:%M")
            sign = "➕" if delta > 0 else "➖"
            text += f"{dt}  {sign} <b>{abs(delta)}</b> — {reason_title}\n<i>Менеджер: {admin_name}</i>\n\n"
        show_screen(chat_id, text.strip(), reply_markup=main_menu_inline(uid), c=c)
        return

    # ===== Лог дій (для менеджера) =====
    if data == "act:log":
        if not is_admin(uid):
            show_screen(chat_id, "⛔ Доступ лише для менеджерів.", reply_markup=main_menu_inline(uid), c=c)
            return
        rows = get_actions_log(limit=15)
        if not rows:
            show_screen(chat_id, "📋 Лог порожній.", reply_markup=main_menu_inline(uid), c=c)
            return
        text = "📋 <b>Останні дії</b>\n\n"
        for ts, admin_name, target_name, delta, reason_title in rows:
            dt = datetime.fromtimestamp(ts, KYIV_TZ).strftime("%d.%m %H:%M")
            sign = "➕" if delta > 0 else "➖"
            text += f"{dt}  {admin_name} → {target_name}\n{sign} <b>{abs(delta)}</b> — {reason_title}\n\n"
        show_screen(chat_id, text.strip(), reply_markup=main_menu_inline(uid), c=c)
        return

    # ===== Нарахувати / Зняти =====
    if data == "act:add":
        if not is_admin(uid):
            show_screen(chat_id, "⛔ Тільки менеджери можуть нараховувати.", reply_markup=main_menu_inline(uid), c=c)
            return
        show_screen(chat_id, "➕ Обери причину нарахування:", reply_markup=reasons_keyboard("add"), c=c)
        return

    if data == "act:sub":
        if not is_admin(uid):
            show_screen(chat_id, "⛔ Тільки менеджери можуть знімати.", reply_markup=main_menu_inline(uid), c=c)
            return
        show_screen(chat_id, "➖ Обери причину списання:", reply_markup=reasons_keyboard("sub"), c=c)
        return

    # ===== Вибір причини =====
    if data.startswith("reason:"):
        if not is_admin(uid):
            show_screen(chat_id, "⛔ Нема доступу.", reply_markup=main_menu_inline(uid), c=c)
            return

        _, mode, reason_key = data.split(":", 2)
        title, pts = find_reason(mode, reason_key)
        if title is None:
            show_screen(chat_id, "Не знайдено причину.", reply_markup=main_menu_inline(uid), c=c)
            return

        show_screen(
            chat_id,
            f"Кому {'нарахувати' if mode=='add' else 'зняти'} <b>{pts}</b> за:\n<i>{title}</i> ?",
            reply_markup=users_keyboard(mode, reason_key),
            c=c
        )
        return

    # ===== Вибір офіціанта =====
    if data.startswith("user:"):
        if not is_admin(uid):
            show_screen(chat_id, "⛔ Нема доступу.", reply_markup=main_menu_inline(uid), c=c)
            return

        _, mode, reason_key, target_uid_str = data.split(":", 3)
        target_uid = int(target_uid_str)

        title, pts = find_reason(mode, reason_key)
        if title is None:
            show_screen(chat_id, "Не знайдено причину.", reply_markup=main_menu_inline(uid), c=c)
            return

        delta = pts if mode == "add" else -pts
        new_balance = apply_points(target_uid, delta)

        manager_label = label_user(name, username, uid)

        # ім'я цільового
        target_label = str(target_uid)
        for (u, n, un, _) in get_all_users_sorted(limit=300):
            if int(u) == int(target_uid):
                target_label = label_user(n, un, u)
                break

        log_action(uid, manager_label, target_uid, target_label, delta, reason_key, title)

        # повідомлення офіціанту (працює, якщо він натискав /start)
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

        show_screen(
            chat_id,
            f"✅ <b>Готово</b>\n\n"
            f"👤 {target_label}\n"
            f"{'➕' if delta>0 else '➖'} <b>{abs(delta)}</b>\n"
            f"📝 <i>{title}</i>\n"
            f"📊 Новий баланс: <b>{new_balance}</b>",
            reply_markup=main_menu_inline(uid),
            c=c
        )
        return

    # ===== Back до причин =====
    if data.startswith("back:reasons:"):
        mode = data.split(":")[-1]
        show_screen(chat_id, "Обери причину:", reply_markup=reasons_keyboard(mode), c=c)
        return

    # fallback
    show_screen(chat_id, "Меню ✅", reply_markup=main_menu_inline(uid), c=c)


print("BOT STARTED")
bot.infinity_polling()
