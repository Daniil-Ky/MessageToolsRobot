import os
import time
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


# ---------------------------------------------------------------------------
# Эфемерные сообщения: видны только указанному пользователю.
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

    data = await safe_api_request("sendMessage", payload)
    if not data.get("ok"):
        logger.warning("Эфемерное сообщение не отправилось (%s), использую обычное с автоудалением",
                        data.get("description"))
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
        "<b>Команды:</b>\n"
        "/repeat количество интервал\nтекст на след. строке\n"
        "(или ответь на медиа той же командой)\n\n"
        "/list — активные повторения\n"
        "/cancel номер — отменить повторение\n\n"
        "/whisper @username текст — приватное сообщение\n"
        "/whisper текст (ответом на чьё-то сообщение) — то же самое\n"
        "(можно приложить фото/видео/стикер вместо текста)",
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
                "Альтернатива: ответь (reply) на его сообщение командой "
                "/whisper текст.",
            )
            return
    else:
        await send_ephemeral(
            context, chat_id, sender_id,
            "Формат команды:\n"
            "/whisper @username текст\n"
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
    ]
    group_commands = [{**cmd, "is_ephemeral": True} for cmd in base_commands]

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
