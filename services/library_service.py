from pathlib import Path
import glob as globmod
import fnmatch
import json
import os
import re
import shutil
import time
# Imports split one per line for GitHub readability.
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.constants import ARCHIVE_EXTENSIONS, LOCK_MARKER, LIBRARY_RESERVED_DIRS, TEMP_DIR_PREFIX, TEMP_FILE_TAG, ENTRY_POINT
from core.exceptions import CancellationError
from core.path_safety import DeletionGuard, is_within
from core.models import ConversionResult
from utils.filename_utils import identity_key
from utils.treewalk import is_link

# Leftovers this app can create when a conversion is killed mid-run (power loss, OOM, cancel). All are named
# with a marker that cannot collide with real game content, so cleanup can remove them safely.
OWN_TEMP_DIRS = (".organizer-repack-", ".organizer-unzip-")
OWN_TEMP_FILES = (".organizer-temp",)
OWN_TEMP_FILE_PREFIX = ".organizer-zip-"


def _is_app_folder(folder):
    r"""True when this folder is the app's own project folder rather than a game category.

    The library root is the app's own project folder when the app is installed there, which is the
    default: `D:\Game Installers\0. Steam Game Organizer` sits inside the library root, and every
    scan picked it up as a category of one game - the app itself. The entry-point filename is the
    one thing that identifies the project regardless of what the folder is called, so the check
    looks for it rather than for a folder name: renaming the project folder no longer re-adds it
    to the catalog.

    Direct children of the project folder are the app's runtime and tooling, not game content.
    The bundled `runtime` folder is the one that mattered: it holds no archives, but it holds
    `python.exe`, `pythonw.exe`, the stdlib under `Lib`, the Tcl interpreter under `tcl`, and the
    vcruntime DLLs, so discovery walked it as a category of one game and listed its `.py`,
    `.pyc`, `.dll`, `.msg`, `.enc` and `.tm` files as archives. Checking for the interpreter
    rather than naming the folder keeps the rule anchored to what the app actually ships.
    """
    folder = Path(folder)
    if (folder / ENTRY_POINT).is_file():
        return True
    return (folder / "python.exe").is_file() and (folder.parent / ENTRY_POINT).is_file()


# Files this app writes into an organized game folder, by exact name. A folder holding only these and
# app-shaped artwork is the app's to remove when the game leaves. Kept here rather than in
# OrganizerService so the leftover sweep and the undo can agree on what counts as ours.
RECOGNISED_FOLDER_FILES = frozenset({".game-info.json", "Open Steam Page.html", "Open Steam Page.desktop", "Open Steam Page in Chrome.desktop", "Open Steam Page (Steam Deck).desktop"})
# Artwork, by suffix rather than by the exact name it was written under. move() copies the primary in as
# `<title>_grid.jpg` and each asset as `<title>_<asset>.<ext>`, so the title and the asset name both vary
# per game; the suffix is the part that says what the file is, and the underscore in the stem is what
# separates the title from the asset name once the name is a path.
RECOGNISED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

# Files that are safe to ignore when determining if a game folder can be pruned
# (OS-generated files, thumbnails, etc. that don't indicate user content)
IGNORED_FILES_IN_SWEEP = frozenset(
    {
        "Thumbs.db",
        "ehthumbs_vista.db",
        ".DS_Store",
        "desktop.ini",
        "Thumbs",
        "folder.jpg",
        "folder.jpeg",
        "folder.png",
        "folder.webp",
        "folder.gif",
        "folder.bmp",
        "folder.tif",
        "folder.tiff",
        "Folder.jpg",
        "Folder.jpeg",
        "Folder.png",
        "Folder.webp",
        "Folder.gif",
        "Folder.bmp",
        "Folder.tif",
        "Folder.tiff",
        "cover.jpg",
        "cover.jpeg",
        "cover.png",
        "cover.webp",
        "cover.gif",
        "cover.bmp",
        "cover.tif",
        "cover.tiff",
        "Cover.jpg",
        "Cover.jpeg",
        "Cover.png",
        "Cover.webp",
        "Cover.gif",
        "Cover.bmp",
        "Cover.tif",
        "Cover.tiff",
        "label.jpg",
        "label.jpeg",
        "label.png",
        "label.webp",
        "label.gif",
        "label.bmp",
        "label.tif",
        "label.tiff",
        "Label.jpg",
        "Label.jpeg",
        "Label.png",
        "Label.webp",
        "Label.gif",
        "Label.bmp",
        "Label.tif",
        "Label.tiff",
        "banner.jpg",
        "banner.jpeg",
        "banner.png",
        "banner.webp",
        "banner.gif",
        "banner.bmp",
        "banner.tif",
        "banner.tiff",
        "Banner.jpg",
        "Banner.jpeg",
        "Banner.png",
        "Banner.webp",
        "Banner.gif",
        "Banner.bmp",
        "Banner.tif",
        "Banner.tiff",
        "thumb.jpg",
        "thumb.jpeg",
        "thumb.png",
        "thumb.webp",
        "thumb.gif",
        "thumb.bmp",
        "thumb.tif",
        "thumb.tiff",
        "Thumb.jpg",
        "Thumb.jpeg",
        "Thumb.png",
        "Thumb.webp",
        "Thumb.gif",
        "Thumb.bmp",
        "Thumb.tif",
        "Thumb.tiff",
        "thumbnail.jpg",
        "thumbnail.jpeg",
        "thumbnail.png",
        "thumbnail.webp",
        "thumbnail.gif",
        "thumbnail.bmp",
        "thumbnail.tif",
        "thumbnail.tiff",
        "Thumbnail.jpg",
        "Thumbnail.jpeg",
        "Thumbnail.png",
        "Thumbnail.webp",
        "Thumbnail.gif",
        "Thumbnail.bmp",
        "Thumbnail.tif",
        "Thumbnail.tiff",
        "art.jpg",
        "art.jpeg",
        "art.png",
        "art.webp",
        "art.gif",
        "art.bmp",
        "art.tif",
        "art.tiff",
        "Art.jpg",
        "Art.jpeg",
        "Art.png",
        "Art.webp",
        "Art.gif",
        "Art.bmp",
        "Art.tif",
        "Art.tiff",
        "poster.jpg",
        "poster.jpeg",
        "poster.png",
        "poster.webp",
        "poster.gif",
        "poster.bmp",
        "poster.tif",
        "poster.tiff",
        "Poster.jpg",
        "Poster.jpeg",
        "Poster.png",
        "Poster.webp",
        "Poster.gif",
        "Poster.bmp",
        "Poster.tif",
        "Poster.tiff",
    }
)


