"""Extracted from tests/test_library_summary.py.

    TestShape was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
import pytest
from pathlib import Path
from tests.test_library_summary import archive
from tests.test_library_summary import game
from tests.test_library_summary import service
from tempfile import TemporaryDirectory


class TestShape(unittest.TestCase):
    def _summary(self, build):
        with TemporaryDirectory() as d:
            root = Path(d)
            build(root)
            catalog = service(root)
            catalog.generate(root)
            return catalog.library_summary()

    def test_categories_are_ranked_by_game_count_then_name(self):
        """Both halves of the sort key are asserted, with a deliberate tie: `Zeta` and `Alpha` hold five each,
        and a sort on the count alone leaves them in whatever order the directory walk happened to produce."""

        def build(root):
            for name in ("Delta", "Gamma", "Beta"):
                archive(game(root, name, f"{name} Game"), "a.zip", 10)
            for index in range(5):
                archive(game(root, "Zeta", f"Z {index}"), "a.zip", 10)
            for index in range(5):
                archive(game(root, "Alpha", f"A {index}"), "a.zip", 10)

        summary = self._summary(build)
        self.assertEqual([row[0] for row in summary.categories], ["Alpha", "Zeta", "Beta", "Delta", "Gamma"])
        self.assertEqual(summary.total_games, 13)

    def test_archive_bytes_are_summed_per_category_and_not_invented(self):
        """Exact byte totals, not a rounded human_size: 1024+2048+4096 is 7168, which no plausible wrong
        implementation lands on by accident. The fourth game has no archive and is not in the catalog at
        all - it is the folder left behind when the game was re-categorised, carrying the sidecar and
        the artwork the organizer wrote. It contributes nothing to the bytes and nothing to the count."""

        def build(root):
            archive(game(root, "Simulation", "One"), "a.zip", 1024)
            archive(game(root, "Simulation", "Two"), "b.zip", 2048)
            archive(game(root, "Strategy", "Three"), "c.zip", 4096)
            game(root, "Strategy", "Four")

        summary = self._summary(build)
        self.assertEqual(summary.categories, (("Simulation", 2, 3072), ("Strategy", 1, 4096)))
        self.assertEqual(summary.total_games, 3)

    def test_genre_placement_counts_only_genres_a_game_actually_carries(self):
        """The two games with no genres at all must add no keys, so `Indie` counts two in Simulation and one in
        Strategy rather than five in total."""

        def build(root):
            archive(game(root, "Simulation", "One", genres=["Indie", "Simulation"]), "a.zip", 1)
            archive(game(root, "Simulation", "Two", genres=["Indie"]), "a.zip", 1)
            archive(game(root, "Strategy", "Three", genres=["Indie"]), "a.zip", 1)
            archive(game(root, "Strategy", "Four", genres=[]), "a.zip", 1)
            archive(game(root, "Strategy", "Five", genres=None), "a.zip", 1)

        summary = self._summary(build)
        self.assertEqual(summary.genre_placement, {"Indie": {"Simulation": 2, "Strategy": 1}, "Simulation": {"Simulation": 1}})

    def test_the_genre_helper_ranks_by_most_games_first(self):
        def build(root):
            for index in range(3):
                archive(game(root, "Puzzle", f"P {index}", genres=["Casual"]), "a.zip", 1)
            archive(game(root, "RPG", "R", genres=["Casual", "RPG"]), "a.zip", 1)
            archive(game(root, "Strategy", "S", genres=["RPG"]), "a.zip", 1)

        summary = self._summary(build)
        self.assertEqual(summary.categories_for_genres(["Casual"]), (("Puzzle", 3), ("RPG", 1)))
        self.assertEqual(summary.categories_for_genres(["No Such Genre"]), (), "a genre nobody has is an answer, not an error")
        self.assertEqual(summary.categories_for_genres(["RPG"]), (("RPG", 1), ("Strategy", 1)))
        self.assertEqual(summary.categories_for_genres(["Casual", "RPG"]),
                         (("Puzzle", 3), ("RPG", 2), ("Strategy", 1)),
                         "RPG scores 2 not 1: its one game carries both genres asked about, which is the "
                         "documented sum. A display wanting per-genre numbers reads genre_placement.")
        self.assertEqual(summary.categories_for_genres(None), ())
        self.assertEqual(summary.categories_for_genres(["  rpg  "]), (("RPG", 1), ("Strategy", 1)), "a Steam genre string arrives padded and must still match")

    def test_a_developer_needs_two_games_to_be_a_precedent(self):
        """One game is not a precedent. Asserted both ways on one library: Bewolba is in, Allerton (a single
        game) is not, and the pair that is in is listed under its casefolded key in game-name order."""

        def build(root):
            for name, folder in (("Tower of Babel", "Puzzle"), ("Crying Suns", "Strategy"), ("Stoneshard", "RPG")):
                archive(game(root, folder, name, developer="Bewolba Studios"), "a.zip", 1)
            archive(game(root, "Idle", "Airborne Kingdom", developer="Allerton Apps"), "a.zip", 1)

        summary = self._summary(build)
        self.assertEqual(sorted(summary.developer_placement), ["bewolba studios"], "a single-game developer must not appear, and the key must be casefolded")
        self.assertEqual(summary.precedent_for("Bewolba Studios"),
                         (("Crying Suns", "Strategy"), ("Stoneshard", "RPG"), ("Tower of Babel", "Puzzle")),
                         "listed by game name, not by the order the categories were walked")
        self.assertEqual(summary.precedent_for("  bewolba studios "), summary.precedent_for("BEWOLBA STUDIOS"), "a Steam developer string arrives padded and inconsistently cased")
        for single in ("Allerton Apps", "", "Nobody At All"):
            self.assertEqual(summary.precedent_for(single), (), f"{single!r} produced a precedent")

    def test_a_folder_of_loose_archives_is_not_a_category(self):
        """`Larage Games` on the real library is a directory of .rar/.zip files, not a category of game folders.

        `_collect`'s `if games:` guard is what keeps it out, and the index is built from that dict rather than
        from the directory listing - so a tally that walked the root itself would list a phantom category
        holding zero games while the game count went on quietly ignoring them.
        """
        with TemporaryDirectory() as d:
            root = Path(d)
            archive(game(root, "Simulation", "Alpha Forge"), "a.zip", 100)
            loose = root / "Larage Games"
            loose.mkdir()
            (loose / "Some Pack v1.rar").write_bytes(b"Rar!" + b"0" * 50)
            (loose / "Another Pack.zip").write_bytes(b"PK" + b"0" * 50)
            catalog = service(root)
            catalog.generate(root)
            summary = catalog.library_summary()
            self.assertEqual([row[0] for row in summary.categories], ["Simulation"])
            self.assertEqual(summary.total_games, 1)
            self.assertNotIn("Larage Games", repr(summary))
