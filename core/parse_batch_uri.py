"""Extracted from core/uri_actions.py.

    parse_batch_uri was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import urlsplit
from core.setup_hint import _setup_hint
from core.configured_bases import _configured_bases
from core.destination_parent import _destination_parent
from core.uri_actions import BatchExtractRequest
from core.uri_actions import SCHEME
from core.uri_actions import UriRefused
from core.category_folder import _category_folder


def parse_batch_uri(uri: str, library_root: Path, extract_base):
    """Returns a BatchExtractRequest naming a category, or raises UriRefused with a message for the user.

    The same three rules as a single extract, with the source rule inverted: because no source is named, the
    category is the only thing that needs checking, and the caller enumerates the library rather than trusting
    anything the page said. An empty category means the whole library and skips the folder check.
    """
    parts = urlsplit(str(uri))
    if parts.scheme.casefold() != SCHEME:
        raise UriRefused(f"Unsupported link type: {parts.scheme or 'none'}")
    action = (parts.netloc or parts.path.lstrip("/")).strip().casefold()
    if action not in ("extract-all", "extract-remaining"):
        raise UriRefused(f"Unknown action: {action or 'none'}")
    if library_root is None:
        raise UriRefused("No game library is configured, so there is nothing to extract from." + _setup_hint())
    bases = _configured_bases(extract_base)
    query = parse_qs(parts.query)
    parent = _destination_parent((query.get("dest") or [""])[0], bases, library_root)
    category = (query.get("category") or [""])[0].strip()
    if category:
        _category_folder(category, library_root)
    return BatchExtractRequest(category=category, destination=parent)
