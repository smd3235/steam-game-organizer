"""Data the app has, and whether any of it reaches the screen.

Every item here is the same shape of defect, found by auditing the models against the views rather than by
reading the code for bugs: a field is fetched, stored, and never shown. Steam's tags were the clearest case -
the store *search* response does not carry them, and neither, as it turns out, does the appdetails payload the
9.23 fix moved them to, so every game in the library had an empty list and nothing downstream could have shown
one. Confidence was on the review card as words in grey body text, which is present but not legible as the
warning it is.

The tests are grouped by that theme rather than by the file the code lives in, because the interesting
assertion is usually about a chain: a field filled in one service, written to a sidecar, and read by a
generator. Asserting any single link of that chain would pass with the rest broken.
"""

from __future__ import annotations

import json
import re
import tempfile
import threading
import unittest
from pathlib import Path

from app.controller import AppController
from app.events import EventBus
from core.logger import AppLogger
from core.models import ArtworkResult, ScanResult, SteamMatch
from core.state import StateStore
from core.config import AppConfig
from services.catalog_service import CatalogService
from services.steam_service import SteamService
from ui.palette import GREEN, ORANGE
from ui.widgets.game_card import GameCard
from utils.filename_utils import identity_key

# TheScanSummaryReachesTheNextSession extracted to tests\the_scan_summary_reaches_the_next_session.py — see that module for its definition.
from tests.the_scan_summary_reaches_the_next_session import TheScanSummaryReachesTheNextSession
# TheCatalogShowsAndSearchesTags extracted to tests\the_catalog_shows_and_searches_tags.py — see that module for its definition.
from tests.the_catalog_shows_and_searches_tags import TheCatalogShowsAndSearchesTags
# TheSourceSaysWhenItHasNoTags extracted to tests\the_source_says_when_it_has_no_tags.py — see that module for its definition.
from tests.the_source_says_when_it_has_no_tags import TheSourceSaysWhenItHasNoTags
# SteamTagsAreActuallyRead extracted to tests\steam_tags_are_actually_read.py — see that module for its definition.
from tests.steam_tags_are_actually_read import SteamTagsAreActuallyRead

# The keys appdetails actually returned, recorded rather than re-measured, so the claim at the top of
# services/steam_service.py can be checked without a network call. One live request each on 2026-10-04:
#   https://store.steampowered.com/api/appdetails?appids=55555&cc=us&l=en   -> 36 keys, success=True
#   https://store.steampowered.com/api/appdetails?appids=66666&cc=us&l=en  -> 38 keys, success=True
# The key set is the whole of what matters: which fields are absent. Both responses carry genres, categories,
# content_descriptors, ratings, supported_languages, metacritic, screenshots, movies and package_groups, and
# neither carries tags - Steam's store tags are community-curated and rendered into the store page's HTML.
APPDETAILS_KEYS_55555 = frozenset(
    {
        "about_the_game",
        "background",
        "background_raw",
        "capsule_image",
        "capsule_imagev5",
        "categories",
        "content_descriptors",
        "controller_support",
        "detailed_description",
        "developers",
        "dlc",
        "genres",
        "header_image",
        "is_free",
        "linux_requirements",
        "mac_requirements",
        "metacritic",
        "movies",
        "name",
        "package_groups",
        "packages",
        "pc_requirements",
        "platforms",
        "price_overview",
        "publishers",
        "ratings",
        "recommendations",
        "release_date",
        "required_age",
        "screenshots",
        "short_description",
        "steam_appid",
        "support_info",
        "supported_languages",
        "type",
        "website",
    }
)
APPDETAILS_KEYS_66666 = APPDETAILS_KEYS_55555 | {"achievements", "legal_notice"}


class _Services:
    organizer = None
    rollback = None

class _Jobs:
    def submit(self, *a, **k):
        raise AssertionError("the summary path must not submit work")

class MatchConfidenceIsVisibleAsAWarning(unittest.TestCase):
    """A doubtful match has to look doubtful, not merely be described in passing."""

    def setUp(self):
        try:
            import tkinter as tk
        except ImportError as exc:
            raise AssertionError(f"tkinter is required and is missing: {exc}") from exc
        self.tk = tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def _card(self, confidence, score=0.0):
        archive = _ArchiveForCard(confidence, score)
        return GameCard(self.root, archive, lambda a: None)

    def _colours(self, card):
        """The pill's own colours, read back off the widget rather than off the source."""
        return card.conf.cget("bg"), card.conf.cget("fg")

    def test_a_high_confidence_match_is_green(self):
        card = self._card("High", 0.98)
        background, _ = self._colours(card)
        self.assertEqual(background, GREEN, "a High confidence match is not distinguished from a doubtful one")
        self.assertIn("High", card.conf.cget("text"))
        self.assertIn("0.98", card.conf.cget("text"), "the score is not shown, so 'High' cannot be judged against 'Medium'")

    def test_a_medium_confidence_match_is_not_green(self):
        """The whole point of the pill. In grey text it was present and invisible as a warning."""
        card = self._card("Medium", 0.71)
        background, _ = self._colours(card)
        self.assertNotEqual(background, GREEN, "a match the app called Medium confidence looks certain")

    def test_an_unset_confidence_is_not_green_either(self):
        card = self._card("", 0.0)
        background, _ = self._colours(card)
        self.assertNotEqual(background, GREEN, "a match with no confidence reads as certain")
        self.assertIn("Unscored", card.conf.cget("text"))

    def test_an_unmatched_game_shows_no_confidence_at_all(self):
        """There is nothing to be confident about, and a pill would imply there was."""
        card = GameCard(self.root, _ArchiveForCard("", 0.0, found=False), lambda a: None)
        self.assertEqual(card.conf.cget("text"), "", "an unmatched game is shown a confidence pill")

    def test_a_skipped_game_is_also_left_without_the_pill(self):
        archive = _ArchiveForCard("Medium", 0.7)
        archive.decision.skipped = True
        card = GameCard(self.root, archive, lambda a: None)
        self.assertEqual(card.badge.cget("text"), "SKIPPED")
        self.assertEqual(card.conf.cget("text"), "", "a skipped archive shows a confidence pill beside its SKIPPED badge")
        self.assertNotEqual(card.conf.cget("bg"), ORANGE, "an emptied pill kept the warning fill, so a skipped game still looks doubtful")

# GREEN is imported from ui.palette rather than written out here. It was a literal in this file, holding a
# value from the generated catalog's CSS (`--good`) rather than the Tkinter theme's green, so it had drifted
# from the colour the widget actually paints and the assertion could only ever fail. palette.py is kept
# tkinter-free for exactly this reason: the audit, the theme and this test all read one definition, and a
# colour cannot pass review here while differing from what the UI draws.

class _Decision:
    category = "Idle"
    changed_from_suggestion = False
    skipped = False

class _ArchiveForCard:
    """The three attributes GameCard reads. Everything else it touches is defensive."""

    def __init__(self, confidence, score, found=True):
        self.steam = SteamMatch(found=found, name="Loop Miner" if found else "", appid="1", confidence=confidence, score=score)
        self.decision = _Decision()
        self.display_name = "Loop Miner"
        self.extension = ".zip"
        self.path = Path("Loop Miner.zip")
        self.identity_key = identity_key("Loop Miner")

if __name__ == "__main__":
    unittest.main()
