"""Reads every archive in the library and reports the ones that will not open.

Read-only: `7z t` decompresses to verify checksums but writes nothing, so it is safe to run against a
library with little free space. Intended to be the audit after the partial-archive incident, and to be
pointable at a library root that is not the configured one.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

EXTENSIONS = {".7z", ".zip", ".rar"}


def archives(library_root: Path):
    for category in sorted(p for p in library_root.iterdir() if p.is_dir() and p.name != "Archive"):
        for game in sorted(p for p in category.iterdir() if p.is_dir() and not p.name.startswith(".")):
            for item in sorted(game.iterdir()):
                if item.is_file() and item.suffix.lower() in EXTENSIONS:
                    yield category.name, game.name, item


def main() -> int:
    # The default was the Steam Deck's /home/deck/Downloads/Games, which cannot exist on the platform this
    # runs on, so running the tool with no arguments on a normal PC printed "library root not found" and
    # exited. It now asks the app for its own default, so the two cannot drift apart again.
    default_root = Path.home() / "Downloads" / "Games"
    root = Path(sys.argv[1] if len(sys.argv) > 1 else default_root).expanduser().resolve()
    # shutil.which alone misses 7-Zip on Windows, where it installs to Program Files and deliberately does
    # not add itself to PATH - so this reported "no 7z on PATH" on a machine that has it. ExtractService
    # already knows both the PATH lookup and the real install folders.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from services.extract_service import ExtractService
    seven_zip, reason = ExtractService.find_tool()
    if not root.is_dir():
        print(f"library root not found: {root}")
        return 1
    if not seven_zip:
        print(f"no 7z/7za available: {reason}")
        return 1

    total = bad = 0
    for category, game, archive in archives(root):
        total += 1
        check = subprocess.run([seven_zip, "t", "-bso0", "-bsp0", str(archive)],
                               capture_output=True, text=True, check=False)
        if check.returncode == 0:
            continue
        bad += 1
        detail = (check.stderr or check.stdout or "").strip().splitlines()
        print(f"BROKEN  {category}/{game}/{archive.name}  exit={check.returncode}")
        for line in detail[-3:]:
            print(f"        {line}")

    print(f"\nchecked {total} archives, {bad} broken")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

