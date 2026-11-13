"""The catalog's status file and its "already unpacked" badge.

Two claims the page now makes about the machine it was written on, and both have to be true: a card marked
Unpacked is a game Extract all would skip, and the banner at the top reports the run that actually happened.

Neither can be checked from the page. A document opened from `file://` has an opaque origin and cannot read
anything beside it - `fetch` and XHR are both refused - so the badge is decided when the page is written and
the banner arrives later through a sibling script. That is why these tests are about the generator and the
app rather than about JavaScript, and why the badge's predicate is asserted to be the planner's own rather
than a second implementation of it.

The one thing none of this can prove is that a browser honours a `<script src>` from `file://`. That is
verified by hand against a real headless browser, because the whole design rests on it and a string in a
generated page does not demonstrate it.
"""

from __future__ import annotations

import json
import tempfile
import unittest

import pytest
from pathlib import Path
from unittest import mock

from core.logger import AppLogger
from services import batch_extract_service, catalog_service
from services.catalog_service import CatalogService
from services.catalog_status import STATUS_GLOBAL, STATUS_NAME, already_extracted, empty_status, archive_has_changed_since_extraction, elapsed_text, status_from_run, write_status
from services.installer_detect import NEEDS_INSTALL_DIRNAME
from tests.test_batch_extract import _game

# TheStatusFileIsWrittenBesideTheCatalog extracted to tests\the_status_file_is_written_beside_the_catalog.py — see that module for its definition.
from tests.the_status_file_is_written_beside_the_catalog import TheStatusFileIsWrittenBesideTheCatalog
# TheUnpackedBadgeTellsTheTruth extracted to tests\the_unpacked_badge_tells_the_truth.py — see that module for its definition.
from tests.the_unpacked_badge_tells_the_truth import TheUnpackedBadgeTellsTheTruth
# TheBannerIsWiredToTheFileThatFeedsIt extracted to tests\the_banner_is_wired_to_the_file_that_feeds_it.py — see that module for its definition.
from tests.the_banner_is_wired_to_the_file_that_feeds_it import TheBannerIsWiredToTheFileThatFeedsIt
def _unpacked_card(text: str) -> int:
    """How many cards on the page carry the badge.

    Counted on the rendered class rather than on 'badge-done', which also appears in the stylesheet and in the
    script - a substring count would pass with the badge never drawn at all.
    """
    return text.count('class="badge badge-done"')

def _payload_of(path: Path) -> dict:
    """Read the status file back the way the browser would see it.

    Nothing in Python can execute the file, so the assignment is stripped and the remainder parsed. That
    checks two things at once: that the file really is a valid JavaScript object literal, and that what comes
    out is what went in - including for a category whose name is trying to be code, which is the case a
    hand-built string gets wrong.
    """
    text = path.read_text(encoding="utf-8")
    marker = f"window.{STATUS_GLOBAL} = "
    assert marker in text, f"the status file does not assign window.{STATUS_GLOBAL}: {text!r}"
    raw = text.split(marker, 1)[1].strip()
    return json.loads(raw[:-1] if raw.endswith(";") else raw)

def _assert_has(case, text: str, needle: str, message: str):
    """assertIn against a whole generated page, without printing the page when it fails.

    The container here is a 600 KB document, so an ordinary assertIn failure buries the one line that says what
    is missing under the entire catalogue. A failure should name the thing, not restate the thing.
    """
    case.assertTrue(needle in text, f"{message} (nothing on the page contains {needle!r})")

@pytest.mark.notkinter
class AStatusFileTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "Games"
        self.dest = self.base / "Out"
        self.dest.mkdir(parents=True)
        self.logger = AppLogger(self.base / "x.log")
        _game(self.root, "Idle", "Loop Miner")
        _game(self.root, "Idle", "Fellwood")
        _game(self.root, "RPG", "Deep Signal")

    def _generate(self, destination=None):
        folders = [destination] if destination else [self.dest]
        return CatalogService(self.logger, extract_folders=folders).generate(self.root, "")[0]

    def _page(self, destination=None) -> str:
        return self._generate(destination).read_text(encoding="utf-8")

    def _unpack(self, name: str, destination: Path):
        folder = destination / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "game.bin").write_bytes(b"x")

    def _unpack_installer(self, name: str, destination: Path):
        """A folder this version extracted as an installer: payload in the Needs Install folder at the
        destination root (the current layout)."""
        mark = destination / NEEDS_INSTALL_DIRNAME / name
        mark.mkdir(parents=True, exist_ok=True)
        (mark / "setup.exe").write_bytes(b"MZ")
        (mark / "setup-1.bin").write_bytes(b"x" * 1000)

class AFinishedRunIsWrittenOutForSomebodyToRead(unittest.TestCase):
    def test_a_duration_is_written_out_rather_than_counted_in_seconds(self):
        """The reader is deciding whether the run they just sat through was worth it.

        '7944' does not answer that; '2h 12m' does. Zero and sub-minute are checked too, because a run that
        failed immediately is exactly the one whose elapsed time matters most.
        """
        for seconds, expected in ((0, "0s"), (45, "45s"), (59, "59s"), (60, "1m"), (3599, "59m"), (3600, "1h 0m"), (7944, "2h 12m"), (86399, "23h 59m")):
            self.assertEqual(elapsed_text(seconds), expected, f"{seconds}s is not written as {expected}")

    def test_an_unusable_duration_does_not_raise(self):
        """These arrive off a job that may never have started, and a readout is not what may take down Tk."""
        for value in (None, "", "abc", object()):
            self.assertEqual(elapsed_text(value), "", f"{value!r} should format as nothing rather than raise")

