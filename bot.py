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


def handle_inline_query(inline_query):
    query_id = inline_query["id"]
    query = inline_query.get("query", "").strip()

    if not query:
        call("answerInlineQuery", {
            "inline_query_id": query_id,
            "results": [],
            "cache_time": 0,
            "is_personal": True,
        })
        return

    parts = query.split(maxsplit=1)
    username = parts[0].strip()
    reason = parts[1].strip() if len(parts) > 1 else ""

    if not username.startswith("@"):
        username = "@" + username

    if not reason:
        call("answerInlineQuery", {
            "inline_query_id": query_id,
            "results": [{
                "type": "article",
                "id": "need_reason",
                "title": "🚫 Бан пользователя",
                "description": "Добавьте причину после username",
                "input_message_content": {
                    "message_text": "Укажите username и причину: @username причина",
                },
            }],
            "cache_time": 0,
            "is_personal": True,
        })
        return

    text = (
        f"🚫 Пользователь {username} был забанен.\n"
        f"👮 Администратор: {ADMIN_NAME}\n"
        f"📝 Причина: {reason}"
    )

    result = {
        "type": "article",
        "id": "ban_result",
        "title": "🚫 Бан пользователя",
        "description": f"{username} — {reason}",
        "input_message_content": {
            "message_text": text,
        },
    }

    call("answerInlineQuery", {
        "inline_query_id": query_id,
        "results": [result],
        "cache_time": 0,
        "is_personal": True,
    })


def handle_update(update):
    if "inline_query" in update:
        handle_inline_query(update["inline_query"])
        return

    message = update.get("message")
    if not message or "text" not in message:
        return

    if message["text"].strip() == "/start":
        call("sendMessage", {
            "chat_id": message["chat"]["id"],
            "text": "Введите в группе: @Chess_sabaka_bot @username причина",
        })


def main():
    try:
        call("deleteWebhook", {"drop_pending_updates": False})
        me = call("getMe")
        print("Bot started:", me.get("username"), "inline:", me.get("supports_inline_queries"))
    except Exception as exc:
        print("startup error:", repr(exc))

    offset = None
    while True:
        try:
            updates = call("getUpdates", {
                "offset": offset,
                "timeout": POLL_TIMEOUT,
                "allowed_updates": ["message", "inline_query"],
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
