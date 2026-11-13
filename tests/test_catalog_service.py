"""Extracted from tests/test_catalog_library.py.

    TestCatalogService was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
import pytest
import json
import re
import zipfile
from tempfile import TemporaryDirectory
from pathlib import Path
from core.logger import AppLogger
from tests.test_catalog_library import make_game
from services.catalog_service import CatalogService


class TestCatalogService(unittest.TestCase):
    _make_game = staticmethod(make_game)

    def test_finds_multi_word_banner_asset_name(self):
        # Asset filenames like "<game>_header_image.jpg" contain underscores in the asset name itself;
        # the banner lookup must match the whole suffix, not just the text after the last underscore.
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            service = CatalogService(AppLogger(root / "x.log"))
            prefix = service._asset_prefix(root / "Simulation" / "Alpha Forge - 2024-01-01", {"name": "Alpha Forge"})
            banner = service._find_banner(root / "Simulation" / "Alpha Forge - 2024-01-01", prefix)
            self.assertEqual(banner.name, "Alpha Forge_header_image.jpg")

    def test_card_markup_has_no_nested_anchor_tags(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            paths = CatalogService(AppLogger(root / "x.log")).generate(root)
            for path in paths:
                text = path.read_text()
                # The tag must be matched as "<a" followed by whitespace or ">", otherwise "<article" also
                # matches and the check silently reports a nested anchor that is not there.
                self.assertIsNone(re.search(r"<a[\s>][^>]*>[^<]*<a[\s>]", text))
                # And confirm no anchor ever contains another anchor, regardless of intervening markup.
                for outer in re.findall(r"<a[\s>][^>]*>(.*?)</a>", text, re.S):
                    self.assertIsNone(re.search(r"<a[\s>]", outer))

    def test_installer_archive_gets_pre_extraction_installer_badge(self):
        # A zip that sniffs as a repack installer (setup.exe + setup-1.bin) gets the pre-extraction badge, with no
        # need for 7z on the machine - the zipfile branch of archive_installer_kind is used.
        with TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Repacks" / "Beta Voyager [FitGirl Repack]"
            game.mkdir(parents=True)
            archive = game / "Beta Voyager [FitGirl Repack].zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("setup.exe", b"")
                handle.writestr("setup-1.bin", b"")
            (game / ".game-info.json").write_text(json.dumps({"appid": "100002", "name": "Beta Voyager", "description": "d", "release_date": "2020", "genres": ["Simulation"]}))
            paths = CatalogService(AppLogger(root / "x.log")).generate(root)
            html = " ".join(p.read_text(encoding="utf-8") for p in paths)
            self.assertIn("badge badge-install", html)
            self.assertIn("Installer</span>", html)
            # Pre-extraction only: no Unpacked/Needs-install state claim yet (match the span, not the CSS rule).
            self.assertNotIn('<span class="badge badge-done"', html)
            self.assertNotIn('<span class="badge badge-warn"', html)

    def test_long_description_with_html_entities_not_mangled_by_truncation(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root, description=('A & B <tag> "quoted" ' * 20))
            paths = CatalogService(AppLogger(root / "x.log")).generate(root)
            for path in paths:
                text = path.read_text()
                self.assertNotIn("&amp;lt;", text)
                self.assertIn("&lt;tag&gt;", text)

    def test_regenerating_deletes_previous_catalog_files(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            # Left behind by earlier releases, so the next run has to clear them out.
            (root / "Game Library (Steam Deck) - 2026-01-01 000000.html").write_text("old")
            (root / "Game Library (Windows) - 2026-01-01 000000.html").write_text("old")
            service = CatalogService(AppLogger(root / "x.log"))
            service.generate(root)
            service.generate(root)
            service.generate(root)
            # One catalog, one name, no platform variants and no accumulating timestamped copies.
            self.assertEqual(sorted(p.name for p in root.glob("*.html")), ["Game Library.html"])

    def test_the_catalog_is_one_portable_file_for_both_platforms(self):
        # It used to be written twice, once per platform, with the cards pointing at different URLs. A single
        # page cannot know which machine is reading it, so the card is the https store page (which opens in a
        # browser everywhere) and the Steam client is an explicit second action.
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            paths = CatalogService(AppLogger(root / "x.log")).generate(root)
            self.assertEqual([p.name for p in paths], ["Game Library.html"])
            text = paths[0].read_text()
            self.assertIn("https://store.steampowered.com/app/100001/", text)
            self.assertIn("steam://store/100001", text)
            self.assertNotIn("Steam Deck Edition", text)
            self.assertNotIn("Windows Edition", text)

    def test_a_chrome_launcher_is_written_only_when_no_browser_owns_html_files(self):
        # With no recorded text/html handler, double-clicking the catalog would not open a browser, so the
        # launcher is the fallback. Where a handler exists the catalog is enough, and an extra file in the
        # user's library root is pure clutter.
        #
        # It is a .url, not a .desktop. The original wrote a Linux desktop entry here, which Windows cannot
        # open at all - a launcher that exists but cannot be launched is worse than none, because it looks
        # like the job is handled. The .url is the format Windows actually opens, and it needs no command:
        # the shell resolves the URL through the same association check that produced it.
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            CatalogService(AppLogger(root / "x.log")).generate(root, write_launcher=True)
            launcher = root / "Open Game Library.url"
            self.assertTrue(launcher.is_file(), f"no launcher written; found {sorted(p.name for p in root.iterdir())}")
            text = launcher.read_text()
            self.assertIn("[InternetShortcut]", text)
            self.assertIn("file://", text)
            self.assertFalse((root / "Open Game Library.desktop").exists(), "the dead Linux launcher is still sitting beside the working one")
            from urllib.parse import unquote

            self.assertIn("Game Library.html", unquote(text))
            # The machine already knows what to do with an .html file, so there is nothing to launch.
            (root / "Open Game Library.url").unlink()
            CatalogService(AppLogger(root / "x.log")).generate(root, write_launcher=False)
            self.assertFalse((root / "Open Game Library.url").exists(), "a launcher was written when the machine already opens HTML")

    def test_the_old_launcher_is_removed_once_the_catalog_opens_on_its_own(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            old = root / "Open Game Library (Steam Deck).desktop"
            old.write_text("[Desktop Entry]\n")
            CatalogService(AppLogger(root / "x.log")).generate(root, write_launcher=True)
            self.assertFalse(old.exists(), "the superseded launcher was left in the library root")

    def test_catalog_open_folder_uses_the_protocol_handler_not_a_file_url(self):
        # A file:// directory link only shows a listing and is blocked in Chrome; it never opens the OS file
        # manager. The catalog uses the registered steamgameorganizer:// handler instead, which can hand a
        # folder path to Explorer. The user-facing label is "Open source" (library/archive folder).
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
            self.assertNotIn('href="file://', text)
            self.assertIn("steamgameorganizer://open-folder", text)
            self.assertIn('data-open-folder="steamgameorganizer://open-folder?', text)
            self.assertIn(">Open source<", text)

    def test_artwork_paths_are_relative_so_a_copied_library_still_shows_images(self):
        # Absolute artwork paths break the moment the Games folder is copied to another PC. Images and the
        # relative folder reference must both stay relative to the library root the catalog lives in.
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
            for reference in re.findall(r'(?:src="([^"]*)|url\(\'([^\']*))', text):
                value = next((v for v in reference if v), "")
                self.assertNotIn(str(root), value)
            self.assertIn('data-rel="Simulation/Alpha Forge - 2024-01-01"', text)

    def test_catalog_offers_a_copy_path_action(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
            self.assertIn("btn-copy", text)
            self.assertIn("data-copy=", text)
            self.assertIn(">Copy path<", text)
            # file:// pages are not a secure context, so the async clipboard API is unavailable there.
            self.assertIn("execCommand('copy')", text)

    def test_search_filter_has_a_haystack_for_every_card(self):
        # The client-side filter reads data-search; a card missing it would be unsearchable.
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root, genres=["Simulation", "Strategy"])
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
            cards = re.findall(r'<article class="card"[^>]*>', text)
            self.assertTrue(cards)
            self.assertTrue(all("data-search=" in card for card in cards))
            self.assertIn("Alpha Forge", text)

    def test_catalog_shows_the_archive_filename_present_in_the_folder(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            self._make_game(root)
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
            self.assertIn("Alpha Forge.zip", text)
