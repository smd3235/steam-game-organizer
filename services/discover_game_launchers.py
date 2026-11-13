"""Extracted from services/catalog_status.py.

    discover_game_launchers was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import os
from services.catalog_status import LAUNCHER_IGNORE_TOKENS
from services.catalog_status import LAUNCHER_MAX_CANDIDATES
from services.catalog_status import LAUNCHER_MAX_DEPTH
from services.catalog_status import LAUNCHER_PREFER_TOKENS
from pathlib import Path


def discover_game_launchers(extracted_root):
    """Conservative playable-exe candidates under an extracted game root.

    Excludes obvious setup/installer/uninstall/redistributable/crash/helper names.
    Returns a list of absolute Paths sorted by a simple confidence heuristic. This is
    intentionally conservative: multiple plausible exes should be presented for user
    choice rather than guessed.
    """
    root = Path(extracted_root)
    if not root.is_dir():
        return []
    found = []
    try:
        for current, dirnames, filenames in os.walk(root):
            current_path = Path(current)
            try:
                rel = current_path.relative_to(root)
                depth = 0 if rel == Path(".") else len(rel.parts)
            except ValueError:
                depth = LAUNCHER_MAX_DEPTH + 1
            if depth >= LAUNCHER_MAX_DEPTH:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__"}]
            for name in filenames:
                path = current_path / name
                if path.suffix.lower() != ".exe":
                    continue
                low = name.casefold()
                if any(token in low for token in LAUNCHER_IGNORE_TOKENS):
                    continue
                score = 0
                if depth == 0:
                    score += 4
                elif depth == 1:
                    score += 2
                if any(token in low for token in LAUNCHER_PREFER_TOKENS):
                    score += 2
                if "launcher" in low:
                    score -= 1
                try:
                    size = path.stat().st_size
                except OSError:
                    size = 0
                if size >= 1024 * 1024:
                    score += 1
                found.append(((-score, depth, low), path.resolve()))
                if len(found) >= LAUNCHER_MAX_CANDIDATES:
                    dirnames[:] = []
                    break
            if len(found) >= LAUNCHER_MAX_CANDIDATES:
                break
    except OSError:
        return []
    found.sort(key=lambda item: item[0])
    return [path for _, path in found]
