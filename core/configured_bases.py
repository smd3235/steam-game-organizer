"""Extracted from core/uri_actions.py.

    _configured_bases was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from pathlib import Path


def _configured_bases(extract_base):
    """The folders the user has already chosen, as a list. None means nowhere is approved."""
    if not extract_base:
        return []
    entries = extract_base if isinstance(extract_base, (list, tuple)) else [extract_base]
    return [Path(p).expanduser() for p in entries]
