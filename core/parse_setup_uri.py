"""Extracted from core/uri_actions.py.

    parse_setup_uri was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from core.prefill import _prefill
from core.uri_actions import SCHEME
from core.uri_actions import SetupRequest
from core.uri_actions import UriRefused
from urllib.parse import parse_qs
from urllib.parse import urlsplit


def parse_setup_uri(uri: str) -> SetupRequest:
    """Returns the setup prefills a steamgameorganizer://setup link carries, or refuses.

    No source or destination is named, so there is nothing to check against the library
    root: the three values only ever seed text boxes, and the wizard that reads them
    validates everything before saving.
    """
    parts = urlsplit(str(uri))
    if parts.scheme.casefold() != SCHEME:
        raise UriRefused(f"Unsupported link type: {parts.scheme or 'none'}")
    action = (parts.netloc or parts.path.lstrip("/")).strip().casefold()
    if action != "setup":
        raise UriRefused(f"Unknown action: {action or 'none'}")
    query = parse_qs(parts.query)
    return SetupRequest(
        library=_prefill(query.get("library")),
        extract=_prefill(query.get("extract")),
        app=_prefill(query.get("app")),
    )
