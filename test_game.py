import unittest

import bot


class GameTests(unittest.TestCase):
    def test_deck_has_36_unique_cards(self):
        self.assertEqual(len(bot.ALL_CARDS), 36)
        self.assertEqual(len(set(bot.ALL_CARDS)), 36)

    def test_initial_hands_have_seven_clickable_cards(self):
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


if __name__ == "__main__":
    unittest.main()
