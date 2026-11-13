"""Regression tests for UI behaviour.

These tests were extracted from tests/test_regressions.py to keep each test module
focused on one area of the app: scan button state, folder opening, setup button,
catalog launcher, and Done-screen fact reporting.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import tkinter as tk

from core.config import AppConfig
from core.logger import AppLogger
from core.models import ArtworkResult
from services.catalog_service import CatalogService
from services.library_service import LibraryService
from services.organizer_service import OrganizerService
from services.rollback_service import RollbackService
from ui.artwork_view import ArtworkView, _asset_prefix_for
from ui.done_view import DoneView
from ui.main_window import MainWindow
from utils.desktop import open_folder
from utils.filename_utils import identity_key
from utils.formatting import human_size


def _tmp_dir(test_case):
    """A temporary directory that is cleaned up when the test finishes."""
    tmp = Path(tempfile.mkdtemp())
    test_case.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    return tmp


def _label_texts(widget):
    """Every label's text under a widget, in one list."""
    found = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Label):
            found.append(str(child.cget("text")))
        found.extend(_label_texts(child))
    return found


class TestScanButtonComesBackAfterAScan(unittest.TestCase):
    """The app's headline button went dead after the first scan, for the rest of the session.

    `begin_scan` and `progress_update` both set `scan_btn` to `disabled`, so it cannot be pressed twice while a
    run is in progress. Nothing ever set it back. `MainWindow._end` - the one place that ends a run and already
    turns the cancel button off - never touched it.

    So the button the app opens with, and the one the user presses to pick up games they have just downloaded,
    stopped working the first time they used it. Restarting the app was the only way back, which makes "did it
    find the game I just downloaded" answerable only by closing the program. `MainWindow.scan`'s
    `if self.busy: return` guard reads like a second scan is supported and simply is not reachable.

    Driven through the real MainWindow rather than a bare ScanView, because the omission is in MainWindow: the
    buttons are correct during a run and only ever brought back at the end, and a test that stops at
    `set_result` never reaches the code that owns the fix.

    Deliberately not asserting any of this by pressing the button. Its command was bound to MainWindow.scan when
    the button was created, so `invoke()` starts a real scan of the configured library root - and this machine's
    settings.json points at D:\Game Installers\Steam Games. While the button was disabled that call was a
    harmless no-op, which is how an earlier version of this test passed without ever pressing it.
    """

    def setUp(self):
        from tests.tk_support import require_tk, close_root, sandbox_app
        from tests.test_ui_geometry import _measured_window
        require_tk(self)
        import tkinter as tk
        self.root = tk.Tk()
        self.addCleanup(close_root, self.root)
        self.app = sandbox_app(self, self.root)
        _measured_window(self.root)
        self.window = self.app.window
        self.scan = self.window.views["scan"]
        self.window.show("scan")
        self.root.update()

    def _run_a_whole_scan(self):
        """Discovery, then the background verification that follows it, then the run ends."""
        self.window.scan_done(type("R", (), {"archives": [], "errors": []})())
        self.window.verification_done([])

    def test_the_button_starts_enabled(self):
        self.assertNotEqual(
            str(self.scan.scan_btn["state"]),
            "disabled",
            "the scan button is dead on a freshly opened window",
        )

    def test_a_finished_scan_leaves_the_button_usable(self):
        self.window.views["scan"].begin_scan()
        self.window._start("Scanning Games…")
        self.assertEqual(str(self.scan.scan_btn["state"]), "disabled", "the button was live during a running scan")
        self._run_a_whole_scan()
        self.assertFalse(self.window.busy, "the window still believes a run is in progress")
        self.assertFalse(self.scan.scanning, "the view still believes a scan is running")
        self.assertNotEqual(
            str(self.scan.scan_btn["state"]),
            "disabled",
            "the scan button is still disabled after the run finished, so the library cannot be "
            "scanned again without restarting the app",
        )

    def test_the_cancel_button_is_turned_off_when_the_run_ends(self):
        self.window.views["scan"].begin_scan()
        self.window._start("Scanning Games…")
        self.assertEqual(str(self.scan.cancel_btn["state"]), "normal", "cancel was not live during a run")
        self._run_a_whole_scan()
        self.assertEqual(str(self.scan.cancel_btn["state"]), "disabled", "the cancel button is still live after the run finished")


