import os
import time
import asyncio
import logging
import itertools
import random

import aiohttp
from telegram import (
    Update,
    KeyboardButton,
    KeyboardButtonRequestUsers,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.error import RetryAfter
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

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

http_session: aiohttp.ClientSession | None = None


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
        "/id — узнать свой ID, или ID другого человека (ответом на его "
        "сообщение)\n\n"
        "/convene Текст — здесь, в личке, выбери получателей (жми "
        "«Добавить получателей» сколько угодно раз, до 10 за раз, затем "
        "«Готово»), затем зайди в нужную группу и напиши там /send — "
        "сообщение с упоминаниями уйдёт туда.",
    )


# ---------------------------------------------------------------------------
# /id — узнать свой Telegram ID или ID другого человека (по reply)
# ---------------------------------------------------------------------------
async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    sender_id = update.effective_user.id
    message = update.message

    if message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user
        safe_name = target.full_name.replace("<", "&lt;").replace(">", "&gt;")
        text = f"{safe_name}: <code>{target.id}</code>"
    else:
        text = f"Ваш Telegram ID: <code>{sender_id}</code>"

    # Эфемерно в любом случае — видно только тому, кто спросил
    await send_ephemeral(context, chat_id, sender_id, text)


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
        "(до 10 человек за раз). Когда выберешь всех — жми «Готово».",
        reply_markup=build_convene_keyboard(request_id),
    )


async def on_users_shared(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    shared = message.users_shared
    sender_id = message.from_user.id

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
    ]
    # /convene используется в личке (там эфемерность не нужна), а /send в
    # группе прячем — видно только итоговое сообщение с упоминаниями.
    ephemeral_names = {"start", "repeat", "list", "cancel", "whisper", "send", "id"}
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
    application.add_handler(MessageHandler(filters.StatusUpdate.USERS_SHARED, on_users_shared))
    application.add_handler(MessageHandler(filters.Text([CONVENE_DONE_BUTTON]), on_convene_done_button))
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
