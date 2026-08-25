import unittest

import bot


class GameTests(unittest.TestCase):
    def test_deck_has_36_unique_cards(self):
        self.assertEqual(len(bot.ALL_CARDS), 36)
        self.assertEqual(len(set(bot.ALL_CARDS)), 36)

    def test_every_card_is_a_button(self):
        game = bot.new_game(1)
        table = next(block for block in bot.game_view(game)["blocks"] if block["type"] == "table")
        self.assertEqual(len(table["cells"]), 4)
        self.assertTrue(all(len(row) == 9 for row in table["cells"]))
        self.assertEqual(sum(len(row) for row in table["cells"]), 36)

    def test_cards_are_conserved(self):
        game = bot.new_game(1)
        total = len(game["deck"]) + len(game["player"]) + len(game["dog"])
        total += 4 * (len(game["player_books"]) + len(game["dog_books"]))
        self.assertEqual(total, 36)


if __name__ == "__main__":
    unittest.main()
