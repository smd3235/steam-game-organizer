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


def _labels(widget) -> list:
    found = []
    for child in widget.winfo_children():
        try:
            found.append(str(child.cget("text")))
        except tk.TclError:
            pass
        found.extend(_labels(child))
    return found


# require_tk() and close_root() now live in tests/tk_support.py, next to TK_AVAILABLE. They were defined
# here and re-derived in two other modules, which is how three copies drifted. Keeping them in one place means
# the rule - fail loudly rather than skip, and cancel pending timers before destroying a root - has exactly
# one place to be wrong.


import pytest


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


class ReviewPaneShowsArchiveSize(unittest.TestCase):
    def setUp(self):
        require_tk(self)
        self.root = tk.Tk()
        self.app = sandbox_app(self, self.root)
        self.view = self.app.window.views["review"]
        self.app.window.show("review")
        self.root.update()

    def tearDown(self):
        # The review and organize views keep a self-rescheduling ticker, as do the drain loop and the window
        # clock. close_root() cancels everything still pending before tearing the window down, so Tk does not
        # print 'invalid command name ..._tick' to stderr - noise that trains you to ignore this suite's
        # output, and it lands in exactly the place a real failing test would print.
        close_root(self.root)

    def _archive(self, path: Path, size: int) -> GameArchive:
        title = normalize_name(path.name)
        return GameArchive(path, title, title, identity_key(title), path.suffix.lower(), (), size=size)

    def test_selected_archive_shows_its_size_in_human_units(self):
        archive = self._archive(Path("Games/Deep Signal/Deep_Signal_v4.7z"), 5 * 1024 * 1024)
        self.view.archives = [archive]
        self.view.select(archive)
        self.root.update()
        text = " ".join(_labels(self.view.meta))
        self.assertIn("ARCHIVE SIZE", text)
        self.assertIn(human_size(5 * 1024 * 1024), text)

    def test_several_copies_report_the_combined_size(self):
        """A library holding a .zip and a .7z of one game is where wasted space hides, so the pane states the
        total across copies rather than only the selected one."""
        first = self._archive(Path("Games/H/H.zip"), 1024 * 1024)
        second = self._archive(Path("Games/H/H.7z"), 2 * 1024 * 1024)
        self.view.archives = [first, second]
        self.view.select(first)
        self.root.update()
        text = " ".join(_labels(self.view.meta))
        self.assertIn("2 copies", text)
        self.assertIn(human_size(3 * 1024 * 1024), text)

    def test_subtitle_carries_the_size_so_it_is_visible_without_scrolling(self):
        archive = self._archive(Path("Games/Q/Quiet Harbor.zip"), 700 * 1024)
        self.view.archives = [archive]
        self.view.select(archive)
        self.root.update()
        self.assertIn(human_size(700 * 1024), str(self.view.subtitle.cget("text")))

    def test_missing_size_is_reported_as_unknown_rather_than_zero(self):
        archive = self._archive(Path("Games/Q/Quiet Harbor.zip"), 0)
        self.view.archives = [archive]
        self.view.select(archive)
        self.root.update()
        self.assertIn("size unknown", str(self.view.subtitle.cget("text")))
        self.assertNotIn("0 B", str(self.view.subtitle.cget("text")))


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


class WorkerUpdatesReachTheUiThread(unittest.TestCase):
    """Scan, verification and organization all report progress from worker threads. Tk is not thread-safe,
    so the reporting path must never call into it directly."""

    def setUp(self):
        self.root = tk.Tk()
        self.app = sandbox_app(self, self.root)

    def tearDown(self):
        try:
            self.app.shutdown()
        except Exception:
            pass
        close_root(self.root)

    def test_a_worker_thread_dispatch_does_not_run_the_callback_inline(self):
        reached = threading.Event()

        def worker():
            self.app._dispatch(reached.set)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(5)
        self.assertFalse(reached.is_set(), "a worker-thread dispatch ran the callback on the worker")
        for _ in range(10):
            self.root.update()
            if reached.is_set():
                break
        self.assertTrue(reached.is_set(), "a queued update never reached the Tk thread")

    def test_the_tk_thread_still_updates_inline(self):
        seen = []
        self.app._dispatch(lambda: seen.append(1))
        self.assertEqual(seen, [1], "a main-thread dispatch stopped running inline")

    def test_the_drain_is_bounded_so_a_flood_cannot_starve_the_event_loop(self):
        count = []

        def worker():
            for index in range(600):
                self.app._dispatch(lambda i=index: count.append(i))

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(5)
        # Driving one drain directly is the only way to observe the boundary: root.update() re-fires timers
        # that fall due while it is running, so several drains can legitimately happen inside one call.
        self.app._pump()
        self.assertEqual(len(count), 200, "a single drain did not stop at its bound")
        for _ in range(30):
            self.root.update()
        self.assertEqual(len(count), 600, "queued updates were dropped rather than drained")

    def test_one_bad_callback_does_not_stop_the_drain_loop(self):
        """The drain reschedules itself at the end, so an exception escaping a callback used to stop every
        later UI update for the rest of the session: the worker carried on and the screen froze."""
        reached = []

        def worker():
            self.app._dispatch(lambda: (_ for _ in ()).throw(ValueError("boom")))
            self.app._dispatch(lambda: reached.append(1))

        threading.Thread(target=worker, daemon=True).start()
        for _ in range(10):
            self.root.update()
        self.assertEqual(reached, [1], "a failing callback stopped the drain loop")

    def test_shutdown_stops_the_drain_loop(self):
        self.app.shutdown()
        count = []
        worker = threading.Thread(target=lambda: self.app._dispatch(lambda: count.append(1)))
        worker.start()
        worker.join(5)
        for _ in range(5):
            self.root.update()
        self.assertEqual(count, [], "a queued update ran after shutdown")


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


