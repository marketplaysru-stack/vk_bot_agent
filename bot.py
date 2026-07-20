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
import traceback

sys.stderr = sys.stdout

# ===== Health-сервер =====
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health():
    server = HTTPServer(('0.0.0.0', 8080), HealthHandler)
    print("🟢 Health-сервер запущен", flush=True)
    server.serve_forever()

# ===== Проверка переменных =====
print("🔹 Начало скрипта", flush=True)

TOKEN = os.getenv('VK_TOKEN')
if not TOKEN:
    print("❌ VK_TOKEN не задан", flush=True)
    sys.exit(1)
print(f"✅ VK_TOKEN получен (первые 10 символов): {TOKEN[:10]}", flush=True)

AGNES_API_KEY = os.getenv('AGNES_API_KEY')
if not AGNES_API_KEY:
    print("❌ AGNES_API_KEY не задан", flush=True)
    sys.exit(1)
print("✅ AGNES_API_KEY получен", flush=True)

groups = []
group_names = ['родительский', 'строительный', 'ai']
for i, name in enumerate(group_names, 1):
    token = os.getenv(f'VK_TOKEN_{i}')
    gid = os.getenv(f'GROUP_ID_{i}')
    if token and gid:
        groups.append({
            'name': name,
            'id': int(gid),
            'token': token
        })
        print(f"✅ Группа {i} ({name}): ID={gid}", flush=True)
    else:
        print(f"⚠️ Группа {i} ({name}) не настроена", flush=True)

if not groups:
    print("❌ Нет ни одной настроенной группы", flush=True)
    sys.exit(1)

# ===== Функции Agnes =====
AGNES_BASE_URL = "https://apihub.agnes-ai.com/v1"

def generate_text(topic):
    print(f"   🔤 Генерация текста для: {topic}", flush=True)
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
        resp = requests.post(f"{AGNES_BASE_URL}/chat/completions", headers=headers, json=data, timeout=90)
        resp.raise_for_status()
        return resp.json()['choices'][0]['message']['content']
    except Exception as e:
        print(f"   ❌ Ошибка текста: {e}", flush=True)
        return None

# ===== Загрузка медиа =====
def download_media(url):
    try:
        resp = requests.get(url, stream=True, timeout=60)
        resp.raise_for_status()
        content_type = resp.headers.get('content-type', '')
        if 'image' in content_type:
            ext = 'jpg'
        elif 'video' in content_type:
            ext = 'mp4'
        else:
            ext = 'bin'
        filename = f"temp_media_{int(time.time())}.{ext}"
        with open(filename, 'wb') as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        return filename
    except Exception as e:
        print(f"   ❌ Ошибка скачивания медиа: {e}", flush=True)
        return None

def upload_photo(vk, group_id, filepath):
    try:
        upload_server = vk.photos.getWallUploadServer(group_id=abs(group_id))
        upload_url = upload_server['upload_url']
        with open(filepath, 'rb') as f:
            files = {'photo': f}
            resp = requests.post(upload_url, files=files).json()
        save_params = {
            'server': resp['server'],
            'photo': resp['photo'],
            'hash': resp['hash'],
            'group_id': abs(group_id)
        }
        saved = vk.photos.saveWallPhoto(**save_params)[0]
        return f"photo{saved['owner_id']}_{saved['id']}"
    except Exception as e:
        print(f"   ❌ Ошибка загрузки фото: {e}", flush=True)
        return None

def upload_video(vk, group_id, filepath):
    try:
        upload_data = vk.video.save(
            name='Видео',
            group_id=abs(group_id),
            privacy_view='all',
            privacy_comment='all'
        )
        upload_url = upload_data['upload_url']
        with open(filepath, 'rb') as f:
            files = {'video_file': f}
            resp = requests.post(upload_url, files=files).json()
        owner_id = resp.get('owner_id')
        video_id = resp.get('video_id') or resp.get('id')
        if owner_id and video_id:
            return f"video{owner_id}_{video_id}"
        else:
            return None
    except Exception as e:
        print(f"   ❌ Ошибка загрузки видео: {e}", flush=True)
        return None

