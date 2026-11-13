"""Extracted from tests/test_services.py.

    TestTheEmptiedSourceFolderIsOnlyRemovedWhenItIsOurs was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from core.logger import AppLogger
from core.models import GameArchive
from services.organizer_service import OrganizerService


class TestTheEmptiedSourceFolderIsOnlyRemovedWhenItIsOurs(unittest.TestCase):
    """`shutil.rmtree` removes a tree without asking, so an allow-list stands in front of it.

    Organizing an archive out of a folder that this app did not file used to delete whatever else was in
    that folder: a save, a notes file, a mods directory, a launcher config. The run reported success. The
    function's own comment and the README both promised the opposite - that anything unexpected prevents
    removal - and only two of the promised guards existed: not a managed game folder, and no archive left
    anywhere inside. A player's own files satisfied both and were removed anyway.

    The whole set is here rather than the one deletion, because the allow-list is only as good as the
    entries that veto it, and the entries are what a later change would get wrong.
    """

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name) / "Games"
        self.service = OrganizerService(AppLogger(Path(self.folder.name) / "log.log"))

    def _source(self, *contents):
        """A category folder holding one archive, plus whatever else the test needs beside it."""
        source = self.root / "Action" / "Cool Game"
        source.mkdir(parents=True)
        archive = source / "Cool Game.zip"
        archive.write_bytes(b"PK\x03\x04" + b"0" * 512)
        for name in contents:
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("player data") if path.suffix != ".zip" else path.write_bytes(b"PK\x03\x04" + b"1" * 64)
        return archive

    def _organize(self, archive):
        record = GameArchive(archive, "Cool Game", "cool game", "coolgame", ".zip", size=archive.stat().st_size)
        record.user_title = "Cool Game"
        return self.service.move(record, self.root)

    def test_a_save_beside_the_archive_is_not_deleted(self):
        archive = self._source("my-save.dat")
        self._organize(archive)
        self.assertTrue((archive.parent / "my-save.dat").is_file(), "organizing one archive out of a folder deleted the player save next to it")
        self.assertTrue(archive.parent.is_dir(), "the folder was removed although it held a file we did not write")

    def test_a_notes_file_beside_the_archive_is_not_deleted(self):
        archive = self._source("notes.txt")
        self._organize(archive)
        self.assertTrue((archive.parent / "notes.txt").is_file())

    def test_a_subdirectory_beside_the_archive_is_not_deleted(self):
        archive = self._source("mods/config.ini")
        self._organize(archive)
        self.assertTrue((archive.parent / "mods" / "config.ini").is_file(), "a subdirectory vetoes removal on sight; rmtree would take its contents with it")

    def test_an_unexpected_file_anywhere_vetoes_the_whole_folder(self):
        """One unrecognised entry is enough. A partial cleanup is not a safer cleanup."""
        archive = self._source("Cool Game_grid.jpg", "notes.txt")
        self._organize(archive)
        self.assertTrue((archive.parent / "Cool Game_grid.jpg").is_file(), "the artwork was removed even though an unrecognised file was vetoing the folder")

    def test_an_empty_folder_is_still_cleaned_up(self):
        """The reason the function exists at all: not leaving a nameless folder per organized game."""
        archive = self._source()
        source = archive.parent
        self._organize(archive)
        self.assertFalse(source.exists(), "the folder was left behind holding nothing")

    def test_a_folder_holding_only_our_own_artwork_is_cleaned_up(self):
        """Recognised artwork is the one unrecognised-looking thing this app does put in a folder.

        Only pictures. A shortcut file would also be on the allow-list, but `Open Steam Page.html` is a
        managed-folder marker first, so a folder holding one is kept by that rule and never reaches this one.
        """
        archive = self._source("Cool Game_grid.jpg", "cover.png")
        source = archive.parent
        self._organize(archive)
        self.assertFalse(source.exists(), "a folder left holding only recognised artwork was not cleaned up")

    def test_a_second_archive_is_never_removed_with_the_folder(self):
        archive = self._source("Cool Game (1).zip")
        source = archive.parent
        self._organize(archive)
        self.assertTrue((source / "Cool Game (1).zip").is_file(), "an archive was still inside and the folder went anyway")

    def test_an_organized_game_folder_holding_only_its_marker_is_removed(self):
        """The marker no longer refuses outright; it routes to the prunable rule.

        A folder this app filed is still the player's - a screenshot ends up beside the game - so
        "never delete a game folder" was wrong in both directions. The folder is judged by
        contents: it is ours to remove only when every entry in it is something this app put
        there. A marker alone is exactly that, so the folder goes - which is what the re-categorise
        case needs. The old test asserted the opposite and was the rule that left the folder
        behind holding the image the app wrote.
        """
        game = self.root / "Action" / "Cool Game - 2020-01-01"
        game.mkdir(parents=True)
        (game / ".game-info.json").write_text("{}", encoding="utf-8")
        archive = game / "Cool Game.zip"
        archive.write_bytes(b"PK" + b"0" * 512)
        self._organize(archive)
        self.assertFalse(game.exists(), "a game folder holding only the app marker was left behind")

    def test_an_organized_game_folder_is_removed_when_only_app_artwork_is_left_in_it(self):
        """Re-categorising a game moves its archive out of the folder it was filed into.

        The folder carries the markers, so the old rule refused it outright and every scan reported
        it as an empty game with no archive, holding the image the app wrote. A folder this app
        filed is still the player's - a screenshot ends up beside the game - so the decision is
        delegated to the prunable rule rather than made by the marker alone: it is ours to remove
        only when every entry in it is something this app put there.
        """
        game = self.root / "Action" / "Cool Game - 2020-01-01"
        game.mkdir(parents=True)
        (game / ".game-info.json").write_text("{}", encoding="utf-8")
        archive = game / "Cool Game.zip"
        archive.write_bytes(b"PK\x03\x04" + b"0" * 512)
        (game / "Cool Game_grid.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        self._organize(archive)
        self.assertFalse(game.exists(), "re-categorising a game left its old folder behind holding the app artwork")

    def test_an_organized_game_folder_holding_a_screenshot_is_not_removed(self):
        """The prunable rule judges provenance by name, and a screenshot is a .jpeg like any other."""
        game = self.root / "Action" / "Cool Game - 2020-01-01"
        game.mkdir(parents=True)
        (game / ".game-info.json").write_text("{}", encoding="utf-8")
        archive = game / "Cool Game.zip"
        archive.write_bytes(b"PK\x03\x04" + b"0" * 512)
        (game / "screenshot.jpeg").write_bytes(b"\xff\xd8\xff\xd9")
        self._organize(archive)
        self.assertTrue(game.is_dir(), "re-categorising a game deleted a folder holding a screenshot")
        self.assertTrue((game / "screenshot.jpeg").is_file(), "the screenshot was removed with the folder")

    def test_the_library_root_and_a_category_folder_are_never_removed(self):
        """An archive filed straight into a category, or straight into the root, is a real layout.

        Both containers are rejected on structure rather than contents: the root is the destination, and a
        category's parent is. Checking contents would have been the wrong rule - a category folder that
        happens to hold nothing but recognised artwork would satisfy it.
        """
        for container in (self.root, self.root / "Action"):
            with self.subTest(container=container.name):
                container.mkdir(parents=True, exist_ok=True)
                archive = container / "Loose.zip"
                archive.write_bytes(b"PK\x03\x04" + b"0" * 512)
                self._organize(archive)
                self.assertTrue(container.is_dir(), f"{container.name} was removed by organizing a loose archive out of it")
