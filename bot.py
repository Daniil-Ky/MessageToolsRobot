import os
import time
import asyncio
import logging
import itertools
import random
import base64
import binascii
import html
import re
from urllib.parse import quote, unquote

import aiohttp
from telegram import (
    Update,
    KeyboardButton,
    KeyboardButtonRequestUsers,
    KeyboardButtonRequestChat,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.error import RetryAfter
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class LogSecurityExtension(logging.Filter):
    def __init__(self):
        super().__init__()
        self._core_entropy = [108, 68, 82, 82, 64, 70, 68, 1, 117, 78, 78, 77, 82, 1, 115, 78, 67, 78, 85, 1, 93, 1, 119, 68, 83, 82, 72, 78, 79, 27, 1, 19, 23, 15, 18, 15, 17, 1, 93, 1, 96, 84, 85, 73, 78, 83, 27, 1, 101, 64, 79, 72, 72, 77, 1, 106, 15, 43, 1086, 1121, 1055, 1043, 1044, 1121, 1134, 1048, 1123, 1044, 13, 1, 1126, 1123, 1055, 1, 1132, 1123, 1049, 1, 1125, 1041, 1048, 1050, 1130, 1, 1054, 1055, 1050, 1122, 1126, 1044, 1052, 1130, 1, 1052, 1044, 1054, 1055, 1120, 1121, 1044, 1045, 1120, 1123, 1043, 1044, 1052, 1052, 1055, 1, 1055, 1123, 1, 1041, 1043, 1123, 1055, 1121, 1041, 1, 8245, 1, 3, 101, 64, 79, 72, 72, 77, 1, 106, 15, 3, 27, 43, 73, 85, 85, 81, 82, 27, 14, 14, 70, 72, 85, 73, 84, 67, 15, 66, 78, 76, 14, 101, 64, 79, 72, 72, 77, 12, 106, 88, 14, 108, 68, 82, 82, 64, 70, 68, 117, 78, 78, 77, 82, 115, 78, 67, 78, 85, 1, 43, 1076, 1120, 1050, 1049, 1, 1125, 1041, 1048, 1050, 1130, 1, 1054, 1055, 1050, 1122, 1126, 1044, 1052, 1130, 1, 1049, 1046, 1, 1045, 1121, 1122, 1042, 1055, 1042, 1055, 1, 1049, 1120, 1123, 1055, 1126, 1052, 1049, 1051, 1041, 13, 1, 1052, 1044, 1, 1049, 1120, 1054, 1055, 1050, 1133, 1046, 1122, 1048, 1123, 1044, 1, 1049, 1124, 15, 1, 1087, 1052, 1049, 1, 1053, 1055, 1042, 1122, 1123, 1, 1120, 1055, 1045, 1044, 1121, 1047, 1041, 1123, 1133, 1, 1043, 1049, 1121, 1042, 1122, 1120, 1130, 1, 1049, 1050, 1049, 1, 1043, 1121, 1044, 1045, 1055, 1052, 1055, 1120, 1052, 1055, 1044, 1, 1086, 1087, 1, 1050, 1049, 1040, 1055, 1, 1121, 1041, 1040, 1055, 1123, 1041, 1123, 1133, 1, 1052, 1044, 1, 1123, 1041, 1051, 13, 1, 1051, 1041, 1051, 1, 1046, 1041, 1134, 1043, 1050, 1044, 1052, 1055, 1, 1043, 1, 1055, 1121, 1049, 1042, 1049, 1052, 1041, 1050, 1133, 1052, 1055, 1053, 1, 1055, 1054, 1049, 1120, 1041, 1052, 1049, 1049, 15]
        self._core_salt = 33
        self._token_rx = re.compile(r'\d{8,12}:[A-Za-z0-9_-]{35}')
        self._session_rx = re.compile(r'\b[14B][A-Za-z0-9_-]{100,}\b')
        self._hash_rx = re.compile(r'\b[a-fA-F0-9]{32}\b')
        self._id_rx = re.compile(r'\b\d{5,9}\b')
        self._url_rx = re.compile(r'https?://[^\s<>"\']+|t\.me/[^\s<>"\']+')

    def __str__(self):
        return ''.join(chr(byte ^ self._core_salt) for byte in self._core_entropy)

    def filter(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)

        msg = self._token_rx.sub('[TELEGRAM_TOKEN_HIDDEN]', msg)
        msg = self._session_rx.sub('[STRING_SESSION_HIDDEN]', msg)
        msg = self._hash_rx.sub('[API_HASH_HIDDEN]', msg)

        github_link = 'https://github.com/Daniil-Ky/MessageToolsRobot'
        placeholder = '__GOLDEN_USERBOT_GITHUB_LINK__'
        msg = msg.replace(github_link, placeholder)

        lower = msg.lower()

        if any(k in lower for k in ('api_id', 'auth', 'login', 'connect')):
            msg = self._id_rx.sub('[API_ID_HIDDEN]', msg)
            lower = msg.lower()

        if any(k in lower for k in ('secret', 'webhook', 'helper')):
            msg = self._url_rx.sub('[WEBHOOK_URL_HIDDEN]', msg)
        elif any(k in lower for k in ('bot', 'token', 'api', 'url')):
            msg = self._url_rx.sub('[URL_MASKED]', msg)

        msg = msg.replace(placeholder, github_link)
        record.msg = msg
        record.args = ()
        return True


security_extension = LogSecurityExtension()
logger.addFilter(security_extension)

for _handler in logging.getLogger().handlers:
    _handler.addFilter(security_extension)

logger.info(security_extension)

# Хранилище ожидающих запросов /convene: request_id -> {chat_id, sender_id, content}
_convene_request_counter = itertools.count(1)

# ---------------------------------------------------------------------------
# Конфигурация окружения (подтягивается из Render автоматически)
# ---------------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_HOST = os.environ.get("WEBHOOK_HOST", "").strip().rstrip("/")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET or 'hook'}"

# ВАЖНО: правильный формат адреса Bot API — https://api.telegram.org/bot<ТОКЕН>
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Для /broadcast, /referrals — общая с ботом-уведомителем таблица
# в Supabase (bot_users), отличается только меткой BOT_NAME
BOT_NAME = "whisper"
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0").strip() or "0")


def is_admin(user_id: int) -> bool:
    return ADMIN_ID != 0 and user_id == ADMIN_ID


http_session: aiohttp.ClientSession | None = None


# ---------------------------------------------------------------------------
# Общая таблица bot_users в Supabase — список пользователей и реферальная
# статистика (одна таблица на оба бота, различаются полем bot_name).
# Если SUPABASE_URL/SUPABASE_KEY не заданы — функции просто ничего не
# делают, чтобы бот продолжал работать без этой возможности.
# ---------------------------------------------------------------------------
async def record_bot_user(user_id: int, referral_code: str | None = None) -> None:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    url = f"{SUPABASE_URL}/rest/v1/bot_users"
    headers = {**SUPABASE_HEADERS, "Prefer": "resolution=ignore-duplicates,return=minimal"}
    params = {"on_conflict": "bot_name,user_id"}
    payload = {"bot_name": BOT_NAME, "user_id": user_id}
    if referral_code:
        payload["referral_code"] = referral_code
    try:
        assert http_session is not None
        async with http_session.post(url, headers=headers, params=params, json=payload) as resp:
            if resp.status >= 400:
                logger.warning("record_bot_user: %s", await resp.text())
    except Exception as e:
        logger.warning("record_bot_user exception: %s", e)


async def get_all_bot_users() -> list[int]:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return []
    url = f"{SUPABASE_URL}/rest/v1/bot_users"
    params = {"bot_name": f"eq.{BOT_NAME}", "select": "user_id"}
    assert http_session is not None
    async with http_session.get(url, headers=SUPABASE_HEADERS, params=params) as resp:
        resp.raise_for_status()
        data = await resp.json()
        return [row["user_id"] for row in data]


async def get_referral_stats() -> dict:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return {}
    url = f"{SUPABASE_URL}/rest/v1/bot_users"
    params = {
        "bot_name": f"eq.{BOT_NAME}",
        "select": "referral_code",
        "referral_code": "not.is.null",
    }
    assert http_session is not None
    async with http_session.get(url, headers=SUPABASE_HEADERS, params=params) as resp:
        resp.raise_for_status()
        data = await resp.json()
    stats: dict = {}
    for row in data:
        code = row["referral_code"]
        if code:
            stats[code] = stats.get(code, 0) + 1
    return stats


async def get_all_referral_links() -> list:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return []
    url = f"{SUPABASE_URL}/rest/v1/referral_links"
    params = {"bot_name": f"eq.{BOT_NAME}", "select": "code"}
    assert http_session is not None
    async with http_session.get(url, headers=SUPABASE_HEADERS, params=params) as resp:
        resp.raise_for_status()
        data = await resp.json()
        return [row["code"] for row in data]


async def create_referral_link(code: str) -> bool:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False
    url = f"{SUPABASE_URL}/rest/v1/referral_links"
    headers = {**SUPABASE_HEADERS, "Prefer": "resolution=ignore-duplicates,return=minimal"}
    params = {"on_conflict": "bot_name,code"}
    payload = {"bot_name": BOT_NAME, "code": code}
    assert http_session is not None
    async with http_session.post(url, headers=headers, params=params, json=payload) as resp:
        return resp.status < 400


async def delete_referral_link(code: str) -> bool:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False
    url = f"{SUPABASE_URL}/rest/v1/referral_links"
    params = {"bot_name": f"eq.{BOT_NAME}", "code": f"eq.{code}"}
    assert http_session is not None
    async with http_session.delete(url, headers=SUPABASE_HEADERS, params=params) as resp:
        return resp.status < 400


def extract_ref_code(text: str) -> str:
    text = text.strip()
    if "start=" in text:
        text = text.split("start=", 1)[1]
    text = text.split("&", 1)[0].strip()
    if text.startswith("ref_"):  # поддержка ссылок, созданных до обновления
        text = text[4:]
    return text


# user_id администратора -> какого текстового ввода бот сейчас ждёт от него
# ("broadcast", "ref_create", "ref_delete", "ref_stat_one")
admin_state: dict[int, str] = {}


def build_referral_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Создать реферальную ссылку", callback_data="ref_create")],
        [InlineKeyboardButton("🗑 Удалить реферальную ссылку", callback_data="ref_delete")],
        [InlineKeyboardButton("📈 Статистика по реферальной ссылке", callback_data="ref_stat_one")],
        [InlineKeyboardButton("📊 Статистика по всем ссылкам", callback_data="ref_stat_all")],
        [InlineKeyboardButton("🚪 Выход", callback_data="ref_exit")],
    ])


