from __future__ import annotations

import json
import os
import random
import sqlite3
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter

RANKS = ["6", "7", "8", "9", "10", "J", "Q", "K", "A"]
SUITS = [("S", "♠"), ("H", "♥"), ("D", "♦"), ("C", "♣")]
ALL_CARDS = [rank + code for rank in RANKS for code, _ in SUITS]


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

    def send_rich(self, chat_id: int, view: dict):
        return self.call("sendRichMessage", {"chat_id": chat_id, "rich_message": view})

    def edit_rich(self, chat_id: int, message_id: int, view: dict):
        return self.call("editMessageText", {
            "chat_id": chat_id, "message_id": message_id, "rich_message": view
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
        self.db.commit()

    def save(self, game: dict):
        self.db.execute(
            "INSERT OR REPLACE INTO games VALUES(?,?,?)",
            (game["id"], game["uid"], json.dumps(game)),
        )
        self.db.commit()

    def get(self, game_id: str):
        row = self.db.execute("SELECT state FROM games WHERE id=?", (game_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def record(self, user_id: int, won: bool):
        self.db.execute("INSERT OR IGNORE INTO stats(user_id) VALUES(?)", (user_id,))
        self.db.execute(
            "UPDATE stats SET wins=wins+?,losses=losses+?,"
            "streak=CASE WHEN ? THEN streak+1 ELSE 0 END,"
            "best=MAX(best,CASE WHEN ? THEN streak+1 ELSE best END) WHERE user_id=?",
            (int(won), int(not won), int(won), int(won), user_id),
        )
        self.db.commit()

    def stats(self, user_id: int):
        return self.db.execute(
            "SELECT wins,losses,streak,best FROM stats WHERE user_id=?", (user_id,)
        ).fetchone() or (0, 0, 0, 0)


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


def new_game(user_id: int) -> dict:
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
        "done": False,
        "started": int(time.time()),
    }
    for _ in range(6):
        game["player"].append(game["deck"].pop())
        game["dog"].append(game["deck"].pop())
    game["player_books"] += take_books(game["player"])
    game["dog_books"] += take_books(game["dog"])
    return game


def dog_turn(game: dict):
    refill(game)
    if not game["dog"] or not game["player"]:
        return
    wanted = rank(random.choice(game["dog"]))
    received = [card for card in game["player"] if rank(card) == wanted]
    if received:
        game["player"] = [card for card in game["player"] if rank(card) != wanted]
        game["dog"] += received
        game["message"] += f"\n🐕 Пёс попросил {wanted} и забрал {len(received)}."
        game["mood"] = "😏"
    else:
        if game["deck"]:
            game["dog"].append(game["deck"].pop())
        game["message"] += f"\n🐕 Пёс попросил {wanted}, но вытянул карту."
        game["mood"] = "🐶"
    game["dog_books"] += take_books(game["dog"])
    refill(game)


def finish_if_needed(game: dict, store: Store):
    if len(game["player_books"]) + len(game["dog_books"]) == 9 or (
        not game["deck"] and (not game["player"] or not game["dog"])
    ):
        won = len(game["player_books"]) > len(game["dog_books"])
        game["done"] = True
        game["mood"] = "😡" if won else "🥳"
        game["message"] = (
            f"{'Вы победили!' if won else 'Карточный Пёс победил!'} "
            f"Счёт {len(game['player_books'])}:{len(game['dog_books'])}."
        )
        store.record(game["uid"], won)


def button(text: str, data: str, style: str | None = None) -> dict:
    result = {"text": text, "callback_data": data}
    if style:
        result["style"] = style
    return result


def card_label(card: str) -> str:
    code = card[-1]
    symbol = dict(SUITS)[code]
    return rank(card) + symbol


def game_view(game: dict) -> dict:
    cells = []
    player = set(game["player"])
    player_books = set(game["player_books"])
    dog_books = set(game["dog_books"])
    for suit_code, suit_symbol in SUITS:
        row = []
        for value in RANKS:
            card = value + suit_code
            if card in player:
                text = card_label(card)
                style = "primary" if suit_code in {"H", "D"} else "success"
                data = f"ask:{game['id']}:{value}"
            elif value in player_books:
                text, style, data = "✓" + value + suit_symbol, "success", "noop"
            elif value in dog_books:
                text, style, data = "🐾", None, "noop"
            else:
                text, style, data = "🂠", None, "noop"
            row.append({
                "text": {"type": "button", "button": button(text, data, style)},
                "align": "center", "valign": "middle",
            })
        cells.append(row)
    elapsed = max(0, int(time.time()) - game["started"])
    blocks = [
        {"type": "heading", "size": 2, "text": f"{game['mood']} Карточный Пёс"},
        {"type": "paragraph", "text": game["message"]},
        {"type": "paragraph", "text": (
            f"Ваши карты: {len(game['player'])} · Наборы: {len(game['player_books'])}\n"
            f"Карты пса: {len(game['dog'])} · Наборы: {len(game['dog_books'])}\n"
            f"Колода: {len(game['deck'])} · Время: {elapsed // 60}:{elapsed % 60:02d}"
        )},
        {"type": "table", "cells": cells, "is_bordered": True, "is_compact": True},
        {"type": "paragraph", "text": "Открытая карта — ваша. 🂠 — скрытая. ✓ — собранный набор. 🐾 — набор пса."},
        {"type": "buttons", "align": "center", "buttons": [
            button("Новая игра", "new", "primary"),
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
    api.call("setMyCommands", {"commands": [
        {"command": "start", "description": "Играть с Карточным Псом"},
        {"command": "creator", "description": "Создатель бота"},
    ]})
    offset = 0
    while True:
        try:
            updates = api.call("getUpdates", {
                "offset": offset, "timeout": 30,
                "allowed_updates": ["message", "callback_query"],
            }, 40)
            for update in updates:
                offset = update["update_id"] + 1
                if "message" in update:
                    message = update["message"]
                    text = message.get("text", "").split("@", 1)[0]
                    if text == "/creator":
                        api.call("sendMessage", {
                            "chat_id": message["chat"]["id"],
                            "text": "Создатель бота — @eternall_dog\nПо всем вопросам и предложениям пишите ему.",
                        })
                    elif text == "/start":
                        game = new_game(message["from"]["id"])
                        store.save(game)
                        api.send_rich(message["chat"]["id"], game_view(game))
                elif "callback_query" in update:
                    query = update["callback_query"]
                    data = query["data"]
                    chat_id = query["message"]["chat"]["id"]
                    message_id = query["message"]["message_id"]
                    if data == "noop":
                        api.answer(query["id"], "Эта карта пока скрыта.")
                        continue
                    if data == "rules":
                        api.answer(query["id"], "Нажмите свой ранг. Соберите больше наборов из четырёх карт.", True)
                        continue
                    if data == "stats":
                        wins, losses, streak, best = store.stats(query["from"]["id"])
                        api.answer(query["id"], f"Победы {wins} · Поражения {losses} · Серия {streak} · Рекорд {best}", True)
                        continue
                    if data == "new":
                        game = new_game(query["from"]["id"])
                    else:
                        _, game_id, wanted = data.split(":")
                        game = store.get(game_id)
                        if not game or game["uid"] != query["from"]["id"] or game["done"]:
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
                        else:
                            drawn = game["deck"].pop() if game["deck"] else None
                            if drawn:
                                game["player"].append(drawn)
                            game["message"] = f"У пса нет {wanted}. Вы вытянули карту."
                            game["mood"] = "😄"
                        game["player_books"] += take_books(game["player"])
                        dog_turn(game)
                    finish_if_needed(game, store)
                    store.save(game)
                    api.answer(query["id"])
                    api.edit_rich(chat_id, message_id, game_view(game))
        except Exception as error:
            print(type(error).__name__, error)
            time.sleep(3)


if __name__ == "__main__":
    main()
