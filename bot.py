import sys
import os
import requests
import json
import urllib.parse
import threading
import time
import re
import traceback
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

# ===== ПРИНУДИТЕЛЬНЫЙ ВЫВОД ЛОГОВ =====
sys.stdout.reconfigure(line_buffering=True)

def log(msg):
    print(msg, flush=True)

# ===== ПОСТОЯННОЕ ХРАНИЛИЩЕ =====
DATA_DIR = "/data"
os.makedirs(DATA_DIR, exist_ok=True)
SCHEDULE_FILE = os.path.join(DATA_DIR, "schedule.json")
log(f"📂 Путь к расписанию: {SCHEDULE_FILE}")

# ===== Health-сервер =====
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        pass

def run_health_server():
    server = HTTPServer(('0.0.0.0', 8080), HealthHandler)
    server.serve_forever()

health_thread = threading.Thread(target=run_health_server, daemon=True)
health_thread.start()
log("🟢 Health-сервер запущен")

log("🚀 Бот запускается...")

# ===== ПРОВЕРКА ПЕРЕМЕННЫХ =====
try:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    AGNES_API_KEY = os.getenv("AGNES_API_KEY")
    GIGACHAT_API_KEY = os.getenv("GIGACHAT_API_KEY")
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан")
    if not AGNES_API_KEY:
        log("⚠️ AGNES_API_KEY не задан, но это не критично (будет использоваться резерв)")
    log("✅ Основные переменные загружены")
except Exception as e:
    log(f"❌ Ошибка: {e}")
    sys.exit(1)

VK_ACCOUNTS = {}
for name, suffix in [("родительский", "РОДИТЕЛЬСКИЙ"), ("строительный", "СТРОИТЕЛЬНЫЙ"), ("ai", "AI")]:
    token = os.getenv(f"VK_TOKEN_{suffix}")
    group_id_str = os.getenv(f"VK_GROUP_ID_{suffix}")
    if token and group_id_str:
        VK_ACCOUNTS[name] = {"token": token, "group_id": int(group_id_str)}
        log(f"✅ Группа '{name}': ID={group_id_str}")
if not VK_ACCOUNTS:
    log("❌ Нет групп")
    sys.exit(1)

# ===== TELEGRAM =====
try:
    r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=10)
    if r.status_code == 200:
        bot_info = r.json()["result"]
        log(f"✅ Подключение к Telegram: @{bot_info['username']}")
    else:
        log(f"❌ Ошибка доступа к Telegram: {r.status_code}")
        sys.exit(1)
except Exception as e:
    log(f"❌ Не удалось подключиться к Telegram: {e}")
    sys.exit(1)

try:
    requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", timeout=10)
    log("✅ Вебхук удалён")
except Exception as e:
    log(f"⚠️ Ошибка удаления вебхука: {e}")

# ===== ФУНКЦИИ РАБОТЫ С РАСПИСАНИЕМ =====
def load_schedule():
    try:
        if os.path.exists(SCHEDULE_FILE):
            with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                log(f"📂 Загружено {len(data)} записей из {SCHEDULE_FILE}")
                return data
        else:
            log(f"📂 Файл {SCHEDULE_FILE} не найден, создаём новый")
            save_schedule([])
            return []
    except Exception as e:
        log(f"⚠️ Ошибка загрузки: {e}")
        return []

def save_schedule(schedule):
    try:
        with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
            json.dump(schedule, f, ensure_ascii=False, indent=2)
        log(f"💾 Сохранено {len(schedule)} записей в {SCHEDULE_FILE}")
    except Exception as e:
        log(f"⚠️ Ошибка сохранения: {e}")

# ===== ГЕНЕРАЦИЯ ТЕКСТА =====
def generate_post_text(niche, topic):
    log(f"🔤 Генерация текста для {niche}: {topic}")
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
            result = response.json()
            text = result["choices"][0]["message"]["content"]
            log(f"   Текст получен, длина {len(text)}")
            return text
        else:
            log(f"   Ошибка текста: {response.status_code}")
            return None
    except Exception as e:
        log(f"   Исключение при генерации текста: {e}")
        traceback.print_exc(file=sys.stdout)
        return None