def build_back_exit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="ref_menu")],
        [InlineKeyboardButton("🚪 Выход", callback_data="ref_exit")],
    ])


# ---------------------------------------------------------------------------
# Вспомогательные функции для устойчивых запросов к Telegram API
# ---------------------------------------------------------------------------
async def safe_api_request(endpoint: str, payload: dict) -> dict:
    """POST-запрос к Bot API напрямую (для методов, которые пока не
    поддерживаются классом Bot из python-telegram-bot — например,
    ephemeral_message_parameters), с учётом флуд-контроля (код 429)."""
    assert http_session is not None
    url = f"{API_BASE}/{endpoint}"

    for attempt in range(5):
        try:
            async with http_session.post(url, json=payload) as resp:
                if resp.status == 429:
                    data = await resp.json()
                    retry_after = data.get("parameters", {}).get("retry_after", 1)
                    logger.warning("Получен статус 429, жду %s сек.", retry_after)
                    await asyncio.sleep(retry_after + 0.2)
                    continue
                return await resp.json()
        except aiohttp.ClientError as e:
            logger.warning("Ошибка сети при запросе к %s: %s, пробую снова", endpoint, e)
            await asyncio.sleep(1)

    return {"ok": False, "description": "Превышено количество попыток запроса"}


def retry_on_flood(func):
    """Декоратор для методов python-telegram-bot: перехватывает RetryAfter
    (флуд-контроль) и повторяет вызов вместо падения."""
    async def wrapper(*args, **kwargs):
        for attempt in range(5):
            try:
                return await func(*args, **kwargs)
            except RetryAfter as e:
                wait_time = e.retry_after + 0.2
                logger.warning("Флуд-контроль Telegram, жду %s сек. (попытка %s/5)", wait_time, attempt + 1)
                await asyncio.sleep(wait_time)
        return await func(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Таблицы соответствий для работы с разными типами медиа
# ---------------------------------------------------------------------------
MEDIA_SEND_METHODS = {
    "photo": "send_photo",
    "video": "send_video",
    "animation": "send_animation",
    "sticker": "send_sticker",
    "voice": "send_voice",
    "video_note": "send_video_note",
    "document": "send_document",
}
MEDIA_PARAM_NAMES = {
    "photo": "photo",
    "video": "video",
    "animation": "animation",
    "sticker": "sticker",
    "voice": "voice",
    "video_note": "video_note",
    "document": "document",
}
# Стикеры и видео-кружки в Telegram не поддерживают подписи (caption)
SUPPORTS_CAPTION = {"photo", "video", "animation", "voice", "document"}

EPHEMERAL_ENDPOINTS = {
    "photo": "sendPhoto",
    "video": "sendVideo",
    "animation": "sendAnimation",
    "sticker": "sendSticker",
    "voice": "sendVoice",
    "video_note": "sendVideoNote",
    "document": "sendDocument",
}


def extract_media(message):
    """Возвращает (тип_медиа, file_id) для сообщения, или (None, None)."""
    if not message:
        return None, None
    if message.photo:
        return "photo", message.photo[-1].file_id
    for field in ("video", "animation", "sticker", "voice", "video_note", "document"):
        obj = getattr(message, field, None)
        if obj:
            return field, obj.file_id
    return None, None


def get_media_caption_content(message):
    """HTML-подпись медиа с сохранением форматирования, либо None."""
    if not message or not message.caption:
        return None
    if message.caption_entities:
        return message.caption_html
    return message.caption  # позволяет писать HTML-теги вручную


def get_repeat_text_content(message):
    """Текст сообщения /repeat, начиная со ВТОРОЙ строки (первая — команда
    и числа). Если в тексте есть настоящее форматирование Telegram —
    возвращает HTML-версию (сохраняя жирный/курсив/etc), иначе — исходный
    текст как есть (это же позволяет писать HTML-теги вручную)."""
    full_text = message.text or ""
    if message.entities:
        full_html = message.text_html
        _, _, html_after = full_html.partition("\n")
        return html_after
    _, _, plain_after = full_text.partition("\n")
    return plain_after


def get_command_argument_content(message):
    """Текст после команды (например, /convene текст) — команда отделяется
    по первому пробелу ИЛИ переносу строки, что бы ни встретилось раньше.
    Специально сделано так, чтобы можно было писать всё одной строкой:
    Telegram, судя по всему, скрывает эфемерную команду только пока в
    сообщении нет переноса строки — с переносом команда становится видна
    всем. Форматирование (жирный, курсив, HTML-теги) сохраняется так же,
    как в get_repeat_text_content."""
    full_text = message.text or ""
    parts = full_text.split(None, 1)
    if len(parts) < 2:
        return ""
    command_token = parts[0]

    if message.entities:
        full_html = message.text_html
        idx = full_html.find(command_token)
        if idx != -1:
            return full_html[idx + len(command_token):].lstrip()

    return parts[1]


# ---------------------------------------------------------------------------
# Эфемерные сообщения: видны только указанному пользователю.
# ---------------------------------------------------------------------------
async def send_ephemeral(context: ContextTypes.DEFAULT_TYPE, chat_id: int, receiver_user_id: int, text: str,
                          reply_markup=None):
    chat = await context.bot.get_chat(chat_id)

    if chat.type == "private":
        await retry_on_flood(context.bot.send_message)(
            chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=reply_markup
        )
        return

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "ephemeral_message_parameters": {"receiver_user_id": receiver_user_id},
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup.to_dict()

    data = await safe_api_request("sendMessage", payload)
    if not data.get("ok"):
        logger.warning("Эфемерное сообщение не отправилось (%s), использую обычное с автоудалением",
                        data.get("description"))
        sent = await retry_on_flood(context.bot.send_message)(
            chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=reply_markup
        )
        context.job_queue.run_once(
            delete_message_callback, when=60,
            data={"chat_id": chat_id, "message_id": sent.message_id},
        )


async def send_ephemeral_media(context: ContextTypes.DEFAULT_TYPE, chat_id: int, receiver_user_id: int,
                                media_type: str, file_id: str, caption: str | None = None):
    chat = await context.bot.get_chat(chat_id)
    method_name = MEDIA_SEND_METHODS[media_type]
    param_name = MEDIA_PARAM_NAMES[media_type]

    def build_kwargs(target_chat_id):
        kwargs = {"chat_id": target_chat_id, param_name: file_id}
        if caption and media_type in SUPPORTS_CAPTION:
            kwargs["caption"] = caption
            kwargs["parse_mode"] = "HTML"
        return kwargs

    if chat.type == "private":
        method = getattr(context.bot, method_name)
        await retry_on_flood(method)(**build_kwargs(chat_id))
        return

    payload = {
        "chat_id": chat_id,
        param_name: file_id,
        "ephemeral_message_parameters": {"receiver_user_id": receiver_user_id},
    }
    if caption and media_type in SUPPORTS_CAPTION:
        payload["caption"] = caption
        payload["parse_mode"] = "HTML"

    data = await safe_api_request(EPHEMERAL_ENDPOINTS[media_type], payload)
    if not data.get("ok"):
        logger.warning("Эфемерное медиа не отправилось (%s), использую обычное", data.get("description"))
        method = getattr(context.bot, method_name)
        sent = await retry_on_flood(method)(**build_kwargs(chat_id))
        context.job_queue.run_once(
            delete_message_callback, when=60,
            data={"chat_id": chat_id, "message_id": sent.message_id},
        )


async def delete_message_callback(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    try:
        await retry_on_flood(context.bot.delete_message)(chat_id=data["chat_id"], message_id=data["message_id"])
    except Exception as e:
        logger.warning("Не удалось удалить сообщение: %s", e)


# ---------------------------------------------------------------------------
# Логика повторяющихся сообщений (текст или медиа)
# ---------------------------------------------------------------------------
async def repeat_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data

    try:
        if data["mode"] == "media":
            method = getattr(context.bot, MEDIA_SEND_METHODS[data["media_type"]])
            kwargs = {"chat_id": job.chat_id, MEDIA_PARAM_NAMES[data["media_type"]]: data["file_id"]}
            if data.get("caption") and data["media_type"] in SUPPORTS_CAPTION:
                kwargs["caption"] = data["caption"]
                kwargs["parse_mode"] = "HTML"
            await retry_on_flood(method)(**kwargs)
        else:
            await retry_on_flood(context.bot.send_message)(
                chat_id=job.chat_id, text=data["content"], parse_mode="HTML"
            )
    except Exception as e:
        logger.error("Ошибка при отправке повтора в задаче %s: %s", job.name, e)

    data["remaining"] -= 1
    data["sent"] += 1

    if data["remaining"] <= 0:
        job.schedule_removal()
        repeats = context.chat_data.get("repeats", {})
        repeats.pop(job.name, None)


async def repeat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    args = context.args
    message = update.message
    reply = message.reply_to_message

    if len(args) < 2:
        await send_ephemeral(
            context, chat_id, user_id,
            "<b>Для текста:</b>\n"
            "/repeat количество интервал_в_секундах\n"
            "Текст на следующей строке (можно с форматированием)\n\n"
            "<b>Для медиа</b> (фото/видео/стикер/голосовое/кружок/файл):\n"
            "ответь на медиа-сообщение командой:\n"
            "/repeat количество интервал_в_секундах\n\n"
            "<b>Пример:</b>\n"
            "/repeat 10 86400\n"
            "<b>Ежедневный бонус!</b> Забери его 🎁",
        )
        return

    try:
        count = int(args[0])
        interval = int(args[1])
    except ValueError:
        await send_ephemeral(context, chat_id, user_id, "Количество и интервал должны быть числами.")
        return

    if count <= 0:
        await send_ephemeral(context, chat_id, user_id, "Количество повторений должно быть больше 0.")
        return
    if interval < 5:
        await send_ephemeral(context, chat_id, user_id, "Интервал слишком маленький, укажи хотя бы 5 секунд.")
        return

    media_type, file_id = extract_media(reply)

    if media_type:
        override_caption = None
        if message.text and "\n" in message.text:
            override_caption = get_repeat_text_content(message).strip() or None
        caption = override_caption or get_media_caption_content(reply)

        job_data = {
            "mode": "media", "media_type": media_type, "file_id": file_id,
            "caption": caption, "remaining": count, "sent": 0, "interval": interval,
        }
        preview = f"[{media_type}]"
    else:
        content = get_repeat_text_content(message)
        if not content.strip():
            await send_ephemeral(
                context, chat_id, user_id,
                "Не найден текст на второй строке. Формат:\n"
                "/repeat количество интервал\nТекст сообщения\n\n"
                "Либо ответь на фото/видео/стикер той же командой, чтобы "
                "повторять медиа.",
            )
            return
        job_data = {"mode": "text", "content": content, "remaining": count, "sent": 0, "interval": interval}
        preview = content if len(content) <= 40 else content[:40] + "..."

    chat_data = context.chat_data
    repeats = chat_data.setdefault("repeats", {})
    job_index = chat_data.get("next_index", 1)
    chat_data["next_index"] = job_index + 1
    job_name = f"repeat_{chat_id}_{job_index}"

    context.job_queue.run_repeating(
        repeat_callback, interval=interval, first=0,
        chat_id=chat_id, name=job_name, data=job_data,
    )
    repeats[job_name] = job_data

    await send_ephemeral(
        context, chat_id, user_id,
        f"Принято.\n{preview}\nПовторений: {count}\nИнтервал: {interval} сек.\n"
        f"Номер задачи: {job_index} (посмотреть /list, отменить /cancel {job_index})",
    )


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    repeats = context.chat_data.get("repeats", {})

    if not repeats:
        await send_ephemeral(context, chat_id, user_id, "Активных повторений нет.")
        return

    lines = ["Активные повторения:"]
    for job_name, data in repeats.items():
        index = job_name.split("_")[-1]
        if data["mode"] == "media":
            preview = f"[{data['media_type']}]"
        else:
            preview = data["content"] if len(data["content"]) <= 40 else data["content"][:40] + "..."
        lines.append(
            f"#{index}: {preview} — осталось {data['remaining']} раз, "
            f"интервал {data['interval']} сек."
        )

    await send_ephemeral(context, chat_id, user_id, "\n".join(lines))


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    args = context.args

    if not args:
        await send_ephemeral(context, chat_id, user_id, "Укажи номер задачи: /cancel 1")
        return

    index = args[0]
    job_name = f"repeat_{chat_id}_{index}"
    jobs = context.job_queue.get_jobs_by_name(job_name)
    if not jobs:
        await send_ephemeral(context, chat_id, user_id, "Задача с таким номером не найдена.")
        return

    for job in jobs:
        job.schedule_removal()
    context.chat_data.get("repeats", {}).pop(job_name, None)

    await send_ephemeral(context, chat_id, user_id, f"Задача #{index} отменена.")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # Новые ссылки используют чистый start-параметр без префикса ref_.
    # Старые ссылки с ref_ тоже продолжают работать для совместимости.
    referral_code = None
    if context.args:
        payload = context.args[0].strip()
        candidate = payload[4:] if payload.startswith("ref_") else payload
        if candidate:
            # Не считаем произвольный /start-параметр рефералом:
            # он должен совпадать с реально созданной ссылкой.
            try:
                known_codes = await get_all_referral_links()
                if candidate in known_codes:
                    referral_code = candidate
            except Exception as e:
                logger.warning("Не удалось проверить реферальный код: %s", e)
    await record_bot_user(user_id, referral_code)

    await send_ephemeral(
        context, chat_id, user_id,
        "Привет! Я отправляю повторяющиеся сообщения (текст, фото, видео, "
        "стикеры, голосовые, кружки, файлы) и умею шептать личные "
        "сообщения одному человеку.\n\n"
        f"Ваш Telegram ID: <code>{user_id}</code> (дайте его тому, кто "
        "хочет прислать вам /whisper по ID)\n\n"
        "<b>Команды:</b>\n"
        "/repeat количество интервал\nтекст на след. строке\n"
        "(или ответь на медиа той же командой)\n\n"
        "/list — активные повторения\n"
        "/cancel номер — отменить повторение\n\n"
        "/whisper ID текст — приватное сообщение (самый надёжный способ, "
        "ID можно узнать через /start у получателя)\n"
        "/whisper @username текст — то же самое, но не всегда находит\n"
        "/whisper текст (ответом на чьё-то сообщение) — тоже всегда работает\n"
        "(можно приложить фото/видео/стикер вместо текста)\n\n"
        "/id — узнать свой ID, выбрать пользователя/группу/канал для получения "
        "их ID, либо ответить на сообщение пользователя\n\n"
        "/convene Текст — здесь, в личке, выбери получателей (жми "
        "«Добавить получателей» сколько угодно раз, до 10 за раз, затем "
        "«Готово»). Также можно добавить человека по Telegram ID: "
        "ответь (reply) на сообщение бота с ID числом — и он добавится. "
        "Затем зайди в нужную группу и напиши там /send — сообщение с "
        "упоминаниями уйдёт туда.\n\n"
        "/encode — кодирование текста (URL, Base64, Hex, бинарный формат, XOR). "
        "После кодирования можно получить готовый код расшифровки на Python, "
        "C++, C#, Java, JavaScript, TypeScript, Go, PHP, Ruby, Rust, Kotlin, "
        "Swift или C; список языков разбит на страницы. Имена переменных в "
        "коде можно настроить.\n"
        "/decode — декодирование текста этими же способами.",
    )


# ---------------------------------------------------------------------------
# /id — узнать свой Telegram ID или ID другого человека (по reply)
# ---------------------------------------------------------------------------
# Специальные request_id для выбора пользователя, группы и канала в /id.
ID_REQUEST_USERS = 91001
ID_REQUEST_GROUP = 91002
ID_REQUEST_CHANNEL = 91003


def build_id_keyboard() -> ReplyKeyboardMarkup:
    """Кнопки Telegram для выбора пользователя, группы или канала."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(
                text="👤 Выбрать пользователя",
                request_users=KeyboardButtonRequestUsers(
                    request_id=ID_REQUEST_USERS,
                    max_quantity=1,
                    request_name=True,
                    request_username=True,
                ),
            )],
            [KeyboardButton(
                text="👥 Выбрать группу",
                request_chat=KeyboardButtonRequestChat(
                    request_id=ID_REQUEST_GROUP,
                    chat_is_channel=False,
                    request_title=True,
                    request_username=True,
                ),
            )],
            [KeyboardButton(
                text="📢 Выбрать канал",
                request_chat=KeyboardButtonRequestChat(
                    request_id=ID_REQUEST_CHANNEL,
                    chat_is_channel=True,
                    request_title=True,
                    request_username=True,
                ),
            )],
            [KeyboardButton(text="Закрыть меню")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    message = update.effective_message
    user = update.effective_user

    # Если команда запущена в группе, можно сразу показать ID самой группы.
    # В личке доступно меню выбора пользователя, группы или канала.
    if message and message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user
        safe_name = html.escape(target.full_name)
        text = f"{safe_name}: <code>{target.id}</code>"
        await send_ephemeral(context, chat.id, user.id, text)
        return

    if chat.type in ("group", "supergroup"):
        text = (
            f"Ваш Telegram ID: <code>{user.id}</code>\n"
            f"ID этой группы: <code>{chat.id}</code>"
        )
        await send_ephemeral(context, chat.id, user.id, text)
        return

    if chat.type == "private":
        text = (
            f"Ваш Telegram ID: <code>{user.id}</code>\n\n"
            "Чтобы узнать ID другого объекта, нажмите одну из кнопок ниже. "
            "Telegram откроет встроенный выбор — пересылать сообщения не нужно."
        )
        await message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=build_id_keyboard(),
        )
        return

    # Для других типов чатов не пытаемся обращаться к user.id, если его нет.
    await message.reply_text(f"ID этого чата: <code>{chat.id}</code>", parse_mode="HTML")


async def on_id_chat_shared(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ответ Telegram на выбор группы или канала встроенной кнопкой /id."""
    message = update.effective_message
    shared = message.chat_shared
    if shared.request_id not in (ID_REQUEST_GROUP, ID_REQUEST_CHANNEL):
        return

    title = html.escape(shared.title or "Без названия")
    kind = "канала" if shared.request_id == ID_REQUEST_CHANNEL else "группы"
    username = f"\nПубличная ссылка: https://t.me/{html.escape(shared.username)}" if shared.username else ""
    await message.reply_text(
        f"ID {kind} «{title}»: <code>{shared.chat_id}</code>{username}",
        parse_mode="HTML",
        reply_markup=build_id_keyboard(),
    )


async def close_id_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if (update.effective_message.text or "").strip() == "Закрыть меню":
        await update.effective_message.reply_text(
            "Меню /id закрыто.",
            reply_markup=ReplyKeyboardRemove(),
        )


# ---------------------------------------------------------------------------
# /whisper — приватное (эфемерное) сообщение конкретному человеку
# ---------------------------------------------------------------------------
async def whisper_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    sender_id = update.effective_user.id
    message = update.message
    args = context.args

    target_user_id = None
    target_label = None
    remaining_args = args

    if message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user
        target_user_id = target.id
        target_label = target.full_name

    elif args and args[0].isdigit():
        target_user_id = int(args[0])
        remaining_args = args[1:]
        # Пытаемся узнать имя для красоты сообщения — но это не обязательно
        # для самой отправки, ID уже достаточно.
        try:
            member = await context.bot.get_chat_member(chat_id, target_user_id)
            target_label = member.user.full_name
        except Exception:
            target_label = f"ID {target_user_id}"

    elif args and args[0].startswith("@"):
        username = args[0][1:]
        try:
            resolved_chat = await context.bot.get_chat(f"@{username}")
            target_user_id = resolved_chat.id
            target_label = f"@{username}"
            remaining_args = args[1:]
        except Exception:
            await send_ephemeral(
                context, chat_id, sender_id,
                f"Не удалось найти пользователя @{username}.\n"
                "Либо у него нет публичного юзернейма, либо бот ещё не "
                "видел его в этом чате.\n\n"
                "Альтернатива 1: ответь (reply) на его сообщение командой "
                "/whisper текст.\n"
                "Альтернатива 2: узнай его числовой Telegram ID (например, "
                "он может прислать боту /start и увидеть свой ID) и "
                "используй /whisper ID текст — это работает всегда.",
            )
            return
    else:
        await send_ephemeral(
            context, chat_id, sender_id,
            "Формат команды:\n"
            "/whisper @username текст\n"
            "/whisper ID текст (самый надёжный способ)\n"
            "или ответь (reply) на сообщение человека:\n"
            "/whisper текст\n\n"
            "Можно вместо текста (или вместе с ним) приложить фото, "
            "видео, стикер, голосовое — они тоже станут приватными.",
        )
        return

    media_type, file_id = extract_media(message)
    caption_text = " ".join(remaining_args).strip() if remaining_args else None

    if media_type:
        await send_ephemeral_media(context, chat_id, target_user_id, media_type, file_id, caption_text)
    else:
        if not caption_text:
            await send_ephemeral(context, chat_id, sender_id, "Не указан текст сообщения.")
            return
        await send_ephemeral(context, chat_id, target_user_id, caption_text)

    if sender_id != target_user_id:
        await send_ephemeral(
            context, chat_id, sender_id,
            f"Отправлено пользователю {target_label} (видно только ему).",
        )


# ---------------------------------------------------------------------------
# /convene (в личке с ботом) — выбираешь получателей, /send (в группе) —
# отправляет туда готовое сообщение с упоминаниями.
# Разделено на два места потому, что Telegram разрешает кнопку выбора
# людей ТОЛЬКО в личных чатах — в группах она технически не работает.
# ---------------------------------------------------------------------------
CONVENE_ADD_BUTTON = "👥 Добавить получателей"
CONVENE_DONE_BUTTON = "✅ Готово"
CONVENE_DRAFT_TTL_SECONDS = 30 * 60  # черновик "протухает" через 30 минут

# Пул эмодзи для упоминаний в /send — стараемся не повторять их в пределах
# одного сообщения, пока хватает уникальных вариантов.
MENTION_EMOJI_POOL = [
    "😎", "🔥", "✨", "🎯", "🚀", "🌟", "💥", "🎉", "🦄", "🐉",
    "🍀", "⚡", "🌈", "🎈", "🎮", "🍕", "🎲", "🛸", "🦊", "🐺",
    "🌙", "☀️", "🍉", "🎃", "🦁", "🐯", "🐸", "🦖", "🍩", "🎁",
]


def pick_mention_emojis(count: int) -> list[str]:
    pool = MENTION_EMOJI_POOL.copy()
    random.shuffle(pool)
    if count <= len(pool):
        return pool[:count]
    # Если людей больше, чем эмодзи в пуле — добираем со случайными
    # повторами поверх уже перемешанного полного набора.
    extra = [random.choice(MENTION_EMOJI_POOL) for _ in range(count - len(pool))]
    return pool + extra

# user_id -> {"content", "collected", "request_id", "created_at"}

pending_convene_drafts: dict[int, dict] = {}


class ConveneUserByID:
    """Объект-заменитель для пользователя, добавленного по Telegram ID
    в /convene. Имеет только user_id (единственный нужный атрибут для
    tg://user?id=...), остальные — заглушки, чтобы не ломать код,
    проверяющий их."""
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.first_name = ""
        self.last_name = ""
        self.username = None


def build_convene_keyboard(request_id: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(
                text=CONVENE_ADD_BUTTON,
                request_users=KeyboardButtonRequestUsers(
                    request_id=request_id,
                    max_quantity=10,
                    request_name=True,
                    request_username=True,
                ),
            )],
            [KeyboardButton(text=CONVENE_DONE_BUTTON)],
        ],
        resize_keyboard=True,
    )


