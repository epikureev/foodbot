import asyncio
import datetime
import json
import sqlite3
import time

import pandas as pd
import schedule
from PIL import Image

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

from google import genai


# =========================
# CONFIG
# =========================

TELEGRAM_TOKEN = "8612915134:AAHN8V2l0YhQrScRo_bZ6rHOCabqS8LyjoQ"
GEMINI_API = "AIzaSyBw63A19MywWyhzMSVwHrxLQPNtigBTd_E"
YOUR_TELEGRAM_ID = 215444830

TEXT_MODEL = "gemini-3.1-flash-lite-preview"
IMAGE_MODEL = "gemini-2.5-flash"

DAILY_LIMIT = 2450


# =========================
# TELEGRAM
# =========================

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()


# =========================
# GEMINI
# =========================

client = genai.Client(api_key=GEMINI_API)


# =========================
# DATABASE
# =========================

conn = sqlite3.connect("food.db")
cursor = conn.cursor()

cursor.execute(
    """
CREATE TABLE IF NOT EXISTS food(
id INTEGER PRIMARY KEY AUTOINCREMENT,
user_id INTEGER,
date TEXT,
food TEXT,
grams REAL,
kcal REAL,
protein REAL,
fat REAL,
carbs REAL
)
"""
)

conn.commit()


# =========================
# JSON PARSER
# =========================


def parse_json(text):

    try:

        start = text.find("{")
        end = text.rfind("}") + 1

        if start == -1:
            return None

        return json.loads(text[start:end])

    except:
        return None


# =========================
# GEMINI TEXT
# =========================


def gemini_parse(text):

    prompt = """
Return JSON only.

{
"food":"name",
"grams":number,
"kcal":number,
"protein":number,
"fat":number,
"carbs":number
}
"""

    try:

        response = client.models.generate_content(
            model=TEXT_MODEL, contents=[prompt, text]
        )

        if not response or not response.text:
            return None

        return response.text

    except Exception as e:

        print("TEXT GEMINI ERROR:", e)

        return None


# =========================
# GEMINI IMAGE
# =========================


def gemini_parse_image(img):

    prompt = """
Identify food in the image.

Estimate portion in grams.

Return JSON only:

{
"food":"name",
"grams":number,
"kcal":number,
"protein":number,
"fat":number,
"carbs":number
}
"""

    try:

        import io
        from google.genai import types

        buffer = io.BytesIO()
        img.save(buffer, format="JPEG")
        image_bytes = buffer.getvalue()

        response = client.models.generate_content(
            model=IMAGE_MODEL,
            contents=[
                prompt,
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            ],
        )

        if not response or not response.text:
            return None

        return response.text

    except Exception as e:

        print("IMAGE GEMINI ERROR:", e)

        return None


# =========================
# SAVE FOOD
# =========================


def save_food(user_id, food, grams, kcal, protein, fat, carbs):

    cursor.execute(
        """
INSERT INTO food(user_id,date,food,grams,kcal,protein,fat,carbs)
VALUES(?,?,?,?,?,?,?,?)
""",
        (
            user_id,
            datetime.date.today().isoformat(),
            food,
            grams,
            kcal,
            protein,
            fat,
            carbs,
        ),
    )

    conn.commit()


# =========================
# DAILY TOTAL
# =========================


def daily_total(date):

    df = pd.read_sql_query(
        "SELECT kcal,protein,fat,carbs FROM food WHERE date=?", conn, params=(date,)
    )

    if df.empty:
        return None

    return df.sum()


# =========================
# EXCEL EXPORT
# =========================


def export_excel(date):

    df = pd.read_sql_query(
        "SELECT food,grams,kcal,protein,fat,carbs FROM food WHERE date=?",
        conn,
        params=(date,),
    )

    filename = f"food_{date}.xlsx"

    df.to_excel(filename, index=False)

    return filename


# =========================
# COMMANDS
# =========================


@dp.message(Command("start"))
async def start(message: Message):

    await message.answer(
        """
Отправьте:

текст еды
фото еды
фото упаковки

Команды:

/undo
/today
"""
    )


@dp.message(Command("undo"))
async def undo(message: Message):

    cursor.execute(
        """
DELETE FROM food
WHERE id=(
SELECT id FROM food
WHERE user_id=?
ORDER BY id DESC
LIMIT 1)
""",
        (message.from_user.id,),
    )

    conn.commit()

    await message.answer("Последняя запись удалена")


@dp.message(Command("today"))
async def today(message: Message):

    today = datetime.date.today().isoformat()

    total = daily_total(today)

    if total is None:

        await message.answer("Сегодня записей нет")

        return

    remaining = DAILY_LIMIT - total.kcal

    await message.answer(
        f"""
Сегодня:

Калории: {total.kcal:.0f}
Белки: {total.protein:.1f}
Жиры: {total.fat:.1f}
Углеводы: {total.carbs:.1f}

Осталось калорий: {remaining:.0f}
"""
    )


# =========================
# PHOTO HANDLER
# =========================


@dp.message(F.photo)
async def photo_handler(message: Message):

    photo = message.photo[-1]

    filename = "food.jpg"

    await bot.download(photo, filename)

    img = Image.open(filename)

    img = img.resize((1024, 1024))

    result = gemini_parse_image(img)

    if not result:

        await message.answer("AI не смог распознать фото")

        return

    data = parse_json(result)

    if not data:

        await message.answer("AI не смог распознать еду")

        return

    food = data.get("food", "unknown")

    grams = float(data.get("grams") or 100)
    kcal = float(data.get("kcal") or 0)
    protein = float(data.get("protein") or 0)
    fat = float(data.get("fat") or 0)
    carbs = float(data.get("carbs") or 0)

    save_food(message.from_user.id, food, grams, kcal, protein, fat, carbs)

    await message.answer(
        f"""
Продукт: {food}

Вес: {grams} г

Калории: {kcal}
Белки: {protein}
Жиры: {fat}
Углеводы: {carbs}
"""
    )


# =========================
# TEXT HANDLER
# =========================


@dp.message(F.text)
async def text_handler(message: Message):

    result = gemini_parse(message.text)

    if not result:

        await message.answer("AI не смог распознать текст")

        return

    data = parse_json(result)

    if not data:

        await message.answer("AI не смог распознать еду")

        return

    food = data.get("food", "unknown")

    grams = float(data.get("grams") or 100)
    kcal = float(data.get("kcal") or 0)
    protein = float(data.get("protein") or 0)
    fat = float(data.get("fat") or 0)
    carbs = float(data.get("carbs") or 0)

    save_food(message.from_user.id, food, grams, kcal, protein, fat, carbs)

    await message.answer(
        f"""
Продукт: {food}

Вес: {grams} г

Калории: {kcal}
Белки: {protein}
Жиры: {fat}
Углеводы: {carbs}
"""
    )


# =========================
# DAILY REPORT
# =========================


async def send_report():

    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()

    total = daily_total(yesterday)

    if total is None:
        return

    file = export_excel(yesterday)

    await bot.send_document(
        chat_id=YOUR_TELEGRAM_ID,
        document=open(file, "rb"),
        caption=f"Отчет за {yesterday}",
    )


def scheduler():

    schedule.every().day.at("08:00").do(lambda: asyncio.run(send_report()))

    while True:

        schedule.run_pending()

        time.sleep(30)


# =========================
# MAIN
# =========================


async def main():

    print("BOT STARTED")

    asyncio.create_task(asyncio.to_thread(scheduler))

    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())
