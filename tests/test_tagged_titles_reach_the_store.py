"""Extracted from tests/test_services.py.

    TestTaggedTitlesReachTheStore was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from core.logger import AppLogger
from services.steam_service import SteamService


class TestTaggedTitlesReachTheStore(unittest.TestCase):
    """The tag stripper and the Steam lookup failed as a pair, and only fixing the stripper is not enough.

    normalize_name() produced the clean title, but _lookup_store() built its search query from the raw folder
    name, so the clean title was never asked for. The variants it did try were right-truncations of the tagged
    string - "Nebula Attracts-Steam RIP com", "Nebula Attracts-Steam RIP", "Nebula Attracts-Steam" - and every one of
    them is a query the Steam Store has no answer to. These pin the wiring, so a future change that goes back to
    querying the raw name fails here rather than in a library scan."""

    QUERIES = {"Nebula Attracts-Steam RIP com": "Nebula Attracts", "Nebula Nights-Steam RIP com": "Nebula Nights", "Stellar.Squirrel-SteamRIP.com": "Stellar Squirrel"}

    def test_the_query_variants_include_the_clean_title(self):
        with TemporaryDirectory() as d:
            service = SteamService(AppLogger(Path(d) / "steam.log"))
            from utils.filename_utils import normalize_name

            for tagged, clean in self.QUERIES.items():
                self.assertIn(clean, service._query_variants(normalize_name(tagged), tagged, None), tagged)

    def test_the_lookup_sends_the_clean_title_to_the_store(self):
        with TemporaryDirectory() as d:
            service = SteamService(AppLogger(Path(d) / "steam.log"))
            asked = []

            def fake(url, ctx=None):
                asked.append(url)
                return {"items": [{"id": 1, "name": "Unrelated"}]}

            service._request_json = fake
            service._details = lambda appid, ctx=None: {"name": "Unrelated"}
            service._lookup_store("Nebula Attracts-Steam RIP com", None)
            # The first variant is the raw name, which is harmless; the clean one has to be in there too.
            self.assertTrue(any("Nebula+Attracts" in url or "Nebula%20Attracts" in url for url in asked), asked[:3])
