import sys
import os
import requests
import json
import urllib.parse
import threading
import time
import re
import traceback
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

# ===== ПРИНУДИТЕЛЬНЫЙ ВЫВОД ЛОГОВ =====
sys.stdout.reconfigure(line_buffering=True)

# ===== НАСТРОЙКА ЛОГГИРОВАНИЯ (файл + консоль) =====
DATA_DIR = "/data"
os.makedirs(DATA_DIR, exist_ok=True)
LOG_FILE = os.path.join(DATA_DIR, "bot_ai.log")

logger = logging.getLogger()
logger.setLevel(logging.INFO)

file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(console_handler)

def log(msg):
    logging.info(msg)

# ===== ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ (индивидуальные для этой группы) =====
VK_TOKEN = os.getenv("VK_TOKEN")
VK_GROUP_ID = os.getenv("VK_GROUP_ID")
MY_NICHE = os.getenv("MY_NICHE", "ai").lower()  # по умолчанию "ai"
AGNES_API_KEY = os.getenv("AGNES_API_KEY")
GIGACHAT_API_KEY = os.getenv("GIGACHAT_API_KEY")
PORT = int(os.getenv("PORT", 8080))  # порт для health-сервера

# Проверка обязательных переменных
if not VK_TOKEN:
    log("❌ VK_TOKEN не задан")
    sys.exit(1)
if not VK_GROUP_ID:
    log("❌ VK_GROUP_ID не задан")
    sys.exit(1)
try:
    VK_GROUP_ID = int(VK_GROUP_ID)
except ValueError:
    log(f"❌ VK_GROUP_ID должен быть числом, получено: {VK_GROUP_ID}")
    sys.exit(1)
if not AGNES_API_KEY:
    log("⚠️ AGNES_API_KEY не задан (картинки через Pollinations)")

log(f"🚀 Запуск исполнителя для ниши '{MY_NICHE}', группа ID {VK_GROUP_ID}")

# ===== ПУТЬ К ОБЩЕМУ ФАЙЛУ РАСПИСАНИЯ =====
SCHEDULE_FILE = os.path.join(DATA_DIR, "schedule.json")
log(f"📂 Файл расписания: {SCHEDULE_FILE}")

# ===== Health-сервер =====
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        pass

def run_health_server():
    server = HTTPServer(('0.0.0.0', PORT), HealthHandler)
    server.serve_forever()

health_thread = threading.Thread(target=run_health_server, daemon=True)
health_thread.start()
log(f"🟢 Health-сервер запущен (порт {PORT})")

# ===== ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ RETRY =====
def retry_call(func, *args, max_retries=3, delay=2, backoff=2, **kwargs):
    last_exception = None
    for attempt in range(max_retries):
        try:
            result = func(*args, **kwargs)
            if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], bool):
                if not result[0] and attempt < max_retries - 1:
                    raise Exception(f"Function returned failure: {result[1]}")
                return result
            if isinstance(result, dict) and result.get('error'):
                raise Exception(result['error'].get('error_msg', 'Unknown API error'))
            return result
        except Exception as e:
            last_exception = e
            log(f"   ⚠️ Попытка {attempt+1}/{max_retries} не удалась: {e}")
            if attempt < max_retries - 1:
                sleep_time = delay * (backoff ** attempt)
                log(f"   ⏳ Повтор через {sleep_time:.1f} сек...")
                time.sleep(sleep_time)
            else:
                log(f"   ❌ Все {max_retries} попыток провалились")
    raise last_exception

# ===== РАБОТА С РАСПИСАНИЕМ =====
def load_schedule():
    try:
        if os.path.exists(SCHEDULE_FILE):
            with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                log(f"📂 Загружено {len(data)} записей из {SCHEDULE_FILE}")
                return data
        else:
            log(f"📂 Файл {SCHEDULE_FILE} не найден")
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
    def _do():
        response = requests.post(
            "https://apihub.agnes-ai.com/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=120
        )
        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}: {response.text[:200]}")
        result = response.json()
        return result["choices"][0]["message"]["content"]
    try:
        text = retry_call(_do, max_retries=3, delay=2, backoff=2)
        log(f"   Текст получен, длина {len(text)}")
        return text
    except Exception as e:
        log(f"   ❌ Генерация текста провалилась: {e}")
        return None

