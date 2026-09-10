import os
import sqlite3

from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)


# ============================================================
# НАСТРОЙКИ
# ============================================================

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")


if not TOKEN:
    raise ValueError(
        "Не найден BOT_TOKEN. "
        "Проверь файл .env"
    )


# ============================================================
# ПУТИ
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

VIDEO_DIR = os.path.join(
    BASE_DIR,
    "videos"
)

DB_FILE = os.path.join(
    BASE_DIR,
    "course.db"
)


# ============================================================
# DATABASE
# ============================================================

def get_connection():

    conn = sqlite3.connect(
        DB_FILE
    )

    conn.row_factory = sqlite3.Row

    return conn


# ============================================================
# SEND LESSONS
# ============================================================

async def send_lessons(
    update: Update
):

    videos = [
        "test.mp4",
        "lesson2.mp4",
        "lesson3.mp4",
    ]

    for index, video_name in enumerate(
        videos,
        start=1
    ):

        video_path = os.path.join(
            VIDEO_DIR,
            video_name
        )

        # ----------------------------------------------------
        # Проверяем файл
        # ----------------------------------------------------

        if not os.path.isfile(video_path):

            await update.message.reply_text(
                f"❌ Не найден видеофайл:\n"
                f"{video_name}"
            )

            continue

        # ----------------------------------------------------
        # Отправляем видео
        # ----------------------------------------------------

        try:

            with open(
                video_path,
                "rb"
            ) as video_file:

                await update.message.reply_video(
                    video=video_file,
                    caption=(
                        f"📹 Заняття №{index}"
                    )
                )

        except Exception as error:

            print(
                "Ошибка отправки видео:",
                error
            )

            await update.message.reply_text(
                "❌ Не удалось отправить "
                f"{video_name}"
            )


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    # --------------------------------------------------------
    # Проверяем Telegram пользователя
    # --------------------------------------------------------

    user = update.effective_user

    if not user:

        return

    telegram_id = user.id

    # --------------------------------------------------------
    # Получаем access code
    #
    # Например:
    #
    # /start X7kP92mQa91
    # --------------------------------------------------------

    if not context.args:

        await update.message.reply_text(
            "👋 Добро пожаловать!\n\n"

            "Для доступа к курсу "
            "нужно сначала приобрести курс "
            "на сайте.\n\n"

            "После оплаты вы получите "
            "персональную ссылку "
            "для входа."
        )

        return

    access_code = context.args[0].strip()

    # --------------------------------------------------------
    # Ищем код в базе
    # --------------------------------------------------------

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            payment_status,
            telegram_id,
            access_code

        FROM orders

        WHERE access_code = ?

        LIMIT 1
        """,
        (access_code,)
    )

    order = cursor.fetchone()

    # --------------------------------------------------------
    # Код не найден
    # --------------------------------------------------------

    if not order:

        conn.close()

        await update.message.reply_text(
            "❌ Ссылка недействительна.\n\n"
            "Если вы уже оплатили курс, "
            "обратитесь в поддержку."
        )

        return

    # --------------------------------------------------------
    # Проверяем оплату
    # --------------------------------------------------------

    if order["payment_status"] != "paid":

        conn.close()

        await update.message.reply_text(
            "❌ Оплата курса не подтверждена."
        )

        return

    # --------------------------------------------------------
    # Проверяем, активирован ли код
    # --------------------------------------------------------

    saved_telegram_id = order["telegram_id"]

    # ========================================================
    # Сценарий 1
    #
    # Код ещё никто не активировал
    # ========================================================

    if saved_telegram_id is None:

        cursor.execute(
            """
            UPDATE orders

            SET telegram_id = ?

            WHERE id = ?
            """,
            (
                telegram_id,
                order["id"]
            )
        )

        conn.commit()

        conn.close()

        await update.message.reply_text(
            "✅ Доступ подтверждён!\n\n"
            "Добро пожаловать на курс 🎓"
        )

        await send_lessons(
            update
        )

        return

    # ========================================================
    # Сценарий 2
    #
    # Этот код уже принадлежит этому пользователю
    # ========================================================

    if saved_telegram_id == telegram_id:

        conn.close()

        await update.message.reply_text(
            "👋 С возвращением!\n\n"
            "Ваш доступ к курсу активен."
        )

        await send_lessons(
            update
        )

        return

    # ========================================================
    # Сценарий 3
    #
    # Код уже активировал другой Telegram аккаунт
    # ========================================================

    conn.close()

    await update.message.reply_text(
        "❌ Эта ссылка уже была активирована.\n\n"
        "Один код доступа можно привязать "
        "только к одному Telegram-аккаунту."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "================================"
    )

    print(
        "Telegram бот запускается..."
    )

    print(
        "================================"
    )

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    # --------------------------------------------------------
    # /start
    # --------------------------------------------------------

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    print(
        "✅ Бот запущен."
    )

    print(
        "Для остановки нажмите Control+C."
    )

    app.run_polling()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()