"""The catalog's side-channel file, and the rule both sides use to decide a game is already unpacked.

The catalog is a file on disk that a browser opens directly, and a page opened from `file://` cannot read
anything else on the machine - `fetch` and XHR are both blocked there because the document has an opaque
origin. A classic `<script src>` is the one thing that does load, which is what makes it possible for a batch
run to report back into a page that was written before that run happened.

So the app writes `Game Library.status.js` beside the catalog and the page loads it as a sibling script. The
status survives the run that is reporting it, which is the entire point: the reader comes back to the browser
after two hours and the page finally says what happened.

This lives in its own module rather than in `catalog_service` because both that module and
`batch_extract_service` need it, and putting it in either would make the two import each other.
"""

import json
from datetime import datetime
from pathlib import Path

from core.constants import APP_NAME

# discover_game_launchers extracted to services\discover_game_launchers.py — see that module for its definition.
# write_extract_result extracted to services\write_extract_result.py — see that module for its definition.
STATUS_NAME = "Game Library.status.js"
# The global the page reads. It is a plain assignment rather than a call into a hook, so the order the two
# scripts load in does not matter: the page defines its own reader and the status file only publishes data.
STATUS_GLOBAL = "libraryBatchStatus"

def already_extracted(destination) -> bool:
    """Whether a game's folder already holds unpacked files.

    Checked for real files rather than for the folder's existence, because an interrupted run leaves the folder
    behind - and treating that as finished would silently skip the game it died on, which is the one game the
    user most wants finished.
    """
    try:
        return Path(destination).is_dir() and any(Path(destination).iterdir())
    except OSError:
        return False

def extract_marker_path(destination) -> Path:
    """The marker file path inside an extracted game's folder."""
    from services.extract_service import EXTRACT_MARKER

    return Path(destination) / EXTRACT_MARKER

def read_extract_marker(destination):
    """Read the `.sgo-extract-info` marker from an extracted folder, or None.

    Returns the parsed dict (may include archive_size, archive_mtime_ns, extracted_at,
    extracted_root, needs_install, launch_target, setup_done, installed_at). Returns
    None when absent, unreadable, or invalid so callers treat pre-marker/manual
    extractions conservatively.
    """
    marker = extract_marker_path(destination)
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None

# update_extract_marker extracted to services\update_extract_marker.py — see that module for its definition.
# Imported after extract_marker_path and read_extract_marker are defined to avoid a circular import.
from services.update_extract_marker import update_extract_marker

def resolve_extracted_root(destination, extract_folders=()):
    """Best-effort actual extracted content root for an extracted folder.

    Prefers the marker's `extracted_root` when it points at an existing directory that
    is under one of the configured extract folders (or when no folders are given).
    Falls back to `destination` when it exists, else None.
    """
    data = read_extract_marker(destination)
    if data:
        root = data.get("extracted_root")
        if root:
            try:
                root_path = Path(str(root)).expanduser()
            except (TypeError, ValueError, OSError):
                root_path = None
            if root_path is not None and root_path.is_dir():
                folders = [Path(p).expanduser() for p in (extract_folders or [])]
                if not folders or any(_within(root_path, f) for f in folders):
                    return root_path
    dest = Path(destination)
    return dest if dest.is_dir() else None

def _resolve_exe_under_extract_root(exe, extract_folders):
    """Resolve an exe path and require it to be a file under configured extract folders."""
    folders = [Path(p).expanduser() for p in (extract_folders or [])]
    if not folders:
        return None
    try:
        exe_path = Path(str(exe)).expanduser().resolve(strict=True)
    except (TypeError, ValueError, OSError):
        return None
    if not exe_path.is_file() or exe_path.suffix.lower() != ".exe":
        return None
    if not any(_within(exe_path, folder) for folder in folders):
        return None
    return exe_path

LAUNCHER_IGNORE_TOKENS = (
    "unins",
    "uninst",
    "setup",
    "install",
    "installer",
    "patch",
    "update",
    "updater",
    "redist",
    "vcredist",
    "dxsetup",
    "dotnet",
    "unitycrash",
    "crashreport",
    "crash",
    "config",
    "launcher_settings",
    "helper",
    "bugreport",
    "elevate",
    "createdump",
    "prereq",
    "quicksfv",
    "sfv",
    "ffmpeg",
    "spatial",
    "metadata",
    "injector",
    "java",
    "jre",
    "jabswitch",
    "keytool",
    "policytool",
    "orbd",
    "rmid",
    "rmiregistry",
    "servertool",
    "tnameserv",
    "pack200",
    "unpack200",
    "jjs",
    "jfr",
    "jstat",
    "jstack",
    "jmap",
    "jhat",
    "jinfo",
    "jcmd",
    "jrunscript",
    "jaccess",
    "jaccesswalker",
    "kinit",
    "klist",
    "ktab",
    "javaw",
    "java-rmi",
    "jcontrol",
    "jconsole",
    "jvisualvm",
)
LAUNCHER_PREFER_TOKENS = ("game", "start", "play", "launch", "bin", "win64", "x64")
LAUNCHER_MAX_DEPTH = 3
LAUNCHER_MAX_CANDIDATES = 250

