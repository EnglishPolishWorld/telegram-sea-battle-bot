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
SHOP_ITEMS = {
    "radar": {"name": "Радар", "icon": "📡", "price": 25,
              "description": "Показывает одну клетку, где точно есть корабль."},
    "mine": {"name": "Мина", "icon": "💣", "price": 20,
             "description": "Следующий выстрел Пса будет обезврежен."},
    "shield": {"name": "Щит", "icon": "🛡", "price": 18,
               "description": "Блокирует следующее попадание по вашему кораблю."},
    "airstrike": {"name": "Авиаудар", "icon": "✈️", "price": 45,
                  "description": "Накрывает сразу три случайные клетки противника."},
    "sonar": {"name": "Сонар", "icon": "🔊", "price": 22,
              "description": "Сообщает, сколько палуб скрыто в случайной строке."},
    "torpedo": {"name": "Торпеда", "icon": "🚀", "price": 40,
                "description": "Проверяет четыре клетки в случайной линии."},
    "repair": {"name": "Ремкомплект", "icon": "🔧", "price": 30,
               "description": "Восстанавливает одну подбитую палубу непотопленного корабля."},
    "smoke": {"name": "Дымовая завеса", "icon": "🌫", "price": 15,
              "description": "Следующий выстрел Пса гарантированно уйдёт в воду."},
    "spyglass": {"name": "Подзорная труба", "icon": "🔭", "price": 12,
                 "description": "Отмечает две клетки, где кораблей точно нет."},
    "salvo": {"name": "Дополнительный залп", "icon": "💥", "price": 35,
              "description": "После вашего выстрела автоматически делает ещё один."},
}
SHOP_PAGE_SIZE = 2
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
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS naval_inventory("
            "user_id INTEGER NOT NULL,item_id TEXT NOT NULL,quantity INTEGER DEFAULT 0,"
            "PRIMARY KEY(user_id,item_id))"
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

    def inventory(self, user_id: int) -> dict[str, int]:
        return {
            item_id: quantity
            for item_id, quantity in self.db.execute(
                "SELECT item_id,quantity FROM naval_inventory WHERE user_id=? AND quantity>0",
                (user_id,),
            ).fetchall()
        }

    def buy(self, user_id: int, item_id: str) -> tuple[bool, str]:
        item = SHOP_ITEMS.get(item_id)
        if not item:
            return False, "Такого товара нет."
        self.db.execute("INSERT OR IGNORE INTO naval_stats(user_id) VALUES(?)", (user_id,))
        coins = self.db.execute(
            "SELECT coins FROM naval_stats WHERE user_id=?", (user_id,)
        ).fetchone()[0]
        if coins < item["price"]:
            return False, f"Не хватает {item['price'] - coins} монет."
        self.db.execute(
            "UPDATE naval_stats SET coins=coins-? WHERE user_id=?", (item["price"], user_id)
        )
        self.db.execute(
            "INSERT INTO naval_inventory(user_id,item_id,quantity) VALUES(?,?,1) "
            "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=quantity+1",
            (user_id, item_id),
        )
        self.db.commit()
        return True, f"{item['icon']} {item['name']} добавлен в инвентарь."

    def consume(self, user_id: int, item_id: str) -> bool:
        cursor = self.db.execute(
            "UPDATE naval_inventory SET quantity=quantity-1 "
            "WHERE user_id=? AND item_id=? AND quantity>0",
            (user_id, item_id),
        )
        self.db.execute("DELETE FROM naval_inventory WHERE quantity<=0")
        self.db.commit()
        return cursor.rowcount == 1

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


def ship_cells_from(index: int, length: int, size: int, vertical: bool) -> list[int] | None:
    row, column = divmod(index, size)
    if (vertical and row + length > size) or (not vertical and column + length > size):
        return None
    return [index + offset * size if vertical else index + offset for offset in range(length)]


def can_place_ship(ships: list[list[int]], cells: list[int], size: int) -> bool:
    occupied = fleet_cells(ships)
    blocked = set(occupied)
    for cell in occupied:
        blocked.update(adjacent(cell, size, True))
    return not blocked.intersection(cells)


def new_game(user_id: int, size: int = 8, manual: bool = False) -> dict:
    size = size if size in GAME_MODES else 8
    mode = GAME_MODES[size]
    return {
        "id": uuid.uuid4().hex[:10],
        "uid": user_id,
        "size": size,
        "phase": "placing" if manual else "battle",
        "orientation": "h",
        "player_ships": [] if manual else place_fleet(size, mode["ships"]),
        "enemy_ships": place_fleet(size, mode["ships"]),
        "player_shots": [],
        "dog_shots": [],
        "dog_targets": [],
        "revealed_enemy": [],
        "revealed_water": [],
        "mine": 0,
        "shield": 0,
        "smoke": 0,
        "salvo": 0,
        "message": (
            "Расставьте корабли. Нажмите клетку, с которой начнётся корабль."
            if manual else "Ваш ход, капитан. Выберите клетку для выстрела."
        ),
        "done": False,
        "won": None,
        "started": int(time.time()),
    }


def next_ship_length(game: dict) -> int | None:
    lengths = GAME_MODES[game["size"]]["ships"]
    return lengths[len(game["player_ships"])] if len(game["player_ships"]) < len(lengths) else None


def place_player_ship(game: dict, index: int) -> tuple[bool, str]:
    if game.get("phase") != "placing":
        return False, "Расстановка уже завершена."
    length = next_ship_length(game)
    if length is None:
        return False, "Все корабли уже расставлены."
    cells = ship_cells_from(index, length, game["size"], game.get("orientation") == "v")
    if not cells:
        return False, "Корабль выходит за границу поля."
    if not can_place_ship(game["player_ships"], cells, game["size"]):
        return False, "Корабли не могут касаться друг друга."
    game["player_ships"].append(cells)
    remaining = len(GAME_MODES[game["size"]]["ships"]) - len(game["player_ships"])
    game["message"] = (
        "Флот готов. Нажмите «Начать бой»."
        if not remaining else f"Корабль размещён. Осталось: {remaining}."
    )
    return True, game["message"]


def begin_battle(game: dict) -> tuple[bool, str]:
    if next_ship_length(game) is not None:
        return False, "Сначала расставьте весь флот."
    game["phase"] = "battle"
    game["started"] = int(time.time())
    game["message"] = "Флот готов. Ваш ход, капитан!"
    return True, game["message"]


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
    if game.get("mine", 0):
        game["mine"] -= 1
        game["dog_event"] = "mine"
        return -1, False
    if game.get("smoke", 0):
        water = list(set(range(size * size)) - fleet_cells(game["player_ships"]) - fired)
        if water:
            game["smoke"] -= 1
            target = rng.choice(water)
            game["dog_shots"].append(target)
            game["dog_event"] = "smoke"
            return target, False
    targets = game["dog_targets"]
    while targets and targets[-1] in fired:
        targets.pop()
    if targets:
        target = targets.pop()
    else:
        target = rng.choice([index for index in range(size * size) if index not in fired])
    game["dog_shots"].append(target)
    hit = target in fleet_cells(game["player_ships"])
    if hit and game.get("shield", 0):
        game["shield"] -= 1
        game["dog_shots"].pop()
        game["dog_event"] = "shield"
        return target, False
    if hit:
        ship = ship_at(game["player_ships"], target)
        if ship and not is_sunk(ship, game["dog_shots"]):
            nearby = [cell for cell in adjacent(target, size) if cell not in game["dog_shots"]]
            rng.shuffle(nearby)
            targets.extend(nearby)
    game["dog_event"] = "normal"
    return target, hit


def fire(game: dict, index: int, store: Store, rng=random) -> str:
    size = game["size"]
    if game["done"]:
        return "Партия уже закончена."
    if game.get("phase", "battle") != "battle":
        return "Сначала завершите расстановку флота."
    if not 0 <= index < size * size or index in game["player_shots"]:
        return "Эта клетка уже проверена."
    game["player_shots"].append(index)
    target_ship = ship_at(game["enemy_ships"], index)
    hit = target_ship is not None
    player_result = "попадание" if hit else "мимо"
    if target_ship and is_sunk(target_ship, game["player_shots"]):
        player_result = "корабль потоплен"
    game["message"] = f"🎯 {index_to_coord(index, size)}: {player_result}!"
    if game.get("salvo", 0):
        game["salvo"] -= 1
        available = [cell for cell in range(size * size) if cell not in game["player_shots"]]
        if available:
            extra = rng.choice(available)
            game["player_shots"].append(extra)
            extra_hit = extra in fleet_cells(game["enemy_ships"])
            game["message"] += (
                f"\n💥 Дополнительный залп в {index_to_coord(extra, size)}: "
                f"{'попадание!' if extra_hit else 'мимо.'}"
            )
    if finish_if_needed(game, store):
        return game["message"]
    dog_index, dog_hit = dog_fire(game, rng)
    if game.get("dog_event") == "mine":
        game["message"] += "\n💣 Мина обезвредила выстрел Пса!"
    elif game.get("dog_event") == "shield":
        game["message"] += f"\n🛡 Щит заблокировал попадание в {index_to_coord(dog_index, size)}!"
    elif game.get("dog_event") == "smoke":
        game["message"] += f"\n🌫 Пёс промахнулся в дыму: {index_to_coord(dog_index, size)}."
    else:
        game["message"] += (
            f"\n🐕 Пёс стреляет в {index_to_coord(dog_index, size)}: "
            f"{'попал!' if dog_hit else 'мимо.'}"
        )
    finish_if_needed(game, store)
    return game["message"]


def use_item(game: dict, item_id: str, store: Store, rng=random) -> tuple[bool, str]:
    if game.get("phase", "battle") != "battle" or game.get("done"):
        return False, "Расходники можно применять только во время боя."
    if store.inventory(game["uid"]).get(item_id, 0) <= 0:
        return False, "Этого предмета нет в инвентаре."
    size = game["size"]
    unshot = set(range(size * size)) - set(game["player_shots"])
    enemy = fleet_cells(game["enemy_ships"])
    message = ""
    if item_id == "radar":
        choices = list(unshot & enemy - set(game.get("revealed_enemy", [])))
        if not choices:
            return False, "Радар больше не находит новых целей."
        target = rng.choice(choices)
        game.setdefault("revealed_enemy", []).append(target)
        message = f"📡 Радар обнаружил цель в {index_to_coord(target, size)}."
    elif item_id == "mine":
        game["mine"] = game.get("mine", 0) + 1
        message = "💣 Мина установлена и перехватит следующий выстрел Пса."
    elif item_id == "shield":
        game["shield"] = game.get("shield", 0) + 1
        message = "🛡 Щит защитит от следующего попадания."
    elif item_id == "airstrike":
        targets = rng.sample(list(unshot), min(3, len(unshot)))
        game["player_shots"].extend(targets)
        hits = sum(target in enemy for target in targets)
        message = f"✈️ Авиаудар: проверено {len(targets)} клетки, попаданий — {hits}."
    elif item_id == "sonar":
        row = rng.randrange(size)
        count = sum(row * size + column in enemy for column in range(size))
        message = f"🔊 Сонар: в строке {row + 1} скрыто палуб — {count}."
    elif item_id == "torpedo":
        vertical = bool(rng.randrange(2))
        line = rng.randrange(size)
        cells = [row * size + line for row in range(size)] if vertical else [line * size + col for col in range(size)]
        targets = [cell for cell in cells if cell in unshot][:4]
        game["player_shots"].extend(targets)
        hits = sum(target in enemy for target in targets)
        message = f"🚀 Торпеда проверила {len(targets)} клетки, попаданий — {hits}."
    elif item_id == "repair":
        damaged = [
            cell for ship in game["player_ships"] if not is_sunk(ship, game["dog_shots"])
            for cell in ship if cell in game["dog_shots"]
        ]
        if not damaged:
            return False, "Сейчас нечего ремонтировать."
        target = rng.choice(damaged)
        game["dog_shots"].remove(target)
        message = f"🔧 Палуба {index_to_coord(target, size)} восстановлена."
    elif item_id == "smoke":
        game["smoke"] = game.get("smoke", 0) + 1
        message = "🌫 Следующий выстрел Пса уйдёт в воду."
    elif item_id == "spyglass":
        choices = list(unshot - enemy - set(game.get("revealed_water", [])))
        if not choices:
            return False, "Все безопасные клетки уже известны."
        targets = rng.sample(choices, min(2, len(choices)))
        game.setdefault("revealed_water", []).extend(targets)
        message = "🔭 Пустые клетки: " + ", ".join(index_to_coord(cell, size) for cell in targets) + "."
    elif item_id == "salvo":
        game["salvo"] = game.get("salvo", 0) + 1
        message = "💥 Следующий выстрел будет двойным."
    else:
        return False, "Неизвестный расходник."
    if not store.consume(game["uid"], item_id):
        return False, "Не удалось списать предмет."
    game["message"] = message
    finish_if_needed(game, store)
    return True, message


def menu_view() -> dict:
    return {"blocks": [
        {"type": "heading", "size": 2, "text": "⚓ Морской бой с Псом"},
        {"type": "paragraph", "text": (
            "Выберите размер моря, а затем самостоятельно расставьте свой флот."
        )},
        {"type": "buttons", "align": "center", "buttons": [
            button("🌊 6×6", "size:6", "success"),
            button("⚓ 8×8", "size:8", "primary"),
            button("🫡 10×10", "size:10"),
        ]},
        {"type": "buttons", "align": "center", "buttons": [
            button("🛒 Магазин", "shop:0"),
            button("📊 Статистика", "stats"),
            button("📖 Правила", "rules"),
        ]},
    ]}


def shop_view(store: Store, user_id: int, page: int = 0) -> dict:
    items = list(SHOP_ITEMS.items())
    pages = max(1, (len(items) + SHOP_PAGE_SIZE - 1) // SHOP_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    balance = store.stats(user_id)[4]
    inventory = store.inventory(user_id)
    blocks = [
        {"type": "heading", "size": 2, "text": "🛒 Адмиральский магазин"},
        {"type": "paragraph", "text": f"Ваш баланс: {balance} 🪙 · Страница {page + 1}/{pages}"},
    ]
    start = page * SHOP_PAGE_SIZE
    for item_id, item in items[start:start + SHOP_PAGE_SIZE]:
        owned = inventory.get(item_id, 0)
        blocks += [
            {"type": "heading", "size": 3, "text": f"{item['icon']} {item['name']}"},
            {"type": "paragraph", "text": (
                f"Цена: {item['price']} 🪙 · В наличии: {owned}\n{item['description']}"
            )},
            {"type": "buttons", "align": "center", "buttons": [
                button("Купить", f"buy:{item_id}:{page}", "primary")
            ]},
        ]
    navigation = []
    if page > 0:
        navigation.append(button("← Назад", f"shop:{page - 1}"))
    if page + 1 < pages:
        navigation.append(button("Дальше →", f"shop:{page + 1}"))
    if navigation:
        blocks.append({"type": "buttons", "align": "center", "buttons": navigation})
    blocks.append({"type": "buttons", "align": "center", "buttons": [button("Меню", "menu")]})
    return {"blocks": blocks}


def placement_cells(game: dict) -> list[list[dict]]:
    size = game["size"]
    occupied = fleet_cells(game["player_ships"])
    ready = next_ship_length(game) is None
    cells = []
    for index in range(size * size):
        label, style = ("▰", "success") if index in occupied else ("≈", "primary")
        data = "noop" if index in occupied or ready else f"place:{game['id']}:{index}"
        cells.append({
            "text": {"type": "button", "button": button(label, data, style)},
            "align": "center", "valign": "middle",
        })
    return [cells[index:index + size] for index in range(0, len(cells), size)]


def placement_view(game: dict) -> dict:
    length = next_ship_length(game)
    total = len(GAME_MODES[game["size"]]["ships"])
    placed = len(game["player_ships"])
    direction = "вертикально" if game.get("orientation") == "v" else "горизонтально"
    blocks = [
        {"type": "heading", "size": 2, "text": "🚢 Расстановка флота"},
        {"type": "paragraph", "text": game["message"]},
        {"type": "paragraph", "text": (
            f"Поле {game['size']}×{game['size']} · размещено {placed}/{total}\n"
            + (f"Следующий корабль: {length} палубы · {direction}" if length else "Флот полностью готов.")
        )},
        {"type": "buttons", "align": "center", "buttons": [
            button("↔ Горизонтально", f"orient:{game['id']}:h", "primary" if game.get("orientation") == "h" else None),
            button("↕ Вертикально", f"orient:{game['id']}:v", "primary" if game.get("orientation") == "v" else None),
        ]},
        {"type": "table", "cells": placement_cells(game), "is_bordered": True, "is_compact": True},
    ]
    actions = []
    if game["player_ships"]:
        actions.append(button("Отменить последний", f"undo:{game['id']}"))
    actions.append(button("Случайно", f"random:{game['id']}"))
    if length is None:
        actions.append(button("Начать бой", f"begin:{game['id']}", "success"))
    blocks += [
        {"type": "buttons", "align": "center", "buttons": actions},
        {"type": "buttons", "align": "center", "buttons": [button("Меню", "menu")]},
    ]
    return {"blocks": blocks}


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
        elif index in game.get("revealed_enemy", []):
            label, style, data = "📡", "success", f"fire:{game['id']}:{index}"
        elif index in game.get("revealed_water", []):
            label, style, data = "○", None, f"fire:{game['id']}:{index}"
        else:
            label, style, data = "≈", "primary", f"fire:{game['id']}:{index}"
        cells.append({
            "text": {"type": "button", "button": button(label, data, style)},
            "align": "center",
            "valign": "middle",
        })
    return [cells[index:index + size] for index in range(0, len(cells), size)]


def battle_view(
    game: dict,
    own: bool = False,
    photo_media: str | bool | None = None,
    inventory: dict[str, int] | None = None,
) -> dict:
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
    ]
    available = [(item_id, count) for item_id, count in (inventory or {}).items() if count > 0]
    if available and not game["done"]:
        blocks.append({"type": "paragraph", "text": "🎒 Расходники — нажмите, чтобы применить"})
        item_buttons = [
            button(
                f"{SHOP_ITEMS[item_id]['icon']} {SHOP_ITEMS[item_id]['name']} ×{count}",
                f"use:{game['id']}:{item_id}",
            )
            for item_id, count in available if item_id in SHOP_ITEMS
        ]
        for start in range(0, len(item_buttons), 3):
            blocks.append({"type": "buttons", "align": "center", "buttons": item_buttons[start:start + 3]})
    blocks.append({"type": "buttons", "align": "center", "buttons": [
        button("Новая игра", "new", "primary"),
        button("Магазин", "shop:0"),
        button("Статистика", "stats"),
        button("Правила", "rules"),
    ]})
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


def prepared_battle_view(
    api: API, game: dict, inline_id: str | None, store: Store, own: bool = False
):
    image = render_scene(game)
    inventory = store.inventory(game["uid"])
    if not inline_id:
        return battle_view(game, own, inventory=inventory), image
    cache_chat_id = int(os.getenv("CACHE_CHAT_ID", str(game["uid"])))
    try:
        file_id = api.cache_photo(cache_chat_id, image)
        return battle_view(game, own, file_id, inventory), None
    except Exception as error:
        print("inline scene fallback:", type(error).__name__, error)
        return battle_view(game, own, False, inventory), None


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
        {"command": "shop", "description": "Магазин расходников"},
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
                            "Сначала расставьте флот: выберите направление и начальную клетку. "
                            "Затем стреляйте по полю противника. После каждого вашего выстрела "
                            "отвечает Пёс. Расходники покупаются в магазине за монеты от побед."
                        )})
                    elif text == "/shop":
                        api.send_rich(chat_id, shop_view(store, user_id))
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
                        "Сначала расставьте корабли. Затем стреляйте по клеткам противника. "
                        "💥 — попадание, ☠ — корабль потоплен. После выстрела ходит Пёс."
                    ), True)
                    continue
                if data in {"new", "menu"}:
                    api.answer(query["id"])
                    api.edit_rich(chat_id, message_id, menu_view(), inline_id)
                    continue
                if data.startswith("shop:"):
                    page = int(data.split(":", 1)[1])
                    api.answer(query["id"])
                    api.edit_rich(chat_id, message_id, shop_view(store, user_id, page), inline_id)
                    continue
                if data.startswith("buy:"):
                    _, item_id, page = data.split(":")
                    bought, notice = store.buy(user_id, item_id)
                    api.answer(query["id"], notice, not bought)
                    api.edit_rich(chat_id, message_id, shop_view(store, user_id, int(page)), inline_id)
                    continue
                if data.startswith("size:"):
                    game = new_game(user_id, int(data.split(":", 1)[1]), manual=True)
                    store.save(game)
                    api.answer(query["id"])
                    api.edit_rich(chat_id, message_id, placement_view(game), inline_id)
                    continue
                if data.startswith(("place:", "orient:", "undo:", "random:", "begin:")):
                    parts = data.split(":")
                    game = store.get(parts[1])
                    if not game or game["uid"] != user_id:
                        api.answer(query["id"], "Эта расстановка принадлежит другому капитану.", True)
                        continue
                    notice = ""
                    valid = True
                    if data.startswith("place:"):
                        valid, notice = place_player_ship(game, int(parts[2]))
                    elif data.startswith("orient:"):
                        game["orientation"] = parts[2] if parts[2] in {"h", "v"} else "h"
                    elif data.startswith("undo:"):
                        if game["player_ships"]:
                            game["player_ships"].pop()
                            game["message"] = "Последний корабль убран."
                    elif data.startswith("random:"):
                        game["player_ships"] = place_fleet(
                            game["size"], GAME_MODES[game["size"]]["ships"]
                        )
                        game["message"] = "Флот расставлен случайно. Можно начинать бой."
                    elif data.startswith("begin:"):
                        valid, notice = begin_battle(game)
                    store.save(game)
                    api.answer(query["id"], notice, not valid)
                    if data.startswith("begin:") and valid:
                        view, image = prepared_battle_view(api, game, inline_id, store)
                        api.edit_rich(chat_id, message_id, view, inline_id, image)
                    else:
                        api.edit_rich(chat_id, message_id, placement_view(game), inline_id)
                    continue
                if data.startswith("use:"):
                    _, game_id, item_id = data.split(":")
                    game = store.get(game_id)
                    if not game or game["uid"] != user_id:
                        api.answer(query["id"], "Этот бой принадлежит другому капитану.", True)
                        continue
                    used, notice = use_item(game, item_id, store)
                    if used:
                        store.save(game)
                    api.answer(query["id"], notice, not used)
                    view, image = prepared_battle_view(api, game, inline_id, store)
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
                    view, image = prepared_battle_view(api, game, inline_id, store, own)
                    api.edit_rich(chat_id, message_id, view, inline_id, image)
                    continue
                api.answer(query["id"], "Неизвестная команда.", True)
        except Exception as error:
            print(type(error).__name__, error)
            time.sleep(3)


if __name__ == "__main__":
    main()
