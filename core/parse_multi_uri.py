"""Extracted from core/uri_actions.py.

    parse_multi_uri was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import urlsplit
from core.constants import ARCHIVE_EXTENSIONS
from core.safe_folder_name import safe_folder_name
from core.within import _within
from core.setup_hint import _setup_hint
from core.configured_bases import _configured_bases
from core.uri_actions import MultiBatchRequest
from core.uri_actions import SCHEME
from core.uri_actions import UriRefused
from core.destination_parent import _destination_parent


def parse_multi_uri(uri: str, library_root: Path, extract_base):
    """Returns a MultiBatchRequest of individually-validated archive paths, or raises.

    Each src parameter is validated exactly as parse_uri validates a single extract:
    it must resolve inside the library root, exist on disk, and carry an archive extension.
    A hostile page can only ask for files the user already owns, the same boundary a
    single Extract link has. The destination is shared and subject to the same typing rules.
    """
    parts = urlsplit(str(uri))
    if parts.scheme.casefold() != SCHEME:
        raise UriRefused(f"Unsupported link type: {parts.scheme or 'none'}")
    action = (parts.netloc or parts.path.lstrip("/")).strip().casefold()
    if action != "extract-multi":
        raise UriRefused(f"Unknown action: {action or 'none'}")
    if library_root is None:
        raise UriRefused("No game library is configured, so there is nothing to extract from." + _setup_hint())
    bases = _configured_bases(extract_base)
    query = parse_qs(parts.query)
    parent = _destination_parent((query.get("dest") or [""])[0], bases, library_root)
    raw_sources = query.get("src") or []
    if len(raw_sources) < 2:
        raise UriRefused("Select at least two games to multi-extract.")
    archives: list[tuple[Path, Path]] = []
    for raw in raw_sources:
        archive = Path(raw).expanduser()
        if not _within(archive, library_root):
            raise UriRefused(f"Refused: {raw} is outside the game library." + _setup_hint())
        if not archive.is_file():
            raise UriRefused(f"That archive is not there any more: {archive.name}")
        if archive.suffix.lower() not in ARCHIVE_EXTENSIONS:
            raise UriRefused(f"Not an archive this can unpack: {archive.name}")
        leaf = safe_folder_name(archive.stem)
        archives.append((archive, parent / leaf))
    if not archives:
        raise UriRefused("No valid archives were selected.")
    return MultiBatchRequest(archives=archives, destination=parent)
