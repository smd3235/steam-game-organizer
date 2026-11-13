"""Shared test helpers extracted from test_batch_extract.py and test_uri_actions.py.

Holds `_game`, `make_archive`, `uri_for`, `AStatusFileTestCase`, `_payload_of`,
`build_game_tree`, `manifest`, `package_zip`, `package_seven_zip`, `run_organize`,
`seven_zip`, `_RecordingRegister`, and `_RecordingService` -
shared fixtures used by multiple test modules to avoid circular imports between them.
"""

import json
import random
import re
import shutil
import subprocess
import tempfile
import tkinter as tk
import unittest
import zipfile
from pathlib import Path
from threading import Event

from app.controller import AppController
from app.events import EventBus
from app.jobs import JobManager
from core.constants import ARCHIVE_EXTENSIONS
from core.logger import AppLogger
from core.models import SteamMatch
from core.state import StateStore
from services.archive_service import ArchiveService
from services.catalog_service import CatalogService
from services.extract_service import ExtractService
from services.installer_detect import NEEDS_INSTALL_DIRNAME
from services.organizer_service import OrganizerService
from services.rollback_service import RollbackService

GB = 1024 ** 3


class CountingCatalog(CatalogService):
    """A catalog that counts its own disk access, so 'no second walk' is a measurement rather than a claim."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.collects = 0
        self.reads = 0

    def _collect(self, library_root):
        self.collects += 1
        return super()._collect(library_root)

    def _read_game(self, game_dir, category_name, library_root):
        self.reads += 1
        return super()._read_game(game_dir, category_name, library_root)


def _contrast_ratio():
    """Reuse the app's own WCAG implementation so both palettes are judged by one formula."""
    import importlib.util

    path = Path(__file__).with_name("test_contrast.py")
    spec = importlib.util.spec_from_file_location("_app_contrast", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return lambda foreground, background: module.contrast(foreground, background)


def _service(tmp: Path) -> ArchiveService:
    """An ArchiveService writing to a temporary log."""
    return ArchiveService(AppLogger(tmp / "log.txt"))


def make_game(root: Path, **metadata) -> Path:
    """A tiny organized game folder: category, zip archive, sidecar, and artwork stubs."""
    game = root / "Simulation" / "Alpha Forge - 2024-01-01"
    game.mkdir(parents=True)
    (game / "Alpha Forge.zip").write_text("x")
    for name in ("header_image", "library_hero"):
        (game / f"Alpha Forge_{name}.jpg").write_bytes(b"\xff\xd8\xff\xdb" + b"0" * 2000)
    payload = {"appid": "100001", "name": "Alpha Forge", "description": "desc", "release_date": "1 Jan, 2024", "genres": ["Simulation"]}
    payload.update(metadata)
    (game / ".game-info.json").write_text(json.dumps(payload))
    return game


def _script_encoded_path(path: Path) -> str:
    """The path the page's script would build, mirrored in Python."""
    from urllib.parse import quote
    return quote(str(path), safe="/:")


def _rgb(value: str) -> tuple:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


class _Jobs:
    """A job manager stand-in that refuses all work."""

    def submit(self, *a, **k):
        raise AssertionError("the summary path must not submit work")


class _Services:
    """A services stand-in with no organizer or rollback."""

    organizer = None
    rollback = None


APPDETAILS_KEYS_55555 = frozenset(
    {
        "about_the_game",
        "background",
        "background_raw",
        "capsule_image",
        "capsule_imagev5",
        "categories",
        "content_descriptors",
        "controller_support",
        "detailed_description",
        "developers",
        "dlc",
        "genres",
        "header_image",
        "is_free",
        "linux_requirements",
        "mac_requirements",
        "metacritic",
        "movies",
        "name",
        "package_groups",
        "packages",
        "pc_requirements",
        "platforms",
        "price_overview",
        "publishers",
        "ratings",
        "recommendations",
        "release_date",
        "required_age",
        "screenshots",
        "short_description",
        "steam_appid",
        "support_info",
        "supported_languages",
        "type",
        "website",
    }
)
APPDETAILS_KEYS_66666 = APPDETAILS_KEYS_55555 | {"achievements", "legal_notice"}


def _tmp_dir(test_case):
    """A temporary directory that is cleaned up when the test finishes."""
    tmp = Path(tempfile.mkdtemp())
    test_case.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    return tmp


def _mojibake(character):
    """What one character becomes when its UTF-8 bytes are read as cp1252, or None when it cannot."""
    try:
        return character.encode("utf-8").decode("cp1252")
    except UnicodeDecodeError:
        return None


MOJIBAKE_SEQUENCES = tuple(
    spelling for spelling in (_mojibake(c) for c in "\u2014\u2013\u2018\u2019\u201c\u201d\u2026\u00a0") if spelling
)
DOUBLE_ENCODED = re.compile("|".join(re.escape(s) for s in MOJIBAKE_SEQUENCES))


MAX_SCANNED_BYTES = 2_000_000


def game(root: Path, category: str, name: str, **metadata) -> Path:
    """One game folder with a sidecar carrying the fields the index reads."""
    folder = root / category / f"{name} - 2024-01-01"
    folder.mkdir(parents=True)
    payload = {"appid": "1", "name": name, "description": "desc", "release_date": "1 Jan, 2024", "genres": ["Indie", "Simulation"], "developer": "Some Studio"}
    payload.update(metadata)
    (folder / ".game-info.json").write_text(json.dumps(payload), encoding="utf-8")
    return folder


def archive(folder: Path, name: str, size: int) -> int:
    (folder / name).write_bytes(b"0" * size)
    return size


def service(root: Path, **kwargs) -> CatalogService:
    return CountingCatalog(AppLogger(root / "x.log"), **kwargs)


def _game(root: Path, category: str, name: str, payload: int = 2048) -> Path:
    """A real zip on disk, with the metadata sidecar the catalog reads."""
    folder = root / category / f"{name} - 2024-01-01"
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / f"{name}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as handle:
        handle.writestr(f"{name}/game.bin", b"a" * payload)
    (folder / ".game-info.json").write_text(f'{{"appid":"1","name":"{name}","genres":["Idle"]}}', encoding="utf-8")
    return archive


def make_archive(library: Path, name: str = "Some Game.7z") -> Path:
    path = library / name
    path.write_bytes(b"not really an archive")
    return path


def uri_for(archive: Path, dest: str | None = None) -> str:
    from urllib.parse import quote
    link = f"steamgameorganizer://extract?src={quote(str(archive), safe='')}"
    if dest is not None:
        link += f"&dest={quote(dest, safe='')}"
    return link


class AStatusFileTestCase(unittest.TestCase):
    """Base class for catalog status file tests."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "Games"
        self.dest = self.base / "Out"
        self.dest.mkdir(parents=True)
        self.logger = AppLogger(self.base / "x.log")
        _game(self.root, "Idle", "Loop Miner")
        _game(self.root, "Idle", "Fellwood")
        _game(self.root, "RPG", "Deep Signal")

    def _generate(self, destination=None):
        folders = [destination] if destination else [self.dest]
        return CatalogService(self.logger, extract_folders=folders).generate(self.root, "")[0]

    def _page(self, destination=None) -> str:
        return self._generate(destination).read_text(encoding="utf-8")

    def _unpack(self, name: str, destination: Path):
        folder = destination / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "game.bin").write_bytes(b"x")

    def _unpack_installer(self, name: str, destination: Path):
        """A folder this version extracted as an installer: payload in the Needs Install folder at the
        destination root (the current layout)."""
        mark = destination / NEEDS_INSTALL_DIRNAME / name
        mark.mkdir(parents=True, exist_ok=True)
        (mark / "setup.exe").write_bytes(b"MZ")
        (mark / "setup-1.bin").write_bytes(b"x" * 1000)

    def _payload_of(self, path: Path):
        from services.catalog_status import STATUS_GLOBAL
        text = path.read_text(encoding="utf-8")
        marker = f"window.{STATUS_GLOBAL} = "
        assert marker in text, f"the status file does not assign window.{STATUS_GLOBAL}: {text!r}"
        raw = text.split(marker, 1)[1].strip()
        import json
        return json.loads(raw[:-1] if raw.endswith(";") else raw)


def _unpacked_card(text: str) -> int:
    """How many cards on the page carry the badge.

    Counted on the rendered class rather than on 'badge-done', which also appears in the stylesheet and in the
    script - a substring count would pass with the badge never drawn at all.
    """
    return text.count('class="badge badge-done"')


def shown(widget):
    """Every string the panel actually put on screen, in creation order."""
    found = []
    pending = list(widget.winfo_children())
    while pending:
        child = pending.pop(0)
        if child.winfo_class() == "Label":
            found.append(child.cget("text"))
        pending.extend(child.winfo_children())
    return found


def _labels(widget) -> list:
    found = []
    for child in widget.winfo_children():
        try:
            found.append(str(child.cget("text")))
        except tk.TclError:
            pass
        found.extend(_labels(child))
    return found


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


class _RecordingRegister:
    """Watches the handler registration without touching the registry."""

    def __init__(self, raise_=None):
        self.calls = []
        self.raise_ = raise_

    def __call__(self, python, entry):
        self.calls.append((python, entry))
        if self.raise_ is not None:
            raise self.raise_


class _RecordingService:
    """A SetupService stand-in that records what the wizard hands it."""

    def __init__(self, rows=None):
        self.checks_calls = []
        self.apply_calls = []
        self.rows = rows if rows is not None else [("ok", "all good")]

    def checks(self, library, app, extract):
        self.checks_calls.append((library, app, extract))
        return self.rows

    def apply(self, config, library, app, extract):
        self.apply_calls.append((library, app, extract))
        return True, [("ok", "Saved.")]
