import sys
import os
import requests
import json
import urllib.parse
import threading
import time
import re
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.stdout.reconfigure(line_buffering=True)

# ===== ФИКСИРУЕМ ПУТЬ К ФАЙЛУ =====
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEDULE_FILE = os.path.join(SCRIPT_DIR, "schedule.json")
print(f"📂 Папка бота: {SCRIPT_DIR}", flush=True)
print(f"📂 Путь к расписанию: {SCHEDULE_FILE}", flush=True)

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
print("🟢 Health-сервер запущен", flush=True)

print("🚀 Бот запускается...", flush=True)

# ===== Переменные =====
try:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    AGNES_API_KEY = os.getenv("AGNES_API_KEY")
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан")
    if not AGNES_API_KEY:
        raise ValueError("AGNES_API_KEY не задан")
    print("✅ Основные переменные загружены", flush=True)
except Exception as e:
    print(f"❌ Ошибка: {e}", flush=True)
    sys.exit(1)

VK_ACCOUNTS = {}
for name, suffix in [("родительский", "РОДИТЕЛЬСКИЙ"), ("строительный", "СТРОИТЕЛЬНЫЙ"), ("ai", "AI")]:
    token = os.getenv(f"VK_TOKEN_{suffix}")
    group_id_str = os.getenv(f"VK_GROUP_ID_{suffix}")
    if token and group_id_str:
        VK_ACCOUNTS[name] = {"token": token, "group_id": int(group_id_str)}
        print(f"✅ Группа '{name}': ID={group_id_str}", flush=True)
if not VK_ACCOUNTS:
    print("❌ Нет групп", flush=True)
    sys.exit(1)

# ===== Telegram =====
try:
    r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=10)
    if r.status_code == 200:
        bot_info = r.json()["result"]
        print(f"✅ Подключение к Telegram: @{bot_info['username']}", flush=True)
    else:
        print(f"❌ Ошибка доступа к Telegram: {r.status_code}", flush=True)
        sys.exit(1)
except Exception as e:
    print(f"❌ Не удалось подключиться к Telegram: {e}", flush=True)
    sys.exit(1)

try:
    requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", timeout=10)
    print("✅ Вебхук удалён", flush=True)
except Exception as e:
    print(f"⚠️ Ошибка удаления вебхука: {e}", flush=True)

# ===== Функции работы с расписанием =====
def load_schedule():
    try:
        if os.path.exists(SCHEDULE_FILE):
            with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                print(f"📂 Загружено {len(data)} записей из {SCHEDULE_FILE}", flush=True)
                return data
        else:
            print(f"📂 Файл {SCHEDULE_FILE} не найден", flush=True)
            return []
    except Exception as e:
        print(f"⚠️ Ошибка загрузки: {e}", flush=True)
        return []

def save_schedule(schedule):
    try:
        with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
            json.dump(schedule, f, ensure_ascii=False, indent=2)
        print(f"💾 Сохранено {len(schedule)} записей в {SCHEDULE_FILE}", flush=True)
    except Exception as e:
        print(f"⚠️ Ошибка сохранения: {e}", flush=True)

# ===== Генерация и публикация (заглушки) =====
def generate_post_text(niche, topic):
    return f"🔥 Пост для {niche} на тему: {topic}\n\n(текст сгенерирован автоматически)"

def get_image_prompt(niche, topic):
    return f"Иллюстрация к посту: {topic}"

def generate_image(niche, topic):
    prompt = get_image_prompt(niche, topic)
    # Используем Pollinations как резерв
    prompt_encoded = urllib.parse.quote(prompt)
    return f"https://image.pollinations.ai/prompt/{prompt_encoded}?width=1024&height=1024&nologo=true"

def download_image(url):
    try:
        resp = requests.get(url, timeout=60)
        if resp.status_code == 200:
            return resp.content
        return None
    except Exception as e:
        print(f"⚠️ Ошибка скачивания: {e}", flush=True)
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
    print(f"📢 Публикую: {topic} в {item['time']} (ниша: {niche})", flush=True)
    post_text = generate_post_text(niche, topic)
    if not post_text:
        print("❌ Текст не сгенерирован", flush=True)
        return
    image_url = generate_image(niche, topic)
    print(f"🖼️ URL картинки: {image_url[:80]}...", flush=True)
    image_bytes = download_image(image_url)
    if not image_bytes:
        print("❌ Картинка не скачалась", flush=True)
        return
    success, error = post_to_vk(niche, image_bytes, post_text)
    if success:
        print("✅ Пост опубликован!", flush=True)
    else:
        print(f"❌ Ошибка публикации: {error}", flush=True)

def scheduler_loop():
    print("🔄 Планировщик запущен", flush=True)
    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            print(f"⏰ Текущее время: {now}", flush=True)
            schedule = load_schedule()
            if not schedule:
                print("📭 Расписание пустое", flush=True)
            else:
                for item in schedule:
                    if item["time"] == now and not item.get("done", False):
                        print(f"📢 Найдено задание: {item['topic']} в {item['time']}", flush=True)
                        execute_scheduled_post(item)
                        item["done"] = True
                        save_schedule(schedule)
        except Exception as e:
            print(f"⚠️ Ошибка в планировщике: {e}", flush=True)
        time.sleep(30)

# ===== Обработчики команд =====
def process_message(message):
    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()
    print(f"📩 Получено: {text}", flush=True)

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
        print(f"⚠️ Ошибка отправки: {e}", flush=True)

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
            print(f"⚠️ getUpdates ошибка: {resp.status_code}", flush=True)
    except Exception as e:
        print(f"⚠️ getUpdates исключение: {e}", flush=True)
    return []

# ===== Запуск =====
if __name__ == "__main__":
    print("🤖 Бот запущен...", flush=True)
    threading.Thread(target=scheduler_loop, daemon=True).start()
    update_id = 0
    while True:
        updates = get_updates(update_id + 1)
        for upd in updates:
            update_id = upd["update_id"]
            if "message" in upd:
                process_message(upd["message"])
        time.sleep(1)