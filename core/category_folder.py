"""Extracted from core/uri_actions.py.

    _category_folder was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from core.constants import LIBRARY_RESERVED_DIRS
from core.uri_actions import UriRefused
from core.within import _within


def _category_folder(raw_category, library_root):
    """The category directory named by a batch link, or refuse.

    The name arrives from a web page, so it is treated as a path fragment rather than a label: it has to be a
    single component with no separators, it may not walk upwards, and the folder it names has to actually be a
    directory inside the library. Checking the resolved folder rather than the string is what makes the last two
    rules hold for '..', for a symlink, and for a drive letter.
    """
    name = (raw_category or "").strip()
    if not name:
        raise UriRefused("The link did not say which category to extract.")
    # A separator, a drive, or a walk upwards all mean the name was never a category.
    if name in (".", "..") or "/" in name or "\\" in name or ":" in name:
        raise UriRefused(f"That is not a category name: {name}")
    if name.startswith("."):
        raise UriRefused(f"Refused: {name} is a hidden folder, not a category.")
    if name in LIBRARY_RESERVED_DIRS:
        raise UriRefused(f"Refused: {name} is a folder the app keeps for itself, not a category.")
    folder = library_root / name
    if not _within(folder, library_root):
        raise UriRefused(f"Refused: {name} is outside the game library.")
    if not folder.is_dir():
        raise UriRefused(f"There is no category called {name} in this library.")
    return folder
