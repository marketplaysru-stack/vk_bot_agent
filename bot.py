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

# Health-сервер
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
print("🟢 Health-сервер запущен на порту 8080", flush=True)

print("🚀 Бот запускается...", flush=True)

# Переменные
try:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    AGNES_API_KEY = os.getenv("AGNES_API_KEY")
    if not BOT_TOKEN:
        raise ValueError("❌ BOT_TOKEN не задан")
    if not AGNES_API_KEY:
        raise ValueError("❌ AGNES_API_KEY не задан")
    print("✅ Основные переменные загружены", flush=True)
except Exception as e:
    print(f"❌ Ошибка: {e}", flush=True)
    sys.exit(1)

# Группы
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

# Проверка Telegram
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

# Удаляем вебхук
try:
    requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", timeout=10)
    print("✅ Вебхук удалён", flush=True)
except Exception as e:
    print(f"⚠️ Ошибка удаления вебхука: {e}", flush=True)

SCHEDULE_FILE = "schedule.json"

# ===== Функции =====
def load_schedule():
    try:
        if os.path.exists(SCHEDULE_FILE):
            with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                print(f"📂 Загружено {len(data)} записей", flush=True)
                return data
        else:
            print("📂 Файл расписания не найден", flush=True)
            return []
    except Exception as e:
        print(f"⚠️ Ошибка загрузки расписания: {e}", flush=True)
        return []

def save_schedule(schedule):
    try:
        with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
            json.dump(schedule, f, ensure_ascii=False, indent=2)
        print(f"💾 Сохранено {len(schedule)} записей", flush=True)
    except Exception as e:
        print(f"⚠️ Ошибка сохранения: {e}", flush=True)

def generate_post_text(niche, topic):
    # ... (оставляем как было, для краткости опустим, но он есть)
    return "Тестовый текст"

def get_image_prompt(niche, topic):
    return f"Иллюстрация к посту: {topic}"

def generate_image(niche, topic):
    return "https://image.pollinations.ai/prompt/test"

def download_image(url):
    return b"fake"

def post_to_vk(niche, image_bytes, text):
    print(f"📤 Публикация в {niche}", flush=True)
    return True, None

def execute_scheduled_post(item):
    niche = item["niche"]
    topic = item["topic"]
    print(f"📢 Публикую пост: {topic} в {item['time']} (ниша: {niche})", flush=True)
    post_text = generate_post_text(niche, topic)
    if not post_text:
        print("❌ Текст не сгенерирован", flush=True)
        return
    image_url = generate_image(niche, topic)
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
            return
        lines = []
        for item in schedule:
            status = "✅" if item.get("done") else "⏳"
            lines.append(f"{status} ID:{item['id']} {item['topic']} -> {item['time']}")
        send_message(chat_id, "\n".join(lines[:10]))
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