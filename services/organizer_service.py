from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
import contextlib
import json
# Imports split one per line for GitHub readability.
import ctypes
from html import escape
from datetime import datetime
import re
from core.constants import (
    canonical_category,
    ARCHIVE_EXTENSIONS,
    LOCK_MARKER,
    COMPRESSION_LEVEL,
    COMPRESSION_THREADS,
    MIN_COMPRESSION_LEVEL,
    LEVEL_RAM_BYTES,
    RAM_HEADROOM_BYTES,
    PROCESSING_DIRNAME,
    TEMP_DIR_PREFIX,
    TEMP_FILE_TAG,
    NO_WINDOW,
    DEFAULT_ZIP_PASSWORD,
)
from core.exceptions import CancellationError
from services.extract_service import ExtractService
from utils.filename_utils import version_key

# Unmistakable markers so a leftover temp file or extraction folder can never be mistaken for real content,
# and so LibraryService.cleanup_leftovers() can recognise exactly what this app created.
# 7z -bsp1 and unrar both report progress as " 92% 2 + path/to/file", with - marking a rewrite of an entry
# that already exists. Only the trailing name matters here; the counter is 7z-internal. The lookbehind keeps
# the digit group from being matched out of a longer number. This is named apart from the extraction side's
# EXTRACT_PROGRESS_RE because the two read different streams - this one parses -bsp1 records off a running
# tool's pipe, that one parses whole lines from a finished listing. They were both called TOOL_PROGRESS_RE
# while holding different patterns, which reads as one shared rule.
STAGE_PROGRESS_RE = re.compile(r"(?<!\d)(\d{1,3})%\s+(?:\d+\s+[+-]\s+)?(.*)$")