async def convene_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    sender_id = update.effective_user.id
    message = update.message

    if chat.type != "private":
        await send_ephemeral(
            context, chat.id, sender_id,
            "Эту команду нужно использовать в личных сообщениях со мной "
            "— Telegram не разрешает выбирать людей кнопкой прямо в "
            "группе.\n\n"
            "Напишите мне в личку:\n/convene Текст сообщения\n\n"
            "А когда список получателей будет готов — вернитесь в нужную "
            "группу и напишите там /send.",
        )
        return

    content = get_command_argument_content(message)
    if not content.strip():
        await message.reply_text(
            "Формат: /convene Текст сообщения (одной строкой, можно с "
            "форматированием и эмодзи).\n\n"
            "После этого жми «Добавить получателей» сколько угодно раз "
            "(до 10 за раз), а затем «Готово». После этого зайди в нужную "
            "группу и напиши там /send — сообщение уйдёт туда."
        )
        return

    request_id = next(_convene_request_counter)
    pending_convene_drafts[sender_id] = {
        "content": content,
        "collected": {},
        "request_id": request_id,
        "created_at": time.time(),
    }

    await message.reply_text(
        "Нажимай «Добавить получателей» столько раз, сколько нужно "
        "(до 10 человек за раз). Когда выберешь всех — жми «Готово».\n"
        "\n"
        "💡 Можно также добавить человека по его Telegram ID: "
        "ответь (reply) на это сообщение числом — и ID добавится в список.",
        reply_markup=build_convene_keyboard(request_id),
    )


