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
pending = set()


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


def keyboard():
    return {"inline_keyboard": [[{"text": "🚫 Бан", "callback_data": "fake_ban"}]]}


def start(chat_id):
    call("sendMessage", {
        "chat_id": chat_id,
        "text": "Выберите действие:",
        "reply_markup": keyboard(),
    })


def handle_update(update):
    callback = update.get("callback_query")
    if callback:
        if callback.get("data") != "fake_ban":
            return
        chat = callback.get("message", {}).get("chat", {})
        chat_id = chat.get("id")
        if not chat_id:
            return
        pending.add(chat_id)
        call("answerCallbackQuery", {"callback_query_id": callback["id"]})
        call("sendMessage", {
            "chat_id": chat_id,
            "text": "Введите в одном сообщении:\n@username причина\n\nНапример: @username нарушение правил",
        })
        return

    message = update.get("message")
    if not message or "text" not in message:
        return

    chat_id = message["chat"]["id"]
    text = message["text"].strip()

    if text == "/start":
        start(chat_id)
        return

    if chat_id not in pending:
        return

    pending.discard(chat_id)
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[0].startswith("@"):
        call("sendMessage", {
            "chat_id": chat_id,
            "text": "Неверный формат. Нажмите «🚫 Бан» и введите: @username причина",
            "reply_markup": keyboard(),
        })
        return

    username, reason = parts
    call("sendMessage", {
        "chat_id": chat_id,
        "text": (
            f"🚫 Пользователь {username} был забанен.\n"
            f"👮 Администратор: {ADMIN_NAME}\n"
            f"📝 Причина: {reason}"
        ),
        "reply_markup": keyboard(),
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
