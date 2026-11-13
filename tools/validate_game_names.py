"""Real Steam game name validator.

Scans the project's source and test files for real Steam game names, appids, and
paths that must never be committed. Every real name that was previously replaced
with a fictional equivalent (see the security entries under `## 9.33` in
CHANGELOG.md) is on the deny list, so any reintroduction fails fast.

Run directly:  python tools\validate_game_names.py

Exits 0 when no real names are found; exits 1 with a list of matches otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Directories that are never scanned: frozen outputs, bundled runtime, git.
SKIP_DIRS = {".git", "dist", "build", "runtime", "__pycache__", ".pytest_cache"}

# The validator itself is excluded: its deny-list entries are expected content.
SELF_PATH = Path(__file__).resolve()

# Real Steam game names that were replaced with fictional equivalents. Each entry
# is a lowercase substring; any file containing it (case-insensitive) is a
# violation. appids are also scanned as bare digits.
REAL_NAMES = [
    "doom",
    "the witcher 3",
    "witcher 3",
    "prison architect",
    "fell & sell",
    "incremedieval",
    "elder scrolls",
    "baldur's gate 3",
    "portal 2",
    "gta5",
    "grand theft auto",
    "half-life 2",
    "halflife 2",
    "rust",
    "brave new wonders",
    "my summer car",
    "sintopia",
    "nivalis nights",
    "mars attracts",
    "star trek",
    "kingdoms and castles",
    "lawn mowing simulator",
    "crystal realms",
    "nova launcher",
    "epsilon online",
    "divinity original sin 2",
    "cities skylines ii",
    "dark souls iii",
    "resident evil 4",
    "star trek voyager",
    "meow tower doomsguard",
    "skyrim",
    "fallout",
    "minecraft",
    "vampire survivors",
    "stardew valley",
    "terraria",
    "factorio",
    "rimworld",
    "civilization",
    "elden ring",
    "cyberpunk",
]

# Real Steam appids that were replaced with fakes. Scanned as standalone digit
# tokens so a version stamp like "2v10112645585273" is not falsely flagged.
REAL_APPIDS = ["1128810"]

# Project root is the parent of the tools/ directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def iter_source_files(root: Path):
    """Yield every .py file under root, skipping vendored/output directories and
    this validator itself (its deny-list entries are expected content)."""
    for path in root.rglob("*.py"):
        if path.resolve() == SELF_PATH:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def scan_file(path: Path):
    """Return a list of (line_number, line_text, reason) violations in one file."""
    violations = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return violations
    # Word-boundary matching so single-word names (rust, doom, skyrim, ...) do not
    # match inside unrelated words (trust, prunable, skyscraper, ...). Multi-word
    # names are bounded at both ends too.
    patterns = [(name, re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)) for name in REAL_NAMES]
    for lineno, line in enumerate(text.splitlines(), 1):
        for name, pattern in patterns:
            if pattern.search(line):
                violations.append((lineno, line.strip(), f"real game name: {name}"))
                break  # one violation per line is enough; avoid duplicate lines
    # Appids: match whole-digit tokens bounded by non-digits.
    for appid in REAL_APPIDS:
        for match in re.finditer(rf"(?<!\d){appid}(?!\d)", text):
            line_start = text.rfind("\n", 0, match.start()) + 1
            lineno = text.count("\n", 0, line_start) + 1
            line = text[line_start:text.find("\n", line_start) if "\n" in text[line_start:] else len(text)]
            violations.append((lineno, line.strip(), f"real Steam appid: {appid}"))
    return violations


def main() -> int:
    bad_files = 0
    total_violations = 0
    for path in sorted(iter_source_files(PROJECT_ROOT)):
        rel = path.relative_to(PROJECT_ROOT)
        violations = scan_file(path)
        if violations:
            bad_files += 1
            total_violations += len(violations)
            print(f"{rel}: {len(violations)} violation(s)")
            for lineno, line, reason in violations:
                print(f"  {lineno}: {reason}  ->  {line[:120]}")
    if total_violations:
        print(f"\n{total_violations} real-name violation(s) across {bad_files} file(s).")
        print("Replace every real name/appid with a fictional equivalent before committing.")
        return 1
    print("No real Steam game names or appids found. Clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
