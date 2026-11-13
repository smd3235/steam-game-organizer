"""Extracted from core/uri_actions.py.

    parse_open_folder_uri was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import urlsplit
from core.within import _within
from core.uri_actions import SCHEME
from core.uri_actions import UriRefused
from core.setup_hint import _setup_hint


def parse_open_folder_uri(uri: str, library_root) -> Path:
    """Returns the library folder path a steamgameorganizer://open-folder link carries, or refuses."""
    parts = urlsplit(str(uri))
    if parts.scheme.casefold() != SCHEME:
        raise UriRefused(f"Unsupported link type: {parts.scheme or 'none'}")
    action = (parts.netloc or parts.path.lstrip("/")).strip().casefold()
    if action != "open-folder":
        raise UriRefused(f"Unknown action: {action or 'none'}")
    if library_root is None:
        raise UriRefused("No game library is configured." + _setup_hint())
    raw = (parse_qs(parts.query).get("path") or [""])[0]
    if not raw:
        raise UriRefused("The link did not say which folder to open.")
    folder = Path(raw).expanduser()
    if not _within(folder, library_root):
        raise UriRefused(f"Refused: {raw} is outside the game library." + _setup_hint())
    try:
        folder = folder.resolve(strict=True)
    except OSError as exc:
        raise UriRefused(f"That folder cannot be opened: {exc}") from exc
    if not folder.is_dir():
        raise UriRefused(f"That folder is not there any more: {folder.name}")
    return folder