# ===== ГЕНЕРАЦИЯ КАРТИНКИ (Agnes -> GigaChat -> Pollinations) =====
def generate_image_agnes(prompt):
    log("   🖼️ Попытка Agnes...")
    if not AGNES_API_KEY:
        log("   AGNES_API_KEY не задан, пропускаем")
        return None
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
            url = response.json()["data"][0]["url"]
            log("   ✅ Agnes успешно")
            return url
        else:
            log(f"   ❌ Agnes ошибка: {response.status_code}")
            return None
    except Exception as e:
        log(f"   ❌ Agnes исключение: {e}")
        return None

def generate_image_gigachat(prompt):
    log("   🖼️ Попытка GigaChat...")
    if not GIGACHAT_API_KEY:
        log("   GIGACHAT_API_KEY не задан, пропускаем")
        return None
    headers = {
        "Authorization": f"Bearer {GIGACHAT_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "GigaChat-Image",
        "prompt": prompt,
        "size": "1024x1024",
        "n": 1
    }
    try:
        response = requests.post(
            "https://gigachat.devices.sberbank.ru/api/v1/images/generations",
            headers=headers,
            json=data,
            timeout=120
        )
        if response.status_code == 200:
            url = response.json()["data"][0]["url"]
            log("   ✅ GigaChat успешно")
            return url
        else:
            log(f"   ❌ GigaChat ошибка: {response.status_code}")
            return None
    except Exception as e:
        log(f"   ❌ GigaChat исключение: {e}")
        return None

def generate_image_pollinations(prompt):
    log("   🖼️ Попытка Pollinations...")
    try:
        prompt_encoded = urllib.parse.quote(prompt)
        url = f"https://image.pollinations.ai/prompt/{prompt_encoded}?width=1024&height=1024&nologo=true"
        # Проверяем доступность (HEAD-запрос)
        resp = requests.head(url, timeout=10)
        if resp.status_code == 200:
            log("   ✅ Pollinations доступен")
            return url
        else:
            log(f"   ❌ Pollinations ошибка: {resp.status_code}")
            return None
    except Exception as e:
        log(f"   ❌ Pollinations исключение: {e}")
        return None

def generate_image(niche, topic):
    log(f"🖼️ Генерация картинки для {niche}: {topic}")
    prompt = (
        f"Иллюстрация к посту на тему: {topic}. "
        "Яркие цвета, современный стиль, 1:1, без текста."
    )

    # Цепочка: Agnes -> GigaChat -> Pollinations
    url = generate_image_agnes(prompt)
    if url:
        return url

    url = generate_image_gigachat(prompt)
    if url:
        return url

    url = generate_image_pollinations(prompt)
    if url:
        return url

    log("❌ Все источники картинок недоступны")
    return None

def download_image(url):
    log(f"📥 Скачивание картинки: {url[:60]}...")
    try:
        response = requests.get(url, timeout=60)
        if response.status_code == 200:
            content = response.content
            log(f"   Успешно, размер {len(content)} байт")
            return content
        else:
            log(f"   Ошибка скачивания: {response.status_code}")
            return None
    except Exception as e:
        log(f"   Исключение при скачивании: {e}")
        traceback.print_exc(file=sys.stdout)
        return None

