"""Extracted from tests/test_catalog_library.py.

    TestGamesWithoutASteamMatch was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
import json
import re
from tempfile import TemporaryDirectory
from pathlib import Path
from core.logger import AppLogger
from services.catalog_service import CatalogService


class TestGamesWithoutASteamMatch(unittest.TestCase):
    """A game with no AppID still belongs on the shelf.

    `_read_game` ended with `if not appid: return None`, so any game folder whose `.game-info.json` had no
    AppID - or that had no `.game-info.json` at all - was dropped before it was ever rendered. That is a
    routine outcome for this library, not an edge case: the scan's own audit row reports "no Steam AppID" as
    one of the normal per-game results, and the folder is still sitting in the library either way.

    The cost was that the page quietly under-reported the library. A 10-game library rendered 8 cards, the
    hero said "8 games", and a category made up entirely of unmatched games disappeared from the rail
    altogether, because the category is only kept when it still has games in it. Nothing on the page said a
    game was missing; it simply was not there.

    The AppID is only needed for the two Steam actions. A game without one still has a name, artwork, an
    archive and a folder, so it still gets a card - just without the store link and the client link, and with
    a note saying why they are missing.
    """

    def setUp(self):
        parent = TemporaryDirectory()
        self.addCleanup(parent.cleanup)
        self.root = Path(parent.name) / "Games"
        fixtures = [
            ("Matched", "Simulation", {"appid": "100001", "name": "Alpha Forge"}, True),
            ("No Appid", "Simulation", {"appid": "", "name": "Hollow Signal"}, True),
            ("Absent Key", "Adventure", {"name": "Quiet Harbor"}, False),
            ("No Metadata", "Adventure", None, False),
        ]
        for folder, category, metadata, art in fixtures:
            game = self.root / category / f"{folder} - 2024-01-01"
            game.mkdir(parents=True)
            (game / f"{folder}.zip").write_text("x")
            if metadata is not None:
                (game / ".game-info.json").write_text(json.dumps(metadata))
            if art:
                (game / f"{folder}_grid.jpg").write_bytes(b"\xff\xd8\xff\xd9" + b"0" * 400)
        self.text = CatalogService(AppLogger(self.root / "x.log")).generate(self.root)[0].read_text()

    def test_every_game_folder_on_disk_gets_a_card(self):
        cards = self.text.count('<article class="card"')
        self.assertEqual(cards, 4, f"{cards} cards for 4 game folders - a game with no Steam match was dropped")

    def test_the_hero_reports_the_number_of_games_that_are_actually_there(self):
        self.assertIn('<p class="tagline">4 games across', self.text, "the hero under-reports the library, so the missing games are invisible")
        self.assertIn('<span class="stat-value">4</span><span class="stat-label">Games</span>', self.text)

    def test_a_game_with_no_appid_says_so_instead_of_looking_broken(self):
        # On the badge, not on the phrase. The plain card link carries a title tooltip that also says "No Steam
        # match", so asserting the words alone was satisfied by the tooltip and never reached the badge at all.
        self.assertIn('<span class="badge badge-muted">No Steam match</span>', self.text, "a card with no store link has to show why, or it reads as a broken card")

    def test_no_card_points_at_a_store_page_with_no_appid_in_it(self):
        for url in re.findall(r'href="(https://store\.steampowered\.com[^"]*)"', self.text):
            self.assertRegex(url, r"/app/\d+/", f"a store link with no AppID in it: {url}")
        for url in re.findall(r'href="(steam://[^"]*)"', self.text):
            self.assertRegex(url, r"steam://store/\d+", f"a steam:// link with no AppID in it: {url}")

    def test_the_matched_game_keeps_both_steam_actions(self):
        # Dropping the AppID everywhere would "fix" the count by breaking the one card that can be opened.
        self.assertIn("https://store.steampowered.com/app/100001/", self.text)
        self.assertIn("steam://store/100001", self.text)

    def test_a_whitespace_only_title_falls_back_to_the_folder_name(self):
        # `"   "` is truthy, so `metadata.get('name') or <folder name>` kept it and rendered a card whose heading
        # is three spaces. The card exists but says nothing about which game it is, which on a shelf of 160 is the
        # same as the card being broken. A name that is only whitespace is no name.
        parent = TemporaryDirectory()
        self.addCleanup(parent.cleanup)
        root = Path(parent.name) / "Games"
        game = root / "Adventure" / "Quiet Harbor - 2024-01-01"
        game.mkdir(parents=True)
        (game / "Quiet Harbor.zip").write_text("x")
        (game / ".game-info.json").write_text(json.dumps({"appid": "1", "name": "   "}))
        text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        headings = re.findall(r"<h3>([^<]*)</h3>", text)
        self.assertEqual(len(headings), 1, "the game lost its card")
        self.assertEqual(headings[0].strip(), "Quiet Harbor", f"a whitespace-only title rendered a blank card heading: {headings!r}")
