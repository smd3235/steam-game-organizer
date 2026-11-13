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


# TestCleanupDoesNotLeaveTheLibraryThroughAJunction extracted to tests\test_cleanup_does_not_leave_the_library_through_a_junction.py — see that module for its definition.
# Imported after _tmp_dir is defined because that module imports it from here,
# which would otherwise be a circular import.
from tests.test_cleanup_does_not_leave_the_library_through_a_junction import TestCleanupDoesNotLeaveTheLibraryThroughAJunction
# TestEmptyCategoryFoldersAreReclaimed extracted to tests\test_empty_category_folders_are_reclaimed.py — see that module for its definition.
from tests.test_empty_category_folders_are_reclaimed import TestEmptyCategoryFoldersAreReclaimed
# TestSyncthingTempFilesAreCleanedUp extracted to tests\test_syncthing_temp_files_are_cleaned_up.py — see that module for its definition.
from tests.test_syncthing_temp_files_are_cleaned_up import TestSyncthingTempFilesAreCleanedUp

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
