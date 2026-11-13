"""Extracted from tests/test_services.py.

    TestAuditProgress was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from core.logger import AppLogger
from core.models import ArtworkResult
from services.library_service import LibraryService
from services.organizer_service import OrganizerService


class TestAuditProgress(unittest.TestCase):
    """The audit pass is the slowest part of a scan - it fetches artwork for every game folder in the library over
    the network - and it reported nothing at all while doing it. The screen showed one line, "Refreshing artwork
    and Steam links for the library", and then sat there for minutes looking hung. These pin the progress channel
    that replaced it."""

    def _library(self, root, names):
        for name in names:
            game = root / "Adventure" / name
            game.mkdir(parents=True)
            (game / ".game-info.json").write_text('{"appid":"777","name":"%s"}' % name.split(" - ")[0])
        return root

    def _services(self, root):
        logger = AppLogger(root / "log.log")
        artwork = type("Artwork", (), {"download_assets": lambda *a, **k: ArtworkResult()})()
        return LibraryService(logger), artwork, OrganizerService(logger)

    def test_it_reports_the_total_before_it_starts(self):
        with TemporaryDirectory() as d:
            root = self._library(Path(d), ["A - 2020-01-01", "B - 2020-01-02", "C - 2020-01-03"])
            library, artwork, organizer = self._services(root)
            seen = []
            library.audit(root, artwork, organizer, None, on_progress=seen.append)
            self.assertEqual(seen[0]["stage"], "audit_plan")
            self.assertEqual(seen[0]["total"], 3, "the total has to be known up front for the bar to mean anything")

    def test_it_reports_every_folder_it_checks(self):
        with TemporaryDirectory() as d:
            root = self._library(Path(d), ["Alpha - 2020-01-01", "Beta - 2020-01-02"])
            library, artwork, organizer = self._services(root)
            seen = []
            library.audit(root, artwork, organizer, None, on_progress=seen.append)
            items = [event for event in seen if event.get("stage") == "audit_item"]
            self.assertEqual([event["index"] for event in items], [1, 2], "one line per folder, in order")
            self.assertTrue(all(event["total"] == 2 for event in items))
            self.assertIn("Alpha - 2020-01-01", items[0]["message"])
            self.assertTrue(any(event.get("state") == "done" for event in items), "no folder ever reported an outcome")

    def test_a_folder_with_no_appid_says_so_rather_than_going_quiet(self):
        # The usual reason a game shows no picture is that nothing could be looked up for it, and that is worth
        # saying out loud instead of letting the folder pass as 'up to date'.
        with TemporaryDirectory() as d:
            root = Path(d) / "lib"
            (root / "Adventure" / "Mystery Game - 2020-01-01").mkdir(parents=True)
            library, artwork, organizer = self._services(root)
            seen = []
            library.audit(root, artwork, organizer, None, on_progress=seen.append)
            items = [event for event in seen if event.get("stage") == "audit_item"]
            self.assertEqual(len(items), 1)
            self.assertIn("no Steam AppID", items[0]["message"])

    def test_a_download_outcome_is_relayed_but_a_start_is_not(self):
        # Relaying every 'started' report would put a second line per folder saying nothing on a library this size.
        with TemporaryDirectory() as d:
            root = self._library(Path(d), ["Alpha - 2020-01-01"])
            library, artwork, organizer = self._services(root)
            seen = []
            artwork.download_assets = (
                lambda *a, **k:
                [k["on_progress"]({"asset": "cover", "state": "start", "detail": ""}),
                 k["on_progress"]({"asset": "cover", "state": "downloaded", "detail": "42 KB"}),
                 k["on_progress"]({"asset": "hero", "state": "failed", "detail": "HTTPError"})][-1]
                or ArtworkResult())
            library.audit(root, artwork, organizer, None, on_progress=seen.append)
            messages = [event["message"] for event in seen if event.get("stage") == "audit_item"]
            self.assertTrue(any("downloaded" in message for message in messages), messages)
            self.assertTrue(any("failed" in message for message in messages), messages)
            self.assertFalse(any("start" in message for message in messages), messages)

    def test_a_broken_progress_sink_cannot_abort_the_pass(self):
        # The pass rewrites Steam links and artwork across the whole library; a display callback that throws must
        # never leave half the library done.
        with TemporaryDirectory() as d:
            root = self._library(Path(d), ["Alpha - 2020-01-01", "Beta - 2020-01-02", "Gamma - 2020-01-03"])
            library, artwork, organizer = self._services(root)

            def explode(event):
                raise RuntimeError("the UI went away")

            stats = library.audit(root, artwork, organizer, None, on_progress=explode)
            self.assertEqual(stats["checked"], 3, "a throwing callback aborted the audit")
            for name in ("Alpha - 2020-01-01", "Beta - 2020-01-02", "Gamma - 2020-01-03"):
                self.assertTrue((root / "Adventure" / name / "Open Steam Page.html").exists(), name)

    def test_the_audit_still_returns_its_counts_without_a_sink(self):
        with TemporaryDirectory() as d:
            root = self._library(Path(d), ["Alpha - 2020-01-01"])
            library, artwork, organizer = self._services(root)
            self.assertEqual(library.audit(root, artwork, organizer)["checked"], 1)