# ===== ПУБЛИКАЦИЯ В VK =====
def post_to_vk(niche, image_bytes, text):
    log(f"📤 Публикация в {niche}")
    if niche not in VK_ACCOUNTS:
        log(f"   Ниша '{niche}' не найдена")
        return False, f"Ниша '{niche}' не найдена"
    vk_token = VK_ACCOUNTS[niche]["token"]
    group_id = VK_ACCOUNTS[niche]["group_id"]

    if image_bytes is None:
        log("   Публикация без фото (только текст)")
        try:
            post = requests.get(
                "https://api.vk.com/method/wall.post",
                params={
                    "owner_id": group_id,
                    "message": text,
                    "access_token": vk_token,
                    "v": "5.131",
                    "from_group": 1
                }
            ).json()
            if "error" in post:
                log(f"   Ошибка публикации (текст): {post['error']['error_msg']}")
                return False, f"Ошибка публикации: {post['error']['error_msg']}"
            log(f"✅ Пост опубликован (без фото) в группе {group_id}, ID: {post['response']['post_id']}")
            return True, None
        except Exception as e:
            log(f"   Исключение при публикации без фото: {e}")
            return False, f"Исключение: {str(e)}"

    try:
        check = requests.get(
            "https://api.vk.com/method/users.get",
            params={"access_token": vk_token, "v": "5.131"}
        ).json()
        if "error" in check:
            log(f"   Ошибка токена: {check['error']['error_msg']}")
            return False, f"Ошибка токена: {check['error']['error_msg']}"
        log("   Токен OK")

        upload_resp = requests.get(
            "https://api.vk.com/method/photos.getWallUploadServer",
            params={"group_id": abs(group_id), "access_token": vk_token, "v": "5.131"}
        ).json()
        if "error" in upload_resp:
            log(f"   Ошибка upload_url: {upload_resp['error']['error_msg']}")
            return False, f"Ошибка upload_url: {upload_resp['error']['error_msg']}"
        upload_url = upload_resp["response"]["upload_url"]
        log(f"   upload_url получен: {upload_url[:50]}...")

        files = {"photo": ("image.jpg", image_bytes, "image/jpeg")}
        up = requests.post(upload_url, files=files).json()
        if "error" in up:
            log(f"   Ошибка загрузки: {up['error']['error_msg']}")
            return False, f"Ошибка загрузки: {up['error']['error_msg']}"
        if up.get("photo") == "[]":
            log("   Пустой ответ от сервера загрузки")
            return False, "Пустой ответ от сервера загрузки"

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
            log(f"   Ошибка сохранения: {save['error']['error_msg']}")
            return False, f"Ошибка сохранения: {save['error']['error_msg']}"
        photo = save["response"][0]
        attachment = f"photo{photo['owner_id']}_{photo['id']}"
        log(f"   Фото сохранено, attachment: {attachment}")

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
            log(f"   Ошибка публикации: {post['error']['error_msg']}")
            return False, f"Ошибка публикации: {post['error']['error_msg']}"
        log(f"✅ Пост опубликован в группе {group_id}, ID: {post['response']['post_id']}")
        return True, None
    except Exception as e:
        log(f"   Исключение в post_to_vk: {e}")
        traceback.print_exc(file=sys.stdout)
        return False, f"Исключение: {str(e)}"

# ===== ВЫПОЛНЕНИЕ ЗАДАНИЯ =====
def execute_scheduled_post(item):
    niche = item["niche"]
    topic = item["topic"]
    time_str = item["time"]
    log(f"📢 Публикую пост: '{topic}' в {time_str} (ниша: {niche})")

    log("🔤 Шаг 1: Генерация текста...")
    post_text = generate_post_text(niche, topic)
    if not post_text:
        log("❌ Текст не сгенерирован")
        return
    log(f"✅ Текст получен, длина {len(post_text)}")

    log("🖼️ Шаг 2: Генерация картинки...")
    image_url = generate_image(niche, topic)
    image_bytes = None
    if image_url:
        log(f"✅ URL картинки: {image_url[:60]}...")
        log("📥 Шаг 3: Скачивание картинки...")
        image_bytes = download_image(image_url)
        if image_bytes:
            log(f"✅ Картинка скачана, размер {len(image_bytes)} байт")
        else:
            log("⚠️ Картинка не скачалась, публикуем без фото")
    else:
        log("⚠️ Картинка не сгенерирована, публикуем без фото")

    log("📤 Шаг 4: Публикация в VK...")
    success, error = post_to_vk(niche, image_bytes, post_text)
    if success:
        log("✅ Пост опубликован!")
    else:
        log(f"❌ Ошибка публикации: {error}")

