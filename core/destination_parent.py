"""Extracted from core/uri_actions.py.

    _destination_parent was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from core.uri_actions import UriRefused
from core.setup_hint import _setup_hint
from core.typed_destination import _typed_destination


def _destination_parent(raw_destination, bases, library_root):
    """The folder a game's own subfolder will be created inside, or refuse.

    Shared by the single and batch actions so the two cannot drift on what counts as an acceptable destination -
    the free-text case in particular is a security boundary, and a second copy of it would be a second thing to
    get wrong.
    """
    if not bases:
        raise UriRefused("No extract folder is configured, so there is nowhere to unpack to." + _setup_hint())
    raw_destination = (raw_destination or "").strip()
    if not raw_destination:
        return bases[0]
    return _typed_destination(raw_destination, library_root)
