import sys
import os
import requests
import json
import urllib.parse
import time
import traceback
from datetime import datetime

# ===== ПРИНУДИТЕЛЬНЫЙ ВЫВОД ЛОГОВ =====
sys.stdout.reconfigure(line_buffering=True)

def log(msg):
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {msg}", flush=True)

log("🚀 Запуск тестового бота (без планировщика)")

# ===== ПРОВЕРКА ПЕРЕМЕННЫХ =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
AGNES_API_KEY = os.getenv("AGNES_API_KEY")
GIGACHAT_API_KEY = os.getenv("GIGACHAT_API_KEY")

if not BOT_TOKEN:
    log("❌ BOT_TOKEN не задан")
    sys.exit(1)
if not AGNES_API_KEY:
    log("⚠️ AGNES_API_KEY не задан, картинки через Pollinations")
    log("✅ Основные переменные загружены")

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

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
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
            raise Exception(json_resp["error"]["error_msg"])
        return json_resp["response"]
    try:
        return retry_call(_do, max_retries=retries, delay=2, backoff=2)
    except Exception as e:
        log(f"   ❌ Ошибка VK API ({method}): {e}")
        return None

def post_to_vk(niche, image_bytes, text):
    log(f"📤 Публикация в {niche}")
    if niche not in VK_ACCOUNTS:
        return False, f"Ниша '{niche}' не найдена"
    vk_token = VK_ACCOUNTS[niche]["token"]
    group_id = VK_ACCOUNTS[niche]["group_id"]

    if image_bytes is None:
        log("   Публикация без фото (только текст)")
        result = vk_api_request("wall.post", {"owner_id": group_id, "message": text, "from_group": 1}, token=vk_token, retries=3)
        if result is None:
            return False, "Ошибка публикации текста"
        log(f"✅ Пост опубликован (без фото) в группе {group_id}, ID: {result['post_id']}")
        return True, None

    try:
        # Получение upload_url
        upload_resp = vk_api_request("photos.getWallUploadServer", {"group_id": abs(group_id)}, token=vk_token, retries=3)
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
        save_resp = vk_api_request("photos.saveWallPhoto", save_params, token=vk_token, retries=3)
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
        post_resp = vk_api_request("wall.post", post_params, token=vk_token, retries=3)
        if post_resp is None:
            return False, "Ошибка публикации поста"
        log(f"✅ Пост опубликован в группе {group_id}, ID: {post_resp['post_id']}")
        return True, None
    except Exception as e:
        log(f"   Исключение в post_to_vk: {e}")
        traceback.print_exc(file=sys.stdout)
        return False, f"Исключение: {str(e)}"

# ===== ТЕСТОВАЯ ПУБЛИКАЦИЯ (прямо сейчас) =====
if __name__ == "__main__":
    log("🧪 Запуск тестовой публикации в группу 'ai'")

    # Генерируем текст
    text = generate_post_text("ai", "Тестовый пост для проверки бота")
    if not text:
        log("❌ Текст не получен, завершаем")
        sys.exit(1)

    # Генерируем картинку
    image_url = generate_image("ai", "Тестовый пост")
    image_bytes = None
    if image_url:
        log(f"✅ URL картинки: {image_url[:60]}...")
        image_bytes = download_image(image_url)
        if image_bytes:
            log(f"✅ Картинка скачана, размер {len(image_bytes)} байт")
        else:
            log("⚠️ Картинка не скачалась, публикуем без фото")
    else:
        log("⚠️ Картинка не сгенерирована, публикуем без фото")

    # Публикуем
    success, error = post_to_vk("ai", image_bytes, text)
    if success:
        log("🎉 УСПЕХ! Пост опубликован.")
    else:
        log(f"❌ ОШИБКА: {error}")

    log("🏁 Тест завершён.")