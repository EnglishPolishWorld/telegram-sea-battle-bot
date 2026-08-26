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
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont


ROOT = os.path.dirname(__file__)
AVATAR_B64 = os.path.join(ROOT, "assets", "naval", "avatar.jpg.b64")
GAME_MODES = {
    6: {"name": "Быстрый", "reward": 5, "ships": [3, 2, 2, 1, 1], "icon": "🌊"},
    8: {"name": "Морской", "reward": 10, "ships": [4, 3, 3, 2, 2, 1, 1], "icon": "⚓"},
    10: {"name": "Адмирал", "reward": 15, "ships": [4, 3, 3, 2, 2, 2, 1, 1, 1, 1], "icon": "🫡"},
}
PROFILE_VERSION = "sea-battle-v1"


class API:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}/"

    def call(self, method: str, payload: dict | None = None, timeout: int = 45):
        request = urllib.request.Request(
            self.base + method,
            json.dumps(payload or {}, ensure_ascii=False).encode(),
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

    def multipart(
        self,
        method: str,
        payload: dict,
        image: bytes,
        file_field: str = "battle_scene",
        filename: str = "scene.jpg",
        content_type: str = "image/jpeg",
    ):
        boundary = "----seabattledogboundary"
        body = bytearray()
        for name, value in payload.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            body.extend(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                f"{value}\r\n".encode()
            )
        body.extend(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
            f"filename=\"{filename}\"\r\nContent-Type: {content_type}\r\n\r\n".encode()
        )
        body.extend(image)
        body.extend(f"\r\n--{boundary}--\r\n".encode())
        request = urllib.request.Request(
            self.base + method,
            bytes(body),
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

    def edit_rich(
        self,
        chat_id: int,
        message_id: int,
        view: dict,
        inline_id: str | None = None,
        image: bytes | None = None,
    ):
        payload = {"rich_message": view}
        if inline_id:
            payload["inline_message_id"] = inline_id
        else:
            payload.update({"chat_id": chat_id, "message_id": message_id})
        return self.multipart("editMessageText", payload, image) if image else self.call("editMessageText", payload)

    @staticmethod
    def inline_result(view: dict) -> dict:
        return {
            "type": "article",
            "id": uuid.uuid4().hex[:12],
            "title": "Морской бой с Псом",
            "description": "Откройте огонь по флоту пса-капитана",
            "input_message_content": {"rich_message": view},
        }

    def answer_inline(self, query_id: str, view: dict):
        return self.call("answerInlineQuery", {
            "inline_query_id": query_id,
            "cache_time": 0,
            "is_personal": True,
            "results": [self.inline_result(view)],
        })

    def answer_guest(self, guest_query_id: str, view: dict):
        return self.call("answerGuestQuery", {
            "guest_query_id": guest_query_id,
            "result": self.inline_result(view),
        })

    def answer(self, query_id: str, text: str = "", alert: bool = False):
        payload = {"callback_query_id": query_id, "show_alert": alert}
        if text:
            payload["text"] = text
        return self.call("answerCallbackQuery", payload)

    def cache_photo(self, chat_id: int, image: bytes) -> str:
        message = self.multipart("sendPhoto", {
            "chat_id": chat_id,
            "disable_notification": True,
        }, image, "photo")
        file_id = message["photo"][-1]["file_id"]
        try:
            self.call("deleteMessage", {"chat_id": chat_id, "message_id": message["message_id"]})
        except Exception as error:
            print("cache cleanup:", type(error).__name__, error)
        return file_id


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS naval_games("
            "id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,state TEXT NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS naval_stats("
            "user_id INTEGER PRIMARY KEY,wins INTEGER DEFAULT 0,losses INTEGER DEFAULT 0,"
            "streak INTEGER DEFAULT 0,best INTEGER DEFAULT 0,coins INTEGER DEFAULT 0,"
            "shots INTEGER DEFAULT 0,hits INTEGER DEFAULT 0)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS naval_settings("
            "key TEXT PRIMARY KEY,value TEXT NOT NULL)"
        )
        self.db.commit()

    def save(self, game: dict):
        self.db.execute(
            "INSERT OR REPLACE INTO naval_games(id,user_id,state) VALUES(?,?,?)",
            (game["id"], game["uid"], json.dumps(game)),
        )
        self.db.commit()

    def get(self, game_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT state FROM naval_games WHERE id=?", (game_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def stats(self, user_id: int) -> tuple[int, int, int, int, int, int, int]:
        return self.db.execute(
            "SELECT wins,losses,streak,best,coins,shots,hits FROM naval_stats WHERE user_id=?",
            (user_id,),
        ).fetchone() or (0, 0, 0, 0, 0, 0, 0)

    def record(self, game: dict, won: bool):
        user_id = game["uid"]
        reward = GAME_MODES[game["size"]]["reward"] if won else 0
        shots = len(game["player_shots"])
        hits = sum(index in fleet_cells(game["enemy_ships"]) for index in game["player_shots"])
        self.db.execute("INSERT OR IGNORE INTO naval_stats(user_id) VALUES(?)", (user_id,))
        self.db.execute(
            "UPDATE naval_stats SET wins=wins+?,losses=losses+?,"
            "streak=CASE WHEN ? THEN streak+1 ELSE 0 END,"
            "best=MAX(best,CASE WHEN ? THEN streak+1 ELSE best END),"
            "coins=coins+?,shots=shots+?,hits=hits+? WHERE user_id=?",
            (int(won), int(not won), int(won), int(won), reward, shots, hits, user_id),
        )
        self.db.commit()

    def leaders(self):
        return self.db.execute(
            "SELECT user_id,wins,best,coins FROM naval_stats "
            "ORDER BY wins DESC,best DESC LIMIT 10"
        ).fetchall()

    def setting(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM naval_settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_setting(self, key: str, value: str):
        self.db.execute(
            "INSERT OR REPLACE INTO naval_settings(key,value) VALUES(?,?)", (key, value)
        )
        self.db.commit()


def button(text: str, data: str, style: str | None = None) -> dict:
    result = {"text": text, "callback_data": data}
    if style:
        result["style"] = style
    return result


def index_to_coord(index: int, size: int) -> str:
    return f"{chr(1040 + index % size)}{index // size + 1}"


def adjacent(index: int, size: int, diagonal: bool = False) -> list[int]:
    row, column = divmod(index, size)
    result = []
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if not (dr or dc) or (not diagonal and abs(dr) + abs(dc) != 1):
                continue
            nr, nc = row + dr, column + dc
            if 0 <= nr < size and 0 <= nc < size:
                result.append(nr * size + nc)
    return result


def place_fleet(size: int, lengths: list[int], rng=random) -> list[list[int]]:
    for _ in range(200):
        ships: list[list[int]] = []
        occupied: set[int] = set()
        for length in lengths:
            choices = []
            for vertical in (False, True):
                max_row = size - length if vertical else size - 1
                max_col = size - 1 if vertical else size - length
                for row in range(max_row + 1):
                    for column in range(max_col + 1):
                        cells = [
                            (row + offset if vertical else row) * size
                            + (column if vertical else column + offset)
                            for offset in range(length)
                        ]
                        halo = set(cells)
                        for cell in cells:
                            halo.update(adjacent(cell, size, True))
                        if not occupied.intersection(halo):
                            choices.append(cells)
            if not choices:
                break
            ship = rng.choice(choices)
            ships.append(ship)
            occupied.update(ship)
        if len(ships) == len(lengths):
            return ships
    raise RuntimeError("Не удалось расставить флот")


def fleet_cells(ships: list[list[int]]) -> set[int]:
    return {cell for ship in ships for cell in ship}


def ship_at(ships: list[list[int]], index: int) -> list[int] | None:
    return next((ship for ship in ships if index in ship), None)


def is_sunk(ship: list[int], shots: list[int]) -> bool:
    return set(ship).issubset(shots)


def afloat(ships: list[list[int]], shots: list[int]) -> int:
    return sum(not is_sunk(ship, shots) for ship in ships)


def new_game(user_id: int, size: int = 8) -> dict:
    size = size if size in GAME_MODES else 8
    mode = GAME_MODES[size]
    return {
        "id": uuid.uuid4().hex[:10],
        "uid": user_id,
        "size": size,
        "player_ships": place_fleet(size, mode["ships"]),
        "enemy_ships": place_fleet(size, mode["ships"]),
        "player_shots": [],
        "dog_shots": [],
        "dog_targets": [],
        "message": "Ваш ход, капитан. Выберите клетку для выстрела.",
        "done": False,
        "won": None,
        "started": int(time.time()),
    }


def finish_if_needed(game: dict, store: Store) -> bool:
    if game["done"]:
        return True
    enemy_destroyed = fleet_cells(game["enemy_ships"]).issubset(game["player_shots"])
    player_destroyed = fleet_cells(game["player_ships"]).issubset(game["dog_shots"])
    if not enemy_destroyed and not player_destroyed:
        return False
    won = enemy_destroyed
    game["done"] = True
    game["won"] = won
    reward = GAME_MODES[game["size"]]["reward"] if won else 0
    game["message"] = (
        f"🏆 Флот пса уничтожен! Победа и +{reward} монет."
        if won else "💀 Ваш флот уничтожен. Пёс-адмирал победил."
    )
    store.record(game, won)
    return True


def dog_fire(game: dict, rng=random) -> tuple[int, bool]:
    size = game["size"]
    fired = set(game["dog_shots"])
    targets = game["dog_targets"]
    while targets and targets[-1] in fired:
        targets.pop()
    if targets:
        target = targets.pop()
    else:
        target = rng.choice([index for index in range(size * size) if index not in fired])
    game["dog_shots"].append(target)
    hit = target in fleet_cells(game["player_ships"])
    if hit:
        ship = ship_at(game["player_ships"], target)
        if ship and not is_sunk(ship, game["dog_shots"]):
            nearby = [cell for cell in adjacent(target, size) if cell not in game["dog_shots"]]
            rng.shuffle(nearby)
            targets.extend(nearby)
    return target, hit


def fire(game: dict, index: int, store: Store, rng=random) -> str:
    size = game["size"]
    if game["done"]:
        return "Партия уже закончена."
    if not 0 <= index < size * size or index in game["player_shots"]:
        return "Эта клетка уже проверена."
    game["player_shots"].append(index)
    target_ship = ship_at(game["enemy_ships"], index)
    hit = target_ship is not None
    player_result = "попадание" if hit else "мимо"
    if target_ship and is_sunk(target_ship, game["player_shots"]):
        player_result = "корабль потоплен"
    game["message"] = f"🎯 {index_to_coord(index, size)}: {player_result}!"
    if finish_if_needed(game, store):
        return game["message"]
    dog_index, dog_hit = dog_fire(game, rng)
    game["message"] += (
        f"\n🐕 Пёс стреляет в {index_to_coord(dog_index, size)}: "
        f"{'попал!' if dog_hit else 'мимо.'}"
    )
    finish_if_needed(game, store)
    return game["message"]


def menu_view() -> dict:
    return {"blocks": [
        {"type": "heading", "size": 2, "text": "⚓ Морской бой с Псом"},
        {"type": "paragraph", "text": (
            "Выберите размер моря. Корабли расставятся автоматически, "
            "а каждое синее поле станет отдельной кликабельной клеткой."
        )},
        {"type": "buttons", "align": "center", "buttons": [
            button("🌊 6×6 · +5", "size:6", "success"),
            button("⚓ 8×8 · +10", "size:8", "primary"),
            button("🫡 10×10 · +15", "size:10"),
        ]},
        {"type": "buttons", "align": "center", "buttons": [
            button("📊 Статистика", "stats"),
            button("📖 Правила", "rules"),
        ]},
    ]}


def board_cells(game: dict, own: bool = False) -> list[list[dict]]:
    size = game["size"]
    shots = game["dog_shots"] if own else game["player_shots"]
    ships = game["player_ships"] if own else game["enemy_ships"]
    occupied = fleet_cells(ships)
    cells = []
    for index in range(size * size):
        ship = ship_at(ships, index)
        if own:
            if index in shots and index in occupied:
                label, style = "💥", "danger"
            elif index in shots:
                label, style = "·", None
            elif index in occupied:
                label, style = "▰", "success"
            else:
                label, style = "≈", "primary"
            data = "noop"
        elif index in shots and ship:
            label = "☠" if is_sunk(ship, shots) else "💥"
            style, data = "danger", "noop"
        elif index in shots:
            label, style, data = "·", None, "noop"
        elif game["done"] and index in occupied:
            label, style, data = "▰", "success", "noop"
        else:
            label, style, data = "≈", "primary", f"fire:{game['id']}:{index}"
        cells.append({
            "text": {"type": "button", "button": button(label, data, style)},
            "align": "center",
            "valign": "middle",
        })
    return [cells[index:index + size] for index in range(0, len(cells), size)]


def battle_view(game: dict, own: bool = False, photo_media: str | bool | None = None) -> dict:
    mode = GAME_MODES[game["size"]]
    elapsed = max(0, int(time.time()) - game["started"])
    enemy_left = afloat(game["enemy_ships"], game["player_shots"])
    player_left = afloat(game["player_ships"], game["dog_shots"])
    blocks = []
    if photo_media is not False:
        blocks.append({
            "type": "photo",
            "photo": {"type": "photo", "media": photo_media or "attach://battle_scene"},
        })
    blocks += [
        {"type": "heading", "size": 2, "text": "⚓ Морской бой с Псом"},
        {"type": "paragraph", "text": game["message"]},
        {"type": "paragraph", "text": (
            f"{mode['icon']} {mode['name']} {game['size']}×{game['size']} · награда {mode['reward']} 🪙\n"
            f"Ваш флот: {player_left} 🚢 · Флот пса: {enemy_left} 🐾 · "
            f"⏱ {elapsed // 60}:{elapsed % 60:02d}"
        )},
        {"type": "buttons", "align": "center", "buttons": [
            button("🎯 Поле противника", f"board:{game['id']}:enemy", "primary" if not own else None),
            button("🛡 Мой флот", f"board:{game['id']}:own", "success" if own else None),
        ]},
        {"type": "paragraph", "text": "Ваш флот" if own else "Выберите клетку для выстрела"},
        {"type": "table", "cells": board_cells(game, own), "is_bordered": True, "is_compact": True},
        {"type": "paragraph", "text": "Легенда: ≈ вода · ▰ корабль · 💥 попадание · ☠ потоплен"},
        {"type": "buttons", "align": "center", "buttons": [
            button("Новая игра", "new", "primary"),
            button("Статистика", "stats"),
            button("Правила", "rules"),
        ]},
    ]
    return {"blocks": blocks}


def load_avatar() -> bytes:
    with open(AVATAR_B64, encoding="ascii") as source:
        return base64.b64decode(source.read())


def render_scene(game: dict) -> bytes:
    canvas = Image.new("RGB", (1280, 720), "#071a38")
    draw = ImageDraw.Draw(canvas)
    for y in range(720):
        ratio = y / 719
        color = (int(12 + 7 * ratio), int(47 + 70 * ratio), int(91 + 65 * ratio))
        draw.line((0, y, 1280, y), fill=color)
    for y in range(470, 720, 34):
        for x in range(-40, 1280, 80):
            draw.arc((x, y, x + 90, y + 38), 190, 350, fill="#53c7df", width=4)
    avatar = Image.open(BytesIO(load_avatar())).convert("RGB").resize((430, 430))
    canvas.paste(avatar, (800, 120))
    draw.rounded_rectangle((790, 110, 1240, 570), 28, outline="#f5c85b", width=8)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    title = ImageFont.truetype(font_path, 54)
    large = ImageFont.truetype(font_path, 38)
    medium = ImageFont.truetype(font_path, 28)
    draw.text((55, 55), "МОРСКОЙ БОЙ", font=title, fill="#fff4c5", stroke_width=2, stroke_fill="#102953")
    draw.text((58, 125), "с Псом-адмиралом", font=large, fill="#77e7ff")
    player_left = afloat(game["player_ships"], game["dog_shots"])
    enemy_left = afloat(game["enemy_ships"], game["player_shots"])
    draw.rounded_rectangle((55, 220, 700, 430), 24, fill="#0a2c58", outline="#54cfe5", width=4)
    draw.text((90, 255), f"ВАШ ФЛОТ   {player_left} КОРАБЛЕЙ", font=medium, fill="white")
    draw.text((90, 325), f"ФЛОТ ПСА   {enemy_left} КОРАБЛЕЙ", font=medium, fill="#ffd36c")
    shots = len(game["player_shots"])
    hits = sum(index in fleet_cells(game["enemy_ships"]) for index in game["player_shots"])
    draw.text((90, 390), f"Выстрелы: {shots}  Попадания: {hits}", font=medium, fill="#a7efff")
    status = "ПОБЕДА!" if game.get("won") is True else "ПОРАЖЕНИЕ" if game.get("won") is False else "ВАШ ХОД"
    color = "#65ef91" if game.get("won") is True else "#ff6b72" if game.get("won") is False else "#f5c85b"
    draw.text((60, 505), status, font=title, fill=color, stroke_width=2, stroke_fill="#102953")
    output = BytesIO()
    canvas.save(output, "JPEG", quality=88, optimize=True)
    return output.getvalue()


def prepared_battle_view(api: API, game: dict, inline_id: str | None, own: bool = False):
    image = render_scene(game)
    if not inline_id:
        return battle_view(game, own), image
    cache_chat_id = int(os.getenv("CACHE_CHAT_ID", str(game["uid"])))
    try:
        file_id = api.cache_photo(cache_chat_id, image)
        return battle_view(game, own, file_id), None
    except Exception as error:
        print("inline scene fallback:", type(error).__name__, error)
        return battle_view(game, own, False), None


def stats_text(store: Store, user_id: int) -> str:
    wins, losses, streak, best, coins, shots, hits = store.stats(user_id)
    accuracy = round(hits * 100 / shots) if shots else 0
    return (
        f"Победы: {wins}\nПоражения: {losses}\nСерия: {streak}\n"
        f"Рекорд: {best}\nМонеты: {coins} 🪙\nТочность: {accuracy}%"
    )


def configure_profile(api: API, store: Store):
    api.call("setMyName", {"name": "Морской бой с Псом"})
    api.call("setMyDescription", {"description": (
        "Морской бой прямо в сообщениях Telegram. Выбирайте клетки, "
        "топите корабли и победите Пса-адмирала!"
    )})
    api.call("setMyShortDescription", {
        "short_description": "⚓ Кликабельный морской бой прямо в сообщениях Telegram"
    })
    if store.setting("profile_version") == PROFILE_VERSION:
        return
    api.multipart(
        "setMyProfilePhoto",
        {"photo": {"type": "static", "photo": "attach://avatar"}},
        load_avatar(),
        "avatar",
        "avatar.jpg",
        "image/jpeg",
    )
    store.set_setting("profile_version", PROFILE_VERSION)


def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN required")
    api = API(token)
    store = Store(os.getenv("DATABASE_PATH", "sea_battle.sqlite3"))
    commands = [
        {"command": "start", "description": "Начать морской бой"},
        {"command": "new", "description": "Новый бой"},
        {"command": "group", "description": "Запустить бой в группе"},
        {"command": "stats", "description": "Моя статистика"},
        {"command": "top", "description": "Рейтинг капитанов"},
        {"command": "rules", "description": "Правила игры"},
        {"command": "creator", "description": "Создатель бота"},
    ]
    api.call("setMyCommands", {"commands": commands})
    api.call("setMyCommands", {"commands": commands, "scope": {"type": "all_group_chats"}})
    try:
        configure_profile(api, store)
    except Exception as error:
        print("profile setup:", type(error).__name__, error)
    offset = 0
    while True:
        try:
            updates = api.call("getUpdates", {
                "offset": offset,
                "timeout": 30,
                "allowed_updates": ["message", "callback_query", "inline_query", "guest_message"],
            }, 40)
            for update in updates:
                offset = update["update_id"] + 1
                if "inline_query" in update:
                    api.answer_inline(update["inline_query"]["id"], menu_view())
                    continue
                if "guest_message" in update:
                    query_id = update["guest_message"].get("guest_query_id")
                    if query_id:
                        api.answer_guest(query_id, menu_view())
                    continue
                if "message" in update:
                    message = update["message"]
                    text = message.get("text", "").split("@", 1)[0]
                    chat_id = message["chat"]["id"]
                    user_id = message["from"]["id"]
                    if text == "/creator":
                        api.call("sendMessage", {
                            "chat_id": chat_id,
                            "text": "Создатель бота — @eternall_dog\nПо всем вопросам и предложениям пишите ему.",
                        })
                    elif text == "/stats":
                        api.call("sendMessage", {"chat_id": chat_id, "text": stats_text(store, user_id)})
                    elif text == "/top":
                        rows = store.leaders()
                        listing = "\n".join(
                            f"{number}. Капитан {uid} — {wins} побед · {coins} 🪙"
                            for number, (uid, wins, _, coins) in enumerate(rows, 1)
                        ) or "Пока победителей нет."
                        api.call("sendMessage", {"chat_id": chat_id, "text": "🏆 Лучшие капитаны\n" + listing})
                    elif text == "/rules":
                        api.call("sendMessage", {"chat_id": chat_id, "text": (
                            "Стреляйте по синим клеткам поля противника. После каждого вашего "
                            "выстрела отвечает Пёс. Побеждает тот, кто первым потопит весь флот."
                        )})
                    elif text in {"/start", "/new", "/group"}:
                        api.send_rich(chat_id, menu_view())
                    continue
                if "callback_query" not in update:
                    continue
                query = update["callback_query"]
                data = query["data"]
                message = query.get("message")
                inline_id = query.get("inline_message_id")
                chat_id = message["chat"]["id"] if message else 0
                message_id = message["message_id"] if message else 0
                user_id = query["from"]["id"]
                if data == "noop":
                    api.answer(query["id"], "Здесь уже всё известно.")
                    continue
                if data == "stats":
                    api.answer(query["id"], stats_text(store, user_id), True)
                    continue
                if data == "rules":
                    api.answer(query["id"], (
                        "Стреляйте по клеткам противника. 💥 — попадание, ☠ — корабль потоплен. "
                        "После вашего выстрела ходит Пёс."
                    ), True)
                    continue
                if data in {"new", "menu"}:
                    api.answer(query["id"])
                    api.edit_rich(chat_id, message_id, menu_view(), inline_id)
                    continue
                if data.startswith("size:"):
                    game = new_game(user_id, int(data.split(":", 1)[1]))
                    store.save(game)
                    api.answer(query["id"])
                    view, image = prepared_battle_view(api, game, inline_id)
                    api.edit_rich(chat_id, message_id, view, inline_id, image)
                    continue
                if data.startswith("fire:") or data.startswith("board:"):
                    parts = data.split(":")
                    game = store.get(parts[1])
                    if not game or game["uid"] != user_id:
                        api.answer(query["id"], "Этот бой принадлежит другому капитану.", True)
                        continue
                    own = data.startswith("board:") and parts[2] == "own"
                    if data.startswith("fire:"):
                        fire(game, int(parts[2]), store)
                        store.save(game)
                        own = False
                    api.answer(query["id"])
                    view, image = prepared_battle_view(api, game, inline_id, own)
                    api.edit_rich(chat_id, message_id, view, inline_id, image)
                    continue
                api.answer(query["id"], "Неизвестная команда.", True)
        except Exception as error:
            print(type(error).__name__, error)
            time.sleep(3)


if __name__ == "__main__":
    main()