# ===== ГЕНЕРАЦИЯ КАРТИНКИ =====
def generate_image_agnes(prompt):
    log("   🖼️ Попытка Agnes...")
    if not AGNES_API_KEY:
        log("   AGNES_API_KEY не задан")
        return None
    headers = {"Authorization": f"Bearer {AGNES_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "agnes-image-2.1-flash",
        "prompt": prompt,
        "size": "1024x1024",
        "n": 1
    }
    def _do():
        response = requests.post(
            "https://apihub.agnes-ai.com/v1/images/generations",
            headers=headers,
            json=data,
            timeout=120
        )
        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}")
        json_resp = response.json()
        if not json_resp.get("data") or len(json_resp["data"]) == 0:
            raise Exception("Empty data")
        return json_resp["data"][0]["url"]
    try:
        url = retry_call(_do, max_retries=2, delay=3, backoff=2)
        log("   ✅ Agnes успешно")
        return url
    except Exception as e:
        log(f"   ❌ Agnes окончательно: {e}")
        return None

def generate_image_gigachat(prompt):
    log("   🖼️ Попытка GigaChat...")
    if not GIGACHAT_API_KEY:
        log("   GIGACHAT_API_KEY не задан")
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
    def _do():
        response = requests.post(
            "https://gigachat.devices.sberbank.ru/api/v1/images/generations",
            headers=headers,
            json=data,
            timeout=120
        )
        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}")
        json_resp = response.json()
        if not json_resp.get("data") or len(json_resp["data"]) == 0:
            raise Exception("Empty data")
        return json_resp["data"][0]["url"]
    try:
        url = retry_call(_do, max_retries=2, delay=3, backoff=2)
        log("   ✅ GigaChat успешно")
        return url
    except Exception as e:
        log(f"   ❌ GigaChat окончательно: {e}")
        return None

def generate_image_pollinations(prompt):
    log("   🖼️ Попытка Pollinations...")
    try:
        prompt_encoded = urllib.parse.quote(prompt)
        url = f"https://image.pollinations.ai/prompt/{prompt_encoded}?width=1024&height=1024&nologo=true"
        log("   ✅ URL сформирован")
        return url
    except Exception as e:
        log(f"   ❌ Pollinations исключение: {e}")
        return None

def generate_image(niche, topic):
    log(f"🖼️ Генерация картинки для {niche}: {topic}")
    prompt = (
        f"Иллюстрация к посту на тему: {topic}. "
        "Яркие цвета, современный стиль, 1:1, без текста."
    )
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
    def _do():
        response = requests.get(url, timeout=60)
        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}")
        if len(response.content) < 100:
            raise Exception("Слишком маленький ответ")
        return response.content
    try:
        content = retry_call(_do, max_retries=3, delay=2, backoff=2)
        log(f"   Успешно, размер {len(content)} байт")
        return content
    except Exception as e:
        log(f"   ❌ Скачивание провалилось: {e}")
        return None

# ===== ПУБЛИКАЦИЯ В VK =====
def vk_api_request(method, params, token, retries=3):
    base_url = "https://api.vk.com/method/"
    params = params.copy()
    params["access_token"] = token
    params["v"] = "5.131"
    def _do():
        response = requests.get(base_url + method, params=params, timeout=60)
        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}")
        json_resp = response.json()
        if "error" in json_resp:
            log(f"   ❌ VK API ошибка в {method}: {json_resp['error']}")
            raise Exception(json_resp["error"]["error_msg"])
        return json_resp["response"]
    try:
        return retry_call(_do, max_retries=retries, delay=2, backoff=2)
    except Exception as e:
        log(f"   ❌ Ошибка VK API ({method}): {e}")
        return None