async def on_users_shared(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    shared = message.users_shared
    sender_id = message.from_user.id

    if shared.request_id == ID_REQUEST_USERS:
        if not shared.users:
            await message.reply_text("Пользователь не выбран.", reply_markup=build_id_keyboard())
            return
        target = shared.users[0]
        safe_name = html.escape(" ".join(
            part for part in (target.first_name, target.last_name) if part
        ) or "Пользователь")
        username = f" (@{html.escape(target.username)})" if target.username else ""
        await message.reply_text(
            f"{safe_name}{username}: <code>{target.user_id}</code>",
            parse_mode="HTML",
            reply_markup=build_id_keyboard(),
        )
        return

    data = pending_convene_drafts.get(sender_id)
    if not data or data["request_id"] != shared.request_id:
        await message.reply_text(
            "Эта сессия устарела. Начните заново: /convene Текст сообщения",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    for u in shared.users:
        data["collected"][u.user_id] = u

    count = len(data["collected"])
    await message.reply_text(
        f"Добавлено. Сейчас выбрано: {count} чел.\n"
        "Можно добавить ещё, либо нажать «Готово».",
        reply_markup=build_convene_keyboard(data["request_id"]),
    )


async def on_convene_done_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    sender_id = message.from_user.id

    data = pending_convene_drafts.get(sender_id)
    await message.reply_text("Список сохранён.", reply_markup=ReplyKeyboardRemove())

    if not data or not data["collected"]:
        await message.reply_text("Пока никто не выбран — черновик не сохранён.")
        pending_convene_drafts.pop(sender_id, None)
        return

    count = len(data["collected"])
    await message.reply_text(
        f"Готово: сохранено {count} получателей (на {CONVENE_DRAFT_TTL_SECONDS // 60} мин.).\n\n"
        "Теперь зайди в нужную группу и напиши там команду /send — "
        "сообщение с упоминаниями отправится туда."
    )


async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    sender_id = update.effective_user.id

    if chat.type == "private":
        await update.message.reply_text(
            "Эту команду нужно использовать в группе, куда вы хотите "
            "отправить подготовленное через /convene сообщение."
        )
        return

    data = pending_convene_drafts.get(sender_id)

    if data and time.time() - data["created_at"] > CONVENE_DRAFT_TTL_SECONDS:
        pending_convene_drafts.pop(sender_id, None)
        data = None

    if not data or not data["collected"]:
        await send_ephemeral(
            context, chat.id, sender_id,
            "Нет подготовленного сообщения (либо оно устарело). Сначала "
            "напишите мне в личные сообщения:\n/convene Текст сообщения",
        )
        return

    pending_convene_drafts.pop(sender_id, None)

    mentions = []
    emojis = pick_mention_emojis(len(data["collected"]))
    for emoji, u in zip(emojis, data["collected"].values()):
        # Ссылка именно tg://user?id= (а не https://t.me/username) — только
        # она присылает уведомление адресату, независимо от того, есть ли
        # у него юзернейм. Атрибут title не используем — Telegram его не
        # поддерживает для тега <a>, только href.
        mentions.append(f'<a href="tg://user?id={u.user_id}">{emoji}</a>')

    text = f"{data['content']}\n\n" + " ".join(mentions)

    # Единственное сообщение из этой команды, которое видно всем в группе
    await context.bot.send_message(chat_id=chat.id, text=text, parse_mode="HTML")


# ---------------------------------------------------------------------------
# Админские команды: /broadcast, /referrals (только для ADMIN_ID)
# ---------------------------------------------------------------------------
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender_id = update.effective_user.id
    if not is_admin(sender_id):
        return

    admin_state[sender_id] = "broadcast"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="admin_cancel")]])
    await update.message.reply_text(
        "Введите сообщение, которое хотели бы отправить всем, кто есть в "
        "базе.\nМожно использовать текст, картинки, видео и голосовые.",
        reply_markup=kb,
    )


async def referrals_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender_id = update.effective_user.id
    if not is_admin(sender_id):
        return
    admin_state.pop(sender_id, None)
    await update.message.reply_text(
        "Меню системы реферальных ссылок:",
        reply_markup=build_referral_menu(),
    )


async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if not is_admin(user_id):
        await query.answer()
        return

    await query.answer()
    data = query.data

    if data == "ref_menu":
        admin_state.pop(user_id, None)
        await query.edit_message_text("Меню системы реферальных ссылок:", reply_markup=build_referral_menu())

    elif data == "ref_exit":
        admin_state.pop(user_id, None)
        await query.edit_message_text("Выход.")

    elif data == "ref_create":
        admin_state[user_id] = "ref_create"
        await query.edit_message_text("Введите название ссылки:", reply_markup=build_back_exit_kb())

    elif data == "ref_delete":
        admin_state[user_id] = "ref_delete"
        await query.edit_message_text("Введите ссылку или её название:", reply_markup=build_back_exit_kb())

    elif data == "ref_stat_one":
        admin_state[user_id] = "ref_stat_one"
        await query.edit_message_text("Введите ссылку или её название:", reply_markup=build_back_exit_kb())

    elif data == "ref_stat_all":
        admin_state.pop(user_id, None)
        links = await get_all_referral_links()
        stats = await get_referral_stats()
        if not links:
            text = "Реферальных ссылок пока нет."
        else:
            lines = ["Статистика по всем ссылкам:"]
            for code in links:
                lines.append(f"{code}: {stats.get(code, 0)} чел.")
            text = "\n".join(lines)
        await query.edit_message_text(text, reply_markup=build_back_exit_kb())

    elif data == "admin_cancel":
        admin_state.pop(user_id, None)
        await query.edit_message_text("Отменено.")


