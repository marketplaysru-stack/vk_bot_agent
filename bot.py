import os
import telebot
import requests
import json
import urllib.parse
import threading
import time
import re
from datetime import datetime, timedelta
from telebot import apihelper

# ============================================================
#  ЧТЕНИЕ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ (НАСТРАИВАЕТСЯ НА БОТХОСТЕ)
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
AGNES_API_KEY = os.getenv("AGNES_API_KEY")

# Проверка обязательных переменных
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не задан в переменных окружения")
if not AGNES_API_KEY:
    raise ValueError("❌ AGNES_API_KEY не задан в переменных окружения")

# ====== ТОКЕНЫ И ID ГРУПП ИЗ ПЕРЕМЕННЫХ ======
VK_ACCOUNTS = {
    "родительский": {
        "token": os.getenv("VK_TOKEN_РОДИТЕЛЬСКИЙ", ""),
        "group_id": int(os.getenv("VK_GROUP_ID_РОДИТЕЛЬСКИЙ", "0"))
    },
    "строительный": {
        "token": os.getenv("VK_TOKEN_СТРОИТЕЛЬНЫЙ", ""),
        "group_id": int(os.getenv("VK_GROUP_ID_СТРОИТЕЛЬНЫЙ", "0"))
    },
    "ai": {
        "token": os.getenv("VK_TOKEN_AI", ""),
        "group_id": int(os.getenv("VK_GROUP_ID_AI", "0"))
    }
}
# Удаляем группы, у которых нет токена или ID
VK_ACCOUNTS = {k: v for k, v in VK_ACCOUNTS.items() if v["token"] and v["group_id"] != 0}

if not VK_ACCOUNTS:
    raise ValueError("❌ Нет ни одной настроенной группы ВКонтакте. Проверьте переменные VK_TOKEN_* и VK_GROUP_ID_*")

print(f"✅ Загружено групп: {len(VK_ACCOUNTS)}")
for name, data in VK_ACCOUNTS.items():
    print(f"   - {name}: group_id={data['group_id']}")

# ============================================================

SCHEDULE_FILE = "schedule.json"

apihelper.CONNECT_TIMEOUT = 60
apihelper.READ_TIMEOUT = 120

bot = telebot.TeleBot(BOT_TOKEN)

# ================ ЗАГРУЗКА / СОХРАНЕНИЕ РАСПИСАНИЯ ================
def load_schedule():
    if os.path.exists(SCHEDULE_FILE):
        with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_schedule(schedule):
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(schedule, f, ensure_ascii=False, indent=2)

