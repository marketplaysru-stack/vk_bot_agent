import sys
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

# ===== ПЕРВЫЙ ВЫВОД В ЛОГИ =====
print("🚀 Бот запускается...", flush=True)
sys.stdout.flush()

# ===== ПРОВЕРКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ =====
try:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    AGNES_API_KEY = os.getenv("AGNES_API_KEY")
    
    if not BOT_TOKEN:
        raise ValueError("❌ BOT_TOKEN не задан в переменных окружения")
    if not AGNES_API_KEY:
        raise ValueError("❌ AGNES_API_KEY не задан в переменных окружения")
    
    print("✅ Основные переменные загружены", flush=True)
except Exception as e:
    print(f"❌ Ошибка при загрузке переменных: {e}", flush=True)
    sys.exit(1)

# ===== ЗАГРУЗКА ГРУПП =====
VK_ACCOUNTS = {}
try:
    for name, suffix in [("родительский", "РОДИТЕЛЬСКИЙ"), ("строительный", "СТРОИТЕЛЬНЫЙ"), ("ai", "AI")]:
        token = os.getenv(f"VK_TOKEN_{suffix}")
        group_id_str = os.getenv(f"VK_GROUP_ID_{suffix}")
        if token and group_id_str:
            VK_ACCOUNTS[name] = {"token": token, "group_id": int(group_id_str)}
            print(f"✅ Группа '{name}': ID={group_id_str}", flush=True)
        else:
            print(f"⚠️ Группа '{name}' не настроена (пропущена)", flush=True)
    
    if not VK_ACCOUNTS:
        raise ValueError("❌ Нет ни одной настроенной группы ВКонтакте")
except Exception as e:
    print(f"❌ Ошибка загрузки групп: {e}", flush=True)
    sys.exit(1)

# ===== НАСТРОЙКА БОТА =====
apihelper.CONNECT_TIMEOUT = 60
apihelper.READ_TIMEOUT = 120
try:
    bot = telebot.TeleBot(BOT_TOKEN)
    print("✅ Бот инициализирован", flush=True)
except Exception as e:
    print(f"❌ Ошибка инициализации бота: {e}", flush=True)
    sys.exit(1)

SCHEDULE_FILE = "schedule.json"

# ================ ФУНКЦИИ ================
def load_schedule():
    try:
        if os.path.exists(SCHEDULE_FILE):
            with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"⚠️ Ошибка загрузки расписания: {e}", flush=True)
    return []