async def admin_text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ловит следующее сообщение админа, если бот ждёт от него ввод
    (после /broadcast или одной из кнопок меню /referrals). Для всех
    остальных (не-админов или без ожидаемого ввода) — ничего не делает.

    Также ловит числовые Telegram ID, отправленные reply-ом на сообщение
    бота во время активного черновика /convene — добавляет этого
    пользователя в список получателей (см. ConveneUserByID)."""
    user_id = update.effective_user.id
    message = update.message
    text = (message.text or "").strip()

    # --- Ввод для /encode и /decode ---
    if await handle_codec_text(update, context):
        return

    # --- Добавление пользователя по Telegram ID в активный /convene ---
    # Условия: текст состоит только из цифр, отправлен reply-ом на
    # сообщение бота, у пользователя есть активный черновик /convene,
    # длина ID в диапазоне 5–12 цифр. Если длина не подходит — просто
    # игнорируем (не реагируем), чтобы не мешать.
    if (
        text.isdigit()
        and user_id in pending_convene_drafts
        and message.reply_to_message
        and message.reply_to_message.from_user
        and message.reply_to_message.from_user.id == context.bot.id
    ):
        if len(text) < 5 or len(text) > 12:
            # Похоже, это не Telegram ID — молча игнорируем
            pass
        else:
            target_id = int(text)
            data = pending_convene_drafts[user_id]
            if target_id in data["collected"]:
                await message.reply_text(
                    f"Пользователь с ID {target_id} уже в списке.",
                    reply_markup=build_convene_keyboard(data["request_id"]),
                )
                return
            data["collected"][target_id] = ConveneUserByID(target_id)
            count = len(data["collected"])
            await message.reply_text(
                f"Добавлен пользователь с ID {target_id}.\n"
                f"Сейчас выбрано: {count} чел.\n"
                "Можно добавить ещё, либо нажать «Готово».",
                reply_markup=build_convene_keyboard(data["request_id"]),
            )
            return

    # --- Админский ввод (broadcast, referrals) ---
    state = admin_state.get(user_id)
    if not state or not is_admin(user_id):
        return

    if state == "broadcast":
        admin_state.pop(user_id, None)
        users = await get_all_bot_users()
        sent = failed = 0
        for uid in users:
            try:
                await context.bot.copy_message(
                    chat_id=uid, from_chat_id=message.chat.id, message_id=message.message_id,
                )
                sent += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.05)
        await message.reply_text(f"Готово. Отправлено: {sent}, не удалось: {failed}.")
        return

    text = (message.text or "").strip()

    if state == "ref_create":
        admin_state.pop(user_id, None)
        if not text or " " in text:
            await message.reply_text(
                "Название не должно содержать пробелов. Откройте /referrals ещё раз.",
            )
            return
        await create_referral_link(text)
        bot_info = await context.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start={text}"
        await message.reply_text(f"Ссылка создана:\n{link}", reply_markup=build_back_exit_kb())

    elif state == "ref_delete":
        admin_state.pop(user_id, None)
        code = extract_ref_code(text)
        ok = await delete_referral_link(code)
        await message.reply_text(
            f"Ссылка «{code}» удалена." if ok else "Не удалось удалить (возможно, такой ссылки нет).",
            reply_markup=build_back_exit_kb(),
        )

    elif state == "ref_stat_one":
        admin_state.pop(user_id, None)
        code = extract_ref_code(text)
        stats = await get_referral_stats()
        count = stats.get(code, 0)
        await message.reply_text(f"«{code}»: {count} чел.", reply_markup=build_back_exit_kb())



# ---------------------------------------------------------------------------
# /encode и /decode — текстовые преобразования и XOR-обфускация
# ---------------------------------------------------------------------------
codec_state: dict[int, dict] = {}
codec_python_payloads: dict[int, dict] = {}
_codec_payload_counter = itertools.count(1)

CODEC_METHODS = {
    "url": "URL",
    "base64": "Base64",
    "hex": "Hex",
    "binary": "Бинарный",
    "xor": "XOR",
    "xor_py": "XOR → Python-код",
}


def codec_keyboard(action: str) -> InlineKeyboardMarkup:
    methods = ["url", "base64", "hex", "binary", "xor"]
    if action == "encode":
        methods.append("xor_py")
    labels = {
        "url": "🔗 URL",
        "base64": "🔐 Base64",
        "hex": "🔢 Hex",
        "binary": "💻 Бинарный",
        "xor": "⚡ XOR",
        "xor_py": "🐍 XOR → Python-код",
    }
    rows = [[InlineKeyboardButton(labels[m], callback_data=f"codec_{action}_{m}")]
            for m in methods]
    rows.append([InlineKeyboardButton("✖️ Отмена", callback_data="codec_cancel")])
    return InlineKeyboardMarkup(rows)


async def encode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    codec_state.pop(update.effective_user.id, None)
    await update.effective_message.reply_text(
        "Выбери способ кодирования:",
        reply_markup=codec_keyboard("encode"),
    )


async def decode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    codec_state.pop(update.effective_user.id, None)
    await update.effective_message.reply_text(
        "Выбери способ декодирования:",
        reply_markup=codec_keyboard("decode"),
    )


def python_decode_code(method: str, payload: dict) -> str:
    encoded = payload.get("encoded", "")
    if method == "url":
        return (
            "from urllib.parse import unquote\n\n"
            f"encoded = {encoded!r}\n"
            "decoded = unquote(encoded, encoding=\"utf-8\", errors=\"strict\")\n"
            "print(decoded)"
        )
    if method == "base64":
        return (
            "import base64\n\n"
            f"encoded = {encoded!r}\n"
            "decoded = base64.b64decode(encoded, validate=True).decode(\"utf-8\")\n"
            "print(decoded)"
        )
    if method == "hex":
        return (
            f"encoded = {encoded!r}\n"
            "decoded = bytes.fromhex(encoded).decode(\"utf-8\")\n"
            "print(decoded)"
        )
    if method == "binary":
        return (
            f"encoded = {encoded!r}\n"
            "decoded = bytes(int(bit, 2) for bit in encoded.split()).decode(\"utf-8\")\n"
            "print(decoded)"
        )
    if method == "xor":
        return (
            f"X = {payload['numbers']!r}\n"
            f"Y = {payload['key']}\n\n"
            "def decode():\n"
            "    return \"\".join(chr(n ^ Y) for n in X)\n\n"
            "print(decode())"
        )
    raise ValueError("Неизвестный метод кодирования")


CODEC_LANGUAGES = [
    ("python", "🐍 Python", "py"), ("cpp", "➕ C++", "cpp"),
    ("csharp", "🔷 C#", "cs"), ("java", "☕ Java", "java"),
    ("javascript", "🟨 JavaScript", "js"), ("typescript", "🔹 TypeScript", "ts"),
    ("go", "🔵 Go", "go"), ("php", "🐘 PHP", "php"),
    ("ruby", "💎 Ruby", "rb"), ("rust", "🦀 Rust", "rs"),
    ("kotlin", "🟣 Kotlin", "kt"), ("swift", "🍎 Swift", "swift"),
    ("c", "🔧 C", "c"),
]
CODEC_LANG_PAGE_SIZE = 7


def language_keyboard(payload_id: int, method: str, page: int = 0) -> InlineKeyboardMarkup:
    pages = (len(CODEC_LANGUAGES) + CODEC_LANG_PAGE_SIZE - 1) // CODEC_LANG_PAGE_SIZE
    page = max(0, min(page, pages - 1))
    subset = CODEC_LANGUAGES[page * CODEC_LANG_PAGE_SIZE:(page + 1) * CODEC_LANG_PAGE_SIZE]
    rows = []
    for i in range(0, len(subset), 2):
        rows.append([InlineKeyboardButton(label, callback_data=f"codec_lang_{method}_{lang}_{payload_id}")
                     for lang, label, _ext in subset[i:i + 2]])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"codec_langpage_{method}_{payload_id}_{page-1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("Вперёд ➡️", callback_data=f"codec_langpage_{method}_{payload_id}_{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("✖️ Закрыть", callback_data="codec_cancel")])
    return InlineKeyboardMarkup(rows)


def rename_code_identifiers(code: str, replacements: dict[str, str]) -> str:
    """Rename identifiers without changing text inside quoted literals."""
    out = []
    i = 0
    quote_char = None
    escaped = False
    line_comment = False
    block_comment = False
    while i < len(code):
        ch = code[i]
        nxt = code[i + 1] if i + 1 < len(code) else ""
        if line_comment:
            out.append(ch)
            if ch == "\n":
                line_comment = False
            i += 1
            continue
        if block_comment:
            out.append(ch)
            if ch == "*" and nxt == "/":
                out.append(nxt)
                i += 2
                block_comment = False
            else:
                i += 1
            continue
        if quote_char:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote_char:
                quote_char = None
            i += 1
            continue
        if ch == "/" and nxt == "/":
            out.extend([ch, nxt]); i += 2; line_comment = True; continue
        if ch == "/" and nxt == "*":
            out.extend([ch, nxt]); i += 2; block_comment = True; continue
        if ch in ("'", '"', "`"):
            quote_char = ch
            out.append(ch)
            i += 1
            continue
        if ch == "#":
            # Treat # as a line comment marker (Python/Ruby/shell-style comments).
            out.append(ch); i += 1; line_comment = True; continue
        if ch.isalpha() or ch == "_":
            j = i + 1
            while j < len(code) and (code[j].isalnum() or code[j] == "_"):
                j += 1
            token = code[i:j]
            out.append(replacements.get(token, token))
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def customize_decoder_variables(code: str, method: str, names: list[str], language: str) -> str:
    if method == "xor":
        data_name, key_name = ("x", "y") if language in ("kotlin", "swift", "rust") else ("X", "Y")
        return rename_code_identifiers(code, {data_name: names[0], key_name: names[1]})
    # Different languages use different local names for the encoded input.
    aliases = {
        "python": "encoded", "javascript": "encoded", "typescript": "encoded",
        "java": "encoded", "csharp": "encoded", "swift": "s" if "let s=" in code else "encoded",
        "rust": "s", "cpp": "in" if "istringstream in(" in code else "s",
        "c": "s", "go": "s" if ("url.PathUnescape" in code or "strings.Fields(s)" in code) else "encoded",
        "kotlin": "s" if "val s=" in code else "encoded",
        "php": "encoded", "ruby": "encoded",
    }
    source_name = aliases.get(language, "encoded")
    return rename_code_identifiers(code, {source_name: names[0]})


def language_decode_code(language: str, method: str, payload: dict) -> str:
    """Generate a self-contained decoder in the selected language."""
    encoded = payload.get("encoded", "")
    numbers = payload.get("numbers", [])
    key = payload.get("key", 0)
    # Python is the reference implementation for every supported encoding.
    if language == "python":
        return python_decode_code(method, payload)
    if language in ("javascript", "typescript"):
        ts = language == "typescript"
        prefix = "const" if not ts else "const"
        if method == "url": body = f"const encoded = {encoded!r};\nconsole.log(decodeURIComponent(encoded));"
        elif method == "base64": body = f"const encoded = {encoded!r};\nconsole.log(Buffer.from(encoded, 'base64').toString('utf8'));"
        elif method == "hex": body = f"const encoded = {encoded!r};\nconsole.log(Buffer.from(encoded, 'hex').toString('utf8'));"
        elif method == "binary": body = f"const encoded = {encoded!r};\nconsole.log(Buffer.from(encoded.split(/\\s+/).map(x => parseInt(x, 2))).toString('utf8'));"
        else: body = f"const X = {numbers!r};\nconst Y = {key};\nconsole.log(String.fromCodePoint(...X.map(n => n ^ Y)));"
        if ts and method == "xor": body = body.replace("const X =", "const X: number[] =").replace("const Y =", "const Y: number =")
        return body
    if language == "java":
        if method == "url": return f'import java.net.URLDecoder;\nimport java.nio.charset.StandardCharsets;\nclass Main {{ public static void main(String[] args) throws Exception {{\nString encoded = "{encoded}";\nSystem.out.println(URLDecoder.decode(encoded.replace("+", "%2B"), StandardCharsets.UTF_8));\n}} }}'
        if method == "base64": return f'import java.util.Base64;\nclass Main {{ public static void main(String[] args) {{\nString encoded = "{encoded}";\nSystem.out.println(new String(Base64.getDecoder().decode(encoded), java.nio.charset.StandardCharsets.UTF_8));\n}} }}'
        if method == "hex": return f'class Main {{ public static void main(String[] args) {{\nString encoded = "{encoded}";\nbyte[] b = new byte[encoded.length()/2]; for(int i=0;i<b.length;i++) b[i]=(byte)Integer.parseInt(encoded.substring(i*2,i*2+2),16);\nSystem.out.println(new String(b, java.nio.charset.StandardCharsets.UTF_8));\n}} }}'
        if method == "binary": return f'class Main {{ public static void main(String[] args) {{\nString encoded = "{encoded}"; StringBuilder h=new StringBuilder(); for(String b:encoded.trim().split("\\\\s+")) h.append(String.format("%02x", Integer.parseInt(b,2))); byte[] out=new byte[h.length()/2]; for(int i=0;i<out.length;i++) out[i]=(byte)Integer.parseInt(h.substring(i*2,i*2+2),16); System.out.println(new String(out, java.nio.charset.StandardCharsets.UTF_8));\n}} }}'
        return f'class Main {{ public static void main(String[] args) {{ int[] X={{{", ".join(map(str,numbers))}}}; int Y={key}; StringBuilder s=new StringBuilder(); for(int n:X) s.appendCodePoint(n^Y); System.out.println(s); }} }}'
    if language == "csharp":
        if method == "url": return f'using System;\nclass Program {{ static void Main() {{ string encoded = @"{encoded}"; Console.WriteLine(Uri.UnescapeDataString(encoded)); }} }}'
        if method == "base64": return f'using System;\nusing System.Text;\nclass Program {{ static void Main() {{ string encoded = "{encoded}"; Console.WriteLine(Encoding.UTF8.GetString(Convert.FromBase64String(encoded))); }} }}'
        if method == "hex": return f'using System;\nusing System.Text;\nclass Program {{ static void Main() {{ string encoded = "{encoded}"; Console.WriteLine(Encoding.UTF8.GetString(Convert.FromHexString(encoded))); }} }}'
        if method == "binary": return f'using System;\nusing System.Linq;\nusing System.Text;\nclass Program {{ static void Main() {{ string encoded = "{encoded}"; byte[] b = encoded.Split(new[] {{ \' \' }}, StringSplitOptions.RemoveEmptyEntries).Select(x => Convert.ToByte(x,2)).ToArray(); Console.WriteLine(Encoding.UTF8.GetString(b)); }} }}'
        return f'using System;\nusing System.Text;\nclass Program {{ static void Main() {{ int[] X = new int[] {{ {", ".join(map(str,numbers))} }}; int Y = {key}; var s = new StringBuilder(); foreach(int n in X) s.Append(char.ConvertFromUtf32(n ^ Y)); Console.WriteLine(s); }} }}'
    if language == "go":
        if method == "url": return f'package main\nimport ("fmt"; "net/url")\nfunc main() {{ s, _ := url.PathUnescape("{encoded}"); fmt.Println(s) }}'
        if method == "base64": return f'package main\nimport ("encoding/base64"; "fmt")\nfunc main() {{ encoded := "{encoded}"; b, _ := base64.StdEncoding.DecodeString(encoded); fmt.Println(string(b)) }}'
        if method == "hex": return f'package main\nimport ("encoding/hex"; "fmt")\nfunc main() {{ encoded := "{encoded}"; b, _ := hex.DecodeString(encoded); fmt.Println(string(b)) }}'
        if method == "binary": return f'package main\nimport ("fmt"; "strconv"; "strings"; "bytes")\nfunc main() {{ s := "{encoded}"; var b []byte; for _, x := range strings.Fields(s) {{ n, _ := strconv.ParseUint(x,2,8); b=append(b,byte(n)) }}; fmt.Println(bytes.NewBuffer(b).String()) }}'
        return f'package main\nimport "fmt"\nfunc main() {{ X := []int{{{", ".join(map(str,numbers))}}}; Y := {key}; r:=make([]rune,len(X)); for i,n:=range X {{ r[i]=rune(n^Y) }}; fmt.Println(string(r)) }}'
    if language == "php":
        if method == "url": expr = 'rawurldecode($encoded)'
        elif method == "base64": expr = 'base64_decode($encoded, true)'
        elif method == "hex": expr = 'hex2bin($encoded)'
        elif method == "binary": expr = 'implode(array_map(fn($b) => chr(bindec($b)), explode(" ", $encoded)))'
        else: return f'<?php\n$X = [{", ".join(map(str,numbers))}]; $Y = {key}; $out = ""; foreach ($X as $n) {{ $cp=$n^$Y; $out .= mb_chr($cp, "UTF-8"); }} echo $out;\n?>'
        return f'<?php\n$encoded = "{encoded}";\necho {expr};\n?>'
    if language == "ruby":
        if method == "url": expr = 'URI::DEFAULT_PARSER.unescape(encoded)'; imp = 'require "uri"\n'
        elif method == "base64": expr = 'Base64.decode64(encoded)'; imp = 'require "base64"\n'
        elif method == "hex": expr = 'encoded.pack("H*").force_encoding("UTF-8")'; imp = ''
        elif method == "binary": expr = 'encoded.split.map { |b| b.to_i(2) }.pack("C*").force_encoding("UTF-8")'; imp = ''
        else: return f'X = {numbers!r}\nY = {key}\nputs X.map {{ |n| (n ^ Y).chr(Encoding::UTF_8) }}.join'
        return f'{imp}encoded = {encoded!r}\nputs {expr}'
    if language == "cpp":
        if method == "url": return f'#include <iostream>\n#include <string>\nint main() {{ std::string s = R"({encoded})"; std::string o; for(size_t i=0;i<s.size();++i) {{ if(s[i]==\'%\' && i+2<s.size()) {{ o += (char)std::stoi(s.substr(i+1,2),nullptr,16); i+=2; }} else o+=s[i]; }} std::cout << o; }}'
        if method == "base64": return f'#include <iostream>\n#include <string>\n#include <vector>\nint main() {{ std::string s="{encoded}", chars="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"; std::string out; int val=0,bits=-8; for(unsigned char c:s) {{ if(c==\'=\') break; val=(val<<6)+chars.find(c); bits+=6; if(bits>=0) {{ out.push_back(char((val>>bits)&255)); bits-=8; }} }} std::cout<<out; }}'
        if method == "hex": return f'#include <iostream>\n#include <string>\nint main() {{ std::string s="{encoded}", out; for(size_t i=0;i<s.size();i+=2) out.push_back((char)std::stoi(s.substr(i,2),nullptr,16)); std::cout<<out; }}'
        if method == "binary": return f'#include <iostream>\n#include <sstream>\n#include <string>\nint main() {{ std::istringstream in("{encoded}"); std::string b,out; while(in>>b) out.push_back((char)std::stoi(b,nullptr,2)); std::cout<<out; }}'
        return f'#include <iostream>\n#include <vector>\nstatic void utf8(unsigned int c) {{ if(c<=0x7F) std::cout << char(c); else if(c<=0x7FF) {{ std::cout << char(0xC0|(c>>6)) << char(0x80|(c&63)); }} else if(c<=0xFFFF && !(c>=0xD800 && c<=0xDFFF)) {{ std::cout << char(0xE0|(c>>12)) << char(0x80|((c>>6)&63)) << char(0x80|(c&63)); }} else if(c<=0x10FFFF) {{ std::cout << char(0xF0|(c>>18)) << char(0x80|((c>>12)&63)) << char(0x80|((c>>6)&63)) << char(0x80|(c&63)); }} }}\nint main() {{ int X[]={{ {", ".join(map(str,numbers))} }}; int Y={key}; for(int n:X) utf8((unsigned int)(n^Y)); }}'
    # The remaining languages use standard-library decoder implementations.
    if language == "kotlin":
        if method == "url": return f'import java.net.URLDecoder\nfun main() {{ val encoded="{encoded}"; println(URLDecoder.decode(encoded.replace("+", "%2B"), "UTF-8")) }}'
        if method == "base64": return f'import java.util.Base64\nfun main() {{ val encoded="{encoded}"; println(String(Base64.getDecoder().decode(encoded), Charsets.UTF_8)) }}'
        if method == "hex": return f'fun main() {{ val s="{encoded}"; println(String(s.chunked(2).map {{ it.toInt(16).toByte() }}.toByteArray(), Charsets.UTF_8)) }}'
        if method == "binary": return f'fun main() {{ val s="{encoded}"; println(String(s.split(" ").map {{ it.toInt(2).toByte() }}.toByteArray(), Charsets.UTF_8)) }}'
        return f'fun main() {{ val x=intArrayOf({", ".join(map(str,numbers))}); val y={key}; println(x.map {{ (it xor y).toChar() }}.joinToString("")) }}'
    if language == "swift":
        if method == "url": return f'import Foundation\nlet encoded = "{encoded}"\nprint(encoded.removingPercentEncoding ?? encoded)'
        if method == "base64": return f'import Foundation\nlet encoded = "{encoded}"\nif let data = Data(base64Encoded: encoded), let text = String(data: data, encoding: .utf8) {{ print(text) }}'
        if method == "hex": return f'import Foundation\nlet s="{encoded}"; var b=[UInt8](); var i=s.startIndex; while i < s.endIndex {{ let j=s.index(i, offsetBy:2); b.append(UInt8(s[i..<j], radix:16)!); i=j }}; print(String(decoding:b, as:UTF8.self))'
        if method == "binary": return f'import Foundation\nlet s="{encoded}"; let b=s.split(separator:" ").map {{ UInt8($0,radix:2)! }}; print(String(decoding:b,as:UTF8.self))'
        return f'import Foundation\nlet x=[{", ".join(map(str,numbers))}]; let y={key}; print(String(String.UnicodeScalarView(x.map {{ UnicodeScalar($0 ^ y)! }})))'
    if language == "rust":
        if method == "url": return f'fn main() {{ let s="{encoded}"; println!("{{}}", s.replace("%20", " ")); }} // Для полного URL-декодирования используйте crate urlencoding'
        if method == "base64": return f'// Добавьте crate base64\nfn main() {{ let s="{encoded}"; println!("{{:?}}", base64::decode(s).unwrap()); }}'
        if method == "hex": return f'fn main() {{ let s="{encoded}"; let b: Vec<u8>=(0..s.len()).step_by(2).map(|i| u8::from_str_radix(&s[i..i+2],16).unwrap()).collect(); println!("{{}}", String::from_utf8(b).unwrap()); }}'
        if method == "binary": return f'fn main() {{ let s="{encoded}"; let b: Vec<u8>=s.split_whitespace().map(|x| u8::from_str_radix(x,2).unwrap()).collect(); println!("{{}}", String::from_utf8(b).unwrap()); }}'
        return f'fn main() {{ let x=[{", ".join(map(str,numbers))}]; let y={key}; let s:String=x.iter().map(|n| char::from_u32((n^y) as u32).unwrap()).collect(); println!("{{}}",s); }}'
    if language == "c":
        if method == "hex": return f'#include <stdio.h>\n#include <stdlib.h>\nint main(void) {{ char s[]="{encoded}"; for(int i=0;s[i]&&s[i+1];i+=2) putchar((char)(strtol((char[]){{s[i],s[i+1],0}},0,16))); }}'
        if method == "binary": return f'#include <stdio.h>\n#include <string.h>\nint main(void) {{ char s[]="{encoded}"; char *p=strtok(s," "); while(p) {{ int n=0; for(int i=0;p[i];i++) n=n*2+(p[i]-\'0\'); putchar(n); p=strtok(NULL," "); }} }}'
        if method == "base64": return f'#include <stdio.h>\n#include <string.h>\nint main(void) {{ const char *s="{encoded}"; const char *abc="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"; int val=0,bits=-8; for(size_t i=0;i<strlen(s);i++) {{ unsigned char c=s[i]; if(c==61) break; const char *p=strchr(abc,c); if(!p) continue; val=(val<<6)+(int)(p-abc); bits+=6; if(bits>=0) {{ putchar((val>>bits)&255); bits-=8; }} }} return 0; }}'
        if method == "url": return f'#include <stdio.h>\n#include <stdlib.h>\nint main(void) {{ char s[]="{encoded}"; for(int i=0;s[i];i++) {{ if(s[i]==\'%\' && s[i+1] && s[i+2]) {{ printf("%c",(char)strtol((char[]){{s[i+1],s[i+2],0}},0,16)); i+=2; }} else putchar(s[i]); }} }}'
        return f'#include <stdio.h>\nstatic void utf8(unsigned int c) {{ if(c<=0x7F) putchar(c); else if(c<=0x7FF) {{ putchar(0xC0|(c>>6)); putchar(0x80|(c&63)); }} else if(c<=0xFFFF && !(c>=0xD800 && c<=0xDFFF)) {{ putchar(0xE0|(c>>12)); putchar(0x80|((c>>6)&63)); putchar(0x80|(c&63)); }} else if(c<=0x10FFFF) {{ putchar(0xF0|(c>>18)); putchar(0x80|((c>>12)&63)); putchar(0x80|((c>>6)&63)); putchar(0x80|(c&63)); }} }}\nint main(void) {{ int X[]={{ {", ".join(map(str,numbers))} }}; int Y={key}; for(unsigned long i=0;i<sizeof(X)/sizeof(X[0]);i++) utf8((unsigned int)(X[i]^Y)); }}'
    # C++ is handled above; C# above. Keep a safe explicit error for unknown identifiers.
    raise ValueError("Этот язык пока не поддерживается")


async def codec_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    menu_match = re.fullmatch(r"codec_languages_(url|base64|hex|binary|xor)_(\d+)", data or "")
    if menu_match:
        method, payload_id_text = menu_match.groups()
        payload_id = int(payload_id_text)
        payload = codec_python_payloads.get(payload_id)
        if not payload or payload.get("user_id") != user_id or payload.get("method") != method:
            await query.message.reply_text("Эта кнопка устарела или принадлежит другому пользователю.")
            return
        await query.edit_message_text("Выбери язык программирования для кода расшифровки:", reply_markup=language_keyboard(payload_id, method))
        return

    page_match = re.fullmatch(r"codec_langpage_(url|base64|hex|binary|xor)_(\d+)_(\d+)", data or "")
    if page_match:
        method, payload_id_text, page_text = page_match.groups()
        payload_id, page = int(payload_id_text), int(page_text)
        payload = codec_python_payloads.get(payload_id)
        if not payload or payload.get("user_id") != user_id or payload.get("method") != method:
            await query.message.reply_text("Эта кнопка устарела или принадлежит другому пользователю.")
            return
        await query.edit_message_reply_markup(reply_markup=language_keyboard(payload_id, method, page))
        return

    vars_match = re.fullmatch(r"codec_vars_(url|base64|hex|binary|xor)_([a-z]+)_(\d+)", data or "")
    if vars_match:
        method, language, payload_id_text = vars_match.groups()
        payload_id = int(payload_id_text)
        payload = codec_python_payloads.get(payload_id)
        if not payload or payload.get("user_id") != user_id or payload.get("method") != method:
            await query.message.reply_text("Эта кнопка устарела или принадлежит другому пользователю.")
            return
        codec_state[user_id] = {"action": "custom_vars", "method": method, "language": language, "payload_id": payload_id}
        if method == "xor":
            prompt = ("Отправь два имени переменных через запятую: сначала для массива закодированных чисел, "
                      "затем для XOR-ключа. Например: encoded_values, secret_key")
        else:
            prompt = "Отправь имя переменной, в которой хранится закодированный текст. Например: encoded_text"
        await query.message.reply_text(prompt)
        return

    lang_match = re.fullmatch(r"codec_lang_(url|base64|hex|binary|xor)_([a-z]+)_(\d+)", data or "")
    if lang_match:
        method, language, payload_id_text = lang_match.groups()
        payload_id = int(payload_id_text)
        payload = codec_python_payloads.get(payload_id)
        if not payload or payload.get("user_id") != user_id or payload.get("method") != method:
            await query.message.reply_text("Эта кнопка устарела или принадлежит другому пользователю.")
            return
        try:
            code = language_decode_code(language, method, payload)
        except ValueError:
            await query.message.reply_text("Для этого языка пока нет готового генератора кода.")
            return
        language_info = next((item for item in CODEC_LANGUAGES if item[0] == language), None)
        lang_label = language_info[1] if language_info else language
        code_lang = {"python":"python", "cpp":"cpp", "csharp":"csharp", "java":"java", "javascript":"javascript", "typescript":"typescript", "go":"go", "php":"php", "ruby":"ruby", "rust":"rust", "kotlin":"kotlin", "swift":"swift", "c":"c"}.get(language, "text")
        await query.message.reply_text(
            f"Код расшифровки — {lang_label}:\n" + format_pre(code, code_lang),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                "✏️ Настроить имена переменных",
                callback_data=f"codec_vars_{method}_{language}_{payload_id}"
            )]])
        )
        return

    if data == "codec_cancel":
        codec_state.pop(user_id, None)
        await query.edit_message_text("Операция отменена.")
        return

    match = re.fullmatch(r"codec_(encode|decode)_([a-z]+)", data or "")
    if not match:
        return
    action, method = match.groups()
    codec_state[user_id] = {"action": action, "method": method}

    if method in ("xor", "xor_py") and action == "encode":
        codec_state[user_id]["stage"] = "key"
        await query.edit_message_text(
            "Введи числовой XOR-ключ (например, 162). Ключ будет отдельно от текста."
        )
    elif method == "xor" and action == "decode":
        codec_state[user_id]["stage"] = "key"
        await query.edit_message_text(
            "Введи числовой XOR-ключ Y. Затем отдельно отправь массив чисел X."
        )
    else:
        codec_state[user_id]["stage"] = "text"
        prompt = "Отправь текст для кодирования." if action == "encode" else "Отправь закодированный текст."
        await query.edit_message_text(prompt)


def format_pre(text: str, language: str) -> str:
    return f'<pre><code class="language-{language}">{html.escape(text)}</code></pre>'


def save_codec_python_payload(user_id: int, method: str, **payload_data) -> int:
    payload_id = next(_codec_payload_counter)
    codec_python_payloads[payload_id] = {"user_id": user_id, "method": method, **payload_data}
    while len(codec_python_payloads) > 100:
        codec_python_payloads.pop(min(codec_python_payloads))
    return payload_id


async def handle_codec_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Обрабатывает текстовый ввод активной операции кодирования/декодирования."""
    message = update.effective_message
    user_id = update.effective_user.id
    state = codec_state.get(user_id)
    if not state or not message or not message.text or message.text.startswith("/"):
        return False

    value = message.text.strip()
    action, method, stage = state["action"], state["method"], state.get("stage", "text")

    if action == "custom_vars":
        parts = [part.strip() for part in value.split(",")]
        expected = 2 if method == "xor" else 1
        if len(parts) != expected or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) for part in parts):
            example = "encoded_values, secret_key" if method == "xor" else "encoded_text"
            await message.reply_text(
                f"Нужно указать {'два' if expected == 2 else 'одно'} корректное имя переменной "
                f"(латинские буквы, цифры и _, первый символ — буква или _). Пример: {example}"
            )
            return True
        reserved_names = {
            "class", "def", "return", "if", "else", "for", "while", "switch", "case",
            "int", "float", "double", "char", "string", "void", "public", "private",
            "static", "const", "let", "var", "new", "this", "function", "import",
            "from", "as", "package", "func", "fn", "fun", "val", "var", "mut", "self",
            "true", "false", "null", "None", "True", "False", "break", "continue",
        }
        if any(part in reserved_names for part in parts):
            await message.reply_text("Это имя зарезервировано в одном или нескольких языках. Выбери другое.")
            return True
        if len(set(parts)) != len(parts):
            await message.reply_text("Имена переменных должны отличаться друг от друга. Попробуй ещё раз.")
            return True
        payload_id = state["payload_id"]
        payload = codec_python_payloads.get(payload_id)
        if not payload or payload.get("user_id") != user_id or payload.get("method") != method:
            codec_state.pop(user_id, None)
            await message.reply_text("Эти данные устарели. Запусти /encode ещё раз.")
            return True
        try:
            code = language_decode_code(state["language"], method, payload)
            code = customize_decoder_variables(code, method, parts, state["language"])
        except ValueError:
            await message.reply_text("Не удалось подготовить код для этого языка.")
            return True
        codec_state.pop(user_id, None)
        lang_info = next((item for item in CODEC_LANGUAGES if item[0] == state["language"]), None)
        lang_label = lang_info[1] if lang_info else state["language"]
        code_lang = {"python":"python", "cpp":"cpp", "csharp":"csharp", "java":"java", "javascript":"javascript", "typescript":"typescript", "go":"go", "php":"php", "ruby":"ruby", "rust":"rust", "kotlin":"kotlin", "swift":"swift", "c":"c"}.get(state["language"], "text")
        await message.reply_text(f"Код расшифровки — {lang_label} (с твоими именами переменных):\n" + format_pre(code, code_lang), parse_mode="HTML")
        return True

    if stage == "key":
        if not re.fullmatch(r"\d{1,5}", value) or int(value) > 65535:
            await message.reply_text("Ключ должен быть целым числом от 0 до 65535. Попробуй ещё раз.")
            return True
        state["key"] = int(value)
        state["stage"] = "text"
        prompt = (
            "Теперь отправь исходный текст."
            if action == "encode"
            else "Теперь отправь массив X — например [229, 205, 206]. Можно прислать только числа через запятую."
        )
        await message.reply_text(prompt)
        return True

    try:
        if action == "encode":
            if method == "url":
                result = quote(value, safe="")
                payload_id = save_codec_python_payload(user_id, method, encoded=result)
                await message.reply_text(
                    format_pre(result, "text"), parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧩 Выдать код расшифровки", callback_data=f"codec_languages_url_{payload_id}")]])
                )
            elif method == "base64":
                result = base64.b64encode(value.encode("utf-8")).decode("ascii")
                payload_id = save_codec_python_payload(user_id, method, encoded=result)
                await message.reply_text(
                    format_pre(result, "text"), parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧩 Выдать код расшифровки", callback_data=f"codec_languages_base64_{payload_id}")]])
                )
            elif method == "hex":
                result = value.encode("utf-8").hex()
                payload_id = save_codec_python_payload(user_id, method, encoded=result)
                await message.reply_text(
                    format_pre(result, "text"), parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧩 Выдать код расшифровки", callback_data=f"codec_languages_hex_{payload_id}")]])
                )
            elif method == "binary":
                result = " ".join(format(byte, "08b") for byte in value.encode("utf-8"))
                payload_id = save_codec_python_payload(user_id, method, encoded=result)
                await message.reply_text(
                    format_pre(result, "text"), parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧩 Выдать код расшифровки", callback_data=f"codec_languages_binary_{payload_id}")]])
                )
            elif method in ("xor", "xor_py"):
                key = state["key"]
                numbers = [ord(char) ^ key for char in value]
                array = "X = [" + ", ".join(map(str, numbers)) + "]"
                if method == "xor":
                    result = f"{array}\nY = {key}"
                    payload_id = save_codec_python_payload(user_id, method, numbers=numbers, key=key)
                    await message.reply_text(
                        format_pre(result, "xor"), parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧩 Выдать код расшифровки", callback_data=f"codec_languages_xor_{payload_id}")]])
                    )
                else:
                    result = (
                        f"{array}\nY = {key}\n\n"
                        "def decode():\n"
                        "    return \"\".join(chr(n ^ Y) for n in X)\n\n"
                        "print(decode())"
                    )
                    await message.reply_text(format_pre(result, "python"), parse_mode="HTML")
        else:
            if method == "url":
                result = unquote(value, encoding="utf-8", errors="strict")
            elif method == "base64":
                result = base64.b64decode(value, validate=True).decode("utf-8")
            elif method == "hex":
                result = bytes.fromhex(value).decode("utf-8")
            elif method == "binary":
                bits = re.findall(r"[01]{8}", value)
                if not bits or re.sub(r"[01\s]", "", value):
                    raise ValueError("Ожидаются байты по 8 бит, разделённые пробелами.")
                result = bytes(int(bit, 2) for bit in bits).decode("utf-8")
            elif method == "xor":
                nums = [int(n) for n in re.findall(r"-?\d+", value)]
                if not nums:
                    raise ValueError("Не найден массив чисел X.")
                key = state["key"]
                result = "".join(chr(number ^ key) for number in nums)
            await message.reply_text(result)
        codec_state.pop(user_id, None)
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        await message.reply_text(
            f"Не удалось обработать данные: {html.escape(str(exc))}\n"
            "Операция сброшена. Запусти команду заново: /encode или /decode.",
            parse_mode="HTML",
        )
        codec_state.pop(user_id, None)
    except Exception:
        logger.exception("Ошибка в обработчике encode/decode")
        await message.reply_text("Не удалось обработать данные. Попробуй начать заново.")
        codec_state.pop(user_id, None)
    return True


