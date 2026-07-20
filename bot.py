import os
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType

sys.stderr = sys.stdout

print("🔹 Запуск минимальной версии бота", flush=True)

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

# Основная логика бота
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
                        'message': 'Привет! Это минимальная версия бота.',
                        'random_id': 0
                    })
                    print("✅ Ответил на привет", flush=True)
                else:
                    vk_session.method('messages.send', {
                        'user_id': user_id,
                        'message': 'Не знаю такой команды. Напиши "привет"',
                        'random_id': 0
                    })
    except Exception as e:
        print(f"❌ Ошибка в боте: {e}", flush=True)

if __name__ == '__main__':
    print("🔹 Запуск потоков...", flush=True)
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    print("🟢 Поток бота запущен", flush=True)
    time.sleep(2)
    run_health()