def save_schedule(schedule):
    try:
        with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
            json.dump(schedule, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Ошибка сохранения расписания: {e}", flush=True)

def generate_post_text(niche, topic):
    system_prompt = (
        "Ты — профессиональный SMM-менеджер и копирайтер. "
        "Напиши яркий, вовлекающий пост для ВКонтакте по заданной теме и нише. "
        "Пост должен быть продающим, полезным и побуждать к действию. "
        "Используй структуру: цепляющий заголовок (до 10 слов) → проблема аудитории → решение → практическая польза → призыв к действию. "
        "Добавь эмодзи, разбей на короткие абзацы. В конце добавь 5 хештегов. Пиши человечно, без канцелярита."
    )
    user_prompt = f"Ниша: {niche}\nТема: {topic}"
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
            print(f"⚠️ Ошибка текста: {response.status_code}", flush=True)
            return None
    except Exception as e:
        print(f"⚠️ Ошибка при генерации текста: {e}", flush=True)
        return None

def get_image_prompt(niche, topic):
    base_prompt = {
        "родительский": f"Семья за уютным столом, тёплый свет, мама обнимает дочку. Тема: {topic}. Фотореализм, 1:1, без текста.",
        "строительный": f"Строитель в каске, современный дом, инструменты. Тема: {topic}. Индустриальный стиль, 1:1, без текста.",
        "ai": f"Ноутбук с нейросетью, неоновые цвета, минимализм. Тема: {topic}. Футуристичный стиль, 1:1, без текста."
    }
    return base_prompt.get(niche, f"Иллюстрация к посту: {topic}. Ярко, современно, 1:1, без текста.")

def generate_image(niche, topic):
    prompt = get_image_prompt(niche, topic)
    headers = {"Authorization": f"Bearer {AGNES_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "agnes-image-2.1-flash",
        "prompt": prompt,
        "size": "1024x1024",
        "n": 1
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
            print(f"⚠️ Agnes ошибка: {response.status_code}", flush=True)
            prompt_encoded = urllib.parse.quote(prompt)
            return f"https://image.pollinations.ai/prompt/{prompt_encoded}?width=1024&height=1024&nologo=true"
    except Exception as e:
        print(f"⚠️ Ошибка генерации картинки: {e}", flush=True)
        prompt_encoded = urllib.parse.quote(prompt)
        return f"https://image.pollinations.ai/prompt/{prompt_encoded}?width=1024&height=1024&nologo=true"

def download_image(url):
    try:
        response = requests.get(url, timeout=60)
        if response.status_code == 200:
            return response.content
        return None
    except Exception as e:
        print(f"⚠️ Ошибка скачивания картинки: {e}", flush=True)
        return None

def post_to_vk(niche, image_bytes, text):
    if niche not in VK_ACCOUNTS:
        return False, f"Ниша '{niche}' не найдена"
    vk_token = VK_ACCOUNTS[niche]["token"]
    group_id = VK_ACCOUNTS[niche]["group_id"]
    try:
        # Проверка токена
        check = requests.get(
            "https://api.vk.com/method/users.get",
            params={"access_token": vk_token, "v": "5.131"}
        ).json()
        if "error" in check:
            return False, f"Ошибка токена: {check['error']['error_msg']}"
        # Получить сервер для загрузки
        upload_resp = requests.get(
            "https://api.vk.com/method/photos.getWallUploadServer",
            params={"group_id": abs(group_id), "access_token": vk_token, "v": "5.131"}
        ).json()
        if "error" in upload_resp:
            return False, f"Ошибка upload_url: {upload_resp['error']['error_msg']}"
        upload_url = upload_resp["response"]["upload_url"]
        # Загрузить фото
        files = {"photo": ("image.jpg", image_bytes, "image/jpeg")}
        up = requests.post(upload_url, files=files).json()
        if "error" in up:
            return False, f"Ошибка загрузки: {up['error']['error_msg']}"
        if up.get("photo") == "[]":
            return False, "Пустой ответ от сервера загрузки"
        # Сохранить фото
        save = requests.get(
            "https://api.vk.com/method/photos.saveWallPhoto",
            params={
                "group_id": abs(group_id),
                "server": up["server"],
                "photo": up["photo"],
                "hash": up["hash"],
                "access_token": vk_token,
                "v": "5.131"
            }
        ).json()
        if "error" in save:
            return False, f"Ошибка сохранения: {save['error']['error_msg']}"
        photo = save["response"][0]
        attachment = f"photo{photo['owner_id']}_{photo['id']}"
        # Опубликовать
        post = requests.get(
            "https://api.vk.com/method/wall.post",
            params={
                "owner_id": group_id,
                "message": text,
                "attachments": attachment,
                "access_token": vk_token,
                "v": "5.131",
                "from_group": 1
            }
        ).json()
        if "error" in post:
            return False, f"Ошибка публикации: {post['error']['error_msg']}"
        print(f"✅ Пост опубликован в группе {group_id}, ID: {post['response']['post_id']}", flush=True)
        return True, None
    except Exception as e:
        return False, f"Исключение: {str(e)}"

def execute_scheduled_post(item):
    niche = item["niche"]
    topic = item["topic"]
    print(f"📢 Публикую пост: {topic} в {item['time']} (ниша: {niche})", flush=True)
    post_text = generate_post_text(niche, topic)
    if not post_text:
        print("❌ Не удалось сгенерировать текст", flush=True)
        return
    image_url = generate_image(niche, topic)
    image_bytes = download_image(image_url)
    if not image_bytes:
        print("❌ Не удалось скачать картинку", flush=True)
        return
    success, error = post_to_vk(niche, image_bytes, post_text)
    if success:
        print("✅ Пост опубликован!", flush=True)
    else:
        print(f"❌ Ошибка публикации: {error}", flush=True)

def scheduler_loop():
    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            schedule = load_schedule()
            for item in schedule:
                if item["time"] == now and not item.get("done", False):
                    execute_scheduled_post(item)
                    item["done"] = True
                    save_schedule(schedule)
        except Exception as e:
            print(f"⚠️ Ошибка в планировщике: {e}", flush=True)
        time.sleep(30)

# ================ ОБРАБОТЧИКИ КОМАНД ================
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message,
        "👋 Бот для генерации рекламных постов.\n"
        "/post_in ниша тема минуты — пост через N минут\n"
        "Пример: /post_in ai Нейросети 5\n"
        "/add ниша тема ГГГГ-ММ-ДД ЧЧ:ММ\n"
        "/list — список постов\n"
        "/remove ID — удалить пост\n"
        "Доступны: родительский, строительный, ai"
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
    schedule.append({"id": new_id, "niche": niche, "topic": topic, "time": full_time, "done": False})
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
    schedule.append({"id": new_id, "niche": niche, "topic": topic, "time": full_time, "done": False})
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

# ================ ЗАПУСК ================
if __name__ == "__main__":
    print("🤖 Бот запущен...", flush=True)
    # Запускаем планировщик
    threading.Thread(target=scheduler_loop, daemon=True).start()
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        print(f"❌ Ошибка в polling: {e}", flush=True)
        sys.exit(1)