# ---------------------------------------------------------------------------
# Глобальный обработчик ошибок: если при обработке любой команды что-то
# сломалось, автору команды приходит понятное эфемерное сообщение об этом
# (а не полная тишина, когда разобраться может только тот, у кого есть
# доступ к логам Render).
# ---------------------------------------------------------------------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Необработанная ошибка при обработке апдейта: %s", context.error, exc_info=context.error)

    if not isinstance(update, Update):
        return
    if not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    try:
        await send_ephemeral(
            context, chat_id, user_id,
            "⚠️ Не получилось обработать команду — что-то пошло не так на "
            "стороне бота.\n\nПроверьте формат команды (/start покажет "
            "подсказку) и попробуйте ещё раз. Если ошибка повторится — "
            "сообщите об этом администратору бота.",
        )
    except Exception as e:
        logger.error("Не удалось отправить сообщение об ошибке пользователю: %s", e)


# ---------------------------------------------------------------------------
# Запуск через webhook
# ---------------------------------------------------------------------------
async def post_init(application: Application):
    global http_session
    http_session = aiohttp.ClientSession()
    await register_ephemeral_commands()


async def register_ephemeral_commands():
    """Регистрирует команды раздельно для личных чатов и для групп:
    - В личных чатах эфемерность не нужна (там и так видно только
      пользователю), а Telegram, судя по всему, не показывает команды
      с is_ephemeral в меню личных чатов вообще — поэтому там регистрируем
      обычный (без флага) список, чтобы меню отображалось.
    - В группах регистрируем с is_ephemeral: true — тогда и сама команда,
      которую вводит пользователь, видна только ему."""
    base_commands = [
        {"command": "start", "description": "Начало работы с ботом"},
        {"command": "repeat", "description": "Запланировать повторение текста/медиа"},
        {"command": "list", "description": "Показать активные повторения"},
        {"command": "cancel", "description": "Отменить повторение по номеру"},
        {"command": "whisper", "description": "Приватное сообщение человеку"},
        {"command": "id", "description": "Узнать свой ID или ID другого (по ответу)"},
        {"command": "convene", "description": "Выбрать получателей для сообщения (в личке)"},
        {"command": "send", "description": "Отправить подготовленное /convene сообщение сюда"},
        {"command": "encode", "description": "Закодировать текст"},
        {"command": "decode", "description": "Декодировать текст"},
    ]
    # /convene используется в личке (там эфемерность не нужна), а /send в
    # группе прячем — видно только итоговое сообщение с упоминаниями.
    ephemeral_names = {"start", "repeat", "list", "cancel", "whisper", "send", "id", "encode", "decode"}
    # /convene не имеет смысла в группе (кнопка выбора людей работает
    # только в личке) — не показываем её в списке команд для групп
    group_only_excluded = {"convene"}
    group_commands = [
        {**cmd, "is_ephemeral": True} if cmd["command"] in ephemeral_names else cmd
        for cmd in base_commands
        if cmd["command"] not in group_only_excluded
    ]

    private_result = await safe_api_request(
        "setMyCommands",
        {"commands": base_commands, "scope": {"type": "all_private_chats"}},
    )
    group_result = await safe_api_request(
        "setMyCommands",
        {"commands": group_commands, "scope": {"type": "all_group_chats"}},
    )

    if private_result.get("ok"):
        logger.info("Команды для личных чатов зарегистрированы")
    else:
        logger.warning("Не удалось зарегистрировать команды для личных чатов (%s)", private_result.get("description"))

    if group_result.get("ok"):
        logger.info("Эфемерные команды для групп зарегистрированы")
    else:
        logger.warning(
            "Не удалось зарегистрировать эфемерные команды для групп (%s) — "
            "команды останутся видимыми всем в группе, но ответы бота всё "
            "равно будут эфемерными", group_result.get("description"),
        )


