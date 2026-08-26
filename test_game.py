import random
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bot


class SeaBattleTests(unittest.TestCase):
    def test_all_modes_place_the_expected_fleet(self):
        for size, mode in bot.GAME_MODES.items():
            ships = bot.place_fleet(size, mode["ships"], random.Random(size))
            self.assertEqual(sorted(map(len, ships)), sorted(mode["ships"]))
            cells = [cell for ship in ships for cell in ship]
            self.assertEqual(len(cells), len(set(cells)))

    def test_ships_never_touch_even_diagonally(self):
        size = 10
        ships = bot.place_fleet(size, bot.GAME_MODES[size]["ships"], random.Random(5))
        ownership = {cell: number for number, ship in enumerate(ships) for cell in ship}
        for cell, owner in ownership.items():
            for neighbor in bot.adjacent(cell, size, True):
                if neighbor in ownership:
                    self.assertEqual(ownership[neighbor], owner)

    def test_new_game_has_two_complete_fleets(self):
        game = bot.new_game(7, 8)
        expected = sum(bot.GAME_MODES[8]["ships"])
        self.assertEqual(len(bot.fleet_cells(game["player_ships"])), expected)
        self.assertEqual(len(bot.fleet_cells(game["enemy_ships"])), expected)

    def test_player_click_is_followed_by_dog_shot(self):
        with TemporaryDirectory() as directory:
            store = bot.Store(str(Path(directory) / "battle.sqlite3"))
            game = bot.new_game(1, 6)
            bot.fire(game, 0, store, random.Random(2))
            self.assertEqual(game["player_shots"], [0])
            self.assertEqual(len(game["dog_shots"]), 1)

    def test_repeated_shot_does_not_give_dog_another_turn(self):
        with TemporaryDirectory() as directory:
            store = bot.Store(str(Path(directory) / "battle.sqlite3"))
            game = bot.new_game(1, 6)
            bot.fire(game, 0, store, random.Random(2))
            bot.fire(game, 0, store, random.Random(2))
            self.assertEqual(len(game["dog_shots"]), 1)

    def test_victory_awards_mode_coins_only_once(self):
        with TemporaryDirectory() as directory:
            store = bot.Store(str(Path(directory) / "battle.sqlite3"))
            game = bot.new_game(9, 10)
            game["player_shots"] = list(bot.fleet_cells(game["enemy_ships"]))
            self.assertTrue(bot.finish_if_needed(game, store))
            self.assertTrue(bot.finish_if_needed(game, store))
            self.assertEqual(store.stats(9)[0], 1)
            self.assertEqual(store.stats(9)[4], 15)

    def test_enemy_board_has_one_clickable_cell_per_coordinate(self):
        game = bot.new_game(1, 8)
        rows = bot.board_cells(game)
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(len(row) == 8 for row in rows))
        callbacks = [cell["text"]["button"]["callback_data"] for row in rows for cell in row]
        self.assertTrue(all(value.startswith("fire:") for value in callbacks))

    def test_own_board_reveals_own_ships(self):
        game = bot.new_game(1, 6)
        labels = [cell["text"]["button"]["text"] for row in bot.board_cells(game, True) for cell in row]
        self.assertEqual(labels.count("▰"), sum(bot.GAME_MODES[6]["ships"]))

    def test_game_state_and_stats_are_persistent(self):
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "battle.sqlite3")
            store = bot.Store(path)
            game = bot.new_game(42, 6)
            store.save(game)
            self.assertEqual(bot.Store(path).get(game["id"])["uid"], 42)

    def test_scene_contains_real_graphics(self):
        game = bot.new_game(1, 8)
        self.assertGreater(len(bot.render_scene(game)), 50000)

    def test_menu_offers_all_three_sizes(self):
        callbacks = [
            item["callback_data"]
            for block in bot.menu_view()["blocks"] if block["type"] == "buttons"
            for item in block["buttons"]
        ]
        self.assertTrue({"size:6", "size:8", "size:10"}.issubset(callbacks))

    def test_old_database_tables_do_not_break_migration(self):
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "old.sqlite3")
            database = sqlite3.connect(path)
            database.execute("CREATE TABLE games(id TEXT PRIMARY KEY,user_id INTEGER,state TEXT)")
            database.commit()
            database.close()
            self.assertEqual(bot.Store(path).stats(1), (0, 0, 0, 0, 0, 0, 0))

    def test_guest_query_uses_rich_message(self):
        class FakeAPI(bot.API):
            def __init__(self):
                self.calls = []

            def call(self, method, payload=None, timeout=45):
                self.calls.append((method, payload))
                return {"inline_message_id": "guest-message"}

        api = FakeAPI()
        api.answer_guest("guest-query", bot.menu_view())
        method, payload = api.calls[0]
        self.assertEqual(method, "answerGuestQuery")
        self.assertEqual(payload["guest_query_id"], "guest-query")
        self.assertIn("rich_message", payload["result"]["input_message_content"])


if __name__ == "__main__":
    unittest.main()