def _game_folder_is_prunable(folder):
    """Whether a game subfolder holds only things this app wrote there.

    A game folder is the player's too - a screenshot or a downloaded manual ends up beside the game - and
    there is nothing in a suffix that separates that from the artwork the app wrote. So the artwork
    accepted here has to carry the shape the organizer writes, <title>_grid.jpg and <title>_<asset>.<ext>,
    and an underscore in the stem is what that looks like once the name is a path. Anything else - a save
    file, a mod, a second archive - keeps the folder, because the sweep is for the game that left, not for
    the player's own files.
    """
    try:
        entries = list(Path(folder).iterdir())
    except OSError:
        return False
    for item in entries:
        if item.is_symlink() or not item.is_file():
            return False
        if item.name in RECOGNISED_FOLDER_FILES:
            continue
        if item.name in IGNORED_FILES_IN_SWEEP:
            continue
        if item.suffix.lower() in RECOGNISED_IMAGE_SUFFIXES and "_" in item.stem:
            continue
        return False
    return True


# Syncthing leftovers, matched by name. Only the documented Syncthing naming is listed here - earlier drafts
# included ".~lock.*", which is a LibreOffice/KDE convention and has nothing to do with Syncthing.
#
# Verified on this machine: .stfolder exists in the library root. No other Syncthing artifact is present, so
# the exact name of a past failure could not be confirmed. If Syncthing leaves a differently named temp file
# for this setup, add its name to SYNC_FILE_PATTERNS below rather than guessing a wildcard that could match
# real content. Cleanup only ever removes files matching these names, and only once they are older than the
# grace period, so an unrecognised leftover is left alone rather than risking game data.
SYNC_FILE_PATTERNS = ("*sync-conflict-*", "*.syncthing.*.tmp", ".syncthing.*", "*.sync-conflict-*.*", "~syncthing~*.tmp")
# Never touched: Syncthing's folder marker, its version history, and its ignore file.
SYNC_NEVER_TOUCH = (".stfolder", ".stversions", ".stignore")

APPID_PATTERN = re.compile(r"app/(\d+)")


