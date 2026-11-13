from pathlib import Path
from datetime import datetime
from html import escape
from urllib.request import pathname2url
from urllib.parse import quote
import sys
import threading
# Imports split one per line for GitHub readability.
from core.library_summary import LibrarySummary
from core.catalog_utils import (
    anchor,
    archive_created,
    archive_size,
    asset_prefix,
    batch_button,
    clean_tags,
    extract_uri,
    find_banner,
    open_folder_uri,
    path_within,
    remaining_button,
    refresh_uri,
    setup_uri,
    store_url,
    steam_protocol_url,
)
from .banner_art import banner_data_uri
from core.constants import APP_NAME, ENTRY_POINT, LIBRARY_RESERVED_DIRS
from core.uri_actions import safe_folder_name
from services.catalog_status import STATUS_NAME, already_extracted, empty_status, write_status, archive_has_changed_since_extraction
from services.installer_detect import NEEDS_INSTALL_DIRNAME, has_needs_install_mark
from utils.formatting import human_size
import json
import re

# Module-level cache shared across all CatalogService instances: {resolved_library_root_str: categories_dict}.
# Instance-level caches are thrown away when the instance is discarded, which made the three separate
# _collect() calls in steam_game_organizer.py (_handle_uri, _handle_multi_uri, _handle_batch_uri) walk
# the whole library three times per process run. A module-level cache keyed on the resolved root lets all
# instances reuse a single walk. A lock guards concurrent access from worker threads.
_COLLECT_CACHE: dict[str, dict] = {}
_COLLECT_CACHE_LOCK = threading.Lock()

# Generic custom banners per category. Every category gets its own coloured theme so categories
# are distinguishable at a glance instead of all reusing the first game's art. Lowercased keys so
# lookups are case-insensitive; anything not listed here falls back to the generated name-based banner.
_CATEGORY_BANNERS = {
    "action": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 300"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#c62828"/><stop offset="100%" stop-color="#ff1744"/></linearGradient></defs><rect width="1200" height="300" fill="url(#g)"/><circle cx="800" cy="150" r="60" fill="#ffcdd2" opacity=".8"/><path d="M760 110l40 80M760 190l40-80" stroke="#fff" stroke-width="12" fill="none" stroke-linecap="round"/></svg>',
    "adventure": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 300"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#1a237e"/><stop offset="100%" stop-color="#5c6bc0"/></linearGradient></defs><rect width="1200" height="300" fill="url(#g)"/><path d="M200 240 L400 60 L600 240 L800 60 L1000 240" stroke="#e8eaf6" stroke-width="8" fill="none"/><circle cx="880" cy="80" r="20" fill="#ffd54f"/></svg>',
    "rpg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 300"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#4a148c"/><stop offset="100%" stop-color="#ab47bc"/></linearGradient></defs><rect width="1200" height="300" fill="url(#g)"/><path d="M300 200 L360 100 L420 200 M450 200 L510 100 L570 200 M600 200 L660 100 L720 200" stroke="#e1bee7" stroke-width="10" fill="none" stroke-linecap="round"/><circle cx="900" cy="220" r="30" fill="#ce93d8"/></svg>',
    "strategy": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 300"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#1b5e20"/><stop offset="100%" stop-color="#43a047"/></linearGradient></defs><rect width="1200" height="300" fill="url(#g)"/><rect x="100" y="100" width="100" height="100" fill="#c8e6c9" opacity=".7"/><rect x="300" y="100" width="100" height="100" fill="#c8e6c9" opacity=".7"/><rect x="500" y="100" width="100" height="100" fill="#c8e6c9" opacity=".7"/><rect x="700" y="100" width="100" height="100" fill="#c8e6c9" opacity=".7"/><rect x="900" y="100" width="100" height="100" fill="#c8e6c9" opacity=".7"/></svg>',
    "shooter": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 300"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#3e2723"/><stop offset="100%" stop-color="#795548"/></linearGradient></defs><rect width="1200" height="300" fill="url(#g)"/><rect x="100" y="80" width="200" height="40" fill="#d7ccc8" opacity=".8" rx="4"/><rect x="350" y="140" width="200" height="40" fill="#d7ccc8" opacity=".8" rx="4"/><rect x="600" y="80" width="200" height="40" fill="#d7ccc8" opacity=".8" rx="4"/><rect x="850" y="140" width="200" height="40" fill="#d7ccc8" opacity=".8" rx="4"/></svg>',
    "racing": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 300"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#d32f2f"/><stop offset="100%" stop-color="#ff5252"/></linearGradient></defs><rect width="1200" height="300" fill="url(#g)"/><circle cx="150" cy="240" r="25" fill="#e0e0e0"/><circle cx="240" cy="240" r="25" fill="#e0e0e0"/><circle cx="960" cy="240" r="25" fill="#e0e0e0"/><circle cx="1050" cy="240" r="25" fill="#e0e0e0"/><path d="M100 180 Q600 60 1100 180" stroke="#fff" stroke-width="3" fill="none"/></svg>',
    "sports": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 300"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#2e7d32"/><stop offset="100%" stop-color="#4caf50"/></linearGradient></defs><rect width="1200" height="300" fill="url(#g)"/><circle cx="600" cy="150" r="100" fill="#fff" opacity=".15"/><path d="M100 150 L1100 150 M600 50 L600 250" stroke="#fff" stroke-width="2" opacity=".6"/></svg>',
    "simulation": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 300"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#1565c0"/><stop offset="100%" stop-color="#42a5f5"/></linearGradient></defs><rect width="1200" height="300" fill="url(#g)"/><rect x="200" y="80" width="200" height="140" fill="#bbdefb" opacity=".7" rx="8"/><rect x="450" y="120" width="200" height="100" fill="#bbdefb" opacity=".7" rx="8"/><rect x="700" y="80" width="200" height="140" fill="#bbdefb" opacity=".7" rx="8"/><rect x="950" y="130" width="150" height="70" fill="#bbdefb" opacity=".7" rx="8"/></svg>',
    "indie": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 300"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#4a148c"/><stop offset="50%" stop-color="#8e24aa"/><stop offset="100%" stop-color="#ce93d8"/></linearGradient></defs><rect width="1200" height="300" fill="url(#g)"/><circle cx="200" cy="80" r="40" fill="#fff" opacity=".3"/><circle cx="1000" cy="220" r="50" fill="#fff" opacity=".2"/><circle cx="400" cy="200" r="30" fill="#fff" opacity=".4"/></svg>',
    "casual": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 300"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#ff6f00"/><stop offset="100%" stop-color="#ffb300"/></linearGradient></defs><rect width="1200" height="300" fill="url(#g)"/><circle cx="200" cy="150" r="30" fill="#fff" opacity=".8"/><circle cx="400" cy="120" r="25" fill="#fff" opacity=".8"/><circle cx="600" cy="180" r="35" fill="#fff" opacity=".8"/><circle cx="800" cy="100" r="20" fill="#fff" opacity=".8"/><circle cx="1000" cy="160" r="28" fill="#fff" opacity=".8"/></svg>',
    "puzzle": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 300"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#4527a0"/><stop offset="100%" stop-color="#7e57c2"/></linearGradient></defs><rect width="1200" height="300" fill="url(#g)"/><rect x="100" y="100" width="80" height="80" fill="#d1c4e9" opacity=".8"/><rect x="200" y="180" width="80" height="80" fill="#d1c4e9" opacity=".8"/><rect x="300" y="100" width="80" height="80" fill="#d1c4e9" opacity=".8"/><rect x="400" y="180" width="80" height="80" fill="#d1c4e9" opacity=".8"/><rect x="500" y="100" width="80" height="80" fill="#d1c4e9" opacity=".8"/></svg>',
    "platformer": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 300"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#33691e"/><stop offset="100%" stop-color="#689f38"/></linearGradient></defs><rect width="1200" height="300" fill="url(#g)"/><path d="M0 250 L200 250 L200 200 L400 200 L400 150 L600 150 L600 100 L800 100 L800 50 L1000 50 L1000 0 L1200 0 L1200 300 L0 300 Z" fill="#2e7d32"/><circle cx="220" cy="230" r="12" fill="#fff"/><circle cx="420" cy="180" r="12" fill="#fff"/><circle cx="620" cy="130" r="12" fill="#fff"/><circle cx="820" cy="80" r="12" fill="#fff"/><circle cx="1020" cy="30" r="12" fill="#fff"/></svg>',
    "horror": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 300"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#000"/><stop offset="100%" stop-color="#212121"/></linearGradient></defs><rect width="1200" height="300" fill="url(#g)"/><circle cx="300" cy="100" r="30" fill="#4a148c" opacity=".6"/><circle cx="900" cy="200" r="40" fill="#6a1b9a" opacity=".6"/><path d="M500 150 Q600 50 700 150 Q800 250 900 150" stroke="#4a148c" stroke-width="4" fill="none"/></svg>',
    "sandbox": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 300"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#827717"/><stop offset="100%" stop-color="#c0ca33"/></linearGradient></defs><rect width="1200" height="300" fill="url(#g)"/><rect x="100" y="200" width="100" height="60" fill="#fff" opacity=".8"/><rect x="250" y="150" width="100" height="110" fill="#fff" opacity=".8"/><rect x="400" y="220" width="100" height="40" fill="#fff" opacity=".8"/><rect x="550" y="100" width="100" height="160" fill="#fff" opacity=".8"/><rect x="700" y="180" width="100" height="80" fill="#fff" opacity=".8"/></svg>',
    "survival": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 300"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#3e2723"/><stop offset="100%" stop-color="#5d4037"/></linearGradient></defs><rect width="1200" height="300" fill="url(#g)"/><path d="M100 280 Q300 100 500 280 Q700 100 900 280 Q1100 100 1200 280" stroke="#8d6e63" stroke-width="8" fill="none"/><circle cx="600" cy="180" r="40" fill="#4e342e"/></svg>',
}


def _category_banner(name: str) -> str:
    """Return a data URI for a custom category banner, or the generated name-based banner if none exists."""
    svg = _CATEGORY_BANNERS.get(name.strip().lower())
    if svg:
        return "data:image/svg+xml," + quote(svg, safe="")
    return banner_data_uri(name)


MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def sort_date(text) -> str:
    """A sortable YYYYMMDD key from a Steam release date, or '00000000' when there is no usable date.

    Steam writes these in at least two shapes - "Jun 24, 2026" and "1 Jan, 2024" - and any part can be missing.
    Stripping the non-digits and taking the first four characters, which is what this did before, survives
    neither shape: it returned "6242" for "Jun 24, 2026", because the first digits in that string are the day.
    Sorting on that key was sorting on the day of the month.

    A missing month or day becomes '00', so a date with only a year still lands in the right year and ties with
    its neighbours instead of sorting to one end of the library.
    """
    raw = str(text or "")
    year = re.search(r"\b((?:19|20)\d{2})\b", raw)
    if not year:
        return "00000000"
    month = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", raw, re.IGNORECASE)
    day = re.search(r"\b(\d{1,2})\b", raw)
    day_value = int(day.group(1)) if day and int(day.group(1)) <= 31 else 0
    return f"{year.group(1)}{MONTHS[month.group(1).lower()]:02d}{day_value:02d}" if month else (f"{year.group(1)}00{day_value:02d}")


