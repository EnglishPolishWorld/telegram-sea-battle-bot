import json
import os
import time
import urllib.error
import urllib.request

TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_NAME = "Собачья Душа"
POLL_TIMEOUT = 30

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

API = f"https://api.telegram.org/bot{TOKEN}/"
pending_reason = {}


def call(method, data=None):
    request = urllib.request.Request(
        API + method,
        json.dumps(data or {}, ensure_ascii=False).encode("utf-8"),
        {"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=POLL_TIMEOUT + 10) as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read().decode(errors="replace")) from exc
    if not result.get("ok"):
        raise RuntimeError(result)
    return result["result"]


def ban_keyboard(username):
    return {"inline_keyboard": [[{"text": "🚫 Бан", "callback_data": f"ban:{username}"}]]}


def handle_update(update):
    callback = update.get("callback_query")
    if callback:
        data = callback.get("data", "")
        if not data.startswith("ban:"):
            return
        username = data[4:]
        chat_id = callback.get("message", {}).get("chat", {}).get("id")
        if not chat_id:
            return
        pending_reason[chat_id] = username
        call("answerCallbackQuery", {"callback_query_id": callback["id"]})
        call("sendMessage", {"chat_id": chat_id, "text": f"Введите причину для {username}:"})
        return

    message = update.get("message")
    if not message or "text" not in message:
        return

    chat_id = message["chat"]["id"]
    text = message["text"].strip()

    if text == "/start":
        call("sendMessage", {"chat_id": chat_id, "text": "Введите @username пользователя."})
        return

    if chat_id in pending_reason:
        username = pending_reason.pop(chat_id)
        call("sendMessage", {
            "chat_id": chat_id,
            "text": (
                f"🚫 Пользователь {username} был забанен.\n"
                f"👮 Администратор: {ADMIN_NAME}\n"
                f"📝 Причина: {text}"
            ),
        })
        return

    if text.startswith("@") and " " not in text and len(text) > 1:
        call("sendMessage", {
            "chat_id": chat_id,
            "text": f"Пользователь: {text}\nВыберите действие:",
            "reply_markup": ban_keyboard(text),
        })


def main():
    offset = None
    while True:
        try:
            updates = call("getUpdates", {
                "offset": offset,
                "timeout": POLL_TIMEOUT,
                "allowed_updates": ["message", "callback_query"],
            })
            for update in updates:
                offset = update["update_id"] + 1
                try:
                    handle_update(update)
                except Exception as exc:
                    print("update error:", repr(exc))
        except Exception as exc:
            print("poll error:", repr(exc))
            time.sleep(3)


if __name__ == "__main__":
    main()
