import os
import asyncio
import logging

import aiohttp
from telegram import Update
from telegram.error import RetryAfter
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_HOST = os.environ.get("WEBHOOK_HOST", "").rstrip("/")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET or 'hook'}"

API_BASE = f"https://telegram.org{BOT_TOKEN}"

http_session: aiohttp.ClientSession | None = None

# ---------------------------------------------------------------------------
# Вспомогательная функция для безопасных HTTP-запросов к Telegram API
# ---------------------------------------------------------------------------
async def safe_api_request(endpoint: str, payload: dict) -> dict:
    """Выполняет POST-запрос к API Telegram с автоматическим учетом RetryAfter."""
    assert http_session is not None
    url = f"{API_BASE}/{endpoint}"
    
    for attempt in range(5):
        try:
            async with http_session.post(url, json=payload) as resp:
                # Telegram может вернуть 429 Too Many Requests
                if resp.status == 429:
                    data = await resp.json()
                    retry_after = data.get("parameters", {}).get("retry_after", 1)
                    logger.warning("Получен статус 429 (aiohttp). Ожидание %s сек.", retry_after)
                    await asyncio.sleep(retry_after + 0.2)
                    continue
                    
                return await resp.json()
        except Exception as e:
            logger.warning("Ошибка сети при запросе к %s: %s. Пробую снова...", endpoint, e)
            await asyncio.sleep(1)
            
    return {"ok": False, "description": "Превышено количество попыток запроса"}

# ---------------------------------------------------------------------------
# Декоратор для защиты вызовов стандартных методов Telegram от RetryAfter
# ---------------------------------------------------------------------------
def retry_on_flood(func):
    """Декоратор для асинхронных функций, перехватывающий ошибку RetryAfter."""
    async def wrapper(*args, **kwargs):
        for attempt in range(5):
            try:
                return await func(*args, **kwargs)
            except RetryAfter as e:
                wait_time = e.retry_after + 0.2
                logger.warning("Флуд-контроль Telegram API. Ожидание %s сек.", wait_time)
                await asyncio.sleep(wait_time)
            except Exception as e:
                # Пропускаем стандартные ошибки дальше
                raise e
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
    if not message or not message.caption:
        return None
    if message.caption_entities:
        return message.caption_html
    return message.caption


def get_repeat_text_content(message):
    full_text = message.text or ""
    if message.entities:
        full_html = message.text_html
        _, _, html_after = full_html.partition("\n")
        return html_after
    _, _, plain_after = full_text.partition("\n")
    return plain_after


# ---------------------------------------------------------------------------
# Эфемерные сообщения с защитой от флуда
# ---------------------------------------------------------------------------
async def send_ephemeral(context: ContextTypes.DEFAULT_TYPE, chat_id: int, receiver_user_id: int, text: str):
    chat = await context.bot.get_chat(chat_id)

    if chat.type == "private":
        await retry_on_flood(context.bot.send_message)(chat_id=chat_id, text=text, parse_mode="HTML")
        return

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "ephemeral_message_parameters": {"receiver_user_id": receiver_user_id},
    }

    try:
        data = await safe_api_request("sendMessage", payload)
        if not data.get("ok"):
            raise RuntimeError(data.get("description", "unknown error"))
    except Exception as e:
        logger.warning("Эфемерное сообщение не отправилось (%s), использую обычное с автоудалением", e)
        sent = await retry_on_flood(context.bot.send_message)(chat_id=chat_id, text=text, parse_mode="HTML")
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

    try:
        data = await safe_api_request(EPHEMERAL_ENDPOINTS[media_type], payload)
        if not data.get("ok"):
            raise RuntimeError(data.get("description", "unknown error"))
    except Exception as e:
        logger.warning("Эфемерное медиа не отправилось (%s), использую обычное", e)
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
# Логика повторяющихся сообщений с защитой от флуда
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
            await retry_on_flood(context.bot.send_message)(chat_id=job.chat_id, text=data["content"], parse_mode="HTML")
    except Exception as e:
        logger.error("Критическая ошибка при отправке повтора в job %s: %s", job.name, e)

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
            "<b>Для медиа</b>:\n"
            "ответь на медиа-сообщение командой:\n"
            "/repeat количество интервал_в_секундах",
        )
        return

    try:
        count = int(args[0])
        interval = int(args[1])
    except ValueError:
        print("Произошла ошибка ValueError")