class TheExtractMarkerDetectsStaleArchives(unittest.TestCase):
    """Unit tests for archive_has_changed_since_extraction.

    The predicate has to be conservative: a missing marker is never stale (old extractions made
    before the marker existed must not be falsely flagged), and a present marker is stale only when
    the archive's size or mtime actually changed.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.base = Path(self.dir.name)
        self.archive = self.base / "Game.zip"
        self.archive.write_bytes(b"original content")
        self.dest_folder = self.base / "Extracted" / "Game"
        self.dest_folder.mkdir(parents=True)
        (self.dest_folder / "game.bin").write_bytes(b"unpacked")

    def _write_marker(self, dest, size=None, mtime_ns=None):
        from services.catalog_status import extract_marker_path
        import json as _json

        marker = extract_marker_path(dest)
        info = {
            "archive_size": size if size is not None else 0,
            "archive_mtime_ns": mtime_ns if mtime_ns is not None else 0,
        }
        marker.write_text(_json.dumps(info), encoding="utf-8")

    def test_a_missing_marker_is_never_stale(self):
        """A folder without a marker is treated as never having been checked - never falsely flagged."""
        self.assertFalse(archive_has_changed_since_extraction(self.dest_folder, self.archive))

    def test_an_unchanged_archive_is_not_stale(self):
        """The marker records the archive's size and mtime; if they match, nothing changed."""
        stat = self.archive.stat()
        self._write_marker(self.dest_folder, size=stat.st_size, mtime_ns=stat.st_mtime_ns)
        self.assertFalse(archive_has_changed_since_extraction(self.dest_folder, self.archive))

    def test_a_changed_size_is_stale(self):
        """A different archive size means the file on disk is a different version."""
        self._write_marker(self.dest_folder, size=self.archive.stat().st_size - 1000, mtime_ns=self.archive.stat().st_mtime_ns)
        self.assertTrue(archive_has_changed_since_extraction(self.dest_folder, self.archive))

    def test_a_changed_mtime_is_stale(self):
        """Even with the same size, a different mtime means the archive was replaced."""
        self._write_marker(self.dest_folder, size=self.archive.stat().st_size, mtime_ns=self.archive.stat().st_mtime_ns + 1)
        self.assertTrue(archive_has_changed_since_extraction(self.dest_folder, self.archive))

    def test_a_missing_archive_is_not_stale(self):
        """A deleted archive means the marker can't be compared, so report 'not changed'."""
        stat = self.archive.stat()
        self._write_marker(self.dest_folder, size=stat.st_size, mtime_ns=stat.st_mtime_ns)
        self.assertFalse(archive_has_changed_since_extraction(self.dest_folder, self.base / "missing.zip"))

class TheStaleBadgeTellsTheTruth(AStatusFileTestCase):
    """The stale badge appears only when the archive changed since extraction, on an unpacked game."""

    def test_a_unchanged_archive_gets_no_stale_badge(self):
        """An unpacked game whose archive matches the marker is not flagged."""
        self._unpack("Loop Miner", self.dest)
        archive = self.root / "Idle" / "Loop Miner - 2024-01-01" / "Loop Miner.zip"
        stat = archive.stat()
        from services.catalog_status import extract_marker_path
        import json as _json

        marker = extract_marker_path(self.dest / "Loop Miner")
        marker.write_text(_json.dumps({"archive_size": stat.st_size, "archive_mtime_ns": stat.st_mtime_ns}), encoding="utf-8")
        page = self._page()
        self.assertNotIn('data-stale="1"', page, "an unchanged archive was flagged as stale")
        self.assertNotIn('class="badge badge-stale"', page, "a stale badge was drawn for a current archive")

    def test_a_changed_archive_gets_a_stale_badge(self):
        """When the archive's size differs from the marker, the card gets a stale cue."""
        self._unpack("Loop Miner", self.dest)
        archive = self.root / "Idle" / "Loop Miner - 2024-01-01" / "Loop Miner.zip"
        from services.catalog_status import extract_marker_path
        import json as _json

        marker = extract_marker_path(self.dest / "Loop Miner")
        marker.write_text(_json.dumps({"archive_size": archive.stat().st_size - 500, "archive_mtime_ns": archive.stat().st_mtime_ns}), encoding="utf-8")
        page = self._page()
        self.assertIn('data-stale="1"', page, "the stale archive was not flagged on its card")
        self.assertIn('class="badge badge-stale"', page, "the stale badge class is missing from the card")

    def test_a_stale_unpacked_game_keeps_the_unpacked_badge(self):
        """Stale and unpacked are separate facts: the game is extracted but the archive moved on."""
        self._unpack("Loop Miner", self.dest)
        archive = self.root / "Idle" / "Loop Miner - 2024-01-01" / "Loop Miner.zip"
        from services.catalog_status import extract_marker_path
        import json as _json

        marker = extract_marker_path(self.dest / "Loop Miner")
        marker.write_text(_json.dumps({"archive_size": archive.stat().st_size - 500, "archive_mtime_ns": archive.stat().st_mtime_ns}), encoding="utf-8")
        page = self._page()
        self.assertEqual(_unpacked_card(page), 1, "the unpacked badge was lost when the archive went stale")
        self.assertIn('data-stale="1"', page, "the stale flag was not set alongside the unpacked badge")

    def test_a_hide_extracted_button_is_present(self):
        """The hide-extracted stat button exists when there are unpacked games to hide."""
        self._unpack("Loop Miner", self.dest)
        page = self._page()
        self.assertIn('data-filter="hide_extracted"', page, "the hide-extracted filter button is missing from the page")

if __name__ == "__main__":
    unittest.main()