class TestOpenFolderIsNotLinuxOnly(unittest.TestCase):
    """Both "open this folder" buttons were wired to xdg-open and nothing else.

    `MainWindow.open_library` and `ArtworkView._open_folder` both did `shutil.which('xdg-open')` and, finding
    nothing, did nothing at all - no message, no error, nothing in the log. On the platform this app is primarily
    run on that is every press: Done's "Open Library Folder" and every Artwork-screen "OPEN GAME FOLDER" were
    dead buttons. Verified on this host: `xdg-open` is not on PATH, `explorer` is, and `os.startfile` exists.

    The two call sites had drifted apart from each other as well, so the behaviour now lives in one helper that
    answers the question the buttons actually care about: did anything get launched.
    """

    def setUp(self):
        from tests.tk_support import require_tk, close_root, sandbox_app
        require_tk(self)
        self.close_root = close_root
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self.folder = Path(self._folder.name)

    def test_opening_a_folder_launches_something_on_this_platform(self):
        if os.name != "nt":
            self.fail("this app is Windows-only now, so open_folder must refuse elsewhere rather than launch nothing")
        launched = []
        with patch("utils.desktop.os.startfile", side_effect=lambda p: launched.append(p)):
            self.assertTrue(open_folder(self.folder))
            self.assertEqual(launched, [str(self.folder)], "on Windows the folder was not handed to the shell, so the button did nothing")

    def test_it_reports_failure_instead_of_silently_doing_nothing(self):
        # The old code returned None whether or not anything happened, so a caller could not tell a launched file
        # manager from a dead button. Anything that cannot be launched is a False, never an exception at the caller.
        #
        # Both routes have to be closed off on Windows: os.startfile failing falls back to explorer, and this host
        # does have explorer, so blocking startfile alone would prove nothing.
        if os.name != "nt":
            self.fail("this app is Windows-only now, so open_folder must refuse elsewhere rather than launch nothing")
        with patch("utils.desktop.os.startfile", side_effect=OSError("no shell here")), patch(
            "utils.desktop.shutil.which", return_value=None
        ):
            self.assertFalse(open_folder(self.folder), "a failed launch was reported as a success")

    def test_a_folder_that_is_not_there_is_not_launched(self):
        self.assertFalse(
            open_folder(self.folder / "no-such-folder"),
            "a missing folder was handed to the shell instead of being refused",
        )

    def test_the_library_button_goes_through_the_helper(self):
        from tests.test_ui_geometry import _measured_window
        from tests.tk_support import sandbox_app
        import tkinter as tk

        root = tk.Tk()
        self.addCleanup(self.close_root, root)
        app = sandbox_app(self, root)
        _measured_window(root)
        app.config.library_root = self.folder
        with patch("utils.desktop.open_folder", return_value=True) as helper:
            app.window.open_library()
            helper.assert_called_once_with(self.folder)

    def test_the_artwork_screen_goes_through_the_helper(self):
        import tkinter as tk
        from ui.artwork_view import ArtworkView

        root = tk.Tk()
        self.addCleanup(self.close_root, root)
        view = ArtworkView(tk.Frame(root), lambda: None)
        with patch("utils.desktop.open_folder", return_value=True) as helper:
            view._open_folder(self.folder)
            helper.assert_called_once_with(self.folder)


class TestTheSetupButtonIsInTheAppToolbar(unittest.TestCase):
    """A Setup button in the app's own toolbar.

    The catalog's Set up on this PC button goes through the protocol handler, which runs with no
    main window - so it cannot reach the app. A reader who already has the app running and needs to
    re-point it, because the app folder was moved, had no way to open the wizard at all: the only
    routes were --setup on the command line and the catalog button, both of which assume the app is
    not already open. The button lives in the footer bar beside System Health and Diagnostics.
    """

    def setUp(self):
        from tests.tk_support import require_tk, close_root, sandbox_app
        require_tk(self)
        self.close_root = close_root
        import tkinter as tk

        root = tk.Tk()
        self.addCleanup(self.close_root, root)
        self.app = sandbox_app(self, root)

    def test_the_button_is_present_and_open_setup_is_bound_to_it(self):
        self.assertTrue(hasattr(self.app.window, "setup_btn"), "the app toolbar has no Setup button")
        self.assertTrue(hasattr(self.app.window, "open_setup"), "MainWindow has no open_setup handler for the button")

    def test_opening_setup_opens_the_wizard(self):
        from unittest.mock import patch

        with patch("ui.setup_window.SetupWindow") as wizard:
            self.app.window.open_setup()
        wizard.assert_called_once()
        args, kwargs = wizard.call_args
        self.assertIs(args[0], self.app.root)
        self.assertIs(args[1], self.app.config)
        self.assertIs(args[2], self.app.logger)


