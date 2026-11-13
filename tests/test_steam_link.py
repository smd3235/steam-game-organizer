"""Tests for the Steam link writer.

Extracted from tests/test_services.py to keep each test module focused on one area:
the one-HTML-link-per-game scheme and removal of legacy .desktop/.url files.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.logger import AppLogger
from services.organizer_service import OrganizerService


class TestSteamLink(unittest.TestCase):
    """One shortcut per game, in the one format every platform opens. A .desktop only launches on Linux and a
    Windows .url only on Windows, so the pair that shipped before meant two files where each platform ignored
    half of them, and no cleanup of the old names."""

    def test_one_html_link_is_written_and_both_old_files_are_removed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Adventure" / "Linked Game - 2024-01-01"
            game.mkdir(parents=True)
            # Left over from the previous scheme, including an older naming round.
            (game / "Open Steam Page (Steam Deck).desktop").write_text("old deck")
            (game / "Open Steam Page (Windows).url").write_text("old windows")
            (game / "Open Steam Page.desktop").write_text("oldest")
            service = OrganizerService(AppLogger(root / "log.log"))
            link = service.write_steam_links(game, "4242", "Linked Game")
            self.assertEqual(link.name, "Open Steam Page.html", "the shortcut is not a single portable html file")
            self.assertTrue(link.is_file())
            body = link.read_text(encoding="utf-8")
            # A meta-refresh opens it in whatever the default browser is on SteamOS or Windows, and the
            # visible link is the fallback if the browser blocks the automatic redirect.
            self.assertIn('http-equiv="refresh"', body)
            self.assertIn("https://store.steampowered.com/app/4242/", body)
            self.assertIn('<a href="https://store.steampowered.com/app/4242/">', body)
            self.assertNotIn("\n-2024-01-01", body, "the folder date leaked into the page title")
            for legacy in service.LEGACY_LINK_NAMES:
                self.assertFalse((game / legacy).exists(), f"the old {legacy} was left behind")

    def test_no_appid_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Adventure" / "No Id - 2024-01-01"
            game.mkdir(parents=True)
            self.assertIsNone(OrganizerService(AppLogger(root / "log.log")).write_steam_links(game, None))
