"""End to end: a real library, real discovery, a real conversion, real moves.

Nothing here about the archive toolchain is stubbed - the thing worth testing is exactly what a stub cannot
show: that a conversion does not lose data, that the source is only ever removed once a verified replacement
exists, and that the numbers the run reports are the numbers on disk.

The fixture is built, not borrowed. An earlier version of this module used a real game from a real library,
which meant the whole suite skipped itself on every machine that did not have that one file on that one drive.
That is not a small gap: these are the tests that found 9.16's directory-counting and packed-lock-marker
defects, and they had been reported as passing while not running at all. A release-shaped tree built from a
seeded generator exercises the same paths on any machine, and the nesting is the part that matters - a flat
fixture cannot show a manifest that counts directories as files.

Conversion is expensive relative to a unit test, so each class performs one real run and the assertions then
read that one outcome rather than repeating the work.
"""

from __future__ import annotations

import pytest

import random
import re
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from threading import Event

from app.controller import AppController
from app.events import EventBus
from app.jobs import JobManager
from core.logger import AppLogger
from core.constants import ARCHIVE_EXTENSIONS
from core.models import SteamMatch
from core.state import StateStore
from services.archive_service import ArchiveService
from services.extract_service import ExtractService
from services.organizer_service import OrganizerService
from services.rollback_service import RollbackService


def seven_zip() -> str:
    """The real 7-Zip, or a failure that names what is missing.

    Skipping here is how the 9.16 defects survived: these were the checks most worth running, and they were
    the ones that quietly did not run wherever 7-Zip was not on PATH. 7-Zip is a stated dependency on both
    target platforms, so its absence is a broken environment and is reported as one.
    """
    tool, reason = ExtractService.find_tool()
    if not tool:
        raise AssertionError(f"7-Zip is required for these tests and was not found: {reason}")
    return tool


def build_game_tree(root: Path, content_folder: str) -> Path:
    """A release-shaped game folder: loose files at the top, `steam_settings`, and a deeper `www/` tree.

    Bytes come from a seeded generator so the totals a conversion reports are identical on every run and every
    machine, which is what lets an assertion compare a rebuild against its source exactly. The payload mixes
    highly repetitive text, which LZMA2 compresses far better than the zip's deflate, with incompressible
    bytes, so a conversion that genuinely shrinks the archive is observable.
    """
    game = root / content_folder
    (game / "steam_settings").mkdir(parents=True)
    for folder in ("images", "media", "scripts"):
        (game / "www" / folder).mkdir(parents=True)
    noise = random.Random(20260903)

    (game / "README.txt").write_text("A game.\n" * 400, encoding="utf-8")
    (game / "_INSTALL TUTORIAL.txt").write_text("Unpack and run.\n" * 200, encoding="utf-8")
    (game / "sponsor.url").write_text("[InternetShortcut]\nURL=https://example.invalid/\n", encoding="utf-8")
    (game / "steam_settings" / "steam_appid.txt").write_text("1234\n", encoding="utf-8")
    (game / "steam_settings" / "configs.app.ini").write_text("[InstallConfig]\nname=Test\n", encoding="utf-8")
    (game / "steam_settings" / "achievements.json").write_text('{"achievements": []}', encoding="utf-8")
    (game / "www" / "index.html").write_text("<html></html>\n" * 50, encoding="utf-8")
    (game / "www" / "style.css").write_text("body { margin: 0; }\n" * 300, encoding="utf-8")
    for index in range(60):
        (game / "www" / "scripts" / f"chunk{index}.js").write_text(f"// chunk {index}\n" + "function tick(state) { return state + 1; }\n" * 200, encoding="utf-8")
    for index in range(8):
        (game / "www" / "images" / f"sheet{index}.webp").write_bytes(noise.randbytes(16_000))
    for index in range(4):
        (game / "www" / "media" / f"track{index}.webm").write_bytes(noise.randbytes(24_000))
    return game


def package_zip(source: Path, game: Path) -> None:
    """Zip a built tree. The only archive format that needs no tool to author, and the source format this app
    actually converts from, so the zip -> 7z path is covered end to end."""
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as handle:
        for item in sorted(game.rglob("*")):
            if item.is_file():
                handle.write(item, item.relative_to(game.parent))


def package_seven_zip(tool: str, source: Path, game: Path) -> None:
    """Pack the tree as a real .7z, keeping the content folder itself as a directory inside the archive.

    That wrapper folder is the shape a release archive actually has, and it is what the app looks for when it
    decides whether a game's content is buried under a generically named directory worth renaming.
    """
    subprocess.run([tool, "a", "-t7z", "-mx=1", "-bso0", "-bsp0", str(source), str(game)], stdin=subprocess.DEVNULL, capture_output=True, check=True)