# ================ ГЕНЕРАЦИЯ ТЕКСТА ================
def generate_post_text(niche, topic):
    system_prompt = (
        "Ты — профессиональный SMM-менеджер и копирайтер. "
        "Напиши яркий, вовлекающий пост для ВКонтакте по заданной теме и нише. "
        "Пост должен быть продающим, полезным и побуждать к действию. "
        "Используй структуру: цепляющий заголовок (до 10 слов) → проблема аудитории → решение → практическая польза → призыв к действию. "
        "Добавь эмодзи (🔥, 💡, 🚀, ✨, 📌 и т.д.), разбей на короткие абзацы. "
        "В конце добавь 5 релевантных хештегов. Пиши человечно, без канцелярита, с душой."
    )
    user_prompt = f"Ниша: {niche}\nТема: {topic}\n\nНапиши пост, который заставит читателя остановиться, прочитать и что-то сделать."
    headers = {"Authorization": f"Bearer {AGNES_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "agnes-2.0-flash",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.85
    }
    try:
        response = requests.post(
            "https://apihub.agnes-ai.com/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=120
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            print(f"[DEBUG] Ошибка текста: {response.status_code}")
            return None
    except Exception as e:
        print(f"[DEBUG] Текст ошибка: {e}")
        return None

# ================ ГЕНЕРАЦИЯ КАРТИНКИ ================
def get_image_prompt(niche, topic):
    base_prompt = {
        "родительский": (
            f"Счастливая семья — мама, папа и двое детей — сидят за уютным столом в светлой гостиной. "
            f"На стене висит календарь с яркими стикерами, на столе лежат книжки и планшет с развивающей игрой. "
            f"Рядом — кружка с чаем и улыбающийся плюшевый мишка. "
            f"Сюжет поста: {topic}. "
            "Стиль: фотореализм, тёплые цвета, семейна� атмосфера. "
            "Добавь элементы: иконка сердца ❤️, звездочки ✨, яркие акценты (оранжевый, жёлтый). "
            "Формат: 1:1, высокое качество, 8K. Без текста на картинке."
        ),
        "строительный": (
            f"Профессиональный строитель в каске и жилете стоит на фоне современного строящегося дома. "
            f"Рядом лежат инструменты: уровень, рулетка, дрель. "
            f"На заднем плане — синее небо и кран. "
            f"Сюжет поста: {topic}. "
            "Стиль: индустриальный, чёткие линии, контрастные цвета (синий, оранжевый, серый). "
            "Добавь иконки: молоток 🔨, каска, гаечный ключ. "
            "Формат: 1:1, высокое разрешение, 8K. Без текста."
        ),
        "ai": (
            f"Минималистичный рабочий стол с мощным ноутбуком, на экране — яркая схема нейросети с разноцветными связями. "
            f"Рядом стоят кофе, беспроводные наушники и стильный смартфон. "
            f"В воздухе парят иконки: ⚡, 💡, 🧠, 📊. "
            f"Сюжет поста: {topic}. "
            "Стиль: футуристичный, глянцевый, неоновые цвета (синий, фиолетовый, бирюзовый). "
            "Формат: 1:1, высокое качество, 4K. Без текста."
        )
    }
    return base_prompt.get(niche, f"Яркая рекламная картинка на тему: {topic}. Современный стиль, 1:1, без текста.")

def generate_image(niche, topic):
    prompt = get_image_prompt(niche, topic)
    headers = {"Authorization": f"Bearer {AGNES_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "agnes-image-2.1-flash",
        "prompt": prompt,
        "size": "1024x1024",
        "n": 1,
        "style": "vibrant"
    }
    try:
        response = requests.post(
            "https://apihub.agnes-ai.com/v1/images/generations",
            headers=headers,
            json=data,
            timeout=120
        )
        if response.status_code == 200:
            return response.json()["data"][0]["url"]
        else:
            print(f"[DEBUG] Agnes ошибка: {response.status_code}")
            prompt_encoded = urllib.parse.quote(prompt)
            return f"https://image.pollinations.ai/prompt/{prompt_encoded}?width=1024&height=1024&nologo=true"
    except Exception as e:
        print(f"[DEBUG] Agnes искл: {e}")
        prompt_encoded = urllib.parse.quote(prompt)
        return f"https://image.pollinations.ai/prompt/{prompt_encoded}?width=1024&height=1024&nologo=true"

def download_image(url):
    try:
        response = requests.get(url, timeout=60)
        if response.status_code == 200:
            return response.content
        return None
    except Exception as e:
        print(f"[DEBUG] Скачивание ошибка: {e}")
        return None

# ================ ПУБЛИКАЦИЯ В ВК ================
def post_to_vk(niche, image_bytes, text):
    if niche not in VK_ACCOUNTS:
        return False, f"Ниша '{niche}' не найдена"
    vk_token = VK_ACCOUNTS[niche]["token"]
    group_id = VK_ACCOUNTS[niche]["group_id"]

    try:
        # Проверка токена
        check_resp = requests.get(
            "https://api.vk.com/method/users.get",
            params={"access_token": vk_token, "v": "5.131"}
        ).json()
        if "error" in check_resp:
            return False, f"Ошибка проверки токена: {check_resp['error']['error_msg']}"

        upload_url_resp = requests.get(
            "https://api.vk.com/method/photos.getWallUploadServer",
            params={
                "group_id": abs(group_id),
                "access_token": vk_token,
                "v": "5.131"
            }
        ).json()
        if "error" in upload_url_resp:
            return False, f"Ошибка upload_url: {upload_url_resp['error']['error_msg']}"
        upload_url = upload_url_resp["response"]["upload_url"]

        files = {"photo": ("image.jpg", image_bytes, "image/jpeg")}
        upload_resp = requests.post(upload_url, files=files).json()
        if "error" in upload_resp:
            return False, f"Ошибка загрузки: {upload_resp['error']['error_msg']}"

        if upload_resp.get("photo") == "[]":
            return False, "Пустой ответ от сервера загрузки"

        save_params = {
            "group_id": abs(group_id),
            "server": upload_resp["server"],
            "photo": upload_resp["photo"],
            "hash": upload_resp["hash"],
            "access_token": vk_token,
            "v": "5.131"
        }
        save_resp = requests.get("https://api.vk.com/method/photos.saveWallPhoto", params=save_params).json()
        if "error" in save_resp:
            return False, f"Ошибка сохранения: {save_resp['error']['error_msg']}"

        photo = save_resp["response"][0]
        attachment = f"photo{photo['owner_id']}_{photo['id']}"

        post_params = {
            "owner_id": group_id,
            "message": text,
            "attachments": attachment,
            "access_token": vk_token,
            "v": "5.131",
            "from_group": 1
        }
        post_resp = requests.get("https://api.vk.com/method/wall.post", params=post_params).json()
        if "error" in post_resp:
            return False, f"Ошибка публикации: {post_resp['error']['error_msg']}"

        print(f"✅ Пост опубликован в группе {group_id}, ID: {post_resp['response']['post_id']}")
        return True, None
    except Exception as e:
        return False, f"Исключение: {str(e)}"

# ================ ВЫПОЛНЕНИЕ ОТЛОЖЕННОГО ПОСТА ================
def execute_scheduled_post(item):
    niche = item["niche"]
    topic = item["topic"]
    print(f"📢 Публикую пост: {topic} в {item['time']} (ниша: {niche})")

    post_text = generate_post_text(niche, topic)
    if not post_text:
        print("❌ Не удалось сгенерировать текст")
        return

    image_url = generate_image(niche, topic)
    image_bytes = download_image(image_url)
    if not image_bytes:
        print("❌ Не удалось скачать картинку")
        return

    success, error = post_to_vk(niche, image_bytes, post_text)
    if success:
        print("✅ Пост опубликован!")
    else:
        print(f"❌ Ошибка публикации: {error}")

# ================ ПЛАНИРОВЩИК ================
def scheduler_loop():
    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        schedule = load_schedule()
        for item in schedule:
            if item["time"] == now and not item.get("done", False):
                execute_scheduled_post(item)
                item["done"] = True
                save_schedule(schedule)
        time.sleep(30)

threading.Thread(target=scheduler_loop, daemon=True).start()

# ================ КОМАНДЫ ================
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message,
        "👋 Бот для генерации рекламных постов с картинками.\n"
        "/post_in ниша тема минуты — пост через N минут\n"
        "Пример: /post_in ai Нейросети 5\n"
        "/add ниша тема ГГГГ-ММ-ДД ЧЧ:ММ\n"
        "/list — список постов\n"
        "/remove ID — удалить\n"
        "Доступные ниши: родительский, строительный, ai"
    )

