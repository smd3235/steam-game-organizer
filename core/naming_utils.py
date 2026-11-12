"""Pure naming and folder helpers used by the organizer, extracted from `services/organizer_service.py`.

None of these touch the disk except `modified_at()` (which only stats) and `unique_dir()` (which only
checks existence). They carry no service state, so they are module-level functions rather than methods —
callers that used `OrganizerService.__new__(OrganizerService)._safe_name(...)` just to reach a static method
can import them directly instead.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

from utils.filename_utils import version_key

# Characters Windows forbids in filenames, plus the control-character range. Stripped before anything else
# so a title made entirely of them can never produce an empty or illegal folder name.
_FORBIDDEN = r'[<>:"/\\|?*\x00-\x1f]'


def safe_name(value) -> str:
    """Sanitize a string for use as a Windows filename.

    Strips forbidden characters and control characters, collapses whitespace, trims trailing dots, and falls
    back to "Unnamed Game" when nothing remains. The title is sanitized *before* the date suffix is added in
    `game_name()`, so a title of only-forbidden characters cannot leave a folder like "- 2020-03-04" with the
    name gone.
    """
    value = re.sub(_FORBIDDEN, "", str(value or "")).strip().rstrip(".")
    return re.sub(r"\s+", " ", value) or "Unnamed Game"


def release_label(release_date) -> str:
    """Parse a Steam release date into `YYYY-MM-DD`, trying several Steam formats.

    Falls back to `safe_name()` of the raw string when nothing parses, so an unrecognized date still yields
    a usable folder suffix rather than crashing.
    """
    value = str(release_date or "Unknown Release Date").strip()
    for pattern in ("%d %b, %Y", "%b %d, %Y", "%Y-%m-%d", "%d %B, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, pattern).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return safe_name(value)


def game_name(archive) -> str:
    """Build an organized game folder name: `<safe title> - <release label>`.

    The title comes from `archive.steam.name`, then `archive.user_title`, then `archive.display_name`, in
    that order. Sanitized before the date is composed in.
    """
    title = safe_name(archive.steam.name or archive.user_title or archive.display_name)
    return safe_name(f"{title} - {release_label(archive.steam.release_date)}")


def asset_prefix(archive) -> str:
    """The filename prefix used for artwork and links beside a game: just the sanitized title, no date.

    Kept separate from `game_name()` so the browser tab title shows the game name without "- 2026-06-01"
    appended to it.
    """
    return safe_name(archive.steam.name or archive.user_title or archive.display_name)


def modified_at(path) -> float:
    """A file's modification time, or 0.0 when it cannot be stat'd.

    Unknown is 0, not an exception — a missing file is older than anything this app cares about.
    """
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0


def path_promotion_key(path):
    """Promotion sort key for a bare filesystem path: `(version_key(name), modified_at)`.

    Used by the library audit, which inspects already-organized folders where no `GameArchive` has been
    built yet.
    """
    return version_key(Path(path).name), modified_at(path)


def promotion_key(archive):
    """Promotion sort key for a `GameArchive`: delegates to `path_promotion_key(archive.path)`."""
    return path_promotion_key(archive.path)


def unique_dir(parent, name) -> Path:
    """Return `parent / name`, or `parent / "name (2)"`, `parent / "name (3)"`, … when it collides.

    If `parent / name` already exists as a directory it is returned as-is; otherwise the first free
    `(n)` suffixed path is returned. Never creates anything.
    """
    target = Path(parent) / name
    if target.is_dir():
        return target
    n = 2
    while target.exists():
        target = Path(parent) / f"{name} ({n})"
        n += 1
    return target