def create_post(group, text, minutes, attachment):
    try:
        vk = vk_api.VkApi(token=group['token']).get_api()
        publish_time = datetime.now() + timedelta(minutes=minutes)
        publish_timestamp = int(publish_time.timestamp())
        vk.wall.post(
            owner_id=group['id'],
            message=text,
            attachments=attachment,
            publish_date=publish_timestamp,
            from_group=1
        )
        return True
    except Exception as e:
        print(f"   ❌ Ошибка создания поста в группе {group['id']}: {e}", flush=True)
        return False

# ===== Основная логика =====
def run_bot():
    try:
        vk_session = vk_api.VkApi(token=TOKEN)
        longpoll = VkLongPoll(vk_session)
        print("✅ Бот-менеджер запущен и ждёт команды...", flush=True)

        for event in longpoll.listen():
            if event.type == VkEventType.MESSAGE_NEW and event.to_me:
                msg_raw = event.text.strip()
                # Заменяем HTML-сущности на нормальные символы
                msg = msg_raw.replace('&quot;', '"').replace('&amp;', '&')
                user_id = event.user_id
                print(f"📩 Получено (raw): {msg_raw}", flush=True)
                print(f"📩 Обработано: {msg}", flush=True)

                if msg.lower() == 'привет':
                    vk_session.method('messages.send', {
                        'user_id': user_id,
                        'message': 'Привет! Я бот-менеджер.\nКоманда: пост в "Название" на тему "..." [с фото/видео ссылка] через X минут',
                        'random_id': 0
                    })
                    continue

                elif msg.lower().startswith('пост в'):
                    # Парсим команду
                    match_group = re.search(r'пост в "([^"]+)"', msg, re.I)
                    match_topic = re.search(r'на тему "([^"]+)"', msg, re.I)
                    match_media = re.search(r'(?:с фото|с видео)\s+(https?://[^\s]+)', msg, re.I)
                    match_time = re.search(r'через\s+(\d+)\s+минут', msg, re.I)

                    if not match_group or not match_topic or not match_time:
                        vk_session.method('messages.send', {
                            'user_id': user_id,
                            'message': '❌ Формат: пост в "Название" на тему "..." [с фото/видео ссылка] через X минут',
                            'random_id': 0
                        })
                        continue

                    group_name = match_group.group(1).strip().lower()
                    topic = match_topic.group(1).strip()
                    minutes = int(match_time.group(1))

                    group = None
                    for g in groups:
                        if g['name'] == group_name:
                            group = g
                            break
                    if not group:
                        vk_session.method('messages.send', {
                            'user_id': user_id,
                            'message': f'❌ Группа "{group_name}" не найдена. Доступны: ' + ', '.join([g['name'] for g in groups]),
                            'random_id': 0
                        })
                        continue

                    vk_session.method('messages.send', {
                        'user_id': user_id,
                        'message': '⏳ Генерирую текст и загружаю медиа... (до 30 сек)',
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

                    attachment = None
                    if match_media:
                        media_url = match_media.group(1)
                        print(f"   📥 Скачивание медиа: {media_url}", flush=True)
                        filepath = download_media(media_url)
                        if filepath:
                            if filepath.endswith(('.jpg', '.jpeg', '.png', '.gif')):
                                attachment = upload_photo(vk_api.VkApi(token=group['token']).get_api(), group['id'], filepath)
                            elif filepath.endswith(('.mp4', '.avi', '.mov', '.mkv', '.webm')):
                                attachment = upload_video(vk_api.VkApi(token=group['token']).get_api(), group['id'], filepath)
                            if attachment:
                                print(f"   ✅ Медиа загружено: {attachment}", flush=True)
                            else:
                                print(f"   ⚠️ Не удалось загрузить медиа", flush=True)
                        else:
                            print(f"   ⚠️ Не удалось скачать медиа", flush=True)

                    success = create_post(group, text, minutes, attachment)
                    if success:
                        vk_session.method('messages.send', {
                            'user_id': user_id,
                            'message': f'✅ Пост для группы "{group_name}" создан. Опубликуется через {minutes} мин.',
                            'random_id': 0
                        })
                    else:
                        vk_session.method('messages.send', {
                            'user_id': user_id,
                            'message': f'❌ Ошибка создания поста в группе "{group_name}".',
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
        print("❌ КРИТИЧЕСКАЯ ОШИБКА:", flush=True)
        traceback.print_exc(file=sys.stdout)

if __name__ == '__main__':
    print("🔹 Запуск...", flush=True)
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    time.sleep(3)
    run_health()