from __future__ import annotations

import base64
import json
import os
import random
import sqlite3
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

RANKS = ["6", "7", "8", "9", "10", "J", "Q", "K", "A"]
SUITS = [("S", "♠"), ("H", "♥"), ("D", "♦"), ("C", "♣")]
ALL_CARDS = [rank + code for rank in RANKS for code, _ in SUITS]
CARD_BASES = {"S": 0x1F0A0, "H": 0x1F0B0, "D": 0x1F0C0, "C": 0x1F0D0}
CARD_VALUES = {"A": 1, "6": 6, "7": 7, "8": 8, "9": 9, "10": 10, "J": 11, "Q": 13, "K": 14}
RANK_NAMES = {"A": "Туз", "K": "Король", "Q": "Дама", "J": "Валет"}
ASSET_ROOT = os.path.join(os.path.dirname(__file__), "assets")
ASSETS = os.path.join(ASSET_ROOT, "dog")
DIFFICULTIES = {
    "easy": {"name": "Лёгкая", "reward": 5, "icon": "🌱"},
    "medium": {"name": "Средняя", "reward": 10, "icon": "🎯"},
    "hard": {"name": "Сложная", "reward": 15, "icon": "🔥"},
}
ITEMS = {
    "scent": {
        "name": "Нюх",
        "icon": "👃",
        "price": 10,
        "description": "Показывает один ранг, который есть у пса.",
    },
    "double_draw": {
        "name": "Двойной добор",
        "icon": "🃏",
        "price": 15,
        "description": "Берёт две карты из колоды без хода пса.",
    },
    "shield": {
        "name": "Защита",
        "icon": "🛡️",
        "price": 20,
        "description": "Отменяет следующий ход пса.",
    },
}