class ArtworkArrivingAsAssetsIsStillArtwork(unittest.TestCase):
    """A game whose artwork arrived as assets rather than as one primary image has to be reported as having artwork.

    Found by running the real pipeline over a real archive - Glow Stick Samurai.7z, the smallest in a 176-archive,
    244 GB library. Steam's API serves this game's pictures as asset URLs (`header_image`, `capsule_image`,
    `background`, ...) and the primary image cache came back empty, so `ArtworkResult.path` was None while
    `ArtworkResult.assets` held five real files. OrganizerService.move() copies every one of them into the game
    folder, so the run had put five images on disk and DoneView reported "0 artwork copied".

    Both screens read only `.path`. A user reading either one concludes artwork failed for a game whose folder is
    full of artwork, which is the outcome that sends someone re-downloading images that are already there.
    """

    def setUp(self):
        require_tk(self)
        self.root = tk.Tk()
        self.addCleanup(close_root, self.root)
        self.assets_dir = Path(mkdtemp())
        self.addCleanup(shutil.rmtree, self.assets_dir, ignore_errors=True)

    def _asset(self, name: str) -> Path:
        path = self.assets_dir / name
        path.write_bytes(b"\xff\xd8\xff\xe0" + b"jpeg-ish")
        return path

    def _game(self, primary=None, assets=None):
        from core.models import ArtworkResult, OrganizationDecision

        return GameArchive(
            path=Path("Games/Idle/Glow Stick Samurai - 2026-09-03/Glow Stick Samurai.7z"),
            display_name="Glow Stick Samurai",
            normalized_title="Glow Stick Samurai",
            identity_key="glowsticksamurai",
            extension=".7z",
            steam=SteamMatch(found=True, appid="77777", name="Glow Stick Samurai"),
            artwork=ArtworkResult(status="ready", path=primary, assets=assets or {}),
            decision=OrganizationDecision(category="Idle", accepted=True),
            conversion=ConversionResult(status="converted"),
        )

    def test_the_done_summary_counts_assets_when_there_is_no_primary_image(self):
        from ui.done_view import DoneView

        view = DoneView(self.root, lambda: None)
        game = self._game(assets={"header_image": self._asset("header_image.jpg")})
        view.show([game])
        self.root.update()
        summary = str(view.summary.cget("text"))
        self.assertIn("1 artwork copied", summary, f"a game with a downloaded asset and no primary image is reported as having no artwork: {summary!r}")

    def test_a_game_with_no_artwork_at_all_is_still_reported_as_having_none(self):
        """The other half. Counting assets must not turn the total into a number that is simply always >= 1."""
        from ui.done_view import DoneView

        view = DoneView(self.root, lambda: None)
        view.show([self._game()])
        self.root.update()
        self.assertIn("0 artwork copied", str(view.summary.cget("text")))

    def test_an_asset_that_is_not_on_disk_is_not_counted(self):
        """OrganizerService only copies assets whose path is a real file, so a path left over from a pruned
        cache would be counted here as artwork the run never wrote."""
        from ui.done_view import DoneView

        view = DoneView(self.root, lambda: None)
        game = self._game(assets={"header_image": self.assets_dir / "gone.jpg"})
        view.show([game])
        self.root.update()
        self.assertIn("0 artwork copied", str(view.summary.cget("text")))

    def test_the_organize_plan_does_not_say_artwork_unavailable_when_assets_are_present(self):
        """The same wrong answer on the screen shown *before* the run, which is where a user decides whether to
        bother running it at all."""
        from ui.organize_view import OrganizeView

        state = StateStore()
        game = self._game(assets={"header_image": self._asset("header_image.jpg")})
        state.update(scan_result=ScanResult(archives=[game]))

        preview = type("P", (), {"preview": staticmethod(lambda archives, root: {})})
        controller = type("C", (), {})()
        controller.services = type("S", (), {"organizer": preview})()
        controller.config = type("Cfg", (), {"library_root": Path("Games"), "sync_to_appdata": lambda self: None})()

        view = OrganizeView(self.root, controller, state, lambda *a: None)
        view.refresh()
        self.root.update()
        text = str(view.list.get("1.0", "end"))
        self.assertIn("artwork included", text, f"the plan calls a game with downloaded artwork 'artwork unavailable': {text!r}")


if __name__ == "__main__":
    unittest.main()
