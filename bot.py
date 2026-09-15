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

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Общая aiohttp-сессия для "сырых" вызовов Bot API (эфемерные сообщения),
# которые пока не поддерживаются классом Bot из python-telegram-bot.
http_session: aiohttp.ClientSession | None = None


# ---------------------------------------------------------------------------
# Отправка статусных сообщений: эфемерные (видны только автору команды),
# с запасным вариантом, если эфемерные сообщения недоступны в этом чате.
# ---------------------------------------------------------------------------
async def send_status(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, text: str):
    chat = await context.bot.get_chat(chat_id)

    # В личном чате и так видно только пользователю — эфемерность не нужна.
    if chat.type == "private":
        await context.bot.send_message(chat_id=chat_id, text=text)
        return

    payload = {
        "chat_id": chat_id,
        "text": text,
        "ephemeral_message_parameters": {"receiver_user_id": user_id},
    }

    try:
        assert http_session is not None
        async with http_session.post(f"{API_BASE}/sendMessage", json=payload) as resp:
            data = await resp.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description", "unknown error"))
        logger.info("Эфемерное сообщение отправлено пользователю %s", user_id)
    except Exception as e:
        # Например, Bot API этой версии/региона ещё не поддерживает
        # эфемерные сообщения — отправляем обычное и удаляем через минуту.
        logger.warning("Эфемерное сообщение не отправилось (%s), использую обычное", e)
        sent = await context.bot.send_message(chat_id=chat_id, text=text)
        context.job_queue.run_once(
            delete_message_callback,
            when=60,
            data={"chat_id": chat_id, "message_id": sent.message_id},
        )