class API:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}/"

    def call(self, method: str, payload: dict | None = None, timeout: int = 45):
        request = urllib.request.Request(
            self.base + method,
            json.dumps(payload or {}).encode(),
            {"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read())
        except urllib.error.HTTPError as error:
            raise RuntimeError(error.read().decode(errors="replace")) from error
        if not result.get("ok"):
            raise RuntimeError(result)
        return result["result"]

    def multipart(self, method: str, payload: dict, image: bytes):
        boundary = "----carddogboundary"
        body = bytearray()
        for name, value in payload.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"dog_scene\"; filename=\"scene.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".encode())
        body.extend(image)
        body.extend(f"\r\n--{boundary}--\r\n".encode())
        request = urllib.request.Request(
            self.base + method, bytes(body),
            {"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.loads(response.read())
        if not result.get("ok"):
            raise RuntimeError(result)
        return result["result"]

    def send_rich(self, chat_id: int, view: dict, image: bytes | None = None):
        payload = {"chat_id": chat_id, "rich_message": view}
        return self.multipart("sendRichMessage", payload, image) if image else self.call("sendRichMessage", payload)

    def edit_rich(self, chat_id: int, message_id: int, view: dict, inline_id: str | None = None, image: bytes | None = None):
        data = {"rich_message": view}
        if inline_id:
            data["inline_message_id"] = inline_id
        else:
            data.update({"chat_id": chat_id, "message_id": message_id})
        return self.multipart("editMessageText", data, image) if image else self.call("editMessageText", data)

    def answer_inline(self, query_id: str, view: dict):
        return self.call("answerInlineQuery", {
            "inline_query_id": query_id, "cache_time": 0, "is_personal": True,
            "results": [{"type": "article", "id": uuid.uuid4().hex[:12],
                "title": "Играть в Сундучки с Псом",
                "description": "Сундучки — 7 карт в руке",
                "input_message_content": {"rich_message": view}}],
        })

    def answer(self, query_id: str, text: str = "", alert: bool = False):
        data = {"callback_query_id": query_id, "show_alert": alert}
        if text:
            data["text"] = text
        return self.call("answerCallbackQuery", data)


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS games(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,state TEXT NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS stats(user_id INTEGER PRIMARY KEY,wins INTEGER DEFAULT 0,"
            "losses INTEGER DEFAULT 0,streak INTEGER DEFAULT 0,best INTEGER DEFAULT 0)"
        )
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(stats)")}
        if "coins" not in columns:
            self.db.execute("ALTER TABLE stats ADD COLUMN coins INTEGER DEFAULT 0")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS inventory("
            "user_id INTEGER NOT NULL,item TEXT NOT NULL,quantity INTEGER DEFAULT 0,"
            "PRIMARY KEY(user_id,item))"
        )
        self.db.commit()

    def ensure_user(self, user_id: int):
        self.db.execute("INSERT OR IGNORE INTO stats(user_id) VALUES(?)", (user_id,))

    def save(self, game: dict):
        self.db.execute(
            "INSERT OR REPLACE INTO games VALUES(?,?,?)",
            (game["id"], game["uid"], json.dumps(game)),
        )
        self.db.commit()

    def get(self, game_id: str):
        row = self.db.execute("SELECT state FROM games WHERE id=?", (game_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def record(self, user_id: int, won: bool, reward: int = 0):
        self.ensure_user(user_id)
        self.db.execute(
            "UPDATE stats SET wins=wins+?,losses=losses+?,"
            "streak=CASE WHEN ? THEN streak+1 ELSE 0 END,"
            "best=MAX(best,CASE WHEN ? THEN streak+1 ELSE best END),"
            "coins=coins+? WHERE user_id=?",
            (int(won), int(not won), int(won), int(won), reward, user_id),
        )
        self.db.commit()

    def stats(self, user_id: int):
        return self.db.execute(
            "SELECT wins,losses,streak,best,coins FROM stats WHERE user_id=?", (user_id,)
        ).fetchone() or (0, 0, 0, 0, 0)

    def inventory(self, user_id: int) -> dict[str, int]:
        owned = {key: 0 for key in ITEMS}
        owned.update(dict(self.db.execute(
            "SELECT item,quantity FROM inventory WHERE user_id=?", (user_id,)
        ).fetchall()))
        return owned

    def buy(self, user_id: int, item: str) -> tuple[bool, str]:
        product = ITEMS.get(item)
        if not product:
            return False, "Товар не найден."
        self.ensure_user(user_id)
        coins = self.stats(user_id)[4]
        if coins < product["price"]:
            return False, f"Не хватает {product['price'] - coins} монет."
        self.db.execute(
            "UPDATE stats SET coins=coins-? WHERE user_id=?",
            (product["price"], user_id),
        )
        self.db.execute(
            "INSERT INTO inventory(user_id,item,quantity) VALUES(?,?,1) "
            "ON CONFLICT(user_id,item) DO UPDATE SET quantity=quantity+1",
            (user_id, item),
        )
        self.db.commit()
        return True, f"Куплено: {product['icon']} {product['name']}."

    def consume(self, user_id: int, item: str) -> bool:
        cursor = self.db.execute(
            "UPDATE inventory SET quantity=quantity-1 "
            "WHERE user_id=? AND item=? AND quantity>0",
            (user_id, item),
        )
        self.db.commit()
        return cursor.rowcount == 1

    def leaders(self):
        return self.db.execute(
            "SELECT user_id,wins,best,coins FROM stats ORDER BY wins DESC,best DESC LIMIT 10"
        ).fetchall()


def rank(card: str) -> str:
    return card[:-1]


def take_books(hand: list[str]) -> list[str]:
    counts = Counter(rank(card) for card in hand)
    made = [value for value, count in counts.items() if count == 4]
    hand[:] = [card for card in hand if rank(card) not in made]
    return made


def refill(game: dict):
    for key in ("player", "dog"):
        if not game[key] and game["deck"]:
            for _ in range(min(6, len(game["deck"]))):
                game[key].append(game["deck"].pop())


def new_game(user_id: int, difficulty: str = "easy") -> dict:
    if difficulty not in DIFFICULTIES:
        difficulty = "easy"
    deck = ALL_CARDS.copy()
    random.shuffle(deck)
    game = {
        "id": uuid.uuid4().hex[:10],
        "uid": user_id,
        "deck": deck,
        "player": [],
        "dog": [],
        "player_books": [],
        "dog_books": [],
        "message": "Ваш ход: нажмите любую открытую карту.",
        "mood": "🐶",
        "pose": 0,
        "difficulty": difficulty,
        "shielded": False,
        "done": False,
        "started": int(time.time()),
    }
    for _ in range(7):
        game["player"].append(game["deck"].pop())
        game["dog"].append(game["deck"].pop())
    game["player_books"] += take_books(game["player"])
    game["dog_books"] += take_books(game["dog"])
    return game


def dog_turn(game: dict):
    refill(game)
    if not game["dog"] or not game["player"]:
        return
    counts = Counter(rank(card) for card in game["dog"])
    difficulty = game.get("difficulty", "easy")
    if difficulty == "hard":
        player_ranks = {rank(card) for card in game["player"]}
        known_hits = [value for value in counts if value in player_ranks]
        wanted = max(known_hits, key=counts.get) if known_hits else max(counts, key=counts.get)
    elif difficulty == "medium":
        best_count = max(counts.values())
        best_ranks = [value for value, amount in counts.items() if amount == best_count]
        wanted = random.choice(best_ranks)
    else:
        wanted = rank(random.choice(game["dog"]))
    received = [card for card in game["player"] if rank(card) == wanted]
    if received:
        game["player"] = [card for card in game["player"] if rank(card) != wanted]
        game["dog"] += received
        game["message"] += f"\n🐕 Пёс попросил {wanted} и забрал {len(received)}."
        game["mood"] = "😏"
        game["pose"] = 1
    else:
        if game["deck"]:
            game["dog"].append(game["deck"].pop())
        game["message"] += f"\n🐕 Пёс попросил {wanted}, но вытянул карту."
        game["mood"] = "🐶"
        game["pose"] = 2
    game["dog_books"] += take_books(game["dog"])
    refill(game)


def finish_if_needed(game: dict, store: Store):
    if game.get("done"):
        return
    if len(game["player_books"]) + len(game["dog_books"]) == 9 or (
        not game["deck"] and (not game["player"] or not game["dog"])
    ):
        won = len(game["player_books"]) > len(game["dog_books"])
        game["done"] = True
        game["mood"] = "😡" if won else "🥳"
        game["pose"] = 6 if won else 7
        reward = DIFFICULTIES.get(game.get("difficulty", "easy"), DIFFICULTIES["easy"])["reward"] if won else 0
        game["message"] = (
            f"{'Вы победили!' if won else 'Карточный Пёс победил!'} "
            f"Счёт {len(game['player_books'])}:{len(game['dog_books'])}."
            + (f" Награда: +{reward} монет 🪙" if reward else "")
        )
        store.record(game["uid"], won, reward)


def button(text: str, data: str, style: str | None = None) -> dict:
    result = {"text": text, "callback_data": data}
    if style:
        result["style"] = style
    return result


def card_label(card: str) -> str:
    return chr(CARD_BASES[card[-1]] + CARD_VALUES[rank(card)])


def card_button_label(card: str) -> str:
    value = rank(card)
    return f"{card_label(card)} {RANK_NAMES.get(value, value)} {dict(SUITS)[card[-1]]}"


def difficulty_view() -> dict:
    return {"blocks": [
        {"type": "heading", "size": 2, "text": "🐶 Сундучки с Псом"},
        {"type": "paragraph", "text": (
            "Выберите сложность. Монеты выдаются только за победу:\n"
            "🌱 Лёгкая — 5 🪙\n🎯 Средняя — 10 🪙\n🔥 Сложная — 15 🪙"
        )},
        {"type": "buttons", "align": "center", "buttons": [
            button("🌱 Лёгкая · 5", "difficulty:easy", "success"),
            button("🎯 Средняя · 10", "difficulty:medium", "primary"),
            button("🔥 Сложная · 15", "difficulty:hard"),
        ]},
        {"type": "buttons", "align": "center", "buttons": [
            button("🛍 Магазин", "shop"),
            button("📊 Статистика", "stats"),
        ]},
    ]}


def shop_view(store: Store, user_id: int, game_id: str | None = None) -> dict:
    coins = store.stats(user_id)[4]
    owned = store.inventory(user_id)
    blocks = [
        {"type": "heading", "size": 2, "text": "🛍 Магазин расходников"},
        {"type": "paragraph", "text": f"Ваш баланс: {coins} 🪙"},
    ]
    for key, product in ITEMS.items():
        blocks.append({"type": "paragraph", "text": (
            f"{product['icon']} {product['name']} · {product['price']} 🪙\n"
            f"{product['description']}\nВ рюкзаке: {owned[key]}"
        )})
        blocks.append({"type": "buttons", "align": "left", "buttons": [
            button(f"🪙 {product['price']} · Купить", f"buy:{key}:{game_id or '-'}", "primary")
        ]})
    blocks.append({"type": "buttons", "align": "center", "buttons": [
        button("← К игре" if game_id else "← В меню", f"back:{game_id}" if game_id else "menu")
    ]})
    return {"blocks": blocks}


def load_asset(path: str) -> Image.Image:
    raw_path = path[:-4] if path.endswith(".b64") else path
    if os.path.exists(raw_path):
        return Image.open(raw_path).convert("RGBA")
    with open(path, encoding="ascii") as source:
        return Image.open(BytesIO(base64.b64decode(source.read()))).convert("RGBA")


def render_scene(game: dict) -> bytes:
    canvas = load_asset(os.path.join(ASSET_ROOT, "table.png.b64")).resize((1280, 720))
    dog = load_asset(os.path.join(ASSETS, f"{game.get('pose', 0)}.png.b64"))
    dog.thumbnail((330, 410), Image.Resampling.NEAREST)
    canvas.alpha_composite(dog, ((1280 - dog.width) // 2, 45))

    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    small = ImageFont.truetype(font_path, 22)
    visible = sorted(game["player"], key=lambda item: (RANKS.index(rank(item)), item[-1]))[:12]
    count = max(7, len(visible))
    asset_name = "hands_blank.png.b64" if count == 7 else f"fan_{count}.webp.b64"
    hands = load_asset(os.path.join(ASSET_ROOT, asset_name)).resize(
        (1280, 720), Image.Resampling.LANCZOS
    )
    layouts = {
        7: [(294, 340), (400, 312), (510, 292), (630, 285), (752, 294), (870, 317), (982, 350)],
        8: [(242, 288), (353, 242), (460, 220), (575, 219), (676, 211), (782, 217), (890, 238), (1012, 275)],
        9: [(197, 311), (281, 267), (388, 231), (496, 217), (618, 216), (719, 218), (828, 222), (946, 247), (1062, 294)],
        10: [(206, 284), (297, 245), (400, 220), (493, 200), (615, 193), (733, 197), (824, 209), (915, 228), (1014, 259), (1094, 307)],
        11: [(181, 319), (256, 269), (349, 238), (436, 215), (518, 199), (637, 193), (753, 198), (838, 213), (921, 233), (1016, 265), (1090, 317)],
        12: [(190, 330), (285, 288), (383, 259), (465, 241), (551, 232), (642, 231), (730, 234), (810, 243), (892, 260), (979, 284), (1050, 315), (1114, 355)],
    }
    font_size = 42 if count == 7 else max(28, 43 - (count - 7) * 3)
    font = ImageFont.truetype(font_path, font_size)
    draw = ImageDraw.Draw(hands)
    for card, (x, y) in zip(visible, layouts[count]):
        value, suit = rank(card), dict(SUITS)[card[-1]]
        color = "#c51f32" if card[-1] in {"H", "D"} else "#17151a"
        draw.text((x, y), value, fill=color, font=font, anchor="mm",
                  stroke_width=1, stroke_fill="white")
        draw.text((x, y + font_size), suit, fill=color, font=font, anchor="mm")
    canvas.alpha_composite(hands)
    if len(game["player"]) > 12:
        scene_draw = ImageDraw.Draw(canvas)
        scene_draw.rounded_rectangle((1080, 565, 1245, 630), 12, fill="#6e1026", outline="#f0c36a", width=3)
        scene_draw.text((1162, 597), f"+{len(game['player'])-12} карт", fill="white", font=small, anchor="mm")
    output = BytesIO()
    canvas.convert("RGB").save(output, "JPEG", quality=88, optimize=True)
    return output.getvalue()


def game_view(game: dict, graphical: bool = True, inventory: dict[str, int] | None = None) -> dict:
    inventory = inventory or {key: 0 for key in ITEMS}
    dog_cells = [{
        "text": {"type": "button", "button": button("🂠", "noop")},
        "align": "center", "valign": "middle",
    } for _ in game["dog"]]
    if not dog_cells:
        dog_cells = [{"text": {"type": "button", "button": button("—", "noop")},
                      "align": "center", "valign": "middle"}]
    player_cells = []
    for card in sorted(game["player"], key=lambda item: (RANKS.index(rank(item)), item[-1])):
        style = "primary" if card[-1] in {"H", "D"} else "success"
        player_cells.append({
            "text": {"type": "button", "button": button(
                card_button_label(card), f"ask:{game['id']}:{rank(card)}", style
            )},
            "align": "center", "valign": "middle",
        })
    if not player_cells:
        player_cells = [{"text": {"type": "button", "button": button("—", "noop")},
                         "align": "center", "valign": "middle"}]
    elapsed = max(0, int(time.time()) - game["started"])
    blocks = []
    if graphical:
        blocks.append({
            "type": "photo",
            "photo": {"type": "photo", "media": "attach://dog_scene"},
        })
    difficulty = DIFFICULTIES.get(game.get("difficulty", "easy"), DIFFICULTIES["easy"])
    blocks += [
        {"type": "heading", "size": 2, "text": f"{game['mood']} Сундучки с Псом"},
        {"type": "paragraph", "text": game["message"]},
        {"type": "paragraph", "text": (
            f"{difficulty['icon']} {difficulty['name']} · награда {difficulty['reward']} 🪙"
            + ("\n🛡️ Следующий ход пса заблокирован." if game.get("shielded") else "")
        )},
        {"type": "paragraph", "text": f"Карты пса · {len(game['dog'])} шт."},
        {"type": "table", "cells": [dog_cells[i:i+7] for i in range(0, len(dog_cells), 7)] or [[]],
         "is_bordered": True, "is_compact": True},
        {"type": "paragraph", "text": (
            f"🂠 Колода: {len(game['deck'])}\n"
            f"📚 Ваши наборы: {' '.join(game['player_books']) or '—'}\n"
            f"🐾 Наборы пса: {' '.join(game['dog_books']) or '—'}\n"
            f"⏱ {elapsed // 60}:{elapsed % 60:02d}"
        )},
        {"type": "paragraph", "text": f"Ваши карты · {len(game['player'])} шт. Нажмите карту, чтобы спросить её ранг."},
        {"type": "table", "cells": [player_cells[i:i+6] for i in range(0, len(player_cells), 6)] or [[]],
         "is_bordered": True, "is_compact": True},
        {"type": "paragraph", "text": "🎒 Расходники"},
        {"type": "buttons", "align": "center", "buttons": [
            button(f"👃 Нюх ×{inventory['scent']}", f"use:{game['id']}:scent"),
            button(f"🃏 Добор ×{inventory['double_draw']}", f"use:{game['id']}:double_draw"),
            button(f"🛡️ Защита ×{inventory['shield']}", f"use:{game['id']}:shield"),
        ]},
        {"type": "buttons", "align": "center", "buttons": [
            button("Новая игра", "new", "primary"),
            button("Магазин", f"shop:{game['id']}"),
            button("Статистика", "stats"),
            button("Правила", "rules"),
        ]},
    ]
    return {"blocks": blocks}


def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN required")
    api = API(token)
    store = Store(os.getenv("DATABASE_PATH", "cards.sqlite3"))
    commands = [
        {"command": "start", "description": "Играть в Сундучки с Псом"},
        {"command": "new", "description": "Новая игра"},
        {"command": "group", "description": "Запустить игру в группе"},
        {"command": "shop", "description": "Магазин расходников"},
        {"command": "stats", "description": "Моя статистика"},
        {"command": "top", "description": "Рейтинг игроков"},
        {"command": "rating", "description": "Рейтинг игроков"},
        {"command": "creator", "description": "Создатель бота"},
    ]
    api.call("setMyCommands", {"commands": commands})
    api.call("setMyCommands", {"commands": commands, "scope": {"type": "all_group_chats"}})
    offset = 0
    while True:
        try:
            updates = api.call("getUpdates", {
                "offset": offset, "timeout": 30,
                "allowed_updates": ["message", "callback_query", "inline_query"],
            }, 40)
            for update in updates:
                offset = update["update_id"] + 1
                if "inline_query" in update:
                    inline = update["inline_query"]
                    api.answer_inline(inline["id"], difficulty_view())
                elif "message" in update:
                    message = update["message"]
                    text = message.get("text", "").split("@", 1)[0]
                    if text == "/creator":
                        api.call("sendMessage", {
                            "chat_id": message["chat"]["id"],
                            "text": "Создатель бота — @eternall_dog\nПо всем вопросам и предложениям пишите ему.",
                        })
                    elif text == "/stats":
                        wins, losses, streak, best, coins = store.stats(message["from"]["id"])
                        api.call("sendMessage", {"chat_id": message["chat"]["id"],
                            "text": f"Победы: {wins}\nПоражения: {losses}\nСерия: {streak}\nРекорд: {best}\nМонеты: {coins} 🪙"})
                    elif text == "/shop":
                        api.send_rich(message["chat"]["id"], shop_view(store, message["from"]["id"]))
                    elif text in {"/top", "/rating"}:
                        rows = store.leaders()
                        listing = "\n".join(
                            f"{index}. Игрок {uid} — {wins} побед · {coins} 🪙"
                            for index, (uid, wins, _, coins) in enumerate(rows, 1)
                        ) or "Пока результатов нет."
                        api.call("sendMessage", {"chat_id": message["chat"]["id"], "text": "🏆 Рейтинг\n" + listing})
                    elif text in {"/start", "/new", "/group"}:
                        api.send_rich(message["chat"]["id"], difficulty_view())
                elif "callback_query" in update:
                    query = update["callback_query"]
                    data = query["data"]
                    message = query.get("message")
                    inline_id = query.get("inline_message_id")
                    chat_id = message["chat"]["id"] if message else 0
                    message_id = message["message_id"] if message else 0
                    if data == "noop":
                        api.answer(query["id"], "Эта карта пока скрыта.")
                        continue
                    if data == "rules":
                        api.answer(query["id"], "Нажмите свой ранг. Соберите больше наборов из четырёх карт.", True)
                        continue
                    if data == "stats":
                        wins, losses, streak, best, coins = store.stats(query["from"]["id"])
                        api.answer(query["id"], f"Победы {wins} · Поражения {losses} · Серия {streak} · Рекорд {best} · {coins} 🪙", True)
                        continue
                    user_id = query["from"]["id"]
                    if data in {"new", "menu"}:
                        api.answer(query["id"])
                        api.edit_rich(chat_id, message_id, difficulty_view(), inline_id)
                        continue
                    if data == "shop" or data.startswith("shop:"):
                        game_id = data.partition(":")[2] or None
                        api.answer(query["id"])
                        api.edit_rich(chat_id, message_id, shop_view(store, user_id, game_id), inline_id)
                        continue
                    if data.startswith("buy:"):
                        _, item, game_id = data.split(":", 2)
                        bought, notice = store.buy(user_id, item)
                        game_id = None if game_id == "-" else game_id
                        api.answer(query["id"], notice, not bought)
                        api.edit_rich(chat_id, message_id, shop_view(store, user_id, game_id), inline_id)
                        continue
                    if data.startswith("back:"):
                        game = store.get(data.split(":", 1)[1])
                        if not game or game["uid"] != user_id:
                            api.answer(query["id"], "Партия не найдена.", True)
                            continue
                        api.answer(query["id"])
                        api.edit_rich(
                            chat_id, message_id,
                            game_view(game, not bool(inline_id), store.inventory(user_id)),
                            inline_id, None if inline_id else render_scene(game),
                        )
                        continue
                    if data.startswith("difficulty:"):
                        difficulty = data.split(":", 1)[1]
                        game = new_game(user_id, difficulty)
                        store.save(game)
                        api.answer(query["id"])
                        api.edit_rich(
                            chat_id, message_id,
                            game_view(game, not bool(inline_id), store.inventory(user_id)),
                            inline_id, None if inline_id else render_scene(game),
                        )
                        continue
                    if data.startswith("use:"):
                        _, game_id, item = data.split(":", 2)
                        game = store.get(game_id)
                        if not game or game["uid"] != user_id or game["done"]:
                            api.answer(query["id"], "Эта партия недоступна.", True)
                            continue
                        if item == "scent" and not game["dog"]:
                            api.answer(query["id"], "У пса сейчас нет карт.", True)
                            continue
                        if item == "double_draw" and not game["deck"]:
                            api.answer(query["id"], "Колода уже пуста.", True)
                            continue
                        if item == "shield" and game.get("shielded"):
                            api.answer(query["id"], "Защита уже активна.", True)
                            continue
                        if item not in ITEMS or not store.consume(user_id, item):
                            api.answer(query["id"], "Такого расходника нет в рюкзаке.", True)
                            continue
                        if item == "scent":
                            revealed = rank(random.choice(game["dog"]))
                            game["message"] = f"👃 Нюх подсказывает: у пса есть ранг {revealed}."
                            game["pose"] = 3
                        elif item == "double_draw":
                            drawn = []
                            for _ in range(min(2, len(game["deck"]))):
                                drawn.append(game["deck"].pop())
                            game["player"] += drawn
                            game["player_books"] += take_books(game["player"])
                            game["message"] = f"🃏 Двойной добор: получено {len(drawn)} карты."
                        else:
                            game["shielded"] = True
                            game["message"] = "🛡️ Защита активна: следующий ход пса будет отменён."
                    elif data.startswith("ask:"):
                        _, game_id, wanted = data.split(":", 2)
                        game = store.get(game_id)
                        if not game or game["uid"] != user_id or game["done"]:
                            api.answer(query["id"], "Эта партия недоступна.", True)
                            continue
                        if wanted not in {rank(card) for card in game["player"]}:
                            api.answer(query["id"], "У вас нет такого ранга.")
                            continue
                        received = [card for card in game["dog"] if rank(card) == wanted]
                        if received:
                            game["dog"] = [card for card in game["dog"] if rank(card) != wanted]
                            game["player"] += received
                            game["message"] = f"Пёс отдал вам {len(received)} карт ранга {wanted}!"
                            game["mood"] = "😮"
                            game["pose"] = 5
                        else:
                            drawn = game["deck"].pop() if game["deck"] else None
                            if drawn:
                                game["player"].append(drawn)
                            game["message"] = f"У пса нет {wanted}. Вы вытянули карту."
                            game["mood"] = "😄"
                            game["pose"] = 4
                        game["player_books"] += take_books(game["player"])
                        if game.get("shielded"):
                            game["shielded"] = False
                            game["message"] += "\n🛡️ Защита отменила ход пса."
                        else:
                            dog_turn(game)
                    else:
                        api.answer(query["id"], "Неизвестная кнопка.", True)
                        continue
                    finish_if_needed(game, store)
                    store.save(game)
                    api.answer(query["id"])
                    api.edit_rich(
                        chat_id, message_id,
                        game_view(game, not bool(inline_id), store.inventory(user_id)), inline_id,
                        None if inline_id else render_scene(game),
                    )
        except Exception as error:
            print(type(error).__name__, error)
            time.sleep(3)


if __name__ == "__main__":
    main()
