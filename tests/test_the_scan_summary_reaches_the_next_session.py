"""Extracted from tests/test_displayed_data.py.

    TheScanSummaryReachesTheNextSession was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import tempfile
import threading
import unittest
from pathlib import Path
from app.controller import AppController
from app.events import EventBus
from core.logger import AppLogger
from core.models import ArtworkResult
from core.models import ScanResult
from core.models import SteamMatch
from core.state import StateStore
from tests.test_helpers import _Jobs
from tests.test_helpers import _Services
from core.config import AppConfig


class TheScanSummaryReachesTheNextSession(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.config = AppConfig(self.base)
        self.logger = AppLogger(self.base / "x.log")

    def test_a_summary_round_trips(self):
        written = self.config.save_scan_summary({"archives": 176, "matched": 171, "artwork": 168})
        self.assertIsNotNone(written, "the summary was not written")
        read = self.config.load_scan_summary()
        self.assertEqual(read["archives"], 176)
        self.assertEqual(read["matched"], 171)
        self.assertIn("recorded_at", read, "the summary has no timestamp, so the panel cannot say how old it is")

    def test_the_config_lands_in_the_file_this_class_had_declared_and_never_used(self):
        """`state_file` was declared on AppConfig and read by nothing. Writing to it is what makes it a real
        declaration rather than a leftover."""
        self.config.save_scan_summary({"archives": 1})
        self.assertTrue(self.config.state_file.is_file(), f"nothing was written to {self.config.state_file}")

    def test_a_missing_empty_or_non_object_file_is_not_fatal(self):
        """Read during layout, before anything else has run, so every broken shape has to answer None."""
        self.assertIsNone(self.config.load_scan_summary(), "no summary yet should read as None")
        self.config.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.config.state_file.write_text("", encoding="utf-8")
        self.assertIsNone(self.config.load_scan_summary(), "an empty file should read as None")
        self.config.state_file.write_text("[]", encoding="utf-8")
        self.assertIsNone(self.config.load_scan_summary(), "valid JSON that is not an object should read as None")

    def test_a_scan_still_completes_when_there_is_no_config_to_record_into(self):
        """The regression this work introduced, kept as a test.

        `AppController` is constructed without a config by half the test suite. The first version of the summary
        called `self.config.save_scan_summary()` before handing the result on, so the resulting AttributeError
        meant `done` was never called and four scan tests sat waiting out a thirty-second timeout instead of
        failing on the line that was wrong.
        """
        controller = AppController(StateStore(), EventBus(), self.logger, _Services(), _Jobs())
        self.assertIsNone(controller.config, "this test is only meaningful while a config-less controller exists")

        finished = threading.Event()
        results = []
        controller._scan_ok(ScanResult(archives=[]), lambda r: (results.append(r), finished.set()))
        self.assertTrue(finished.wait(5), "the scan never handed its result on")
        self.assertEqual(1, len(results))

    def test_a_scan_summary_counts_artwork_the_way_the_screens_do(self):
        """`artwork_ready` counted the primary image alone until 9.20, and the summary would have reintroduced it.

        A game whose pictures arrived as asset URLs has no primary path, so a primary-only count reports zero
        for a game folder holding five images - the exact defect 9.20 fixed, in a new place.
        """

        class _Assets(ArtworkResult):
            """One game's artwork as the asset-URL case really produces it: no primary path, several assets.

            Subclasses the real result and overrides only `files()`. The previous stand-in defined `present()`
            by calling the unbound `ArtworkResult.present` on itself, which is defined in terms of `files()` -
            a method it did not have. So it raised AttributeError every time, and what this test was reporting
            was its own broken double rather than anything about artwork counting.
            """

            def __init__(self, *paths):
                super().__init__()
                self.path = paths[0] if paths else ""
                self.assets = {f"asset{n}": p for n, p in enumerate(paths[1:], 1)}

            def files(self):
                named = ([self.path] if self.path else []) + list(self.assets.values())
                return [Path(p) for p in named if p]

        class _UnreadableArtwork:
            """Artwork whose present() raises, standing in for a malformed sidecar or a pruned cache."""

            path = ""
            assets: dict = {}

            def present(self):
                raise OSError("artwork record is unreadable")

        class _Archive:
            def __init__(self, size, artwork):
                self.size = size
                self.artwork = artwork
                self.steam = SteamMatch(found=True)

        archives = [_Archive(100, _Assets("", "a.jpg", "b.jpg")), _Archive(50, _Assets("c.jpg"))]
        result = ScanResult(archives=archives)
        controller = AppController(StateStore(), EventBus(), self.logger, _Services(), _Jobs())
        controller.config = self.config
        controller._record_scan(result)
        read = self.config.load_scan_summary()
        self.assertEqual(read["archives"], 2)
        self.assertEqual(read["artwork"], 2, "a game whose artwork arrived as assets was counted as having none")
        self.assertEqual(read["total_bytes"], 150)

    def test_one_unreadable_artwork_entry_does_not_cost_the_whole_summary(self):
        """Every number is built in one expression, so an entry that raises used to take all of them.

        The summary is a convenience readout, so the worst one malformed artwork record may cost is that one
        game counted as having no picture. It must not also cost the archive count, the byte total and the
        match count, which is what happened: the generator aborted the dict literal that was building them.
        """

        class _Archive:
            def __init__(self, size, artwork, found=True):
                self.size = size
                self.artwork = artwork
                self.steam = SteamMatch(found=found)

        class _Broken:
            path = ""
            assets: dict = {}

            def present(self):
                raise OSError("artwork record is unreadable")

        class _Good:
            path = ""
            assets: dict = {}

            def present(self):
                return True

        result = ScanResult(archives=[_Archive(100, _Broken()), _Archive(50, _Good(), found=False)])
        controller = AppController(StateStore(), EventBus(), self.logger, _Services(), _Jobs())
        controller.config = self.config
        controller._record_scan(result)
        read = self.config.load_scan_summary()
        self.assertIsNotNone(read, "one bad artwork record stopped the summary being recorded at all")
        self.assertEqual(read["archives"], 2, "the archive count was lost to one bad entry")
        self.assertEqual(read["total_bytes"], 150, "the byte total was lost to one bad entry")
        self.assertEqual(read["unmatched"], 1, "the match counts were lost to one bad entry")
        self.assertEqual(read["artwork"], 1, "the broken entry should count as no artwork, and the good one as some")
