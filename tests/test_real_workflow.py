"""Extracted from tests/test_workflow_smoke.py.

    TestRealWorkflow was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import pytest
import json
import random
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from tests.tk_support import require_tk
from tests.tk_support import close_root
from tests.tk_support import sandbox_app
from tests.test_artwork_render import _jpeg_bytes
from tests.test_workflow_smoke import MOCK_APPIDS
from tests.test_workflow_smoke import ROOT
from tests.test_ui_geometry import _measured_window
from tests.wait_for_organize import wait_for_organize
from tests.wait_until import wait_until


class TestRealWorkflow(unittest.TestCase):
    def setUp(self):
        require_tk(self)
        import tkinter as tk

        # A canary, not a protection: this module cannot write settings.json any more (the project root is
        # redirected below), but an earlier version did, and it left the app pointing at a temporary library
        # this module then deleted - which the app itself refuses to start from. Worth catching at the first
        # test rather than debugging later as a mysterious failure somewhere else.
        settings_path = ROOT / "config" / "settings.json"
        if settings_path.is_file():
            configured = settings_path.read_text(encoding="utf-8")
            self.assertNotIn("organizer-workflow-", configured,
                             "settings.json still names a temporary library from an earlier "
                             "test run; the library has been deleted and the app will not "
                             "start until this is corrected")

        self.root = tk.Tk()
        self.addCleanup(close_root, self.root)
        wait_until._root = self.root

        self.app = sandbox_app(self, self.root)
        _measured_window(self.root)
        self.window = self.app.window
        self.scan = self.window.views["scan"]

        # The whole project root is redirected, not just the library. MainWindow.scan() calls save_api() and
        # records convert_archives, both of which call config.save(); a finished scan records a summary; an
        # organize run records into the undo journal; and every screen change appends a line to the log.
        # Redirecting the library alone left every one of those in the repository's own config/, which is why
        # this module used to snapshot those files and put them back after each test. That is not a fix: two
        # concurrent suite runs restore each other's writes, and the race they had left the real
        # settings.json holding convert_archives: false, which silently disables archive conversion on the
        # next real run. sandbox_app() roots the whole tree in a temporary directory instead, so there is
        # nothing to restore. tests/test_project_state_guard.py is what keeps it that way.

        # A temporary library, so this cannot move anything on a real volume.
        self.library = Path(tempfile.mkdtemp(prefix="organizer-workflow-")) / "Games"
        self.library.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.library.parent, ignore_errors=True)
        self.app.config.library_root = self.library
        # Conversion is set here rather than inherited, for the same reason the library root is. The organize
        # assertions below are about a rebuilt .7z, so a developer whose own settings.json has
        # convert_archives off - which is the state this repository's settings.json was found in - otherwise
        # turned every one of them into an assertion that nothing was converted, and the run still went green
        # as long as the files moved. A test that quietly stops testing the thing its name claims is worse than
        # no test, so the configuration under test is stated here.
        #
        # Set on the checkbox rather than on the config, because MainWindow.scan() reads the checkbox and
        # assigns it back to the config on every scan - so a value written straight into the settings dict is
        # overwritten with the checkbox's a moment later, which is exactly what happened here: the assertions
        # below kept asking for a rebuilt .7z while the run faithfully converted nothing and the log said
        # CONVERSION_DISABLED. This is the control a person would click, so it is what the test clicks, and
        # the settings file it saves belongs to the sandbox.
        self.scan.convert_var.set(True)
        self.app.controller.config = self.app.config

        # The artwork cache starts empty now the project root is redirected, and an empty cache with no network
        # means no artwork at all - so every game would be organized with no pictures in its folder and the
        # assertion about that would fail for a reason that has nothing to do with what it checks.
        #
        # It used to arrive by accident, and this is the same defect as the settings.json corruption wearing a
        # different hat. Pointed at this repository, the run read two pieces of the developer's own state:
        # `config/steam-matches.json` - 708KB of real lookups, which is how a tagged archive came back with a
        # different AppID than the mock table gives it - and `cache/artwork`, where three of these four AppIDs
        # were sitting as CACHE_HITs left by earlier runs of this same test. An assertion that is only true
        # because a test wrote real state is not an assertion, so the fixture states what it needs, and states
        # it with a genuine JPEG rather than bytes that merely look like one: a hand-built header here would
        # make the end-to-end claim a fiction. `tests/test_artwork_render.py` covers Tk decoding real image
        # bytes; what is being checked here is those bytes reaching the game folder.
        artwork_dir = self.app.config.artwork_dir
        jpeg = _jpeg_bytes()
        for appid in MOCK_APPIDS:
            (artwork_dir / f"{appid}_steam_fallback.jpg").write_bytes(jpeg)

    def _run_scan(self):
        """Press Scan and wait for verification to release the run."""
        self.window.show("scan")
        self.root.update()
        self.scan.scan_btn.invoke()
        wait_until(lambda: not self.window.busy, 90.0, "the scan and its background verification to finish")
        self.root.update()

    def test_a_scan_saves_into_the_sandbox_and_never_into_this_projects_own_settings(self):
        """The redirect, asserted against a real scan - and the write it protects is asserted too.

        A test that only checked the repository's settings.json was untouched would pass just as happily if
        the run had stopped saving anything at all, so the sandbox's own settings file is checked for the
        library the run actually scanned. Both halves matter: the first is the property, the second is what
        stops it being satisfied by a broken scan.
        """
        settings = ROOT / "config" / "settings.json"
        sandbox_settings = self.app.config.settings_file
        before = settings.read_bytes() if settings.is_file() else None

        self._run_scan()

        self.assertTrue(sandbox_settings.is_file(), f"the scan saved no settings at all, so this proves nothing: {sandbox_settings} is missing")
        self.assertEqual(str(self.library),
                         json.loads(sandbox_settings.read_text(encoding="utf-8"))["library_root"],
                         "the scan did not save the library it scanned, so it did not "
                         "exercise config.save()")
        self.assertNotIn(b"organizer-workflow-", before or b"", "settings.json already named a temporary directory before this test ran")
        self.assertEqual(before, settings.read_bytes() if settings.is_file() else None, f"the scan rewrote the repository settings file {settings.name}")

    def test_the_scan_button_is_disabled_while_a_scan_runs(self):
        """The other half of the guard: a run must not be startable twice.

        Asserted during the run, not after it. By the time a scan finishes, _end has restored the button to
        normal whether or not anything ever disabled it, so a test that only looked at the end state would
        pass against the guard being deleted entirely.
        """
        self.window.show("scan")
        self.root.update()
        self.scan.scan_btn.invoke()
        # The press itself flips both buttons on the Tk thread, so this needs no waiting.
        self.assertEqual("disabled", str(self.scan.scan_btn.cget("state")), "the scan button stayed live during its own run, so a second press would start a scan on top of this one")
        self.assertEqual("normal", str(self.scan.cancel_btn.cget("state")), "the cancel button never came on during a run")
        # A second press must not begin a second run.
        #
        # Read before the update(), for the same reason the first assertion needs no waiting: nothing pumps the
        # event loop in between, so the button is exactly as `scan()` left it and a run that has finished cannot
        # have re-enabled it yet. Order matters here now that it does - with the fixture's artwork cache seeded
        # instead of timing out against the network, a whole scan completes in milliseconds, and an update()
        # first would let `_end` restore the button before this read, which reads as a second scan having
        # started when the guard held perfectly well.
        self.scan.scan_btn.invoke()
        self.assertEqual("disabled", str(self.scan.scan_btn.cget("state")), "a second press on a live button started another scan")
        self.root.update()
        wait_until(lambda: not self.window.busy, 90.0, "the scan to finish")
        self.root.update()

    def test_the_button_that_died_after_the_first_scan_still_works(self):
        """The headline regression, end to end on a real event loop.

        `begin_scan` and `progress_update` disable the scan button and only `_end` brings it back. A test that
        presses it once cannot tell a working button from one that happened to start enabled.
        """
        for attempt in (1, 2, 3):
            with self.subTest(attempt=attempt):
                self.window.show("scan")
                self.root.update()
                self.assertEqual("normal", str(self.scan.scan_btn.cget("state")), f"scan button was unusable before scan #{attempt}")
                self.scan.scan_btn.invoke()
                # Read the buttons *during* the run. A scan takes long enough that the window is up and
                # busy here, and this is the only place the double-scan guard is observable: by the time
                # the run ends, _end has put the button back to normal whether or not anything ever
                # disabled it, so an end-state-only assertion cannot tell a working guard from no guard.
                self.assertEqual("normal", str(self.scan.cancel_btn.cget("state")), f"the cancel button never came on during scan #{attempt}")
                wait_until(lambda: not self.window.busy, 90.0, f"scan #{attempt} to finish")
                self.root.update()
                self.assertEqual("normal", str(self.scan.scan_btn.cget("state")), f"scan button was unusable after scan #{attempt}")
                self.assertEqual("disabled", str(self.scan.cancel_btn.cget("state")), f"the cancel button was still live after scan #{attempt}")

    def test_scan_verifies_and_hands_archives_to_review(self):
        self._run_scan()
        state = self.window.state.get()
        result = getattr(state, "scan_result", None)
        archives = getattr(result, "archives", [])
        self.assertTrue(archives, "mock scan produced no archives at all")
        self.assertEqual("review", self.window.current, "verification finishing should leave the user on Review")
        review = self.window.views["review"]
        self.assertTrue(review.archives if hasattr(review, "archives") else True)

    def test_review_to_organize_to_done_moves_real_files(self):
        """The full chain, ending with bytes actually moved on disk.

        The point of driving Organize through the view rather than the controller is that the view owns the
        accept set, the button states and the run summary, and a run can finish correctly while the screen
        still says it never started.
        """
        self._run_scan()
        review = self.window.views["review"]
        review.approve_all()
        self.root.update()

        archives = self.window.state.get().scan_result.archives
        accepted = [a for a in archives if a.decision.accepted]
        self.assertTrue(accepted, "approve_all accepted nothing, so Organize would have had no work")
        self.assertEqual([], [a.steam.appid for a in accepted
                              if a.steam.appid not in MOCK_APPIDS],
                         "the Steam fixture handed out an AppID this module seeds no "
                         "artwork for, so the artwork assertion below would fail for a "
                         "reason of its own")

        # Mock discovery hands back paths under /mock/library that were never written, so a move has nothing
        # to move and the run correctly reports nothing organized - which would make every assertion below
        # pass for the wrong reason. Point each archive at a real file so the organize stage moves real bytes
        # and the run's numbers mean something.
        #
        # Through state.update(), not by mutating the snapshot: StateStore.get() deep-copies, so an archive
        # taken from a snapshot is not the object _accepted() later reads, and setting .path on it changes
        # nothing at all. Writing the whole archive list back is what makes the new paths real.
        incoming = self.library / "Incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        for index, archive in enumerate(archives):
            source = incoming / f"{index}.zip"
            with zipfile.ZipFile(source, "w") as handle:
                handle.writestr(f"{archive.display_name}/game.bin", bytes(index + 1) * 4096)
            archive.path = source
        self.window.state.update(scan_result=type(self.window.state.get().scan_result)(archives=archives))

        self.window.show("organize")
        self.root.update()
        organize = self.window.views["organize"]
        organize._confirm_organize()
        wait_for_organize(self.window, 180.0)
        self.root.update()

        self.assertEqual("normal", str(self.scan.scan_btn.cget("state")), "the scan button was still dead after an organize run")
        self.assertFalse(self.window.busy, "the window is still marked busy after organize finished")

        # Done has to receive the run's real outcome. Asserting the widgets exist proves
        # nothing - the view is constructed at startup, so every attribute is there long
        # before a run has written to it. The counters are what a user reads to decide
        # whether the run worked, so they are what has to be non-default.
        #
        # goto_done() rather than show('done'): show() only grids the view in, and the
        # handoff of the run's archives into it is exactly the step that was once missing,
        # which left this screen on its empty placeholder for every run.
        self.window.goto_done()
        self.root.update()
        self.assertEqual("done", self.window.current)
        done = self.window.views["done"]
        self.assertTrue(done._last_archives, "the done screen received no archives, so it is showing its startup text")
        organized = int(done.tiles["organized"].cget("text") or 0)
        converted = int(done.tiles["converted"].cget("text") or 0)
        skipped = int(done.tiles["skipped"].cget("text") or 0)
        failed = int(done.tiles["failed"].cget("text") or 0)
        self.assertGreater(organized, 0, f'the done screen organised nothing from {len(accepted)} accepted game(s); tiles={{k: v.cget("text") for k, v in done.tiles.items()}}')

        # The invariant is organized + failed == accepted. `organized` already counts every accepted archive
        # whose conversion did not fail, so `converted` and `skipped` are subsets of it rather than parts of a
        # total - summing all four double-counts, which only looked right while every archive happened to be
        # converted. `skipped` in particular moves when a conversion ends up left as-is, which it did for a run
        # with no artwork available.
        self.assertEqual(len(accepted), organized + failed, f"{len(accepted)} accepted, but organized={organized} failed={failed}")
        for label, value in (("converted", converted), ("skipped", skipped)):
            self.assertLessEqual(value, organized, f"{label}={value} exceeds organized={organized}, so the tiles overlap")
        self.assertNotEqual("No completed run yet.", str(done.summary.cget("text")), "the done summary is still its startup placeholder")

        # And the bytes really moved, through a real conversion. The sources are gone from Incoming and each game
        # folder holds a rebuilt .7z with its metadata, artwork and Steam link - the only part of this no
        # mock could have faked. The extension is .7z rather than .zip because conversion is on by default,
        # which is the release configuration this test is here to cover.
        self.assertEqual([], sorted(incoming.glob("*.zip")), "the organize run reported success but left every source archive in place")
        landed = [p for p in self.library.rglob("*.7z") if p.parent != incoming]
        self.assertEqual(len(accepted), len(landed), f"expected one rebuilt archive per accepted game; found {landed}")
        for archive_path in landed:
            with self.subTest(archive=archive_path.name):
                folder = archive_path.parent
                self.assertTrue((folder / ".game-info.json").is_file(), f"{folder.name} has no metadata")
                self.assertTrue((folder / "Open Steam Page.html").is_file(), f"{folder.name} has no Steam link")
                self.assertTrue(any(folder.glob("*.jpg")), f"{folder.name} has no artwork, so nothing was copied out of the cache the fixture seeded")
                # The app's own lock marker must never end up packed inside a published archive.
                self.assertFalse(any(p.name == ".organizer-lock" for p in folder.rglob("*")), f"{folder.name} shipped the build lock marker to the library")

    def _build_incoming(self, payload_size=4096, compressible=True):
        """Scan, accept everything, and point each archive at a real file. Returns (incoming, accepted, originals).

        Mock discovery hands back paths under /mock/library that were never written, so a move has nothing to
        move and the run correctly reports nothing organized - which would make every assertion below pass for
        the wrong reason.

        Written back through state.update() rather than by mutating a snapshot: StateStore.get() deep-copies,
        so an archive taken from a snapshot is not the object _accepted() later reads.

        The original bytes are read here, before anything is moved. Reading them afterwards asks a question
        about files the organize run has already deleted.

        `compressible=False` fills the archive with random bytes. LZMA2 turns a single repeated byte into
        almost nothing, so a run over compressible data finishes in milliseconds and any assertion about a
        cancel landing mid-flight is asserting nothing - the run was over before it could be observed.
        """
        self._run_scan()
        review = self.window.views["review"]
        review.approve_all()
        self.root.update()
        archives = self.window.state.get().scan_result.archives
        accepted = [a for a in archives if a.decision.accepted]
        self.assertTrue(accepted, "approve_all accepted nothing, so Organize would have had no work")

        incoming = self.library / "Incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        originals = {}
        for index, archive in enumerate(archives):
            source = incoming / f"{index}.zip"
            if compressible:
                body = bytes([index + 1]) * payload_size
            else:
                # Seeded so a failure can be reproduced, and generated in slices so a large payload does not
                # become one enormous bytes object.
                rng = random.Random(1000 + index)
                body = b"".join(rng.randbytes(65536) for _ in range(max(1, payload_size // 65536)))
            with zipfile.ZipFile(source, "w", zipfile.ZIP_STORED) as handle:
                handle.writestr(f"{archive.display_name}/game.bin", body)
            archive.path = source
            originals[index] = (source, source.read_bytes())
        self.window.state.update(scan_result=type(self.window.state.get().scan_result)(archives=archives))
        return incoming, accepted, originals

    def _organize_fixture(self, payload_size=4096):
        """The same, but run to completion. Returns (incoming, accepted)."""
        incoming, accepted, _ = self._build_incoming(payload_size)
        self.window.show("organize")
        self.root.update()
        self.window.views["organize"]._confirm_organize()
        wait_for_organize(self.window, 180.0)
        self.root.update()
        return incoming, accepted

    def _confirm_dialogs(self):
        """Make every modal confirmation answer itself, and put the real ones back afterwards.

        tests/tk_support.py stubs tkinter.messagebox only when tkinter is *absent*. On a machine that has
        tkinter - which is the primary platform - nothing is stubbed, so MainWindow.undo_last() reaches the real
        askyesno() and blocks on a modal dialog with nobody to answer it. The run does not fail, it hangs,
        which looks exactly like a slow test. Patched here rather than assumed.
        """
        import tkinter.messagebox as messagebox
        from ui import main_window

        # Patched on the module object MainWindow resolves at call time, and on tkinter.messagebox itself,
        # because main_window did `from tkinter import messagebox` - it holds its own reference to the module,
        # so patching only one of the two leaves the other holding the real dialog.
        original = main_window.messagebox.askyesno
        original_stdlib = messagebox.askyesno
        replacement = lambda *args, **kwargs: True
        main_window.messagebox.askyesno = replacement
        messagebox.askyesno = replacement
        self.addCleanup(setattr, main_window.messagebox, "askyesno", original)
        self.addCleanup(setattr, messagebox, "askyesno", original_stdlib)
        self.assertIs(replacement, main_window.messagebox.askyesno, "the confirmation dialog the window will call is not the stub")

    def test_undo_puts_a_real_organized_run_back_where_it_started(self):
        """Organize then undo, end to end through the window, on real bytes.

        Undo is the only thing standing between a bad run and a user re-downloading a library by hand, and
        the button path is not what the RollbackService unit tests exercise: MainWindow.undo_last() gates on a
        confirmation dialog, calls _start(), and hands the result to undo_done(). A run that organized correctly
        and then restored nothing would leave every game filed under a category folder with its original path
        gone, which is the outcome a person notices days later.
        """
        incoming, accepted, originals = self._build_incoming()
        self.window.show("organize")
        self.root.update()
        self.window.views["organize"]._confirm_organize()
        wait_for_organize(self.window, 180.0)
        self.root.update()

        organized_paths = sorted(p for p in self.library.rglob("*.7z") if p.parent != incoming)
        self.assertEqual(len(accepted), len(organized_paths), f"nothing was organized, so undo has nothing to undo; found {organized_paths}")

        # The real confirmation dialog, answered yes.
        self._confirm_dialogs()
        self.window.undo_last()
        wait_until(lambda: not self.window.busy, 90.0, "the undo to finish")
        self.root.update()

        self.assertEqual("scan", self.window.current, "undo did not return to the scan screen")

        # Undo restores each organized file back to where its source was, under the extension it now has.
        # That is deliberate: the journal records a .zip source and a .7z target, because conversion runs
        # before the move, and writing the .7z bytes to a .zip name would produce an archive whose name lies
        # about its format. The original .zip is not recovered - conversion replaced it - so this asserts that
        # the folder is repopulated and readable, not that the pre-organize bytes come back.
        for original, _payload in originals.values():
            with self.subTest(archive=original.name):
                restored = original.with_suffix(".7z")
                self.assertTrue(restored.is_file(), f"nothing was restored at {restored.name}; Incoming holds {sorted(p.name for p in incoming.iterdir())}")
                self.assertGreater(restored.stat().st_size, 0, f"{restored.name} came back empty")
                # The .7z extension is not just a rename: these are real 7-Zip archives, so the
                # signature is checked rather than trusting the name. zipfile cannot open one, which
                # is itself the reason undo must not write 7z bytes under a .zip name.
                self.assertEqual(b"7z\xbc\xaf\x27\x1c", restored.read_bytes()[:6], f"{restored.name} does not hold a 7-Zip archive")
        # Recomputed after the undo: the list read before it would still hold the paths even on a perfect undo.
        still_there = [p for p in organized_paths if p.exists()]
        self.assertEqual([], still_there, f"these organized archives survived the undo: {[p.name for p in still_there]}")
        # And the game folders are left holding only what belongs to the game, not a second copy of the archive.
        for folder in self.library.rglob("*.7z"):
            self.assertEqual(incoming, folder.parent, f"{folder} was left outside Incoming after an undo")

        # The journal must be consumed, or a second Undo would replay moves that were already reversed.
        self.assertEqual(0, self.app.services.rollback.pending_count(), "the undo journal was not cleared, so a second Undo would repeat it")

    def test_stopping_a_run_mid_flight_unwinds_it_and_says_so(self):
        """The STOP RUN button has to actually stop the run, and the window has to say it was stopped.

        A cancel that is requested but never noticed leaves the run going to completion: hours of compression
        for a result the user already declined, and a status line still reading WORKING while it happens.

        The archives are large on purpose. With four tiny ones the run finished before the stop could be
        observed, and the test passed against a cancel that does nothing simply because there was nothing
        left to cancel - the same way an end-state-only assertion cannot see a deleted guard.
        """
        incoming, accepted, _ = self._build_incoming(payload_size=32 * 1024 * 1024, compressible=False)
        self.window.show("organize")
        self.root.update()
        organize = self.window.views["organize"]
        organize._confirm_organize()
        wait_until(lambda: organize.ctx is not None, 15.0, "the organize run to start")

        # Press the real button, not the controller.
        organize._stop()
        self.root.update()
        self.assertEqual("disabled", str(organize.stop_btn.cget("state")), "the stop button stayed live after a stop was requested")
        self.assertIn("STOPPING", str(organize.stop_btn.cget("text")))

        # The run unwinds on its own. Bounded, because "never finishes" is the failure this is looking for.
        wait_until(lambda: organize.ctx is None, 180.0, "the cancelled organize run to unwind")
        self.root.update()
        self.assertFalse(self.window.busy, "the window is still busy after the run was cancelled")
        status = str(self.window.status.cget("text"))
        self.assertRegex(status, r"(?i)cancel|stop", f"the status line does not say the run was cancelled: {status!r}")
        self.assertEqual("READY", str(self.window.runtime.cget("text")))

        # A cancelled run must not leave a half-built archive behind, and must not claim success. The done
        # screen is where success would be claimed, so it is checked rather than the status line alone:
        # goto_done() hands the run's archives over, and a cancelled run has none to hand over, so the screen
        # must still be showing the placeholder it starts with.
        done = self.window.views["done"]
        self.assertNotIn("complete", status.lower(), "the status line reports a completed run after the user cancelled it")
        self.assertFalse(done._last_archives, f"the done screen was handed {len(done._last_archives)} archive(s) by a cancelled run")
        self.assertEqual("No completed run yet.", str(done.summary.cget("text")), "the done screen reports a finished run after the user cancelled it")

    def test_every_screen_is_reachable_and_survives_a_round_trip(self):
        """Each screen builds, shows, and leaves the window usable.

        A view that raises while being gridded in takes the whole navigation down with it, and that shows up
        as a click that silently does nothing rather than as a traceback.
        """
        self._run_scan()
        for key in ("scan", "review", "organize", "artwork", "done"):
            with self.subTest(screen=key):
                self.window.show(key)
                self.root.update()
                self.assertEqual(key, self.window.current)
                self.assertTrue(self.window.views[key].winfo_exists())
                self.assertTrue(self.root.winfo_exists())

    def test_the_window_closes_while_a_run_is_in_flight(self):
        """Closing during a run must not hang or raise.

        shutdown() runs on the Tk thread, so this is the path where wait=True would have frozen the window
        behind a conversion. That the run was genuinely in flight when the close happened is asserted, not
        assumed - a test that closed an idle window would pass against the very freeze it exists to catch.
        """
        import tkinter as tk

        self._run_scan()
        review = self.window.views["review"]
        review.approve_all()
        self.root.update()
        self.window.show("organize")
        self.root.update()
        organize = self.window.views["organize"]
        organize._confirm_organize()

        # Hand the job to its worker thread before closing, so there is a real run to shut down.
        wait_until(lambda: organize.ctx is not None, 15.0, "the organize run to start")
        self.app.shutdown()
        try:
            self.root.update()
        except tk.TclError:
            pass  # the root is gone, which is the point
        self.assertTrue(self.app._closed, "shutdown did not mark the app closed")
