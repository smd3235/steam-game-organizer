"""Tests for the two checks that stand between a conversion and a destroyed game.

Both exist because a rebuild of incomplete data is a *valid* archive: it passes `7z t`, it gets published,
and the intact source is deleted, so nothing downstream can notice. The only place to catch that is before the
source is removed.
"""

from __future__ import annotations

import subprocess
import unittest

import pytest
import os
import time
import zipfile
from pathlib import Path
from tempfile import mkdtemp

from core.logger import AppLogger
from services.extract_service import ExtractService
from services.organizer_service import OrganizerService


def _seven_zip() -> str | None:
    tool, _reason = ExtractService.find_tool()
    return tool


def _require_seven_zip(case):
    """Fail, naming the cause, when 7-Zip is missing.

    This was a class-wide `skipUnless`, which reported the suite green on any machine where none of these checks
    ran — and these are the checks that stand between a conversion and a destroyed game, so the one machine that
    needed them most would have been the one reporting cleanest. 7-Zip is a stated dependency on both target
    platforms, so its absence is a broken environment and is reported as one.
    """
    if not _seven_zip():
        case.fail("7-Zip is required for these checks and was not found on PATH or at the standard install location; the application needs it to convert anything.")


@pytest.mark.notkinter
class ArchiveManifestDescribesTheArchive(unittest.TestCase):
    def setUp(self):
        _require_seven_zip(self)
        self.dir = Path(mkdtemp())
        self.service = OrganizerService(AppLogger(self.dir / "manifest.log"), convert_archives=lambda: True)
        self.archive = self.dir / "Game.zip"
        with zipfile.ZipFile(self.archive, "w", zipfile.ZIP_DEFLATED) as handle:
            handle.writestr("data/a.bin", b"a" * 5000)
            handle.writestr("data/b.bin", b"b" * 7000)
            handle.writestr("readme.txt", b"hello")

    def test_the_manifest_counts_the_files_and_bytes_the_archive_holds(self):
        claimed = self.service._archive_manifest(self.archive)
        self.assertIsNotNone(claimed, "could not read the archive's own index")
        files, total = claimed
        self.assertEqual(files, 3)
        self.assertEqual(total, 12005)

    def test_a_complete_extraction_is_not_short(self):
        extracted = self.dir / "out"
        extracted.mkdir()
        subprocess.run([_seven_zip(), "x", "-y", f"-o{extracted}", "--", str(self.archive)], stdin=subprocess.DEVNULL, capture_output=True)
        self.assertFalse(self.service._extraction_is_short(self.archive, extracted))

    def test_an_extraction_missing_a_file_is_caught(self):
        """The case that matters: 7z can exit 0 having written only part of an archive. Comparing the index
        against what landed is the only way to know the rebuild would be missing a file."""
        extracted = self.dir / "partial"
        (extracted / "data").mkdir(parents=True)
        (extracted / "data" / "a.bin").write_bytes(b"a" * 5000)
        self.assertTrue(self.service._extraction_is_short(self.archive, extracted))

    def test_a_truncated_file_extracts_to_nothing_and_is_still_caught(self):
        broken = self.dir / "Broken.zip"
        broken.write_bytes(self.archive.read_bytes()[:200])
        extracted = self.dir / "broken-out"
        subprocess.run([_seven_zip(), "x", "-y", f"-o{extracted}", "--", str(broken)], stdin=subprocess.DEVNULL, capture_output=True)
        # The manifest of a truncated archive describes only what survived, so this case is caught by the
        # source integrity test instead - which is exactly why both checks exist.
        self.assertFalse(self.service._source_is_intact(broken))

    def test_a_healthy_archive_passes_the_source_integrity_test(self):
        self.assertTrue(self.service._source_is_intact(self.archive))

    def test_an_unknown_manifest_is_never_treated_as_data_loss(self):
        missing = self.dir / "gone.zip"
        claimed = self.service._archive_manifest(missing)
        self.assertIsNone(claimed, "a missing archive should report an unknown manifest, not an empty one")
        self.assertFalse(self.service._extraction_is_short(missing, self.dir), "an unreadable manifest must not be mistaken for a short extraction")


