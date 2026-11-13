"""Extracted from tests/test_end_to_end.py.

    SevenZipSourceIsRepackedAfterRenaming was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import pytest
import shutil
import subprocess
import tempfile
import unittest
from tests.test_helpers import build_game_tree
from tests.test_helpers import manifest
from tests.test_helpers import package_seven_zip
from tests.test_helpers import run_organize
from tests.test_helpers import seven_zip
from pathlib import Path


class SevenZipSourceIsRepackedAfterRenaming(unittest.TestCase):
    """A real .7z whose content folder is generically named gets renamed and rebuilt.

    This is the shape almost every archive the app converts has, and it is the path the 9.16 directory-counting
    defect broke: the source is a .7z, so its own index carries directory entries, and the guard that read that
    index was counting them as files and refusing the conversion. A zip source cannot show it, because `zipfile`
    stores no directory entries at all.
    """

    @classmethod
    def setUpClass(cls):
        cls.tool = seven_zip()
        cls.scratch = Path(tempfile.mkdtemp(prefix="e2e-7z-"))
        cls.library = cls.scratch / "Games"
        staging = cls.scratch / "built"
        # `Game` is the only name the app recognises as a wrapper folder worth renaming.
        build_game_tree(staging, "Game")
        game_dir = cls.library / "Some Game"
        game_dir.mkdir(parents=True)
        cls.source = game_dir / "Some Game.7z"
        package_seven_zip(cls.tool, cls.source, staging / "Game")

        cls.before = manifest(cls.tool, cls.source)
        cls.log_path = cls.scratch / "e2e.log"
        cls.discovered, cls.moved, cls.events = run_organize(cls.library, cls.log_path, steam_name="Some Game")
        cls.produced = sorted(cls.library.rglob("*.7z"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.scratch, ignore_errors=True)

    def test_the_run_converted_the_archive_rather_than_declining_it(self):
        """An already-.7z source is normally left alone, so a run that reports 'not needed' here has not
        silently stopped converting the most common case in the library."""
        stages = [event.get("stage") for event in self.events]
        self.assertIn("converted", stages, f"the run declined to convert the .7z source: {set(stages)}")
        self.assertEqual(len(self.produced), 1, f"expected one rebuilt archive, found {self.produced}")

    def test_the_rebuilt_archive_still_holds_the_whole_game(self):
        after = manifest(self.tool, self.produced[0])
        self.assertEqual(after[0], self.before[0], f"the rebuilt archive holds {after[0]} files, the source declared {self.before[0]}")
        self.assertEqual(after[1], self.before[1], f"the rebuilt archive holds {after[1]:,} bytes, the source declared {self.before[1]:,}")

    def test_the_generic_content_folder_was_renamed(self):
        proc = subprocess.run([self.tool, "l", "-slt", "--", str(self.produced[0])], stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace")
        paths = [line[7:] for line in proc.stdout.splitlines() if line.startswith("Path = ")]
        self.assertTrue(any(p.startswith("Some Game\\") for p in paths), f"the content folder was not renamed to the game's name: {paths[:5]}")
        self.assertFalse(any(p.startswith("Game\\") for p in paths), "the generically named content folder was published unchanged")

    def test_the_rebuilt_archive_passes_its_own_integrity_test(self):
        proc = subprocess.run([self.tool, "t", "--", str(self.produced[0])], stdin=subprocess.DEVNULL, capture_output=True)
        self.assertEqual(proc.returncode, 0, "the archive this run produced does not verify")

    def test_the_rebuilt_archive_carries_no_app_internals(self):
        proc = subprocess.run([self.tool, "l", "-slt", "--", str(self.produced[0])], stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace")
        self.assertNotIn(".organizer-lock", proc.stdout, "the app's own lock marker was packed into the published archive")

    def test_no_staging_folder_survived_a_successful_run(self):
        leftovers = [p.name for p in self.library.rglob("*") if p.name.startswith(".organizer-repack-")]
        self.assertEqual(leftovers, [], "a staging folder was left behind by a successful run")
