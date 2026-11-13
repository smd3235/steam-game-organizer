"""Extracted from tests/test_displayed_data.py.

    TheSourceSaysWhenItHasNoTags was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import tempfile
import unittest
from pathlib import Path
from core.logger import AppLogger
from tests.test_helpers import APPDETAILS_KEYS_55555
from tests.test_helpers import APPDETAILS_KEYS_66666
from services.steam_service import SteamService


class TheSourceSaysWhenItHasNoTags(unittest.TestCase):
    """A tag list that is empty because nothing could be fetched has to say so.

    Measured on this machine, every `.game-info.json` sidecar in the real library reads `"tags": []` and so does
    every entry in config/steam-matches.json - 165 of 165 and 344 of 344 - and the app reported nothing for
    nine releases. The parse was never the whole problem: appdetails has no `tags` field at all, so no reshaping
    of it could return one, and the v9.23 note described a fix that cannot work. Without a second data source
    (a key-gated one, or scraping the store page, both of which are a person's decision and not this test's) the
    honest end state is an empty list that is no longer silent.

    A warning nobody sees is a warning nobody acts on, so every assertion here reads the log file the app
    already writes rather than a stub of the logger - which is the same thing a person opens to find out.
    """

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.log = self.base / "steam.log"
        self.logger = AppLogger(self.log)
        self.service = SteamService(self.logger, mock=True, cache_file=self.base / "cache.json")

    def _payload(self, keys=APPDETAILS_KEYS_55555):
        """A payload with the real field set, holding the four fields `_build_match` has to be able to read."""
        details = dict.fromkeys(keys)
        details.update(name="Sir Beats Alot", steam_appid="55555", type="game", genres=[{"id": 1, "description": "Action"}], categories=[{"id": 1, "description": "Single-player"}], release_date={"coming_soon": False, "date": "Apr 21, 2016"}, short_description="A game.")
        return details

    def _logged(self):
        """Whatever the app wrote to its log, read as empty when it wrote nothing at all.

        `AppLogger` opens the file in append mode per line and swallows OSError, so a run that logs nothing
        leaves no file behind. Reading it unguarded raises FileNotFoundError, which reports a broken test
        instead of the silence under test - which is precisely the condition three of these assert.
        """
        return self.log.read_text(encoding="utf-8", errors="replace") if self.log.is_file() else ""

    def test_the_recorded_payload_is_the_one_that_was_measured_and_has_no_tag_field(self):
        """The finding everything else rests on, kept as data so it can be checked without the network.

        The counts are asserted as well as the absence, because a transcription that quietly dropped three keys
        would still satisfy an `assertNotIn('tags', ...)`. A test that cannot fail is worse than none.
        """
        self.assertEqual(36, len(APPDETAILS_KEYS_55555), "the recorded key set was transcribed wrongly")
        self.assertEqual(38, len(APPDETAILS_KEYS_66666), "the recorded key set was transcribed wrongly")
        for keys in (APPDETAILS_KEYS_55555, APPDETAILS_KEYS_66666):
            with self.subTest(tags_present="tags" in keys):
                self.assertNotIn("tags", keys, "appdetails does serve tags, so the source and this fix both change")

    def test_the_real_payload_shape_yields_no_tags_and_reports_it(self):
        """The defect, asserted on the shape the endpoint really returns.

        `tags: []` is the correct answer here - Steam sent no tags. What was wrong was that the app produced
        that same value, silently, from every game forever, which is indistinguishable from the bug it was.
        """
        match = self.service._build_match("55555", {"name": "Sir Beats Alot"}, self._payload())
        self.assertEqual([], match.tags, "the recorded payload carries no tags, so there is nothing to return")
        self.assertEqual(["Action"], match.genres, "genres come from the same payload and are unaffected")
        text = self._logged()
        self.assertIn("TAGS_UNAVAILABLE", text, "the payload has no tag field and nothing said so, so the empty list still means two things")
        self.assertIn("[WARN", text, "tags are unobtainable from this source and it was not worth a warning")
        self.assertIn("field=[tags]", text, "the report does not name the field that is missing")

    def test_a_lookup_reports_it_and_names_the_app_it_was_read_for(self):
        """Through the real path rather than the private helper, stubbed where the tests stub Steam.

        `_details` is the request boundary the rest of the Steam tests replace, so this exercises lookup's own
        reading of a payload rather than `_build_match` called directly.
        """
        self.service._details = lambda appid, ctx=None: self._payload()
        match = self.service._lookup_appid("55555", None)
        self.assertTrue(match.found, "the fixture failed to match, so nothing downstream ran")
        self.assertEqual([], match.tags)
        self.assertIn("appid=55555", self._logged(), "the report does not say which game it was read for")

    def test_a_run_of_games_reports_it_once_and_not_once_each(self):
        """A warning per game is 165 identical lines, and a log that says the same thing 165 times is a log
        nobody reads. Once per service says the same thing once and still says it."""
        for appid in ("1", "2", "3"):
            self.service._build_match(appid, {"name": "x"}, self._payload())
        self.assertEqual(1, self._logged().count("TAGS_UNAVAILABLE"), "the same missing field was reported once per game rather than once")

    def test_a_source_that_does_carry_tags_is_not_reported_as_unavailable(self):
        """The other half, and the half that decides whether the warning is worth having.

        A warning that fires when there is nothing to report is worse than no warning, because it is the thing
        a person opens the log to find. If Steam ever serves the field, this shape must be silent about it.
        """
        details = self._payload()
        details["tags"] = [{"id": 16689, "name": "Great Soundtrack"}, {"id": 1038, "name": "Immersive Sim"}]
        match = self.service._build_match("55555", {"name": "Sir Beats Alot"}, details)
        self.assertEqual(["Great Soundtrack", "Immersive Sim"], match.tags)
        text = self._logged()
        self.assertNotIn("TAGS_UNAVAILABLE", text, "this payload carried tags and was reported as carrying none")
        self.assertIn("TAGS_PRESENT", text, "tags arrived and nothing recorded that the source had them")