class CatalogService:
    """Builds an offline, clickable HTML game catalog (banner art + TOC + per-category header) from the
    already-organized library. It is one file, not a per-platform pair: the same page is correct on Windows
    and on any other machine, so there is nothing to choose between and nothing to keep in sync. Each run
    overwrites it and removes what earlier releases left behind. Folder references are emitted relative to the
    library root so a copied catalog keeps working after the whole Games folder is moved elsewhere.

    The same run retains what it read, as the library index `library_summary()` hands back. The walk is the
    expensive part and it was already happening on every scan and after every organize run; the metadata
    describing all 165 games used to be parsed and then thrown away with nothing reading it."""

    CATALOG_NAME = "Game Library.html"
    # Every name this catalog has ever used, so a library organised by an earlier release is cleaned up
    # instead of collecting one more catalog per run.
    LEGACY_CATALOGS = ("Game Library (Steam Deck) - *.html", "Game Library (Windows) - *.html", "Game Library - *.html", "Game Library.html")
    LEGACY_LAUNCHER = "Open Game Library (Steam Deck).desktop"

    def __init__(self, logger, extract_folders=()):
        self.logger = logger
        from core.constants import ENTRY_POINT

        if getattr(sys, "frozen", False):
            self._setup_cmd = f"{ENTRY_POINT.replace('.py', '.exe')} --setup"
        else:
            self._setup_cmd = f"runtime{chr(92)}python.exe steam_game_organizer.py --setup"
        # The destinations the page offers. Passed in rather than read from config here, because the catalog
        # service is otherwise deliberately free of app configuration and can be pointed at any library.
        self.extract_folders = [Path(p) for p in extract_folders] or [Path.home() / "Downloads" / "Extracted"]
        # The index retained from the walk generate() already performs. None means "not built yet", which is an
        # ordinary state on a process that reaches a screen before it has scanned anything.
        self._summary = None
        self._library_root = None
        # Template caches - avoid regenerating static content on each render
        self._css_cache = None
        self._script_cache = None

    def generate(self, library_root, write_launcher=False):
        library_root = Path(library_root).expanduser().resolve()
        if not library_root.is_dir():
            return []
        # generate() always walks fresh: the library may have changed since the last call (a game moved
        # category, an archive converted away). Clear the module-level _collect() cache so stale data
        # is not returned to any CatalogService instance.
        with _COLLECT_CACHE_LOCK:
            _COLLECT_CACHE.clear()
        categories = self._collect(library_root)
        # Retained here, ahead of the empty check and of anything being rendered or written: an empty library is
        # a valid index, and a write that fails four lines below still leaves metadata the scan just paid for.
        self._retain(library_root, categories)
        if not categories:
            return []
        self._remove_previous(library_root)
        path = library_root / self.CATALOG_NAME
        try:
            path.write_text(self._render(categories, self.extract_folders, library_root), encoding="utf-8")
        except OSError as exc:
            self.logger.warning("CATALOG", f"WRITE_FAILED path=[{path}] error={type(exc).__name__}")
            return []
        # The status file is written only when it is not already there. A run's result is the thing a reader
        # comes back to the page for, and every scan regenerates the catalog - so overwriting it here would
        # erase the last run's outcome on the next scan, which is the one thing the banner exists to report.
        if not (library_root / STATUS_NAME).exists():
            write_status(library_root, empty_status(), self.logger)
        if write_launcher:
            self._write_chrome_launcher(library_root, path)
        self.logger.info("CATALOG", f"GENERATED files=1 games={sum(len(v) for v in categories.values())}")
        return [path]

    def _retain(self, library_root, categories):
        """Keep the collected metadata as the library index instead of dropping it on the floor.

        `generate()` calls `_collect()` on every scan and again at the end of every organize run, and until
        now the dict went out of scope when the method returned: the whole walk, 165 sidecars parsed,
        discarded. This is a retention change over a walk that already happens, not a new one - nothing here
        touches the disk, and `LibrarySummary.from_categories` reads the dict the walk already produced, so
        the index costs arithmetic over data the scan paid for regardless. Building it from a walk of its own
        would be strictly worse than keeping this one, which is the whole reason this is worth doing.

        Called on every `generate()`, and that is also what keeps it fresh. Organize moves games between
        categories and then regenerates the catalog (app/controller.py), so the index follows the moves for
        free; a scan ends the same way. Neither needs invalidating, because both end here.
        """
        self._library_root = Path(library_root)
        self._summary = LibrarySummary.from_categories(categories)
        self.logger.info("CATALOG", f"INDEX_BUILT categories={len(self._summary.categories)} games={self._summary.total_games} developers={len(self._summary.developer_placement)}")

    def library_summary(self, library_root=None) -> LibrarySummary:
        """The library index, for the questions a category decision needs answered.

        Pass the library root and a cold call builds the index once and caches it. Reaching a screen before
        any catalog pass has run in this process is an ordinary state, not a failure, and answering it with
        an empty index would read as "your library has no categories" - so it is built on demand here.

        With no root and nothing retained there is nothing to build from, and an empty summary comes back
        with built_at == 0.0, which `indexed` reports as False. That is how a display tells "not looked yet"
        apart from "looked, and there is nothing".

        A root that differs from the one retained rebuilds rather than answering, because one service
        instance can be pointed at a different library and a summary of the previous one is worse than none.
        """
        if library_root is not None:
            root = Path(library_root).expanduser().resolve()
            if self._summary is None or root != self._library_root:
                return self.rebuild_summary(root)
        return self._summary if self._summary is not None else LibrarySummary()

    def rebuild_summary(self, library_root) -> LibrarySummary:
        """Walk the library and replace the retained index. The only path here that reads the disk.

        A root that is missing, is not a directory, or cannot be listed yields an empty-but-valid summary and
        a warning in the log rather than an exception: the caller is a screen drawing a panel, and it should
        not go down over a folder the user cannot reach.

        Nothing is retained in that case, deliberately, so `indexed` stays False and the next read tries again.
        Caching the failure would report a drive that is not plugged in as a library with no categories, and
        there would be no way back short of restarting the app.
        """
        root = Path(library_root).expanduser().resolve()
        self._library_root = root
        self._summary = None
        if not root.is_dir():
            self.logger.warning("CATALOG", f"INDEX_BUILD_FAILED path=[{root}] error=[NotADirectoryError]")
            return LibrarySummary()
        try:
            categories = self._collect(root)
        except OSError as exc:
            self.logger.warning("CATALOG", f"INDEX_BUILD_FAILED path=[{root}] error={type(exc).__name__}")
            return LibrarySummary()
        self._retain(root, categories)
        return self._summary

    def invalidate_summary(self):
        """Drop the retained index so the next read rebuilds it.

        For the paths that change the library without regenerating the catalog - Undo puts an archive back
        where it came from and can remove the folder the run created - where holding on to the old numbers
        would be worse than paying for one fresh walk the next time something asks.
        """
        self._summary = None
        self._library_root = None
        with _COLLECT_CACHE_LOCK:
            _COLLECT_CACHE.clear()

    def _is_app_folder(self, folder):
        r"""True when this folder is the app's own project folder rather than a game category.

        The library root is the app's own project folder when the app is installed there, which is the
        default: `D:\Game Installers\0. Steam Game Organizer` sits inside the library root, and every
        scan picked it up as a category of one game - the app itself. The entry-point filename is the
        one thing that identifies the project regardless of what the folder is called, so the check
        looks for it rather than for a folder name: renaming the project folder no longer re-adds it
        to the catalog.
        """
        return (folder / ENTRY_POINT).is_file()

    def _remove_previous(self, library_root):
        for pattern in self.LEGACY_CATALOGS:
            for old in library_root.glob(pattern):
                if old.name == self.CATALOG_NAME:
                    continue
                try:
                    old.unlink()
                except OSError as exc:
                    self.logger.warning("CATALOG", f"OLD_FILE_REMOVE_FAILED path=[{old}] error={type(exc).__name__}")
        launcher = library_root / self.LEGACY_LAUNCHER
        try:
            if launcher.is_file() and not (library_root / self.CATALOG_NAME).is_file():
                launcher.unlink()
        except OSError as exc:
            self.logger.warning("CATALOG", f"OLD_FILE_REMOVE_FAILED path=[{launcher}] error={type(exc).__name__}")

    def _write_chrome_launcher(self, library_root, html_path):
        # Only written when the machine has no browser association for .html at all, in which case double
        # clicking the catalog would not open a browser. A desktop that already knows what to do with an HTML
        # file gets the catalog on its own, with nothing extra sitting in the library root.
        #
        # There is no browser command anywhere in this file, and there never needed to be. It used to take one
        # and ignore it: a .url with a URL and nothing else is resolved by the shell association, so a command
        # inside it could not have been acted on. The caller asked the registry whether a launcher was needed
        # by searching PATH for five Linux package names and then for three Flatpak app ids, and on this
        # platform every one of those lookups fails - so the answer came from HKCR or it did not come at all.
        file_url = f"file://{pathname2url(str(html_path))}"
        # A .url, not a .desktop. This wrote a Linux desktop entry into the library root on a Windows machine,
        # where Windows has no association for the extension - so the launcher could not be opened at all. The
        # file exists in the real library, naming a browser command that does not exist either: see
        # OrganizerService.chrome_command, which used to invent one when it found no browser.
        launcher = library_root / "Open Game Library.url"
        try:
            launcher.write_text(
                f"[InternetShortcut]\nURL={file_url}\n",
                encoding="utf-8",
            )
            # The temporary older name is removed so a library that already has the dead .desktop does not keep
            # it beside the working one. LEGACY_LAUNCHER handles the release that wrote '(Steam Deck)'.
            for stale in (library_root / "Open Game Library.desktop", library_root / self.LEGACY_LAUNCHER):
                try:
                    stale.unlink()
                except OSError:
                    pass
        except OSError as exc:
            self.logger.warning("CATALOG", f"LAUNCHER_WRITE_FAILED path=[{launcher}] error={type(exc).__name__}")

    def _collect(self, library_root):
        root = Path(library_root).expanduser().resolve()
        key = str(root)
        with _COLLECT_CACHE_LOCK:
            cached = _COLLECT_CACHE.get(key)
            if cached is not None:
                return cached
        categories = {}
        for category_dir in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in LIBRARY_RESERVED_DIRS and not self._is_app_folder(p)):
            games = []
            for game_dir in sorted(p for p in category_dir.iterdir() if p.is_dir()):
                # A game subfolder with no archive is not a game: it is the folder left behind when the
                # game was re-categorised, carrying the Steam link, the metadata and the artwork the
                # organizer wrote. Cataloguing it rendered a card on the shelf for a game that is not
                # there, with a broken Extract button, and every scan reported it as a scan problem.
                # The empty-folder sweep is what removes these; the catalog only has to skip them.
                if not self._find_archive(game_dir):
                    continue
                entry = self._read_game(game_dir, category_dir.name, library_root)
                if entry:
                    games.append(entry)
            if games:
                categories[category_dir.name] = games
        with _COLLECT_CACHE_LOCK:
            _COLLECT_CACHE[key] = categories
        return categories

    def _read_game(self, game_dir, category_name, library_root):
        meta_path = game_dir / ".game-info.json"
        metadata = {}
        if meta_path.is_file():
            try:
                metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                metadata = {}
        # A title that is only whitespace counts as no title. `"   "` is truthy, so the `or` chain used to keep
        # it and render a card whose heading was three spaces - present on the shelf, identifying nothing.
        name = str(metadata.get("name") or "").strip() or re.sub(r"\s*-\s*(?:\d{4}-\d{2}-\d{2}|Unknown Release Date)$", "", game_dir.name).strip() or game_dir.name
        appid = str(metadata.get("appid") or "").strip()
        banner = find_banner(game_dir, asset_prefix(game_dir, metadata))
        banner_rel = str(banner.relative_to(library_root)).replace("\\", "/") if banner else ""
        # Relative folder reference: the catalog is written into the library root, so this path stays valid
        # if the whole Games folder is copied elsewhere. An absolute path would break the moment it moves.
        folder_rel = str(game_dir.relative_to(library_root)).replace("\\", "/")
        archive = self._find_archive(game_dir)
        return {
            "name": name,
            "appid": appid,
            "category": category_name,
            "description": metadata.get("description") or "No description available.",
            "release_date": metadata.get("release_date") or "Unknown release date",
            "developer": metadata.get("developer") or "",
            "publisher": metadata.get("publisher") or "",
            "genres": metadata.get("genres") or [],
            "banner": banner_rel,
            # Steam's own tags. Written into the sidecar since tags were first captured, and read here for the
            # first time: they are the most descriptive thing Steam offers about a game - "Great Soundtrack",
            # "Immersive Sim", "Controller Support" - and none of it is visible anywhere else in the app.
            "tags": clean_tags(metadata.get("tags")),
            "folder": game_dir,
            "folder_rel": folder_rel,
            "archive": archive,
            # Installer signature read from the archive's own index (no extraction): an InstallSignature('iso'/'repack',
            # program) if the archive is a launcher rather than a ready-to-play game, None if it is a game archive or could
            # not be inspected. _find_archive returns the basename, so resolve it against the game folder for the actual
            # file on disk. The on-disk "Needs Install" marker is the fallback; this is the pre-extraction preview.
            "installer": self._archive_installer_kind(game_dir / archive) if archive else None,
            # Size on disk, so the catalog can sort and total a library rather than just list names.
            "archive_size": archive_size(game_dir),
            # Archive creation date: a reliable "is this a new file" signal the reader can compare against
            # the stale-extraction badge when an archive with the same name was replaced by a new download.
            "archive_created": archive_created(game_dir),
            # Full path to the archive on disk, for the stale-extraction check.
            # 'archive' above is a basename; this is the resolved path the marker was written from.
            "_archive_path": str(game_dir / archive) if archive else "",
        }

    def _archive_installer_kind(self, archive):
        """InstallSignature('iso'/'repack' + program name) or None for the archive at `path`.

        Catalog generation must never be blocked by one archive this machine cannot inspect: any exception from the
        sniffer (missing tool, locked file, unrecognised format) is swallowed and the game simply gets no installer
        badge. The post-extraction "Needs Install" marker remains the hard guarantee.
        """
        if not archive:
            return None
        try:
            from services.archive_service import ArchiveService

            return ArchiveService(self.logger).archive_installer_kind(archive)
        except Exception as exc:
            self.logger.warning("CATALOG", f"INSTALLER_KIND_FAILED path=[{Path(archive).name}] error={type(exc).__name__}")
            return None

    def _asset_prefix(self, game_dir, metadata):
        """Filesystem-safe asset prefix for a game folder.

        Delegates to core.catalog_utils.asset_prefix. Kept as a method so existing
        tests and call sites that use `self._asset_prefix(...)` keep working.
        """
        return asset_prefix(game_dir, metadata)

    def _find_banner(self, game_dir, prefix):
        """The best banner image for a game folder, by priority then any image file.

        Delegates to core.catalog_utils.find_banner. Kept as a method so existing
        tests and call sites that use `self._find_banner(...)` keep working.
        """
        return find_banner(game_dir, prefix)

    def _find_archive(self, game_dir):
        """The game archive inside the folder, shown so the catalog lists what is actually on disk."""
        try:
            return next((p.name for p in sorted(game_dir.iterdir()) if p.is_file() and p.suffix.lower() in (".zip", ".rar", ".7z")), "")
        except OSError:
            return ""

    def _unpacked_archives(self, categories, extract_folders=()):
        """Which archives on the page are already unpacked, and where.

        Returns (unpacked, needs_install, stale, unpacked_at, extracted_paths) keyed by
        archive file name. `extracted_paths[name]` is the best-effort actual extracted
        content root (from `.sgo-extract-info` `extracted_root` when present/valid, else the
        found folder). Probes all configured extract folders and both conventional layouts
        (<dest>/<stem> and <dest>/Needs Install/<stem>) so multi-root setups and marker
        relocations are resolved correctly. A stem claimed by more than one card is left out
        entirely rather than guessed at.
        """
        from services.catalog_status import read_extract_marker, resolve_extracted_root

        folders = [Path(p).expanduser() for p in (extract_folders or [])] or [Path.home() / "Downloads" / "Extracted"]
        by_stem = {}
        for games in categories.values():
            for game in games:
                name = game.get("archive") or ""
                if name:
                    by_stem.setdefault(Path(name).stem, []).append(game)
        unpacked = set()
        needs_install = set()
        stale = set()
        unpacked_at = {}
        extracted_paths = {}
        launch_targets = {}
        setup_done = {}
        marker_dirs = {}
        for stem, group in by_stem.items():
            if len(group) != 1:
                continue
            name = group[0].get("archive") or ""
            archive_path = group[0].get("_archive_path") or ""
            if not name:
                continue
            leaf = safe_folder_name(stem)
            found = None
            for dest in folders:
                for candidate in (dest / leaf, dest / NEEDS_INSTALL_DIRNAME / leaf):
                    if already_extracted(candidate):
                        found = candidate
                        break
                if found:
                    break
            if not found:
                continue
            unpacked.add(name)
            marker = read_extract_marker(found) or {}
            actual = resolve_extracted_root(found, folders) or found
            extracted_paths[name] = actual
            marker_dirs[name] = found
            is_needs = bool(marker.get("needs_install")) or has_needs_install_mark(found) or has_needs_install_mark(actual)
            if marker.get("setup_done") and not marker.get("needs_install"):
                setup_done.add(name)
                is_needs = False
            if is_needs:
                needs_install.add(name)
            elif found.parent and found.parent.name == NEEDS_INSTALL_DIRNAME and not marker.get("setup_done"):
                needs_install.add(name)
            launch_target = marker.get("launch_target")
            if launch_target:
                try:
                    target_path = Path(str(launch_target)).expanduser()
                    if target_path.is_file() and target_path.suffix.lower() == ".exe" and (not folders or any(path_within(target_path, f) for f in folders)):
                        launch_targets[name] = str(target_path.resolve())
                except Exception:
                    pass
            if archive_path and archive_has_changed_since_extraction(found, archive_path):
                stale.add(name)
            when = marker.get("extracted_at")
            if when:
                unpacked_at[name] = str(when)
        return unpacked, needs_install, stale, unpacked_at, extracted_paths, launch_targets, setup_done, marker_dirs

    def _render(self, categories, extract_folders=(), library_root=""):
        # The destination is a free-text box, not a dropdown, so the configured folders are offered as
        # suggestions only - the datalist - and the box starts on the first of them.
        folders = [str(Path(p).expanduser()) for p in (extract_folders or [])]
        dest_choices = "".join(f'<option value="{escape(path)}"></option>' for path in folders)
        dest_default = escape(folders[0] if folders else str(Path.home() / "Downloads" / "Extracted"))
        # Where the games are, prefilled rather than left empty. On the machine that ran the scan that value
        # is simply the library the page was written into, so every path on the page is already right before
        # anything is typed; on any other machine - a colleague's, a laptop, the same box after the Games folder has
        # been moved - it is overwritten with where the games actually are. Artwork and the category links are
        # relative to the page and survive a move by themselves, but a copied folder path and an Extract
        # source are not, so those two are rebuilt from this box.
        root_default = escape(str(library_root)) if library_root else ""
        total_games = sum(len(v) for v in categories.values())
        total_art = sum(1 for v in categories.values() for g in v if g["banner"])
        total_bytes = sum(int(g.get("archive_size") or 0) for v in categories.values() for g in v)
        no_art = sum(1 for v in categories.values() for g in v if not g["banner"])
        # Which cards carry the "already unpacked" badge. Checks all configured extract folders and uses
        # marker `extracted_root` when present; open-extracted links prefer the actual recorded root.
        unpacked, needs_install, stale, unpacked_at, extracted_paths, launch_targets, setup_done, marker_dirs = self._unpacked_archives(categories, extract_folders)
        # Count games that are already unpacked and have an archive, so the "Unextracted only" stat can show a
        # count that answers "how much is left to do?" at a glance.
        has_archive = sum(1 for v in categories.values() for g in v if g["archive"])
        already_unpacked = len(unpacked)
        already_stale = len(stale)
        # Years are counted per-game for the rail's year chips. Decades would be too coarse on a shelf of 166
        # games spanning 1995–2025; a per-year count keeps each chip honest and the row short enough to scan.
        year_counts = {}
        for games in categories.values():
            for game in games:
                raw = sort_date(game.get("release_date")) or ""
                if len(raw) >= 4:
                    try:
                        y = int(raw[:4])
                    except ValueError:
                        y = 0
                    if y > 0:
                        year_counts[y] = year_counts.get(y, 0) + 1
        years = sorted(year_counts, reverse=True)
        year_chips = "".join(f'<button class="chip-btn chip-btn-year" type="button" aria-pressed="false" data-year="{y}">{y}<span class="chip-count">{year_counts[y]}</span></button>' for y in years)
        # Games added recently, by days since the archive was created on disk. A 7/14/30 day chip lets a
        # reader narrow the shelf to what they just pulled in, without typing a date they do not know.
        from datetime import datetime as _dt

        day_counts = {}
        for days in (7, 14, 30):
            count = 0
            for games in categories.values():
                for game in games:
                    created = game.get("archive_created") or ""
                    if not created:
                        continue
                    try:
                        then = _dt.strptime(created, "%Y-%m-%d %H:%M")
                    except ValueError:
                        continue
                    age = (_dt.now() - then).days
                    if 0 <= age <= days:
                        count += 1
            day_counts[days] = count
        day_chips = "".join(f'<button class="chip-btn chip-btn-days" type="button" aria-pressed="false" data-days="{d}">{d}d<span class="chip-count">{day_counts[d]}</span></button>' for d in (7, 14, 30) if day_counts[d])
        # The genre rail is derived from what is actually on disk rather than a fixed vocabulary, so it stays
        # useful for a library of any shape and is never a row of filters that match nothing.
        genre_counts = {}
        for games in categories.values():
            for game in games:
                for genre in game["genres"][:6]:
                    key = str(genre).strip()
                    if key:
                        genre_counts[key] = genre_counts.get(key, 0) + 1
        top_genres = [name for name, _ in sorted(genre_counts.items(), key=lambda item: (-item[1], item[0].casefold()))[:24]]
        # The same treatment for Steam's tags, which outnumber genres several times over and are the more
        # useful filter on a shelf of 165 games: "Great Soundtrack" or "Immersive Sim" narrows to a handful
        # where "Action" narrows to most of the library. Counted from what is on disk for the same reason -
        # a fixed vocabulary would be a row of filters that match nothing.
        tag_counts = {}
        for games in categories.values():
            for game in games:
                for tag in game["tags"]:
                    if tag:
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1
        top_tags = [name for name, _ in sorted(tag_counts.items(), key=lambda item: (-item[1], item[0].casefold()))[:24]]
        tag_chips = "".join(f'<button class="chip-btn chip-btn-tag" type="button" aria-pressed="false" data-genre="{escape(name)}">{escape(name)}<span class="chip-count">{tag_counts[name]}</span></button>' for name in top_tags)
        # The hero already reports how many games have no artwork, but it was a number the reader could do
        # nothing with - on a shelf where a third of the cards are placeholders, "34 missing art" is exactly
        # the thing you want to filter down to and then go and fix. Rendered as a real toggle when there is
        # anything to filter, and still a plain tile when there is none, so a complete library is not offered
        # a filter that cannot narrow anything.
        no_art_stat = f'<button class="stat stat-filter" type="button" data-filter="noart" aria-pressed="false" title="Show only the games with no artwork"><span class="stat-value">{no_art}</span><span class="stat-label">Missing art</span></button>' if no_art else f'<div class="stat stat-good"><span class="stat-value">{no_art}</span><span class="stat-label">Missing art</span></div>'
        remaining = has_archive - already_unpacked
        unextracted_stat = (
            f'<button class="stat stat-filter" type="button" data-filter="unextracted" aria-pressed="false" title="Show only games that have not been unpacked yet"><span class="stat-value">{remaining}</span><span class="stat-label">To extract</span></button>' if remaining else f'<div class="stat stat-good"><span class="stat-value">{remaining}</span><span class="stat-label">To extract</span></div>'
        )
        stale_stat = (
            f'<button class="stat stat-filter" type="button" data-filter="stale" aria-pressed="false" title="Show only games whose archive changed since extraction"><span class="stat-value">{already_stale}</span><span class="stat-label">New version</span></button>'
            if already_stale
            else f'<div class="stat stat-good"><span class="stat-value">{already_stale}</span><span class="stat-label">New version</span></div>'
        )
        hide_extracted_stat = (
            f'<button class="stat stat-filter" type="button" data-filter="hide_extracted" aria-pressed="false" title="Hide already-extracted games, keeping only those with no archive or a new version available"><span class="stat-value">{already_unpacked}</span><span class="stat-label">Hide extracted</span></button>'
            if remaining < has_archive
            else '<div class="stat stat-good"><span class="stat-value">0</span><span class="stat-label">Hide extracted</span></div>'
        )
        # data-toc-count is what lets the rail recount itself as a filter narrows the shelf. Without it the
        # numbers beside every category kept reporting the unfiltered totals, so a search matching 12 games
        # still showed 166 beside the category list.
        toc_items = "".join(f'<li><a class="toc-link" href="#{anchor(name)}" data-target="{anchor(name)}"><span class="toc-dot" aria-hidden="true"></span><span class="toc-name">{escape(name)}</span><span class="count" data-toc-count="{anchor(name)}">{len(games)}</span></a></li>' for name, games in categories.items())
        genre_chips = "".join(f'<button class="chip-btn" type="button" aria-pressed="false" data-genre="{escape(name)}">{escape(name)}<span class="chip-count">{genre_counts[name]}</span></button>' for name in top_genres)
        # Games that are already unpacked, shown first as a "ready to play" section so
        # the reader sees what they can jump straight into before browsing categories.
        recent_games = []
        for games in categories.values():
            for g in games:
                if g["archive"] and g["archive"] in unpacked:
                    recent_games.append(g)
        recent_games.sort(key=lambda g: unpacked_at.get(g["archive"], ""), reverse=True)
        recent_section = self._render_recent(recent_games, unpacked, needs_install, stale, unpacked_at, extracted_paths, launch_targets, setup_done, marker_dirs) if recent_games else ""
        sections = recent_section + "".join(self._render_section(name, games, unpacked, needs_install, stale, unpacked_at, extracted_paths, launch_targets, setup_done, marker_dirs) for name, games in categories.items())
        # Split into separate lines because a wall of prose is why this was 287 characters on one line: as a list
        # each point is separately readable, and the whole thing collapses out of the way until it is asked for.
        subtitle = "Cards open the Steam store page in your browser • Open in Steam launches the client • Copy the folder path to jump straight to the files • If the games live somewhere else now, set the game folder and both follow it — Extract also has to be inside the folder the app itself is pointed at"
        help_points = [part.strip() for part in subtitle.split("•") if part.strip()]
        help_items = "".join(f"<li>{escape(point)}</li>" for point in help_points)
        return f'''<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>Game Library</title>
<style>
{self._css()}
</style>
</head>
<body>
<div class="progress" aria-hidden="true"><span id="progress-bar"></span></div>
<header class="hero">
  <div class="hero-inner">
    <h1><span class="glyph" aria-hidden="true">&#127918;</span> Game Library</h1>
    <div class="stats">
      <div class="stat"><span class="stat-value">{total_games}</span><span class="stat-label">Games</span></div>
      <div class="stat"><span class="stat-value">{day_counts.get(7, 0)}</span><span class="stat-label">Added this week</span></div>
      <div class="stat"><span class="stat-value">{len(categories)}</span><span class="stat-label">Categories</span></div>
      <div class="stat"><span class="stat-value">{total_art}</span><span class="stat-label">With artwork</span></div>
      <div class="stat"><span class="stat-value">{escape(human_size(total_bytes)) if total_bytes else "0 B"}</span><span class="stat-label">On disk</span></div>
      {no_art_stat}
      {unextracted_stat}
      {stale_stat}
      {hide_extracted_stat}
    </div>
    <p class="generated">Generated {escape(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))} — regenerates on every scan</p>
    <p class="tagline">{total_games} games across {len(categories)} categories</p>
  </div>
</header>
<!-- Filled from Game Library.status.js, which the app rewrites after every batch run. It is left hidden when
     there is no run to report, which is the state of a library that has just been scanned. The element is in
     the page rather than written into it so that a run finishing hours later can still reach a page that was
     written before that run started. -->
<div id="run-status" class="run-status" role="status" aria-live="polite" hidden></div>
<div class="bar">
  <div class="bar-inner">
    <label class="field">
      <span class="field-icon" aria-hidden="true">&#128269;</span>
      <input id="search" type="search" placeholder="Search games, genres, developers…" autocomplete="off" aria-label="Search games">
    </label>
    <p id="result-count" class="result-count" role="status" aria-live="polite"></p>
    <div class="sorts" role="group" aria-label="Sort games">
      <span class="sorts-label">Sort</span>
      <button class="sort is-active" type="button" data-sort="name">Name</button>
      <button class="sort" type="button" data-sort="date" data-desc="1" title="Sort by release date, newest first">Newest</button>
      <button class="sort" type="button" data-sort="date" title="Sort by release date, oldest first">Oldest</button>
      <button class="sort" type="button" data-sort="size" data-desc="1">Largest</button>
      <button class="sort" type="button" data-sort="size" title="Sort by archive size, smallest first">Smallest</button>
      <button class="sort" type="button" data-sort="added" data-desc="1" title="Sort by when you got the file, newest first">Recently added</button>
      <button class="sort" type="button" data-sort="added" title="Sort by when you got the file, oldest first">Longest owned</button>
    </div>
    <label class="root">
      <span class="sorts-label">Game folder</span>
      <input id="game-folder" type="text" value="{root_default}" spellcheck="false"
             autocomplete="off" aria-label="Folder the game library is in on this machine" placeholder="C:\\Users\\you\\Downloads\\Games">
    </label>
    <label class="dest">
      <span class="sorts-label">Extract to</span>
      <input id="extract-dest" type="text" list="dest-choices" value="{dest_default}" spellcheck="false"
             autocomplete="off" aria-label="Folder to extract games into" placeholder="C:\\Users\\you\\Downloads\\Extracted">
      <datalist id="dest-choices">{dest_choices}</datalist>
    </label>
    <!-- The third box cannot live here: a file:// page cannot write a file, so the folder
         choices a page offers are remembered by the browser alone and never reach the app.
         This button hands the two boxes above to the app's own setup wizard, which saves
         them where the Extract links are checked against, and registers the
         steamgameorganizer:// link the buttons go through. -->
<a class="btn btn-setup" id="setup-link" href="{setup_uri()}" data-setup="{setup_uri()}"
        title="Set the game library, this app and the extract folder for this PC">Set up on this PC</a>
<span class="setup-fallback" id="setup-fallback" hidden>
          <span class="setup-fallback-text">Nothing opened? Open a terminal in the game folder and paste this:</span>
          <code class="setup-cmd" id="setup-cmd" title="Click to copy">{escape(self._setup_cmd)}</code>
          <button class="btn-copy-cmd" id="setup-copy" title="Copy the command to the clipboard">Copy</button>
        </span>
      {batch_button("", total_games, total_bytes, "Extract all", "Unpack every game in the whole library", scope="the whole library") if total_games else ""}
      {remaining_button(sum(1 for games in categories.values() for g in games if g["archive"] and g["archive"] not in unpacked), "Extract remaining", "Unpack only games not already extracted") if total_games else ""}
      <button id="refresh-catalog" class="btn btn-ghost" type="button" data-refresh="{refresh_uri()}" title="Re-scan the library and refresh this page so Unpacked badges match what is on disk">Refresh catalog</button>
      <button id="multi-btn" class="btn btn-warning" type="button" data-multi="select" title="Select games to extract them together">Select games</button>
    <button id="extract-selected" class="btn btn-accent" type="button" data-multi="extract" title="Extract the selected games" hidden>Extract <span id="multi-count">0</span></button>
    <button id="clear-selection" class="btn btn-ghost" type="button" data-multi="clear" title="Clear the selection" hidden>Clear</button>
    <div class="size-toggle">
      <button class="size-btn" data-size="medium" title="Medium cards">M</button>
      <button class="size-btn" data-size="large" title="Large cards">L</button>
    </div>
    <button id="theme" class="icon-btn" type="button" title="Switch between dark and light" aria-label="Switch between dark and light">&#9681;</button>
    <p id="empty" class="empty" hidden>No games match that search.</p>
  </div>
</div>
<div class="shell">
  <aside class="rail">
      <div id="batch-status" class="batch-status" role="status" aria-live="polite" hidden></div>
     <nav class="toc" aria-label="Categories"><p class="rail-title">Categories</p><ul>{toc_items}</ul></nav>
    {f'<nav class="years" aria-label="Release years"><p class="rail-title">Years</p><div class="chip-row">{year_chips}</div></nav>' if year_chips else ""}
    {f'<nav class="days" aria-label="Recently added"><p class="rail-title">Added</p><div class="chip-row">{day_chips}</div></nav>' if day_chips else ""}
    {f'<nav class="genres" aria-label="Genres"><p class="rail-title">Genres</p><div class="chip-row">{genre_chips}</div></nav>' if genre_chips else ""}
    {f'<nav class="tags-nav" aria-label="Tags"><p class="rail-title">Tags</p><div class="chip-row">{tag_chips}</div></nav>' if tag_chips else ""}
    <!-- Was a single 287-character paragraph sitting permanently at the bottom of the rail, which measured 144px
         of a 236px column to say six things the reader had not asked for yet. A disclosure costs one line until
         wanted, and native <details> needs no script and no state to get wrong. -->
    <details class="rail-help">
      <summary>How this page works</summary>
      <ul>{help_items}</ul>
    </details>
  </aside>
   <main>
      {sections}
   </main>
</div>
<button id="to-top" class="to-top" type="button" title="Back to top (Home)" aria-label="Back to top">&#8593;</button>
<div id="toast" class="toast" role="status" aria-live="polite"></div>
<!-- Before the page's own script on purpose. A classic script tag is the one thing a file:// page is allowed
     to load from beside itself - fetch and XHR are both blocked there - so this is how a batch run reports back
     into a page that was written before it ran. Loading it first means the data is already on window by the
     time the script below looks for it. If the file is absent the tag is a no-op and the page is unaffected. -->
<script src="{escape(STATUS_NAME)}"></script>
<script>
{self._script()}
</script>
<footer><p>Generated automatically by {APP_NAME}. Regenerated on every scan. Press <kbd>/</kbd> to search, <kbd>Esc</kbd> to clear.</p>
<p class="foot-note">Extract and Extract all go through a <code>steamgameorganizer://</code> link, which only
works once {APP_NAME} has been set up on this machine &mdash; the <em>Set up on this PC</em> button at the
top of the page sets the three folders and registers the link. On a PC where the app has never run, start it
once with <code>{escape(self._setup_cmd)}</code> first. If a button does nothing, that is the
first thing to check &mdash; <em>Copy folder path</em> works either way.</p></footer>
</body>
</html>'''

    def _render_section(self, name, games, unpacked=(), needs_install=(), stale=(), unpacked_at=None, extracted_paths=None, launch_targets=None, setup_done=None, marker_dirs=None):
        # Custom per-category banner so every category looks distinct instead of all reusing the
        # first game's art. Falls back to the generated name-based banner for unknown categories.
        header_image = _category_banner(name)
        layers = f"--gen:url('{header_image}')"
        real_banner = next((g["banner"] for g in games if g["banner"]), "")
        if real_banner:
            layers += f";--real:url('{real_banner}')"
        unpacked_at = unpacked_at or {}
        cards = "".join(self._render_card(g, unpacked, needs_install, stale, unpacked_at, extracted_paths=extracted_paths, launch_targets=launch_targets, setup_done=setup_done, marker_dirs=marker_dirs) for g in games)
        total = sum(int(g.get("archive_size") or 0) for g in games)
        with_art = sum(1 for g in games if g["banner"])
        facts = f'<span class="category-facts">{len(games)} game{"" if len(games) == 1 else "s"}'
        if total:
            facts += f' <span class="dot">•</span> {escape(human_size(total))}'
        if with_art < len(games):
            facts += f' <span class="dot">•</span> {len(games) - with_art} without art'
        facts += "</span>"
        return f'''<section id="{anchor(name)}" class="category" data-category="{escape(name)}">
  <div class="category-header" style="{layers}">
    <div class="category-titles">
      <h2>{escape(name)}</h2>
      {facts}
    </div>
   <div class="category-actions">
      {batch_button(name, len(games), total, "Extract all", "Unpack every game in this category")}
      {remaining_button(sum(1 for g in games if g["archive"] and g["archive"] not in unpacked), "Extract remaining", "Unpack only games in this category not already extracted")}
      <button class="jump-top" type="button" title="Jump back to the top of the catalog">&#8593; Top</button>
    </div>
  </div>
  <div class="grid">{cards}</div>
 </section>'''

    def _render_recent(self, games, unpacked=(), needs_install=(), stale=(), unpacked_at=None, extracted_paths=None, launch_targets=None, setup_done=None, marker_dirs=None):
        """A banner section at the top showing games already unpacked."""
        unpacked_at = unpacked_at or {}
        extracted_paths = extracted_paths or {}
        cards = "".join(self._render_card(g, unpacked, needs_install, stale, unpacked_at, show_badges=False, extracted_paths=extracted_paths, launch_targets=launch_targets, setup_done=setup_done, marker_dirs=marker_dirs) for g in games)
        total = sum(int(g.get("archive_size") or 0) for g in games)
        with_art = sum(1 for g in games if g["banner"])
        facts = f'<span class="category-facts">{len(games)} game{"" if len(games) == 1 else "s"} unpacked'
        if total:
            facts += f' <span class="dot">•</span> {escape(human_size(total))}'
        if with_art < len(games):
            facts += f' <span class="dot">•</span> {len(games) - with_art} without art'
        facts += "</span>"
        layers = f"--gen:url('{banner_data_uri('Recently extracted')}')"
        return f'''<section id="{anchor("Recently extracted")}" class="category recent" data-category="Recently extracted">
  <div class="category-stuck" aria-hidden="true"><span class="category-stuck-name">Recently extracted</span></div>
  <div class="category-header" style="{layers}">
    <div class="category-titles">
      <h2>Recently extracted</h2>
      {facts}
    </div>
    <div class="category-actions">
      <button class="jump-top" type="button" title="Jump back to the top of the catalog">&#8593; Top</button>
    </div>
  </div>
  <div class="grid">{cards}</div>
</section>'''

    def _render_card(self, game, unpacked=(), needs_install=(), stale=(), unpacked_at=None, show_badges=True, extracted_paths=None, launch_targets=None, setup_done=None, marker_dirs=None):
        unpacked_at = unpacked_at or {}
        extracted_paths = extracted_paths or {}
        launch_targets = launch_targets or {}
        setup_done = setup_done or set()
        marker_dirs = marker_dirs or {}
        # A game with no artwork used to get a flat grey block reading "No artwork", which on a shelf of 166
        # cards read as broken rather than art-free. It gets the same generated banner the categories get,
        # keyed on the game's own name, so every card looks designed and the shelf still reads as one shelf.
        art = f"{banner_data_uri(game['name'])}" if not game["banner"] else escape(game["banner"])
        appid = game["appid"]
        # A game with no Steam match still gets a card. It used to be dropped here instead, which quietly
        # under-reported the library: no AppID is a routine scan result, not a reason a folder on disk stops
        # being one of your games. Only the two Steam actions need an AppID, so only those go away - the
        # card keeps its artwork, its archive, its size and both path buttons, and says why the Steam
        # actions are missing rather than rendering a link to store.steampowered.com/app// .
        linked = bool(appid)
        link_open = f'<a class="card-link" href="{store_url(appid)}" target="_blank" rel="noopener" title="Open {escape(game["name"])} on Steam">' if linked else '<div class="card-link card-link-plain" title="No Steam match for this game">'
        link_close = "</a>" if linked else "</div>"
        steam_button = f'<a class="btn btn-steam" href="{steam_protocol_url(appid)}" title="Open in the Steam client">Open in Steam</a>' if linked else ""
        no_match_badge = "" if linked else '<span class="badge badge-muted">No Steam match</span>'
        description = game["description"]
        truncated = description[:220] + ("…" if len(description) > 220 else "")
        archive_badge = f'<span class="badge">{escape(game["archive"])}</span>' if game["archive"] else ""
        # The badge is drawn from the same predicate the batch planner skips on, so it cannot claim a game is
        # done that Extract all would unpack again. data-unpacked rides along so the script can retract the
        # badge when the reader types a different destination - the check was made against one folder only,
        # and saying so is better than leaving a claim standing that is no longer true.
        # Badges are suppressed in the "Recently extracted" banner, which duplicates cards that also appear in
        # their category section - showing the same badge twice would double the count the reader sees.
        is_unpacked = bool(game["archive"]) and game["archive"] in unpacked
        is_needs_install = bool(game["archive"]) and game["archive"] in needs_install
        is_setup_done = bool(game["archive"]) and game["archive"] in setup_done
        # Stale is a state (archive changed since extraction). Actions and data attrs use state; the visual
        # badge can be suppressed in duplicate/recent sections via show_badges.
        is_stale = bool(game["archive"]) and game["archive"] in stale
        # An installer repack is unpacked but not yet playable: show amber where an already-unpacked game shows
        # green, so the two states cannot be read as the same thing. Both carry data-result so the script retracts
        # whichever one a card has when the reader points the box somewhere else.
        if show_badges and is_needs_install:
            unpacked_on = unpacked_at.get(game["archive"], "")
            done_badge = (
                f'<span class="badge badge-warn" data-result title="Extracted into a {NEEDS_INSTALL_DIRNAME} '
                f"folder - run the installer there to install" + (f" on {unpacked_on}" if unpacked_on else "") + '">'
                '<svg class="badge-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" '
                'aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2" '
                'stroke="currentColor" stroke-width="2.5"/><path d="M8 11l4 4 4-4" stroke="currentColor" '
                'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg> Needs install' + (f' <span class="unpacked-on">{escape(unpacked_on)}</span>' if unpacked_on else "") + "</span>"
            )
        elif show_badges and is_unpacked:
            unpacked_on = unpacked_at.get(game["archive"], "")
            done_title = "Already unpacked into the folder Extract to defaults to" + (f" on {unpacked_on}" if unpacked_on else "")
            done_badge = '<span class="badge badge-done" data-result title="' + escape(done_title) + '">Unpacked' + (f' <span class="unpacked-on">{escape(unpacked_on)}</span>' if unpacked_on else "") + "</span>"
        else:
            done_badge = ""
        if show_badges and is_stale:
            stale_badge = (
                '<span class="badge badge-stale" data-result title="The archive has changed since extraction - re-extract to update">'
                '<svg class="badge-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" '
                'aria-hidden="true"><rect x="1" y="4" width="22" height="16" rx="2" '
                'stroke="currentColor" stroke-width="2.5"/><path d="M12 11V5v6m0 0l4-4m-4 4l-4-4" '
                'stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>'
                "</svg> New version</span>"
            )
        else:
            stale_badge = ""
        # Pre-extraction installer badge: only for an archive that is an installer but has not been unpacked yet.
        # "Needs install" and "Unpacked" already speak for a game that has been touched; installer is the *preview*
        # of what the archive is when neither of those yet applies. No data-result attribute: this is a property of
        # the archive itself, not a run result, so the retract-on-destination-change script leaves it alone.
        is_installer = show_badges and bool(game.get("installer")) and not is_unpacked and not is_needs_install
        if is_installer:
            kind = game["installer"].kind
            program = game["installer"].program.name
            install_badge = (
                f'<span class="badge badge-install" title="This archive is a {kind} installer ({program}); '
                f'unpack it then run {program} to install this game">'
                '<svg class="badge-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" '
                'aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2" '
                'stroke="currentColor" stroke-width="2.5"/><path d="M8 11l4 4 4-4" stroke="currentColor" '
                'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg> Installer</span>'
            )
        else:
            install_badge = ""
        genre_badges = "".join(f'<span class="chip">{escape(str(g))}</span>' for g in game["genres"][:3])
        # Steam's tags get their own row rather than sharing the badge line with genres. They answer a different
        # question - "what is this like to play" rather than "what kind of thing is it" - and mixing the two made
        # a card whose first badge row was six near-identical grey pills. Capped at four: past that the row stops
        # being a summary and starts being a wall, and the full list is in the search index either way.
        tag_row = ""
        if game["tags"]:
            shown_tags = "".join(f'<span class="chip chip-tag" title="{escape(t)}">{escape(t)}</span>' for t in game["tags"][:4])
            more = f'<span class="chip chip-more">+{len(game["tags"]) - 4}</span>' if len(game["tags"]) > 4 else ""
            tag_row = f'<div class="tags">{shown_tags}{more}</div>'
        size = int(game.get("archive_size") or 0)
        size_line = f'<span class="size">{escape(human_size(size))}</span>' if size else ""
        facts = [part for part in (escape(game["release_date"]), escape(game["developer"]) or "") if part]
        added = escape(game["archive_created"]) or ""
        if added:
            facts.append(f"Added {added}")
        fact_line = '<p class="meta">' + ' <span class="dot">•</span> '.join(facts) + "</p>" if facts else ""
        # Sort keys are precomputed here rather than parsed out of the rendered text in the browser.
        # The haystack also carries the release date and the description, so "2019" or "rogue-like" finds a game.
        # It used to be name, category, developer, publisher, archive and genres only, which made the two most
        # identifying things about a game - when it came out and what it is about - unsearchable. The description
        # is already truncated for display, so this costs the shelf about a fifth of a kilobyte per card.
        haystack = " ".join([game["name"], game["category"], game["developer"], game["publisher"], game["archive"], str(game.get("release_date") or ""), str(game.get("archive_created") or ""), game["description"], " ".join(str(g) for g in game["genres"]), " ".join(game["tags"])]).casefold()
        sort_name = game["name"].casefold()
        sort_date_key = sort_date(game["release_date"])
        sort_size = str(size)
        sort_added = game.get("archive_created") or ""
        sort_days = ""
        created = game.get("archive_created") or ""
        if created:
            try:
                sort_days = str((datetime.now() - datetime.strptime(created, "%Y-%m-%d %H:%M")).days)
            except ValueError:
                sort_days = ""
        # One facet attribute carries genres and tags together, so a single chip in the rail filters either and
        # the two kinds of chip cannot disagree about what they match. The attribute name is kept from when it
        # only held genres because the script reads it, not because it describes only genres any more.
        facets = []
        for value in list(game["genres"]) + game["tags"]:
            text = str(value).strip()
            if text and text not in facets:
                facets.append(text)
        genre_attrs = "".join(f' data-genre="{escape(facet)}"' for facet in facets[:8])
        extract_link = extract_uri(game)
        folder_uri = open_folder_uri(game)
        # The library-relative folder and the archive name ride along on both path buttons, so the page can
        # rebuild a path under whichever game folder is typed into the toolbar. Without them the only copy of
        # either belongs to the machine that ran the scan, and both buttons break the moment the folder moves.
        folder_attr = f' data-rel="{escape(game["folder_rel"])}"'
        archive_attr = f' data-archive="{escape(game["archive"])}"' if game["archive"] else ""
        # Compute extracted folder path (for open-extracted). Prefer the absolute path recorded by the marker
        # (supports alternate extract roots/layouts); fall back to destination-relative <stem>/Needs Install layout.
        extracted_rel = ""
        extracted_path = ""
        launch_target = ""
        marker_dir = ""
        if game.get("archive"):
            stem = Path(game["archive"]).stem
            leaf = safe_folder_name(stem)
            actual = extracted_paths.get(game["archive"])
            if actual:
                try:
                    extracted_path = str(Path(actual))
                except Exception:
                    extracted_path = ""
            lt = launch_targets.get(game["archive"])
            if lt:
                try:
                    launch_target = str(Path(lt))
                except Exception:
                    launch_target = ""
            # Use extracted_path (actual content root) for marker_dir so pick-launcher/Play
            # target the game folder, not the marker folder. Fall back to marker_dirs.
            actual_root = extracted_paths.get(game["archive"])
            if actual_root:
                try:
                    marker_dir = str(Path(actual_root))
                except Exception:
                    marker_dir = ""
            else:
                md = marker_dirs.get(game["archive"])
                if md:
                    try:
                        marker_dir = str(Path(md))
                    except Exception:
                        marker_dir = ""
            if is_needs_install:
                extracted_rel = f"{NEEDS_INSTALL_DIRNAME}/{leaf}"
            elif is_unpacked:
                extracted_rel = leaf
        extracted_attr = f' data-extracted-rel="{escape(extracted_rel)}"' if extracted_rel else ""
        extracted_path_attr = f' data-extracted-path="{escape(extracted_path)}"' if extracted_path else ""
        needs_install_attr = ' data-needs-install="1"' if is_needs_install else ""
        setup_done_attr = ' data-setup-done="1"' if is_setup_done else ""
        launch_target_attr = f' data-launch-target="{escape(launch_target)}"' if launch_target else ""
        marker_dir_attr = f' data-marker-dir="{escape(marker_dir)}"' if marker_dir else ""
        state_attrs = f"{extracted_attr}{extracted_path_attr}{needs_install_attr}{setup_done_attr}{launch_target_attr}{marker_dir_attr}"
        play_action = ""
        pick_launcher_action = ""
        mark_installed_action = ""
        if (extracted_rel or extracted_path) and marker_dir:
            pick_launcher_action = f'<a class="btn btn-folder btn-pick-launcher" href="#" data-pick-launcher="1"{folder_attr}{archive_attr}{state_attrs} title="Choose the main game .exe once for Play">Pick launcher</a>'
        if (extracted_rel or extracted_path) and launch_target and not is_needs_install and not is_stale:
            play_action = f'<a class="btn btn-play" href="#" data-play="1"{folder_attr}{archive_attr}{state_attrs} title="Play using the saved launcher, or choose it once">Play</a>'
        if is_needs_install and not is_setup_done and marker_dir and (extracted_rel or extracted_path):
            mark_installed_action = f'<a class="btn btn-folder btn-mark-installed" href="#" data-mark-installed="1"{folder_attr}{archive_attr}{state_attrs} title="Mark setup/installation as complete so Play becomes available">Mark installed</a>'

        # Primary action: Extract / Re-extract / Play (ready) / Open installer / Open extracted
        if extract_link and is_stale:
            primary_button = f'<a class="btn btn-extract btn-reextract" href="{extract_link}" data-extract="{extract_link}"{folder_attr}{archive_attr}{state_attrs} title="A newer archive is available - extract to update">Re-extract</a>'
        elif play_action:
            primary_button = play_action
        elif is_needs_install and (extracted_rel or extracted_path):
            primary_button = f'<a class="btn btn-open-extracted" href="#" data-open-extracted="1"{folder_attr}{archive_attr}{state_attrs} title="Open the folder with installer files">Open installer</a>'
        elif is_unpacked and (extracted_rel or extracted_path):
            primary_button = f'<a class="btn btn-open-extracted" href="#" data-open-extracted="1"{folder_attr}{archive_attr}{state_attrs} title="Open the extracted game folder">Open extracted</a>'
        elif extract_link:
            primary_button = f'<a class="btn btn-extract" href="{extract_link}" data-extract="{extract_link}"{folder_attr}{archive_attr}{state_attrs} title="Unpack this archive to the chosen destination">Extract</a>'
        else:
            primary_button = ""
        # Secondary actions: stale access, pick launcher, mark installed. Never duplicate primary.
        secondary_actions = []
        if is_stale and (extracted_rel or extracted_path) and not is_needs_install:
            secondary_actions.append(f'<a class="btn btn-folder" href="#" data-open-extracted="1"{folder_attr}{archive_attr}{state_attrs} title="Open the currently extracted folder (before updating)">Open extracted</a>')
        elif is_stale and (extracted_rel or extracted_path) and is_needs_install:
            secondary_actions.append(f'<a class="btn btn-folder" href="#" data-open-extracted="1"{folder_attr}{archive_attr}{state_attrs} title="Open the installer folder (before updating)">Open installer</a>')
        if pick_launcher_action:
            secondary_actions.append(pick_launcher_action)
        if mark_installed_action:
            secondary_actions.append(mark_installed_action)
        secondary_open = "".join(secondary_actions)
        archive_abs = escape(str(game["folder"] / game["archive"])) if game["archive"] else ""
        checkbox = f'<input class="card-check" type="checkbox" data-archive-path="{archive_abs}"{archive_attr}>' if game["archive"] else ""
        copy_button = f'<button class="btn btn-copy" data-rel="{escape(game["folder_rel"])}" data-archive="{escape(game["archive"])}" data-copy="" title="Copy the folder path to the clipboard">Copy path</button>' if game["archive"] else ""
        return f'''<article class="card" data-search="{escape(haystack)}" data-name="{escape(sort_name)}" data-date="{sort_date_key}" data-size="{sort_size}" data-added="{escape(sort_added)}" data-art="{"1" if game["banner"] else "0"}"{' data-days="' + sort_days + '"' if sort_days else ""}{' data-unpacked="1"' if is_unpacked or is_needs_install else ""}{' data-stale="1"' if is_stale else ""}{genre_attrs}>
  {link_open}
    <div class="card-art">
      <img loading="lazy" src="{art}" alt="{escape(game["name"])} artwork">
      {checkbox}
      <span class="scrim" aria-hidden="true"></span>
      <span class="card-cat">{escape(game["category"])}</span>
       <span class="card-hover"><span class="hover-date">Releases {escape(game["release_date"]) if game["release_date"] else "date unknown"}</span><span class="hover-genres">{escape(", ".join(str(g) for g in game["genres"][:5]) if game["genres"] else "No genres listed")}</span></span>
    </div>
    <div class="card-body">
      <h3>{escape(game["name"])}</h3>
      {fact_line}
      <p class="desc">{escape(truncated)}</p>
      {tag_row}
       <div class="badges">{genre_badges}{no_match_badge}{archive_badge}{install_badge}{done_badge}{stale_badge}{size_line}</div>
    </div>
  {link_close}
  <div class="card-actions">
    <!-- Extract goes through a registered steamgameorganizer:// handler. A page genuinely cannot open a folder
         or run a program - that boundary is the whole point of the sandbox - but a protocol handler is the one
         supported way to ask the desktop to, and the browser still confirms before it hands the link over.
         Copy-path stays as the fallback for a machine where the handler was never installed, where it is the
         only thing that works with no setup at all. -->
    {primary_button}
    {secondary_open}
    <a class="btn btn-folder" href="{folder_uri}" data-open-folder="{folder_uri}"{folder_attr} title="Open this game's archive/source folder in Explorer">Open source</a>
     {copy_button}
    {steam_button}
   </div>
</article>'''

    def _script(self):
        if getattr(self, "_script_cache", None) is not None:
            return self._script_cache
        # Plain ES5-ish JS with no build step and no external requests, so the page stays fully offline.
        # execCommand('copy') is used rather than the async clipboard API because file:// pages are not a
        # secure context in Chrome, where navigator.clipboard is unavailable. localStorage is likewise wrapped:
        # it throws outright on a file:// page in some browsers rather than returning null.
        # Raw, so the backslashes in the path-building regexes reach the browser as written. Read as a normal
        # string "\\\\" collapsed to one, and /[\\]+$/ is a character class with an escaped bracket in it: the
        # page's whole script would then be a syntax error and none of it would run.
        self._script_cache = r"""
(function(){
   var doc=document.documentElement;
   var search=document.getElementById('search'), empty=document.getElementById('empty'), toast=document.getElementById('toast');
   var cards=Array.prototype.slice.call(document.querySelectorAll('.card'));
     var state={genre:'',noart:false,year:'',unextracted:false,hide_extracted:false,days:''};
   var counts=Array.prototype.slice.call(document.querySelectorAll('[data-toc-count]'));
   var tally=document.getElementById('result-count');
   var root;
   // Protocol handler detection: try to navigate to the scheme; if it fails, show a persistent banner.
   var handlerChecked=false, handlerWorks=null;
   function store(key,value){
     try{if(value===undefined){return window.localStorage.getItem(key);}window.localStorage.setItem(key,value);}catch(e){return null;}
   }
   function show(msg, duration){
     toast.textContent=msg; toast.className='toast show';
     clearTimeout(toast._t);
     toast._t=setTimeout(function(){toast.className='toast';}, duration || 1800);
   }
   function copyText(text){
     var path=text;
     if(!path) return;
     // Prefer modern clipboard API (works on https, fails on file:// in Chrome).
     if(navigator.clipboard && navigator.clipboard.writeText){
       navigator.clipboard.writeText(path).then(
         function(){show('Copied: '+path);},
         function(){fallbackCopy(path);}
       );
     }else{
       fallbackCopy(path);
     }
     function fallbackCopy(p){
       var ta=document.createElement('textarea'); ta.value=p;
       ta.setAttribute('readonly',''); ta.style.position='fixed'; ta.style.opacity='0';
       document.body.appendChild(ta); ta.select();
       try{document.execCommand('copy'); show('Copied: '+p);}
       catch(e){show('Copy failed — path: '+p);}
       document.body.removeChild(ta);
     }
   }
  function apply(){
    var q=(search.value||'').toLowerCase(), shown=0;
    cards.forEach(function(card){
      var hay=card.getAttribute('data-search')||'';
      var genres=card.getAttribute('data-genre')||'';
      var hit=(!q||hay.indexOf(q)!==-1)&&(!state.genre||genres.toLowerCase().indexOf(state.genre.toLowerCase())!==-1)
            &&(!state.noart||card.getAttribute('data-art')==='0')
            &&(!state.unextracted||card.getAttribute('data-unpacked')!=='1')
            &&(!state.hide_extracted||card.getAttribute('data-unpacked')!=='1'||card.getAttribute('data-stale')==='1');
      if(state.year){
        var date=card.getAttribute('data-date')||'';
        hit=hit&&(date.indexOf(state.year)!==-1);
      }
      if(state.days){
        var created=card.getAttribute('data-days')||'';
        hit=hit&&(created!==''&&parseInt(created,10)<=parseInt(state.days,10));
      }
      card.classList.toggle('is-hidden',!hit); if(hit)shown++;
    });
    empty.hidden=shown!==0;
    document.querySelectorAll('section.category').forEach(function(sec){
      var any=Array.prototype.some.call(sec.querySelectorAll('.card'),function(c){return !c.classList.contains('is-hidden');});
      sec.classList.toggle('is-empty',!any);
      // The rail counts what the section is showing right now, not what it held before a filter. Left as it
      // was, a search matching twelve games still reported 166 beside every category, which is not a count of
      // anything the reader can see on the page. A category with nothing left in it greys out rather than
      // vanishing: the shape of the library stays visible while a filter is on.
      var left=sec.querySelectorAll('.card:not(.is-hidden)').length, slot=document.querySelector('[data-toc-count="'+sec.id+'"]');
      if(slot) slot.textContent=left;
      var link=document.querySelector('.toc-link[data-target="'+sec.id+'"]');
      if(link) link.classList.toggle('is-muted',!left);
    });
    // How many matched, which the page did not say anywhere before. Typing into a 166-card shelf with no
    // feedback means not knowing whether a search found nothing, found one game, or quietly failed to run.
    var filtering=!!q||!!state.genre||state.noart||!!state.year||state.unextracted||state.hide_extracted||!!state.days;
    tally.textContent=filtering?shown+' of '+cards.length:cards.length+' games';
    tally.classList.toggle('is-filtering',filtering);
  }
  // The two path boxes: where the games are, and where unpacked files should land. The first exists because
  // this page is written into the library root by whichever machine ran the scan and is read on whichever
  // machine opens it - a colleague's, a laptop, or the same box after the Games folder has been moved. Artwork and
  // the category links are relative to the page and survive a move on their own; a copied folder path and an
  // Extract source do not, so both are rebuilt from this box instead of being baked in.
  var rootBox=document.getElementById('game-folder'), destBox=document.getElementById('extract-dest');
  // Captured before the remembered destination is restored further down. The "Unpacked" and "Needs install"
  // badges were decided when this page was written, against the folder the box starts out holding, so that folder
  // is the only one they can be said to describe - and it is what they are compared against.
  var defaultDest=(destBox.value||'').trim().replace(/[\\/]+$/,'');
  function syncUnpackedBadges(){
    // Retracts the badges the moment the reader points the page somewhere else. The check behind them was made
    // against one folder, on one machine, at one moment, and a page opened from file:// cannot look at any
    // other - so the honest response to a claim about a folder the reader has just changed is to take it back.
    var elsewhere=((destBox.value||'').trim().replace(/[\\/]+$/,'')!==defaultDest);
    Array.prototype.forEach.call(document.querySelectorAll('.card[data-unpacked]'),function(card){
      // Both the "Unpacked" and the "Needs install" badge ride on data-result; retract whichever one a card has,
      // because both were decided against a single folder the reader may just have changed.
      var badge=card.querySelector('[data-result]');
      if(badge) badge.hidden=elsewhere;
    });
  }
  destBox.addEventListener('input',syncUnpackedBadges);
  destBox.addEventListener('change',syncUnpackedBadges);
    // What the last batch run actually did, read from the file the app rewrites when a run finishes. Single
    // extract results are NOT written here — they are handled by the desktop progress dialog + result window,
    // so the banner only ever reflects a batch run.
    (function(){
      var run=window.libraryBatchStatus, banner=document.getElementById('run-status');
      if(!run||!run.ran_at||!banner) return;
      var parts=[];
    if(run.total) parts.push(run.extracted+' of '+run.total+' extracted');
    if(run.skipped) parts.push(run.skipped+' already unpacked');
    if(run.needs_install) parts.push(run.needs_install+' need install');
    if(run.failed) parts.push(run.failed+' failed');
    if(run.cancelled) parts.push(run.cancelled+' not started');
    // A run that was cancelled, or that failed something, is styled as a warning. A green banner over three
    // failures is the one thing worse than no banner, because it reads as the whole run having worked.
    banner.className='run-status'+((run.failed||run.cancelled)?' run-status-warn':'');
    banner.textContent='Last run '+run.ran_at+(run.category?' - '+run.category:'')+': '+
                      (parts.length?parts.join(', '):'nothing to do')+
                      (run.elapsed?' in '+run.elapsed:'')+
                      (run.destination?' - into '+run.destination:'');
       banner.hidden=false;
     })();
     // The same status, summarized as a one-line chip in the rail so the run result is visible even when the
     // banner has scrolled out of view. Shows just the date and the outcome, not the full detail.
     (function(){
       var run=window.libraryBatchStatus, railChip=document.getElementById('batch-status');
       if(!run||!run.ran_at||!railChip) return;
       var summary=[];
       if(run.total) summary.push(run.extracted+'/'+run.total);
       if(run.failed) summary.push(run.failed+' failed');
       if(run.cancelled) summary.push('cancelled');
       railChip.textContent=run.ran_at+' - '+(summary.length?summary.join(' '):'ok');
       railChip.className='batch-status'+(run.failed||run.cancelled?' batch-status-warn':'');
       railChip.hidden=false;
     })();
  function escapeHtml(value){
    return String(value||'').replace(/[&<>"]/g,function(ch){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch];
    });
  }
  function typedRoot(){
    // A path pasted out of a file manager arrives wrapped in quotes, and a trailing separator would double up
    // with the one joining the rest of the path onto it.
    return (rootBox.value||'').trim().replace(/^["']|["']$/g,'').replace(/[\\/]+$/,'');
  }
  function joinPath(root,relative){
    relative=(relative||'').replace(/^[\\/]+/,'');
    return relative?root+'/'+relative:root;
  }
  // encodeURI leaves & ? # = and + alone, and inside a query string any of those splits one path into two
  // parameters, so they are escaped after it. The '%' it adds for a literal per cent is already escaped, and
  // ':' and '/' stay because a Windows drive letter and the path separators have to survive intact.
  function encodePath(value){
    return encodeURI(value).replace(/[&?#=+]/g,function(ch){return '%'+ch.charCodeAt(0).toString(16).toUpperCase();});
  }
  function archiveSrc(button){
    var archive=button.getAttribute('data-archive')||'';
    if(!archive) return '';
    var rel=button.getAttribute('data-rel')||'';
    var joined=joinPath(root,rel);
    return encodePath(joinPath(joined,archive));
  }
  function applyLinks(){
    var dest=(destBox.value||'').trim(); root=typedRoot();
    var buttons=document.querySelectorAll('.btn-extract');
    for(var i=0;i<buttons.length;i++){
      // Always rebuilt from the pristine data-extract, so typing in either box cannot accumulate parameters,
      // and the source follows the typed game folder rather than the machine that wrote this page. An empty
      // box falls back to the source that was written, so clearing it never makes the links unusable.
      var base=buttons[i].getAttribute('data-extract'), src=root?archiveSrc(buttons[i]):'';
      var link=src?base.split('?')[0]+'?src='+src:base;
      buttons[i].setAttribute('href',dest?link+'&dest='+encodeURIComponent(dest):link);
    }
    function markerPathFor(el){
      var m=(el.getAttribute('data-marker-dir')||'').replace(/^["']|["']$/g,'').trim();
      if(m) return m;
      return ((el.getAttribute('data-extracted-path')||'').replace(/^["']|["']$/g,'').trim()) || '';
    }
    // Open-extracted links: open the extracted/installer folder via protocol handler.
    // Prefer an absolute path recorded at generation from the marker's extracted_root (works across
    // configured extract roots/layout changes); fall back to typed destination + relative layout.
    var openExtracted=document.querySelectorAll('[data-open-extracted]');
    for(var j=0;j<openExtracted.length;j++){
      var oe=openExtracted[j];
      var abs=(oe.getAttribute('data-extracted-path')||'').replace(/^["']|["']$/g,'').trim();
      var rel=(oe.getAttribute('data-extracted-rel')||'').replace(/^[\\/]+/,'');
      var full='';
      if(abs){ full=abs; }
      else if(rel && dest){ full=joinPath(dest.replace(/[\\/]+$/,''), rel); }
      if(full){
        oe.setAttribute('href','steamgameorganizer://open-extracted?path='+encodePath(full));
      } else {
        oe.setAttribute('href','#');
      }
    }
    var plays=document.querySelectorAll('[data-play]');
    for(var p=0;p<plays.length;p++){
      var pl=plays[p], mp=markerPathFor(pl), lt=(pl.getAttribute('data-launch-target')||'').replace(/^["']|["']$/g,'').trim();
      if(lt){ pl.setAttribute('href','steamgameorganizer://play?exe='+encodePath(lt)+(mp?'&path='+encodePath(mp):'')); }
      else if(mp){ pl.setAttribute('href','steamgameorganizer://play?path='+encodePath(mp)); }
      else { pl.setAttribute('href','#'); }
    }
    var picks=document.querySelectorAll('[data-pick-launcher]');
    for(var pk=0;pk<picks.length;pk++){
      var el=picks[pk], mpk=markerPathFor(el);
      el.setAttribute('href', mpk?'steamgameorganizer://pick-launcher?path='+encodePath(mpk):'#');
    }
    var marks=document.querySelectorAll('[data-mark-installed]');
    for(var mi=0;mi<marks.length;mi++){
      var em=marks[mi], mpm=markerPathFor(em);
      em.setAttribute('href', mpm?'steamgameorganizer://mark-installed?path='+encodePath(mpm):'#');
    }
    // Open-folder links rebuild their path from the typed game folder root, same as Extract.
    var folderButtons=document.querySelectorAll('.btn-folder');
    for(var i=0;i<folderButtons.length;i++){
      var fb=folderButtons[i];
      var fpath=root?joinPath(root,fb.getAttribute('data-rel')||''):'';
      if(fpath){fb.setAttribute('href','steamgameorganizer://open-folder?path='+encodePath(fpath));}
    }
    // Copy-path buttons carry the full archive path so a reader can paste it anywhere.
    // file:// pages cannot use the async clipboard API, so execCommand is the fallback.
    var copyButtons=document.querySelectorAll('.btn-copy');
    for(var i=0;i<copyButtons.length;i++){
      var cb=copyButtons[i];
      cb.setAttribute('data-copy',root?archiveSrc(cb):'');
    }
    document.querySelectorAll('.btn-copy').forEach(function(btn){
      btn.addEventListener('click',function(event){
        event.preventDefault();
        var path=(btn.getAttribute('data-copy')||'');
        if(!path) return;
        var ta=document.createElement('textarea');
        ta.value=path;
        ta.setAttribute('readonly','');
        ta.style.position='fixed';
        ta.style.opacity='0';
        document.body.appendChild(ta);
        ta.select();
        try{document.execCommand('copy');show('Copied: '+path);}
        catch(e){show('Copy failed — path: '+path);}
        document.body.removeChild(ta);
      });
    });
    // The setup button carries both boxes with it, so the wizard it opens starts on the
    // folders this reader has already typed rather than the ones the page was written
    // with - the same values the Extract links above were just rebuilt from. An empty
    // box sends no parameter, and the wizard falls back to the app's own setting.
    var setupLink=document.getElementById('setup-link');
    var setupFallback=document.getElementById('setup-fallback');
    if(setupLink){
      var sbase=setupLink.getAttribute('data-setup'), params=[];
      if(root)params.push('library='+encodePath(root));
      if(dest)params.push('extract='+encodePath(dest));
      setupLink.setAttribute('href',params.length?sbase+'?'+params.join('&'):sbase);
      // A browser that has never seen the scheme shows a prompt and then opens the
      // app; one that has dismissed the prompt once opens nothing at all. Either way
      // the reader is left staring at a page that did not change, and the footer's
      // sentence is the only help. Showing the command-line fallback next to the
      // button the moment it is clicked turns that into an answer in place.
      setupLink.addEventListener('click',function(){
        if(!setupFallback) return;
        setupFallback.hidden=true;
        setTimeout(function(){ if(setupFallback) setupFallback.hidden=false; }, 2500);
      });
    }
    // The batch links carry the same destination, rebuilt the same way from the same box - always from the
    // pristine data-batch, so typing in the box cannot accumulate a second dest parameter onto a link that
    // already has one. The library-wide link has no query string at all, so the separator has to be chosen
    // rather than assumed: & when it is already present, bbase + ? when it is not.
    var batch=document.querySelectorAll('[data-batch]');
    for(var j=0;j<batch.length;j++){
      var bbase=batch[j].getAttribute('data-batch');
      var hasQuery=bbase.indexOf('?')>=0;
      var blink=dest?(hasQuery?bbase+'&':bbase+'?')+'dest='+encodeURIComponent(dest):bbase;
      batch[j].setAttribute('href',blink);
    }
  }
  // A batch is hours of disk writes, so it is confirmed on the evidence rather than on the button's label: how
  // many games, how much archive, and where it is about to land. Without this, "Extract all" on a 176-game
  // library is one click from filling a drive.
  function confirmBatch(link){
    var name=link.getAttribute('data-batch-name')||'these games';
    var count=link.getAttribute('data-batch-count')||'?';
    var what=link.getAttribute('data-batch-confirm')||'Unpack';
    var dest=(destBox.value||'').trim()||'the first configured extract folder';
    return confirm(what+'\n\n'+count+' from '+name+'\nTo: '+dest+
                   '\n\nThis can run for hours and needs several times the archive size in free space.'+
                   '\nGames already unpacked there are skipped.');
  }
  function remember(box,key){
    var value=box.value.trim();
    if(value) store(key,value);
    return value;
  }
  function commit(box,key,label){
    var value=remember(box,key);
    applyLinks();
    show(label+': '+(value||'not set'));
  }
  // On regeneration the app embeds current defaults - prefer them so paths stay in sync (stale localStorage must not override).
  var savedRoot=store('catalog-root'), savedDest=store('catalog-dest');
  var defRoot=rootBox.getAttribute('value')||rootBox.defaultValue||'';
  var defDest=destBox.getAttribute('value')||destBox.defaultValue||'';
  if(defRoot){ rootBox.value=defRoot; store('catalog-root',defRoot); }
  else if(savedRoot) rootBox.value=savedRoot;
  if(defDest){ destBox.value=defDest; store('catalog-dest',defDest); }
  else if(savedDest) destBox.value=savedDest;
  rootBox.addEventListener('input',function(){remember(rootBox,'catalog-root');applyLinks();});
  rootBox.addEventListener('change',function(){remember(rootBox,'catalog-root');applyLinks();});
  rootBox.addEventListener('keydown',function(event){if(event.key==='Enter'){event.preventDefault();commit(rootBox,'catalog-root','Game folder');}});
  destBox.addEventListener('input',function(){remember(destBox,'catalog-dest');applyLinks();});
  destBox.addEventListener('change',function(){remember(destBox,'catalog-dest');applyLinks();});
  destBox.addEventListener('keydown',function(event){if(event.key==='Enter'){event.preventDefault();commit(destBox,'catalog-dest','Extract to');}});
  // Restoring the remembered values above is not enough on its own: the links have to be rebuilt from them
  // once, or a page reopened with a destination remembered would quietly extract to the first configured
  // folder until the reader happened to type something. The same goes for the "Unpacked" badges, which were
  // decided against the folder the box starts out holding: a page reopened with a different destination
  // remembered has to drop them on load rather than wait for the reader to touch the box.
  applyLinks();
  syncUnpackedBadges();
  // Every batch link is confirmed before the browser hands it to the desktop. preventDefault() does the work:
  // without it the navigation starts the run immediately and the prompt would appear over a window that is
  // already unpacking. The single Extract links are deliberately not confirmed - one archive is a small,
  // reversible thing, and a prompt on every card would make the button tiresome.
  var batchLinks=Array.prototype.slice.call(document.querySelectorAll('[data-batch]'));
  batchLinks.forEach(function(link){
    link.addEventListener('click',function(event){
      if(!confirmBatch(link)){event.preventDefault();return;}
    });
  });
  // Refresh re-generates this page through the app so its Unpacked badges are
  // re-checked against what is actually on disk now. A file:// page cannot do
  // that itself - it would need the app to walk the folder and rewrite the page.
  var refreshBtn=document.getElementById('refresh-catalog');
  if(refreshBtn){
    refreshBtn.addEventListener('click',function(){
      window.location.href=refreshBtn.getAttribute('data-refresh');
    });
  }
  // Sorting reorders cards inside each category's own grid, so a section never bleeds into another one.
  // Newest and Largest are descending, which the plain string compare below is not: it would put the oldest
  // game and the smallest archive first, under labels claiming the opposite.
  var grids=Array.prototype.slice.call(document.querySelectorAll('.grid'));
  function sortBy(key,descending){
    grids.forEach(function(grid){
      var kids=Array.prototype.slice.call(grid.children);
      kids.sort(function(a,b){
        var x=a.getAttribute('data-'+key)||'', y=b.getAttribute('data-'+key)||'';
        if(key==='size'){
          var diff=(parseInt(y,10)||0)-(parseInt(x,10)||0);
          if(diff) return descending?diff:-diff;
        }else if(x!==y){
          return x<y?(descending?1:-1):(descending?-1:1);
        }
        // Every game with no release date shares a key, and so do every 4.2 GB archive. Falling back to the
        // name keeps the order from reshuffling arbitrarily when the reader switches between two sorts that
        // tie, which reads as the page rearranging itself at random.
        var an=a.getAttribute('data-name')||'', bn=b.getAttribute('data-name')||'';
        return an<bn?-1:an>bn?1:0;
      }).forEach(function(card){grid.appendChild(card);});
    });
  }
  document.querySelectorAll('.sort').forEach(function(btn){
    btn.addEventListener('click',function(){
      document.querySelectorAll('.sort').forEach(function(b){b.classList.remove('is-active');});
      btn.classList.add('is-active');
      sortBy(btn.getAttribute('data-sort')||'name',btn.getAttribute('data-desc')==='1');
    });
  });
  // Genre chips narrow the shelf without typing. One chip at a time: the counts in the rail are worth more
  // than being able to intersect them, and an intersectable filter on 166 cards is still 166 cards. Selecting
  // one no longer clears the search box - it used to, which meant narrowing a search you had already typed
  // silently threw that search away. The two narrow together, which is what clicking a chip after typing
  // reads as meaning.
  document.querySelectorAll('.chip-btn').forEach(function(chip){
    chip.addEventListener('click',function(){
      var genre=chip.getAttribute('data-genre')||'';
      var year=chip.getAttribute('data-year')||'';
      var days=chip.getAttribute('data-days')||'';
      var already=chip.classList.contains('is-active');
      if(genre){
        document.querySelectorAll('.chip-btn').forEach(function(c){c.classList.remove('is-active');c.setAttribute('aria-pressed','false');});
        state.genre=already?'':genre;
        chip.classList.toggle('is-active',!already);
        chip.setAttribute('aria-pressed',already?'false':'true');
      }else if(year){
        chip.classList.toggle('is-active',!already);
        chip.setAttribute('aria-pressed',already?'false':'true');
        state.year=chip.classList.contains('is-active')?year:'';
      }else if(days){
        chip.classList.toggle('is-active',!already);
        chip.setAttribute('aria-pressed',already?'false':'true');
        state.days=chip.classList.contains('is-active')?days:'';
      }
      apply();
    });
  });
  // The hero's "Missing art" figure doubles as a filter over the cards that have none. It was a number the
  // reader could not act on, on the shelf where a third of the cards are placeholders - which is precisely
  // where you want to see only those and go and fetch the banners.
   document.querySelectorAll('.stat-filter').forEach(function(tile){
     tile.addEventListener('click',function(){
       var filter=tile.getAttribute('data-filter');
       if(filter==='noart'){
         state.noart=!state.noart;
         tile.classList.toggle('is-active',state.noart);
         tile.setAttribute('aria-pressed',state.noart?'true':'false');
        }else if(filter==='unextracted'){
          state.unextracted=!state.unextracted;
          tile.classList.toggle('is-active',state.unextracted);
          tile.setAttribute('aria-pressed',state.unextracted?'true':'false');
        }else if(filter==='hide_extracted'){
          state.hide_extracted=!state.hide_extracted;
          tile.classList.toggle('is-active',state.hide_extracted);
          tile.setAttribute('aria-pressed',state.hide_extracted?'true':'false');
        }
       apply();
     });
   });
  // A category can be a long way down the page, so every banner carries its own way back to the top, plus a
  // floating one that appears once scrolling starts.
  function toTop(){window.scrollTo({top:0,behavior:'smooth'});}
  document.querySelectorAll('.jump-top').forEach(function(btn){btn.addEventListener('click',toTop);});
  var toTopBtn=document.getElementById('to-top');
  toTopBtn.addEventListener('click',toTop);
  // Entrance animation: cards fade in and rise as they scroll into view. IntersectionObserver is cheaper
  // than a scroll listener because it never fires for elements outside the viewport, and the threshold of
  // 0.05 means the animation starts the moment a card is within a pixel of being visible.
  // Staggered delays create a cascading reveal: each card animates 40ms after the previous one,
  // so a grid of cards flows in one after another instead of all at once.
  var observer=new IntersectionObserver(function(entries){
    entries.forEach(function(entry){
      if(entry.isIntersecting){
        var card=entry.target;
        var delay=parseInt(card.getAttribute('data-delay')||'0',10);
        setTimeout(function(){card.classList.add('in-view');},delay);
      }
    });
  },{threshold:0.05});
  var cardEl=document.querySelectorAll('.card');
  cardEl.forEach(function(card,i){
     card.setAttribute('data-delay',String(i*20));
    observer.observe(card);
  });
  // Category headers also fade in as they scroll into view, with a slightly longer
  // stagger so the header clears before the grid beneath it animates.
  var catObserver=new IntersectionObserver(function(entries){
    entries.forEach(function(entry){
      if(entry.isIntersecting)entry.target.classList.add('in-view');
    });
  },{threshold:0.1});
  document.querySelectorAll('section.category').forEach(function(sec){catObserver.observe(sec);});
  // Reading position, as a hairline under the toolbar, and the category you are actually in. Both are cheap
  // and both are what a long page is missing when it has no chrome to orient by.
  var bar=document.getElementById('progress-bar'), links=Array.prototype.slice.call(document.querySelectorAll('.toc-link'));
  var sections=Array.prototype.slice.call(document.querySelectorAll('section.category'));
  var hero=document.querySelector('header.hero');
  var ticking=false;
  // Two thresholds, not one. Collapsing the hero shortens the document, which can shorten the scroll offset,
  // which would expand it again - and a hero that flickers between 413px and 90px on a slow trackpad is worse
  // than one that never collapses at all. The gap between the two is what makes the state stable: once
  // collapsed, the reader has to come most of the way back up before it returns.
  var HERO_COLLAPSE=140, HERO_EXPAND=60;
  function onScroll(){
    if(ticking)return; ticking=true;
    window.requestAnimationFrame(function(){
      var height=Math.max(1,doc.scrollHeight-window.innerHeight);
      bar.style.width=Math.min(100,(window.scrollY/height)*100)+'%';
      toTopBtn.classList.toggle('show',window.scrollY>520);
      var compact=hero.classList.contains('is-compact');
      if(compact&&window.scrollY<HERO_EXPAND) hero.classList.remove('is-compact');
      else if(!compact&&window.scrollY>HERO_COLLAPSE) hero.classList.add('is-compact');
      var line=window.scrollY+window.innerHeight*0.3, active=null;
      sections.forEach(function(sec){if(sec.offsetTop<=line)active=sec;});
      links.forEach(function(link){
        var on=active&&link.getAttribute('data-target')===active.id;
        link.classList.toggle('is-current',!!on);
        if(on)link.setAttribute('aria-current','true');else link.removeAttribute('aria-current');
      });
      if(active){var stuck=active.querySelector('.category-stuck');if(stuck)stuck.style.opacity=window.scrollY+window.innerHeight*0.3>active.offsetTop+120?'1':'0';}
      ticking=false;
    });
  }
  window.addEventListener('scroll',onScroll,{passive:true});
  window.addEventListener('resize',onScroll);
  onScroll();
  // Light and dark both have to look deliberate, because this file is opened on whatever the machine is set
  // to. Dark is the default rather than the OS preference: the generated banner art and card scrims are tuned
  // for it, so on a light-mode desktop the page came up in the palette it was least designed for. The stored
  // choice still wins, so anyone who flips it keeps it.
  var theme=document.getElementById('theme');
  function setTheme(name){
    try{doc.setAttribute('data-theme',name);}catch(e){}
    try{document.body.setAttribute('data-theme',name);}catch(e){}
    try{store('catalog-theme',name);}catch(e){}
    try{theme.setAttribute('aria-pressed',name==='light'?'true':'false');}catch(e){}
  }
  var saved=store('catalog-theme');
  setTheme(saved||'dark');
  theme.addEventListener('click',function(){setTheme(doc.getAttribute('data-theme')==='light'?'dark':'light');});
  // Keyboard: "/" is where a reader's hands already are, and Escape is the universal undo for a filter. Both
  // path boxes are text boxes the reader may well be typing a path into, and "/" is the separator on any
  // machine this app is not the only thing that might have typed - so neither shortcut may fire while the
  // caret is in one of them.
  function typing(){
    var el=document.activeElement;
    return !!el&&(el.tagName==='INPUT'||el.tagName==='TEXTAREA');
  }
document.addEventListener('keydown',function(event){
     if(event.key==='/'&&!typing()){event.preventDefault();search.focus();search.select();}
     else if(event.key==='?'&&!typing()){event.preventDefault();showShortcuts();}
     else if(event.key==='Escape'){
       if(document.activeElement===search){search.value='';}
       if(document.body.classList.contains('multi-mode')){
         document.body.classList.remove('multi-mode');
         multiBtn.hidden=false;
         extractSelected.hidden=true;
         clearSelection.hidden=true;
         document.querySelectorAll('.card').forEach(function(card){card.classList.remove('multi-ready','multi-selected');});
         document.querySelectorAll('.card-check').forEach(function(cb){cb.checked=false;});
         state.multi=[];
         updateMultiCount();
       }
       state.genre='';state.noart=false;state.year='';state.unextracted=false;state.hide_extracted=false;
       document.querySelectorAll('.chip-btn.is-active').forEach(function(c){c.classList.remove('is-active');c.setAttribute('aria-pressed','false');});
       document.querySelectorAll('.stat-filter.is-active').forEach(function(t){t.classList.remove('is-active');t.setAttribute('aria-pressed','false');});
       apply();
       hideShortcuts();
     }
     else if(event.key==='Home'&&document.activeElement===document.body){toTop();}
   });
search.addEventListener('input',apply);
   // Card size preset - small / medium / large. Saves the choice so it survives a reload.
   var sizeBtns=document.querySelectorAll('.size-btn');
   function setCardSize(size,save){document.body.className=document.body.className.replace(/card-size-\S+/g,'');document.body.classList.add('card-size-'+size);sizeBtns.forEach(function(b){b.classList.toggle('is-active',b.getAttribute('data-size')===size);});if(save!==false){try{store('card-size',size);}catch(e){}}}
   var savedSize=store('card-size');
   if(savedSize!=='medium'&&savedSize!=='large') savedSize='medium';
   setCardSize(savedSize||'medium',false);
   sizeBtns.forEach(function(btn){btn.addEventListener('click',function(){setCardSize(btn.getAttribute('data-size'),true);});});
   // Multi-select mode: enter it to reveal checkboxes on every card, then collect the
   // chosen archives into a single extract-multi:// URI so the app unpacks them as one batch.
   var multiBtn=document.getElementById('multi-btn');
   var extractSelected=document.getElementById('extract-selected');
   var clearSelection=document.getElementById('clear-selection');
   var multiCount=document.getElementById('multi-count');
   state.multi=state.multi||[];
  multiBtn.addEventListener('click',function(){
    if(document.body.classList.contains('multi-mode')){
      document.body.classList.remove('multi-mode');
      multiBtn.hidden=false;
      extractSelected.hidden=true;
      clearSelection.hidden=true;
      document.querySelectorAll('.card').forEach(function(card){card.classList.remove('multi-ready','multi-selected');});
      document.querySelectorAll('.card-check').forEach(function(cb){cb.checked=false;});
      state.multi=[];
      updateMultiCount();
    }else{
      document.body.classList.add('multi-mode');
      multiBtn.hidden=true;
      extractSelected.hidden=false;
      clearSelection.hidden=false;
      document.querySelectorAll('.card-check').forEach(function(cb){cb.closest('.card').classList.add('multi-ready');});
    }
  });
  clearSelection.addEventListener('click',function(){
    state.multi=[];
    updateMultiCount();
document.querySelectorAll('.card-check').forEach(function(cb){cb.checked=false;});
     document.querySelectorAll('.card').forEach(function(card){card.classList.remove('multi-selected');});
   });
extractSelected.addEventListener('click',function(){
      var selected=[];
      document.querySelectorAll('.card-check:checked').forEach(function(cb){selected.push(cb.getAttribute('data-archive-path'));});
      if(selected.length<2){alert('Select at least two games to extract them together.');return;}
      var params=selected.map(function(f){return 'src='+encodeURIComponent(f);}).join('&');
      window.location.href='steamgameorganizer://extract-multi?'+params;
    });
    function updateMultiCount(){
      var count=document.querySelectorAll('.card-check:checked').length;
      multiCount.textContent=String(count);
      extractSelected.hidden=!count;
    }
    document.addEventListener('change',function(event){
      if(event.target.classList.contains('card-check')){
        var card=event.target.closest('.card');
        if(event.target.checked){state.multi.push(event.target.getAttribute('data-archive-path'));card.classList.add('multi-selected');}
        else{state.multi=state.multi.filter(function(f){return f!==event.target.getAttribute('data-archive-path');});card.classList.remove('multi-selected');}
        updateMultiCount();
      }
    });
   // --- New: Protocol handler detection & status polling ---
   function checkHandler(){
     if(handlerChecked) return;
     handlerChecked=true;
     // Try to navigate to the scheme. If it fails, the browser may show a prompt or do nothing.
     // We can't reliably detect success synchronously, so we use a timeout heuristic.
     var testLink=document.createElement('a');
     testLink.href='steamgameorganizer://ping';
     testLink.style.display='none';
     document.body.appendChild(testLink);
     testLink.click();
     document.body.removeChild(testLink);
     // After a short delay, if the page is still here and no navigation occurred,
     // assume the handler is not registered. This is best-effort.
     setTimeout(function(){
       handlerWorks=false;
       showHandlerBanner();
     }, 800);
     // If the handler IS registered, the app will launch and we'll likely navigate away.
     // If we're still here after 2s, it probably didn't work.
     setTimeout(function(){
       if(handlerWorks===null){
         handlerWorks=false;
         showHandlerBanner();
       }
     }, 2000);
   }
   function showHandlerBanner(){
     if(document.getElementById('handler-banner')) return;
     var banner=document.createElement('div');
     banner.id='handler-banner';
     banner.style.cssText='position:fixed;top:0;left:0;right:0;background:var(--warn);color:var(--bg);padding:12px 20px;text-align:center;z-index:80;font-size:.85rem;box-shadow:var(--shadow);';
     banner.innerHTML='<strong>Protocol handler not registered.</strong> Extract/Open/Play buttons need the <code>steamgameorganizer://</code> scheme. '
       + '<button id="handler-setup-btn" style="margin-left:12px;padding:4px 12px;background:var(--bg);color:var(--warn);border:none;border-radius:4px;cursor:pointer;">Set up on this PC</button>'
       + '<button id="handler-dismiss" style="margin-left:8px;background:none;border:none;color:var(--bg);cursor:pointer;font-size:1.2rem;line-height:1;">&times;</button>';
     document.body.insertBefore(banner, document.body.firstChild);
     document.getElementById('handler-setup-btn').addEventListener('click',function(){
       var setupLink=document.getElementById('setup-link');
       if(setupLink) setupLink.click();
     });
     document.getElementById('handler-dismiss').addEventListener('click',function(){
       banner.remove();
     });
   }
   // Check handler on first Extract/Open/Play button click
   document.addEventListener('click',function(e){
     var target=e.target.closest('[href^="steamgameorganizer://"]');
     if(target && !handlerChecked){
       checkHandler();
     }
   });
   // Status polling during batch runs: re-fetch Game Library.status.js every 5s while a run is active.
   var statusPollTimer=null;
   function startStatusPoll(){
     if(statusPollTimer) return;
     statusPollTimer=setInterval(function(){
       var script=document.querySelector('script[src="Game Library.status.js"]');
       if(!script) return;
       var newScript=document.createElement('script');
       newScript.src='Game Library.status.js?' + Date.now();
       newScript.onload=function(){
         // Re-run status display logic
         var run=window.libraryBatchStatus, banner=document.getElementById('run-status'), railChip=document.getElementById('batch-status');
         if(run && run.ran_at){
           var parts=[];
           if(run.total) parts.push(run.extracted+' of '+run.total+' extracted');
           if(run.skipped) parts.push(run.skipped+' already unpacked');
           if(run.needs_install) parts.push(run.needs_install+' need install');
           if(run.failed) parts.push(run.failed+' failed');
           if(run.cancelled) parts.push(run.cancelled+' not started');
           if(banner){
             banner.className='run-status'+((run.failed||run.cancelled)?' run-status-warn':'');
             banner.textContent='Last run '+run.ran_at+(run.category?' - '+run.category:'')+': '+
                               (parts.length?parts.join(', '):'nothing to do')+
                               (run.elapsed?' in '+run.elapsed:'')+
                               (run.destination?' - into '+run.destination:'');
             banner.hidden=false;
           }
           if(railChip){
             var summary=[];
             if(run.total) summary.push(run.extracted+'/'+run.total);
             if(run.failed) summary.push(run.failed+' failed');
             if(run.cancelled) summary.push('cancelled');
             railChip.textContent=run.ran_at+' - '+(summary.length?summary.join(' '):'ok');
             railChip.className='batch-status'+(run.failed||run.cancelled?' batch-status-warn':'');
             railChip.hidden=false;
           }
           // If run is complete (has elapsed and not cancelled), stop polling
           if(run.elapsed && !run.cancelled){
             stopStatusPoll();
           }
         }
       };
       document.head.appendChild(newScript);
       // Clean up old script
       if(script.parentNode) script.parentNode.removeChild(script);
     }, 5000);
   }
   function stopStatusPoll(){
     if(statusPollTimer){
       clearInterval(statusPollTimer);
       statusPollTimer=null;
     }
   }
   // Start polling if a batch run is in progress (no elapsed time yet but has ran_at)
   if(window.libraryBatchStatus && window.libraryBatchStatus.ran_at && !window.libraryBatchStatus.elapsed){
     startStatusPoll();
   }
   // Keyboard shortcuts overlay
   function showShortcuts(){
     if(document.getElementById('shortcuts-overlay')) return;
     var overlay=document.createElement('div');
     overlay.id='shortcuts-overlay';
     overlay.style.cssText='position:fixed;inset:0;background:rgba(8,11,18,.92);z-index:90;display:flex;align-items:center;justify-content:center;';
     overlay.innerHTML='<div style="background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:28px;max-width:520px;width:90%;max-height:85vh;overflow:auto;">'
       + '<h3 style="margin:0 0 16px;">Keyboard Shortcuts</h3>'
       + '<dl style="display:grid;grid-template-columns:140px 1fr;gap:8px 16px;font-size:.85rem;">'
       + '<dt><kbd>/</kbd></dt><dd>Focus search</dd>'
       + '<dt><kbd>?</kbd></dt><dd>Show this help</dd>'
       + '<dt><kbd>Esc</kbd></dt><dd>Clear search / exit multi-select / close this</dd>'
       + '<dt><kbd>Home</kbd></dt><dd>Scroll to top</dd>'
       + '<dt><kbd>Enter</kbd></dt><dd>Save path box (Game folder / Extract to)</dd>'
       + '</dl>'
       + '<p style="margin-top:16px;color:var(--muted);font-size:.75rem;">Click outside or press <kbd>Esc</kbd> to close.</p>'
       + '</div>';
     overlay.addEventListener('click',function(e){if(e.target===overlay) hideShortcuts();});
     document.body.appendChild(overlay);
   }
   function hideShortcuts(){
     var overlay=document.getElementById('shortcuts-overlay');
     if(overlay) overlay.remove();
   }
 })();
 """
        return self._script_cache

    def _css(self):
        if getattr(self, "_css_cache", None) is not None:
            return self._css_cache
        self._css_cache = """
/* One set of custom properties per theme, switched by [data-theme] on <html>. Every colour below is one of
   these variables, so the light theme is a real theme rather than an inverted filter. Contrast against the
   surface each one is used on is at or above 4.5:1 for text and 3:1 for borders and large text. */
:root{color-scheme:dark;
  --bg:#080b12;--bg-2:#0c111b;--panel:#111827;--raised:#172032;--line:#202b3f;--line-soft:#18202f;
  --text:#e9eef7;--muted:#a5b4cb;--dim:#7b8ba4;--accent:#5aa9ff;--accent-ink:#04101f;--accent-2:#8b6cff;
  --good:#54e0a4;--warn:#ffc078;--chip:#172033;--shadow:0 18px 42px rgba(0,0,0,.55);--scrim:rgba(8,11,18,.72);
  /* Base surfaces are spelled out as literal rgba rather than color-mix() on purpose: color-mix() only exists
     in Chromium 111+, and a single dropped background declaration would leave the dark theme on the browser's
     default white page behind near-white text, and background-clip:text on transparent type would make the
     title invisible rather than merely plain. No declaration below depends on it. */
  --glow-1:rgba(90,169,255,.16);--glow-2:rgba(139,108,255,.15);--bar:rgba(8,11,18,.88);
  --wash:rgba(12,17,27,.55);--accent-soft:rgba(90,169,255,.16);--accent-line:rgba(90,169,255,.45);--accent-glow:rgba(90,169,255,.22);
  --title-fade:#a9bdd6;}
:root[data-theme="light"]{
  color-scheme:light;
  --bg:#eef1f7;--bg-2:#f6f8fc;--panel:#ffffff;--raised:#ffffff;--line:#dbe2ee;--line-soft:#e8edf6;
  --text:#10151f;--muted:#4c5a70;--dim:#5f6b80;--accent:#1560d0;--accent-ink:#ffffff;--accent-2:#5a3fd6;
  --good:#0b7a51;--warn:#a85f1f;--chip:#eef1f7;--shadow:0 14px 34px rgba(20,32,56,.14);--scrim:rgba(255,255,255,.78);
  --glow-1:rgba(21,96,208,.12);--glow-2:rgba(90,63,214,.10);--bar:rgba(246,248,252,.88);
  --wash:rgba(246,248,252,.7);--accent-soft:rgba(21,96,208,.12);--accent-line:rgba(21,96,208,.4);--accent-glow:rgba(21,96,208,.2);
  --title-fade:#5c78a8;}
*{box-sizing:border-box;}
html{scroll-behavior:smooth;scroll-padding-top:96px;}
body{margin:0;background:
  radial-gradient(1200px 520px at 12% -10%,var(--glow-1),transparent 70%),
  radial-gradient(1000px 460px at 88% -6%,var(--glow-2),transparent 68%),
  var(--bg);background-attachment:fixed;color:var(--text);font-family:-apple-system,"Segoe UI",Roboto,Inter,Arial,sans-serif;-webkit-font-smoothing:antialiased;line-height:1.5;}
a{color:inherit;text-decoration:none;}
:focus-visible{outline:2px solid var(--accent);outline-offset:3px;border-radius:6px;}
kbd{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.76rem;background:var(--raised);border:1px solid var(--line);border-bottom-width:2px;border-radius:5px;padding:1px 6px;color:var(--muted);}
.progress{position:fixed;top:0;left:0;right:0;height:2px;z-index:60;background:transparent;pointer-events:none;}
#progress-bar{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--accent),var(--accent-2));box-shadow:0 0 12px var(--accent);transition:width .1s linear;}
/* The hero measured 413px on a 1080px screen - 38% of the viewport gone before a single card, for a heading, a
   line of text and five numbers. Padding came down, and the whole block collapses out of the way once the
   reader starts scrolling, which is where the space was actually being wasted: not at rest, but on every screen
   after it. The toolbar below is already sticky, so the hero is not made sticky - it would collide with it at
   top:0, and it has nothing to offer once it has scrolled away. */
header.hero{padding:44px 28px 34px;text-align:center;border-bottom:1px solid var(--line-soft);
  transition:padding .3s cubic-bezier(.4,0,.2,1);}
header.hero.is-compact{padding:9px 28px;}
header.hero.is-compact h1{font-size:clamp(1.25rem,2.3vw,1.6rem);margin-bottom:0;}
header.hero.is-compact .eyebrow,header.hero.is-compact .tagline,header.hero.is-compact .generated{
  opacity:0;height:0;margin:0;overflow:hidden;pointer-events:none;
  transition:opacity .16s ease,height .3s cubic-bezier(.4,0,.2,1),margin .3s cubic-bezier(.4,0,.2,1);}
header.hero.is-compact .stats{margin-bottom:0;gap:10px;}
header.hero.is-compact .stat{padding:6px 16px;min-width:0;}
header.hero.is-compact .stat-value{font-size:1.05rem;}
header.hero.is-compact .stat-label{font-size:.6rem;margin-top:1px;}
header.hero h1{margin:0 0 10px;font-size:clamp(2.1rem,5vw,3.1rem);font-weight:800;letter-spacing:-.03em;
  background:linear-gradient(180deg,var(--text),var(--title-fade));
  -webkit-background-clip:text;background-clip:text;color:transparent;}
.glyph{display:inline-block;transform:translateY(-2px);-webkit-text-fill-color:initial;}
.eyebrow{margin:0 0 12px;color:var(--accent);font-size:.7rem;font-weight:700;letter-spacing:.22em;text-transform:uppercase;}
.tagline{color:var(--muted);margin:6px 0 22px;font-size:.95rem;}
.sep{color:var(--dim);}
.stats{display:flex;gap:14px;justify-content:center;flex-wrap:wrap;margin-bottom:20px;}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:10px 20px;min-width:104px;
  backdrop-filter:blur(8px);transition:border-color .18s ease,transform .18s ease,box-shadow .18s ease;}
.stat:hover{border-color:var(--accent);transform:translateY(-3px);box-shadow:0 12px 28px var(--accent-soft);}
/* The missing-art tile is a button, so it has to be told apart from the four that only report. Same box, same
   hover, and it reads as pressed while its filter is on rather than sitting there looking like a number. */
.stat-filter{cursor:pointer;font:inherit;color:inherit;text-align:center;}
.stat-filter.is-active{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent),0 12px 28px var(--accent-soft);}
.result-count{margin:0;font-size:.72rem;color:var(--muted);white-space:nowrap;align-self:center;min-width:5.5em;}
.result-count.is-filtering{color:var(--accent);font-weight:600;}
.toc-link.is-muted{opacity:.4;}
.toc-link.is-muted:hover{opacity:.75;}
.stat-value{display:block;font-size:1.6rem;font-weight:800;letter-spacing:-.02em;font-variant-numeric:tabular-nums;}
.stat-label{display:block;color:var(--dim);font-size:.68rem;text-transform:uppercase;letter-spacing:.1em;margin-top:3px;}
.stat-good .stat-value{color:var(--good);}
.generated{color:var(--dim);font-size:.76rem;margin:0;letter-spacing:.02em;}
   .bar{position:sticky;top:0;z-index:50;background:var(--bar);backdrop-filter:blur(14px) saturate(1.3);
    border-bottom:1px solid var(--line);padding:12px 24px;box-sizing:initial;}
.bar-inner{display:flex;gap:12px;align-items:center;}
.field{position:relative;flex:0 1 190px;min-width:110px;display:block;}
.field-icon{position:absolute;left:13px;top:50%;transform:translateY(-50%);font-size:.82rem;opacity:.6;pointer-events:none;}
#search{width:100%;padding:11px 14px 11px 34px;border-radius:11px;border:1px solid var(--line);background:var(--panel);color:var(--text);font:inherit;font-size:.92rem;}
#search::placeholder{color:var(--dim);}
#search:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-glow);}
.sorts{display:flex;align-items:center;gap:6px;}
.sorts-label{color:var(--dim);font-size:.7rem;text-transform:uppercase;letter-spacing:.1em;margin-right:2px;}
.dest{display:flex;align-items:center;gap:9px;flex:3 1 520px;min-width:0;}
.root{display:flex;align-items:center;gap:9px;flex:2 1 300px;min-width:0;}
#extract-dest,#game-folder{width:100%;min-width:0;padding:12px 16px;border-radius:12px;border:1px solid var(--line);
  background:var(--panel);color:var(--text);font:inherit;font-size:.95rem;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;}
#extract-dest::placeholder,#game-folder::placeholder{color:var(--dim);font-family:inherit;}
#extract-dest:focus,#game-folder:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-glow);}
.sort{font:inherit;font-size:.78rem;font-weight:600;color:var(--muted);background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:7px 15px;cursor:pointer;transition:background .15s ease,color .15s ease,border-color .15s ease;}
.sort:hover{border-color:var(--accent);color:var(--text);}
.sort.is-active{background:var(--accent);border-color:var(--accent);color:var(--accent-ink);}
.icon-btn{font:inherit;font-size:1rem;line-height:1;width:38px;height:38px;border-radius:11px;color:var(--muted);
  background:var(--panel);border:1px solid var(--line);cursor:pointer;transition:color .15s ease,border-color .15s ease,transform .15s ease;}
.icon-btn:hover{color:var(--accent);border-color:var(--accent);transform:rotate(18deg);}
.empty{color:var(--dim);font-size:.9rem;margin:10px 0 0;}
.shell{display:grid;grid-template-columns:236px minmax(0,1fr);gap:32px;padding:0 24px;}
  .rail{position:sticky;top:88px;align-self:start;max-height:calc(100vh - 108px);overflow:auto;padding:26px 0 20px;
    scrollbar-width:thin;scrollbar-color:var(--accent) transparent;}
  .rail::-webkit-scrollbar{width:8px;}
  .rail::-webkit-scrollbar-track{background:transparent;}
  .rail::-webkit-scrollbar-thumb{background:var(--accent-line);border-radius:4px;transition:opacity .2s;}
  .rail:hover::-webkit-scrollbar-thumb{opacity:.8;}
.rail-title{margin:0 0 10px;color:var(--dim);font-size:.66rem;font-weight:700;letter-spacing:.16em;text-transform:uppercase;}
nav.toc ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:2px;}
.toc-link{display:flex;align-items:center;gap:9px;padding:7px 11px;border-radius:9px;border:1px solid transparent;
  font-size:.88rem;color:var(--muted);transition:background .15s ease,color .15s ease,border-color .15s ease;}
.toc-link:hover{background:var(--panel);color:var(--text);border-color:var(--line);}
.toc-link.is-current{background:var(--accent-soft);border-color:var(--accent-line);color:var(--text);}
.toc-dot{width:6px;height:6px;border-radius:50%;background:var(--dim);flex:none;transition:background .15s ease,box-shadow .15s ease;}
.toc-link.is-current .toc-dot{background:var(--accent);box-shadow:0 0 0 3px var(--accent-glow);}
.toc-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
nav.toc .count{color:var(--good);font-weight:700;font-size:.78rem;font-variant-numeric:tabular-nums;}
 .genres,.tags-nav{margin-top:26px;}
 nav.years{margin-top:26px;}
 .chip-row{display:flex;flex-wrap:wrap;gap:6px;}
.chip-btn{font:inherit;font-size:.74rem;color:var(--muted);background:var(--chip);border:1px solid var(--line);
  border-radius:999px;padding:5px 11px;cursor:pointer;display:inline-flex;gap:6px;align-items:center;
  transition:background .15s ease,color .15s ease,border-color .15s ease;}
.chip-btn:hover{border-color:var(--accent);color:var(--text);}
.chip-btn.is-active{background:var(--accent);border-color:var(--accent);color:var(--accent-ink);}
/* The tag rail is tinted like the tag chips on the card, so a filter and the thing it filters are recognisably
   the same kind of thing. It shares the one `.chip-btn` behaviour and the one facet attribute with the genre
   rail rather than being a second filter with its own rules. */
.chip-btn-tag{background:rgba(139,108,255,.12);border-color:rgba(139,108,255,.34);color:#b9a6ff;}
.chip-btn-tag:hover{border-color:var(--accent-2);color:var(--text);}
.chip-btn-tag.is-active{background:var(--accent-2);border-color:var(--accent-2);color:#fff;}
:root[data-theme="light"] .chip-btn-tag{background:rgba(139,108,255,.1);color:#5a3fd6;}
.chip-count{opacity:.65;font-variant-numeric:tabular-nums;}
/* One line until asked for, rather than 144px of always-visible prose. */
.rail-help{margin:26px 0 0;padding-top:18px;border-top:1px solid var(--line-soft);}
.rail-help summary{cursor:pointer;color:var(--dim);font-size:.72rem;list-style:revert;}
.rail-help summary:hover{color:var(--muted);}
.rail-help ul{margin:12px 0 0;padding-left:17px;color:var(--dim);font-size:.72rem;line-height:1.55;}
.rail-help li{margin-bottom:7px;}
.rail-help li:last-child{margin-bottom:0;}
main{padding:26px 0 72px;min-width:0;}
   section.category{margin:0 0 46px;transition:opacity .5s ease,transform .5s ease;}
   section.category.is-empty{display:none;}
   section.category.in-view{opacity:1;transform:translateY(0);}
   .category-stuck{position:sticky;top:88px;z-index:40;background:var(--bg);backdrop-filter:blur(8px);border-bottom:1px solid var(--line);padding:8px 0 6px;margin:-26px 0 18px;}
  .category-stuck .category-stuck-name{font-size:clamp(0.9rem,1.6vw,1.1rem);font-weight:700;color:var(--text);letter-spacing:-.01em;}
  .category-stuck .category-header h2{font-size:clamp(1rem,1.8vw,1.2rem);}
.category-header{border-radius:18px;padding:30px 28px;background-size:cover;background-position:center;background-color:var(--panel);
  display:flex;justify-content:space-between;align-items:flex-end;gap:16px;border:1px solid var(--line);min-height:136px;
  /* The generated banner is the base layer and is always present; when a game in the category has
     artwork its banner is painted over it at full opacity, so real art takes up as much of the banner
     as it can without making the banner taller. A dark gradient at the bottom keeps the title readable. */
  background-image:linear-gradient(180deg,rgba(8,11,18,.28),rgba(8,11,18,.72)),var(--real,none),var(--gen);
  background-blend-mode:normal,normal,normal;}
.category-titles{min-width:0;flex:1;}
.category-header h2{margin:0 0 8px;font-size:clamp(1.75rem,4vw,2.6rem);letter-spacing:-.02em;text-shadow:0 2px 14px rgba(0,0,0,.8);}
.category-facts{color:#e7eefa;font-size:.95rem;background:rgba(6,10,18,.55);border:1px solid rgba(255,255,255,.16);padding:5px 14px;border-radius:999px;display:inline-block;backdrop-filter:blur(6px);font-weight:600;}
.dot{opacity:.5;}
.category-actions{display:flex;gap:8px;align-items:center;flex-shrink:0;}
/* The batch buttons sit on the category banner, which is a photograph behind them, so they carry their own
   background and border rather than inheriting the panel look the card buttons use. Sized and weighted like the
   Top button beside them so the two do not read as belonging to different interfaces. */
.btn-batch{font:inherit;font-size:.72rem;font-weight:700;color:#e7eefa;background:rgba(6,10,18,.62);
  border:1px solid rgba(255,255,255,.28);border-radius:999px;padding:6px 14px;white-space:nowrap;cursor:pointer;
  backdrop-filter:blur(6px);text-decoration:none;display:inline-block;
  transition:background .15s ease,border-color .15s ease,transform .15s ease;}
.btn-batch:hover{background:var(--accent);border-color:var(--accent);color:var(--accent-ink);transform:translateY(-1px);}
.bar .btn-batch{font-size:.78rem;padding:9px 18px;background:var(--panel);color:var(--text);border-color:var(--line);}
:root[data-theme="light"] .btn-batch{color:#16202f;background:rgba(255,255,255,.78);border-color:rgba(0,0,0,.16);}
:root[data-theme="light"] .btn-batch:hover{color:var(--accent-ink);}
.jump-top{font:inherit;font-size:.72rem;font-weight:600;color:var(--text);background:rgba(6,10,18,.48);border:1px solid rgba(255,255,255,.24);border-radius:999px;padding:6px 14px;cursor:pointer;transition:background .15s ease,border-color .15s ease,transform .15s ease;}
.jump-top:hover{background:var(--accent);border-color:var(--accent);transform:translateY(-1px);}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(268px,1fr));gap:18px;margin-top:18px;}
   .card{display:flex;flex-direction:column;background:var(--panel);border:1px solid var(--line);border-radius:16px;overflow:hidden;
   transition:transform .2s cubic-bezier(.2,.7,.3,1),border-color .2s ease,box-shadow .2s ease,background .2s ease;}
.card.is-hidden{display:none;}
.card.in-view{opacity:1;transform:translateY(0);}
/* Card size presets - small = half, medium = default, large = double. The body class drives
   grid columns, gap, and card scale so the whole shelf reflows at once. */
.grid{grid-template-columns:repeat(auto-fill,minmax(var(--card-min-width,268px),1fr));gap:var(--card-gap,18px);margin-top:var(--card-margin-top,18px);}
body.card-size-medium{--card-min-width:268px;--card-gap:18px;--card-margin-top:18px;}
body.card-size-large{--card-min-width:504px;--card-gap:26px;--card-margin-top:26px;}
.size-toggle{display:flex;gap:6px;align-items:center;white-space:nowrap;}
.size-btn{flex:none;width:24px;height:24px;border-radius:6px;font-size:.68rem;font-weight:700;border:1px solid var(--line);background:var(--raised);color:var(--text);cursor:pointer;}
.size-btn:hover{border-color:var(--accent);}
.size-btn.is-active{background:var(--accent);border-color:var(--accent);color:var(--accent-ink);}
.card:hover{transform:translateY(-6px);border-color:var(--accent-line);box-shadow:0 24px 50px rgba(0,0,0,.4);}
.card:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-glow);}
.card:hover .card-hover{opacity:1;transform:translateY(0);}
.card-hover{position:absolute;left:0;right:0;bottom:0;background:linear-gradient(180deg,rgba(8,11,18,0) 0,rgba(8,11,18,.78) 55%,rgba(8,11,18,.92) 100%);
  opacity:0;transform:translateY(8px);transition:opacity .2s ease,transform .2s ease;color:var(--text);padding:14px 14px 10px;}
.card-hover .hover-genres,.card-hover .hover-date{display:block;font-size:.73rem;opacity:.85;line-height:1.4;}
.card-link{display:flex;flex-direction:column;color:inherit;flex:1;}
.card-link-plain{cursor:default;}
.card-art{position:relative;overflow:hidden;background:var(--bg-2);}
.card img{width:100%;aspect-ratio:460/215;object-fit:cover;background:var(--bg-2);display:block;transition:transform .35s cubic-bezier(.2,.7,.3,1);}
.card:hover img{transform:scale(1.06);}
.card-check{position:absolute;top:10px;right:10px;width:24px;height:24px;opacity:0;cursor:pointer;z-index:3;accent-color:var(--accent);}
body.multi-mode .card-check{opacity:1;}
body.multi-mode .card.multi-selected{border:2px solid var(--accent);}
body.multi-mode .category-header{opacity:1;visibility:visible;}
body.multi-mode .badge-done,body.multi-mode .badge-warn,body.multi-mode .badge-install,body.multi-mode .badge-stale{opacity:1;visibility:visible;}
.scrim{position:absolute;inset:0;background:linear-gradient(180deg,transparent 52%,var(--scrim));opacity:.85;pointer-events:none;}
.card-cat{position:absolute;left:10px;top:10px;font-size:.62rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
  color:#eaf2ff;background:rgba(6,10,18,.62);border:1px solid rgba(255,255,255,.18);padding:3px 9px;border-radius:999px;backdrop-filter:blur(6px);}
.card-body{padding:14px 16px 12px;display:flex;flex-direction:column;flex:1;}
.card-body h3{margin:0 0 4px;font-size:1.02rem;line-height:1.32;letter-spacing:-.01em;}
.meta{margin:0 0 8px;color:var(--accent);font-size:.75rem;font-weight:600;}
 .desc{margin:0;color:var(--muted);font-size:.83rem;line-height:1.55;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;}
 .badges{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:auto;padding-top:12px;}
 .chip{background:var(--chip);border:1px solid var(--line);color:var(--muted);font-size:.67rem;padding:2px 9px;border-radius:999px;}
 /* Subtle pulse for badges that need attention - "No Steam match" and installer badges
    draw the eye without being distractingly bright. Uses a gentle opacity swing so the
    badge breathes in and out rather than flashing. */
  .badge-muted,.badge-warn,.badge-install,.badge-stale{animation:badge-pulse 3s ease-in-out infinite;}
  .badge-install{animation-delay:.3s;}
  .badge-warn,.badge-stale{animation-delay:.15s;}
 @keyframes badge-pulse{0%,100%{opacity:.85;}50%{opacity:1;}}
  /* Steam tags get their own row and their own tint. They answer a different question from genres - what this is
     like to play, rather than what kind of thing it is - and sharing one row made every card look like the same
     six grey pills. Capped at four on the card: past that the row stops being a summary and becomes a wall, and
     the whole list is in the search index regardless. */
  .tags{display:flex;gap:5px;flex-wrap:wrap;margin:9px 0 0;}
  .chip-tag{background:rgba(139,108,255,.15);border-color:rgba(139,108,255,.42);color:#bda9ff;
    max-width:170px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  :root[data-theme="light"] .chip-tag{background:rgba(139,108,255,.12);border-color:rgba(139,108,255,.38);color:#5a3fd6;}
  .chip-more{background:none;border-style:dashed;color:var(--dim);}
.badge{background:var(--accent-soft);border:1px solid var(--accent-line);color:var(--accent);font-size:.67rem;padding:2px 8px;border-radius:999px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;overflow:hidden;text-overflow:ellipsis;max-width:190px;white-space:nowrap;}
.badge-muted{background:var(--wash);border-color:var(--line);color:var(--muted);}
  /* The "already unpacked" mark. Green, because the predicate behind it is the same one Extract all skips on -
     it is not a claim about what someone thinks was done, it is the planner's own answer. */
  .badge-done{background:rgba(46,160,67,.14);border-color:rgba(46,160,67,.45);color:#3fb950;}
  .badge-done .unpacked-on{font-size:.62rem;color:#5ed37a;opacity:.85;}
/* The "unpacked but needs installing" mark. Amber so it reads as work left undone, not as a finished game -
   the unpack succeeded, but setup.exe has to be run before there is anything to launch. Sized and glowing
   like the installer badge so the one action a reader still has to take cannot be missed. */
  .badge-warn{background:rgba(219,109,40,.18);border-color:rgba(219,109,40,.7);color:#ffc078;
    font-weight:700;font-size:.82rem;padding:5px 10px;box-shadow:0 0 0 1px rgba(219,109,40,.25) inset,0 0 12px rgba(219,109,40,.35);}
  .badge-warn:hover{background:rgba(219,109,40,.28);box-shadow:0 0 0 1px rgba(219,109,40,.4) inset,0 0 18px rgba(219,109,40,.5);}
/* Pre-extraction installer badge. Blue - informational, not a state claim - so it cannot be mistaken for the
   green "ready" mark or the amber "unpacked but still needs installing" mark. Sized and glowing so a game
   that is an installer cannot be missed in a shelf of otherwise identical cards: the icon is 20px with a
   drop-shadow, the badge text is bold and larger than the other badges, and the whole thing carries an
   inner ring and outer glow that survives the card's photo background. */
.badge-install{background:rgba(41,128,220,.18);border-color:rgba(41,128,220,.7);color:#6cb4ee;
  font-weight:700;font-size:.82rem;padding:5px 10px;box-shadow:0 0 0 1px rgba(41,128,220,.25) inset,0 0 12px rgba(41,128,220,.35);}
.badge-install:hover{background:rgba(41,128,220,.28);box-shadow:0 0 0 1px rgba(41,128,220,.4) inset,0 0 18px rgba(41,128,220,.5);}
  .badge-icon{display:inline-block;width:16px;height:16px;vertical-align:middle;margin-right:6px;flex-shrink:0;
    filter:drop-shadow(0 0 3px rgba(41,128,220,.6));}
  .badge-warn .badge-icon{filter:drop-shadow(0 0 3px rgba(219,109,40,.6));}
  /* Stale-extraction badge. Orange — between the amber "needs install" and the blue "installer" — signals a
     game that is unpacked but whose archive on disk has changed. Pulses gently so it catches the eye without
     competing with the warning and installer animations. */
  .badge-stale{background:rgba(219,109,40,.14);border-color:rgba(219,109,40,.7);color:#ff9a3c;
    font-weight:700;font-size:.82rem;padding:5px 10px;box-shadow:0 0 0 1px rgba(219,109,40,.25) inset,0 0 8px rgba(219,109,40,.3);}
  .badge-stale:hover{background:rgba(219,109,40,.24);box-shadow:0 0 0 1px rgba(219,109,40,.4) inset,0 0 12px rgba(219,109,40,.4);}
  .badge-stale .badge-icon{filter:drop-shadow(0 0 3px rgba(219,109,40,.6));}
  /* The last batch run's result. Sits between the hero and the toolbar because it is the answer to the last
     thing the reader did, hours after they did it. Kept to one line that wraps rather than a panel: it is a
     status, not a section, and the page is already tall enough. */
  .run-status{margin:14px 0 0;padding:10px 14px;border:1px solid var(--accent-line);
    background:var(--accent-soft);color:var(--text);border-radius:10px;font-size:.85rem;line-height:1.45;}
  .run-status[hidden]{display:none;}
  .run-status-warn{border-color:var(--warn);background:rgba(219,109,40,.12);}
 .category.recent .category-header{background:linear-gradient(135deg,rgba(255,192,120,.28),var(--chip));}
 .batch-status{margin:6px 0 16px;padding:6px 12px;border-radius:8px;font-size:.74rem;font-weight:600;
   background:var(--raised);border:1px solid var(--line);color:var(--dim);}
 .batch-status[hidden]{display:none;}
 .batch-status-warn{border-color:var(--warn);color:var(--warn);}
   .foot-note{margin:8px 0 0;color:var(--dim);}
.size{margin-left:auto;color:var(--dim);font-size:.72rem;font-variant-numeric:tabular-nums;white-space:nowrap;}
.card-actions{display:flex;gap:7px;padding:11px 13px 13px;border-top:1px solid var(--line-soft);background:var(--wash);}
.btn{flex:1;text-align:center;padding:8px;border-radius:9px;font-size:.74rem;font-weight:600;border:1px solid var(--line);
  background:var(--raised);color:var(--text);cursor:pointer;font-family:inherit;transition:background .15s ease,border-color .15s ease,color .15s ease;}
.btn:hover{background:var(--accent-soft);border-color:var(--accent);}
.btn-extract{border-color:var(--good);color:var(--good);}
.btn-extract:hover{background:rgba(84,224,164,.14);}
:root[data-theme="light"] .btn-extract{border-color:#0b7a51;color:#0b7a51;}
.btn-reextract{border-color:var(--warn);color:var(--warn);}
.btn-reextract:hover{background:rgba(245,158,11,.14);}
.btn-open-extracted{border-color:var(--accent);color:var(--accent);}
.btn-open-extracted:hover{background:rgba(90,169,255,.14);}
 .btn-steam{border-color:var(--good);color:var(--good);}
 .btn-steam:hover{background:var(--wash);border-color:var(--good);}
 .btn-folder{border-color:var(--dim);color:var(--muted);}
 .btn-folder:hover{border-color:var(--accent);}
/* The setup button sits in the toolbar, not on a card, so it is sized like the
   bar's batch button rather than the card buttons' flex row, and wears the
   accent to read as the one thing to do on a PC this page has not seen. */
.btn-setup{border-color:var(--accent);white-space:nowrap;text-decoration:none;display:inline-block;}
  .btn-setup:hover{background:var(--accent-soft);}
  .bar .btn-setup{font-size:.78rem;padding:9px 18px;animation:setup-pulse 2s cubic-bezier(.4,0,.6,1) 1s 1;}
  @keyframes setup-pulse{0%,100%{box-shadow:0 0 0 0 rgba(90,169,255,.4);}50%{box-shadow:0 0 0 8px rgba(90,169,255,0);}}
/* The command-line fallback shown beside the setup button. A browser that has never seen
   steamgameorganizer:// shows a prompt and then opens the app; one that has dismissed the
   prompt once opens nothing at all, and the reader is left staring at a page that did not
   change. This row is always visible so the fallback is an answer in place, not a footnote
   the reader has to scroll to find. */
.setup-fallback{display:inline-flex;align-items:center;gap:8px;margin-left:12px;
  font-size:.72rem;color:var(--muted);}
.setup-fallback-text{color:var(--muted);}
.setup-cmd{background:var(--panel);border:1px solid var(--line);border-radius:6px;
  padding:2px 8px;font-size:.7rem;color:var(--text);white-space:nowrap;}
.toast{position:fixed;left:50%;bottom:28px;transform:translate(-50%,20px);background:var(--raised);border:1px solid var(--accent);
  color:var(--text);padding:12px 20px;border-radius:12px;font-size:.85rem;box-shadow:var(--shadow);opacity:0;pointer-events:none;
  transition:opacity .2s ease,transform .2s ease;z-index:70;max-width:82vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.toast.show{opacity:1;transform:translate(-50%,0);}
/* The last single Extract click's outcome used to be shown here as a dedicated bar.
   The extract UI now surfaces that result in a desktop dialog, so the bar is removed. */
.to-top{position:fixed;right:24px;bottom:24px;z-index:40;width:44px;height:44px;border-radius:50%;font-size:1.05rem;font-weight:700;
  color:var(--text);background:var(--raised);border:1px solid var(--line);box-shadow:var(--shadow);cursor:pointer;
  opacity:0;pointer-events:none;transition:opacity .2s ease,transform .2s ease,background .2s ease;}
.to-top.show{opacity:1;pointer-events:auto;}
  .to-top:hover{background:var(--accent);color:var(--accent-ink);transform:translateY(-3px);}
  /* CSS-only tooltips: a data-tip attribute renders a styled callout on hover,
     replacing the browser-default title= bubble with a themed one. */
  [data-tip]{position:relative;cursor:help;}
  [data-tip]::after{content:attr(data-tip);position:absolute;left:50%;bottom:125%;transform:translateX(-50%);
    background:var(--raised);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:6px 12px;
    font-size:.74rem;white-space:nowrap;pointer-events:none;opacity:0;transition:opacity .15s ease;
    box-shadow:0 8px 24px rgba(0,0,0,.4);z-index:10;}
  [data-tip]:hover::after{opacity:1;}
footer{text-align:center;color:var(--dim);padding:30px;font-size:.79rem;border-top:1px solid var(--line-soft);margin-top:20px;}
/* Below the rail's own minimum, the sidebar becomes a horizontal chip strip: the sticky column is worth
   nothing when it would eat a third of a narrow window. */
@media (max-width:1080px){
  .shell{grid-template-columns:minmax(0,1fr);gap:0;}
  .rail{position:static;max-height:none;padding:20px 0 0;}
  nav.toc ul{flex-direction:row;flex-wrap:wrap;gap:7px;}
  .toc-link{border:1px solid var(--line);background:var(--panel);}
  .genres,.tags-nav,.rail-help{display:none;}
}
@media (max-width:560px){
  .bar-inner{flex-wrap:wrap;}
  .sorts{flex:1 1 100%;justify-content:flex-start;}
  .dest,.root{flex:1 1 100%;}
  #extract-dest,#game-folder{max-width:none;font-size:.88rem;padding:11px 13px;}
  .grid{grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px;}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important;}html{scroll-behavior:auto;}}
@media print{
  .bar,.rail,.to-top,.progress,.card-actions{display:none;}
  body{background:#fff;color:#000;}
  .card,.category-header{border-color:#ccc;box-shadow:none;}
}
"""
        return self._css_cache


# New in this release: offline HTML game catalog (TOC, category hero art, one portable file for every platform).
