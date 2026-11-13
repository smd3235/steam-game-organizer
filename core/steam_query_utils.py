"""Pure utility functions extracted from SteamService.

These functions have no dependency on SteamService instance state and can be
imported and tested independently. They were previously methods on SteamService
that took all their inputs as parameters.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from utils.filename_utils import identity_key


def expand_acronyms(title: str) -> str:
    """Expand common gaming acronyms that appear in filenames but not Steam titles.

    Returns "" when no expansion was made, so callers can fall back to the original title.
    Previously SteamService._expand_acronyms.
    """
    acronyms = {
        r"\bAiO\b": "All in One",
        r"\bVR\b": "Virtual Reality",
        r"\bFPS\b": "First Person Shooter",
        r"\bRPG\b": "Role Playing Game",
        r"\bMMO\b": "Massively Multiplayer Online",
        r"\bRTS\b": "Real Time Strategy",
        r"\bTBS\b": "Turn Based Strategy",
        r"\bARPG\b": "Action RPG",
        r"\bCRPG\b": "Computer RPG",
        r"\bJRPG\b": "Japanese RPG",
        r"\bMOBA\b": "Multiplayer Online Battle Arena",
        r"\bTCG\b": "Trading Card Game",
        r"\bCCG\b": "Collectible Card Game",
        r"\bF2P\b": "Free to Play",
        r"\bP2W\b": "Pay to Win",
        r"\bDLC\b": "Downloadable Content",
        r"\bGOTY\b": "Game of the Year",
        r"\bSotY\b": "Simulation of the Year",
    }
    result = title
    for pattern, expansion in acronyms.items():
        result = re.sub(pattern, expansion, result, flags=re.I)
    return result if result != title else ""


def to_roman(value: int) -> str:
    """Convert an integer 1-39 to a Roman numeral. Returns "" out of range.

    Previously SteamService._to_roman.
    """
    if not 1 <= value <= 39:
        return ""
    table = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    result = ""
    for amount, symbol in table:
        while value >= amount:
            result += symbol
            value -= amount
    return result


def from_roman(text: str) -> int:
    """Convert a Roman numeral to an integer. Returns 0 out of range or invalid.

    Previously SteamService._from_roman.
    """
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    previous = 0
    for char in reversed(text.upper()):
        current = values.get(char, 0)
        total += current if current >= previous else -current
        previous = current
    return total if 1 <= total <= 39 else 0


def swap_trailing_numeral(title: str) -> str:
    """Swap a trailing Arabic numeral to a Roman numeral, or vice versa.

    Returns "" when no swap applies. Previously SteamService._swap_trailing_numeral,
    which called self._to_roman and self._from_roman; those are now module functions.
    """
    words = title.split()
    if not words:
        return ""
    last = words[-1]
    if re.fullmatch(r"\d{1,2}", last):
        roman = to_roman(int(last))
        return " ".join(words[:-1] + [roman]) if roman else ""
    if re.fullmatch(r"(?i)[ivxlcdm]+", last):
        value = from_roman(last.upper())
        return " ".join(words[:-1] + [str(value)]) if value else ""
    return ""


def score(query: str, name: str) -> float:
    """Score how well a query matches a Steam game name, 0.0 to 1.0.

    Uses identity_key normalization, SequenceMatcher ratios, token overlap, and
    subset checks. Scene-release abbreviation tokens (trailing words <= 4 chars)
    are forgiven so they don't sink an otherwise good match.

    Previously SteamService._score.
    """
    query_key = identity_key(query)
    name_key = identity_key(name)
    if not query_key or not name_key:
        return 0.0
    if query_key == name_key:
        return 1.0
    query_tokens = set(re.findall(r"[a-z0-9]+", query.casefold()))
    name_tokens = set(re.findall(r"[a-z0-9]+", name.casefold()))
    if not query_tokens or not name_tokens:
        return 0.0
    sequence = SequenceMatcher(None, query_key, name_key).ratio()
    token = SequenceMatcher(None, " ".join(sorted(query_tokens)), " ".join(sorted(name_tokens))).ratio()
    overlap = len(query_tokens & name_tokens) / max(1, len(query_tokens | name_tokens))
    result = max(sequence, token * 0.95, overlap * 0.96)
    if query_key in name_key or name_key in query_key:
        result = max(result, 0.90)
    if query_tokens <= name_tokens or name_tokens <= query_tokens:
        result = max(result, 0.95)
    if len(query_tokens) > 1:
        short_trailing = [t for t in query_tokens if len(t) <= 4]
        if short_trailing:
            remainder_tokens = query_tokens - set(short_trailing)
            if remainder_tokens and remainder_tokens <= name_tokens:
                result = max(result, 0.90)
    return result