class DirectoriesAreNotCountedAsFiles(unittest.TestCase):
    """7-Zip 26.x lists a directory as `Attributes = D` with a zero `Size` and no `Folder` line at all.

    Counting those as files inflates the manifest by the number of folders, so `_extraction_is_short` compares a
    complete extraction against a larger claim and calls it short - refusing to convert a perfectly good
    archive. Every archive this app converts is a .7z, and a game always has a folder structure, so the check
    would refuse essentially every real conversion. The zip fixtures elsewhere cannot show this: `zipfile`
    stores no directory entries at all.
    """

    def setUp(self):
        _require_seven_zip(self)
        self.dir = Path(mkdtemp())
        self.service = OrganizerService(AppLogger(self.dir / "manifest.log"), convert_archives=lambda: True)
        self.tree = self.dir / "tree" / "Game"
        (self.tree / "data" / "nested").mkdir(parents=True)
        (self.tree / "data" / "a.bin").write_bytes(b"a" * 5000)
        (self.tree / "data" / "nested" / "b.bin").write_bytes(b"b" * 7000)
        (self.tree / "readme.txt").write_bytes(b"hello")
        self.archive = self.dir / "Game.7z"
        proc = subprocess.run([_seven_zip(), "a", "-t7z", "-mx=1", "-bso0", "-bsp0", str(self.archive), str(self.tree / "*")], stdin=subprocess.DEVNULL, capture_output=True)
        self.assertEqual(proc.returncode, 0, "could not build the fixture archive")

    def tearDown(self):
        __import__("shutil").rmtree(self.dir, ignore_errors=True)

    def test_the_manifest_counts_only_the_files(self):
        claimed = self.service._archive_manifest(self.archive)
        self.assertIsNotNone(claimed, "could not read the archive's own index")
        files, total = claimed
        self.assertEqual(files, 3, f"directory entries were counted as files: {claimed}")
        self.assertEqual(total, 12005, f"directory entries contributed to the byte total: {claimed}")

    def test_a_complete_extraction_of_a_real_7z_is_not_short(self):
        extracted = self.dir / "out"
        extracted.mkdir()
        subprocess.run([_seven_zip(), "x", "-y", f"-o{extracted}", "--", str(self.archive)], stdin=subprocess.DEVNULL, capture_output=True)
        self.assertFalse(self.service._extraction_is_short(self.archive, extracted), "a faithful extraction was mistaken for a short one")

    def test_an_extraction_missing_a_file_is_still_caught(self):
        extracted = self.dir / "partial"
        (extracted / "data").mkdir(parents=True)
        (extracted / "data" / "a.bin").write_bytes(b"a" * 5000)
        self.assertTrue(self.service._extraction_is_short(self.archive, extracted), "fixing the directory count must not blunt the check that catches real loss")


class StaleBuildDirsAreSweptAtStartup(unittest.TestCase):
    """A staging folder left by a killed run is cleared before a new conversion starts, but never one that
    another instance may be writing into."""

    def setUp(self):
        self.dir = Path(mkdtemp())
        self.library = self.dir / "Games"
        self.processing = self.library / "Processing"
        self.processing.mkdir(parents=True)
        self.service = OrganizerService(AppLogger(self.dir / "sweep.log"), convert_archives=lambda: True)

    def _stale(self, name: str, size: int = 1000, marker: str | None = None) -> Path:
        folder = self.processing / name
        folder.mkdir()
        (folder / "partial.7z").write_bytes(b"x" * size)
        if marker is not None:
            (folder / ".organizer-lock").write_text(marker, encoding="utf-8")
        # Older than the minimum age, so the age guard does not decide the outcome on its own.
        old = time.time() - 7200
        os.utime(folder, (old, old))
        return folder

    def test_an_abandoned_folder_is_removed_and_its_space_reported(self):
        folder = self._stale(".organizer-repack-abc123", size=4096, marker="999999 1\n")
        removed, reclaimed = self.service.sweep_stale_build_dirs(self.library)
        self.assertEqual(removed, 1)
        self.assertGreaterEqual(reclaimed, 4096)  # the lock marker counts too
        self.assertFalse(folder.exists())

    def test_a_folder_with_no_lock_marker_is_still_swept(self):
        folder = self._stale(".organizer-repack-nomarker")
        self.service.sweep_stale_build_dirs(self.library)
        self.assertFalse(folder.exists())

    def test_a_folder_another_live_process_owns_is_left_alone(self):
        # A pid that is certainly running: this one.
        folder = self._stale(".organizer-repack-inuse", marker=f"{os.getpid()} 1\n")
        removed, _bytes = self.service.sweep_stale_build_dirs(self.library)
        self.assertEqual(removed, 0)
        self.assertTrue(folder.exists(), "a staging folder in use by a live process was swept")

    def test_a_just_started_folder_is_left_alone(self):
        folder = self.processing / ".organizer-repack-fresh"
        folder.mkdir()
        (folder / "partial.7z").write_bytes(b"x" * 50)
        removed, _bytes = self.service.sweep_stale_build_dirs(self.library)
        self.assertEqual(removed, 0)
        self.assertTrue(folder.exists(), "a folder touched moments ago was swept")

    def test_only_this_apps_own_staging_folders_are_touched(self):
        keep = self.processing / "something-else"
        keep.mkdir()
        (keep / "precious.txt").write_text("do not delete", encoding="utf-8")
        self.service.sweep_stale_build_dirs(self.library)
        self.assertTrue((keep / "precious.txt").exists(), "sweeping reached beyond the app's own staging folders")

    def test_the_game_folders_are_never_searched(self):
        """A stale folder beside a game rather than under Processing is the fallback layout for when no
        library root is known. The sweep only clears the library's own scratch area, so a game folder is
        never walked."""
        beside = self.library / "Some Game" / ".organizer-repack-orphan"
        beside.mkdir(parents=True)
        (beside / "partial.7z").write_bytes(b"x" * 20)
        old = time.time() - 7200
        os.utime(beside, (old, old))
        removed, _bytes = self.service.sweep_stale_build_dirs(self.library)
        self.assertEqual(removed, 0)
        self.assertTrue((beside / "partial.7z").exists(), "a folder inside a game folder was deleted")

    def test_a_missing_processing_folder_is_not_an_error(self):
        empty = self.dir / "NoGames"
        self.assertEqual(self.service.sweep_stale_build_dirs(empty), (0, 0))
        self.assertEqual(self.service.sweep_stale_build_dirs(None), (0, 0))


if __name__ == "__main__":
    unittest.main()
