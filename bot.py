import os
import sys
import threading
import requests
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType

sys.stderr = sys.stdout

print("🔹 Бот с генерацией текста (тест)", flush=True)

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

# ===== Функция генерации текста =====
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

# Основная логика
def run_bot():
    try:
        TOKEN = os.getenv('VK_TOKEN')
        if not TOKEN:
            print("❌ VK_TOKEN не задан", flush=True)
            return
        print(f"✅ VK_TOKEN получен (первые 10 символов): {TOKEN[:10]}", flush=True)

        vk_session = vk_api.VkApi(token=TOKEN)
        longpoll = VkLongPoll(vk_session)
        print("✅ Бот запущен и ждёт команды...", flush=True)

        for event in longpoll.listen():
            if event.type == VkEventType.MESSAGE_NEW and event.to_me:
                msg = event.text.strip()
                user_id = event.user_id
                print(f"📩 Получено: {msg}", flush=True)

                if msg.lower() == 'привет':
                    vk_session.method('messages.send', {
                        'user_id': user_id,
                        'message': 'Привет! Бот работает, генерация текста включена.',
                        'random_id': 0
                    })
                    continue

                elif msg.lower().startswith('сгенерируй текст'):
                    # Просто тест генерации
                    topic = msg.replace('сгенерируй текст', '').strip()
                    if not topic:
                        vk_session.method('messages.send', {
                            'user_id': user_id,
                            'message': '❌ Укажи тему после "сгенерируй текст"',
                            'random_id': 0
                        })
                        continue
                    vk_session.method('messages.send', {
                        'user_id': user_id,
                        'message': f'⏳ Генерирую текст на тему "{topic}"...',
                        'random_id': 0
                    })
                    text = generate_text(topic)
                    if text:
                        # Отправляем сгенерированный текст в ответ (не более 2000 символов)
                        answer = text[:2000] + ('...' if len(text)>2000 else '')
                        vk_session.method('messages.send', {
                            'user_id': user_id,
                            'message': answer,
                            'random_id': 0
                        })
                    else:
                        vk_session.method('messages.send', {
                            'user_id': user_id,
                            'message': '❌ Не удалось сгенерировать текст.',
                            'random_id': 0
                        })
                    continue

                else:
                    vk_session.method('messages.send', {
                        'user_id': user_id,
                        'message': 'Не знаю команды. Напиши "привет" или "сгенерируй текст ..."',
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