class LibraryService:
    """Audits the already-organized library on every scan (regardless of All/New Only) so Steam link files
    stay normalized and artwork keeps getting refreshed for every game, not just newly discovered archives."""

    # What one audited folder can turn out to be. A string rather than a bool because every one of these reads
    # differently to a user, and the screen used to report the same words for four of them.
    AUDIT_NO_APPID = "no_appid"
    AUDIT_WRITTEN = "written"
    AUDIT_UP_TO_DATE = "up_to_date"
    AUDIT_UNAVAILABLE = "unavailable"
    # What a folder would do under a real scan, reported by a preview that rewrites nothing. Distinct from
    # AUDIT_WRITTEN so a caller cannot read a preview outcome as a record of work done.
    AUDIT_WOULD_REFRESH = "would_refresh"
    AUDIT_SKIP_ARTWORK = "skip_artwork"
    # One shape for every return, including the two bail-outs. They used to hand back a two-key dict while
    # the real return had three, so whether summary['no_artwork'] existed depended on whether the library
    # root happened to be there. Every caller uses .get(), which is what let the difference go unnoticed.
    EMPTY_AUDIT = {"checked": 0, "refreshed": 0, "no_artwork": 0}
    # The wording each outcome is reported with. Kept beside the constants so the progress line and the counter
    # cannot disagree about what a value means - which is how "refreshed" came to cover a folder holding nothing.
    AUDIT_TEXT = {
        AUDIT_NO_APPID: "no Steam AppID — nothing to refresh",
        AUDIT_WRITTEN: "artwork refreshed",
        AUDIT_UP_TO_DATE: "already up to date",
        AUDIT_UNAVAILABLE: "no artwork available",
        # Said as intent, not as a count: nothing was refreshed, so this folder is not added to
        # refreshed below. The wording has to make the difference visible on the line itself, since
        # a preview that reported 'artwork refreshed' would be the defect this release is fixing.
        AUDIT_WOULD_REFRESH: "would refresh artwork",
        AUDIT_SKIP_ARTWORK: "artwork download skipped",
    }

    def __init__(self, logger, config_dir=None):
        self.logger = logger
        self._config_dir = Path(config_dir) if config_dir else None

    def _config_dir_for(self, library_root):
        """Return the config directory for scan state. Uses the app's project-root config_dir when
        available, otherwise falls back to library_root.parent/config for backward compatibility."""
        if self._config_dir is not None:
            return self._config_dir
        return Path(library_root).parent / "config"

    def _load_scan_state(self, library_root):
        """Load the incremental scan state from config/scan-state.json.

        Returns a dict with folder_mtimes mapping game folder paths to their last scanned mtime,
        or None if no state exists.
        """
        try:
            config_dir = self._config_dir_for(library_root)
            state_file = config_dir / "scan-state.json"
            if not state_file.is_file():
                return None
            data = json.loads(state_file.read_text(encoding="utf-8"))
            # Return folder_mtimes if present, otherwise None for backward compatibility
            return data.get("folder_mtimes")
        except (OSError, ValueError, AttributeError):
            return None

    def _save_scan_state(self, library_root, folder_mtimes):
        """Save folder mtimes to config/scan-state.json for incremental scanning.

        Merges with existing scan state to preserve other summary fields.
        """
        try:
            config_dir = self._config_dir_for(library_root)
            state_file = config_dir / "scan-state.json"
            existing = {}
            if state_file.is_file():
                try:
                    existing = json.loads(state_file.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
            # Merge: keep existing summary fields, update folder_mtimes and recorded_at
            existing["folder_mtimes"] = folder_mtimes
            existing["recorded_at"] = time.time()
            config_dir.mkdir(parents=True, exist_ok=True)
            import tempfile

            fd, tmp = tempfile.mkstemp(prefix="scan-state.", suffix=".tmp", dir=config_dir)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(existing, f, indent=2)
                for attempt in range(4):
                    try:
                        os.replace(tmp, state_file)
                        break
                    except PermissionError:
                        if attempt == 3:
                            raise
                        time.sleep(0.05 * (attempt + 1))
            finally:
                try:
                    os.unlink(tmp)
                except FileNotFoundError:
                    pass
        except (OSError, TypeError, ValueError):
            pass  # Best effort - scan already succeeded

    def _get_folder_mtime(self, folder):
        """Get the most recent mtime of files in a game folder that matter for scanning.

        Checks: archive files, .game-info.json, Steam link files, artwork files.
        Returns 0 if folder doesn't exist or is empty.
        """
        try:
            folder = Path(folder)
            if not folder.is_dir():
                return 0
            max_mtime = 0
            for item in folder.iterdir():
                if item.is_file():
                    # Track files that would change if the game content changed
                    if item.suffix.lower() in (".zip", ".rar", ".7z") or item.name == ".game-info.json" or item.name.startswith("Open Steam Page") or item.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
                        try:
                            mtime = item.stat().st_mtime_ns
                            if mtime > max_mtime:
                                max_mtime = mtime
                        except OSError:
                            pass
            return max_mtime
        except OSError:
            return 0

    def _pending_archive_in(self, game_dir):
        """The .zip/.rar still sitting in an organized game folder, if any. An existing .7z needs no repair, so
        a fully converted folder reports nothing and is skipped without touching the disk."""
        try:
            return next((item for item in sorted(game_dir.iterdir()) if item.is_file() and item.suffix.lower() in (".zip", ".rar")), None)
        except OSError:
            return None

    def pending_candidates(self, library_root):
        """Every .zip/.rar still inside an organized game folder, smallest first.

        Size order is the point: converting needs room for the source, the extracted content and the rebuilt
        archive at the same time, so on a nearly full volume the small archives are the ones that can actually
        finish. Returns (game_dir, pending_path, size_bytes, appid, display_name) tuples.
        """
        library_root = Path(library_root).expanduser().resolve()
        if not library_root.is_dir():
            return []
        found = []
        for category_dir in sorted(p for p in library_root.iterdir() if p.is_dir() and p.name not in LIBRARY_RESERVED_DIRS and not _is_app_folder(p)):
            for game_dir in sorted(p for p in category_dir.iterdir() if p.is_dir()):
                pending = self._pending_archive_in(game_dir)
                if pending is None:
                    continue
                try:
                    size = pending.stat().st_size
                except OSError:
                    size = 0
                metadata = self._read_metadata(game_dir)
                appid = self._find_appid(game_dir, metadata)
                name = metadata.get("name") or game_dir.stem.split(" - ")[0]
                found.append((game_dir, pending, size, appid, name))
        found.sort(key=lambda item: item[2])
        return found

    def convert_pending_archives(self, library_root, organizer_service, ctx=None, journal=None, on_progress=None, unlocker=None, outcomes=None, zip_password="", work=None):
        """Converts leftover .zip/.rar inside already-organized game folders to .7z, independent of the All /
        New Only choice. Discovery hides archives that already sit next to a Steam link, so under New Only a
        failed conversion would otherwise stay broken forever. Artwork is already covered for every organized
        game by audit(); this pass exists purely to finish conversions that organizing never got to.

        `unlocker` must be supplied for password-protected zips. Discovery only removes the password from the
        archives it actually walks, and it skips anything sitting in an already-organized folder, so without it
        every such leftover could not be extracted here and stayed a .zip forever.

        `work` optionally supplies pre-computed candidates (game_dir, pending, appid, name), e.g. from
        pending_candidates(), so the library is walked once instead of once per pass."""
        library_root = Path(library_root).expanduser().resolve()
        if not library_root.is_dir():
            return 0
        converted = 0
        if work is None:
            # Collect the whole list first. The pass converts what it finds, and each conversion rewrites the
            # folder it was reading from, so a running count is only meaningful against a total that was fixed
            # before the first rebuild started - which is also what lets the screen answer "how many are left".
            work = []
            for category_dir in sorted(p for p in library_root.iterdir() if p.is_dir() and p.name not in LIBRARY_RESERVED_DIRS and not _is_app_folder(p)):
                for game_dir in sorted(p for p in category_dir.iterdir() if p.is_dir()):
                    pending = self._pending_archive_in(game_dir)
                    if pending is None:
                        continue
                    metadata = self._read_metadata(game_dir)
                    work.append((game_dir, pending, self._find_appid(game_dir, metadata), metadata.get("name") or game_dir.stem.split(" - ")[0]))
        if work and on_progress:
            on_progress({"stage": "repair_plan", "index": 0, "total": len(work), "game": work[0][3], "message": f"{len(work)} archive(s) queued for conversion"})
        for index, (game_dir, pending, appid, name) in enumerate(work, 1):
            if ctx:
                ctx.checkpoint()
            archive = _RepairArchive(pending, appid, name)
            if on_progress:
                try:
                    on_progress({"stage": "repair_start", "index": index, "total": len(work), "game": name, "file": pending.name, "message": f"Converting {index} of {len(work)}: {name}"})
                except Exception as exc:
                    self.logger.warning("LIBRARY", f"REPAIR_PROGRESS_FAILED error={type(exc).__name__}")
            try:
                # Unlock before repacking: the extraction step has no way to supply a password, so a
                # protected archive would otherwise fail to extract and be left exactly as it was.
                if unlocker is not None and pending.suffix.lower() == ".zip":
                    if unlocker(pending, ctx):
                        archive.conversion.message = "ZIP password removed before conversion"
                before = pending
                # Stamp the position onto everything the conversion reports, including its own completion
                # event, so every line the user sees carries the same "which one of how many".
                inner = on_progress
                if on_progress:

                    def relay(event, index=index, total=len(work)):
                        if isinstance(event, dict):
                            event = dict(event, index=index, total=total)
                        on_progress(event)

                    inner = relay
                after = organizer_service._repack_with_official_name(archive, ctx=ctx, on_progress=inner, zip_password=zip_password, library_root=library_root)
                if after.suffix.lower() == ".7z" and after != before:
                    converted += 1
                    archive.conversion.status = "converted"
                    archive.conversion.organized_path = after
                    if journal is not None:
                        journal.append((before, after))
                elif archive.conversion.status == "pending":
                    archive.conversion.status = "skipped"
                    archive.conversion.final_name = pending.name
            except CancellationError:
                raise
            except Exception as exc:
                archive.conversion.status = "failed"
                archive.conversion.message = f"{type(exc).__name__}: {str(exc)[:200]}"
                self.logger.warning("LIBRARY", f"PENDING_CONVERT_FAILED folder=[{game_dir}] path=[{pending.name}] error={type(exc).__name__} message=[{str(exc)[:300]}]")
            if outcomes is not None:
                outcomes.append((pending, archive.conversion))
        self.logger.info("LIBRARY", f"PENDING_CONVERT_COMPLETE converted={converted}")
        return converted

    @staticmethod
    def apply_outcomes(archives, outcomes):
        """Copy repair outcomes onto the matching discovered GameArchive objects.

        The repair pass runs on files discovery has already skipped, so without this the Done screen and the run
        report showed these archives as having no conversion result at all - the one state it could not explain.
        """
        by_path = {path: note for path, note in (outcomes or [])}
        for archive in archives or []:
            note = by_path.get(getattr(archive, "path", None))
            if note is not None:
                archive.conversion = note

    def _size_on_disk(self, path):
        total = 0
        try:
            if path.is_file():
                return path.stat().st_size
            for item in path.rglob("*"):
                if item.is_file():
                    try:
                        total += item.stat().st_size
                    except OSError:
                        pass
        except OSError:
            pass
        return total

    def _is_own_temp(self, path):
        name = path.name
        if path.is_dir():
            return name.startswith(OWN_TEMP_DIRS)
        if name.startswith(OWN_TEMP_FILE_PREFIX):
            return True
        return any(tag in name for tag in OWN_TEMP_FILES)

    @staticmethod
    def _temp_owner(path):
        """(pid, started) of the process that created a temp folder, from its lock marker.

        A repack folder is only safe to delete once the process that owns it is gone. Without this, a scan that
        ran while a conversion was still extracting could delete the extraction folder out from under it.
        """
        try:
            marker = path / LOCK_MARKER if path.is_dir() else None
            if marker is None or not marker.is_file():
                return None
            text = marker.read_text(encoding="utf-8", errors="ignore").split()
            return int(text[0]), float(text[1])
        except (OSError, ValueError, IndexError):
            return None

    @staticmethod
    def _pid_alive(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _temp_is_stale(self, path):
        """True when a temp artefact is genuinely abandoned and can be removed.

        Every extraction folder this code creates carries a lock marker, so an unmarked folder is residue from
        an older release and is safe to remove immediately. A marked folder is only removed once its owning
        process is gone. A temp file has no marker to read, but its name carries the owner's pid - and a build
        that is still running keeps its own mtime fresh, so an owner that is gone plus a young file is still
        left alone rather than judged on the pid alone, which a recycled one can make a lie."""
        if not path.is_dir():
            return self._temp_file_is_stale(path)
        owner = self._temp_owner(path)
        if owner is None:
            return True
        pid, started = owner
        if self._pid_alive(pid):
            return False
        # A dead pid can be recycled. If the folder is younger than the grace window, assume the pid was
        # reused and leave it alone rather than deleting a folder out from under a live conversion.
        return (time.time() - started) > self.OWN_TEMP_GRACE_SECONDS

    TEMP_FILE_OWNER_RE = re.compile(rf"{re.escape(TEMP_FILE_TAG)}\.(\d+)\.")

    def _temp_file_is_stale(self, path):
        steam_match = self.TEMP_FILE_OWNER_RE.search(path.name)
        if not steam_match:
            return True
        if self._pid_alive(int(steam_match.group(1))):
            return False
        try:
            return (time.time() - path.stat().st_mtime) > self.OWN_TEMP_GRACE_SECONDS
        except OSError:
            return False

    def _conversion_in_progress(self, game_dir):
        """True when a conversion owns an extraction folder inside this game folder right now.

        An in-flight repack holds the source archive while it builds the replacement, so the folder briefly
        contains more than one archive and neither is redundant. Anything that reasons about "how many
        archives belong here" has to stand aside until that finishes, and the lock marker written into the
        extraction folder is what makes that decision safe.
        """
        try:
            children = sorted(game_dir.iterdir())
        except OSError:
            return False
        for child in children:
            if child.is_dir() and child.name.startswith(TEMP_DIR_PREFIX):
                if not self._temp_is_stale(child):
                    return True
            # An in-flight build is also visible as a partial file wearing the temp tag.
            if child.is_file() and TEMP_FILE_TAG in child.name:
                return True
        return False

    OWN_TEMP_GRACE_SECONDS = 10 * 60

    def _is_sync_leftover(self, path):
        name = path.name
        if any(name.startswith(s) for s in SYNC_NEVER_TOUCH):
            return False
        return any(fnmatch.fnmatch(name, pattern) for pattern in SYNC_FILE_PATTERNS)

    def cleanup_leftovers(self, library_root, ctx=None, grace_seconds=6 * 3600):
        """Reclaims disk used by temp files this app or Syncthing left behind.

        A conversion holds an extraction folder and a partially built archive at the same time as the
        original, so a run killed part-way (power loss, OOM, cancel) can strand several GB inside the library
        folder that is synced to another PC. This runs before discovery so junk is neither catalogued nor
        replicated onward.

        Our own temp files are deleted immediately - they carry a marker no real game file can have, and
        nothing is converting at this point. Syncthing leftovers are only deleted once they are older than the
        grace period, because a "*.syncthing.*.tmp" may still be an in-flight transfer on the other
        machine. Syncthing's own state and version history are never removed.

        The walk refuses to descend into a junction or symlink. os.walk(followlinks=False) does not: it asks
        Path.is_symlink(), which is False for a junction, so the walk steps through one and matches a temp name
        in whatever folder it points at - deleting a file on the other side of it, in a tree the caller passed
        as the library root. Syncthing creates junctions as a matter of course, so a library that syncs to
        another machine is exactly where one appears. A link that itself matches is left alone for the same
        reason: it is a way out of the library, not a leftover inside it."""
        library_root = Path(library_root).expanduser().resolve()
        if not library_root.is_dir():
            return {}
        # Every deletion this sweep performs is checked against the library root before it runs: a
        # junction walker that somehow reaches outside must never delete outside the library.
        _guard = DeletionGuard([library_root])
        now = time.time()
        removed = 0
        freed = 0
        skipped_young = 0
        skipped_link = 0
        for current, dirs, files in os.walk(library_root):
            here = Path(current)
            # Never descend into Syncthing's version history or its state directory.
            dirs[:] = [d for d in dirs if d not in SYNC_NEVER_TOUCH]
            # Nor through a junction: everything reached that way is outside the library, and this deletes.
            walkable = [d for d in dirs if not is_link(here / d)]
            skipped_link += len(dirs) - len(walkable)
            dirs[:] = walkable
            if ctx:
                ctx.checkpoint()
            for name in list(dirs) + files:
                target = here / name
                if is_link(target):
                    skipped_link += 1
                    continue
                own = self._is_own_temp(target)
                sync = False if own else self._is_sync_leftover(target)
                if not (own or sync):
                    continue

                # Our own temp folders carry a lock marker naming the process that created them, and a temp
                # file carries the owner's pid in its name. Only remove one whose owner is gone, so a scan
                # cannot delete an extraction folder - or a half-built replacement, which costs the whole
                # multi-hour build - out from under a running repack.
                if own and not self._temp_is_stale(target):
                    skipped_young += 1
                    continue
                try:
                    age = now - target.stat().st_mtime
                except OSError:
                    continue
                if not own and age < grace_seconds:
                    skipped_young += 1
                    continue
                size = self._size_on_disk(target)
                try:
                    # Containment check before anything is removed: a target outside the library root
                    # is refused outright, never deleted.
                    if not is_within(target, library_root):
                        self.logger.warning("LIBRARY", f"LEFTOVER_REFUSED path=[{target}] reason=[outside the library]")
                        continue
                    if target.is_dir():
                        shutil.rmtree(str(target))
                    else:
                        target.unlink()
                except OSError as exc:
                    self.logger.warning("LIBRARY", f"LEFTOVER_REMOVE_FAILED path=[{target}] error={type(exc).__name__}")
                    continue
                removed += 1
                freed += size
                self.logger.info("LIBRARY", f"LEFTOVER_REMOVED path=[{target}] kind=[{'organizer' if own else 'syncthing'}] bytes={size}")
        summary = {"removed": removed, "bytes_freed": freed, "deferred_syncthing": skipped_young, "skipped_links": skipped_link}
        self.logger.info("LIBRARY", f"CLEANUP_COMPLETE removed={removed} bytes_freed={freed} deferred_syncthing={skipped_young} skipped_links={skipped_link}")
        # A category folder left with no game in it is dead weight on the catalog page and a trap for the next
        # scan, which walks it as a game folder with no archive and reports it as a scan problem. It is not a
        # temp artefact and not a Syncthing leftover, so the sweep above never touches it, and re-categorising a
        # game - which moves its archive out of the folder it was filed into - leaves exactly these behind.
        empty = self._sweep_empty_categories(library_root, ctx)
        summary.update(empty)
        return summary

    def _move_to_archive(self, folder, library_root):
        archive_dir = Path(library_root).expanduser().resolve() / "Archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        target = archive_dir / folder.name
        n = 2
        while target.exists():
            target = archive_dir / f"{folder.name} ({n})"
            n += 1
        shutil.move(str(folder), str(target))
        return target

    def _sweep_empty_categories(self, library_root, ctx=None):
        """Move game folders without archives and empty categories to Archive.

        A game folder with no archive of its own, holding only things this app wrote
        (Steam link, metadata, artwork), is moved to Archive so the user can review it.
        This runs per game folder, so a category that still has other games does not
        protect empty folders left inside it - the old check scanned the whole category
        tree and skipped everything when any archive existed anywhere in it.

        A category itself is moved to Archive only when it holds no game subfolders
        and no archive was left directly in it by hand.
        """
        removed = 0
        for category_dir in sorted(p for p in library_root.iterdir() if p.is_dir() and p.name not in LIBRARY_RESERVED_DIRS and not _is_app_folder(p)):
            if ctx:
                ctx.checkpoint()
            if is_link(category_dir):
                continue
            if self._is_own_temp(category_dir) and not self._temp_is_stale(category_dir):
                continue
            # An archive file sitting directly in the category folder means a game was left
            # there by hand - the category itself stays, though empty game subfolders still go.
            try:
                root_has_archive = any(item.is_file() and item.suffix.lower() in ARCHIVE_EXTENSIONS for item in category_dir.iterdir())
            except OSError:
                continue
            pruned = 0
            for game_dir in sorted(p for p in category_dir.iterdir() if p.is_dir()):
                # A game folder with no archive of its own is a game that left - regardless
                # of what other game folders in this category still hold.
                try:
                    has_archive_in_game = any(item.is_file() and item.suffix.lower() in ARCHIVE_EXTENSIONS for item in game_dir.iterdir())
                except OSError:
                    continue
                if has_archive_in_game:
                    continue
                if _game_folder_is_prunable(game_dir):
                    try:
                        target = self._move_to_archive(game_dir, library_root)
                        pruned += 1
                        self.logger.info("LIBRARY", f"EMPTY_GAME_FOLDER_ARCHIVED path=[{game_dir}] destination=[{target}]")
                    except OSError as exc:
                        self.logger.warning("LIBRARY", f"EMPTY_GAME_FOLDER_ARCHIVE_FAILED path=[{game_dir}] error={type(exc).__name__}")
            # Only move the category itself if nothing is left in it and it does not hold
            # an archive left by hand at the category root.
            if not root_has_archive and not any(p for p in category_dir.iterdir() if p.is_dir()):
                try:
                    target = self._move_to_archive(category_dir, library_root)
                    removed += 1
                    self.logger.info("LIBRARY", f"EMPTY_CATEGORY_ARCHIVED path=[{category_dir}] destination=[{target}]")
                except OSError as exc:
                    self.logger.warning("LIBRARY", f"EMPTY_CATEGORY_ARCHIVE_FAILED path=[{category_dir}] error={type(exc).__name__}")
        self.logger.info("LIBRARY", f"EMPTY_CATEGORY_SWEEP removed={removed}")
        return {"empty_categories_removed": removed}

    def audit_empty_game_folders(self, library_root):
        """Reports every game folder that holds no archive, whether or not it is prunable.

        A folder with no archive is a game that has left the building: its archive was
        converted away, re-categorised elsewhere, or deleted outside the app. The sweep
        above removes only folders holding things this app wrote; folders the player has
        added files to (saves, mods, a second archive) are kept and listed here instead
        so the user can decide what to do with them.

        Returns a list of (category, game_dir, prunable, file_names) tuples.
        """
        library_root = Path(library_root).expanduser().resolve()
        if not library_root.is_dir():
            return []
        found = []
        for category_dir in sorted(p for p in library_root.iterdir() if p.is_dir() and p.name not in LIBRARY_RESERVED_DIRS and not _is_app_folder(p)):
            if is_link(category_dir):
                continue
            try:
                game_dirs = [p for p in category_dir.iterdir() if p.is_dir()]
            except OSError:
                continue
            for game_dir in sorted(game_dirs):
                try:
                    has_archive = any(item.is_file() and item.suffix.lower() in ARCHIVE_EXTENSIONS for item in game_dir.iterdir())
                except OSError:
                    continue
                if has_archive:
                    continue
                try:
                    files = [item.name for item in game_dir.iterdir()]
                except OSError:
                    files = []
                found.append((category_dir.name, game_dir, _game_folder_is_prunable(game_dir), files))
        return found

    def audit(self, library_root, artwork_service, organizer_service, ctx=None, on_progress=None, preview_only=False, download_artwork=True):
        library_root = Path(library_root).expanduser().resolve()
        # Returns its counts instead of only logging them. The scan feed used to say "Library links and
        # artwork refreshed" with no idea how much work that actually covered.
        if not library_root.is_dir():
            return dict(self.EMPTY_AUDIT)
        # The folders are collected before any work rather than walked as it goes. Knowing the total up front
        # is what lets the screen show real progress, and without it this phase was one line of text followed by
        # minutes of silence: on a library of a few hundred games it fetches artwork for every one of them over
        # the network, which is the slowest thing a scan does and the part a user most needs to see moving.
        try:
            folders = [game for category in sorted(p for p in library_root.iterdir() if p.is_dir() and p.name not in LIBRARY_RESERVED_DIRS) for game in sorted(p for p in category.iterdir() if p.is_dir())]
        except OSError as exc:
            self.logger.warning("LIBRARY", f"AUDIT_LIST_FAILED path=[{library_root}] error={type(exc).__name__}")
            return dict(self.EMPTY_AUDIT)

        # Incremental scanning: load previous folder mtimes
        saved_mtimes = self._load_scan_state(library_root) or {}
        current_mtimes = {}
        skipped_unchanged = 0

        total = len(folders)
        checked = 0
        refreshed = 0
        failed_art = 0
        would_refresh = 0

        def report(**event):
            # A progress sink is a display, never a dependency: a callback that raises must not abort a
            # library-wide pass that is halfway through rewriting Steam links.
            if not on_progress:
                return
            try:
                on_progress(event)
            except Exception as exc:
                self.logger.warning("LIBRARY", f"AUDIT_PROGRESS_FAILED error={type(exc).__name__}")

        report(stage="audit_plan", index=0, total=total, message=f"Checking {total} game folder(s)")

        # Phase 1: Prepare all games - read metadata, find appid, write links/metadata
        # This is fast (disk I/O) and must be sequential to avoid race conditions
        audit_items = []  # (index, game_dir, name, appid, prefix, has_any, expected_name, on_asset)
        for index, game_dir in enumerate(folders, 1):
            if ctx:
                ctx.checkpoint()
            name = game_dir.stem

            # Incremental scan: check if folder has changed since last scan
            folder_key = str(game_dir)
            folder_mtime = self._get_folder_mtime(game_dir)
            current_mtimes[folder_key] = folder_mtime

            if saved_mtimes.get(folder_key) == folder_mtime and folder_mtime > 0:
                # Folder unchanged since last scan - skip it
                skipped_unchanged += 1
                checked += 1
                report(stage="audit_item", index=index, total=total, state="skipped", game=name, message=f"{index} of {total}: {name} — unchanged since last scan")
                continue

            def asset_event(event, index=index, name=name):
                if event.get("state") not in ("downloaded", "failed"):
                    return
                detail = event.get("detail") or event.get("asset") or ""
                report(stage="audit_item", index=index, total=total, state=event.get("state"), game=name, message=f"{index} of {total}: {name} — {event.get('asset', 'artwork')} {event.get('state')}" + (f" ({detail})" if detail else ""))

            metadata = self._read_metadata(game_dir)
            appid = self._find_appid(game_dir, metadata)
            if not appid:
                checked += 1
                report(stage="audit_item", index=index, total=total, state="done", game=name, message=f"{index} of {total}: {name} — {self._audit_text(self.AUDIT_NO_APPID)}")
                continue
            if preview_only:
                checked += 1
                escaped_prefix = globmod.escape(self._asset_prefix(game_dir, metadata))
                outcome = self.AUDIT_UP_TO_DATE if any(game_dir.glob(f"{escaped_prefix}_*")) else self.AUDIT_WOULD_REFRESH
                if outcome == self.AUDIT_WOULD_REFRESH:
                    would_refresh += 1
                report(stage="audit_item", index=index, total=total, state="done", game=name, message=f"{index} of {total}: {name} — {self._audit_text(outcome)}")
                continue
            # Write Steam links and metadata (fast, sequential)
            organizer_service.write_steam_links(game_dir, appid, metadata.get("name") or game_dir.stem.split(" - ")[0])
            if not metadata:
                organizer_service.write_metadata(game_dir, _MinimalArchive(appid, self._asset_prefix(game_dir), game_dir.parent.name))
            prefix = self._asset_prefix(game_dir, metadata)
            escaped_prefix = globmod.escape(prefix)
            expected_name = metadata.get("name") or prefix
            has_any = any(game_dir.glob(f"{escaped_prefix}_*"))
            if not download_artwork:
                checked += 1
                outcome = self.AUDIT_UP_TO_DATE if has_any else self.AUDIT_SKIP_ARTWORK
                if outcome == self.AUDIT_UP_TO_DATE:
                    pass  # not counted as refreshed
                else:
                    pass  # not counted as failed
                report(stage="audit_item", index=index, total=total, state="done", game=name, message=f"{index} of {total}: {name} — {self._audit_text(outcome)}")
                continue
            audit_items.append((index, game_dir, name, appid, prefix, has_any, expected_name, asset_event))

        # Phase 2: Parallel artwork downloads
        if audit_items:
            # Use 4 workers for parallel downloads (network-bound)
            max_workers = min(4, len(audit_items))
            download_results = {}  # index -> (result, changed)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_index = {}
                for index, game_dir, name, appid, prefix, has_any, expected_name, asset_event in audit_items:
                    future = executor.submit(self._download_artwork_for_audit, artwork_service, appid, expected_name, asset_event, ctx)
                    future_to_index[future] = (index, game_dir, name, appid, prefix, has_any, expected_name, asset_event)
                for future in as_completed(future_to_index):
                    index, game_dir, name, appid, prefix, has_any, expected_name, asset_event = future_to_index[future]
                    try:
                        result = future.result()
                        download_results[index] = result
                    except CancellationError:
                        raise
                    except Exception as exc:
                        self.logger.warning("LIBRARY", f"AUDIT_DOWNLOAD_FAILED path=[{game_dir}] error={type(exc).__name__}")
                        download_results[index] = (None, False, str(exc))

        # Phase 3: Process results and copy artwork to game folders
        for index, game_dir, name, appid, prefix, has_any, _expected_name, _asset_event in audit_items:
            checked += 1
            result, changed, error = download_results.get(index, (None, False, "No download result"))
            if error:
                self.logger.warning("LIBRARY", f"AUDIT_GAME_FAILED path=[{game_dir}] error=[{error}]")
                report(stage="audit_item", index=index, total=total, state="failed", game=name, message=f"{index} of {total}: {name} — skipped ({error})")
                continue
            if result:
                # Copy downloaded artwork to game folder
                escaped_prefix = globmod.escape(prefix)
                if result.path and result.path.is_file() and not any(game_dir.glob(f"{escaped_prefix}_grid.*")):
                    shutil.copy2(str(result.path), str(game_dir / f"{prefix}_grid{result.path.suffix}"))
                    changed = True
                for asset_name, path in result.assets.items():
                    if not path.is_file():
                        continue
                    target = game_dir / f"{prefix}_{asset_name}{path.suffix}"
                    if not target.is_file():
                        shutil.copy2(str(path), str(target))
                        changed = True
            if changed:
                try:
                    artwork_service.clear(appid)
                except Exception:
                    pass
                outcome = self.AUDIT_WRITTEN
                refreshed += 1
            elif has_any:
                outcome = self.AUDIT_UP_TO_DATE
            else:
                reason = getattr(result, "reason", "") if result else "no artwork came back"
                self.logger.warning("LIBRARY", f"AUDIT_ARTWORK_UNAVAILABLE path=[{game_dir}] appid=[{appid}] reason=[{reason}]")
                outcome = f"{self.AUDIT_UNAVAILABLE}: {reason}"
                failed_art += 1
            report(stage="audit_item", index=index, total=total, state="done", game=name, message=f"{index} of {total}: {name} — {self._audit_text(outcome)}")

        self.logger.info("LIBRARY", f"AUDIT_COMPLETE checked={checked} refreshed={refreshed} no_artwork={failed_art} would_refresh={would_refresh} skipped_unchanged={skipped_unchanged}")
        # Save updated folder mtimes for incremental scanning
        self._save_scan_state(library_root, current_mtimes)
        report(stage="audit_done", index=total, total=total, message=f"Checked {checked} game folder(s) — refreshed {refreshed}" + (f", {would_refresh} would refresh" if would_refresh else "") + (f", {failed_art} with no artwork" if failed_art else "") + (f", {skipped_unchanged} unchanged skipped" if skipped_unchanged else ""))
        return {"checked": checked, "refreshed": refreshed, "no_artwork": failed_art, "would_refresh": would_refresh, "skipped_unchanged": skipped_unchanged}

    def _audit_text(self, outcome):
        """The line shown for one folder, taken from the outcome rather than guessed from the folder.

        _audit_outcome() used to answer 'artwork refreshed' whenever the folder held an AppID, which is a
        statement about the folder rather than about the run - so it said so for a game whose artwork had
        never been fetched and never would be.
        """
        base = outcome.split(":")[0]
        detail = outcome.split(":", 1)[1].strip() if ":" in outcome else ""
        text = self.AUDIT_TEXT.get(base, f"{base}")
        return f"{text} ({detail})" if detail else text

    def _download_artwork_for_audit(self, artwork_service, appid, expected_name, on_asset, ctx):
        """Download artwork for a single game during audit (called from thread pool).

        Returns (ArtworkResult, changed, error) tuple. error is None on success.
        """
        try:
            if ctx:
                ctx.checkpoint()
            result = artwork_service.download_assets(appid, {}, ctx, "", expected_name, on_progress=(on_asset or (lambda event: None)))
            # Check if anything new was downloaded
            changed = bool(result.path and result.path.is_file()) or bool(result.assets)
            return (result, changed, None)
        except CancellationError:
            raise
        except Exception as exc:
            return (None, False, f"{type(exc).__name__}: {exc}")

    def enforce_single_archive(self, library_root, organizer_service, ctx=None, journal=None):
        """Collapses every already-organized game folder back to exactly one archive, before discovery runs,
        so a stray extra copy never reaches the review queue with a path that is about to move."""
        library_root = Path(library_root).expanduser().resolve()
        if not library_root.is_dir():
            return 0
        archived = 0
        for category_dir in sorted(p for p in library_root.iterdir() if p.is_dir() and p.name not in LIBRARY_RESERVED_DIRS and not _is_app_folder(p)):
            for game_dir in sorted(p for p in category_dir.iterdir() if p.is_dir()):
                if ctx:
                    ctx.checkpoint()
                try:
                    archived += self._enforce_single_archive(game_dir, library_root, organizer_service, ctx, journal)
                except CancellationError:
                    raise
                except Exception as exc:
                    self.logger.warning("LIBRARY", f"SINGLE_ARCHIVE_FAILED path=[{game_dir}] error={type(exc).__name__}")
        self.logger.info("LIBRARY", f"SINGLE_ARCHIVE_COMPLETE extra_archives_archived={archived}")
        return archived

    def _metadata_path(self, game_dir):
        return game_dir / ".game-info.json"

    def _enforce_single_archive(self, game_dir, library_root, organizer_service, ctx=None, journal=None):
        """Every organized game folder must hold exactly one game archive per game. Archives dropped into an
        existing folder by hand (or left behind by an interrupted run) are extra copies of a game already
        there: the newest version stays and the rest move to the library Archive folder, using the same
        promotion rule organizing applies. Only same-identity archives are collapsed - two genuinely different
        games sharing a folder (a bad Steam match) are left alone, since archiving one would hide a real game."""
        try:
            archives = [item for item in sorted(game_dir.iterdir()) if item.is_file() and item.suffix.lower() in ARCHIVE_EXTENSIONS]
        except OSError as exc:
            self.logger.warning("LIBRARY", f"SINGLE_ARCHIVE_SCAN_FAILED path=[{game_dir}] error={type(exc).__name__}")
            return 0
        if len(archives) < 2:
            return 0
        # A conversion is running in this folder. Mid-build it holds the source and is producing its
        # replacement, so both are legitimately present for minutes and neither is an "extra copy". Touching
        # the folder here is what moved a live archive out from under a running repack.
        if self._conversion_in_progress(game_dir):
            self.logger.info("LIBRARY", f"SINGLE_ARCHIVE_BUSY folder=[{game_dir}] reason=[a conversion is in progress here]")
            return 0
        moved = 0
        for identity, group in self._group_by_identity(archives).items():
            if len(group) < 2:
                self.logger.warning("LIBRARY", f"MULTIPLE_GAMES_IN_FOLDER folder=[{game_dir}] identity=[{identity}] archives={len(archives)} distinct=1")
                continue
            keep = self._pick_converted_keeper(group, organizer_service)
            # Never archive on the strength of a "kept" archive that has not been shown to exist. Promoting a
            # zero-byte or unreadable stub is how a folder ends up with no usable archive at all while the real
            # one sits in Archive. If the kept file is not there, this folder is already in trouble and
            # archiving anything would only make it worse.
            try:
                usable = keep.is_file() and keep.stat().st_size > 0
            except OSError:
                usable = False
            if not usable:
                self.logger.warning("LIBRARY", f"SINGLE_ARCHIVE_NO_KEEP folder=[{game_dir}] keep=[{keep.name}] reason=[kept archive missing or empty; nothing archived]")
                continue
            for path in group:
                if path == keep:
                    continue
                if ctx:
                    ctx.checkpoint()
                try:
                    target = organizer_service.archive_file(path, library_root)
                except OSError as exc:
                    self.logger.warning("LIBRARY", f"SINGLE_ARCHIVE_MOVE_FAILED path=[{path}] error={type(exc).__name__}")
                    continue
                moved += 1
                if journal is not None:
                    journal.append((path, target))
                self.logger.info("LIBRARY", f"EXTRA_ARCHIVE_MOVED folder=[{game_dir}] kept=[{keep.name}] source=[{path.name}] destination=[{target}]")
        return moved

    def _group_by_identity(self, archives):
        groups = {}
        for path in archives:
            groups.setdefault(identity_key(path.name), []).append(path)
        return groups

    def _pick_converted_keeper(self, group, organizer_service):
        """Choose which archive in a game folder stays when collapsing duplicates.

        The converted format is .7z: a game that has been through the conversion pass holds a .7z, and the
        source .zip/.rar beside it is the leftover the pass is supposed to remove. Choosing the keeper by
        version + modification time alone means a newer .zip can win over an older .7z, and the folder ends
        up holding the unconverted source while the converted archive sits in Archive - which is what the
        user is seeing: the wrong file was sent to the archive folder. .7z wins outright when one is
        present, because it is the format this app produces and the one the next scan expects.
        """
        converted = [p for p in group if p.suffix.lower() == ".7z"]
        if converted:
            return max(converted, key=organizer_service._path_promotion_key)
        return max(group, key=organizer_service._path_promotion_key)

    def _audit_game(self, game_dir, artwork_service, organizer_service, ctx, on_asset=None, preview_only=False, download_artwork=True):
        """Refresh one folder, and say what actually happened.

        Returns one of AUDIT_* rather than a bool. It used to return `changed or not has_any`, which folds two
        different situations into True - "files were written" and "this folder had no artwork and still has
        none" - and the caller counted both as refreshed. The per-folder progress line was worse: it never
        asked this function at all, and reported 'artwork refreshed' for any folder holding an AppID. So a user
        with no network got "Checked 176 game folder(s) - refreshed 176" and nothing in the log, because
        _audit_outcome() only ever tested for the AppID. Verified here: offline, and with an AppID that has no
        art on Steam, both reported refreshed with no image on disk.
        """
        metadata = self._read_metadata(game_dir)
        appid = self._find_appid(game_dir, metadata)
        if not appid:
            return self.AUDIT_NO_APPID
        # Preview Only rewrites nothing, so it never writes a link, a metadata sidecar or an artwork file.
        # It still answers the questions a real scan would: does this folder have an AppID, and does it already
        # hold artwork? What it cannot answer without writing is whether artwork is actually available from
        # Steam, so a folder with no art is reported as one a real scan *would* refresh rather than as refreshed
        # or as unavailable - those two are statements about a run that did not happen. refreshed stays 0.
        if preview_only:
            escaped_prefix = globmod.escape(self._asset_prefix(game_dir, metadata))
            return self.AUDIT_UP_TO_DATE if any(game_dir.glob(f"{escaped_prefix}_*")) else self.AUDIT_WOULD_REFRESH

        # The store page title uses the game's real name, so the date suffix on the folder name never
        # reaches the browser tab the user reads.
        organizer_service.write_steam_links(game_dir, appid, metadata.get("name") or game_dir.stem.split(" - ")[0])
        if not metadata:
            organizer_service.write_metadata(game_dir, _MinimalArchive(appid, self._asset_prefix(game_dir), game_dir.parent.name))
        prefix = self._asset_prefix(game_dir, metadata)
        escaped_prefix = globmod.escape(prefix)
        expected_name = metadata.get("name") or prefix
        has_any = any(game_dir.glob(f"{escaped_prefix}_*"))
        if not download_artwork:
            return self.AUDIT_UP_TO_DATE if has_any else self.AUDIT_SKIP_ARTWORK
        result = artwork_service.download_assets(appid, {}, ctx, "", expected_name, on_progress=(on_asset or (lambda event: None)))
        changed = False
        if result.path and result.path.is_file() and not any(game_dir.glob(f"{escaped_prefix}_grid.*")):
            shutil.copy2(str(result.path), str(game_dir / f"{prefix}_grid{result.path.suffix}"))
            changed = True
        for name, path in result.assets.items():
            if not path.is_file():
                continue
            target = game_dir / f"{prefix}_{name}{path.suffix}"
            if not target.is_file():
                shutil.copy2(str(path), str(target))
                changed = True
        if changed:
            try:
                artwork_service.clear(appid)
            except Exception:
                pass
            return self.AUDIT_WRITTEN
        # Nothing was written. Whether that is correct or a failure depends entirely on whether the folder
        # already had artwork, so the two have to be distinguished rather than merged into one truthy value.
        if has_any:
            return self.AUDIT_UP_TO_DATE
        reason = getattr(result, "reason", "") or "no artwork came back"
        self.logger.warning("LIBRARY", f"AUDIT_ARTWORK_UNAVAILABLE path=[{game_dir}] appid=[{appid}] reason=[{reason}]")
        return f"{self.AUDIT_UNAVAILABLE}: {reason}"

    def _read_metadata(self, game_dir):
        path = self._metadata_path(game_dir)
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _safe_name(self, value):
        value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(value or "")).strip().rstrip(".")
        return re.sub(r"\s+", " ", value) or "Unnamed Game"

    def _asset_prefix(self, game_dir, metadata=None):
        # Assets are written on disk using the sanitized Steam name (see OrganizerService._asset_prefix), not
        # the raw folder name, so prefer the metadata name when available for an exact match (this also
        # avoids mismatches on collision-suffixed folders like "Game - 2020-01-02 (2)").
        name = (metadata or {}).get("name")
        if name:
            return self._safe_name(name)
        return re.sub(r"\s*-\s*(?:\d{4}-\d{2}-\d{2}|Unknown Release Date)$", "", game_dir.name).strip() or game_dir.name

    def _find_appid(self, game_dir, metadata):
        appid = str(metadata.get("appid") or "").strip()
        if appid.isdigit():
            return appid
        for candidate in list(game_dir.glob("*.desktop")) + list(game_dir.glob("*.url")) + list(game_dir.glob("*.html")):
            try:
                text = candidate.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            found = APPID_PATTERN.search(text)
            if found:
                return found.group(1)
        return ""


class _MinimalArchive:
    """Lightweight stand-in so LibraryService can reuse OrganizerService.write_metadata() for games that
    predate the .game-info.json sidecar, without needing a full GameArchive/SteamMatch round trip."""

    def __init__(self, appid, name, category):
        self.steam = type("S", (), {"appid": appid, "name": name, "description": "", "release_date": "", "genres": [], "tags": [], "developer": "", "publisher": ""})()
        self.user_title = name
        self.display_name = name
        self.decision = type("D", (), {"category": category})()


class _RepairArchive:
    """Minimal stand-in for GameArchive so the library repair pass can reuse the organizer's conversion
    routine on an archive that discovery never built an object for.

    It carries a real ConversionResult, not just the fields the packer reads. Without one the organizer's
    `note = getattr(archive,'conversion',None)` was always None here, so every repair outcome was thrown away:
    the Done screen could not name what the repair pass did, and a caller could not tell a successful
    conversion from an archive that was skipped or that failed to extract."""

    def __init__(self, path, appid, name):
        self.path = path
        self.display_name = name
        self.user_title = name
        self.steam = type("S", (), {"appid": appid or "", "found": bool(appid), "name": name, "description": "", "release_date": "", "genres": [], "tags": []})()
        self.decision = type("D", (), {"category": ""})()
        self.conversion = ConversionResult()


# New in this release: library-wide Steam link normalization and artwork refresh that runs every scan.
