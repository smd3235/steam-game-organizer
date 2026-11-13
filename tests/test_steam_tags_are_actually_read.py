"""Extracted from tests/test_displayed_data.py.

    SteamTagsAreActuallyRead was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import tempfile
import unittest
from pathlib import Path
from core.logger import AppLogger
from services.steam_service import SteamService


class SteamTagsAreActuallyRead(unittest.TestCase):
    """Both tag shapes are still parsed, although the store API sends neither.

    Kept, because they are what a working source would arrive in and the parse is what reads them. What these
    cannot test is whether Steam sends them at all - the fixtures here assert the parser, not the source. The
    class that covers the source is the one below.
    """

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.logger = AppLogger(self.base / "x.log")
        self.service = SteamService(self.logger, mock=True, cache_file=self.base / "cache.json")

    def _build(self, details):
        return self.service._build_match("1", {"name": "x"}, details)

    def test_tags_arrive_as_a_list_of_name_objects(self):
        """A list of {"id", "name"} objects, which is the shape a working source would send."""
        match = self._build({"tags": [{"id": 16689, "name": "Great Soundtrack"}, {"id": 1038, "name": "Immersive Sim"}]})
        self.assertEqual(match.tags, ["Great Soundtrack", "Immersive Sim"])

    def test_tags_arrive_as_an_id_keyed_object(self):
        """The other documented shape.

        Without this the rule reads one shape and quietly returns nothing for the other - and an empty tag list
        is indistinguishable from a game that has no tags, so nothing downstream would ever report the miss.
        """
        match = self._build({"tags": {16689: "Great Soundtrack", 1038: "Immersive Sim"}})
        self.assertEqual(match.tags, ["Great Soundtrack", "Immersive Sim"])

    def test_a_missing_or_odd_tag_field_is_not_an_error(self):
        for details in ({}, {"tags": None}, {"tags": "Great Soundtrack"}, {"tags": [{"id": 1}]}):
            with self.subTest(details=details):
                self.assertEqual(self._build(details).tags, [])

    def test_a_tag_that_is_only_whitespace_is_dropped(self):
        """Whitespace-only tags would render as a blank chip on the card."""
        self.assertEqual(self._build({"tags": [{"name": "  "}, {"name": " Co-op "}]}).tags, ["Co-op"])

    def test_tags_come_from_the_details_and_not_the_search_hit(self):
        """Tags are read from the payload in hand rather than from the search hit.

        The search response carries an id, a name, a price and a thumbnail, so a tag read from it is nothing for
        every game, always. This was read as the defect in 9.23 and the read was moved here; it turned out to
        be no defect at all, because this payload has no tags either. The assertion is still the right one -
        the fields come from the one response that describes the game rather than from the one that merely
        matched its name - and it no longer claims to be the fix.
        """
        match = self.service._build_match("42", {"name": "Loop Miner", "id": 42}, {"tags": [{"id": 1, "name": "Idle"}]})
        self.assertEqual(match.tags, ["Idle"], "tags are read from the search result, which carries none")
