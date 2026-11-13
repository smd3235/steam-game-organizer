"""Regression tests for the leftover cleanup sweep.

These tests were extracted from tests/test_regressions.py to keep each test module
focused on one area of the app: cleanup of empty categories, Syncthing temp files,
junction safety, and re-categorise leftovers.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from core.logger import AppLogger
from services.library_service import LibraryService
from utils.treewalk import is_link


def _tmp_dir(test_case):
    """A temporary directory that is cleaned up when the test finishes."""
    import tempfile as _tf

    tmp = Path(_tf.mkdtemp())
    test_case.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    return tmp


class TestSyncthingTempFilesAreCleanedUp(unittest.TestCase):
    """Syncthing writes its in-flight transfers under two different names, and only one was recognised.

    Found in the real library, not in a fixture: three files sat in the library root named

        ~syncthing~Game Library (Steam Deck) - 2026-10-02 115241.html.tmp   (399 KB)
        ~syncthing~Game Library (Windows) - 2026-10-02 115241.html.tmp     (396 KB)
        ~syncthing~Open Game Library (Steam Deck).desktop.tmp             (335 bytes)

    `SYNC_FILE_PATTERNS` listed `*.syncthing.*.tmp` - the tilde-free infix form - so cleanup walked straight past
    all three. They had been there two days. The irony is that the stranded files are named after the old
    Steam Deck catalogs, so the very artifacts this app was supposed to be deleting are the ones it kept.

    Nothing had noticed because every test used the infix spelling, which is the one form the code handles.
    """

    def _service(self, root):
        return LibraryService(AppLogger(Path(root) / "x.log"))

    def _debris(self, root, name):
        path = Path(root) / name
        path.write_text("x" * 4096)
        # Aged past any grace period, so only the pattern can decide whether it is removed.
        old = time.time() - 30 * 24 * 3600
        os.utime(path, (old, old))
        return path

    def test_the_tilde_spelling_is_recognised(self):
        for name in (
            "~syncthing~Game Library (Steam Deck) - 2026-10-02 115241.html.tmp",
            "~syncthing~Open Game Library (Steam Deck).desktop.tmp",
            "~syncthing~game.7z.tmp",
        ):
            with self.subTest(name=name):
                root = Path(_tmp_dir(self))
                debris = self._debris(root, name)
                self._service(root).cleanup_leftovers(root, grace_seconds=0)
                self.assertFalse(debris.exists(), f"{name} was left behind; cleanup does not match this spelling")

    def test_the_infix_spelling_still_works(self):
        """Both spellings, because the fix must not have been to swap one for the other."""
        root = Path(_tmp_dir(self))
        debris = self._debris(root, "game.7z.syncthing.abc.tmp")
        self._service(root).cleanup_leftovers(root, grace_seconds=0)
        self.assertFalse(debris.exists(), "the spelling that already worked stopped being cleaned up")

    def test_a_transfer_still_in_flight_is_left_alone(self):
        """The grace period is the reason any of this is safe, so it is asserted for the new pattern too.

        A '~syncthing~' file that is minutes old may be an in-flight transfer on the other machine, and deleting it
        would destroy the copy being written.
        """
        root = Path(_tmp_dir(self))
        live = root / "~syncthing~game.7z.tmp"
        live.write_text("x" * 4096)
        self._service(root).cleanup_leftovers(root, grace_seconds=3600)
        self.assertTrue(live.exists(), "a transfer that is still in flight was deleted")

    def test_a_real_game_file_is_never_matched(self):
        """The pattern is a prefix, so it is worth proving it cannot reach a game archive."""
        root = Path(_tmp_dir(self))
        keep = root / "~syncthing notes.txt"
        keep.write_text("x")
        self._service(root).cleanup_leftovers(root, grace_seconds=0)
        self.assertTrue(keep.exists(), "a file merely starting with ~syncthing~ was deleted")


class TestCleanupDoesNotLeaveTheLibraryThroughAJunction(unittest.TestCase):
    """cleanup_leftovers() deleted a file that was never in the library.

    os.walk(followlinks=False) is documented not to follow symlinks, and the walk here relied on that. A Windows
    junction is not a symlink - Path.is_symlink() answers False for one, because the OS hands it back as an
    ordinary directory - so os.walk stepped straight through it. Everything reached that way is outside the
    folder the caller passed as the library root, and this is the one walk in the app that deletes what it finds.

    Confirmed live before the fix, in a temp directory:

        library/linked/  -> junction -> elsewhere/
        elsewhere/~syncthing~orphan.tmp   4096 bytes

    cleanup_leftovers() reported removed=1, and the file on the far side of the junction was gone. A file matched
    by name in a neighbouring folder, which a Syncthing setup makes routine, was destroyed by a routine scan.

    This is deliberately the opposite of the rule tests/test_services.py pins for scanning, where a junction to a
    sibling folder IS followed: reading a sibling folder through a link finds games the user meant to include, and
    refusing it would hide them. Deleting is not symmetric. The caller named one folder as the boundary, and a link
    is a way out of it, not a road inside.
    """

    def _link_directory(self, link, target):
        # Fails rather than skips: a skipped test here would report the library safe on the one platform where the
        # link is a junction rather than a symlink, which is the platform this defect needs.
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, timeout=30)
        if made.returncode == 0:
            return "junction"
        try:
            link.symlink_to(target, target_is_directory=True)
            return "symlink"
        except OSError as exc:
            self.fail(f"no way to make a directory link on this machine: {exc}")

    def _service(self, root):
        return LibraryService(AppLogger(Path(root) / "x.log"))

    def test_a_matching_file_behind_a_junction_survives(self):
        root = Path(_tmp_dir(self))
        library = root / "Games"
        library.mkdir()
        elsewhere = root / "Elsewhere"
        elsewhere.mkdir()
        victim = elsewhere / "~syncthing~orphan.tmp"
        victim.write_text("x" * 4096)
        old = time.time() - 30 * 24 * 3600
        os.utime(victim, (old, old))
        kind = self._link_directory(library / "linked", elsewhere)
        # A file the walk would find and the pattern would match, reached only by walking through the link.
        inside = library / "stale.7z.syncthing.abc.tmp"
        inside.write_text("x" * 4096)
        os.utime(inside, (old, old))
        self.assertTrue(
            any(p.name == victim.name for p in library.rglob("*")),
            f"the {kind} does not lead to the victim, so nothing would have been deleted",
        )
        self._service(root).cleanup_leftovers(library, grace_seconds=0)
        self.assertTrue(
            victim.exists(),
            f"cleanup deleted a {kind} and removed a file {victim} that was outside the library root",
        )
        self.assertFalse(inside.exists(), "the leftover actually inside the library was left behind by the fix")

    def test_a_junction_named_like_our_own_temp_folder_is_declined(self):
        """A link matching this app's own temp-folder names is declined, and the decline is visible.

        The content behind such a link was never actually at risk: shutil.rmtree() raises OSError on a Windows
        junction rather than descending it, so the folder survived by accident and cleanup logged
        LEFTOVER_REMOVE_FAILED while reporting a successful sweep. That is a warning about a folder the app did
        not create, on a scan the user reads as a routine clean-up - and it is the only warning in the pass that
        is not about something real.

        So what the fix changes is not the outcome but the intent: the link is recognised and counted, instead of
        attempted, failed, and reported as an error. Asserted on both halves, because either alone would pass
        against the old code - the content check alone passes there too.
        """
        root = Path(_tmp_dir(self))
        library = root / "Games"
        library.mkdir()
        precious = root / "Do Not Touch"
        precious.mkdir()
        (precious / "save.dat").write_text("x" * 4096)
        self._link_directory(library / ".organizer-repack-stale", precious)
        summary = self._service(root).cleanup_leftovers(library, grace_seconds=0)
        self.assertTrue(
            (precious / "save.dat").exists(), "cleanup reached through a link named as one of its own temp folders"
        )
        self.assertEqual(summary.get("skipped_links"), 1, f"the link was not counted as declined: {summary}")
        logged = (root / "x.log").read_text(encoding="utf-8", errors="replace")
        self.assertNotIn(
            "LEFTOVER_REMOVE_FAILED",
            logged,
            f"a link was attempted and then failed, instead of being declined up front: {logged[-400:]}",
        )

    def test_the_summary_reports_what_it_declined_to_walk(self):
        """A skipped junction is invisible otherwise - removed=0 and bytes_freed=0 read identically to 'nothing to
        do', which is how a library full of links could report a clean sweep for ever."""
        root = Path(_tmp_dir(self))
        library = root / "Games"
        library.mkdir()
        elsewhere = root / "Elsewhere"
        elsewhere.mkdir()
        (elsewhere / "~syncthing~orphan.tmp").write_text("x" * 4096)
        self._link_directory(library / "linked", elsewhere)
        summary = self._service(root).cleanup_leftovers(library, grace_seconds=0)
        self.assertEqual(summary.get("skipped_links"), 1, f"the junction was not reported as declined: {summary}")

    def test_is_link_says_no_to_a_plain_folder(self):
        """The fix must not turn cleanup into a no-op: a real temp folder, matched by name and old enough, still
        goes. is_link() is on the path of every deletion, so a false positive here would silently disable cleanup."""
        root = Path(_tmp_dir(self))
        junk = root / ".organizer-unzip-gone"
        junk.mkdir()
        (junk / "part.bin").write_text("x" * 4096)
        plain = root / "notes.txt"
        plain.write_text("x")
        self.assertFalse(is_link(junk), "an ordinary folder was reported as a link")
        self.assertFalse(is_link(plain), "an ordinary file was reported as a link")
        self._service(root).cleanup_leftovers(root, grace_seconds=0)
        self.assertFalse(junk.exists(), "a genuine leftover inside the library stopped being cleaned up")


