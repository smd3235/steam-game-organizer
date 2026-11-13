"""Extracted from core/uri_actions.py.

    parse_pick_launcher_uri was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from pathlib import Path
from core.parse_extract_root_action import _parse_extract_root_action


def parse_pick_launcher_uri(uri: str, extract_folders) -> Path:
    """Returns the extracted marker/root directory for a pick-launcher action."""
    return _parse_extract_root_action(uri, extract_folders, "pick-launcher", must_have_marker=True)
