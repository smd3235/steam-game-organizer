"""Extracted from tests/test_batch_extract.py.

    PlanningABatchKnowsWhatItWouldDo was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import tempfile
import unittest
import zipfile
from pathlib import Path
from core.logger import AppLogger
from tests.test_batch_extract import _game
from services.batch_extract_service import plan_batch


class PlanningABatchKnowsWhatItWouldDo(unittest.TestCase):
    """plan_batch runs before anything is unpacked, so the window can state the real count and size first."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "Games"
        self.dest = Path(temporary.name) / "Out"
        self.dest.mkdir(parents=True)
        self.logger = AppLogger(Path(temporary.name) / "x.log")
        _game(self.root, "Idle", "Loop Miner", 4096)
        _game(self.root, "Idle", "Fellwood", 4096)
        _game(self.root, "RPG", "Deep Signal", 4096)

    def _plan(self, category="", **kwargs):
        return plan_batch(self.root, self.dest, category, self.logger, **kwargs)

    def test_a_category_plan_covers_that_category_only(self):
        plan = self._plan("Idle")
        self.assertEqual(sorted(item.name for item in plan.items), ["Fellwood", "Loop Miner"])
        self.assertEqual(plan.category, "Idle")

    def test_a_whole_library_plan_covers_every_category(self):
        plan = self._plan()
        self.assertEqual(sorted(item.name for item in plan.items), ["Deep Signal", "Fellwood", "Loop Miner"])

    def test_the_plan_states_a_total_size_rather_than_leaving_the_window_to_add_it_up(self):
        plan = self._plan()
        self.assertGreater(plan.total_bytes, 0)
        self.assertEqual(plan.total_bytes, sum(item.size for item in plan.items))

    def test_two_games_with_one_name_do_not_land_in_one_folder(self):
        """A .7z and a .zip of the same title in different categories normalise to the same stem, and would
        otherwise unpack into one folder and interleave. The folder comes from the stem, so the collision has to
        be broken there."""
        _game(self.root, "RPG", "Loop Miner", 4096)
        folders = [item.destination for item in self._plan().items]
        self.assertEqual(len(folders), len(set(folders)), f"two games share a destination: {folders}")

    def test_an_already_unpacked_game_is_skipped_and_counted(self):
        """Otherwise Extract all on a shelf of 176 re-unpacks everything already unpacked on every click, and
        the button stops being usable after the first hour."""
        first = self._plan("Idle").items[0]
        first.destination.mkdir(parents=True)
        (first.destination / "already here.bin").write_bytes(b"x" * 10)
        second = self._plan("Idle")
        self.assertEqual(len(second.items), 1)
        self.assertEqual(second.already_done, 1)

    def test_an_empty_folder_is_not_treated_as_finished(self):
        """An interrupted run leaves the folder behind. Treating that as done would silently skip the one game
        the user most wants finished - the one it died on."""
        self._plan("Idle").items[0].destination.mkdir(parents=True)
        self.assertEqual(len(self._plan("Idle").items), 2, "an empty folder counted as already extracted")

    def test_the_destination_is_the_parent_and_each_game_gets_a_folder_inside_it(self):
        plan = self._plan("Idle")
        for item in plan.items:
            self.assertEqual(item.destination.parent, self.dest, "a game's folder is not inside the requested destination")

    def test_an_installer_archive_gets_a_needs_install_destination(self):
        """An installer archive (setup.exe + .bin) must land in <dest>/Needs Install/, not crash plan_batch.

        NEEDS_INSTALL_DIRNAME was a bare str, so `NEEDS_INSTALL_DIRNAME / leaf` raised TypeError whenever any
        archive in the batch was detected as an installer. That crashed plan_batch before the window opened,
        which is why Extract all on a library with repacks silently produced no UI at all.
        """
        from services.installer_detect import NEEDS_INSTALL_DIRNAME

        folder = self.root / "Idle" / "Repack Game - 2024-01-01"
        folder.mkdir(parents=True, exist_ok=True)
        archive = folder / "Repack Game.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as handle:
            handle.writestr("setup.exe", b"x" * 100)
            handle.writestr("game.bin", b"y" * 4096)
        (folder / ".game-info.json").write_text('{"appid":"1","name":"Repack Game","genres":["RPG"]}', encoding="utf-8")
        plan = self._plan("Idle")
        installers = [item for item in plan.items if NEEDS_INSTALL_DIRNAME in item.destination.parts]
        self.assertTrue(installers, "no item placed under Needs Install/")
        self.assertEqual(len(plan.items), 3)
        for item in installers:
            self.assertIn(NEEDS_INSTALL_DIRNAME, item.destination.parts)