class TestTheCatalogLauncherIsUsable(unittest.TestCase):
    """A launcher beside the catalog must be a file this machine can actually open.

    Found in the real library rather than reasoned about. `Open Game Library.desktop` was sitting in the library
    root on this PC, containing:

        Exec=google-chrome --new-tab file:///D:/Game%20Installers/...

    and it was dead twice over. Windows has no association for `.desktop`, so double-clicking it opened nothing;
    and `google-chrome` does not exist here (`shutil.which` returns None), because `chrome_command()` returned a
    hardcoded string whenever no browser was found rather than admitting it had none.

    It was written at all because `html_handler()` only ever read the Linux XDG mimeapps.list, which cannot exist
    on this platform - so it always answered "nothing here opens HTML", on a machine where `HKCR\\.html` says
    `htmlfile` and double-clicking the catalog works perfectly well. A launcher is only needed when the machine
    genuinely has no handler, and this one did not know how to tell.

    The suite passed throughout: the one test covering this passed an explicit `/usr/bin/chrome` command and then
    only asserted that the file had been created, which is the one thing that was never the problem.
    """

    def test_a_launcher_file_carries_a_url_and_no_command_at_all(self):
        """The command is not merely unused now - it never could have been used.

        A .url with a `URL=` line and nothing else is resolved by the shell association, so the catalog's launcher
        never had a way to honour a browser command even when it was handed one.       The machinery that searched for
        one is gone; this asserts the file cannot reintroduce the idea.
        """
        from pathlib import Path as _Path
        from core.logger import AppLogger

        root = _Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        catalog = CatalogService(AppLogger(root / "x.log"))
        catalog._write_chrome_launcher(root, root / "Game Library.html")
        text = (root / "Open Game Library.url").read_text()
        self.assertNotIn("Exec=", text, "the launcher names a program again, which the format cannot act on")

    def test_no_launcher_is_written_when_the_machine_already_opens_html(self):
        from pathlib import Path as _Path
        from core.logger import AppLogger

        service = OrganizerService(AppLogger(_Path(_tmp_dir(self)) / "x.log"))
        # The real registry, not a mock: the whole defect was that this question was answered from a file that does
        # not exist here rather than from the platform that does.
        handler = service.html_handler()
        self.assertTrue(
            handler,
            "html_handler() reports nothing on a machine whose HKCR\\.html is set; "
            "it is still only reading the Linux mimeapps.list",
        )
        self.assertFalse(
            service.needs_catalog_launcher(),
            "a launcher was deemed necessary on a machine that already opens .html with a browser",
        )

    def test_a_launcher_is_never_a_linux_desktop_file_on_windows(self):
        """The fallback still has to be a format Windows understands.

        Reaching this branch needs a machine with no HTML association at all, which is rare - so it is reached by
        patching rather than by waiting for one, and the format is asserted rather than the presence.
        """
        import os

        if os.name != "nt":
            self.fail("this app is Windows-only now")
        from pathlib import Path as _Path
        from core.logger import AppLogger

        root = _Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        catalog = CatalogService(AppLogger(root / "x.log"))
        catalog._write_chrome_launcher(root, root / "Game Library.html")
        written = sorted(p.name for p in root.iterdir())
        self.assertEqual(
            [],
            [n for n in written if n.endswith(".desktop")],
            f"wrote a Linux desktop entry on Windows: {written}",
        )
        self.assertTrue(written, f"no launcher at all was written for a machine with no HTML handler: {written}")


