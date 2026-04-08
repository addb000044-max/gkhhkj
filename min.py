#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import asyncio
import os
import sqlite3
import random
import threading
import re
import json
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from typing import Optional, Dict, Set, Tuple, List
from collections import defaultdict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    filters,
    ContextTypes,
    JobQueue,
)
from telegram.constants import ParseMode
from deep_translator import GoogleTranslator

# -------------------- إعدادات التسجيل --------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# -------------------- Configuration --------------------
BOT_TOKEN = "8703594245:AAGLI_i8D1oWEopqypRfecr8o6JHNpUXiak"
REQUIRED_CHANNEL_USERNAME = "arinasaa"
REQUIRED_CHANNEL_INVITE = "https://t.me/arinasaa"
REQUIRED_CHAT_ID = None
SUPERVISION_CHANNEL = -1003818028273
MAINTENANCE_CHANNEL = -1003818028273
BOT_USERNAME = "arinasabot"
SERVER_NAME = os.environ.get("SERVER_NAME", "unknown")

# Premium file
PRIVATE_CHANNEL_ID = -1003818028273
TARGET_MESSAGE_ID = 106
PREMIUM_FILE_PRICE = 1

# GitHub Gist settings
GIST_ID = "b998f8c8e46d75ab05007ac85fc25264"
GITHUB_TOKEN = "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"
GIST_URL = f"https://api.github.com/gists/{GIST_ID}"

# الإيموجيات المسموح باستخدامها في البوت (ذهبية)
ALLOWED_EMOJIS = {'🪄', '🐥', '🚧', '🟡', '⭐', '🔔', '🪝', '🎫', '💫', '✨', '🌟', '⚡', '☀️', '🐠', '🏆', '💰', '💡', '👑', '🔐'}
BAD_EMOJIS = {'💀', '👹', '👺', '🤡', '💩', '🔫', '🗡️', '⚔️', '🩸', '❤️‍🔥', '💔', '🖤', '🏴', '❌', '⛔'}

# تتبع عدد الرسائل المتكررة
user_message_count: Dict[int, Dict[str, int]] = {}
USER_SPAM_LIMIT = 2
SPAM_TIMEFRAME = 5

# -------------------- قائمة الرسائل في القناة (للاستخدام الدوري) --------------------
CHANNEL_MESSAGES = [221, 222, 223, 224, 225, 226, 227, 228, 232, 234]