@bot.message_handler(commands=['post_in'])
def post_in(message):
    text = message.text.replace("/post_in", "").strip()
    match = re.search(r'(\d+)$', text)
    if not match:
        bot.reply_to(message, "❌ Укажи число минут в конце, например: /post_in ai Нейросети 5")
        return
    minutes = int(match.group(1))
    rest = text[:match.start()].strip()
    parts = rest.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "❌ Формат: /post_in ниша тема минуты\nНапример: /post_in ai Нейросети 5")
        return
    niche = parts[0].lower()
    topic = parts[1].strip()

    if niche not in VK_ACCOUNTS:
        bot.reply_to(message, f"❌ Ниша '{niche}' не найдена. Доступны: {', '.join(VK_ACCOUNTS.keys())}")
        return

    publish_time = datetime.now() + timedelta(minutes=minutes)
    full_time = publish_time.strftime("%Y-%m-%d %H:%M")

    schedule = load_schedule()
    new_id = str(int(time.time()))
    schedule.append({
        "id": new_id,
        "niche": niche,
        "topic": topic,
        "time": full_time,
        "done": False
    })
    save_schedule(schedule)
    bot.reply_to(message, f"✅ Пост добавлен: [{niche}] {topic} в {full_time} (через {minutes} мин)")

@bot.message_handler(commands=['add'])
def add_post(message):
    args = message.text.split(maxsplit=4)
    if len(args) < 5:
        bot.reply_to(message, "❌ Формат: /add ниша тема ГГГГ-ММ-ДД ЧЧ:ММ\nНапример: /add ai Нейросети 2026-07-21 13:05")
        return
    niche = args[1]
    topic = args[2]
    date = args[3]
    time_str = args[4]
    full_time = f"{date} {time_str}"
    try:
        datetime.strptime(full_time, "%Y-%m-%d %H:%M")
    except ValueError:
        bot.reply_to(message, "❌ Неверный формат даты или времени. Используй: ГГГГ-ММ-ДД ЧЧ:ММ")
        return
    if niche not in VK_ACCOUNTS:
        bot.reply_to(message, f"❌ Ниша '{niche}' не найдена")
        return
    schedule = load_schedule()
    new_id = str(int(time.time()))
    schedule.append({
        "id": new_id,
        "niche": niche,
        "topic": topic,
        "time": full_time,
        "done": False
    })
    save_schedule(schedule)
    bot.reply_to(message, f"✅ Пост добавлен: [{niche}] {topic} на {full_time}")

@bot.message_handler(commands=['list'])
def list_posts(message):
    schedule = load_schedule()
    if not schedule:
        bot.reply_to(message, "📭 Нет запланированных постов")
        return
    lines = []
    for item in schedule:
        status = "✅" if item.get("done") else "⏳"
        lines.append(f"{status} ID:{item['id']} [{item['niche']}] {item['topic']} -> {item['time']}")
    bot.reply_to(message, "\n".join(lines[:10]))

@bot.message_handler(commands=['remove'])
def remove_post(message):
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "❌ Укажи ID поста: /remove 123456")
        return
    post_id = parts[1]
    schedule = load_schedule()
    new_schedule = [item for item in schedule if item["id"] != post_id]
    if len(new_schedule) == len(schedule):
        bot.reply_to(message, "❌ Пост с таким ID не найден")
        return
    save_schedule(new_schedule)
    bot.reply_to(message, f"✅ Пост {post_id} удалён")

@bot.message_handler(commands=['help'])
def help_command(message):
    bot.reply_to(message,
        "📌 Команды:\n"
        "/post_in ниша тема минуты — пост через N минут\n"
        "/add ниша тема ГГГГ-ММ-ДД ЧЧ:ММ\n"
        "/list — список постов\n"
        "/remove ID — удалить пост"
    )

if __name__ == "__main__":
    print("🤖 Бот запущен...")
    bot.polling(none_stop=True)