import os
import sys
import threading
import requests
import re
import time
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType

sys.stderr = sys.stdout

print("🔹 Запуск бота с генерацией текста", flush=True)

# Health-сервер
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health():
    server = HTTPServer(('0.0.0.0', 8080), HealthHandler)
    print("🟢 Health-сервер запущен", flush=True)
    server.serve_forever()

# ===== Функция генерации текста через Agnes =====
AGNES_API_KEY = os.getenv('AGNES_API_KEY')
AGNES_BASE_URL = "https://apihub.agnes-ai.com/v1"

def generate_text(topic):
    print(f"   🔤 Генерация текста для: {topic}", flush=True)
    if not AGNES_API_KEY:
        print("   ❌ AGNES_API_KEY не задан", flush=True)
        return None
    headers = {
        "Authorization": f"Bearer {AGNES_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "agnes-2.0-flash",
        "messages": [
            {"role": "system", "content": "Ты — профессиональный SMM-менеджер. Напиши пост для ВКонтакте на заданную тему. Длина до 200 слов. Добавь 5 хештегов."},
            {"role": "user", "content": f"Тема: {topic}"}
        ],
        "temperature": 0.8
    }
    try:
        print("   🔤 Отправка запроса к Agnes...", flush=True)
        resp = requests.post(f"{AGNES_BASE_URL}/chat/completions", headers=headers, json=data, timeout=90)
        print(f"   🔤 Ответ получен, статус: {resp.status_code}", flush=True)
        resp.raise_for_status()
        result = resp.json()
        text = result['choices'][0]['message']['content']
        print(f"   🔤 Текст сгенерирован, длина: {len(text)} символов", flush=True)
        return text
    except Exception as e:
        print(f"   ❌ Ошибка генерации текста: {e}", flush=True)
        return None

# ===== Создание поста в группе (без медиа) =====
def create_post(group_id, token, text, minutes):
    try:
        vk = vk_api.VkApi(token=token).get_api()
        publish_time = datetime.now() + timedelta(minutes=minutes)
        publish_timestamp = int(publish_time.timestamp())
        vk.wall.post(
            owner_id=group_id,
            message=text,
            attachments=None,
            publish_date=publish_timestamp,
            from_group=1
        )
        return True
    except Exception as e:
        print(f"   ❌ Ошибка создания поста: {e}", flush=True)
        return False

# ===== Основная логика =====
def run_bot():
    try:
        TOKEN = os.getenv('VK_TOKEN')
        if not TOKEN:
            print("❌ VK_TOKEN не задан", flush=True)
            return

        # Читаем группы из переменных
        groups = []
        for i, name in enumerate(['родительский', 'строительный', 'ai'], 1):
            token = os.getenv(f'VK_TOKEN_{i}')
            gid = os.getenv(f'GROUP_ID_{i}')
            if token and gid:
                groups.append({'name': name, 'id': int(gid), 'token': token})
                print(f"✅ Группа {i} ({name}): ID={gid}", flush=True)

        if not groups:
            print("❌ Нет групп", flush=True)
            return

        vk_session = vk_api.VkApi(token=TOKEN)
        longpoll = VkLongPoll(vk_session)
        print("✅ Бот запущен и ждёт команды...", flush=True)

        for event in longpoll.listen():
            if event.type == VkEventType.MESSAGE_NEW and event.to_me:
                msg_raw = event.text.strip()
                msg = msg_raw.replace('&quot;', '"').replace('&amp;', '&')
                user_id = event.user_id
                print(f"📩 Получено: {msg}", flush=True)

                if msg.lower() == 'привет':
                    vk_session.method('messages.send', {
                        'user_id': user_id,
                        'message': 'Привет! Я бот-менеджер (генерация текста).\nКоманда: пост в "Название" на тему "..." через X минут',
                        'random_id': 0
                    })
                    continue

                elif msg.lower().startswith('пост в'):
                    # Парсинг
                    match_group = re.search(r'пост в "([^"]+)"', msg, re.I)
                    match_topic = re.search(r'на тему "([^"]+)"', msg, re.I)
                    match_time = re.search(r'через\s+(\d+)\s+минут', msg, re.I)

                    if not match_group or not match_topic or not match_time:
                        vk_session.method('messages.send', {
                            'user_id': user_id,
                            'message': '❌ Формат: пост в "Название" на тему "..." через X минут',
                            'random_id': 0
                        })
                        continue

                    group_name = match_group.group(1).strip().lower()
                    topic = match_topic.group(1).strip()
                    minutes = int(match_time.group(1))

                    # Найти группу
                    group = next((g for g in groups if g['name'] == group_name), None)
                    if not group:
                        vk_session.method('messages.send', {
                            'user_id': user_id,
                            'message': f'❌ Группа "{group_name}" не найдена',
                            'random_id': 0
                        })
                        continue

                    vk_session.method('messages.send', {
                        'user_id': user_id,
                        'message': '⏳ Генерирую текст... (до 20 сек)',
                        'random_id': 0
                    })

                    text = generate_text(topic)
                    if not text:
                        vk_session.method('messages.send', {
                            'user_id': user_id,
                            'message': '❌ Не удалось сгенерировать текст.',
                            'random_id': 0
                        })
                        continue

                    success = create_post(group['id'], group['token'], text, minutes)
                    if success:
                        vk_session.method('messages.send', {
                            'user_id': user_id,
                            'message': f'✅ Пост для "{group_name}" создан (текст). Опубликуется через {minutes} мин.',
                            'random_id': 0
                        })
                    else:
                        vk_session.method('messages.send', {
                            'user_id': user_id,
                            'message': f'❌ Ошибка создания поста в "{group_name}".',
                            'random_id': 0
                        })
                    continue

                else:
                    vk_session.method('messages.send', {
                        'user_id': user_id,
                        'message': 'Не знаю команды. Напиши "привет" или "пост в ..."',
                        'random_id': 0
                    })

    except Exception as e:
        print(f"❌ Ошибка: {e}", flush=True)

if __name__ == '__main__':
    print("🔹 Запуск...", flush=True)
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    time.sleep(2)
    run_health()