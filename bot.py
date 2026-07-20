import os
import sys
import threading
import re
import time
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType

sys.stderr = sys.stdout

print("🔹 Бот с командой 'пост' (без генерации)", flush=True)

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health():
    server = HTTPServer(('0.0.0.0', 8080), HealthHandler)
    print("🟢 Health-сервер запущен", flush=True)
    server.serve_forever()

def run_bot():
    try:
        TOKEN = os.getenv('VK_TOKEN')
        if not TOKEN:
            print("❌ VK_TOKEN не задан", flush=True)
            return
        print(f"✅ VK_TOKEN получен (первые 10 символов): {TOKEN[:10]}", flush=True)

        # Читаем группы (для простоты пока только родительская)
        GROUP_ID = os.getenv('GROUP_ID_1')
        if not GROUP_ID:
            print("❌ GROUP_ID_1 не задан", flush=True)
            return
        GROUP_ID = int(GROUP_ID)

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
                        'message': 'Привет! Бот с командой "пост".\nПример: пост текст через 2 минуты',
                        'random_id': 0
                    })
                    continue

                elif msg.lower().startswith('пост'):
                    # Парсим: пост текст через X минут
                    match_text = re.search(r'пост\s+(.+?)\s+через\s+(\d+)\s+минут', msg, re.I)
                    if not match_text:
                        vk_session.method('messages.send', {
                            'user_id': user_id,
                            'message': '❌ Формат: пост ТЕКСТ через X минут',
                            'random_id': 0
                        })
                        continue

                    text = match_text.group(1).strip()
                    minutes = int(match_text.group(2))

                    vk_session.method('messages.send', {
                        'user_id': user_id,
                        'message': f'⏳ Создаю пост... (без генерации)',
                        'random_id': 0
                    })

                    try:
                        vk = vk_api.VkApi(token=TOKEN).get_api()  # используем токен пульта (если он имеет права на стену) или токен группы? Лучше токен группы.
                        # Для простоты используем токен пульта, но он должен иметь права на стену. Если нет, используем отдельный токен.
                        # Временно используем токен пульта — если ошибка, потом поменяем.
                        publish_time = datetime.now() + timedelta(minutes=minutes)
                        publish_timestamp = int(publish_time.timestamp())
                        vk.wall.post(
                            owner_id=GROUP_ID,
                            message=text,
                            attachments=None,
                            publish_date=publish_timestamp,
                            from_group=1
                        )
                        vk_session.method('messages.send', {
                            'user_id': user_id,
                            'message': f'✅ Пост создан. Опубликуется через {minutes} мин.',
                            'random_id': 0
                        })
                    except Exception as e:
                        vk_session.method('messages.send', {
                            'user_id': user_id,
                            'message': f'❌ Ошибка создания поста: {e}',
                            'random_id': 0
                        })
                    continue

                else:
                    vk_session.method('messages.send', {
                        'user_id': user_id,
                        'message': 'Не знаю команды. Напиши "привет" или "пост текст через X минут"',
                        'random_id': 0
                    })
    except Exception as e:
        print(f"❌ Ошибка в боте: {e}", flush=True)

if __name__ == '__main__':
    print("🔹 Запуск...", flush=True)
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    time.sleep(2)
    run_health()