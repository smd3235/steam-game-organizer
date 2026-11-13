"""Extracted from tests/test_catalog_library.py.

    TestCatalogBanners was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
import pytest
import json
from tempfile import TemporaryDirectory
from pathlib import Path
from core.logger import AppLogger
from services.catalog_service import CatalogService
from services.banner_art import banner_svg
from services.banner_art import banner_data_uri
from core.constants import DEFAULT_CATEGORIES


class TestCatalogBanners(unittest.TestCase):
    """The generated banner art and the per-banner jump-to-top control."""

    def test_every_category_gets_a_unique_deterministic_banner(self):
        # Two categories rendering identical art defeats the point of per-category banners, and art that
        # changes between regenerations makes the catalog look unstable. Both are checked over the real
        # category list plus the ad-hoc names users add themselves.
        names = list(DEFAULT_CATEGORIES) + ["Indie", "Simulation", "Early Access"]
        rendered = {banner_svg(name): name for name in names}
        self.assertEqual(len(rendered), len(set(names)), "two categories produced identical banner art")
        self.assertEqual(banner_svg("Adventure"), banner_svg("Adventure"), "banner art is not deterministic")
        self.assertNotEqual(banner_svg("Adventure"), banner_svg("Indie"))

    def test_banner_data_uri_is_embedded_safely_in_css(self):
        uri = banner_data_uri("Adventure")
        self.assertTrue(uri.startswith("data:image/svg+xml,"))
        # An unencoded '#' would terminate the url() early and drop the whole background image.
        self.assertNotIn("#", uri.split(",", 1)[1])
        self.assertNotIn('"', uri.split(",", 1)[1])
        self.assertNotIn(" ", uri.split(",", 1)[1])

    def test_every_category_header_has_a_jump_to_top_button(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            for folder, appid in (("Adventure", "11"), ("Strategy", "22"), ("RPG", "33")):
                game = root / folder / f"Game {appid} - 2020-01-01"
                game.mkdir(parents=True)
                (game / ".game-info.json").write_text(json.dumps({"appid": appid, "name": f"Game {appid}", "genres": ["G"]}))
                (game / f"Game {appid}.7z").write_bytes(b"7z\xbc\xaf\x27\x1c")
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        self.assertEqual(text.count('class="jump-top"'), 3, "each category banner needs its own jump-to-top button")
        self.assertIn("querySelectorAll('.jump-top')", text, "jump-to-top buttons are not wired up")
        self.assertIn("toTopBtn.addEventListener('click',toTop)", text, "floating top button is not wired up")
        self.assertEqual(text.count('id="to-top"'), 1)

    def test_categories_without_art_still_get_a_banner(self):
        # No game in these folders has artwork, which used to produce a flat empty header.
        with TemporaryDirectory() as d:
            root = Path(d)
            for folder, appid in (("Adventure", "11"), ("Strategy", "22")):
                game = root / folder / f"Bare {appid} - 2020-01-01"
                game.mkdir(parents=True)
                (game / ".game-info.json").write_text(json.dumps({"appid": appid, "name": f"Bare {appid}"}))
                (game / f"Bare {appid}.7z").write_bytes(b"7z\xbc\xaf\x27\x1c")
            text = CatalogService(AppLogger(root / "x.log")).generate(root)[0].read_text()
        self.assertEqual(text.count("--gen:url("), 2, "artless categories lost their generated banner")
        self.assertEqual(text.count("--real:url("), 0, "no real art exists in this library")
