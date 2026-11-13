"""Extracted from core/uri_actions.py.

    parse_uri was moved here during a module split so the original file
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
from core.uri_actions import ExtractRequest
from core.uri_actions import SCHEME
from core.uri_actions import UriRefused
from core.destination_parent import _destination_parent


def parse_uri(uri: str, library_root: Path, extract_base):
    """Returns an ExtractRequest, or raises UriRefused with a message for the user.

    extract_base may be one destination or an iterable of them, matching AppConfig.extract_folders. A page
    offers that same list, and every entry in it has already been chosen by the user, so each is trusted
    equally - but nothing outside the list is.
    """
    bases = _configured_bases(extract_base)
    if not uri:
        raise UriRefused("No action was given.")
    parts = urlsplit(str(uri))
    if parts.scheme.casefold() != SCHEME:
        raise UriRefused(f"Unsupported link type: {parts.scheme or 'none'}")
    # urlsplit puts the host in netloc, so extract://?x=1 arrives as path=''
    action = (parts.netloc or parts.path.lstrip("/")).strip().casefold()
    if action != "extract":
        raise UriRefused(f"Unknown action: {action or 'none'}")

    if library_root is None:
        raise UriRefused("No game library is configured, so there is nothing to extract from." + _setup_hint())
    raw_source = (parse_qs(parts.query).get("src") or [""])[0]
    if not raw_source:
        raise UriRefused("The link did not say which archive to extract.")

    archive = Path(raw_source).expanduser()
    if not _within(archive, library_root):
        # The common fresh-PC case: the page names a folder this app has never
        # been set up to use, so the refusal says how to point it there.
        raise UriRefused(f"Refused: {raw_source} is outside the game library." + _setup_hint())
    if not archive.is_file():
        raise UriRefused(f"That archive is not there any more: {archive.name}")
    if archive.suffix.lower() not in ARCHIVE_EXTENSIONS:
        raise UriRefused(f"Not an archive this can unpack: {archive.name}")

    # Each game gets its own folder under the chosen parent, so extracting a second game does not mix it
    # with the first and a typo cannot scatter files next to unrelated ones.
    leaf = safe_folder_name(archive.stem)
    raw_destination = (parse_qs(parts.query).get("dest") or [""])[0]
    parent = _destination_parent(raw_destination, bases, library_root)
    return ExtractRequest(archive=archive, destination=parent / leaf)
