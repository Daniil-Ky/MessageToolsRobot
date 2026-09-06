import os
import logging
import threading

from flask import Flask
from telegram import Update
from telegram.ext import (
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


# ---------- Keep-alive веб-сервер (нужен, чтобы Render не "усыплял" бота) ----------
keep_alive_app = Flask(__name__)


@keep_alive_app.route("/")
def home():
    return "Bot is running"


def run_keep_alive():
    keep_alive_app.run(host="0.0.0.0", port=PORT)


# ---------- Логика повторяющихся сообщений ----------
async def repeat_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data

    await context.bot.send_message(chat_id=job.chat_id, text=data["text"])
    data["remaining"] -= 1
    data["sent"] += 1

    if data["remaining"] <= 0:
        # Удаляем job из очереди
        job.schedule_removal()
        # Удаляем из списка активных для этого чата
        repeats = context.application.chat_data.get(job.chat_id, {}).get("repeats", {})
        repeats.pop(job.name, None)


async def repeat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args

    if len(args) < 3:
        await update.message.reply_text(
            "Формат команды:\n"
            "/repeat текст количество_повторений интервал_в_секундах\n\n"
            "Пример:\n"
            "/repeat Ежедневный бонус 10 86400"
        )
        return

    try:
        count = int(args[-2])
        interval = int(args[-1])
    except ValueError:
        await update.message.reply_text(
            "Количество повторений и интервал должны быть числами.\n"
            "Пример: /repeat Ежедневный бонус 10 86400"
        )
        return

    text = " ".join(args[:-2]).strip()

    if not text:
        await update.message.reply_text("Не указан текст сообщения.")
        return

    if count <= 0:
        await update.message.reply_text("Количество повторений должно быть больше 0.")
        return

    if interval < 5:
        await update.message.reply_text(
            "Интервал слишком маленький, укажи хотя бы 5 секунд."
        )
        return

    chat_data = context.application.chat_data.setdefault(chat_id, {})
    repeats = chat_data.setdefault("repeats", {})

    # Уникальное имя job'а
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

    await update.message.reply_text(
        f"Принято.\nТекст: {text}\nПовторений: {count}\nИнтервал: {interval} сек.\n"
        f"Номер задачи: {job_index} (посмотреть /list, отменить /cancel {job_index})"
    )


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_data = context.application.chat_data.get(chat_id, {})
    repeats = chat_data.get("repeats", {})

    if not repeats:
        await update.message.reply_text("Активных повторений нет.")
        return

    lines = ["Активные повторения:"]
    for job_name, data in repeats.items():
        index = job_name.split("_")[-1]
        preview = data["text"] if len(data["text"]) <= 40 else data["text"][:40] + "..."
        lines.append(
            f"#{index}: \"{preview}\" — осталось {data['remaining']} раз, "
            f"интервал {data['interval']} сек."
        )

    await update.message.reply_text("\n".join(lines))


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        await update.message.reply_text("Укажи номер задачи: /cancel 1")
        return

    index = args[0]
    job_name = f"repeat_{chat_id}_{index}"

    jobs = context.job_queue.get_jobs_by_name(job_name)
    if not jobs:
        await update.message.reply_text("Задача с таким номером не найдена.")
        return

    for job in jobs:
        job.schedule_removal()

    chat_data = context.application.chat_data.get(chat_id, {})
    chat_data.get("repeats", {}).pop(job_name, None)

    await update.message.reply_text(f"Задача #{index} отменена.")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я отправляю повторяющиеся сообщения.\n\n"
        "Команды:\n"
        "/repeat текст количество интервал_в_секундах\n"
        "/list — активные повторения\n"
        "/cancel номер — отменить повторение"
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN (переменная окружения)")

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("repeat", repeat_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("cancel", cancel_command))

    # Запускаем keep-alive сервер в отдельном потоке
    threading.Thread(target=run_keep_alive, daemon=True).start()

    logger.info("Бот запущен")
    application.run_polling()


if __name__ == "__main__":
    main()