def scheduler_loop():
    log("🔄 Планировщик запущен")
    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            log(f"⏰ Текущее время: {now}")
            schedule = load_schedule()
            if not schedule:
                log("📭 Расписание пустое")
            else:
                for item in schedule:
                    if item["time"] == now and not item.get("done", False):
                        log(f"📢 Найдено задание: {item['topic']} в {item['time']}")
                        execute_scheduled_post(item)
                        item["done"] = True
                        save_schedule(schedule)
        except Exception as e:
            log(f"⚠️ Ошибка в планировщике: {e}")
            traceback.print_exc(file=sys.stdout)
        time.sleep(30)

# ===== ОБРАБОТЧИКИ КОМАНД =====
def process_message(message):
    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()
    log(f"📩 Получено: {text}")

    if text.startswith("/start"):
        send_message(chat_id,
            "👋 Бот для постов.\n"
            "/post_in ниша тема минуты — пост через N минут\n"
            "/list — список\n"
            "/debug — показать файл расписания"
        )
        return

    if text.startswith("/post_in"):
        parts = text.replace("/post_in", "").strip()
        match = re.search(r'(\d+)$', parts)
        if not match:
            send_message(chat_id, "❌ Укажи минуты")
            return
        minutes = int(match.group(1))
        rest = parts[:match.start()].strip()
        first_space = rest.find(' ')
        if first_space == -1:
            send_message(chat_id, "❌ Формат: /post_in ниша тема минуты")
            return
        niche = rest[:first_space].lower()
        topic = rest[first_space+1:].strip()
        if niche not in VK_ACCOUNTS:
            send_message(chat_id, f"❌ Ниша '{niche}' не найдена")
            return
        publish_time = datetime.now() + timedelta(minutes=minutes)
        full_time = publish_time.strftime("%Y-%m-%d %H:%M")
        schedule = load_schedule()
        new_id = str(int(time.time()))
        schedule.append({"id": new_id, "niche": niche, "topic": topic, "time": full_time, "done": False})
        save_schedule(schedule)
        send_message(chat_id, f"✅ Пост добавлен: [{niche}] {topic} в {full_time}")
        return

    if text.startswith("/list"):
        schedule = load_schedule()
        if not schedule:
            send_message(chat_id, "📭 Нет постов")
        else:
            lines = []
            for item in schedule:
                status = "✅" if item.get("done") else "⏳"
                lines.append(f"{status} ID:{item['id']} {item['topic']} -> {item['time']}")
            send_message(chat_id, "\n".join(lines[:10]))
        return

    if text.startswith("/debug"):
        try:
            if os.path.exists(SCHEDULE_FILE):
                with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
                    content = f.read()
                    send_message(chat_id, f"📄 Содержимое schedule.json:\n{content[:500]}")
            else:
                send_message(chat_id, "❌ Файл не найден")
        except Exception as e:
            send_message(chat_id, f"❌ Ошибка: {e}")
        return

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        log(f"⚠️ Ошибка отправки: {e}")

def get_updates(offset):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"offset": offset, "timeout": 30, "allowed_updates": ["message"]}
    try:
        resp = requests.get(url, params=params, timeout=35)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("result"):
                return data["result"]
        else:
            log(f"⚠️ getUpdates ошибка: {resp.status_code}")
    except Exception as e:
        log(f"⚠️ getUpdates исключение: {e}")
    return []

# ===== ЗАПУСК =====
if __name__ == "__main__":
    log("🤖 Бот запущен...")
    threading.Thread(target=scheduler_loop, daemon=True).start()
    update_id = 0
    while True:
        updates = get_updates(update_id + 1)
        for upd in updates:
            update_id = upd["update_id"]
            if "message" in upd:
                process_message(upd["message"])
        time.sleep(1)