"""Extracted from core/uri_actions.py.

    parse_open_extracted_uri was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import urlsplit
from core.within import _within
from core.setup_hint import _setup_hint
from core.uri_actions import SCHEME
from core.uri_actions import UriRefused
from core.configured_bases import _configured_bases


def parse_open_extracted_uri(uri: str, extract_folders) -> Path:
    """Returns the folder path a steamgameorganizer://open-extracted link carries, or refuses.

    Opens the extracted game (or installer) folder. The path must be inside one of the configured
    extract folders (resolved/normalized so drive-letter/UNC case and symlinks do not cause false
    refusals on Windows).
    """
    parts = urlsplit(str(uri))
    if parts.scheme.casefold() != SCHEME:
        raise UriRefused(f"Unsupported link type: {parts.scheme or 'none'}")
    action = (parts.netloc or parts.path.lstrip("/")).strip().casefold()
    if action != "open-extracted":
        raise UriRefused(f"Unknown action: {action or 'none'}")
    bases = _configured_bases(extract_folders)
    if not bases:
        raise UriRefused("No extract folder is configured." + _setup_hint())
    raw = (parse_qs(parts.query).get("path") or [""])[0]
    if not raw:
        raise UriRefused("The link did not say which folder to open.")
    folder = Path(raw).expanduser()
    if not any(_within(folder, b) for b in bases):
        raise UriRefused(f"Refused: {raw} is outside the configured extract folders.")
    try:
        folder = folder.resolve(strict=True)
    except OSError as exc:
        raise UriRefused(f"That folder cannot be opened: {exc}") from exc
    if not folder.is_dir():
        raise UriRefused(f"That folder is not there any more: {folder.name}")
    return folder
