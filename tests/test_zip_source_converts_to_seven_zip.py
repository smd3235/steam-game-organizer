"""Extracted from tests/test_end_to_end.py.

    ZipSourceConvertsToSevenZip was moved here during a module split so the original file
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
from tests.test_helpers import package_zip
from tests.test_helpers import run_organize
from tests.test_helpers import seven_zip
from pathlib import Path


class ZipSourceConvertsToSevenZip(unittest.TestCase):
    """A real zip -> 7z conversion, then every property that has to hold about it."""

    @classmethod
    def setUpClass(cls):
        cls.tool = seven_zip()
        cls.scratch = Path(tempfile.mkdtemp(prefix="e2e-zip-"))
        cls.library = cls.scratch / "Games"
        game_dir = cls.library / "Test Game"
        game_dir.mkdir(parents=True)
        build_game_tree(game_dir, "Test Game")
        cls.source = game_dir / "Test Game.zip"
        package_zip(cls.source, game_dir / "Test Game")

        cls.before = manifest(cls.tool, cls.source)
        cls.source_bytes = cls.source.stat().st_size
        cls.log_path = cls.scratch / "e2e.log"
        cls.discovered, cls.moved, cls.events = run_organize(cls.library, cls.log_path)
        cls.produced = sorted(cls.library.rglob("*.7z"))
        cls.after = manifest(cls.tool, cls.produced[0]) if cls.produced else (0, 0)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.scratch, ignore_errors=True)

    def test_the_run_converted_exactly_one_archive(self):
        self.assertEqual(self.discovered, 1, "discovery did not find the one archive it was given")
        self.assertEqual(len(self.produced), 1, f"expected one converted archive, found {[p.name for p in self.produced]}")
        self.assertFalse(self.source.exists(), "the source survived a successful conversion")

    def test_the_rebuilt_archive_still_holds_the_whole_game(self):
        """The corruption case. A rebuild that lost files is a perfectly valid archive, so nothing downstream
        would ever notice; only comparing against the source's own index catches it."""
        self.assertGreater(self.before[0], 0, "the source archive declares no files")
        self.assertEqual(self.after[0], self.before[0], f"the rebuilt archive holds {self.after[0]} files, the source declared {self.before[0]}")
        self.assertEqual(self.after[1], self.before[1], f"the rebuilt archive holds {self.after[1]:,} bytes, the source declared {self.before[1]:,}")

    def test_the_rebuilt_archive_passes_its_own_integrity_test(self):
        proc = subprocess.run([self.tool, "t", "--", str(self.produced[0])], stdin=subprocess.DEVNULL, capture_output=True)
        self.assertEqual(proc.returncode, 0, "the archive this run produced does not verify")

    def test_the_rebuilt_archive_carries_no_app_internals(self):
        """The staging folder holds this app's own lock marker, and packing the folder packs it too. It also
        changes every run, so an archive carrying it is neither the game nor reproducible."""
        proc = subprocess.run([self.tool, "l", "-slt", "--", str(self.produced[0])], stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace")
        self.assertNotIn(".organizer-lock", proc.stdout, "the app's own lock marker was packed into the published archive")

    def test_the_reported_sizes_are_the_real_sizes_on_disk(self):
        converted = [event for event in self.events if event.get("stage") == "converted"]
        self.assertTrue(converted, "the run never reported a completed conversion")
        reported = converted[-1]
        self.assertEqual(reported["source_bytes"], self.source_bytes, "the run reported a source size that is not the file's real size")
        self.assertEqual(reported["target_bytes"], self.produced[0].stat().st_size, "the run reported a target size that is not the produced file's real size")

    def test_converting_to_7z_actually_saved_space(self):
        target = self.produced[0].stat().st_size
        self.assertLess(target, self.source_bytes, f"repacking to 7z did not shrink the archive ({self.source_bytes:,} -> {target:,})")

    def test_the_game_ended_up_in_its_category_folder(self):
        self.assertEqual(len(self.moved), 1)
        landed = self.moved[0]
        self.assertTrue(landed.organized_path and landed.organized_path.exists(), f"{landed.display_name} was reported as moved but is not on disk")
        self.assertEqual(landed.organized_path.parent.parent.name, "Simulation")

    def test_the_run_reported_each_stage_of_the_conversion(self):
        stages = [event.get("stage") for event in self.events]
        for expected in ("extracting", "compressing", "converted"):
            self.assertIn(expected, stages, f"the run never reported the {expected} stage: {set(stages)}")

    def test_no_staging_folder_survived_a_successful_run(self):
        leftovers = [p.name for p in self.library.rglob("*") if p.name.startswith(".organizer-repack-")]
        self.assertEqual(leftovers, [], "a staging folder was left behind by a successful run")
