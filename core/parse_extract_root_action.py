"""Extracted from core/uri_actions.py.

    _parse_extract_root_action was moved here during a module split so the original file
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


def _parse_extract_root_action(uri: str, extract_folders, expected_action: str, *, must_have_marker: bool = False) -> Path:
    parts = urlsplit(str(uri))
    if parts.scheme.casefold() != SCHEME:
        raise UriRefused(f"Unsupported link type: {parts.scheme or 'none'}")
    action = (parts.netloc or parts.path.lstrip("/")).strip().casefold()
    if action != expected_action:
        raise UriRefused(f"Unknown action: {action or 'none'}")
    bases = _configured_bases(extract_folders)
    if not bases:
        raise UriRefused("No extract folder is configured." + _setup_hint())
    raw = (parse_qs(parts.query).get("path") or [""])[0]
    if not raw:
        raise UriRefused("The link did not say which folder to use.")
    folder = Path(raw).expanduser()
    if not any(_within(folder, b) for b in bases):
        raise UriRefused(f"Refused: {raw} is outside the configured extract folders.")
    try:
        folder = folder.resolve(strict=True)
    except OSError as exc:
        raise UriRefused(f"That folder cannot be opened: {exc}") from exc
    if not folder.is_dir():
        raise UriRefused(f"That folder is not there any more: {folder.name}")
    if must_have_marker and not (folder / ".sgo-extract-info").is_file():
        raise UriRefused(f"That extracted folder has no marker information: {folder.name}")
    return folder