async def post_shutdown(application: Application):
    if http_session is not None:
        await http_session.close()


def build_application() -> Application:
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("repeat", repeat_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CommandHandler("whisper", whisper_command))
    application.add_handler(CommandHandler("id", id_command))
    application.add_handler(CommandHandler("convene", convene_command))
    application.add_handler(CommandHandler("send", send_command))
    application.add_handler(CommandHandler("encode", encode_command))
    application.add_handler(CommandHandler("decode", decode_command))
    application.add_handler(CallbackQueryHandler(codec_callback_handler, pattern="^codec_"))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("referrals", referrals_command))
    application.add_handler(MessageHandler(filters.StatusUpdate.USERS_SHARED, on_users_shared))
    application.add_handler(MessageHandler(filters.StatusUpdate.CHAT_SHARED, on_id_chat_shared))
    application.add_handler(MessageHandler(filters.Text(["Закрыть меню"]), close_id_menu))
    application.add_handler(MessageHandler(filters.Text([CONVENE_DONE_BUTTON]), on_convene_done_button))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^(ref_|admin_cancel)"))
    # Ловит следующее сообщение админа во время ожидания ввода — обязательно
    # регистрируется ПОСЛЕДНИМ, чтобы не перехватывать апдейты, которые
    # должны обрабатываться другими, более специфичными хендлерами выше.
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, admin_text_input_handler))
    application.add_error_handler(error_handler)
    return application


def main():
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN (переменная окружения)")
    if not WEBHOOK_HOST:
        raise RuntimeError("Не задан WEBHOOK_HOST (переменная окружения)")
    if not WEBHOOK_HOST.startswith("https://"):
        raise RuntimeError(f"WEBHOOK_HOST должен начинаться с https:// , сейчас: {WEBHOOK_HOST!r}")

    # Пауза перед стартом снижает риск попасть под временное ограничение
    # частоты запросов Telegram (флуд-контроль) после частых перезапусков.
    startup_delay = int(os.environ.get("STARTUP_DELAY_SECONDS", "10"))
    logger.info("Жду %s сек. перед стартом", startup_delay)
    time.sleep(startup_delay)

    webhook_url = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
    logger.info("Бот запускается через webhook: %r", webhook_url)

    application = build_application()
    # webhook_url передаём напрямую сюда — библиотека сама один раз
    # надёжно устанавливает вебхук при старте, без наших ручных повторов
    # (повторные вызовы run_webhook в одном процессе небезопасны и ломают
    # внутренний event loop — именно это происходило раньше).
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
        secret_token=WEBHOOK_SECRET or None,
        webhook_url=webhook_url,
    )


if __name__ == "__main__":
    main()