def manifest(tool: str, path: Path) -> tuple:
    """(file count, total uncompressed bytes) as the archive's own index declares them.

    Directories are excluded. 7-Zip 26.x lists them as `Attributes = D` with a zero `Size` and no `Folder`
    line, so without this they would be counted as empty files and a faithful rebuild would look like it had
    gained a folder's worth of entries.
    """
    proc = subprocess.run([tool, "l", "-slt", "--", str(path)], stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace")
    files = total = 0
    for block in proc.stdout.split("\n\n"):
        if "Path = " not in block or re.search(r"^Folder = \+$", block, re.M):
            continue
        attributes = re.search(r"^Attributes = (.*)$", block, re.M)
        if attributes and "D" in attributes.group(1).split():
            continue
        match = re.search(r"^Size = (\d+)$", block, re.M)
        if not match:
            continue
        files += 1
        total += int(match.group(1))
    return files, total


def run_organize(library: Path, log_path: Path, steam_name: str | None = None, category: str = "Simulation") -> tuple:
    """Organize everything in `library` through the real controller and wait for the run to finish.

    Returns (archives discovered, what the run reported as moved, every progress event it emitted).
    """
    logger = AppLogger(log_path)
    discovered = ArchiveService(logger).discover(library)
    for archive in discovered.archives:
        archive.decision.accepted = True
        archive.decision.category = category
        archive.steam = SteamMatch(found=True, appid=1234, name=steam_name or archive.display_name, release_date="1 Jan, 2024")
    organizer = OrganizerService(logger, convert_archives=lambda: True)
    services = type("Services", (), {"organizer": organizer, "rollback": RollbackService(library, logger)})()
    jobs = JobManager()
    controller = AppController(StateStore(), EventBus(), logger, services, jobs)
    finished = Event()
    moved: list = []
    events: list = []
    controller.organize(discovered.archives, library, lambda done: (moved.extend(done), finished.set()), on_progress=lambda event: events.append(event))
    if not finished.wait(900):
        jobs.shutdown()
        raise AssertionError("the organize run did not finish within 15 minutes")
    jobs.shutdown()
    return len(discovered.archives), moved, events


@pytest.mark.integration
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


class CorruptSourceIsRefused(unittest.TestCase):
    """A truncated archive - what an interrupted download leaves - must never be consumed.

    The fixture is a real .7z cut short, because that is the shape this actually failed on: a library was found
    holding 82 truncated files that reported success as games and would each have been offered for conversion.
    """

    def setUp(self):
        self.tool = seven_zip()
        self.scratch = Path(tempfile.mkdtemp(prefix="e2e-bad-"))
        self.library = self.scratch / "Games"
        staging = self.scratch / "built"
        build_game_tree(staging, "Game")
        broken_dir = self.library / "Broken Game"
        broken_dir.mkdir(parents=True)
        whole = self.scratch / "whole.7z"
        package_seven_zip(self.tool, whole, staging / "Game")
        self.truncated_bytes = whole.read_bytes()[:4096]
        self.broken = broken_dir / "Broken Game.7z"
        self.broken.write_bytes(self.truncated_bytes)
        self.log_path = self.scratch / "e2e.log"

    def tearDown(self):
        shutil.rmtree(self.scratch, ignore_errors=True)

    def test_a_truncated_archive_is_left_alone_and_the_refusal_is_logged(self):
        discovered, _moved, _events = run_organize(self.library, self.log_path)
        self.assertEqual(discovered, 1, "the broken archive was not discovered")

        # Refusing to convert is not refusing to organise: the game is still filed under its category, and the
        # app still writes its own sidecar files beside it. What matters is that the only *archive* left is the
        # one that arrived, byte for byte.
        survivors = sorted(p for p in self.library.rglob("*") if p.is_file() and p.suffix.lower() in ARCHIVE_EXTENSIONS)
        self.assertEqual(len(survivors), 1, f"a truncated archive produced or removed archives: {survivors}")
        self.assertEqual(survivors[0].read_bytes(), self.truncated_bytes, "the truncated archive's bytes changed")
        text = self.log_path.read_text(encoding="utf-8", errors="replace")
        self.assertIn("SOURCE_INTEGRITY_FAILED", text, "the refusal was not recorded in the log")


if __name__ == "__main__":
    unittest.main()
