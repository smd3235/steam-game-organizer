"""Extracted from core/uri_actions.py.

    _typed_destination was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import os
from pathlib import Path
from core.uri_actions import SYSTEM_PATHS
from core.uri_actions import UriRefused
from core.within import _within


def _typed_destination(raw: str, library_root: Path) -> Path:
    """Validates a destination the user typed into the catalog page.

    The page offers a free-text box, so this cannot be the 'must be inside a pre-approved folder' check the
    configured list uses. What still holds: the path has to be absolute (a relative one would land wherever the
    handler happens to be started from), it may not sit inside a system folder or be the home folder itself, and
    it may not sit inside the game library, where unpacking would be picked up as new game folders on the next
    scan. Refusing a few known-bad targets is weaker than a fixed allow-list and is honest about being so.
    """
    expanded = Path(raw).expanduser()
    if not expanded.is_absolute():
        raise UriRefused(f"That is not a full path, so it would unpack somewhere unknown: {raw}")
    try:
        expanded = expanded.resolve()
    except OSError as exc:
        raise UriRefused(f"Cannot use that destination: {exc}") from exc
    if expanded.parent == expanded:
        raise UriRefused(f"Refused: {expanded} is the filesystem root.")
    if expanded == Path.home().resolve():
        raise UriRefused(f"Refused: {expanded} is your home folder. Pick a folder inside it.")
    # Every folder on the way up is checked, not just the destination itself, so C:\Windows\System32\games is
    # refused as readily as the destination that contains it. That is also what catches a junction, which
    # resolve() rewrites to its target and an exact-match list would then wave through.
    for parent in (expanded, *expanded.parents):
        if os.path.normcase(str(parent)) in SYSTEM_PATHS:
            raise UriRefused(f"Refused: {expanded} is inside a system folder.")
    if _within(expanded, library_root):
        raise UriRefused(f"Refused: {expanded} is inside the game library. Choose somewhere outside it.")
    if expanded.exists():
        if not expanded.is_dir():
            raise UriRefused(f"That destination is a file, not a folder: {expanded}")
    else:
        # Allow a folder that is not created yet, but only if the closest folder that does exist can be written.
        ancestor = expanded.parent
        while not ancestor.exists() and ancestor != ancestor.parent:
            ancestor = ancestor.parent
        if not ancestor.is_dir() or not os.access(ancestor, os.W_OK):
            raise UriRefused(f"Cannot create a folder there: {ancestor} is not writable.")
    return expanded