class OrganizerService:
    def __init__(self, logger, convert_archives=True):
        self.logger = logger
        # May be a bool or a callable. The service is built once at startup but the control is a live
        # checkbox, so the app passes a callable and the current value is read at the moment of use rather
        # than frozen at construction.
        self._convert_setting = convert_archives
        # Cache for archive integrity tests: {path_str: (size, mtime_ns, result)}
        self._integrity_cache = {}
        # Cache for archive content-folder-name listings: {path_str: (size, mtime_ns, folder_name|None)}.
        # A .7z whose top-level folder is already named correctly skips the full extract-and-rebuild cycle,
        # but the listing is re-run on every scan until this cache remembers it.
        self._content_folder_cache = {}
        # Cache for archive manifest listings (file count + total bytes from 7z index): {path_str: (size, mtime_ns, (files, bytes)|None)}.
        # _extraction_is_short() reads the manifest on every conversion; caching it skips a redundant 7z l -slt
        # when the same archive is re-checked within one process.
        self._manifest_cache = {}

    @property
    def convert_archives(self):
        """A .zip or .rar is still moved and renamed into its game folder either way, it is just not
        rebuilt, so turning conversion off never blocks organizing a game."""
        setting = self._convert_setting
        return bool(setting() if callable(setting) else setting)

    def _safe_name(self, value):
        value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(value or "")).strip().rstrip(".")
        return re.sub(r"\s+", " ", value) or "Unnamed Game"

    def _release_label(self, release_date):
        value = str(release_date or "Unknown Release Date").strip()
        for pattern in ("%d %b, %Y", "%b %d, %Y", "%Y-%m-%d", "%d %B, %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(value, pattern).strftime("%Y-%m-%d")
            except ValueError:
                pass
        return self._safe_name(value)

    def _game_name(self, archive):
        # The title is sanitised before the date is added, not after. Sanitising the composed string leaves the
        # date behind, so a title built only from characters Windows forbids produced a folder called
        # "- 2020-03-04" with the game name gone and _safe_name's "Unnamed Game" fallback unreachable - while
        # _asset_prefix, which has no date to keep the string alive, did produce "Unnamed Game". The folder and
        # the files inside it were named after different things.
        title = self._safe_name(archive.steam.name or archive.user_title or archive.display_name)
        return self._safe_name(f"{title} - {self._release_label(archive.steam.release_date)}")

    def _asset_prefix(self, archive):
        return self._safe_name(archive.steam.name or archive.user_title or archive.display_name)

    def _modified_at(self, path):
        try:
            return Path(path).stat().st_mtime
        except OSError:
            return 0

    def _path_promotion_key(self, path):
        """Same promotion rule as _promotion_key, but for a bare path. Used by the library audit, which
        inspects already-organized folders where no GameArchive has been built yet."""
        return version_key(Path(path).name), self._modified_at(path)

    def _promotion_key(self, archive):
        """Promotion key for a GameArchive object - delegates to _path_promotion_key."""
        return self._path_promotion_key(archive.path)

    def _unique_dir(self, parent, name):
        target = parent / name
        if target.is_dir():
            return target
        n = 2
        while target.exists():
            target = parent / f"{name} ({n})"
            n += 1
        return target

    def needs_catalog_launcher(self):
        """Whether a launcher file belongs beside the catalog on this machine.

        Only true when the machine has no association for .html at all, because that is the single case where
        double-clicking the catalog would not open a browser. A machine that already knows what to do with an
        HTML file gets the catalog on its own, with nothing extra sitting in the library root.

        This used to return a browser *command*, found by searching PATH for `google-chrome-stable`,
        `google-chrome`, `chrome`, `chromium` and `chromium-browser`, and then asking Flatpak for
        `com.google.Chrome`, `com.google.ChromeDev` and `org.chromium.Chromium`. None of those can match here -
        Chrome installs itself into Program Files without registering on PATH, and a Flatpak app id is a SteamOS
        concept. `browser()` also returned a second value, an XDG desktop-file id like `chrome.desktop`, which
        every caller discarded. The command was then handed to the launcher writer, which never used it: a .url
        file carries a URL and nothing else and is resolved by the shell association, so a command inside it
        would have had nothing to act on.

        Six Linux package and app names, a discarded second return value, and a command that went nowhere were
        the whole mechanism behind a yes/no question. Answered directly now.
        """
        return not self.html_handler()

    def html_handler(self):
        r"""Whether this machine already opens .html with something, and which program that is.

        On Windows the answer comes from the registry, because that is where Windows keeps it. This used to read
        only the Linux XDG mimeapps.list, which cannot exist here - so it always answered "nothing", on a machine
        where `HKCR\.html` resolves to `htmlfile` and double-clicking the catalog works perfectly well. That wrong
        answer is what caused a launcher to be written beside every catalog, pointing at a browser command that did
        not exist, in a `.desktop` format Windows ignores.

        There is no attempt to *set* that handler. Windows deliberately ignores attempts by a program to change a
        default file association, and rightly so - an app that could do it would be hijacking every .html on the
        machine.
        """
        return self._windows_html_handler()

    @staticmethod
    def _windows_html_handler():
        """The ProgID Windows associates with .html, or None.

        Read from HKCR, which is the merged view of machine and user associations - so it sees a handler set
        per-user as well as one installed for everyone. Returns the ProgID ('htmlfile', 'MSEdgeHTM') rather than
        a path: the association is what decides whether double-clicking works, and the ProgID is what the
        registry stores.
        """
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, ".html") as key:
                progid = winreg.QueryValueEx(key, "")[0]
        except OSError:
            return None
        return str(progid).strip() or None

    # Every link filename this app has ever written. Older releases shipped a Linux .desktop and a separate
    # Windows .url, which meant two files per game to describe one URL, and neither worked on the other
    # platform. Anything in this list is normalized down to the single portable .html shortcut.
    LEGACY_LINK_NAMES = ("Open Steam Page.desktop", "Open Steam Page in Chrome.desktop", "Open Steam Page (Steam Deck).desktop", "Open Steam Page (Windows).url")
    LINK_NAME = "Open Steam Page.html"

    def _clean_old_links(self, game_dir):
        for name in self.LEGACY_LINK_NAMES:
            path = game_dir / name
            try:
                if path.is_file():
                    path.unlink()
            except OSError as exc:
                self.logger.warning("ORGANIZER", f"OLD_LINK_REMOVE_FAILED path=[{path}] error={type(exc).__name__}")

    def write_steam_links(self, game_dir, appid, name=None):
        """Write one shortcut per game that opens the Steam store page.

        This is a single .html file on purpose. The old pair - a Linux .desktop beside a Windows .url - meant two
        files per game to describe one URL, and each platform ignored the other's. A .url would also have been
        enough on its own, but an HTML document carries a readable title and works when the file is opened from
        anywhere at all, including a share or a mapped drive, and it needs no executable bit or trust prompt.
        """
        if not appid:
            return None
        url = f"https://store.steampowered.com/app/{appid}/"
        self._clean_old_links(game_dir)
        link = game_dir / self.LINK_NAME
        # The browser tab shows this, so it uses the game's real name. Falling back to the folder name would
        # put the date suffix - "Chef Knight - 2026-06-01" - in every title the user sees.
        name = escape(str(name or getattr(game_dir, "name", game_dir)))
        link.write_text(
            '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
            f"<title>{name} — Steam</title>\n"
            f'<meta http-equiv="refresh" content="0; url={url}">\n'
            '<link rel="canonical" href="' + url + '">\n'
            "<style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;"
            'background:#0b0e14;color:#e7ecf3;font-family:-apple-system,"Segoe UI",Roboto,Arial,sans-serif}'
            "main{text-align:center;padding:32px}"
            "a{color:#4da3ff;font-weight:600}h1{font-size:1.35rem;margin:0 0 10px}</style>\n"
            "</head>\n<body>\n<main>\n"
            f"<h1>{name}</h1>\n<p>Opening the Steam store page…</p>\n"
            f'<p><a href="{url}">Open on Steam</a></p>\n'
            "</main>\n</body>\n</html>\n",
            encoding="utf-8",
        )
        return link

    def write_metadata(self, game_dir, archive):
        steam = archive.steam
        data = {
            "appid": steam.appid,
            "name": steam.name or archive.user_title or archive.display_name,
            "description": steam.description,
            "release_date": steam.release_date,
            "genres": steam.genres,
            "tags": steam.tags,
            "developer": steam.developer,
            "publisher": steam.publisher,
            "category": archive.decision.category,
            "steam_url": f"https://store.steampowered.com/app/{steam.appid}/" if steam.appid else "",
        }
        path = game_dir / ".game-info.json"
        try:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            self.logger.warning("ORGANIZER", f"METADATA_WRITE_FAILED path=[{path}] error={type(exc).__name__}")

    # What an organized game folder looks like from the inside. The app writes all of these itself, so their
    # presence means the folder is a game the user owns, not a leftover folder a download left behind.
    MANAGED_FOLDER_MARKERS = (".game-info.json", "Open Steam Page.html")

    # The only files this app may delete along with a folder it has just emptied. Everything else in that
    # folder belongs to the user, whatever produced it.
    #
    # The link and metadata names are here as well as in MANAGED_FOLDER_MARKERS because the two lists answer
    # different questions: that one asks "is this a game the app filed?", this one asks "is every entry here
    # something the app put there?". A folder carrying either marker is kept by the first rule regardless.
    RECOGNISED_FOLDER_FILES = frozenset({".game-info.json", LINK_NAME, *LEGACY_LINK_NAMES})
    # Artwork, by suffix rather than by the exact name it was written under. move() copies the primary in as
    # `<title>_grid.jpg` and each asset as `<title>_<asset>.<ext>`, so the title and the asset name both vary
    # per game; the suffix is the part that says what the file is.
    RECOGNISED_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"})

    def _folder_is_disposable(self, folder):
        """True when a folder holds nothing this app did not put there itself.

                This allow-list is the whole safety argument, because `shutil.rmtree` removes a whole tree without
                asking anything first. Every entry is checked, and one unrecognised entry vetoes the whole folder: a
                save file, a notes file, a mods directory, a launcher config, anything at all that is not ours.

                Subdirectories veto on sight rather than being walked. There is no directory this app writes into a
                download folder, so a directory there is always the user's, and rmtree would take its entire contents
                with it. Symlinks are refused for the same reason one-handed: a link is not the thing it points at,
                and following it out of the library is not a removal anybody asked for.

                A folder that cannot even be listed is not disposable. `iterdir` raising means the answer is unknown,
                and unknown is not the same as empty.

        Asked from outside the class too, but not by the Undo button: RollbackService decides that with
                _folder_is_prunable(), which is stricter, because this rule trusts an image's suffix and an undo is
                asking about a folder the user may have put things in.
        """
        try:
            entries = list(Path(folder).iterdir())
        except OSError as exc:
            self.logger.warning("ORGANIZER", f"KEPT_SOURCE_FOLDER path=[{folder}] reason=[unreadable: {type(exc).__name__}]")
            return False
        for item in entries:
            if item.is_symlink() or not item.is_file():
                self.logger.info("ORGANIZER", f"KEPT_SOURCE_FOLDER path=[{folder}] reason=[holds {item.name}]")
                return False
            if item.name in self.RECOGNISED_FOLDER_FILES:
                continue
            if item.suffix.lower() in self.RECOGNISED_IMAGE_SUFFIXES:
                continue
            self.logger.info("ORGANIZER", f"KEPT_SOURCE_FOLDER path=[{folder}] reason=[unrecognised file {item.name}]")
            return False
        return True

    def _folder_is_prunable(self, folder):
        """Whether an undo may remove a game folder it has just emptied.

        Deliberately stricter than _folder_is_disposable(), and the difference is the whole point of having
        two. That rule accepts any image by suffix, which is right for the one folder it was written for: the
        download folder this app emptied itself, where every .jpg got there by being downloaded. An organized
        game folder is the user's folder - it is where a screenshot or a downloaded manual ends up beside the
        game - and there is nothing in a suffix that separates that from the artwork the app wrote. So the
        artwork accepted here has to carry the shape _asset_prefix() writes, <title>_grid.jpg and
        <title>_<asset>.jpg, and an underscore in the stem is what that looks like once the name is a path.

        Called from outside the class, like _folder_is_disposable(): RollbackService holds one of these to
        decide whether the Undo button may remove a folder, and one answer has to rule both.
        """
        try:
            entries = list(Path(folder).iterdir())
        except OSError as exc:
            self.logger.warning("ORGANIZER", f"KEPT_PRUNED_FOLDER path=[{folder}] reason=[unreadable: {type(exc).__name__}]")
            return False
        for item in entries:
            if item.is_symlink() or not item.is_file():
                self.logger.info("ORGANIZER", f"KEPT_PRUNED_FOLDER path=[{folder}] reason=[holds {item.name}]")
                return False
            if item.name in self.RECOGNISED_FOLDER_FILES:
                continue
            if item.suffix.lower() in self.RECOGNISED_IMAGE_SUFFIXES and "_" in item.stem:
                continue
            self.logger.info("ORGANIZER", f"KEPT_PRUNED_FOLDER path=[{folder}] reason=[unrecognised file {item.name}]")
            return False
        return True

    def _remove_generated_source_folder(self, source, destination):
        folder = Path(source).parent
        destination = Path(destination).resolve()
        if folder == destination or folder.parent == destination or not folder.is_dir():
            return False
        # Never delete a folder that still holds an archive (zip/rar/7z) anywhere inside it. A second
        # copy of a game left in the folder by hand is a real case, and the sweep exists for it.
        try:
            has_archive = any(item.is_file() and item.suffix.lower() in ARCHIVE_EXTENSIONS for item in folder.rglob("*"))
        except OSError:
            return False
        if has_archive:
            return False
        # Whether this folder is one this app filed. A download folder is not: the player dropped the
        # archive there and may have put saves, notes or mods beside it, and the disposable rule
        # accepts any picture because every .jpg in a download folder got there by being downloaded.
        # A game folder is the player's too - a screenshot ends up beside the game - so the prunable
        # rule accepts only app-shaped artwork and refuses everything else.
        #
        # The marker used to refuse outright, on the reasoning "never delete a game folder". That is
        # right for the case the comment below describes - a second copy of an already-organised
        # game - and wrong for the re-categorise case: the archive moves out, the folder stays, and
        # every scan reports it as an empty game with no archive, holding the image the app wrote.
        # The folder is now judged by contents instead: it is ours to remove only when every entry
        # in it is something this app put there, and a managed folder is moved to Archive rather than
        # deleted so the user can review it before deleting.
        managed = any((folder / marker).exists() for marker in self.MANAGED_FOLDER_MARKERS)
        if managed:
            if not self._folder_is_prunable(folder):
                return False
        elif not self._folder_is_disposable(folder):
            return False
        destination = Path(destination).expanduser().resolve()
        archive_dir = destination / "Archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        target = archive_dir / folder.name
        n = 2
        while target.exists():
            target = archive_dir / f"{folder.name} ({n})"
            n += 1
        try:
            shutil.move(str(folder), str(target))
            self.logger.info("ORGANIZER", f"REMOVED_GENERATED_FOLDER path=[{folder}] destination=[{target}]")
            return True
        except OSError as exc:
            self.logger.warning("ORGANIZER", f"GENERATED_FOLDER_REMOVE_FAILED path=[{folder}] error={type(exc).__name__}")
            return False

    # Folder names that hold the actual playable game content inside a repack/release wrapper (as opposed to
    # installer-based layouts, which are left untouched since there is nothing meaningful to rename).
    GENERIC_CONTENT_FOLDER_NAMES = {"game"}

    def _find_generic_content_folder(self, root, max_depth=3):
        queue = [(root, 0)]
        while queue:
            current, depth = queue.pop(0)
            if depth > max_depth:
                continue
            try:
                children = [child for child in current.iterdir() if child.is_dir()]
            except OSError:
                continue
            for child in children:
                if child.name.casefold() in self.GENERIC_CONTENT_FOLDER_NAMES:
                    return child
            queue.extend((child, depth + 1) for child in children)
        return None

    def _content_folder_name(self, path):
        """The top-level folder inside an archive, or None when the archive holds no folder.

        Used to decide whether a .7z already has the right content folder name and can skip the
        full extract-and-rebuild cycle. Listing the index is a single read of the header, so this
        is seconds where the rebuild would be hours.
        """
        sevenzip, _reason = ExtractService.find_tool()
        if not sevenzip:
            return None
        try:
            stat = path.stat()
        except OSError:
            return None
        cache_key = str(path)
        cached = self._content_folder_cache.get(cache_key)
        if cached and cached[0] == stat.st_size and cached[1] == stat.st_mtime_ns:
            return cached[2]
        try:
            proc = subprocess.run([sevenzip, "l", "-slt", str(path)], stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", creationflags=NO_WINDOW)
        except OSError:
            self._content_folder_cache[cache_key] = (stat.st_size, stat.st_mtime_ns, None)
            return None
        if proc.returncode != 0:
            self._content_folder_cache[cache_key] = (stat.st_size, stat.st_mtime_ns, None)
            return None
        # 7-Zip's -slt listing prints each entry as a block with a "Path = " line. The first
        # directory entry at the top level is the content folder; a bare file at the root means
        # the archive has no folder to rename.
        names = set()
        for line in proc.stdout.splitlines():
            if not line.startswith("Path = "):
                continue
            name = line[len("Path = ") :].strip().replace("\\", "/")
            if not name or name.endswith("/"):
                continue
            parts = name.split("/")
            if len(parts) > 1:
                names.add(parts[0])
        result = sorted(names)[0] if len(names) == 1 else None
        self._content_folder_cache[cache_key] = (stat.st_size, stat.st_mtime_ns, result)
        return result

    def _available_ram(self):
        """Bytes of memory the kernel says are genuinely available, and the same for swap, or (None, None).

        ullAvailPhys is Windows' counterpart to Linux's MemAvailable: the kernel's own estimate of what a fresh
        allocation can claim without paging, where MemFree would be useless because it excludes reclaimable
        page cache. There is no swap on Windows, but there is a page file, and ullAvailPageFile is the commit
        allowance still unspent - so it answers the question the swap figure was asked for: how much room is
        left before the system starts refusing allocations.
        """
        return self._available_ram_windows()

    def _available_ram_windows(self):
        """Ask the kernel for the two numbers, over GlobalMemoryStatusEx.

        This reading used to come from /proc/meminfo, so on Windows it always failed and the panel showed no
        figure at all - and no reading means no headroom, so the compressor was free to pick a level the
        machine had no memory for.
        """
        try:

            class _Status(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64), ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64), ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64), ("ullAvailExtendedVirtual", ctypes.c_uint64)]

            status = _Status()
            status.dwLength = ctypes.sizeof(status)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None, None
            return int(status.ullAvailPhys), int(status.ullAvailPageFile)
        except (AttributeError, OSError, TypeError, ValueError):
            return None, None

    def _choose_compression_level(self):
        """Highest LZMA2 level that fits in real headroom right now, so maximum compression is used
        whenever the machine can actually sustain it and quietly stepped back when it cannot.

        The per-level costs are measured, not guessed: on this library's archives a level 6 build peaked
        at 702 MB and a level 9 build at 2561 MB, because peak usage tracks the LZMA2 dictionary almost
        linearly (levels 8 and 9 both use a 64 MB dictionary, so they cost the same and 9 compresses more).
        """
        available, swap_free = self._available_ram()
        if available is None:
            return COMPRESSION_LEVEL
        level = COMPRESSION_LEVEL
        while level > MIN_COMPRESSION_LEVEL and LEVEL_RAM_BYTES.get(level, 0) > available:
            level -= 1
        # Swap already in use means the system has been under pressure already. That is not proof the
        # compressor will not fit, but it is worth giving one level of headroom back rather than letting a
        # 2.5 GB match finder make the session thrash while an unattended run grinds on.
        if swap_free is not None and swap_free < RAM_HEADROOM_BYTES:
            level = max(MIN_COMPRESSION_LEVEL, level - 1)
        return level

    def _archive_manifest(self, path):
        """What the archive claims to contain: (file count, total uncompressed bytes) from its own index.

        Read-only and index-only, so it is cheap even for a 30 GB archive. Returns None when the tool cannot
        be run or the listing cannot be parsed, which the caller must treat as "unknown", not as "empty".

        Results are cached by (path, size, mtime_ns) to avoid re-reading the archive index when the same
        archive is checked multiple times in one process (_extraction_is_short() calls it per conversion).
        """
        sevenzip, _reason = ExtractService.find_tool()
        if not sevenzip:
            return None
        try:
            stat = path.stat()
        except OSError:
            return None
        cache_key = str(path)
        cached = self._manifest_cache.get(cache_key)
        if cached and cached[0] == stat.st_size and cached[1] == stat.st_mtime_ns:
            return cached[2]
        try:
            proc = subprocess.run([sevenzip, "l", "-slt", "-p", "--", str(path)], stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", creationflags=NO_WINDOW)
        except OSError:
            self._manifest_cache[cache_key] = (stat.st_size, stat.st_mtime_ns, None)
            return None
        if proc.returncode != 0:
            self._manifest_cache[cache_key] = (stat.st_size, stat.st_mtime_ns, None)
            return None
        files = 0
        total = 0
        # A directory entry has no `Size` of its own, so it would land in the totals as a zero byte file and
        # inflate the file count by the number of folders in the archive. 7-Zip 26.x reports directories as
        # `Attributes = D` and does not emit a `Folder` line at all; older builds used `Folder = +`, so both are
        # matched. The archive's own header block carries `Physical Size` rather than `Size`, which is what
        # keeps it out of the totals.
        for block in proc.stdout.split("\n\n"):
            if "Path = " not in block:
                continue
            if re.search(r"^Folder = \+$", block, re.M):
                continue
            attributes = re.search(r"^Attributes = (.*)$", block, re.M)
            if attributes and "D" in attributes.group(1).split():
                continue
            match = re.search(r"^Size = (\d+)$", block, re.M)
            if not match:
                continue
            files += 1
            total += int(match.group(1))
        result = (files, total) if files else None
        self._manifest_cache[cache_key] = (stat.st_size, stat.st_mtime_ns, result)
        return result

    def _extraction_is_short(self, path, temp_dir, game_files=None):
        """True when extraction produced less than the archive says it holds.

        This is the check that stands between a lossy extraction and a destroyed game. `7z t` on the rebuilt
        archive only proves the new file is internally readable: a rebuild of a partial extraction is a
        perfectly valid archive that is missing most of the game, it verifies clean, and the source is then
        deleted. Nothing downstream can detect that, so it has to be caught here, while the original is still
        on disk.

        `game_files` lets the caller pass the already-scanned extraction file list instead of re-walking the
        tree - this check and the byte total both read the same list during one conversion.

        Returns False when the manifest cannot be read, so an unknown is never mistaken for data loss.
        """
        claimed = self._archive_manifest(path)
        if not claimed:
            return False
        want_files, want_bytes = claimed
        have_files = 0
        have_bytes = 0
        try:
            items = game_files if game_files is not None else self._game_files(temp_dir)
            for item in items:
                have_files += 1
                try:
                    have_bytes += item.stat().st_size
                except OSError:
                    pass
        except OSError:
            return False
        if have_files >= want_files and have_bytes >= want_bytes:
            return False
        # A shortfall of up to 5% is not data loss: unrar exits 9 when it cannot open a file for a reason of
        # its own, and a repack's _INSTALL TUTORIAL.txt files are the usual victims. Big Ambitions had 72
        # of 1335 files missing and was 273 MB short of 6.76 GB - 4% - all tutorial text files that unrar
        # could not open. Ale Abbey extracted 123 of 125 and was 38 KB short of 1.2 GB. The check exists
        # for the opposite case, where a download was interrupted and most of the game is missing, so the
        # shortfall is measured as a fraction of the total and a small one is allowed through. The rebuild
        # then carries the files that did extract, which is the game. 5% is high enough to cover a batch
        # unrar failure and low enough that a truncated download - which misses far more than 5% of a
        # multi-GB game - is still caught.
        if want_bytes > 0 and (want_bytes - have_bytes) <= want_bytes // 20:
            self.logger.info("ORGANIZER", f"EXTRACTION_SLIGHT_SHORTFALL path=[{path.name}] claimed_files={want_files} extracted_files={have_files} claimed_bytes={want_bytes} extracted_bytes={have_bytes} shortfall={want_bytes - have_bytes}")
            return False
        self.logger.error("ORGANIZER", f"EXTRACTION_INCOMPLETE path=[{path.name}] claimed_files={want_files} extracted_files={have_files} claimed_bytes={want_bytes} extracted_bytes={have_bytes}")
        return True

    def _source_is_intact(self, path):
        """True when the archive passes a full CRC test before anything is done to it.

        This is the only check that catches the worst case: an archive that is itself incomplete, because a
        download was interrupted. Extracting one yields a self-consistent subset, and repacking that subset
        produces a perfectly valid .7z that passes `7z t`, is published, and leaves the source deleted - the
        game is then unrecoverable and nothing anywhere reports a problem. A real library held 82 truncated
        32-byte files exactly like this. Testing the source costs one extra read of it, which is a price worth
        paying next to losing the file.

        A password-protected zip cannot be tested by `7z t` without the password, and the app does not have
        one to give it: the password is removed later in the conversion pass, after this check. Running
        `7z t` on an encrypted zip therefore fails with "Break signaled" (exit 255), which the old code
        reported as a corrupt source and skipped the game entirely. The zip is not corrupt - it is
        encrypted - so the integrity test is skipped for encrypted zips, which are then decrypted and
        converted below.

        Results are cached by (path, size, mtime) to avoid re-testing unchanged archives across scans.
        """
        sevenzip, _reason = ExtractService.find_tool()
        if not sevenzip:
            return True
        if path.suffix.lower() == ".zip" and self._zip_is_encrypted(path):
            return True

        # Check cache
        try:
            stat = path.stat()
            cache_key = str(path)
            cached = self._integrity_cache.get(cache_key)
            if cached and cached[0] == stat.st_size and cached[1] == stat.st_mtime_ns:
                self.logger.debug("ORGANIZER", f"INTEGRITY_CACHE_HIT path=[{path.name}]")
                return cached[2]
        except OSError:
            pass

        try:
            proc = subprocess.run([sevenzip, "t", "--", str(path)], stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", creationflags=NO_WINDOW)
        except OSError:
            return True
        if proc.returncode == 0:
            result = True
        else:
            detail = re.sub(r"\s+", " ", (proc.stderr or proc.stdout)).strip()[:300]
            # The tool's own bytes go into the log verbatim otherwise, and one stray 0x9D makes the whole line
            # unreadable to anything reading the log with the platform's default codec.
            detail = detail.encode("ascii", "replace").decode("ascii")
            self.logger.error("ORGANIZER", f"SOURCE_INTEGRITY_FAILED path=[{path.name}] exit={proc.returncode} detail=[{detail or 'no output'}]")
            result = False

        # Cache result
        try:
            stat = path.stat()
            self._integrity_cache[str(path)] = (stat.st_size, stat.st_mtime_ns, result)
        except OSError:
            pass

        return result

    def _zip_is_encrypted(self, path):
        """True when the zip's central directory marks any entry as encrypted.

        Python's zipfile reads the flag bits without decrypting, so this is a cheap check that needs no
        password. WinZip AES entries carry bit 0 of the general-purpose flags.
        """
        try:
            with zipfile.ZipFile(path) as source:
                return any(info.flag_bits & 0x1 for info in source.infolist() if not info.is_dir())
        except Exception:
            return False

    def _unlock_zip(self, path, ctx=None):
        """Remove the password from a WinZip AES zip in place, so the conversion below can extract it.

        Delegates to ArchiveService._remove_zip_password, which is where the decryption logic lives.
        Returns True when the archive was rewritten without a password, False when it was already
        plain, and False when anything went wrong. A missing file is not an error here: this runs
        after the integrity test, which means the source was already read and found intact.

        The encryption check uses flag bits, not a zipfile read: opening a WinZip AES archive with
        Python's zipfile raises NotImplementedError, which would be caught by the except below and
        reported as "already plain" for an encrypted file.
        """
        from services.archive_service import ArchiveService

        if not path.is_file():
            return False
        if not self._zip_is_encrypted(path):
            return False
        return ArchiveService(self.logger)._remove_zip_password(path, ctx)

    def _looks_like_resource_failure(self, detail):
        """True when a build died from memory pressure or an interrupt rather than from bad input.

        7z reports these as exit 255 with 'Break signaled' and no useful explanation, which is
        indistinguishable from a genuine error by exit code alone. Retrying one level lower costs a
        minute; giving up costs the entire extraction.
        """
        text = (detail or "").lower()
        return any(marker in text for marker in ("break signaled", "not enough memory", "out of memory", "cannot allocate", "killed"))

    @staticmethod
    def _defender_flagged(detail):
        """The filenames Windows Defender refused to scan during a 7z build, parsed from its error text.

        7z's content-intelligence integration asks Defender to scan every file as it packs. A file
        Defender flags is reported as "Operation did not complete successfully because the file contains
        a virus or potentially unwanted software", followed by the path on the next line and "The
        system cannot find the file specified" on the line after. The names are extracted from the
        first form, which is stable across 7-Zip versions; the second form is the same file reported
        again after the scan was refused.
        """
        if not detail:
            return []
        names = []
        # The actual format is "path : message", not "message path": 7z prints the member path first,
        # then a colon, then the Defender refusal. The earlier version split on the message and took
        # what came after, which found nothing and returned an empty list - so every Defender refusal
        # was reported as a build failure with no exclusions to retry with.
        for line in detail.split("|"):
            line = line.strip()
            if "Operation did not complete successfully because the file contains a virus" not in line:
                continue
            path = line.split(" : ", 1)[0].strip()
            if not path:
                continue
            name = path.replace("\\", "/").lstrip("./").rsplit("/", 1)[-1]
            if name:
                names.append(name)
        return names

    @staticmethod
    def _still_running(process):
        # Tolerant on purpose: this runs from a finally block, and a process double or a platform that lacks
        # one of these must not turn a handled failure into an AttributeError that hides the real cause.
        poll = getattr(process, "poll", None)
        if poll is None:
            return False
        try:
            return poll() is None
        except OSError:
            return False

    @staticmethod
    def _stop_tool(process, grace=3.0):
        """Ends a running archive tool.

        terminate() asks first because 7z closes its output file on SIGTERM and the partial build can be
        reused as a retry candidate; kill() is the backstop for a tool wedged in a syscall. Both are needed:
        a level-9 LZMA2 build under memory pressure can ignore a polite signal for a long time.
        """
        if not OrganizerService._still_running(process):
            return
        with contextlib.suppress(OSError, AttributeError):
            process.terminate()
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            if not OrganizerService._still_running(process):
                return
            time.sleep(0.05)
        with contextlib.suppress(OSError, AttributeError):
            process.kill()
        # subprocess.TimeoutExpired is a SubprocessError, not an OSError, so a suppress written for the
        # signals above lets it straight through. That is the one exception this wait can raise, and letting
        # it out of a `finally` replaces whatever was already failing - which is the masking of the real cause
        # that the tolerance above exists to prevent.
        with contextlib.suppress(OSError, AttributeError, subprocess.TimeoutExpired):
            process.wait(timeout=5)

    @staticmethod
    def _watch_cancel(process, ctx):
        """Starts the thread that makes a cancel actually stop the tool, and returns its cancel Event.

        The read loop below spends minutes blocked in os.read() on the tool's pipe, so it cannot notice a
        cancel by looking for one. This thread waits on the job's event instead and kills the child, which
        closes the pipe, which lets the read loop return and unwind. Without it Cancel did nothing until the
        whole archive finished - up to twenty minutes - and closing the window waited behind it.
        """
        stop = threading.Event()
        if ctx is None:
            return stop

        def watch():
            # Poll rather than wait() forever so a tool that finishes on its own still releases the thread.
            while not stop.wait(0.2):
                if ctx.cancelled:
                    OrganizerService._stop_tool(process)
                    return

        thread = threading.Thread(target=watch, name="organizer-cancel-watch", daemon=True)
        thread.start()
        return stop

    def _run_tool(self, args, stage, report, throttle=1.0, cwd=None, ctx=None):
        """Runs an archive tool and streams its own progress back as it goes.

        7z is invoked with -bsp1 and unrar writes to stderr; both emit a percentage and the name of the
        entry currently being written, separated by backspace or carriage-return characters. Reading that is
        the only honest source of progress for a stage that can run for minutes - a UI timer can only guess,
        and a guess is what left the bar frozen. stdout and stderr are merged so one reader covers both
        tools, and the tail is retained because it is the only diagnostic when a conversion fails.
        """
        process = subprocess.Popen(args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        stop = self._watch_cancel(process, ctx)
        try:
            tail = []
            buffer = ""
            last_sent = -10.0
            last_file = ""
            fd = process.stdout.fileno()
            while True:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                # Backspace and carriage return are how both tools redraw a progress line in place, so they are
                # record separators here rather than characters to keep.
                buffer += chunk.decode("utf-8", errors="replace")
                records = re.split(r"[\b\r\n]", buffer)
                buffer = records.pop()
                for record in records:
                    if record.strip():
                        tail.append(record.strip())
                        del tail[:-6]
                    steam_match = STAGE_PROGRESS_RE.search(record)
                    if not steam_match:
                        continue
                    pct = int(steam_match.group(1))
                    name = (steam_match.group(2) or "").strip()
                    last_file = name
                    # 7z redraws on every write, which for a large archive is hundreds of events a second.
                    now = time.monotonic()
                    if now - last_sent < throttle and pct < 100:
                        continue
                    last_sent = now
                    report(f"{pct}%" + (f" — {Path(name).name}" if name else ""), stage=stage, progress=pct / 100, tool_file=name or last_file, tool_percent=pct)
            process.wait()
            # Checked before the exit code is read: a cancelled child exits on a signal, which looks exactly
            # like a crash, and reporting that would blame the tool for the user pressing Cancel.
            if ctx is not None and ctx.cancelled:
                self.logger.info("ORGANIZER", f"TOOL_CANCELLED stage=[{stage}]")
                raise CancellationError(f"{stage} cancelled")
            return process.returncode, " | ".join(tail)[-400:]
        finally:
            stop.set()
            self._stop_tool(process, grace=0.5)
            # One leaked pipe per conversion, and an overnight run is hundreds of conversions. Nothing else
            # closes this: the read loop only reaches EOF, which is not the same as releasing the descriptor.
            with contextlib.suppress(OSError):
                process.stdout.close()

    @staticmethod
    def _game_files(directory):
        """Every file a rebuild is built from, excluding the app's own lock marker.

        The marker has to sit directly in the staging folder, because that is what a sweep reads to tell an
        abandoned build from one still in flight. That leaves it otherwise indistinguishable from the game's
        own data: packed into the published archive, counted in the extracted byte total, and credited as an
        extracted file - where it would mask the loss of a real one, which is the only thing that check exists
        to catch. The marker also changes every run, so an archive carrying it is not reproducible.
        """
        try:
            items = list(Path(directory).rglob("*"))
        except OSError:
            return []
        return [item for item in items if item.name != LOCK_MARKER and item.is_file() and not item.is_symlink()]

    @staticmethod
    def _write_lock_marker(temp_dir):
        """Record which process owns this extraction folder, so a later scan can tell an abandoned folder
        from one a conversion is still writing into. SIGKILL skips cleanup, so these do get left behind."""
        try:
            (Path(temp_dir) / LOCK_MARKER).write_text(f"{os.getpid()} {time.time():.0f}\n", encoding="utf-8")
        except OSError:
            # A missing marker only costs us the pid check; the age fallback still applies.
            pass

    def _remove_tree(self, directory):
        """Deletes a staging or extraction folder and everything in it. Its own errors are swallowed: this
        runs on the failure path, where a locked or already-deleted file must not mask the original error."""
        try:
            for child in sorted(directory.rglob("*"), key=lambda item: len(item.parts), reverse=True):
                try:
                    child.unlink() if child.is_file() or child.is_symlink() else child.rmdir()
                except OSError:
                    pass
            directory.rmdir()
        except OSError:
            pass

    def sweep_stale_build_dirs(self, library_root=None, min_age_seconds=900):
        """Delete staging folders an earlier run abandoned, before a new conversion starts.

        A killed or cancelled run never reaches its own cleanup, and what it leaves is a folder of extracted
        game data and a half-written archive that was never verified and never published. Left alone it just
        occupies the disk until a person happens to notice it. It is safe to clear at this point because
        nothing is in flight yet, but two things are genuinely not ours to delete, so both are checked:

        - a folder whose lock marker names a process that is still alive and is not us, which is a conversion
          a second instance of this app is writing into right now;
        - a folder touched in the last few minutes, because a recycled pid can otherwise make a dead run look
          alive, and a run that has only just started must never be swept out from under itself.

        Returns (folders removed, bytes reclaimed).
        """
        if library_root is None:
            return 0, 0
        processing = Path(library_root).expanduser().resolve() / PROCESSING_DIRNAME
        if not processing.is_dir():
            return 0, 0
        removed = 0
        reclaimed = 0
        now = time.time()
        try:
            candidates = sorted(p for p in processing.iterdir() if p.is_dir() and p.name.startswith(TEMP_DIR_PREFIX))
        except OSError:
            return 0, 0
        for folder in candidates:
            if self._build_dir_is_live(folder, now, min_age_seconds):
                continue
            try:
                size = sum(item.stat().st_size for item in folder.rglob("*") if item.is_file())
            except OSError:
                size = 0
            self._remove_tree(folder)
            if folder.exists():
                self.logger.warning("ORGANIZER", f"STALE_BUILD_DIR_KEPT path=[{folder.name}] reason=[could not be removed]")
                continue
            removed += 1
            reclaimed += size
            self.logger.info("ORGANIZER", f"STALE_BUILD_DIR_REMOVED path=[{folder.name}] bytes={size}")
        if removed:
            self.logger.info("ORGANIZER", f"STALE_BUILD_DIR_SWEEP folders={removed} bytes={reclaimed}")
        return removed, reclaimed

    def _build_dir_is_live(self, folder, now, min_age_seconds):
        """True when a staging folder may still be in use, so it must not be swept."""
        try:
            age = now - folder.stat().st_mtime
        except OSError:
            return True
        if age < min_age_seconds:
            return True
        marker = folder / LOCK_MARKER
        try:
            pid = int(marker.read_text(encoding="utf-8").split()[0])
        except (OSError, ValueError, IndexError):
            return False
        if pid == os.getpid():
            return True
        return self._pid_is_alive(pid)

    @staticmethod
    def _pid_is_alive(pid):
        """Whether a process id still exists. Written per platform because the obvious check is wrong here.

        os.kill(pid, 0) is the portable idiom, but on Windows it raises a plain OSError for a pid that does
        not exist as well as for one that does, so treating any OSError as "alive" means a dead run's folder is
        never reclaimed - which is the whole case this sweep exists for.
        """
        if pid <= 0:
            return False
        if os.name == "nt":
            import ctypes

            # PROCESS_QUERY_LIMITED_INFORMATION is the least privilege that still answers "does this exist".
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _staging_dir(self, archive_path, library_root=None):
        """Creates the per-conversion staging folder this archive is built in, or returns None when there is
        no library root to stage under.

        Staging lives under the library root so the finished archive can be renamed into the game folder in
        one atomic step. When the root is unknown the caller falls back to building beside the source,
        because guessing a root that turned out to be one level too high would put the staging folder in the
        user's Downloads directory."""
        if library_root is None:
            return None
        try:
            processing = Path(library_root).expanduser().resolve() / PROCESSING_DIRNAME
            processing.mkdir(parents=True, exist_ok=True)
            job = tempfile.mkdtemp(prefix=f"{TEMP_DIR_PREFIX}-", dir=str(processing))
        except OSError as exc:
            self.logger.warning("ORGANIZER", f"ARCHIVE_STAGING_UNAVAILABLE path=[{archive_path.name}] error={type(exc).__name__} reason=[building beside the source instead]")
            return None
        self._write_lock_marker(Path(job))
        return Path(job)

    def cleanup_processing_dir(self, library_root=None):
        """Removes the library's Processing folder once nothing is staged in it, and reports whether it went.

        The folder is the app's own scratch area, so it is litter the moment the last conversion is done -
        an empty Processing/ in the library root is something the user has to notice and delete by hand.
        Removal is deliberately rmdir rather than rmtree: a folder that still has something in it holds either
        a staging folder abandoned by a killed run, which may be the only copy of a partially built archive, or
        a conversion a second instance of this app is writing into right now. rmdir fails harmlessly in both
        cases and the folder stays, which the next scan then reclaims (LibraryService.cleanup_leftovers).
        """
        if library_root is None:
            return False
        processing = Path(library_root).expanduser().resolve() / PROCESSING_DIRNAME
        try:
            processing.rmdir()
        except FileNotFoundError:
            return False
        except OSError as exc:
            self.logger.debug("ORGANIZER", f"PROCESSING_DIR_KEPT path=[{processing}] reason=[{type(exc).__name__}: not empty]")
            return False
        self.logger.info("ORGANIZER", f"PROCESSING_DIR_REMOVED path=[{processing}]")
        return True

    def _repack_with_official_name(self, archive, ctx=None, on_progress=None, zip_password="", library_root=None):
        """Right before an accepted archive is moved into its final folder: if a generic 'game' content
        folder is found inside (as opposed to an installer layout or a bare .iso that needs mounting), rename
        it to the verified Steam title, so the extracted folder is already named correctly for the player.
        Every .zip and .rar is converted to .7z. An existing .7z is only rebuilt when a generic content
        folder needs renaming. Uses the free '7z'/'7za' tool (p7zip - the same engine PeaZip itself is built
        on) for all output, since RAR compression is proprietary and cannot produce the requested .7z
        format. Safely leaves the source unchanged if 7z is unavailable. Extracts/repacks one archive fully, including
        cleanup, before returning, so only one temporary extraction ever exists on disk at a time."""
        path = archive.path
        suffix = path.suffix.lower()
        note = getattr(archive, "conversion", None)
        if suffix not in (".zip", ".rar", ".7z"):
            if note:
                note.status = "not_needed"
                note.source_format = suffix.lstrip(".").upper()
                note.final_name = path.name
            return path

        def report(message, stage="working", **extra):
            # Progress is reported as a structured record so the UI can show what is happening to which file
            # (stage, source format, sizes) instead of a single overwritable sentence.
            if on_progress:
                on_progress({"message": message, "stage": stage, "file": path.name, "source_suffix": suffix, **extra})

        # Callers pass a list of candidates collected up front, so this archive can be converted by something
        # else - an Organize run in the same app, or a second repair pass - before this one reaches it. The
        # source is then simply gone, and stat() below would raise FileNotFoundError that surfaced as a red
        # "failed" for a conversion that had in fact already succeeded. Report it as resolved instead.
        if not path.exists():
            self.logger.info("ORGANIZER", f"ARCHIVE_ALREADY_RESOLVED path=[{path.name}]")
            report(f"{path.name} was already converted elsewhere", stage="skipped", message_text="Already converted by another run before this pass reached it", progress=1.0)
            if note:
                note.status = "skipped"
                note.message = "Already converted by another run"
                note.source_format = suffix.lstrip(".").upper()
                note.final_name = path.name
            return path
        if not self.convert_archives:
            # Enforced here rather than at each caller, because conversion is the destructive act and this is
            # the one place every route through it passes: the repair pass and move() both land here. The
            # archive is still moved and renamed into its folder, it is simply not rebuilt.
            self.logger.info("ORGANIZER", f"CONVERSION_DISABLED path=[{path.name}]")
            message = f"Left as {suffix.lstrip('.').upper()} — conversion is turned off"
            report(message, stage="skipped", message_text="ZIP/RAR conversion is turned off in settings", progress=1.0)
            if note:
                note.status = "skipped"
                note.message = "Conversion is turned off in settings"
                note.source_format = suffix.lstrip(".").upper()
                note.final_name = path.name
            return path
        sevenzip, _reason = ExtractService.find_tool()
        if not sevenzip:
            report(f"Conversion skipped for {path.name}: 7z/7za is unavailable", stage="skipped")
            # Logged every time so skipped conversions are diagnosable from the log.
            self.logger.warning("ORGANIZER", f"ARCHIVE_TOOLS_MISSING path=[{path.name}] reason=[7z/7za not found on PATH; archive left unchanged]")
            if note:
                note.status = "skipped"
                note.message = "7z/7za not installed, so the file was left as-is"
                note.source_format = suffix.lstrip(".").upper()
                note.final_name = path.name
            return path
        if not self._source_is_intact(path):
            report(f"{path.name} is not a complete archive; left unchanged", stage="failed", message_text="this archive did not pass an integrity test, so it was left as it is rather than converted")
            if note:
                note.status = "failed"
                note.message = "Archive failed its integrity test, so it was left unchanged"
                note.source_format = suffix.lstrip(".").upper()
                note.final_name = path.name
                note.final_size = path.stat().st_size
                note.source_size = path.stat().st_size
            return path
        # A password-protected zip cannot be extracted, so it is unlocked here - after the integrity test
        # above has confirmed the source is worth spending time on. The unlock used to run in the
        # controller before move() was called, which meant it ran before this verify step: a corrupt or
        # missing file was being decrypted and rewritten for nothing, and the rewrite was what the
        # integrity test was then failing on. The password is '123', the standard FitGirl/repack value.
        if suffix == ".zip" and self.convert_archives:
            try:
                if self._unlock_zip(path, ctx):
                    self.logger.info("ORGANIZER", f"ZIP_UNLOCKED_AFTER_VERIFY path=[{path.name}]")
            except CancellationError:
                raise
            except Exception as exc:
                self.logger.warning("ORGANIZER", f"ZIP_UNLOCK_FAILED path=[{path.name}] error={type(exc).__name__}")
        # Only one thing can make an archive worth rebuilding: renaming the generic content folder inside it
        # to the official Steam name, and that is guarded by the game having matched Steam at all. An archive
        # with no match can never be renamed, so no rebuild is possible whatever is inside it - which makes
        # the extraction above pure waste. It ran anyway, so every unmatched .7z in the library was read in
        # full by 7z t, written out to staging in full, and then deleted with `return path` a few lines later.
        # Hours of I/O per run to change no file, and on a volume short of space the extraction failed and the
        # game was filed as broken: "7z could not extract this archive", for an archive never being touched.
        if suffix == ".7z" and not (archive.steam.found and archive.steam.name):
            report(f"{path.name} is already a .7z and has no Steam name to rebuild it with; left unchanged", stage="skipped", message_text="this game has no Steam match, so there is no official name to rebuild the archive with")
            if note:
                note.status = "not_needed"
                note.message = "Already a .7z, and with no Steam match there is no official name to rebuild it with"
                note.source_format = "7Z"
                note.final_name = path.name
                note.final_size = path.stat().st_size
                note.source_size = path.stat().st_size
            return path
        # A .7z whose content folder is already named correctly needs no rebuild at all. Listing the
        # archive's index is a single read of the header - seconds, not the hours the full extract and
        # rebuild take - and when the top-level folder already matches the official Steam name there
        # is nothing to do. Every .7z in the library used to be extracted in full, rebuilt, verified,
        # and replaced on every run regardless, which is what made a scan of an already-converted
        # library take hours to change no file.
        if suffix == ".7z" and archive.steam.found and archive.steam.name:
            existing = self._content_folder_name(path)
            if existing and self._safe_name(archive.steam.name) == self._safe_name(existing):
                report(f"{path.name} is already a .7z with the right content folder name; left unchanged", stage="skipped", message_text="this archive is already a .7z and the folder inside it is already named correctly")
                if note:
                    note.status = "not_needed"
                    note.message = "Already a .7z and the content folder is already named correctly"
                    note.source_format = "7Z"
                    note.final_name = path.name
                    note.final_size = path.stat().st_size
                    note.source_size = path.stat().st_size
                return path
        temp_dir = None
        build_target = None
        staging_dir = None
        try:
            source_bytes = path.stat().st_size
            report(f"Extracting {path.name}", stage="extracting", source_bytes=source_bytes, source_suffix=suffix)
            original_stat = path.stat()
            # Everything this conversion writes lives in one staging folder under the library root, which is on
            # the same volume as the game folder, so both halves of the work - the multi-GB extraction and the
            # rebuilt archive - are off the shelf while they run. The game folder then holds exactly one thing
            # for the whole run: its untouched source. Extracting in there used to put several GB of loose
            # files inside the game folder, where a scan could offer a nested archive as its own game and where
            # Syncthing replicated the working set. Never the system temp dir either: %TEMP% is small and
            # frequently a slow disk, and filling it aborted the conversion with a bare OSError.
            staging_dir = self._staging_dir(path, library_root)
            temp_dir = staging_dir if staging_dir is not None else Path(tempfile.mkdtemp(prefix=TEMP_DIR_PREFIX, dir=str(path.parent)))
            self._write_lock_marker(temp_dir)
            if ctx:
                ctx.checkpoint()
            extractor = "7z"
            # Info-ZIP unzip cannot read WinZip AES archives (compression method 99), which is what the
            # password-protected game zips in this library actually are, and it cannot be given the password
            # non-interactively either - it exited 81 having written nothing. 7-Zip reads AES and accepts -p,
            # and it is already required below to build the .7z, so it handles every format here.
            unrar = ExtractService.find_unrar()
            if suffix == ".rar" and unrar:
                extractor = "unrar"
                args = [unrar, "x", "-y", "-o+"]
                if zip_password:
                    args.append(f"-p{zip_password}")
                args += [str(path), f"{temp_dir}{os.sep}"]
            else:
                extractor = "7z"
                # -bsp1 is what makes 7z emit a redrawable percentage for this stage; without a multi-GB
                # extract is a silent wait and the UI has nothing truthful to show.
                args = [sevenzip, "x", "-y", "-bsp1", f"-o{temp_dir}"]
                if zip_password:
                    args.append(f"-p{zip_password}")
                args.append(str(path))
            extract_code, detail = self._run_tool(args, "extracting", report, ctx=ctx)
            # unrar's exit code 9 means "errors occurred during extraction" - some files failed, others
            # succeeded. It is not a fatal error and the archive is not corrupt: a repack's _INSTALL
            # TUTORIAL.txt that unrar cannot open for a reason of its own produces exit 9 with 99% of the
            # game extracted fine. Treating every non-zero exit as a failure turned a working conversion
            # into a left-unchanged source, which is what Ale Abbey was. The completeness check below
            # stands between a lossy extraction and a destroyed game, so exit 9 is allowed through and
            # only fails when the extracted content is genuinely short of what the archive declared.
            if extract_code != 0 and not (extractor == "unrar" and extract_code == 9):
                # Extraction used to fail silently and leave the source as .zip/.rar with nothing in the log,
                # which is why a stalled conversion was impossible to diagnose. Always record the exit code,
                # the tool, and the tool's own output.
                detail = re.sub(r"\s+", " ", detail)[:400]
                self.logger.warning("ORGANIZER", f"ARCHIVE_EXTRACT_FAILED path=[{path.name}] extractor=[{extractor}] exit={extract_code} detail=[{detail or 'no output'}]")
                report(f"Could not extract {path.name}; left unchanged", stage="failed", message_text=f"{extractor} could not extract this archive (exit {extract_code})", progress=1.0)
                if note:
                    note.status = "failed"
                    note.message = f"{extractor} could not extract this archive (exit {extract_code})"
                    note.source_format = suffix.lstrip(".").upper()
                    note.final_name = path.name
                return path
            if extractor == "unrar" and extract_code == 9:
                detail = re.sub(r"\s+", " ", detail)[:400]
                self.logger.info("ORGANIZER", f"ARCHIVE_EXTRACT_WARN path=[{path.name}] extractor=[unrar] exit=9 detail=[{detail or 'no output'}]")
            extracted_bytes = sum(item.stat().st_size for item in self._game_files(temp_dir))
            # The original is still on disk here, which is the only moment a lossy extraction can still be
            # caught. A rebuild of a partial extraction is internally valid, passes `7z t`, and is then
            # published while the intact source is deleted - an unrecoverable loss of the game. Comparing the
            # archive's own index against what landed on disk is what stands between the two.
            game_files = list(self._game_files(temp_dir))
            if self._extraction_is_short(path, temp_dir, game_files=game_files):
                report(f"Extraction of {path.name} was incomplete; left unchanged", stage="failed", message_text="this archive did not extract completely, so it was left as it is rather than replaced")
                if note:
                    note.status = "failed"
                    note.message = "Extraction was incomplete, so the original was left unchanged"
                    note.source_format = suffix.lstrip(".").upper()
                    note.final_name = path.name
                    note.final_size = original_stat.st_size
                    note.source_size = original_stat.st_size
                shutil.rmtree(temp_dir, ignore_errors=True)
                return path
            has_iso = any(item.suffix.lower() == ".iso" for item in game_files)
            renamed = False
            if not has_iso and archive.steam.found and archive.steam.name:
                content_folder = self._find_generic_content_folder(temp_dir)
                if content_folder is not None:
                    new_folder = content_folder.with_name(self._safe_name(archive.steam.name))
                    if new_folder != content_folder and not new_folder.exists():
                        content_folder.rename(new_folder)
                        renamed = True
                        self.logger.info("ORGANIZER", f"RENAMED_CONTENT_FOLDER source=[{content_folder.name}] target=[{new_folder.name}]")
            if suffix == ".7z" and not renamed:
                # Terminal stage, so the run's stage timeline and conversion count close for this archive.
                # This branch used to return without reporting anything, leaving the organize view showing
                # EXTRACTING for a game that had finished - and if it was the last game, a run that ended
                # looking hung.
                report(f"{path.name} is already a .7z and its content folder is already named correctly", stage="skipped", message_text="this archive is already a .7z with the right folder name inside it")
                if note:
                    note.status = "not_needed"
                    note.message = "Already a .7z and the content folder is already named correctly"
                    note.source_format = "7Z"
                    note.final_name = path.name
                    note.final_size = original_stat.st_size
                    note.source_size = original_stat.st_size
                return path
            # All newly built archives use 7z, including conversions from zip and rar.
            packer = "7z"
            target_suffix = ".7z"
            # The replacement is built in the staging folder, not in the game folder. A .rar -> .7z conversion
            # used to write straight to the final "Name.7z", so a build interrupted part-way left a partial
            # archive wearing the real name; dedupe then preferred that partial file over the intact .rar and
            # archived the good copy, leaving the folder with an unusable stub - which is how Trampoline Tornado lost
            # its game from the shelf. Staging outside the game folder means a folder being converted holds
            # only its source until a verified replacement is ready to be renamed in. The folder already exists
            # by now: the extraction above ran inside it.
            # The name inside staging is irrelevant to the shelf: only final_name below is ever published.
            build_target = staging_dir / path.with_suffix(target_suffix).name if staging_dir is not None else path.with_name(f"{path.stem}{TEMP_FILE_TAG}.{os.getpid()}{target_suffix}")
            final_name = path.name if suffix == target_suffix else path.with_suffix(target_suffix).name
            if suffix != target_suffix:
                n = 2
                while (path.parent / final_name).exists():
                    final_name = path.with_name(f"{path.stem} ({n}){target_suffix}").name
                    n += 1
            if ctx:
                ctx.checkpoint()
            # Memory, not speed, is the binding constraint: an LZMA2 level 9 match finder needs ~2.5 GB on its own,
            # and v9.0 pinned -mx=9 unconditionally. Against anything else running that means swap
            # exhaustion and a build killed mid-write, throwing away a multi-GB extraction for nothing. So
            # the level is chosen per archive against real headroom, and still downgraded if a build dies
            # anyway, which is what turned a single failure into a lost archive.
            level = self._choose_compression_level()
            # Logged because "maximum compression" is the goal, and a silently stepped-down level would
            # otherwise look like a successful run that quietly left space on the table.
            self.logger.info("ORGANIZER", f"COMPRESS_LEVEL path=[{path.name}] level={level}")
            report(f"Compressing {path.name} to .7z at level {level}", stage="compressing", source_bytes=source_bytes, extracted_bytes=extracted_bytes, level=level, source_suffix=suffix)
            # Files Windows Defender refused to scan on the previous attempt. Each is added to the -xr!
            # exclusion list so the build is retried without it; the loop exits when the build succeeds,
            # when the flagged set stops growing, or when 7z exits 1 with a written target - in which
            # case the flagged files were skipped but the archive is still usable.
            exclusions = []
            while True:
                # The repack failure mode is Windows Defender's content-intelligence integration: 7z asks
                # Defender to scan every file as it packs, and a file Defender flags - a launcher or a DLL
                # from a repack - is reported as "Operation did not complete successfully because the
                # file contains a virus or potentially unwanted software" with exit 1, which the run then
                # reports as a build failure for a game that was extracted fine. The fix is to exclude
                # the offending files from the build rather than disabling the scan: -mci=off breaks 7z on
                # valid archives (exit 2, "The parameter is incorrect"), so it cannot be used. The flagged
                # names are parsed out of the error and fed back as -xr! exclusions, so a build that fails
                # once on Defender is retried without the file(s) Defender refused.
                pack_cmd = [sevenzip, "a", "-t7z", f"-mx={level}", "-bsp1", f"-xr!{LOCK_MARKER}"]
                for exclude in exclusions:
                    pack_cmd.append(f"-xr!{exclude}")
                if COMPRESSION_THREADS > 0:
                    pack_cmd.append(f"-mmt={COMPRESSION_THREADS}")
                # stdin is closed on purpose: if 7z ever decides to prompt (a password-protected entry, a
                # name collision), it must fail fast rather than block the whole overnight run on a tty read.
                pack_code, detail = self._run_tool(pack_cmd + [str(build_target), "."], "compressing", report, cwd=str(temp_dir), ctx=ctx)
                if pack_code == 0:
                    break
                detail = re.sub(r"\s+", " ", detail)[:400]
                if level > MIN_COMPRESSION_LEVEL and self._looks_like_resource_failure(detail):
                    self.logger.warning("ORGANIZER", f"COMPRESS_LEVEL_DOWNGRADED path=[{path.name}] level={level} next={level - 1} detail=[{detail or 'no output'}]")
                    try:
                        build_target.unlink()
                    except OSError:
                        pass
                    level -= 1
                    continue
                flagged = self._defender_flagged(detail)
                if flagged:
                    before = len(exclusions)
                    exclusions = sorted(set(exclusions) | set(flagged))
                    if len(exclusions) > before:
                        self.logger.warning("ORGANIZER", f"COMPRESS_EXCLUDES_ADDED path=[{path.name}] files={len(flagged)} total={len(exclusions)}")
                        continue
                # 7z exits 1 with "WARNING: Cannot open some files" when Defender refuses to scan a
                # file during the build. The archive is still written - the flagged files are skipped,
                # not the whole build - so a build that exits 1 with a Defender warning and leaves a
                # non-empty target is a partial success, not a failure. The verification step below
                # catches the case where the skipped files were the whole game.
                if pack_code == 1 and build_target.is_file() and build_target.stat().st_size > 0:
                    self.logger.warning("ORGANIZER", f"COMPRESS_WARN_EXIT1 path=[{path.name}] detail=[{detail}]")
                    break
                raise OSError(f"{packer} build exited {pack_code}" + (f": {detail}" if detail else ""))
            report(f"Verifying {build_target.name}", stage="verifying", source_suffix=suffix)
            # Testing the rebuilt archive reads every byte of it, which for a multi-GB build is another long
            # silent wait. It went through subprocess.run(), which cannot be interrupted, so Cancel appeared to
            # hang here. The same watcher used for the extract and pack stages covers it.
            verify = subprocess.Popen([sevenzip, "t", str(build_target)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
            verify_stop = self._watch_cancel(verify, ctx)
            try:
                while verify.poll() is None:
                    if ctx is not None and ctx.cancelled:
                        raise CancellationError("verification cancelled")
                    time.sleep(0.05)
            finally:
                verify_stop.set()
                self._stop_tool(verify, grace=0.5)
            if verify.returncode != 0:
                raise OSError(f"rebuilt archive verification failed (exit {verify.returncode})")
            try:
                os.utime(build_target, (original_stat.st_atime, original_stat.st_mtime))
            except OSError as metadata_error:
                self.logger.warning("ORGANIZER", f"ARCHIVE_METADATA_RESTORE_FAILED path=[{build_target.name}] error={type(metadata_error).__name__}")
            final_path = path.parent / final_name
            if suffix == target_suffix:
                os.replace(build_target, path)
                final_path = path
                self.logger.info("ORGANIZER", f"ARCHIVE_REBUILT_WITH_RENAME path=[{path.name}] format=[{target_suffix}]")
            else:
                # Publish first, delete the source second. The other order can destroy the only copy: if the
                # replace fails after an unlink, the game is gone with nothing in its place.
                os.replace(build_target, final_path)
                try:
                    path.unlink()
                except OSError as exc:
                    # Two copies where there was one is recoverable; a deleted source and no output is not.
                    self.logger.warning("ORGANIZER", f"SOURCE_REMOVE_FAILED source=[{path.name}] error={type(exc).__name__} converted=[{final_path.name}]")
                self.logger.info("ORGANIZER", f"ARCHIVE_REPACKED source=[{path.name}] target=[{final_path.name}] format=[{target_suffix}]")
            # source_bytes belongs on this event. Only the extracting and compressing events carried it, and
            # the running saved-space total is computed from the completion event alone, so a total built from
            # this line was always zero no matter how much space a conversion actually freed.
            report(f"Converted to {final_path.suffix.lstrip('.').upper()}: {final_path.name}", stage="converted", source_bytes=source_bytes, target_bytes=final_path.stat().st_size, target_name=final_path.name, source_format=suffix.lstrip(".").upper(), target_format=target_suffix.lstrip(".").upper(), level=level)
            if note:
                note.status = "rebuilt" if suffix == target_suffix else "converted"
                note.source_format = suffix.lstrip(".").upper()
                note.target_format = final_path.suffix.lstrip(".").upper()
                note.final_name = final_path.name
                note.final_size = final_path.stat().st_size
                note.source_size = original_stat.st_size
                if renamed:
                    note.message = f"Content folder renamed to {self._safe_name(archive.steam.name) or final_path.stem}"
            return final_path
        except CancellationError:
            raise
        except Exception as exc:
            report(f"Conversion failed for {path.name}: {str(exc)[:240]}", stage="failed", message_text=str(exc)[:240])
            # The message and free space are the two facts that actually explain a failed conversion; logging
            # only the exception type made these look identical and unactionable in the log.
            free_bytes = 0
            try:
                free_bytes = shutil.disk_usage(path.parent).free
            except OSError:
                pass
            self.logger.warning("ORGANIZER", f"ARCHIVE_REPACK_FAILED path=[{path.name}] error={type(exc).__name__} message=[{str(exc)[:500]}] free_bytes=[{free_bytes}] stage=[repack]")
            if note:
                note.status = "failed"
                note.message = str(exc)[:300] or type(exc).__name__
                note.source_format = suffix.lstrip(".").upper()
                note.final_name = path.name
                note.free_bytes_at_failure = free_bytes
            if build_target and build_target != path and build_target.exists():
                try:
                    build_target.unlink()
                except OSError:
                    pass
            return path
        finally:
            # One folder held the extraction and the build, so one sweep takes both. A caller with no library
            # root to stage under falls back to a hidden folder beside the source, which is swept the same way.
            if temp_dir:
                for child in sorted(temp_dir.rglob("*"), key=lambda item: len(item.parts), reverse=True):
                    try:
                        child.unlink() if child.is_file() or child.is_symlink() else child.rmdir()
                    except OSError:
                        pass
                try:
                    temp_dir.rmdir()
                except OSError:
                    pass
            if staging_dir:
                self._remove_tree(staging_dir)
                # Last conversion out, so this is the moment the library has no use for the scratch area.
                # Done here rather than only at the end of the run so a cancel, a crash, or a rollback still
                # leaves the library root as it found it.
                self.cleanup_processing_dir(library_root)

    def preview(self, archives, destination):
        groups = {}
        for archive in archives:
            if archive.decision.accepted:
                groups.setdefault(archive.identity_key, []).append(archive)
        changes = []
        for group in groups.values():
            primary = max(group, key=self._promotion_key)
            changes.append((primary.path, Path(destination) / primary.decision.category / self._game_name(primary) / primary.path.name))
            for old in group:
                if old is not primary:
                    changes.append((old.path, Path(destination) / "Archive" / old.path.name))
        return changes

    def move(self, archive, destination, on_progress=None):
        destination = Path(destination).expanduser().resolve()
        category = self._safe_name(canonical_category((archive.decision.category or "Unsorted").strip() or "Unsorted"))
        category_dir = destination / category
        category_dir.mkdir(parents=True, exist_ok=True)
        game_dir = self._unique_dir(category_dir, self._game_name(archive))
        # Whether this run is the one that made the folder. Only then may a failed move take it away again: a
        # folder that was already there belongs to the user, empty or not.
        created_dir = not game_dir.is_dir()
        game_dir.mkdir(exist_ok=True)
        archive.created_game_dir = created_dir
        source = archive.path
        target = game_dir / archive.path.name
        try:
            shutil.move(str(source), str(target))
        except Exception:
            # shutil.move does not give up when a rename fails - it falls back to copy-then-unlink. On a file the
            # user has open in Explorer the copy succeeds and the unlink then fails too, so the run reports the
            # file as unmoved while a complete duplicate of it is already sitting in the category folder. The next
            # run finds that copy and treats the game as organized, with the real archive still at the root. An
            # orphan is only a duplicate while the original is still there, hence the source check.
            try:
                if target.exists() and source.exists():
                    # The fallback copies with copy2, which carries the read-only attribute across, so on the
                    # read-only files that provoke this in the first place the orphan cannot be unlinked until
                    # the flag is cleared. Leaving it would keep the duplicate that starts the next run wrong.
                    try:
                        os.chmod(str(target), 0o666)
                    except OSError:
                        pass
                    target.unlink()
            except OSError:
                pass
            if created_dir:
                try:
                    # The folder is made before the move so the archive has somewhere to land, so a move that
                    # fails outright leaves a folder behind holding whatever it managed to write. When this run
                    # is what created the folder, everything in it belongs to this move, so it goes as a whole
                    # rather than entry by entry - repeated failures would otherwise fill a category with
                    # nameless folders that no scan will ever report.
                    shutil.rmtree(game_dir, ignore_errors=True)
                except OSError:
                    pass
            raise
        archive.path = target
        # Recorded the moment the file lands rather than when this method returns. Everything below the repack
        # can still fail - a locked archive, a metadata write - and a failure there has to leave a record the
        # run can roll back. Setting this only on the way out meant a partial move was invisible: the run rolled
        # every earlier game back to the library root and left this one sitting in its category folder, so the
        # library ended up half-organized with nothing on the screen saying so.
        archive.organized_path = target
        # Repack/rename only after the archive is already safely in its final folder: organizing is the
        # critical step and must complete regardless of whether the best-effort RAR conversion succeeds. The
        # conversion setting is enforced inside _repack_with_official_name, so this call is safe either way.
        # The zip password "123" was hardcoded here; it now comes from DEFAULT_ZIP_PASSWORD in core.constants.
        archive.path = self._repack_with_official_name(archive, on_progress=on_progress, zip_password=DEFAULT_ZIP_PASSWORD, library_root=destination)
        target = archive.path
        archive.organized_path = target
        prefix = self._asset_prefix(archive)
        if archive.artwork.path and archive.artwork.path.is_file():
            shutil.copy2(str(archive.artwork.path), str(game_dir / f"{prefix}_grid{archive.artwork.path.suffix}"))
        if archive.artwork.assets:
            for name, path in archive.artwork.assets.items():
                if path.is_file():
                    shutil.copy2(str(path), str(game_dir / f"{prefix}_{name}{path.suffix}"))
        self.write_steam_links(game_dir, archive.steam.appid, self._asset_prefix(archive))
        self.write_metadata(game_dir, archive)
        self._remove_generated_source_folder(source, destination)
        self.logger.info("ORGANIZER", f"MOVE source=[{source}] destination=[{target}]")
        archive.organized_path = target
        return target

    def archive_file(self, source, destination, note=None):
        source = Path(source)
        archive_dir = Path(destination).expanduser().resolve() / "Archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        target = archive_dir / source.name
        n = 2
        while target.exists():
            target = archive_dir / f"{source.stem} ({n}){source.suffix}"
            n += 1
        shutil.move(str(source), str(target))
        self._remove_generated_source_folder(source, destination)
        self.logger.info("ORGANIZER", f"ARCHIVE_OLD source=[{source}] destination=[{target}]")
        # Filing a duplicate into Archive/ is a completed outcome, not outstanding work. Recording it
        # explicitly keeps the Done screen from reporting this archive as a still-pending conversion,
        # which is what happened when the note was simply left at its default status.
        if note is not None:
            note.status = "archived"
            note.message = "Filed under Archive/ as a duplicate of the same game"
            note.source_format = source.suffix.lstrip(".").upper()
            note.final_name = target.name
            note.final_size = target.stat().st_size if target.exists() else 0
        return target
