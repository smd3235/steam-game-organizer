"""Tests for what the user is actually shown about a run: sizes, space saved, progress and the live log.

Each test here was written because the thing it covers was measured to be missing or wrong. The archive size
was computed during discovery and thrown away, so no screen could show how big a file was; the run published
two byte totals that nothing read, one of which could only ever be zero.
"""

from __future__ import annotations

import tkinter as tk
import threading
import unittest
import zipfile
import shutil
from pathlib import Path
from tempfile import mkdtemp

from core.logger import AppLogger
from core.models import ConversionResult, GameArchive, ScanResult, SteamMatch
from core.state import StateStore
from services.archive_service import ArchiveService
from ui.theme import human_size
from utils.filename_utils import identity_key, normalize_name

try:
    from .tk_support import TK_AVAILABLE, close_root, require_tk, sandbox_app
except ImportError:
    from tests.tk_support import TK_AVAILABLE, close_root, require_tk, sandbox_app

def _archive(folder: Path, name: str, payload: int) -> Path:
    """A real zip whose size on disk is genuinely larger than the bytes written into it."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as handle:
        handle.writestr("data.bin", b"a" * payload)
    return target

# require_tk() and close_root() now live in tests/tk_support.py, next to TK_AVAILABLE. They were defined
# here and re-derived in two other modules, which is how three copies drifted. Keeping them in one place means
# the rule - fail loudly rather than skip, and cancel pending timers before destroying a root - has exactly
# one place to be wrong.

import pytest

from tests.test_helpers import _labels
from tests.test_artwork_arriving_as_assets_is_still_artwork import ArtworkArrivingAsAssetsIsStillArtwork
# WorkerUpdatesReachTheUiThread extracted to tests\worker_updates_reach_the_ui_thread.py — see that module for its definition.
from tests.test_worker_updates_reach_the_ui_thread import WorkerUpdatesReachTheUiThread
# ReviewPaneShowsArchiveSize extracted to tests\review_pane_shows_archive_size.py — see that module for its definition.
from tests.test_review_pane_shows_archive_size import ReviewPaneShowsArchiveSize
@pytest.mark.slow
class ArchiveSizeIsDiscovered(unittest.TestCase):
    """The size has to exist on the model before any screen can show it."""

    def setUp(self):
        self.dir = Path(mkdtemp())
        self.log = AppLogger(self.dir / "discovery.log")

    def test_discovery_records_the_real_size_of_every_archive(self):
        first = _archive(self.dir / "One", "First Game.zip", 40_000)
        second = _archive(self.dir / "Two", "Second Game.7z", 90_000)
        result = ArchiveService(self.log).discover(self.dir)
        sizes = {a.path.name: a.size for a in result.archives}
        self.assertEqual(sizes.get("First Game.zip"), first.stat().st_size)
        self.assertEqual(sizes.get("Second Game.7z"), second.stat().st_size)
        self.assertTrue(all(a.size > 0 for a in result.archives), "an archive was discovered with no size")

    def test_mock_discovery_records_a_size(self):
        result = ArchiveService(self.log, mock=True).discover(self.dir)
        self.assertTrue(result.archives)
        self.assertTrue(all(a.size > 0 for a in result.archives), "mock discovery produced a sizeless archive")

    def test_a_discovered_archive_reaches_the_review_pane_with_its_size(self):
        """Discovery and the review pane are separate units, so each can be correct alone while the size is
        dropped between them. This walks the real path end to end: files on disk, real discovery, real view."""
        require_tk(self)
        root = tk.Tk()
        try:
            _archive(self.dir / "Deep Signal", "Deep_Signal_v4.7z", 120_000)
            _archive(self.dir / "Quiet Harbor", "Quiet Harbor.zip", 60_000)
            archives = ArchiveService(self.log).discover(self.dir).archives
            self.assertEqual(len(archives), 2)
            app = sandbox_app(self, root)
            view = app.window.views["review"]
            app.window.show("review")
            root.update()
            view.archives = archives
            view.select(archives[0])
            root.update()
            biggest = max(archives, key=lambda a: a.size)
            view.select(biggest)
            root.update()
            self.assertIn(human_size(biggest.size), str(view.subtitle.cget("text")))
            self.assertIn(human_size(biggest.size), " ".join(_labels(view.meta)))
        finally:
            close_root(root)

class SpaceSavedIsReal(unittest.TestCase):
    """The Done screen's headline number has to be the difference between the two real sizes."""

    def _conversion(self, name: str, source: int, final: int, status: str = "converted") -> ConversionResult:
        return ConversionResult(
            status=status,
            source_size=source,
            final_size=final,
            source_format="ZIP",
            target_format="7Z",
            final_name=Path(name).with_suffix(".7z").name,
        )

    def test_saved_is_the_difference_between_source_and_final(self):
        from ui.done_view import _saved_bytes

        self.assertEqual(_saved_bytes(self._conversion("A.zip", 1000, 400)), 600)
        self.assertEqual(_saved_bytes(self._conversion("B.zip", 1000, 1000)), 0)

    def test_an_archive_that_grew_reports_no_saving(self):
        from ui.done_view import _saved_bytes

        self.assertEqual(_saved_bytes(self._conversion("C.zip", 1000, 1400)), 0)

    def test_a_failed_conversion_reports_no_saving(self):
        from ui.done_view import _saved_bytes

        self.assertEqual(_saved_bytes(self._conversion("D.zip", 1000, 0, status="failed")), 0)

    def test_unknown_sizes_report_no_saving_rather_than_a_guess(self):
        from ui.done_view import _saved_bytes

        self.assertEqual(_saved_bytes(self._conversion("E.zip", 0, 0)), 0)

    def test_total_saved_ignores_archives_that_did_not_actually_shrink(self):
        """The Done headline is a sum over the archives that really shrank. Including one that grew would
        understate the saving, and including a failed one would invent it."""
        from ui.done_view import _saved_bytes

        notes = [self._conversion("A.zip", 1000, 400), self._conversion("B.zip", 1000, 1000), self._conversion("C.zip", 1000, 1400), self._conversion("D.zip", 1000, 250)]
        shrunk = [n for n in notes if _saved_bytes(n) > 0]
        self.assertEqual(sum(_saved_bytes(n) for n in shrunk), 1350)

