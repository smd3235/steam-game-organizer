"""Regression tests for scan and library behaviour.

These tests were extracted from tests/test_regressions.py to keep each test module
focused on one area of the app: known identity regressions, New Only scanning,
and Preview Only write protection.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.config import AppConfig
from ui.main_window import MainWindow
from utils.filename_utils import identity_key, normalize_name
from core.models import ArtworkResult


def _tmp_dir(test_case):
    """A temporary directory that is cleaned up when the test finishes."""
    tmp = Path(tempfile.mkdtemp())
    test_case.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    return tmp


class TestKnownRegressionCases(unittest.TestCase):
    def test_known_identities(self):
        # 2026-11-10: "Incremental" is a legitimate game genre (idle/incremental games), so
        # "Delta Realm Incremental.zip" folds to "deltarealmincremental", not "deltarealm".
        # Replaced a real Steam game name with fictional "Nebula Online" per the
        # no-real-game-names rule (see tools/validate_game_names.py deny list).
        expected = {
            "Alpha Forge v 0 8.zip": "alphaforge",
            "Gamma Quest v 1 0.zip": "gammaquest",
            "Delta Realm Incremental.zip": "deltarealmincremental",
            "Nebula Online.zip": "nebulaonline",
        }
        for name, key in expected.items():
            self.assertEqual(identity_key(name), key, name)

    # The titles here are the real folders from one library, and every one of them failed to find its Steam name.
    # The cause was the tag stripper, not Steam: it only fired on whitespace-delimited tags, so the hyphenated
    # and dotted spellings these folders actually use survived into the search query, which then asked the store
    # for "Nebula Attracts-Steam" and never for "Nebula Attracts". The stripper is fixed and covered in
    # tests/test_filename_utils.py; this pins the outcome, so a change to the tag rules that brings any of these
    # back fails here by name.
    def test_tagged_library_folders_still_find_their_real_game(self):
        expected = {
            "Stellar.Squirrel-SteamRIP.com": "Stellar Squirrel",
            "Nebula Attracts-Steam RIP com": "Nebula Attracts",
            "Nebula Nights-Steam RIP com": "Nebula Nights",
            "Sun Topia-Steam RIP com": "Sun Topia",
        }
        for tagged, clean in expected.items():
            self.assertEqual(normalize_name(tagged), clean, tagged)
            self.assertEqual(identity_key(tagged), identity_key(clean), tagged)

    # Both the fake home and the project root hang off one temporary tree, which is the point. They used to be
    # Path('/tmp/...'), and on Windows a leading slash is not absolute - it resolves against whatever drive happens
    # to be current. So the mkdir created C:\tmp\portable-home\Downloads\Games and AppConfig rooted its config,
    # cache and log directories at C:\tmp\project-root: two directories outside this repository, on the one platform
    # whose own guard (tests/test_platform.py) forbids POSIX paths, created by the test asserting nothing is
    # hard-coded. C:\tmp is not a harmless accident either - ArtworkService deletes from whatever cache directory it
    # is handed, and a sibling test handed it C:\tmp\artwork-cache.
    def test_default_library_root_is_portable(self):
        root = Path(_tmp_dir(self))
        home = root / "portable-home"
        with patch("pathlib.Path.home", return_value=home):
            expected = home / "Downloads" / "Games"
            expected.mkdir(parents=True, exist_ok=True)
            config = AppConfig(root / "project-root")
            self.assertEqual(config.library_root, expected)

    def test_scan_done_keeps_scan_visible_until_verification_finishes(self):
        window = SimpleNamespace()
        window.closing = False
        window.views = {"scan": Mock(), "review": Mock()}
        window.views["scan"].art_var = SimpleNamespace(get=lambda: True)
        window.show = Mock()
        window.status = Mock()
        result = SimpleNamespace(archives=[object()])

        MainWindow.scan_done(window, result)

        window.views["scan"].set_result.assert_called_once_with(result)
        window.views["review"].load.assert_called_once_with(result.archives, download_artwork=True)
        window.status.configure.assert_called_once()
        window.show.assert_called_once_with("scan")

    def test_scan_new_artwork_done_routes_to_review_without_calling_end(self):
        """Reproduced before the fix: _scan_new_artwork_done called _end and stopped on Scan, so the
            newly-discovered archives were never loaded into Review and the user could not accept them."""
        from ui.main_window import MainWindow

        window = SimpleNamespace()
        window.closing = False
        window.views = {"scan": Mock(), "review": Mock()}
        window.show = Mock()
        window.status = Mock()
        archives = [object(), object()]

        MainWindow._scan_new_artwork_done(window, archives)

        window.views["scan"].finish_artwork_scan.assert_called_once_with(archives)
        window.views["review"].load.assert_called_once_with(archives, download_artwork=True)
        window.status.configure.assert_called_once()
        window.show.assert_called_once_with("scan")
        # Must NOT have called _end: verification_done owns the run termination.
        self.assertFalse(
            hasattr(window, "_end") and window._end.called,
            "_scan_new_artwork_done called _end, which would leave verification without a run guard",
        )


class TestNewOnlyWithNothingNewDoesNotBlockOnTheVerifyScreen(unittest.TestCase):
    """A New Only scan that finds nothing new must still be finishable.

    Under New Only a scan that has nothing new hands an empty list to the review screen, and the run
    is genuinely done: the audit and catalog phases already ran and wrote their pages. The CONTINUE
    button was gated on the list being non-empty, so it was disabled; Approve All Verified was itself
    disabled on an empty list, so the only button available could not be pressed and the run appeared
    to hang on the verify screen with no way to continue.
    """

    def setUp(self):
        from tests.tk_support import require_tk, close_root, sandbox_app
        require_tk(self)
        self.close_root = close_root
        import tkinter as tk

        root = tk.Tk()
        self.addCleanup(self.close_root, root)
        self.app = sandbox_app(self, root)
        self.view = self.app.window.views["review"]
        self.app.window.show("review")
        self.root = self.app.root
        self.root.update()

    def test_the_continue_button_is_enabled_on_an_empty_list(self):
        self.view.load([])
        self.root.update()
        self.assertEqual(
            str(self.view.continue_button.cget("state")),
            "normal",
            "a scan with nothing new left no way to finish the run",
        )

    def test_the_continue_button_is_disabled_while_games_are_unresolved(self):
        from core.models import GameArchive

        archive = GameArchive(
            self.app.config.library_root / "Game.zip",
            "Game",
            "game",
            "game",
            ".zip",
            (0,),
        )
        self.view.load([archive])
        self.root.update()
        self.assertEqual(str(self.view.continue_button.cget("state")), "disabled")

    def test_the_empty_list_says_the_run_is_done(self):
        self.view.load([])
        self.root.update()
        self.assertIn("CONTINUE TO ORGANIZATION", self.view.continue_button.cget("text"))
        self.assertIn("already ran", self.view.subtitle.cget("text"))


class TestPreviewOnlyDoesNotMoveAnything(unittest.TestCase):
    """Preview Only said nothing was touched, and moved an archive to Archive/.

    The scan's own two neighbouring phases are guarded by `if not preview_only` and one of them carries a comment
    naming Preview Only as the reason. This third one was not, and it is the only one of the three that writes:
    the leftover-repair pass converts in place behind the review screen, but this one files a file away.

    Confirmed live before the fix, against a real library shape:

    Game/Loop Miner v1.0.zip  +  Game/Loop Miner v2.0.zip

    enforce_single_archive() returned 1 and Loop Miner v1.0.zip turned up in Archive/ - a move, on screen, while
    the feed was reporting 'Skipped in Preview Only - no files touched'.

    Two copies of one game in a folder is the case the method exists for: people drop a second copy in by hand,
    and identity_key() compares names after normalize_name() has stripped the version, so both are one identity.
    The survivor is chosen by version, so which file disappears depends on the versions, not on the user.

    Worth being precise about the first attempt, which is why this test names its files: 'Loop Miner (1).zip' does
    NOT reproduce it, because '(1)' survives normalize_name() as a distinct word and identity_key() returns
    'loopminer1'. It is correctly treated as a second, different game. Written as '(1)' this test would have
    passed against the bug, which is the outcome to avoid.

    The scope question this note raised is now answered, and the answer is the one this release commits to:
    Preview Only writes nothing, in any phase. The audit still runs and still reports - a user wants to know what
    a real scan would find - but it writes no link, no metadata sidecar and no artwork, and its refreshed count
    is literally 0 with a separate would_refresh count naming what a real scan would have done. The catalog is
    skipped outright and the summary says so rather than silently producing nothing. Discovery's password unlock
    rewrites a protected zip in place, so under preview that archive is reported as locked and uninspectable
    instead of being opened. The three gates live beside the existing ones (cleanup, dedupe, repair) in
    app/controller.py, all on the same preview_only argument, so the mode has one definition of read-only.
    """

    def _library_with_two_versions(self, root):
        """Builds <root>/<Category>/<Game>/ holding two versions of one archive, which is the shape the sweep
        actually walks. It needs saying, because a fixture one level deeper passes against the bug: the sweep reads
        library_root/<Category>/<Game>, so a root/Games/Idle/Loop Miner tree has it treating the *category* as the
        game folder, finding no archives in it, collapsing nothing, and reporting a clean sweep. That is exactly the
        shape that made the first version of this test prove nothing."""
        from core.logger import AppLogger
        from services.library_service import LibraryService
        from services.organizer_service import OrganizerService

        root = Path(root)
        game = root / "Idle" / "Loop Miner - 2024-01-01"
        game.mkdir(parents=True)
        for name, size in (("Loop Miner v1.0.zip", 2048), ("Loop Miner v2.0.zip", 4096)):
            (game / name).write_bytes(b"PK\x03\x04" + b"0" * size)
        (game / ".game-info.json").write_text(
            json.dumps({"appid": "1", "name": "Loop Miner"}), encoding="utf-8"
        )
        log = AppLogger(root / "x.log")
        return root, LibraryService(log), OrganizerService(log, convert_archives=False)

    def test_the_duplicate_sweep_is_guarded_by_preview_only(self):
        """Asserted on the parsed source, so the guard cannot be satisfied by a word in a comment."""
        import ast

        src = Path("app/controller.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "enforce_single_archive"
        ]
        self.assertEqual(len(calls), 2, f"expected two enforce_single_archive() calls, found {len(calls)}")
    # The call inside scan() (which has a preview_only parameter) must be guarded so a preview-only
    # run never moves files. The call inside scan_new_artwork() needs no guard: that quick scan has
    # no preview_only mode and always modifies files.
        guards = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
            if "preview_only" not in names:
                continue
            if any(inner is calls[0] for inner in ast.walk(node)) or any(
                inner is calls[1] for inner in ast.walk(node)
            ):
                guards.append(node)
        self.assertTrue(guards, "at least one enforce_single_archive() call is inside a `if preview_only:` guard")

    def test_a_second_copy_in_the_folder_is_moved_when_not_previewing(self):
        """The precondition: if this did not move, the scan test below would pass for the wrong reason."""
        root = _tmp_dir(self)
        library, service, organizer = self._library_with_two_versions(root)
        self.assertEqual(service.enforce_single_archive(library, organizer), 1)
        self.assertTrue((library / "Archive").is_dir(), "no archive was filed, so the case is not being exercised")
        self.assertFalse(
            (library / "Idle" / "Loop Miner - 2024-01-01" / "Loop Miner v1.0.zip").exists(),
            "the older version was not the one filed, so this is not the move the guard is about",
        )

    def test_a_preview_only_scan_leaves_the_archives_as_it_found_it(self):
        """Driven through controller.scan(), because that is where the gate lives - the same way the neighbouring
        conversion test is, so the two phases of one scan are pinned by the same kind of evidence.

        Asserted on the archives and on Archive/, not on the folder listing. The audit phase writes a Steam link
        file in a normal scan, but under Preview Only it writes nothing (see the note above), so the folder listing is
        safe to assert on here too. Before the fix this failed with

         ['.game-info.json', 'Loop Miner v1.0.zip', 'Loop Miner v2.0.zip'] -> no Loop Miner v1.0.zip

        i.e. the older copy had been filed into Archive/ during a scan whose feed said nothing was touched."""
        from threading import Event

        from app.controller import AppController
        from app.events import EventBus
        from core.state import StateStore
        from app.jobs import JobManager
        from core.logger import AppLogger
        from services.rollback_service import RollbackService
        from services.library_service import LibraryService
        from services.archive_service import ArchiveService
        from services.artwork_service import ArtworkResult

        root = _tmp_dir(self)
        library, service, organizer = self._library_with_two_versions(root)
        game = library / "Idle" / "Loop Miner - 2024-01-01"
        archives = sorted(p.name for p in game.iterdir() if p.suffix.lower() in (".zip", ".rar", ".7z"))
        self.assertEqual(archives, ["Loop Miner v1.0.zip", "Loop Miner v2.0.zip"], "the fixture is not two archives")
        logger = AppLogger(Path(root) / "scan.log")
        jobs = JobManager()
        services = type("Services", (), {})()
        services.organizer = organizer
        services.rollback = RollbackService(Path(root), logger)
        services.library = service
        services.archive = ArchiveService(logger)
        services.artwork = type(
            "Artwork",
            (),
            {
                "download_assets": lambda *a, **k: ArtworkResult(),
                "lookup": lambda *a, **k: ArtworkResult(),
            },
        )()
        services.catalog = type("Catalog", (), {"generate": lambda *a, **k: []})()
        controller = AppController(StateStore(), EventBus(), logger, services, jobs)
        seen = []
        finished = Event()
        try:
            controller.scan(
                Path(root),
                lambda result: finished.set(),
                progress=lambda event: seen.append(event),
                preview_only=True,
            )
            self.assertTrue(finished.wait(30), "the preview scan never finished")
        finally:
            jobs.shutdown()
        self.assertEqual(
            sorted(p.name for p in game.iterdir() if p.suffix.lower() in (".zip", ".rar", ".7z")),
            archives,
            "Preview Only moved an archive out of the game folder",
        )
        self.assertFalse((library / "Archive").exists(), "Preview Only created the Archive folder")
        skipped = [e for e in seen if isinstance(e, dict) and e.get("stage") == "dedupe_done" and e.get("skipped")]
        self.assertEqual(len(skipped), 1, f"the scan did not report the sweep as skipped: {seen}")
        # The rest of the scan still has to run: the first version of this fix returned early out of the phase, which
        # left discovery, the audit and the catalog silent while every phase above still reported itself.
        for stage in ("discover_done", "audit_done", "catalog_done"):
            self.assertTrue(
                [e for e in seen if isinstance(e, dict) and e.get("stage") == stage],
                f"{stage} never ran, so the scan was cut short: {[e.get('stage') for e in seen if isinstance(e, dict)]}",
            )

    def test_a_preview_only_scan_leaves_every_file_byte_identical(self):
        """The strongest form: a full snapshot of every file under root is compared after the scan."""
        from services.extract_service import ExtractService
        from app.controller import AppController
        from app.events import EventBus
        from core.state import StateStore
        from app.jobs import JobManager
        from core.logger import AppLogger
        from services.rollback_service import RollbackService
        from services.library_service import LibraryService
        from services.archive_service import ArchiveService
        from services.organizer_service import OrganizerService

        root = Path(_tmp_dir(self))
        category = root / "Idle"
        category.mkdir()
        game = category / "Loop Miner - 2024-01-01"
        game.mkdir()
        archive = game / "Loop Miner v1.0.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("game.txt", "data")
        (game / ".game-info.json").write_text(json.dumps({"appid": "1", "name": "Loop Miner"}), encoding="utf-8")
        (game / "Loop Miner_grid.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        tool = ExtractService.find_tool()[0]
        if not tool:
            self.fail("7-Zip is required to build an encrypted fixture zip and was not found")
        payload = root / "payload"
        payload.mkdir()
        (payload / "Game Folder").mkdir()
        (payload / "Game Folder" / "main.exe").write_bytes(b"binary" * 400)
        encrypted = root / "encrypted.zip"
        built = subprocess.run(
            [tool, "a", "-tzip", "-p123", "-bso0", "-bsp0", str(encrypted), str(payload)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
        )
        self.assertEqual(built.returncode, 0, f"could not build the encrypted fixture: {built.stderr!r}")
        with zipfile.ZipFile(encrypted) as source:
            self.assertTrue(
                any(i.flag_bits & 0x1 for i in source.infolist() if not i.is_dir()),
                "the fixture is not encrypted, so this test proves nothing",
            )
        shutil.move(str(encrypted), str(game / "locked.zip"))
        before = sorted(
            (p.relative_to(root), p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob("*")
            if p.is_file()
        )
        log_dir = Path(_tmp_dir(self))
        logger = AppLogger(log_dir / "scan.log")
        jobs = JobManager()
        services = type("Services", (), {})()
        organizer = OrganizerService(logger, convert_archives=False)
        services.organizer = organizer
        services.rollback = RollbackService(log_dir, logger)
        services.library = LibraryService(logger)
        services.archive = ArchiveService(logger)
        services.artwork = type(
            "Artwork",
            (),
            {
                "download_assets": lambda *a, **k: ArtworkResult(),
                "lookup": lambda *a, **k: ArtworkResult(),
            },
        )()
        catalog_calls = []

        class RecordingCatalog:
            def generate(self, *a, **k):
                catalog_calls.append((a, k))
                return []

        services.catalog = RecordingCatalog()
        controller = AppController(StateStore(), EventBus(), logger, services, jobs)
        finished = threading.Event()
        try:
            controller.scan(
                root,
                lambda result: finished.set(),
                progress=lambda event: None,
                preview_only=True,
            )
            self.assertTrue(finished.wait(30), "the preview scan never finished")
        finally:
            jobs.shutdown()
        after = sorted(
            (p.relative_to(root), p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob("*")
            if p.is_file()
        )
        self.assertEqual(before, after, "Preview Only changed a file in the library root")
        self.assertFalse(catalog_calls, "catalog.generate was called under Preview Only")

    def test_a_normal_scan_writes_artwork_and_generates_the_catalog(self):
        """The precondition: if this did not write anything, the preview test above would pass for the wrong reason."""
        from app.controller import AppController
        from app.events import EventBus
        from core.state import StateStore
        from app.jobs import JobManager
        from core.logger import AppLogger
        from services.rollback_service import RollbackService
        from services.library_service import LibraryService
        from services.archive_service import ArchiveService
        from services.artwork_service import ArtworkResult
        from services.organizer_service import OrganizerService

        root = Path(_tmp_dir(self))
        category = root / "Idle"
        category.mkdir()
        game = category / "Loop Miner - 2024-01-01"
        game.mkdir()
        archive = game / "Loop Miner v1.0.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("game.txt", "data")
        (game / ".game-info.json").write_text(
            json.dumps({"appid": "1", "name": "Loop Miner"}), encoding="utf-8"
        )
        (game / "Loop Miner_grid.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        before = sorted(
            (p.relative_to(root), p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob("*")
            if p.is_file()
        )
        logger = AppLogger(Path(root) / "scan.log")
        jobs = JobManager()
        services = type("Services", (), {})()
        organizer = OrganizerService(logger, convert_archives=False)
        services.organizer = organizer
        services.rollback = RollbackService(Path(root), logger)
        services.library = LibraryService(logger)
        services.archive = ArchiveService(logger)
        services.artwork = type(
            "Artwork",
            (),
            {
                "download_assets": lambda *a, **k: ArtworkResult(),
                "lookup": lambda *a, **k: ArtworkResult(),
            },
        )()
        catalog_calls = []

        class RecordingCatalog:
            def generate(self, *a, **k):
                catalog_calls.append((a, k))
                return ["catalog.html"]

        services.catalog = RecordingCatalog()
        controller = AppController(StateStore(), EventBus(), logger, services, jobs)
        finished = threading.Event()
        try:
            controller.scan(
                root,
                lambda result: finished.set(),
                progress=lambda event: None,
                preview_only=False,
            )
            self.assertTrue(finished.wait(30), "the normal scan never finished")
        finally:
            jobs.shutdown()
        after = sorted(
            (p.relative_to(root), p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob("*")
            if p.is_file()
        )
        self.assertNotEqual(before, after, "a normal scan left the library root unchanged")
        self.assertTrue(catalog_calls, "catalog.generate was not called in a normal scan")
        self.assertTrue((game / "Open Steam Page.html").exists(), "a normal scan did not write the Steam link")
