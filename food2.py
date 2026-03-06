import asyncio
import datetime
import json
import sqlite3
import time
import io
import base64

import pandas as pd
import requests
from PIL import Image

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message


TELEGRAM_TOKEN = "8612915134:AAHN8V2l0YhQrScRo_bZ6rHOCabqS8LyjoQ"
HF_API = "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"

ADMIN_ID = 215444830

DAILY_LIMIT = 2450


# =====================
# TELEGRAM
# =====================

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()


# =====================
# DATABASE
# =====================

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


# =====================
# ERROR
# =====================


def fatal_error(e):

    print("FATAL ERROR:", e)

    import os

    os._exit(1)


# =====================
# JSON PARSER
# =====================


def parse_json(text):

    if not text:
        return None

    try:

        start = text.find("{")
        end = text.rfind("}") + 1

        if start == -1 or end == -1:
            return None

        return json.loads(text[start:end])

    except:
        return None


# =====================
# HUGGING FACE TEXT
# =====================


def hf_text_parse(text):

    prompt = f"""
Определи еду и её КБЖУ.

Ответ только JSON:

{{
"food":"название еды",
"grams":число,
"kcal":число,
"protein":число,
"fat":число,
"carbs":число
}}

Еда: {text}
"""

    headers = {"Authorization": f"Bearer {HF_API}"}

    payload = {"inputs": prompt}

    try:

        response = requests.post(
            "https://api-inference.huggingface.co/models/google/flan-t5-large",
            headers=headers,
            json=payload,
        )

        result = response.json()

        if isinstance(result, list):
            return result[0]["generated_text"]

        return None

    except Exception as e:

        fatal_error(e)


# =====================
# HUGGING FACE IMAGE
# =====================


def hf_image_parse(img):

    prompt = """
Определи еду на изображении.

Ответ только JSON:

{
"food":"название еды",
"grams":число,
"kcal":число,
"protein":число,
"fat":число,
"carbs":число
}
"""

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG")

    img_base64 = base64.b64encode(buffer.getvalue()).decode()

    headers = {"Authorization": f"Bearer {HF_API}", "Content-Type": "application/json"}

    payload = {
        "model": "meta-llama/Llama-3.2-11B-Vision-Instruct",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"},
                    },
                ],
            }
        ],
        "max_tokens": 200,
    }

    try:

        response = requests.post(
            "https://router.huggingface.co/v1/chat/completions",
            headers=headers,
            json=payload,
        )

        result = response.json()

        print(result)

        text = result["choices"][0]["message"]["content"]

        return text

    except Exception as e:

        fatal_error(e)


# =====================
# SAVE FOOD
# =====================


def save_food(user, food, grams, kcal, protein, fat, carbs):

    cursor.execute(
        """
    INSERT INTO food(user_id,date,food,grams,kcal,protein,fat,carbs)
    VALUES(?,?,?,?,?,?,?,?)
    """,
        (
            user,
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


# =====================
# DAILY TOTAL
# =====================


def daily_total(date):

    df = pd.read_sql_query(
        "SELECT kcal,protein,fat,carbs FROM food WHERE date=?", conn, params=(date,)
    )

    if df.empty:
        return None

    return df.sum()


# =====================
# COMMANDS
# =====================


@dp.message(Command("start"))
async def start(message: Message):

    await message.answer(
        """
Отправьте:

текст еды
фото еды

Команды:

/undo
/stats
"""
    )


# =====================
# DELETE LAST
# =====================


@dp.message(Command("undo"))
async def undo(message: Message):

    cursor.execute(
        """
    DELETE FROM food
    WHERE id=(
        SELECT id FROM food
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 1
    )
    """,
        (message.from_user.id,),
    )

    conn.commit()

    await message.answer("Последняя запись удалена")


# =====================
# TODAY STATS
# =====================


@dp.message(Command("stats"))
async def stats(message: Message):

    today = datetime.date.today().isoformat()

    total = daily_total(today)

    if total is None:

        await message.answer("Сегодня записей нет")
        return

    await message.answer(
        f"""
Сегодня:

Калории {total.kcal:.0f}
Белки {total.protein:.1f}
Жиры {total.fat:.1f}
Углеводы {total.carbs:.1f}

Осталось {DAILY_LIMIT-total.kcal:.0f} kcal
"""
    )


# =====================
# PHOTO
# =====================


@dp.message(F.photo)
async def photo(message: Message):

    photo = message.photo[-1]

    file = "food.jpg"

    await bot.download(photo, file)

    img = Image.open(file)
    img = img.resize((1024, 1024))

    result = hf_image_parse(img)

    data = parse_json(result)

    if not data:

        await message.answer("Не смог распознать")
        return

    save_food(
        message.from_user.id,
        data["food"],
        data["grams"],
        data["kcal"],
        data["protein"],
        data["fat"],
        data["carbs"],
    )

    await message.answer(
        f"""
{data['food']}

{data['kcal']} калорий
"""
    )


# =====================
# TEXT
# =====================


@dp.message(F.text)
async def text(message: Message):

    result = hf_text_parse(message.text)

    data = parse_json(result)

    if not data:

        await message.answer("Ошибка распознавания")
        return

    save_food(
        message.from_user.id,
        data["food"],
        data["grams"],
        data["kcal"],
        data["protein"],
        data["fat"],
        data["carbs"],
    )

    await message.answer(
        f"""
{data['food']}

{data['kcal']} калорий
"""
    )


# =====================
# MAIN
# =====================


async def main():

    print("BOT STARTED")

    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())
