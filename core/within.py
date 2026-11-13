"""Extracted from core/uri_actions.py.

    _within was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from pathlib import Path


def _within(candidate: Path, root: Path) -> bool:
    """True when candidate is root itself or sits under it.

    Both sides are fully resolved first, because '..' segments and symlinks are exactly what this is guarding
    against; comparing the unresolved strings would let /library/../etc pass.
    """
    try:
        candidate = candidate.resolve()
        root = root.resolve()
    except OSError:
        return False
    return candidate == root or root in candidate.parents