def post_to_vk(niche, image_bytes, text):
    log(f"📤 Публикация в {niche}")
    if niche != MY_NICHE:
        log(f"   ⚠️ Задание для другой ниши ({niche}), пропускаем")
        return False, "Не моя ниша"

    group_id = VK_GROUP_ID
    token = VK_TOKEN

    if image_bytes is None:
        log("   Публикация без фото (только текст)")
        result = vk_api_request("wall.post", {"owner_id": group_id, "message": text, "from_group": 1}, token=token, retries=3)
        if result is None:
            return False, "Ошибка публикации текста"
        log(f"✅ Пост опубликован (без фото) в группе {group_id}, ID: {result['post_id']}")
        return True, None

    try:
        # Получение upload_url
        upload_resp = vk_api_request("photos.getWallUploadServer", {"group_id": abs(group_id)}, token=token, retries=3)
        if upload_resp is None:
            return False, "Не удалось получить upload_url"
        upload_url = upload_resp["upload_url"]
        log(f"   upload_url получен: {upload_url[:50]}...")

        # Загрузка фото
        def _upload():
            files = {"photo": ("image.jpg", image_bytes, "image/jpeg")}
            resp = requests.post(upload_url, files=files, timeout=60)
            if resp.status_code != 200:
                raise Exception(f"HTTP {resp.status_code}")
            data = resp.json()
            log(f"   Ответ сервера загрузки: {data}")
            if data.get("error"):
                raise Exception(f"Ошибка загрузки: {data['error']}")
            if not all(k in data for k in ("server", "photo", "hash")):
                raise Exception(f"Неполный ответ: {data}")
            if data.get("photo") == "[]" or not data.get("photo"):
                raise Exception("photo пустое или '[]'")
            return data

        up = retry_call(_upload, max_retries=3, delay=2, backoff=2)

        # Сохранение фото
        save_params = {
            "group_id": abs(group_id),
            "server": up["server"],
            "photo": up["photo"],
            "hash": up["hash"]
        }
        save_resp = vk_api_request("photos.saveWallPhoto", save_params, token=token, retries=3)
        if save_resp is None:
            return False, "Ошибка сохранения фото"
        photo = save_resp[0]
        attachment = f"photo{photo['owner_id']}_{photo['id']}"
        log(f"   Фото сохранено, attachment: {attachment}")

        # Публикация поста
        post_params = {
            "owner_id": group_id,
            "message": text,
            "attachments": attachment,
            "from_group": 1
        }
        post_resp = vk_api_request("wall.post", post_params, token=token, retries=3)
        if post_resp is None:
            return False, "Ошибка публикации поста"
        log(f"✅ Пост опубликован в группе {group_id}, ID: {post_resp['post_id']}")
        return True, None
    except Exception as e:
        log(f"   Исключение в post_to_vk: {e}")
        traceback.print_exc(file=sys.stdout)
        return False, f"Исключение: {str(e)}"

# ===== ВЫПОЛНЕНИЕ ЗАПЛАНИРОВАННОГО ПОСТА =====
def execute_scheduled_post(item):
    if item["niche"] != MY_NICHE:
        log(f"⏭️ Пропускаем задание для другой ниши: {item['niche']}")
        return

    niche = item["niche"]
    topic = item["topic"]
    time_str = item["time"]
    log(f"📢 Публикую запланированный пост: '{topic}' в {time_str} (ниша: {niche})")

    log("🔤 Шаг 1: Генерация текста...")
    post_text = generate_post_text(niche, topic)
    if not post_text:
        log("❌ Текст не сгенерирован, пропускаем пост")
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
        log("✅ Пост успешно опубликован!")
    else:
        log(f"❌ Ошибка публикации: {error}")

# ===== ПЛАНИРОВЩИК =====
def scheduler_loop():
    log("🔄 Планировщик запущен (проверка каждые 30 секунд)")
    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            log(f"⏰ Текущее время: {now}")
            schedule = load_schedule()
            if not schedule:
                log("📭 Расписание пустое")
            else:
                # Ищем задания для нашей ниши
                for item in schedule:
                    if item["time"] == now and not item.get("done", False) and item["niche"] == MY_NICHE:
                        log(f"📢 Найдено задание: {item['topic']} в {item['time']}")
                        execute_scheduled_post(item)
                        item["done"] = True
                        save_schedule(schedule)
        except Exception as e:
            log(f"⚠️ Ошибка в планировщике: {e}")
            traceback.print_exc(file=sys.stdout)
        time.sleep(30)

# ===== ЗАПУСК =====
if __name__ == "__main__":
    log(f"🤖 Бот-исполнитель для ниши '{MY_NICHE}' запущен")
    # Добавляем тестовое задание, если расписание пустое (для проверки)
    schedule = load_schedule()
    if not schedule:
        test_time = (datetime.now() + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M")
        schedule.append({
            "id": f"test_{MY_NICHE}_{int(time.time())}",
            "niche": MY_NICHE,
            "topic": f"Тестовый пост для {MY_NICHE}",
            "time": test_time,
            "done": False
        })
        save_schedule(schedule)
        log(f"🧪 Добавлено тестовое задание на {test_time}")

    threading.Thread(target=scheduler_loop, daemon=True).start()
    # Бесконечный цикл, чтобы бот не завершался
    while True:
        time.sleep(60)