class TestEmptyCategoryFoldersAreReclaimed(unittest.TestCase):
    """A category folder with no game in it is removed.

    Re-categorising a game moves its archive out of the folder it was filed into, and that folder was
    kept carrying the Steam link, the metadata and the artwork the organizer wrote. Every scan walked it
    as a game folder with no archive and reported it as a scan problem, and the catalog page showed an empty
    category with a broken Extract button. The leftover sweep only ever matched temp artefacts and
    Syncthing files by name, so it never touched these, and the app had no pass for them at all.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.service = LibraryService(AppLogger(self.tmp / "x.log"))

    def test_an_empty_category_is_removed(self):
        library = self.tmp / "Games"
        library.mkdir()
        action = library / "Action"
        action.mkdir()
        (action / ".game-info.json").write_text("{}", encoding="utf-8")
        (action / "Open Steam Page.html").write_text("x")
        summary = self.service.cleanup_leftovers(library, grace_seconds=0)
        self.assertEqual(
            summary.get("empty_categories_removed"), 1, f"the empty category was not removed: {summary}"
        )
        self.assertFalse(action.exists(), "the empty category folder was left behind")

    def test_a_category_holding_an_archive_is_not_removed(self):
        library = self.tmp / "Games"
        library.mkdir()
        action = library / "Action"
        action.mkdir()
        (action / "Loop Miner.zip").write_bytes(b"PK\x03\x04" + b"0" * 512)
        summary = self.service.cleanup_leftovers(library, grace_seconds=0)
        self.assertEqual(
            summary.get("empty_categories_removed"), 0, f"a category holding an archive was removed: {summary}"
        )
        self.assertTrue(action.exists(), "a category holding an archive was deleted")

    def test_the_reserved_folders_and_the_app_folder_are_not_removed(self):
        library = self.tmp / "Games"
        library.mkdir()
        (library / "Archive").mkdir()
        (library / "Processing").mkdir()
        app = library / "Steam Game Organizer"
        app.mkdir()
        (app / "steam_game_organizer.py").write_text("# stub\n")
        summary = self.service.cleanup_leftovers(library, grace_seconds=0)
        self.assertEqual(
            summary.get("empty_categories_removed"), 0, f"a reserved folder or the app folder was removed: {summary}"
        )
        self.assertTrue((library / "Archive").exists())
        self.assertTrue((library / "Processing").exists())
        self.assertTrue(app.exists(), "the app project folder was deleted")

    def test_a_category_holding_a_game_subfolder_is_not_removed(self):
        # A subfolder holding a real game - an archive, which is what makes it a game rather than a
        # leftover - keeps the category. The sweep prunes empty game folders, so the distinction is
        # the archive: a folder with one stays, a folder with only app artefacts goes.
        library = self.tmp / "Games"
        library.mkdir()
        action = library / "Action"
        action.mkdir()
        (action / "Loop Miner - 2020-01-01").mkdir()
        (action / "Loop Miner - 2020-01-01" / "Loop Miner.zip").write_bytes(b"PK\x03\x04" + b"0" * 512)
        summary = self.service.cleanup_leftovers(library, grace_seconds=0)
        self.assertEqual(
            summary.get("empty_categories_removed"), 0, f"a category holding a game was removed: {summary}"
        )
        self.assertTrue(action.exists(), "a category holding a game was deleted")


class TestReCategoriseLeftoversAreReclaimed(unittest.TestCase):
    """A game moved to another category leaves its old folder behind, and the sweep reclaims it.

    Re-categorising a game moves its archive out of the folder it was filed into. The folder stays
    carrying the Steam link, the metadata and the artwork the organizer wrote, and every scan walks it
    as a game folder with no archive and reports it as a scan problem. The category that held it is
    then left holding only those empty game folders, and the catalog page shows an empty category with
    a broken Extract button. The leftover sweep only ever matched temp artefacts and Syncthing files by
    name, so it never touched these, and the app had no pass for them at all.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.service = LibraryService(AppLogger(self.tmp / "x.log"))

    def _game(self, category, name):
        game = self.tmp / "Games" / category / name
        game.mkdir(parents=True)
        (game / ".game-info.json").write_text("{}", encoding="utf-8")
        (game / "Open Steam Page.html").write_text("x")
        (game / (name + "_grid.jpg")).write_bytes(b"\xff\xd8\xff\xd9")
        (game / (name + "_header_image.jpg")).write_bytes(b"\xff\xd8\xff\xd9")
        return game

    def test_a_category_holding_only_leftover_game_folders_is_removed(self):
        puzzle = self._game("Puzzle", "TerraScape - 2024-07-17")
        self._game("Puzzle", "Twisted Tower - 2026-08-18")
        summary = self.service.cleanup_leftovers(self.tmp / "Games", grace_seconds=0)
        self.assertEqual(summary.get("empty_categories_removed"), 1, f"the category was not reclaimed: {summary}")
        self.assertFalse((self.tmp / "Games" / "Puzzle").exists(), "the category holding only leftover game folders was left behind")
        self.assertFalse(puzzle.exists(), "the leftover game folder was left behind")

    def test_a_leftover_game_folder_holding_a_save_file_is_not_removed(self):
        game = self._game("Puzzle", "TerraScape - 2024-07-17")
        (game / "save.dat").write_text("x")
        summary = self.service.cleanup_leftovers(self.tmp / "Games", grace_seconds=0)
        self.assertEqual(summary.get("empty_categories_removed"), 0, f"a category holding a player file was reclaimed: {summary}")
        self.assertTrue(game.exists(), "a game folder holding a save file was deleted")

    def test_a_leftover_game_folder_holding_a_screenshot_is_not_removed(self):
        game = self._game("Puzzle", "TerraScape - 2024-07-17")
        (game / "screenshot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        summary = self.service.cleanup_leftovers(self.tmp / "Games", grace_seconds=0)
        self.assertEqual(summary.get("empty_categories_removed"), 0, f"a category holding a screenshot was reclaimed: {summary}")
        self.assertTrue(game.exists(), "a game folder holding a screenshot was deleted")

    def test_a_leftover_game_folder_holding_an_archive_is_not_removed(self):
        game = self._game("Puzzle", "TerraScape - 2024-07-17")
        (game / "TerraScape.zip").write_bytes(b"PK\x03\x04" + b"0" * 512)
        summary = self.service.cleanup_leftovers(self.tmp / "Games", grace_seconds=0)
        self.assertEqual(summary.get("empty_categories_removed"), 0, f"a category holding an archive was reclaimed: {summary}")
        self.assertTrue(game.exists(), "a game folder holding an archive was deleted")
