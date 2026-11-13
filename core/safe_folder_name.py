"""Extracted from core/uri_actions.py.

    safe_folder_name was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import re
from core.uri_actions import UNSAFE_CHARS
import unicodedata


def safe_folder_name(text: str, fallback: str = "Extracted") -> str:
    """A single path component that is safe on every filesystem this can land on.

    Windows reserved device names and a trailing dot or space are stripped too: the catalog that supplies
    these names may sit on a synced or shared folder, and a folder named "CON" is unusable
    the moment it reaches one.
    """
    cleaned = UNSAFE_CHARS.sub(" ", unicodedata.normalize("NFKC", str(text or "")))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    reserved = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}
    if not cleaned or cleaned.casefold() in reserved:
        return fallback
    return cleaned[:120]