async def delete_message_callback(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    try:
        await context.bot.delete_message(chat_id=data["chat_id"], message_id=data["message_id"])
    except Exception as e:
        logger.warning("Не удалось удалить сообщение: %s", e)


# ---------------------------------------------------------------------------
# Логика повторяющихся сообщений
# ---------------------------------------------------------------------------
async def repeat_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data

    await context.bot.send_message(chat_id=job.chat_id, text=data["text"])
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

    if len(args) < 3:
        await send_status(
            context, chat_id, user_id,
            "Формат команды:\n"
            "/repeat текст количество_повторений интервал_в_секундах\n\n"
            "Пример:\n"
            "/repeat Ежедневный бонус 10 86400",
        )
        return

    try:
        count = int(args[-2])
        interval = int(args[-1])
    except ValueError:
        await send_status(
            context, chat_id, user_id,
            "Количество повторений и интервал должны быть числами.\n"
            "Пример: /repeat Ежедневный бонус 10 86400",
        )
        return

    text = " ".join(args[:-2]).strip()

    if not text:
        await send_status(context, chat_id, user_id, "Не указан текст сообщения.")
        return

    if count <= 0:
        await send_status(context, chat_id, user_id, "Количество повторений должно быть больше 0.")
        return

    if interval < 5:
        await send_status(
            context, chat_id, user_id,
            "Интервал слишком маленький, укажи хотя бы 5 секунд.",
        )
        return

    chat_data = context.chat_data
    repeats = chat_data.setdefault("repeats", {})

    job_index = chat_data.get("next_index", 1)
    chat_data["next_index"] = job_index + 1
    job_name = f"repeat_{chat_id}_{job_index}"

    job_data = {"text": text, "remaining": count, "sent": 0, "interval": interval}

    context.job_queue.run_repeating(
        repeat_callback,
        interval=interval,
        first=0,
        chat_id=chat_id,
        name=job_name,
        data=job_data,
    )

    repeats[job_name] = job_data

    await send_status(
        context, chat_id, user_id,
        f"Принято.\nТекст: {text}\nПовторений: {count}\nИнтервал: {interval} сек.\n"
        f"Номер задачи: {job_index} (посмотреть /list, отменить /cancel {job_index})",
    )


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    chat_data = context.chat_data
    repeats = chat_data.get("repeats", {})

    if not repeats:
        await send_status(context, chat_id, user_id, "Активных повторений нет.")
        return

    lines = ["Активные повторения:"]
    for job_name, data in repeats.items():
        index = job_name.split("_")[-1]
        preview = data["text"] if len(data["text"]) <= 40 else data["text"][:40] + "..."
        lines.append(
            f"#{index}: \"{preview}\" — осталось {data['remaining']} раз, "
            f"интервал {data['interval']} сек."
        )

    await send_status(context, chat_id, user_id, "\n".join(lines))


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    args = context.args

    if not args:
        await send_status(context, chat_id, user_id, "Укажи номер задачи: /cancel 1")
        return

    index = args[0]
    job_name = f"repeat_{chat_id}_{index}"

    jobs = context.job_queue.get_jobs_by_name(job_name)
    if not jobs:
        await send_status(context, chat_id, user_id, "Задача с таким номером не найдена.")
        return

    for job in jobs:
        job.schedule_removal()

    context.chat_data.get("repeats", {}).pop(job_name, None)

    await send_status(context, chat_id, user_id, f"Задача #{index} отменена.")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    await send_status(
        context, chat_id, user_id,
        "Привет! Я отправляю повторяющиеся сообщения.\n\n"
        "Команды:\n"
        "/repeat текст количество интервал_в_секундах\n"
        "/list — активные повторения\n"
        "/cancel номер — отменить повторение",
    )


# ---------------------------------------------------------------------------
# Запуск через webhook
# ---------------------------------------------------------------------------
async def post_init(application: Application):
    global http_session
    http_session = aiohttp.ClientSession()

    if not WEBHOOK_HOST:
        raise RuntimeError("Не задан WEBHOOK_HOST (переменная окружения)")

    webhook_url = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
    await set_webhook_with_retry(application, webhook_url)
    logger.info("Webhook установлен: %s", webhook_url)

    await register_ephemeral_commands()


async def set_webhook_with_retry(application: Application, webhook_url: str, attempts: int = 5):
    """Telegram может временно ограничивать частые вызовы (RetryAfter) —
    например, если сервис несколько раз подряд перезапускался. Ждём
    указанное время и пробуем снова, вместо того чтобы падать целиком."""
    for attempt in range(1, attempts + 1):
        try:
            await application.bot.set_webhook(
                url=webhook_url,
                secret_token=WEBHOOK_SECRET or None,
            )
            return
        except RetryAfter as e:
            wait = e.retry_after + 1
            logger.warning(
                "Telegram ограничил частоту запросов, жду %s сек. (попытка %s/%s)",
                wait, attempt, attempts,
            )
            await asyncio.sleep(wait)
    # Последняя попытка без перехвата — если и она не пройдёт, лог покажет причину
    await application.bot.set_webhook(url=webhook_url, secret_token=WEBHOOK_SECRET or None)


async def register_ephemeral_commands():
    """Регистрирует команды с флагом is_ephemeral — тогда и сама команда,
    которую вводит пользователь в группе, будет видна только ему.
    Поле is_ephemeral появилось в Bot API 10.2 и пока не поддерживается
    классом Bot из python-telegram-bot, поэтому вызываем API напрямую."""
    commands = [
        {"command": "start", "description": "Начало работы с ботом", "is_ephemeral": True},
        {"command": "repeat", "description": "Запланировать повторяющееся сообщение", "is_ephemeral": True},
        {"command": "list", "description": "Показать активные повторения", "is_ephemeral": True},
        {"command": "cancel", "description": "Отменить повторение по номеру", "is_ephemeral": True},
    ]
    try:
        assert http_session is not None
        async with http_session.post(f"{API_BASE}/setMyCommands", json={"commands": commands}) as resp:
            data = await resp.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description", "unknown error"))
        logger.info("Эфемерные команды зарегистрированы")
    except Exception as e:
        logger.warning(
            "Не удалось зарегистрировать эфемерные команды (%s) — команды "
            "останутся видимыми всем в группе, но ответы бота всё равно "
            "будут эфемерными", e,
        )


async def post_shutdown(application: Application):
    if http_session is not None:
        await http_session.close()


def main():
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN (переменная окружения)")

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

    logger.info("Бот запускается через webhook")
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
        secret_token=WEBHOOK_SECRET or None,
    )


if __name__ == "__main__":
    main()