class TestTheAppStopsReportingWorkItDidNotDo(unittest.TestCase):
    """Six readouts that answered a question nobody asked, so the number on screen was not the number on disk.

    None of them crashed and none of them logged: each was output that was confidently wrong, on screens whose
    entire job is to tell the user what the last run did. Every case was reproduced on this machine before the
    fix, and each test is written so that putting the fix back fails it - which is the only evidence here that a
    test is looking at the defect rather than at its own fixture.

    Fix 1 and fix 2 are the same function and are kept as two tests, because they were two separate false readouts
    that happened to share a line of code, and one test asserting both would not say which one came back.
    """

    def _facts_view(self, **extra):
        """The Done screen's RUN FACTS rail as a stand-in, so _paint_facts can be called without a window.

        `state` hands back a real AppState, and that is the point of the fixture rather than a shortcut: the defect
        was that AppState carries neither `config` nor `rollback_pending`, so a stand-in state that had them would
        have made the screen look right and hidden the bug these tests exist for. The library root arrives as a
        config object rather than a path, because the screen holds the config - a Path cannot follow the rebind
        MainWindow.choose() makes, and holding one was how the row went stale after a Games-directory change.
        """
        view = SimpleNamespace(
            facts={name: Mock() for name in ("duration", "compressed", "saved", "free", "undo", "where")},
            state=SimpleNamespace(get=lambda: __import__("core.models", fromlist=["AppState"]).AppState()),
            rollback=None,
            config=None,
            undo_btn=Mock(),
        )
        for name, value in extra.items():
            setattr(view, name, value)
        return view

    def _shown(self, view, fact):
        """The text one RUN FACTS row was last given."""
        return view.facts[fact].configure.call_args.kwargs["text"]

    def _audit_library(self, root):
        """One organized game folder carrying an AppID and no artwork: the shape of every folder in a real library,
        and the case the audit used to call 'refreshed' whatever else was true."""
        library = Path(root) / "Games"
        game = library / "Puzzle" / "SunTopia - 1 Jan, 2026"
        game.mkdir(parents=True)
        (game / ".game-info.json").write_text(json.dumps({"appid": "1234", "name": "SunTopia"}), encoding="utf-8")
        # The folder carries its archive, so the empty-folder sweep does not prune it. A game folder with no
        # archive is exactly what the sweep is for, and this fixture is an organized game that is still there.
        (game / "SunTopia.7z").write_bytes(b"7z\xbc\xaf\x27\x1c")
        organizer = SimpleNamespace(write_steam_links=Mock(), write_metadata=Mock())
        return library, game, organizer

    def _image(self, path):
        """A real JPEG rather than four bytes, because ArtworkPanel decodes what it is given and a truncated file
        would fail the artwork test for a reason that has nothing to do with the filenames on it."""
        from PIL import Image

        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (12, 16), (24, 28, 32)).save(str(path), "JPEG")
        return path

    def test_the_done_screen_undo_row_reads_the_journal_rather_than_the_app_state(self):
        """Reproduced before the fix: pending_count() was 1 and the row said 'nothing to undo'.

        It read `getattr(snap,'rollback_pending',())`, and AppState has no such field and nothing anywhere sets one,
        so the getattr default is what the row always showed. The Undo button would in fact have restored every
        move the run had made. The count is read from the journal file rather than remembered anywhere, because
        undo_last() consumes that file - a remembered number is one more thing that can disagree with the button.
        """

        view = self._facts_view(rollback=SimpleNamespace(pending_count=lambda: 3))
        DoneView._paint_facts(view, [], [], [])
        self.assertEqual(self._shown(view, "undo"), "3 move(s)", "the Undo row disagrees with the journal it exists to summarise")
        view.undo_btn.configure.assert_called_with(state="normal")

    def test_the_done_screen_undo_button_is_disabled_when_journal_is_empty(self):
        """When the rollback journal is empty the Undo button must not offer an action it cannot perform."""

        view = self._facts_view(rollback=SimpleNamespace(pending_count=lambda: 0))
        DoneView._paint_facts(view, [], [], [])
        view.undo_btn.configure.assert_called_with(state="disabled")

    def test_the_done_screen_names_the_library_and_the_space_left_on_it(self):
        """Reproduced before the fix: both rows rendered their placeholder - 'Library: -' and 'Free space: -' -
        immediately after a successful run, because they read `snap.config` and AppState has no config either.

        Both were getattr-guarded, which is why nothing crashed: the guard is exactly what let the wrong answer
        through. Free space is the number that decides whether the next conversion can finish, so it is read from
        the volume that actually holds the library rather than from a field that does not exist.

        The config is read at paint time, not captured at construction: a Path is an immutable snapshot, and
        MainWindow rebinds config.library_root when the Games directory changes, so a value taken once named the
        previous directory for the rest of the session - the same false row, one level up.
        """
        library = Path(_tmp_dir(self)) / "Steam Games"
        library.mkdir()
        config = SimpleNamespace(library_root=library)
        view = self._facts_view(config=config)

        DoneView._paint_facts(view, [], [], [])
        self.assertEqual(self._shown(view, "where"), str(library), "the Library row fell back to its placeholder")
        free = self._shown(view, "free")
        self.assertNotEqual(free, "—", "the free-space row fell back to its placeholder")
        self.assertEqual(
            free,
            human_size(shutil.disk_usage(str(library)).free),
            "the free-space row is reporting some other volume than the library",
        )
        config.library_root = Path(_tmp_dir(self)) / "Other Games"
        DoneView._paint_facts(view, [], [], [])
        self.assertEqual(
            self._shown(view, "where"),
            str(config.library_root),
            "the row still names the directory the app was opened with, after the user changed it",
        )

    def test_the_audit_reports_a_folder_it_could_not_refresh_as_a_failure(self):
        """Reproduced before the fix: offline, with an AppID that has no art on Steam, the audit returned
        `refreshed: 1`, the progress line read 'artwork refreshed', and there was no image on disk.

        `_audit_game` returned `changed or not has_any`, which folds "files were written" and "this folder had no
        artwork and still has none" into the same truthy value, and the per-folder line never asked the function at
        all - it reported 'artwork refreshed' for any folder holding an AppID. A user reading that would go and
        fetch artwork they already had, or believe a failed fetch had succeeded.
        """
        root = _tmp_dir(self)
        library, game, organizer = self._audit_library(root)
        offline = SimpleNamespace(download_assets=lambda *a, **k: ArtworkResult(reason="offline"))
        seen = []
        summary = LibraryService(AppLogger(Path(root) / "audit.log")).audit(library, offline, organizer, on_progress=seen.append)
        self.assertEqual(summary["refreshed"], 0, "a folder nothing was written to was counted as refreshed")
        self.assertEqual(summary["no_artwork"], 1, f"the folder was not reported as having no artwork: {summary}")
        self.assertEqual(sorted(p.suffix for p in game.iterdir()), [".7z", ".json"], "the fixture gained artwork it was never given")
        lines = [e["message"] for e in seen if isinstance(e, dict) and e.get("stage") == "audit_item" and e.get("state") == "done"]
        self.assertTrue(lines, f"the audit reported nothing per folder: {seen}")
        self.assertNotIn("artwork refreshed", lines[-1], f"the per-folder line still claims a refresh: {lines[-1]}")
        self.assertIn("no artwork available", lines[-1], f"the per-folder line does not say what went wrong: {lines[-1]}")
        # Driven through controller.scan(), because the line the user reads last is the controller's and not the
        # service's. audit() reports its own no-artwork figure on its audit_done event, but audit_progress()
        # relabels that as an ordinary 'audit' line and the controller then emits a second audit_done from
        # checked/refreshed alone - so the count was computed, logged, and dropped on the way to the screen.
        from threading import Event

        from app.controller import AppController
        from app.events import EventBus
        from app.jobs import JobManager
        from core.state import StateStore
        from services.archive_service import ArchiveService
        from services.rollback_service import RollbackService

        root2 = _tmp_dir(self)
        library2, game2, organizer2 = self._audit_library(root2)
        logger2 = AppLogger(Path(root2) / "scan.log")
        jobs2 = JobManager()
        services2 = type("Services", (), {})()
        services2.library = LibraryService(logger2)
        services2.organizer = organizer2
        services2.rollback = RollbackService(Path(root2), logger2, organizer=organizer2)
        services2.archive = ArchiveService(logger2)
        services2.artwork = type(
            "Artwork",
            (),
            {
                "download_assets": lambda *a, **k: ArtworkResult(reason="offline"),
                "lookup": lambda *a, **k: ArtworkResult(),
            },
        )()
        services2.catalog = type("Catalog", (), {"generate": lambda *a, **k: []})()
        controller2 = AppController(StateStore(), EventBus(), logger2, services2, jobs2)
        phases = []
        finished2 = Event()
        try:
            controller2.scan(library2, lambda result: finished2.set(), progress=lambda event: phases.append(event))
            self.assertTrue(finished2.wait(30), "the scan never finished")
        finally:
            jobs2.shutdown()
        summaries = [e["message"] for e in phases if isinstance(e, dict) and e.get("stage") == "audit_done" and e.get("message")]
        self.assertTrue(summaries, f"the scan reported no audit summary at all: {[e.get('stage') for e in phases if isinstance(e, dict)]}")
        self.assertEqual(len(summaries), 1, f"the audit announced itself as finished more than once: {summaries}")
        self.assertIn(
            "1 with no artwork",
            summaries[0],
            f"the last line the user reads drops the count of folders with no artwork: {summaries[0]!r}",
        )

    def test_the_audit_can_still_report_a_folder_it_really_refreshed(self):
        """The precondition for the test above. If this fixture could never refresh anything, that test would pass
        for the wrong reason - so the same folder is audited again with artwork to hand, and must count."""
        root = _tmp_dir(self)
        library, game, organizer = self._audit_library(root)
        cached = self._image(Path(root) / "cache" / "grid.jpg")
        online = SimpleNamespace(download_assets=lambda *a, **k: ArtworkResult(status="downloaded", path=cached))
        summary = LibraryService(AppLogger(Path(root) / "audit.log")).audit(library, online, organizer)
        self.assertEqual(summary["refreshed"], 1, f"a folder that gained an image was not counted: {summary}")
        self.assertTrue((game / "SunTopia_grid.jpg").is_file(), f"nothing was copied into the folder: {sorted(p.name for p in game.iterdir())}")

    def test_the_artwork_screen_names_only_files_that_are_on_disk(self):
        """Reproduced before the fix: four of twelve real Steam names were listed under a filename that did not
        exist. Two separate mistakes, and both are exercised here.

        The prefix was rebuilt as `' '.join(name.split())`, which agrees with the sanitiser on an ordinary name and
        disagrees on any name holding a character the sanitiser deletes - so 'Settlements: Legacy' was listed as
        'Settlements: Legacy_grid.jpg' against a file called 'Settlements Legacy_grid.jpg'. The asset name was
        recovered from the cached file's stem with `stem.split('_',1)[-1]`, a guess that only holds while the cache
        happens to prefix every filename; the cache stores each asset as `<key>.jpg` with nothing in front, so
        'header_image' came back as 'image' and 'library_hero' as 'hero'. The plain-named game below pins that
        half, and it is the one that fails on an ordinary title.
        """
        import tkinter as tk


        root = Path(_tmp_dir(self))
        cache = root / "cache"

        def sanitize(title):
            return OrganizerService._safe_name(OrganizerService.__new__(OrganizerService), title)

        def game(title):
            # The folder carries the sanitised name, because a colon cannot exist in a Windows filename - which is
            # precisely why the sanitiser is there, and why the two spellings have to be kept apart here.
            prefix = sanitize(title)
            folder = root / "Puzzle" / f"{prefix} - 1 Jan, 2026"
            folder.mkdir(parents=True)
            assets = {}
            for key in ("header_image", "library_hero", "background_raw"):
                assets[key] = self._image(cache / f"{key}.jpg")
                self._image(folder / f"{prefix}_{key}.jpg")
            grid = self._image(folder / f"{prefix}_grid.jpg")
            return (
                SimpleNamespace(
                    path=folder / f"{prefix}.7z",
                    steam=SimpleNamespace(name=title, appid="1234"),
                    user_title="",
                    display_name=title,
                    artwork=ArtworkResult(status="downloaded", path=grid, assets=assets),
                    decision=SimpleNamespace(accepted=True),
                ),
                folder,
            )

        colon, colon_folder = game("Settlements: Legacy")
        # An ordinary title, which sanitises to itself. This is the game that fails when only the asset name is
        # wrong, so the two halves of the defect are pinned by two different games rather than by one of both.
        plain, plain_folder = game("Stellar Squirrel")
        self.assertEqual(_asset_prefix_for(colon), sanitize(colon.steam.name))
        self.assertNotEqual(
            _asset_prefix_for(colon),
            colon.steam.name,
            "the prefix was not sanitised, so this test cannot fail for the reason it is here for",
        )
        window = tk.Tk()
        window.withdraw()
        self.addCleanup(window.destroy)
        view = ArtworkView(window, on_done=lambda: None)
        view.show([colon, plain])
        listed = [
            text.split("\nAssets: ", 1)[1]
            for text in _label_texts(view.inner)
            if "\nAssets: " in text
        ]
        self.assertEqual(len(listed), 2, f"the screen did not list assets for both games: {listed}")
        for folder, names in zip((colon_folder, plain_folder), listed, strict=True):
            for name in names.split(", "):
                self.assertTrue(
                    (folder / name).is_file(),
                    f"the screen names {name!r}, which is not in {folder.name}: on disk it is {sorted(p.name for p in folder.iterdir())}",
                )

    def test_extract_with_no_dest_lands_in_the_extract_folder_itself(self):
        """Reproduced before the fix: the app's own message named the path -
        `Extracted 2 file(s) to C:\\Users\\...\\Downloads\\extracted\\Extracted`.

        config.extract_folder is already the folder extracted games go in; it is what the catalog's Extract button
        writes to and what the protocol handler is restricted to. The command line appended the name again, so
        every --extract without an explicit --dest landed one level deeper than the same game extracted from the
        catalog, and both runs wrote into folders nothing else ever read.
        """
        import steam_game_organizer

        root = Path(_tmp_dir(self))
        extracted = root / "extracted"
        config = SimpleNamespace(extract_folder=extracted, settings={})
        args = SimpleNamespace(dest=None, extract=str(root / "SunTopia.zip"), zip_password="")
        with patch.object(steam_game_organizer, "_extract", return_value=SimpleNamespace(message="", ok=True)) as extract:
            steam_game_organizer._extract_to_disk(args, config, Mock())
            self.assertEqual(
                extract.call_args.args[1],
                extracted,
                f"a folder was appended to the extract folder: {extract.call_args.args[1]}",
            )

    def _undo_case(self, extra=(), owned=True):
        """A journalled organize of one game, ready for undo_last().

        `extra` adds entries to the game folder, and `owned` decides whether the run is recorded as having created
        it. The two matter separately because they are the two independent guards: a folder the run did not create
        is left alone whatever it holds, and a folder it did create is left alone if it holds anything else.
        """

        root = Path(_tmp_dir(self))
        project = root / "project"
        project.mkdir()
        # Incoming holds no archive: the run moved it out, which is the state undo_last() is called from. A file left
        # there would make `not restore.exists()` false and the undo a no-op - a fixture that proves nothing.
        source = root / "Incoming" / "SunTopia v1.0.7z"
        source.parent.mkdir()
        library = root / "Games"
        game = library / "Puzzle" / "SunTopia - 2026-01-01"
        game.mkdir(parents=True)
        organized = game / "SunTopia.7z"
        organized.write_bytes(b"7z\xbc\xaf\x27\x1c")
        (game / ".game-info.json").write_text(json.dumps({"appid": "1234", "name": "SunTopia"}), encoding="utf-8")
        for name, body in extra:
            target = game / name
            if body is None:
                target.write_bytes(b"\xff\xd8\xff\xd9")
            else:
                target.write_text(body, encoding="utf-8")
        logger = AppLogger(project / "rollback.log")
        service = RollbackService(project, logger, organizer=OrganizerService(logger))
        dirs = [str(game)] if owned else []
        self.assertTrue(
            service.record([(source, organized)], dirs),
            "the move was not journalled, so Undo has nothing to undo",
        )
        return service, source, organized, game, library

    def test_undo_removes_the_game_folders_the_run_emptied(self):
        """Reproduced over a 13-game organize: Undo restored all 13 archives and left 12 folders behind.

        The archive goes home and the folder the run created stays holding what the run wrote into it - the
        metadata, the Steam link, the artwork. It names a game it does not contain, no scan reports it, and the
        user has to delete it by hand. The decision to remove is delegated to OrganizerService._folder_is_prunable
        rather than reimplemented, so the allow-list protecting a player's saves stays in one place.
        """
        service, source, organized, game, library = self._undo_case(extra=(("SunTopia_grid.jpg", None),))
        result = service.undo_last(library)
        self.assertEqual(result["moved"], 1, f"the archive was not restored: {result}")
        self.assertEqual(result["pruned"], 1, f"the emptied folder was not pruned: {result}")
        self.assertTrue(source.is_file(), "the archive did not go home")
        self.assertFalse(
            game.exists(),
            f"Undo left the emptied game folder behind: {sorted(p.name for p in game.iterdir()) if game.is_dir() else 'the archive is back and the folder is still there'}",
        )
        self.assertTrue(library.is_dir(), "the category folder the game sat in was removed as well")

    def test_undo_leaves_a_game_folder_holding_something_it_did_not_write(self):
        """Passes either way, deliberately: a pruning rule that has only been shown to remove things is half a
        safety argument. A save file is the obvious case and it is enough."""
        service, source, organized, game, library = self._undo_case(extra=(("save.dat", "progress"),))
        service.undo_last(library)
        self.assertTrue((game / "save.dat").is_file(), f"Undo deleted a save file: {game}")
        self.assertTrue(source.is_file(), "the archive was not restored, so this case proved nothing")

    def test_undo_leaves_a_photo_the_player_saved_beside_the_game(self):
        """The allow-list judges provenance by name and suffix, and a screenshot beside a game is a .jpeg like any
        other. It used to be _folder_is_disposable(), which accepts every image suffix - correct for the download
        folder this app emptied itself, and wrong for the user's game folder, where the first version of this prune
        applied it. Verified against that version: the folder came back gone."""
        service, source, organized, game, library = self._undo_case(extra=(("my-photo.jpeg", None),))
        service.undo_last(library)
        self.assertTrue(
            (game / "my-photo.jpeg").is_file(),
            f"Undo deleted a picture the player saved: {sorted(p.name for p in game.iterdir()) if game.is_dir() else 'the whole folder is gone'}",
        )

    def test_undo_leaves_a_game_folder_the_run_did_not_create(self):
        """OrganizerService.move() reuses a category/game folder that is already there and records
        created_game_dir=False, so a source/target pair alone cannot tell the two apart. This is the same rule
        AppController._prune_rolled_back_folder() applies from the same flag; the first version of this prune had
        no equivalent and would have removed a folder the user made."""
        service, source, organized, game, library = self._undo_case(owned=False)
        result = service.undo_last(library)
        self.assertEqual(result["moved"], 1, f"the archive was not restored: {result}")
        self.assertEqual(result["pruned"], 0, f"a folder this run did not create was removed: {result}")
        self.assertTrue((game / ".game-info.json").is_file(), f"the folder was removed anyway: {game}")

    def test_undo_refuses_a_journal_row_naming_a_folder_outside_the_library(self):
        """The journal is a file in config/, and both ends of every row go from it into shutil.move and
        shutil.rmtree. undo_last() already accepted the configured library root and never looked at it."""

        root = Path(_tmp_dir(self))
        project = root / "project"
        project.mkdir()
        library = root / "Games"
        library.mkdir()
        elsewhere = root / "Photos" / "holiday"
        elsewhere.mkdir(parents=True)
        # Named the way the app names its own artwork - an underscore in the stem - so _folder_is_prunable() would
        # accept it and the containment check is the only thing refusing. A plain sunset.jpg would have been saved
        # by the stricter allow-list instead, and this test would have passed without testing what it is for.
        kept = elsewhere / "holiday_grid.jpg"
        kept.write_bytes(b"\xff\xd8\xff\xd9")
        away = elsewhere / "clip.rar"
        away.write_bytes(b"Rar!\x1a\x07\x00")
        logger = AppLogger(project / "rollback.log")
        service = RollbackService(project, logger, organizer=OrganizerService(logger))
        self.assertTrue(
            service.record([(root / "Incoming" / "clip.rar", away)], [str(elsewhere)]),
            "the row was not journalled, so this case proves nothing",
        )
        result = service.undo_last(library)
        self.assertEqual(result["pruned"], 0, f"a folder outside the library was removed: {result}")
        self.assertTrue(kept.is_file(), f"Undo deleted a folder outside the library: {sorted(elsewhere.iterdir()) if elsewhere.is_dir() else 'it is gone'}")
