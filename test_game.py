import unittest
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import bot


class GameTests(unittest.TestCase):
    def test_deck_has_36_unique_cards(self):
        self.assertEqual(len(bot.ALL_CARDS), 36)
        self.assertEqual(len(set(bot.ALL_CARDS)), 36)

    def test_initial_hands_have_seven_clickable_cards(self):
        with patch("bot.random.shuffle", lambda deck: None):
            game = bot.new_game(1)
        tables = [block for block in bot.game_view(game)["blocks"] if block["type"] == "table"]
        self.assertEqual(len(game["player"]), 7)
        self.assertEqual(len(game["dog"]), 7)
        self.assertEqual(sum(len(row) for row in tables[0]["cells"]), 7)
        self.assertEqual(sum(len(row) for row in tables[1]["cells"]), 7)
        callbacks = [cell["text"]["button"]["callback_data"] for row in tables[1]["cells"] for cell in row]
        self.assertTrue(all(value.startswith("ask:") for value in callbacks))

    def test_cards_are_conserved(self):
        game = bot.new_game(1)
        total = len(game["deck"]) + len(game["player"]) + len(game["dog"])
        total += 4 * (len(game["player_books"]) + len(game["dog_books"]))
        self.assertEqual(total, 36)

    def test_cards_use_graphical_unicode_faces(self):
        self.assertEqual(bot.card_label("AS"), "🂡")
        self.assertEqual(bot.card_label("KH"), "🂾")

    def test_scene_supports_twelve_visible_cards(self):
        game = bot.new_game(1)
        game["player"] = bot.ALL_CARDS[:12]
        self.assertGreater(len(bot.render_scene(game)), 50000)

    def test_hard_victory_awards_fifteen_coins_once(self):
        with TemporaryDirectory() as directory:
            store = bot.Store(str(Path(directory) / "game.sqlite3"))
            game = bot.new_game(7, "hard")
            game.update({
                "deck": [], "player": [], "dog": [],
                "player_books": ["6", "7", "8", "9", "10"],
                "dog_books": ["J", "Q", "K", "A"],
            })
            bot.finish_if_needed(game, store)
            bot.finish_if_needed(game, store)
            self.assertEqual(store.stats(7), (1, 0, 1, 1, 15))

    def test_shop_purchase_and_consumption_are_persistent(self):
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "game.sqlite3")
            store = bot.Store(path)
            store.record(9, True, 15)
            bought, _ = store.buy(9, "scent")
            self.assertTrue(bought)
            self.assertEqual(store.stats(9)[4], 5)
            self.assertEqual(store.inventory(9)["scent"], 1)
            self.assertTrue(store.consume(9, "scent"))
            self.assertEqual(bot.Store(path).inventory(9)["scent"], 0)

    def test_existing_stats_database_gets_coin_column(self):
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "old.sqlite3")
            database = sqlite3.connect(path)
            database.execute(
                "CREATE TABLE stats(user_id INTEGER PRIMARY KEY,wins INTEGER DEFAULT 0,"
                "losses INTEGER DEFAULT 0,streak INTEGER DEFAULT 0,best INTEGER DEFAULT 0)"
            )
            database.execute("INSERT INTO stats(user_id,wins) VALUES(1,3)")
            database.commit()
            database.close()
            store = bot.Store(path)
            self.assertEqual(store.stats(1), (3, 0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
