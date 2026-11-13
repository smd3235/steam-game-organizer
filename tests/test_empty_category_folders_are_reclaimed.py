"""Extracted from tests/test_cleanup_regressions.py.

    TestEmptyCategoryFoldersAreReclaimed was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from core.logger import AppLogger
from services.library_service import LibraryService


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
