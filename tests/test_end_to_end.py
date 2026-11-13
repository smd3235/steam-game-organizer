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

# ZipSourceConvertsToSevenZip extracted to tests\zip_source_converts_to_seven_zip.py — see that module for its definition.
from tests.zip_source_converts_to_seven_zip import ZipSourceConvertsToSevenZip
# SevenZipSourceIsRepackedAfterRenaming extracted to tests\seven_zip_source_is_repacked_after_renaming.py — see that module for its definition.
from tests.seven_zip_source_is_repacked_after_renaming import SevenZipSourceIsRepackedAfterRenaming
# CorruptSourceIsRefused extracted to tests\corrupt_source_is_refused.py — see that module for its definition.
from tests.corrupt_source_is_refused import CorruptSourceIsRefused
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

if __name__ == "__main__":
    unittest.main()
