"""Extracted from tests/test_services.py.

    TestStoreApiInsteadOfScrapedHtml was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from core.exceptions import CancellationError
from core.logger import AppLogger
from core.models import SteamMatch
from services.steam_service import SteamService


class TestStoreApiInsteadOfScrapedHtml(unittest.TestCase):
    """The eight checks that used to be made against a scraped store page, now made against the JSON API.

    There is no HTML handler left to test - the service reads storesearch and appdetails instead of parsing a
    page - but what those tests were *for* still stands, and it is what these pin. A transport failure has to
    arrive as a diagnosable reason rather than as a crash or a bare "no match". A cancelled lookup has to stay
    cancelled instead of being laundered into a miss. And a cache that is corrupt or half-written must not be
    able to poison the next scan."""

    def service(self, root, **kwargs):
        return SteamService(AppLogger(Path(root) / "steam.log"), **kwargs)

    def test_a_store_http_error_is_reported_as_such_rather_than_as_no_match(self):
        # "No Steam Store search result" and "Steam answered 404" send an organizer down different paths, and only
        # the second is worth retrying, so the code has to survive to the log.
        from urllib.error import HTTPError
        from services.steam_service import _SHARED_POOL

        with TemporaryDirectory() as d:
            service = self.service(d)

            def fake_request(method, url, headers=None, body=None):
                raise HTTPError("https://store.steampowered.com", 404, "Not Found", {}, None)

            with patch.object(_SHARED_POOL, "request", side_effect=fake_request):
                result = service._lookup_store("Any Game", None)
            self.assertFalse(result.found)
            self.assertIn("Steam Store HTTP 404", result.reason)

    def test_a_transport_failure_is_reported_by_its_kind(self):
        # No network at all is ordinary - a Deck asleep, a captive portal - and the exception type is the only
        # thing in the log that says whether another attempt could ever help.
        from urllib.error import URLError
        from services.steam_service import _SHARED_POOL

        with TemporaryDirectory() as d:
            service = self.service(d)

            def fake_request(method, url, headers=None, body=None):
                raise URLError("name resolution failed")

            with patch.object(_SHARED_POOL, "request", side_effect=fake_request):
                result = service._lookup_store("Any Game", None)
            self.assertFalse(result.found)
            self.assertIn("Steam Store lookup failed: URLError", result.reason)

    def test_appdetails_failing_is_a_miss_and_not_an_exception(self):
        # The AppID is known but the name behind it is not. Raising here would abandon an entire scan over the one
        # game whose store page happened to be unavailable when the rest were fine.
        from urllib.error import URLError
        from services.steam_service import _SHARED_POOL

        with TemporaryDirectory() as d:
            service = self.service(d)

            def fake_request(method, url, headers=None, body=None):
                raise URLError("offline")

            with patch.object(_SHARED_POOL, "request", side_effect=fake_request):
                result = service._lookup_appid("55555", None)
            self.assertFalse(result.found)
            self.assertEqual(result.reason, "Steam AppID details unavailable")

    def test_a_cancelled_lookup_is_not_laundered_into_a_miss(self):
        # A cancel is not a search that found nothing. Swallowing it would leave the game unmatched, and every
        # later scan would report it as a game Steam does not have rather than one the user stopped looking for.
        from services.steam_service import _SHARED_POOL

        with TemporaryDirectory() as d:
            service = self.service(d)

            def fake_request(method, url, headers=None, body=None):
                raise CancellationError("cancelled")

            with patch.object(_SHARED_POOL, "request", side_effect=fake_request):
                with self.assertRaises(CancellationError):
                    service.lookup("Any Game")
                with self.assertRaises(CancellationError):
                    service._details("55555", None)

    def test_a_corrupt_cache_file_leaves_the_cache_empty_rather_than_raising(self):
        # The cache is written to a temp file and replaced precisely so it cannot be half-written, but a file
        # truncated by a kill during that rename is still a file this has to open on the next run.
        with TemporaryDirectory() as d:
            cache = Path(d) / "steam-matches.json"
            cache.write_text('{"sirbeatsalot": {"found": tru')
            service = self.service(d, cache_file=cache)
            self.assertEqual(service.cache, {})
            service._lookup_store = lambda title, ctx: SteamMatch(found=True, appid="55555", name="Sir Beats Alot")
            self.assertTrue(service.lookup("Sir Beats Alot").found, "a corrupt cache file stopped the lookup entirely")

    def test_cache_rows_that_are_not_a_usable_match_are_discarded(self):
        # A row that cannot be trusted is worse than no row at all: it would then be served from cache indefinitely,
        # and a non-numeric appid is a broken store link rather than a slow one.
        import json

        with TemporaryDirectory() as d:
            cache = Path(d) / "steam-matches.json"
            cache.write_text(
                json.dumps({
                    "kept": {"found": True, "appid": "123", "name": "Example"},
                    "unfound": {"found": False, "appid": "123", "name": "Example"},
                    "notanid": {"found": True, "appid": "abc", "name": "Example"},
                    "noname": {"found": True, "appid": "123", "name": ""},
                    "notadict": "Example"}))
            service = self.service(d, cache_file=cache)
            self.assertEqual(sorted(service.cache), ["kept"])

    def test_an_empty_title_never_scores_as_a_match(self):
        # An empty name reaching the scorer means a store row that carried none. Scoring zero against nothing is
        # how such a row ends up winning a ranked list of real games.
        with TemporaryDirectory() as d:
            service = self.service(d)
            self.assertEqual(service._score("", "Sir Beats Alot"), 0.0)
            self.assertEqual(service._score("Sir Beats Alot", ""), 0.0)
            chosen, score = service._choose([{"id": "1", "name": ""}], "Sir Beats Alot")
            self.assertIsNone(chosen, "an unnamed store row was accepted as the match")

    def test_a_numeral_beyond_the_conversion_table_is_refused(self):
        # The tables stop at 39, the highest numeral with a single-character form. Past that the swap has to decline
        # rather than invent a numeral the store has never been indexed under.
        with TemporaryDirectory() as d:
            service = self.service(d)
            self.assertEqual(service._to_roman(40), "")
            self.assertEqual(service._from_roman("XL"), 0)
            self.assertEqual(service._swap_trailing_numeral("Some Game 40"), "")

    def test_a_short_trailing_abbreviation_does_not_sink_a_match(self):
        # Scene release groups abbreviate subtitles: "Voyager AtU" for "Across the Unknown",
        # "AiO" for "All in One". The Steam search still finds the game via a prefix variant,
        # but the scorer compares the full query. A lone short token the rest of the query
        # already matches on should not reject the right game.
        with TemporaryDirectory() as d:
            service = self.service(d)
            name = "Star Horizon Voyager - Across the Unknown"
            self.assertGreater(service._score("Star Horizon Voyager AtU", name), 0.78, "abbreviation token should not sink a match the search already found")
            chosen, score = service._choose([{"id": "2643390", "name": name}], "Star Horizon Voyager AtU")
            self.assertIsNotNone(chosen, "the right game was ranked out by an abbreviation token")

    def test_a_short_trailing_abbreviation_still_rejects_unrelated_games(self):
        # The abbreviation tolerance only fires when dropping it leaves a subset of the name
        # tokens. A genuinely different game must still be rejected.
        with TemporaryDirectory() as d:
            service = self.service(d)
            self.assertLess(service._score("Some Game AiO", "Different Title"), 0.78, "unrelated games should not be rescued by the abbreviation rule")