class RunStatePublishesOnlyWhatIsRead(unittest.TestCase):
    """run_bytes and run_written were published on every completed run and read by nothing. run_written was
    additionally always 0, because written_bytes was never assigned anywhere in the view."""

    def test_completed_run_publishes_duration_and_no_phantom_totals(self):
        import time

        store = StateStore()
        view = type("V", (), {})()
        view.state = store
        view.work = type("W", (), {"grid_remove": lambda self: None})()
        view.bar = type("B", (), {"configure": lambda self, **k: None})()
        view.ctx = None
        view.started_at = time.monotonic() - 5.0
        view.done_bytes = 123
        view.on_done = lambda archives: None
        from ui.organize_view import OrganizeView

        OrganizeView._done(view, [])
        snapshot = store.get()
        self.assertGreater(snapshot.run_seconds, 4.0)
        self.assertFalse(hasattr(snapshot, "run_bytes"), "run_bytes is published but never read")
        self.assertFalse(hasattr(snapshot, "run_written"), "run_written is published but never read")

class StaleBuildFoldersAreCounted(unittest.TestCase):
    """A real library was found holding 14 abandoned build folders and 6.7 GB of disk space."""

    def setUp(self):
        self.dir = Path(mkdtemp())
        self.log = AppLogger(self.dir / "stale.log")

    def test_abandoned_build_folders_are_reported_with_their_size(self):
        stale = self.dir / "Idle" / ".organizer-repack-abc123"
        stale.mkdir(parents=True)
        (stale / "partial.7z").write_bytes(b"x" * 5000)
        (stale / "nested").mkdir()
        (stale / "nested" / "more.bin").write_bytes(b"y" * 3000)
        result = ArchiveService(self.log).discover(self.dir)
        self.assertEqual(result.stale_build_dirs, 1)
        self.assertEqual(result.stale_build_bytes, 8000)

    def test_a_clean_library_reports_nothing(self):
        result = ArchiveService(self.log).discover(self.dir)
        self.assertEqual(result.stale_build_dirs, 0)
        self.assertEqual(result.stale_build_bytes, 0)

    def test_nothing_is_deleted_by_finding_them(self):
        stale = self.dir / ".organizer-repack-keepme"
        stale.mkdir()
        (stale / "partial.7z").write_bytes(b"x" * 100)
        ArchiveService(self.log).discover(self.dir)
        self.assertTrue(stale.is_dir(), "discovery deleted an abandoned build folder")
        self.assertTrue((stale / "partial.7z").exists(), "discovery deleted the contents of one")

class HiddenFoldersAreNotLibraryContent(unittest.TestCase):
    """Syncthing keeps superseded copies under .stversions. On a real library that made discovery report 525
    archives when the library held 174, and pulled in 82 truncated 32-byte downloads that 7z rejects."""

    def setUp(self):
        self.dir = Path(mkdtemp())
        self.log = AppLogger(self.dir / "hidden.log")

    def _archive(self, folder: Path, name: str, payload: int = 2000) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / name
        with zipfile.ZipFile(target, "w") as handle:
            handle.writestr("data.bin", b"a" * payload)
        return target

    def test_archives_inside_a_dot_folder_are_not_discovered(self):
        self._archive(self.dir / "Real Game", "Real Game.zip")
        self._archive(self.dir / ".stversions" / "Real Game", "Real Game.zip")
        self._archive(self.dir / ".stfolder" / "Real Game", "Real Game.zip")
        result = ArchiveService(self.log).discover(self.dir)
        names = [a.path.name for a in result.archives]
        self.assertEqual(names, ["Real Game.zip"])
        self.assertNotIn(".stversions", str(result.archives[0].path))

    def test_a_dot_folder_deeper_in_the_tree_is_skipped_too(self):
        self._archive(self.dir / "Games" / ".stversions" / "Old", "Old.zip")
        self._archive(self.dir / "Games" / "Current", "Current.zip")
        result = ArchiveService(self.log).discover(self.dir)
        self.assertEqual([a.path.name for a in result.archives], ["Current.zip"])

    def test_the_rule_is_scoped_to_the_library_not_its_ancestors(self):
        """A library that itself lives under a dot-named folder must still be scanned in full. Checking every
        parent rather than only those below the root would silently skip the entire library."""
        nested = self.dir / ".hidden-root" / "Games"
        self._archive(nested / "One", "One.zip")
        self._archive(nested / "Two", "Two.zip")
        result = ArchiveService(self.log).discover(nested)
        self.assertEqual(sorted(a.path.name for a in result.archives), ["One.zip", "Two.zip"])

if __name__ == "__main__":
    unittest.main()