def get_launch_target(marker_dir, extract_folders=()):
    """Return the validated persisted launch target exe for a marker directory, else None."""
    data = read_extract_marker(marker_dir) or {}
    target = data.get("launch_target")
    if not target:
        return None
    return _resolve_exe_under_extract_root(target, extract_folders)

def mark_setup_done(destination, *, extract_folders=(), logger=None):
    """Persist explicit "installed/setup done" state for a needs-install extraction.

    Clears `needs_install` and records `setup_done`/`installed_at`. Conservative: only
    updates an existing marker directory under configured extract folders when provided.
    """
    dest = Path(destination)
    folders = [Path(p).expanduser() for p in (extract_folders or [])]
    try:
        resolved = dest.resolve(strict=True)
    except OSError:
        return None
    if not resolved.is_dir():
        return None
    if folders and not any(_within(resolved, folder) for folder in folders):
        return None
    return update_extract_marker(resolved, logger=logger, needs_install=False, setup_done=True, installed_at=datetime.now().strftime("%Y-%m-%d %H:%M"))

def _within(candidate: Path, root: Path) -> bool:
    try:
        candidate = candidate.resolve()
        root = root.resolve()
    except OSError:
        return False
    return candidate == root or root in candidate.parents

def archive_has_changed_since_extraction(destination, archive_path) -> bool:
    """True when the archive's current size or mtime differs from what was recorded at extraction.

    Reads the `.sgo-extract-info` marker written by ExtractService into the destination folder.
    Returns False when the marker is absent (pre-v9.32 extraction, or a folder created by hand)
    so an existing extraction is never falsely flagged as stale.
    """
    data = read_extract_marker(destination)
    if not data:
        return False
    try:
        current = Path(archive_path).stat()
    except OSError:
        return False
    return data.get("archive_size") != current.st_size or data.get("archive_mtime_ns") != current.st_mtime_ns

def empty_status() -> dict:
    """The status written next to a brand new catalog: a run has not happened yet, so it says nothing.

    Every key is present even when it has no value. The page reads the keys without checking they exist, and a
    missing key would be a silent `undefined` in the middle of a banner rather than a visible absence.
    """
    return {"ran_at": "", "category": "", "destination": "", "total": 0, "extracted": 0, "skipped": 0, "failed": 0, "cancelled": 0, "already_done": 0, "needs_install": 0, "elapsed": ""}

def elapsed_text(seconds) -> str:
    """A duration as '2h 14m', '14m' or '40s'.

    Written out rather than left as a number of seconds because the reader who is looking at this is trying to
    work out whether the run they just sat through was worth it, and '7944' does not answer that.
    """
    try:
        total = int(max(0, float(seconds)))
    except (TypeError, ValueError):
        return ""
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m"
    return f"{total // 3600}h {(total % 3600) // 60}m"

def status_from_run(plan, job) -> dict:
    """The status of a finished run, in the shape empty_status() established.

    Takes the plan and the job rather than copying their fields out at the call site, so that a counter added
    to one of them has somewhere obvious to be added here too. Neither type is imported - this module is
    imported by the batch service's own dependencies, and importing them back would be a circle.
    """
    started, finished = getattr(job, "started_at", 0.0), getattr(job, "finished_at", 0.0)
    ran = finished - started if started and finished else 0.0
    return {"ran_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "category": str(plan.category), "destination": str(plan.destination), "total": len(plan.items), "extracted": job.succeeded, "skipped": job.skipped, "failed": job.failed, "cancelled": job.cancelled, "already_done": plan.already_done, "needs_install": getattr(job, "needs_install", 0), "elapsed": elapsed_text(ran)}

def status_javascript(status: dict) -> str:
    """The file's whole contents.

    `json.dumps` produces a valid JavaScript object literal for a dict of strings and numbers, which is what
    makes this safe to write without hand-escaping: a category named `"; alert(1); "` comes back out as a JSON
    string, not as code. The file is loaded as a script rather than inlined into the page, so there is no
    `</script>` to break out of either.
    """
    return f"/* Written by {APP_NAME}. Rewritten after every batch run. Safe to delete. */\nwindow.{STATUS_GLOBAL} = {json.dumps(status)};\n"

def write_status(library_root, status: dict, logger=None) -> Path:
    """Write the status file beside the catalog. Returns the path, or None if it could not be written.

    A failure here is logged and swallowed. The run it describes already happened and the game folders are
    already on disk, so a browser cannot be told about it must not turn a successful unpack into a failed one.
    """
    path = Path(library_root) / STATUS_NAME
    try:
        path.write_text(status_javascript(status), encoding="utf-8")
    except OSError as exc:
        if logger:
            logger.warning("CATALOG", f"STATUS_WRITE_FAILED path=[{path}] error={type(exc).__name__}")
        return None
    if logger:
        logger.info("CATALOG", f"STATUS_WRITTEN path=[{path}]")
    return path