# -------------------- قاعدة البيانات المحلية (SQLite) --------------------
conn = sqlite3.connect('bot_data.db', check_same_thread=False)
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    lang TEXT DEFAULT 'en',
    gems INTEGER DEFAULT 0,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    verified INTEGER DEFAULT 0,
    warned_disclaimer INTEGER DEFAULT 0,
    last_quote_sent TIMESTAMP,
    group_id INTEGER DEFAULT 0,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    lang_set INTEGER DEFAULT 0
)''')
c.execute('''CREATE TABLE IF NOT EXISTS referrals (
    referrer_id INTEGER,
    referred_id INTEGER UNIQUE,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    rewarded INTEGER DEFAULT 0
)''')
c.execute('''CREATE TABLE IF NOT EXISTS subscriptions (
    user_id INTEGER,
    service TEXT,
    expiry TIMESTAMP,
    PRIMARY KEY (user_id, service)
)''')
c.execute('''CREATE TABLE IF NOT EXISTS last_quote_sent_global (
    id INTEGER PRIMARY KEY DEFAULT 1,
    last_sent TIMESTAMP,
    current_index INTEGER DEFAULT 0
)''')
conn.commit()

# -------------------- مسح جميع البيانات القديمة (بداية جديدة) --------------------
def reset_all_data():
    logger.warning("⚠️ RESETTING ALL DATA - Starting fresh!")
    c.execute("DELETE FROM users")
    c.execute("DELETE FROM referrals")
    c.execute("DELETE FROM subscriptions")
    c.execute("DELETE FROM last_quote_sent_global")
    conn.commit()
    if GIST_ID and GITHUB_TOKEN:
        try:
            empty_files = {
                "users.json": {"content": "[]"},
                "referrals.json": {"content": "[]"},
                "subscriptions.json": {"content": "{}"},
                "last_quote_sent_global.json": {"content": "{\"last_sent\": null, \"current_index\": 0}"}
            }
            data = {"files": empty_files}
            headers = {"Authorization": f"token {GITHUB_TOKEN}"}
            resp = requests.patch(GIST_URL, headers=headers, json=data, timeout=10)
            if resp.status_code in (200, 201):
                logger.info("Gist reset to empty state.")
            else:
                logger.error(f"Failed to reset Gist: {resp.status_code}")
        except Exception as e:
            logger.error(f"Error resetting Gist: {e}")

# -------------------- تم تعطيل مسح البيانات التلقائي --------------------
# لا يتم استدعاء reset_all_data() تلقائياً الآن للحفاظ على البيانات

# -------------------- مزامنة جميع البيانات مع GitHub Gist --------------------
def load_all_from_gist():
    if not GIST_ID or not GITHUB_TOKEN:
        logger.warning("GIST_ID or GITHUB_TOKEN not set. Using local DB only.")
        return
    try:
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}
        resp = requests.get(GIST_URL, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            files = data.get("files", {})
            if "users.json" in files:
                users = json.loads(files["users.json"]["content"])
                c.execute("DELETE FROM users")
                for u in users:
                    c.execute("INSERT INTO users (user_id, lang, gems, first_seen, verified, warned_disclaimer, last_quote_sent, group_id, last_activity, lang_set) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                              (u["user_id"], u.get("lang", "en"), u.get("gems", 0), u.get("first_seen", datetime.now().isoformat()),
                               u.get("verified", 0), u.get("warned_disclaimer", 0), u.get("last_quote_sent"), u.get("group_id", 0), u.get("last_activity", datetime.now().isoformat()), u.get("lang_set", 0)))
            if "referrals.json" in files:
                refs = json.loads(files["referrals.json"]["content"])
                c.execute("DELETE FROM referrals")
                for r in refs:
                    c.execute("INSERT INTO referrals (referrer_id, referred_id, timestamp, rewarded) VALUES (?, ?, ?, ?)",
                              (r["referrer_id"], r["referred_id"], r["timestamp"], r.get("rewarded", 0)))
            if "subscriptions.json" in files:
                subs = json.loads(files["subscriptions.json"]["content"])
                c.execute("DELETE FROM subscriptions")
                for user_id, services in subs.items():
                    for service, expiry in services.items():
                        c.execute("INSERT INTO subscriptions (user_id, service, expiry) VALUES (?, ?, ?)",
                                  (int(user_id), service, expiry))
            if "last_quote_sent_global.json" in files:
                lq = json.loads(files["last_quote_sent_global.json"]["content"])
                c.execute("DELETE FROM last_quote_sent_global")
                c.execute("INSERT INTO last_quote_sent_global (id, last_sent, current_index) VALUES (1, ?, ?)",
                          (lq.get("last_sent"), lq.get("current_index", 0)))
            conn.commit()
            logger.info("Loaded all data from Gist")
    except Exception as e:
        logger.error(f"Failed to load from Gist: {e}")

def save_all_to_gist():
    if not GIST_ID or not GITHUB_TOKEN:
        return
    try:
        c.execute("SELECT user_id, lang, gems, first_seen, verified, warned_disclaimer, last_quote_sent, group_id, last_activity, lang_set FROM users")
        users = [{"user_id": row[0], "lang": row[1], "gems": row[2], "first_seen": row[3],
                  "verified": row[4], "warned_disclaimer": row[5], "last_quote_sent": row[6], "group_id": row[7], "last_activity": row[8], "lang_set": row[9]} for row in c.fetchall()]
        users_json = json.dumps(users, indent=2, default=str)
        
        c.execute("SELECT referrer_id, referred_id, timestamp, rewarded FROM referrals")
        refs = [{"referrer_id": row[0], "referred_id": row[1], "timestamp": row[2], "rewarded": row[3]} for row in c.fetchall()]
        refs_json = json.dumps(refs, indent=2, default=str)
        
        c.execute("SELECT user_id, service, expiry FROM subscriptions")
        subs = defaultdict(dict)
        for row in c.fetchall():
            subs[str(row[0])][row[1]] = row[2]
        subs_json = json.dumps(subs, indent=2, default=str)
        
        c.execute("SELECT last_sent, current_index FROM last_quote_sent_global WHERE id=1")
        row = c.fetchone()
        lq = {"last_sent": row[0] if row else None, "current_index": row[1] if row else 0}
        lq_json = json.dumps(lq, indent=2, default=str)

        files = {
            "users.json": {"content": users_json},
            "referrals.json": {"content": refs_json},
            "subscriptions.json": {"content": subs_json},
            "last_quote_sent_global.json": {"content": lq_json}
        }
        data = {"files": files}
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}
        resp = requests.patch(GIST_URL, headers=headers, json=data, timeout=10)
        if resp.status_code in (200, 201):
            logger.info("Saved all data to Gist")
        else:
            logger.error(f"Failed to save to Gist: {resp.status_code}")
    except Exception as e:
        logger.error(f"Error saving to Gist: {e}")

# -------------------- دوال قاعدة البيانات --------------------
def add_user(user_id: int, referrer_id: Optional[int] = None):
    c.execute("INSERT OR IGNORE INTO users (user_id, lang_set) VALUES (?, 0)", (user_id,))
    conn.commit()
    if referrer_id and referrer_id != user_id:
        c.execute("SELECT user_id FROM users WHERE user_id = ?", (referrer_id,))
        if c.fetchone():
            c.execute("SELECT referred_id FROM referrals WHERE referred_id = ?", (user_id,))
            if not c.fetchone():
                c.execute("INSERT INTO referrals (referrer_id, referred_id, timestamp, rewarded) VALUES (?, ?, ?, 0)",
                          (referrer_id, user_id, datetime.now().isoformat()))
                conn.commit()
                save_all_to_gist()
                return True
    save_all_to_gist()
    return False

def check_and_reward_referral(user_id: int):
    c.execute("SELECT referrer_id, rewarded FROM referrals WHERE referred_id = ?", (user_id,))
    row = c.fetchone()
    if row and row[1] == 0:
        referrer_id = row[0]
        c.execute("UPDATE users SET gems = gems + 2 WHERE user_id = ?", (referrer_id,))
        c.execute("UPDATE referrals SET rewarded = 1 WHERE referred_id = ?", (user_id,))
        conn.commit()
        save_all_to_gist()
        return referrer_id
    return None

def get_user_gems(user_id: int) -> int:
    c.execute("SELECT gems FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    return row[0] if row else 0

def deduct_gems(user_id: int, gems: int) -> bool:
    current = get_user_gems(user_id)
    if current >= gems:
        c.execute("UPDATE users SET gems = gems - ? WHERE user_id = ?", (gems, user_id))
        conn.commit()
        save_all_to_gist()
        return True
    return False

def add_gems(user_id: int, gems: int):
    c.execute("UPDATE users SET gems = gems + ? WHERE user_id = ?", (gems, user_id))
    conn.commit()
    save_all_to_gist()

def set_user_lang(user_id: int, lang: str, manual: bool = False):
    c.execute("UPDATE users SET lang = ?, lang_set = ? WHERE user_id = ?", (lang, 1 if manual else 0, user_id))
    conn.commit()
    save_all_to_gist()

def get_user_lang_db(user_id: int) -> str:
    c.execute("SELECT lang, lang_set FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if row:
        return row[0]
    return 'en'

def is_lang_manually_set(user_id: int) -> bool:
    c.execute("SELECT lang_set FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    return row[0] == 1 if row else False

def set_user_verified(user_id: int):
    c.execute("UPDATE users SET verified = 1 WHERE user_id = ?", (user_id,))
    c.execute("UPDATE users SET gems = gems + 2 WHERE user_id = ?", (user_id,))
    conn.commit()
    referrer = check_and_reward_referral(user_id)
    if referrer:
        try:
            asyncio.create_task(send_referral_notification(referrer))
        except:
            pass
    lang = get_user_lang_db(user_id)
    asyncio.create_task(send_welcome_bonus_notification(user_id, lang))
    save_all_to_gist()

def is_user_verified(user_id: int) -> bool:
    c.execute("SELECT verified FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    return row[0] == 1 if row else False

def has_seen_disclaimer(user_id: int) -> bool:
    c.execute("SELECT warned_disclaimer FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    return row[0] == 1 if row else False

def set_disclaimer_seen(user_id: int):
    c.execute("UPDATE users SET warned_disclaimer = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    save_all_to_gist()

def has_subscription(user_id: int, service: str) -> bool:
    c.execute("SELECT expiry FROM subscriptions WHERE user_id = ? AND service = ?", (user_id, service))
    row = c.fetchone()
    if row:
        expiry = datetime.fromisoformat(row[0])
        if expiry > datetime.now():
            return True
        else:
            c.execute("DELETE FROM subscriptions WHERE user_id = ? AND service = ?", (user_id, service))
            conn.commit()
            save_all_to_gist()
    return False

def add_subscription(user_id: int, service: str, days: int):
    expiry = (datetime.now() + timedelta(days=days)).isoformat()
    c.execute("INSERT OR REPLACE INTO subscriptions (user_id, service, expiry) VALUES (?, ?, ?)",
              (user_id, service, expiry))
    conn.commit()
    save_all_to_gist()

def update_last_activity(user_id: int):
    c.execute("UPDATE users SET last_activity = ? WHERE user_id = ?", (datetime.now().isoformat(), user_id))
    conn.commit()
    save_all_to_gist()

def get_users_for_quote() -> List[int]:
    c.execute("SELECT user_id FROM users WHERE verified=1")
    return [row[0] for row in c.fetchall()]

def get_last_quote_sent_time() -> Optional[datetime]:
    c.execute("SELECT last_sent FROM last_quote_sent_global WHERE id=1")
    row = c.fetchone()
    if row and row[0]:
        return datetime.fromisoformat(row[0])
    return None

def set_last_quote_sent_time(dt: datetime):
    c.execute("UPDATE last_quote_sent_global SET last_sent=? WHERE id=1", (dt.isoformat(),))
    conn.commit()
    save_all_to_gist()

def get_current_quote_index() -> int:
    c.execute("SELECT current_index FROM last_quote_sent_global WHERE id=1")
    row = c.fetchone()
    return row[0] if row else 0

def set_current_quote_index(idx: int):
    c.execute("UPDATE last_quote_sent_global SET current_index=? WHERE id=1", (idx,))
    conn.commit()
    save_all_to_gist()

async def send_welcome_bonus_notification(user_id: int, lang: str):
    try:
        chat = await application.bot.get_chat(PRIVATE_CHANNEL_ID)
        await chat.copy_message(chat_id=user_id, message_id=235)
    except Exception as e:
        logger.error(f"Welcome bonus copy failed for {user_id}: {e}")
        msg = await get_localized_text("🎉 Welcome bonus! You received 2 🔸 as a gift! Use them to buy translation service or premium file.", lang)
        await application.bot.send_message(user_id, msg, parse_mode=ParseMode.MARKDOWN)

async def send_weekly_reward(context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now().weekday()
    if today != 6:
        return
    selected_group = random.randint(0, 3)
    c.execute("SELECT user_id FROM users WHERE verified=1 AND group_id=?", (selected_group,))
    users = c.fetchall()
    for (uid,) in users:
        c.execute("UPDATE users SET gems = gems + 2 WHERE user_id=?", (uid,))
    conn.commit()
    save_all_to_gist()
    for (uid,) in users:
        lang = get_user_lang_db(uid)
        msg = await get_localized_text(f"🎉 Weekly reward! Your group (Group {selected_group+1}) won 2 🔸 each! Congratulations!", lang)
        try:
            await context.bot.send_message(uid, msg, parse_mode=ParseMode.MARKDOWN)
        except:
            pass
    logger.info(f"Weekly reward sent to group {selected_group+1}")

async def send_daily_quote(context: ContextTypes.DEFAULT_TYPE):
    last_sent = get_last_quote_sent_time()
    now = datetime.now()
    if last_sent and now - last_sent < timedelta(hours=26):
        return
    users = get_users_for_quote()
    if not users:
        return
    current_index = get_current_quote_index()
    message_id = CHANNEL_MESSAGES[current_index % len(CHANNEL_MESSAGES)]
    new_index = (current_index + 1) % len(CHANNEL_MESSAGES)
    for uid in users:
        try:
            await context.bot.copy_message(chat_id=uid, from_chat_id=PRIVATE_CHANNEL_ID, message_id=message_id)
        except Exception as e:
            logger.error(f"Failed to copy message {message_id} to {uid}: {e}")
    set_last_quote_sent_time(now)
    set_current_quote_index(new_index)
    logger.info(f"Sent periodic message {message_id} to {len(users)} users (next index {new_index})")

async def assign_groups():
    c.execute("SELECT user_id FROM users WHERE group_id=0")
    users = c.fetchall()
    if not users:
        return
    random.shuffle(users)
    groups = defaultdict(list)
    for i, (uid,) in enumerate(users):
        group = i % 4
        groups[group].append(uid)
    for group, uids in groups.items():
        for uid in uids:
            c.execute("UPDATE users SET group_id=? WHERE user_id=?", (group+1, uid))
    conn.commit()
    save_all_to_gist()
    logger.info("Assigned groups to users")

# -------------------- Translation --------------------
async def translate_text(text: str, target_lang: str, source_lang: str = 'auto') -> Optional[str]:
    if target_lang in ['zh-cn', 'zh', 'he', 'iw']:
        return None
    try:
        translator = GoogleTranslator(source=source_lang, target=target_lang)
        return translator.translate(text)
    except Exception as e:
        logger.error(f"Translation error: {e}")
        return None

def get_user_lang(update: Update) -> str:
    return update.effective_user.language_code or 'en'

# -------------------- Localization --------------------
_localization_cache: Dict[Tuple[str, str], str] = {}

async def get_localized_text(original: str, target_lang: str) -> str:
    if target_lang == 'en':
        return original
    if target_lang in ['zh-cn', 'zh', 'he', 'iw']:
        return original + " (Translation to this language is not supported)"
    cache_key = (original, target_lang)
    if cache_key in _localization_cache:
        return _localization_cache[cache_key]
    translated = await translate_text(original, target_lang, source_lang='en')
    if translated:
        _localization_cache[cache_key] = translated
        return translated
    return original + " (auto-translated from English)"

# -------------------- قائمة اللغات --------------------
LANGUAGE_FLAGS = {}
SUPPORTED_LANGS = []

languages_list_final = [
    ("🇩🇿", "العربية", "ar"),
    ("🇬🇧", "English", "en"),
    ("🇫🇷", "Français", "fr"),
    ("🇪🇸", "Español", "es"),
    ("🇩🇪", "Deutsch", "de"),
    ("🇮🇹", "Italiano", "it"),
    ("🇵🇹", "Português", "pt"),
    ("🇷🇺", "Русский", "ru"),
    ("🇨🇳", "中文", "zh-cn"),
    ("🇮🇱", "עברית", "he"),
    ("🇯🇵", "日本語", "ja"),
    ("🇰🇷", "한국어", "ko"),
    ("🇹🇷", "Türkçe", "tr"),
    ("🇮🇷", "فارسی", "fa"),
    ("🇮🇳", "हिन्दी", "hi"),
    ("🇧🇩", "বাংলা", "bn"),
    ("🇵🇰", "اردو", "ur"),
    ("🇬🇷", "Ελληνικά", "el"),
    ("🇹🇭", "ไทย", "th"),
    ("🇻🇳", "Tiếng Việt", "vi"),
    ("🇮🇩", "Bahasa Indonesia", "id"),
    ("🇲🇾", "Bahasa Melayu", "ms"),
    ("🇳🇱", "Nederlands", "nl"),
    ("🇸🇪", "Svenska", "sv"),
    ("🇳🇴", "Norsk", "no"),
    ("🇩🇰", "Dansk", "da"),
    ("🇫🇮", "Suomi", "fi"),
    ("🇵🇱", "Polski", "pl"),
    ("🇨🇿", "Čeština", "cs"),
    ("🇸🇰", "Slovenčina", "sk"),
    ("🇭🇺", "Magyar", "hu"),
    ("🇷🇴", "Română", "ro"),
    ("🇧🇬", "Български", "bg"),
    ("🇷🇸", "Српски", "sr"),
    ("🇭🇷", "Hrvatski", "hr"),
    ("🇸🇮", "Slovenščina", "sl"),
    ("🇺🇦", "Українська", "uk"),
    ("🇧🇾", "Беларуская", "be"),
    ("🇱🇹", "Lietuvių", "lt"),
    ("🇱🇻", "Latviešu", "lv"),
    ("🇪🇪", "Eesti", "et"),
    ("🇬🇪", "ქართული", "ka"),
    ("🇦🇲", "Հայերեն", "hy"),
    ("🇦🇿", "Azərbaycan dili", "az"),
    ("🇰🇿", "Қазақ тілі", "kk"),
    ("🇺🇿", "O‘zbek tili", "uz"),
    ("🇹🇯", "тоҷикӣ", "tg"),
    ("🇰🇬", "Кыргызча", "ky"),
    ("🇲🇳", "Монгол хэл", "mn"),
    ("🇳🇵", "नेपाली", "ne"),
    ("🇱🇰", "සිංහල", "si"),
    ("🇲🇲", "မြန်မာဘာသာ", "my"),
    ("🇰🇭", "ខ្មែរ", "km"),
    ("🇱🇦", "ລາວ", "lo"),
    ("🇸🇴", "Soomaali", "so"),
    ("🇰🇪", "Kiswahili", "sw"),
    ("🇲🇬", "Malagasy", "mg"),
    ("🇦🇱", "Shqip", "sq"),
    ("🇲🇹", "Malti", "mt"),
    ("🇮🇸", "Íslenska", "is"),
    ("🇮🇪", "Gaeilge", "ga"),
    ("🇦🇩", "Català", "ca"),
    ("🇵🇾", "Avañe'ẽ", "gn"),
    ("🇵🇪", "Runa Simi", "qu"),
    ("🇿🇼", "chiShona", "sn"),
    ("🇱🇸", "Sesotho", "st"),
    ("🇳🇬", "Hausa", "ha"),
    ("🇬🇭", "Akan", "ak"),
    ("🇲🇱", "Bambara", "bm"),
    ("🇭🇹", "Kreyòl Ayisyen", "ht"),
    ("🇦🇫", "پښتو", "ps"),
    ("🇹🇲", "Türkmen dili", "tk"),
    ("🇱🇺", "Lëtzebuergesch", "lb"),
    ("🇲🇰", "Македонски", "mk"),
    ("🇧🇦", "Bosanski", "bs"),
    ("🇼🇸", "Gagana Samoa", "sm"),
    ("🇲🇻", "ދިވެހި", "dv"),
    ("🇪🇷", "ትግርኛ", "ti"),
    ("🇳🇿", "Māori", "mi")
]

for flag, name, code in languages_list_final:
    LANGUAGE_FLAGS[code] = flag
    SUPPORTED_LANGS.append((code, name))

# قاموس سريع لرموز اللغات (أحرف صغيرة)
LANG_CODES = {code.lower(): code for code, _ in SUPPORTED_LANGS}
# إضافة بعض الاختصارات الشائعة
LANG_CODES['ar'] = 'ar'
LANG_CODES['en'] = 'en'
LANG_CODES['fr'] = 'fr'
LANG_CODES['es'] = 'es'
LANG_CODES['de'] = 'de'
LANG_CODES['it'] = 'it'
LANG_CODES['pt'] = 'pt'
LANG_CODES['ru'] = 'ru'
LANG_CODES['ja'] = 'ja'
LANG_CODES['ko'] = 'ko'
LANG_CODES['tr'] = 'tr'
LANG_CODES['fa'] = 'fa'
LANG_CODES['hi'] = 'hi'
LANG_CODES['ur'] = 'ur'
LANG_CODES['el'] = 'el'
LANG_CODES['th'] = 'th'
LANG_CODES['vi'] = 'vi'
LANG_CODES['id'] = 'id'
LANG_CODES['ms'] = 'ms'
LANG_CODES['nl'] = 'nl'
LANG_CODES['sv'] = 'sv'
LANG_CODES['pl'] = 'pl'
LANG_CODES['cs'] = 'cs'
LANG_CODES['hu'] = 'hu'
LANG_CODES['ro'] = 'ro'
LANG_CODES['uk'] = 'uk'
LANG_CODES['bg'] = 'bg'
LANG_CODES['sr'] = 'sr'
LANG_CODES['hr'] = 'hr'
LANG_CODES['sl'] = 'sl'
LANG_CODES['sk'] = 'sk'
LANG_CODES['da'] = 'da'
LANG_CODES['no'] = 'no'
LANG_CODES['fi'] = 'fi'

COLS = 7
ROWS_PER_PAGE = 3
LANGUAGES_PER_PAGE = COLS * ROWS_PER_PAGE
LANGUAGE_PAGES = []
for i in range(0, len(SUPPORTED_LANGS), LANGUAGES_PER_PAGE):
    LANGUAGE_PAGES.append(SUPPORTED_LANGS[i:i + LANGUAGES_PER_PAGE])

# -------------------- لوحة المفاتيح الرئيسية --------------------
async def get_main_keyboard(lang: str) -> ReplyKeyboardMarkup:
    my_account = await get_localized_text("My Account", lang)
    buy_trans = await get_localized_text(f"Buy Translation (2 🔸 / 24 days)", lang)
    get_prem = await get_localized_text(f"Get Premium File (1 🔸)", lang)
    change_lang = await get_localized_text("🔁 Change Language", lang)
    buttons = [
        [my_account],
        [buy_trans],
        [get_prem],
        [change_lang]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

# -------------------- عرض لوحة مفاتيح اللغات --------------------
async def get_language_keyboard(page: int, lang: str) -> ReplyKeyboardMarkup:
    current_page = LANGUAGE_PAGES[page]
    keyboard = []
    row = []
    for idx, (code, _) in enumerate(current_page):
        flag = LANGUAGE_FLAGS.get(code, '🏳️')
        row.append(KeyboardButton(flag))
        if len(row) == COLS or idx == len(current_page) - 1:
            keyboard.append(row)
            row = []
    nav_row = [
        KeyboardButton("◀️"),
        KeyboardButton("▶️"),
        KeyboardButton("⤴️")
    ]
    keyboard.append(nav_row)
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# -------------------- CAPTCHA --------------------
def generate_captcha() -> tuple:
    a = random.randint(2, 9)
    b = random.randint(2, 9)
    answer = str(a + b)
    question = f"🔐 **Verification required**\n\nWhat is {a} + {b}?\n(Reply with the number only)"
    return question, answer

async def send_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang_db(update.effective_user.id)
    question, answer = generate_captcha()
    localized_question = await get_localized_text(question, lang)
    context.user_data['captcha_answer'] = answer
    await update.message.reply_text(localized_question, parse_mode=ParseMode.MARKDOWN)

# -------------------- Subscription check --------------------
async def check_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    global REQUIRED_CHAT_ID
    if REQUIRED_CHAT_ID is None:
        try:
            chat = await context.bot.get_chat(f"@{REQUIRED_CHANNEL_USERNAME}")
            REQUIRED_CHAT_ID = chat.id
            logger.info(f"Resolved channel @{REQUIRED_CHANNEL_USERNAME} to chat ID: {REQUIRED_CHAT_ID}")
        except Exception as e:
            logger.error(f"Failed to resolve channel username: {e}")
            return False
    try:
        member = await context.bot.get_chat_member(chat_id=REQUIRED_CHAT_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Subscription check error for user {user_id}: {e}")
        return False

async def subscription_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    join_text = await get_localized_text("🚧 Join Channel", lang)
    joined_text = await get_localized_text("🐥 I've joined", lang)
    msg_text = await get_localized_text(
        f"**Access Required**\n\nYou must join the channel to use this bot.\nAfter joining, click the button below.",
        lang
    )
    keyboard = [
        [InlineKeyboardButton(join_text, url=REQUIRED_CHANNEL_INVITE)],
        [InlineKeyboardButton(joined_text, callback_data="check_sub")]
    ]
    await update.message.reply_text(
        msg_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

# -------------------- Progress animation --------------------
async def progress_bar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    frames = ["🪄", "✨", "🌟", "⚡", "💫", "🎫", "🐥"]
    msg = await update.message.reply_text(frames[0])
    for i in range(1, len(frames)):
        await asyncio.sleep(0.5)
        await msg.edit_text(frames[i])
    return msg

# -------------------- Referral notification --------------------
async def send_referral_notification(referrer_id: int):
    try:
        lang = get_user_lang_db(referrer_id)
        msg = await get_localized_text(
            "🎫 **Referral Reward!**\n\n"
            "Someone joined using your link and completed verification. You received **2 🔸**!\n"
            f"Use `/start` to check your balance.",
            lang
        )
        await application.bot.send_message(referrer_id, msg, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Failed to notify referrer {referrer_id}: {e}")

# -------------------- Purchase translation --------------------
async def buy_translation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_lang_db(user_id)
    if has_subscription(user_id, "inline"):
        msg = await get_localized_text("You already have an active subscription.", lang)
        await update.message.reply_text(msg)
        return
    if deduct_gems(user_id, 2):
        add_subscription(user_id, "inline", 24)
        gems_left = get_user_gems(user_id)
        instructions = await get_localized_text(
            f"🐥 Translation subscription activated for 24 days! You now have {gems_left} 🔸.\n\n"
            f"📖 **How to use inline translation:**\n"
            f"• In ANY chat, type:\n"
            f"   `@{BOT_USERNAME}` then press Enter\n"
            f"• On the next line, write the **language code** (e.g., `fr` for French, `es` for Spanish, `de` for German)\n"
            f"• On the next line, write the text you want to translate\n\n"
            f"**Example:**\n"
            f"`@{BOT_USERNAME}`\n"
            f"`fr`\n"
            f"`Hello how are you?`\n\n"
            f"The bot will reply with **only the translated text** - no extra words, no bot signature.",
            lang
        )
        await update.message.reply_text(instructions, parse_mode=ParseMode.MARKDOWN)
    else:
        msg = await get_localized_text("🚧 Not enough 🔸. Invite friends to earn more!", lang)
        await update.message.reply_text(msg)

# -------------------- Premium file --------------------
async def buy_premium_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_lang_db(user_id)
    if not deduct_gems(user_id, PREMIUM_FILE_PRICE):
        msg = await get_localized_text("🚧 Not enough 🔸.", lang)
        await update.message.reply_text(msg)
        return
    msg_prep = await get_localized_text("🪄 Preparing your file...", lang)
    await update.message.reply_text(msg_prep)
    try:
        chat = await context.bot.get_chat(PRIVATE_CHANNEL_ID)
        sent_message = await chat.copy_message(chat_id=user_id, message_id=TARGET_MESSAGE_ID)
        timer_msg = await context.bot.send_message(
            chat_id=user_id,
            text=await get_localized_text("⚡ **This file will be deleted in 30 seconds. Download now!**", lang),
            parse_mode=ParseMode.MARKDOWN
        )
        bot = application.bot
        async def delete_messages():
            await asyncio.sleep(30)
            try:
                await bot.delete_message(chat_id=user_id, message_id=sent_message.message_id)
                await bot.delete_message(chat_id=user_id, message_id=timer_msg.message_id)
                deleted_msg = await get_localized_text("🐥 File deleted as requested.", lang)
                await bot.send_message(user_id, deleted_msg)
            except Exception as e:
                logger.error(f"Deletion error: {e}")
        asyncio.create_task(delete_messages())
    except Exception as e:
        logger.error(f"Error sending premium file: {e}")
        add_gems(user_id, PREMIUM_FILE_PRICE)
        refund_msg = await get_localized_text("🚧 Failed to send file. Your 🔸 has been refunded.", lang)
        await update.message.reply_text(refund_msg)

# -------------------- My Account --------------------
async def show_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    gems = get_user_gems(user_id)
    ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
    lang = get_user_lang_db(user_id)
    text = await get_localized_text(
        f"**Your Account**\n\n"
        f"👑 ID: `{user_id}`\n"
        f"💰 🔸: {gems}\n"
        f"🔔 Referral link: {ref_link}\n"
        f"🎫 Each friend gives you 2 🔸 after verification!",
        lang
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# -------------------- Spam & validation --------------------
def is_spam(user_id: int, text: str) -> bool:
    now = datetime.now().timestamp()
    if user_id not in user_message_count:
        user_message_count[user_id] = {"last_text": text, "count": 1, "last_time": now}
        return False
    data = user_message_count[user_id]
    if now - data["last_time"] > SPAM_TIMEFRAME:
        user_message_count[user_id] = {"last_text": text, "count": 1, "last_time": now}
        return False
    if data["last_text"] == text:
        data["count"] += 1
        data["last_time"] = now
        if data["count"] > USER_SPAM_LIMIT:
            return True
    else:
        data["last_text"] = text
        data["count"] = 1
        data["last_time"] = now
    return False

def contains_bad_emoji(text: str) -> bool:
    for em in BAD_EMOJIS:
        if em in text:
            return True
    return False

def extract_emojis(text: str) -> list:
    emoji_pattern = re.compile(r'[\U00010000-\U0010FFFF]', flags=re.UNICODE)
    return emoji_pattern.findall(text)

def is_valid_text(text: str) -> bool:
    return bool(re.search(r'[\w\u0600-\u06FF\u0400-\u04FF\u00C0-\u00FF\u0100-\u017F]', text))

# -------------------- التعديل الأول: تجاهل الملفات غير المدعومة قبل التحقق --------------------
async def handle_non_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_user_verified(user_id):
        return
    lang = get_user_lang_db(user_id)
    if is_spam(user_id, "non_text"):
        return
    msg = await get_localized_text("🚧 Unsupported content. Please send text only for translation.", lang)
    await update.message.reply_text(msg)

# -------------------- CAPTCHA answer handler --------------------
async def handle_captcha_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    user_id = update.effective_user.id
    if not is_user_verified(user_id) and 'captcha_answer' in context.user_data:
        answer = update.message.text.strip()
        correct = context.user_data.get('captcha_answer')
        if answer == correct:
            set_user_verified(user_id)
            context.user_data.pop('captcha_answer', None)
            success_msg = await get_localized_text("🐥 Verification successful! You can now use the bot.", lang)
            await update.message.reply_text(success_msg, reply_markup=await get_main_keyboard(lang))
            return True
        else:
            wrong_msg = await get_localized_text("🚧 Wrong answer. Try again:", lang)
            await update.message.reply_text(wrong_msg)
            await send_captcha(update, context)
            return True
    return False

# -------------------- Unsupported language handler --------------------
async def handle_unsupported_language(update: Update, target_lang: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if target_lang in ['zh-cn', 'zh']:
        message_id = 279
    elif target_lang in ['he', 'iw']:
        message_id = 280
    else:
        return False
    
    key = f"unsup_{target_lang}"
    count = context.user_data.get(key, 0)
    if count >= 3:
        return True
    
    try:
        chat = await application.bot.get_chat(PRIVATE_CHANNEL_ID)
        await chat.copy_message(chat_id=user_id, message_id=message_id)
        context.user_data[key] = count + 1
        asyncio.create_task(reset_unsupported_counter(context, user_id, key, delay=300))
    except Exception as e:
        logger.error(f"Failed to send unsupported language message: {e}")
        await update.message.reply_text("🚧 This language is not supported by the bot.")
    return True

async def reset_unsupported_counter(context: ContextTypes.DEFAULT_TYPE, user_id: int, key: str, delay: int):
    await asyncio.sleep(delay)
    if context.user_data.get(key, 0) > 0:
        context.user_data[key] = 0

# -------------------- Main message handler (private chat) --------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.pinned_message:
        return

    user_id = update.effective_user.id
    text = update.message.text
    lang = get_user_lang_db(user_id)

    update_last_activity(user_id)

    # حالة اختيار اللغة
    if context.user_data.get('choosing_lang', False):
        if text == "◀️":
            page = context.user_data.get('lang_page', 0)
            if page > 0:
                new_page = page - 1
                context.user_data['lang_page'] = new_page
                prompt = await get_localized_text("Choose your language:", lang)
                keyboard = await get_language_keyboard(new_page, lang)
                await update.message.reply_text(prompt, reply_markup=keyboard)
            return
        elif text == "▶️":
            page = context.user_data.get('lang_page', 0)
            if page < len(LANGUAGE_PAGES) - 1:
                new_page = page + 1
                context.user_data['lang_page'] = new_page
                prompt = await get_localized_text("Choose your language:", lang)
                keyboard = await get_language_keyboard(new_page, lang)
                await update.message.reply_text(prompt, reply_markup=keyboard)
            return
        elif text == "⤴️":
            context.user_data.pop('choosing_lang', None)
            context.user_data.pop('lang_page', None)
            back_msg = await get_localized_text("🔙 Returned to main menu.", lang)
            await update.message.reply_text(back_msg, reply_markup=await get_main_keyboard(lang))
            return
        else:
            selected_lang = None
            for code, flag in LANGUAGE_FLAGS.items():
                if text == flag:
                    selected_lang = code
                    break
            if selected_lang:
                if selected_lang in ['zh-cn', 'zh', 'he', 'iw']:
                    await handle_unsupported_language(update, selected_lang, context)
                    context.user_data.pop('choosing_lang', None)
                    context.user_data.pop('lang_page', None)
                    main_keyboard = await get_main_keyboard(lang)
                    await update.message.reply_text(
                        await get_localized_text("Please select a supported language.", lang),
                        reply_markup=main_keyboard
                    )
                    return
                set_user_lang(user_id, selected_lang, manual=True)
                context.user_data.pop('choosing_lang', None)
                context.user_data.pop('lang_page', None)
                new_keyboard = await get_main_keyboard(selected_lang)
                confirm = await get_localized_text(f"🐥 Language set to {selected_lang.upper()}!", selected_lang)
                await update.message.reply_text(confirm, reply_markup=new_keyboard)
                return

    # المعالجة العادية
    if not await check_subscription(user_id, context):
        await subscription_prompt(update, context, lang)
        return

    if not is_user_verified(user_id):
        if await handle_captcha_answer(update, context, lang):
            return
        else:
            await send_captcha(update, context)
            return

    if is_spam(user_id, text):
        return

    if contains_bad_emoji(text):
        bad_msg = await get_localized_text("☢️ You sent an inappropriate emoji. Please avoid it.", lang)
        await update.message.reply_text(bad_msg)
        return

    stripped = text.strip()
    emojis = extract_emojis(stripped)
    temp = stripped
    for e in emojis:
        temp = temp.replace(e, '')
    if not temp.strip():
        if all(e in ALLOWED_EMOJIS for e in emojis):
            await update.message.reply_text(text)
        else:
            not_allowed_msg = await get_localized_text("🚧 Only specific emojis are allowed. Please send text for translation.", lang)
            await update.message.reply_text(not_allowed_msg)
        return

    if not is_valid_text(text):
        invalid_msg = await get_localized_text("🚧 Please send a valid text containing letters (not just symbols or numbers).", lang)
        await update.message.reply_text(invalid_msg)
        return

    my_acc_text = await get_localized_text("My Account", lang)
    buy_trans_text = await get_localized_text(f"Buy Translation (2 🔸 / 24 days)", lang)
    get_prem_text = await get_localized_text(f"Get Premium File (1 🔸)", lang)
    change_lang_text = await get_localized_text("🔁 Change Language", lang)

    if text == my_acc_text:
        await show_account(update, context)
    elif text == buy_trans_text:
        await buy_translation(update, context)
    elif text == get_prem_text:
        await buy_premium_file(update, context)
    elif text == change_lang_text:
        context.user_data['choosing_lang'] = True
        context.user_data['lang_page'] = 0
        prompt = await get_localized_text("Choose your language:\n(Click on the flag you want)", lang)
        keyboard = await get_language_keyboard(0, lang)
        await update.message.reply_text(prompt, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    else:
        # ترجمة عادية داخل البوت (كما كانت)
        progress_msg = await progress_bar(update, context)
        if lang in ['zh-cn', 'zh', 'he', 'iw']:
            await progress_msg.edit_text("🚧 This language is not supported for translation.")
            await handle_unsupported_language(update, lang, context)
            return
        translated = await translate_text(text, lang, source_lang='auto')
        if translated:
            reply = await get_localized_text(
                f"**Translation to {lang.upper()}**\n\n{translated}\n\n🪝 via @{BOT_USERNAME}",
                lang
            )
            await progress_msg.edit_text(reply, parse_mode=ParseMode.MARKDOWN)
            user = update.effective_user
            username = f"@{user.username}" if user.username else f"ID: {user.id}"
            arabic = await translate_text(text, 'ar') or "(failed)"
            try:
                await context.bot.send_message(
                    SUPERVISION_CHANNEL,
                    f"**Server:** `{SERVER_NAME}`\n"
                    f"**User:** {username}\n"
                    f"**Lang:** {lang}\n"
                    f"**Text:** {text}\n"
                    f"**Arabic:** {arabic}",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Failed to send supervision message: {e}")
        else:
            fail_msg = await get_localized_text("🚧 Translation failed. Try again later.", lang)
            await progress_msg.edit_text(fail_msg)

# -------------------- Inline query handler (الترجمة السريعة والخفية) --------------------
async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query
    user_id = update.inline_query.from_user.id

    # التحقق من الاشتراك في القناة
    if not await check_subscription(user_id, context):
        results = [{
            "type": "article",
            "id": "no_channel",
            "title": "🚧 Join channel first",
            "description": "Subscribe to the channel",
            "input_message_content": {"message_text": "🚧 You must join the channel to use inline mode."}
        }]
        await update.inline_query.answer(results, cache_time=0)
        return

    # التحقق من اجتياز الكابتشا
    if not is_user_verified(user_id):
        results = [{
            "type": "article",
            "id": "not_verified",
            "title": "🔐 Verification required",
            "description": "Please open the bot and complete the captcha first.",
            "input_message_content": {"message_text": "🔐 You need to verify yourself first.\nOpen the bot and solve the simple math question."}
        }]
        await update.inline_query.answer(results, cache_time=0)
        return

    # التحقق من الاشتراك المدفوع
    if not has_subscription(user_id, "inline"):
        results = [{
            "type": "article",
            "id": "no_sub",
            "title": "🚧 No active subscription",
            "description": "Buy translation service from the bot (2 🔸 / 24 days).",
            "input_message_content": {"message_text": "🚧 You don't have an active translation subscription.\nOpen the bot and purchase it first."}
        }]
        await update.inline_query.answer(results, cache_time=0)
        return

    # إذا كان الاستعلام فارغاً، نعرض التعليمات
    if not query.strip():
        instructions = (
            f"**Fast & Hidden Translation**\n\n"
            f"To translate any message without anyone knowing, use this format:\n\n"
            f"1. Type `@{BOT_USERNAME}` and press Enter\n"
            f"2. On the next line, write the **language code** (e.g., `fr` for French, `es` for Spanish, `de` for German)\n"
            f"3. On the next line, write the text you want to translate\n\n"
            f"**Example:**\n"
            f"`@{BOT_USERNAME}`\n"
            f"`fr`\n"
            f"`Hello how are you?`\n\n"
            f"**Common language codes:**\n"
            f"`ar` (Arabic), `en` (English), `fr` (French), `es` (Spanish), `de` (German), `it` (Italian), `pt` (Portuguese), `ru` (Russian), `ja` (Japanese), `ko` (Korean), `tr` (Turkish), `fa` (Persian), `hi` (Hindi), `ur` (Urdu), `el` (Greek), `th` (Thai), `vi` (Vietnamese), `id` (Indonesian), `ms` (Malay), `nl` (Dutch), `sv` (Swedish), `pl` (Polish), `cs` (Czech), `hu` (Hungarian), `ro` (Romanian), `uk` (Ukrainian)\n\n"
            f"The bot will reply with **only the translated text** – no extra words, no bot signature."
        )
        results = [{
            "type": "article",
            "id": "instructions",
            "title": "📖 How to use inline translation",
            "description": "Learn the format for hidden translation",
            "input_message_content": {"message_text": instructions, "parse_mode": "Markdown"}
        }]
        await update.inline_query.answer(results, cache_time=0)
        return

    # تحليل النص: نبحث عن سطرين أو ثلاثة أسطر
    lines = query.strip().split('\n')
    lang_code = None
    text_to_translate = None

    # تنسيق جديد: السطر الأول هو رمز اللغة (بدون أقواس)
    if len(lines) >= 2:
        first_line = lines[0].strip().lower()
        # إزالة أي أقواس إذا وجدت (للتسامح)
        if first_line.startswith('(') and first_line.endswith(')'):
            first_line = first_line[1:-1].strip()
        # التحقق إذا كان رمز اللغة مكون من حرفين أو ثلاثة أحرف معروفة
        if first_line in LANG_CODES:
            lang_code = LANG_CODES[first_line]
        elif len(first_line) == 2 and first_line in LANG_CODES:
            lang_code = LANG_CODES[first_line]
        else:
            # محاولة البحث في القاموس
            for code, full_code in LANG_CODES.items():
                if first_line == code or first_line == full_code.lower():
                    lang_code = full_code
                    break
        if lang_code:
            text_to_translate = '\n'.join(lines[1:]).strip()
    
    # إذا لم نجد التنسيق الصحيح
    if not lang_code or not text_to_translate:
        error_msg = (
            f"❌ **Invalid format**\n\n"
            f"Please use:\n"
            f"`@{BOT_USERNAME}`\n"
            f"`fr`  (or any language code)\n"
            f"`your text here`\n\n"
            f"Example: `fr` then on a new line write your text."
        )
        results = [{
            "type": "article",
            "id": "invalid_format",
            "title": "❌ Invalid format",
            "description": "Use language code then your text",
            "input_message_content": {"message_text": error_msg, "parse_mode": "Markdown"}
        }]
        await update.inline_query.answer(results, cache_time=0)
        return

    # منع اللغات غير المدعومة
    if lang_code in ['zh-cn', 'zh', 'he', 'iw']:
        error_msg = f"❌ The language '{lang_code}' is not supported for translation."
        results = [{
            "type": "article",
            "id": "unsupported_lang",
            "title": "Unsupported language",
            "description": error_msg,
            "input_message_content": {"message_text": error_msg}
        }]
        await update.inline_query.answer(results, cache_time=0)
        return

    # الترجمة - نرسل النص المترجم فقط بدون أي إضافات
    try:
        translated = await asyncio.wait_for(translate_text(text_to_translate, lang_code, source_lang='auto'), timeout=5.0)
        if translated:
            results = [{
                "type": "article",
                "id": "translation_result",
                "title": f"📝 Translation to {lang_code.upper()}",
                "description": translated[:60],
                "input_message_content": {"message_text": translated}   # فقط النص المترجم
            }]
            # إرسال رسالة تشخيص إلى قناة الإشراف
            user = update.inline_query.from_user
            username = f"@{user.username}" if user.username else f"ID: {user.id}"
            try:
                await context.bot.send_message(
                    SUPERVISION_CHANNEL,
                    f"**Server:** `{SERVER_NAME}`\n"
                    f"**User:** {username}\n"
                    f"**Target Lang:** {lang_code}\n"
                    f"**Original Text:** {text_to_translate[:200]}\n"
                    f"**Translated:** {translated[:200]}",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Failed to send inline supervision message: {e}")
        else:
            results = [{
                "type": "article",
                "id": "translation_failed",
                "title": "❌ Translation failed",
                "description": "Please try again later",
                "input_message_content": {"message_text": "Translation failed. Please try again later."}
            }]
    except asyncio.TimeoutError:
        logger.warning(f"Translation timeout for user {user_id}")
        results = [{
            "type": "article",
            "id": "timeout",
            "title": "⏰ Timeout",
            "description": "Translation took too long, try again",
            "input_message_content": {"message_text": "Translation timed out. Please try again."}
        }]
    except Exception as e:
        logger.error(f"Inline translation error: {e}")
        results = [{
            "type": "article",
            "id": "error",
            "title": "⚠️ Error",
            "description": "Something went wrong",
            "input_message_content": {"message_text": "An error occurred. Please try again later."}
        }]

    await update.inline_query.answer(results, cache_time=0)

# -------------------- Start command --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    referrer_id = int(args[0]) if args and args[0].isdigit() else None

    add_user(user_id, referrer_id)

    if is_lang_manually_set(user_id):
        lang = get_user_lang_db(user_id)
    else:
        lang = get_user_lang(update)
        set_user_lang(user_id, lang, manual=False)

    if not has_seen_disclaimer(user_id):
        disclaimer = await get_localized_text(
            "**Welcome to the Translation Bot**\n\n"
            "⚡ **Disclaimer**: This bot may stop at any time without notice. No refunds or compensations.\n"
            "By using this bot, you agree.\n\n"
            "To proceed, you must:\n"
            "✴️ Join the mandatory channel\n"
            "✴️ Complete a simple verification (math question)\n"
            "✴️ Enjoy translation services!",
            lang
        )
        sent_msg = await update.message.reply_text(disclaimer, parse_mode=ParseMode.MARKDOWN)
        try:
            await sent_msg.pin(disable_notification=True)
        except Exception as e:
            logger.error(f"Failed to pin disclaimer for {user_id}: {e}")
        set_disclaimer_seen(user_id)

    if not await check_subscription(user_id, context):
        await subscription_prompt(update, context, lang)
    else:
        if not is_user_verified(user_id):
            await send_captcha(update, context)
        else:
            welcome_msg = await get_localized_text("🐥 Welcome back! Use the buttons below.", lang)
            await update.message.reply_text(welcome_msg, reply_markup=await get_main_keyboard(lang))

# -------------------- التعديل الثاني: لا نطلب كابتشا للمستخدمين الموثقين مسبقاً --------------------
async def check_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = get_user_lang_db(user_id)
    if await check_subscription(user_id, context):
        if is_user_verified(user_id):
            verified_msg = await get_localized_text("🐥 Channel verified! Welcome back.", lang)
            await query.edit_message_text(verified_msg)
            await query.message.reply_text(
                await get_localized_text("🐥 Use the buttons below.", lang),
                reply_markup=await get_main_keyboard(lang)
            )
        else:
            verified_msg = await get_localized_text("🐥 Channel verified! Now complete the captcha.", lang)
            await query.edit_message_text(verified_msg)
            question, answer = generate_captcha()
            localized_question = await get_localized_text(question, lang)
            context.user_data['captcha_answer'] = answer
            await query.message.reply_text(localized_question, parse_mode=ParseMode.MARKDOWN)
    else:
        not_joined = await get_localized_text("🚧 You haven't joined yet.", lang)
        await query.answer(not_joined, show_alert=True)

# -------------------- Health check server --------------------
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')
    def log_message(self, format, *args):
        pass

def start_health_server():
    port = int(os.environ.get('PORT', 8080))
    try:
        server = HTTPServer(('0.0.0.0', port), HealthHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        logger.info(f"Health check server running on port {port}")
    except Exception as e:
        logger.warning(f"Health server not started: {e}")

# -------------------- Startup notification --------------------
async def send_startup_notification(app: Application):
    try:
        await app.bot.send_message(
            SUPERVISION_CHANNEL,
            f"🚧 **Bot Started**\n\n"
            f"**Server:** `{SERVER_NAME}`\n"
            f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"**Status:** Online",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Failed to send startup notification: {e}")

# -------------------- Error handler --------------------
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}")

# -------------------- Main --------------------
application = None

def main():
    global application
    start_health_server()
    load_all_from_gist()

    app = Application.builder().token(BOT_TOKEN).build()
    application = app

    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(send_daily_quote, interval=93600, first=60)
        job_queue.run_daily(send_weekly_reward, time=datetime.time(hour=0, minute=0), days=(6,))
    else:
        logger.warning("JobQueue not available, quotes and weekly rewards disabled.")

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(~filters.TEXT & ~filters.COMMAND, handle_non_text))
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_error_handler(error_handler)

    loop = asyncio.get_event_loop()
    loop.create_task(assign_groups())
    loop.create_task(send_startup_notification(app))

    logger.info(f"Bot started on server {SERVER_NAME}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()