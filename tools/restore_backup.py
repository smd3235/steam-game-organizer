#!/usr/bin/env python3
"""Restore tool for Steam Game Organizer backups.

Extracts specific files/folders from timestamped 7z backups.
Usage:
    runtime\python.exe tools\restore_backup.py                    # List backups
    runtime\python.exe tools\restore_backup.py -l                 # List contents of latest
    runtime\python.exe tools\restore_backup.py -f path/to/file    # Extract file from latest
    runtime\python.exe tools\restore_backup.py -f path -b N       # Extract from backup #N (1=latest)
    runtime\python.exe tools\restore_backup.py -f path -o outdir  # Extract to custom output dir
    runtime\python.exe tools\restore_backup.py -s pattern         # Search ALL backups for pattern
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUP_DIR = ROOT / "backup"
SEVEN_ZIP = ROOT / "runtime" / "7z.exe"


def list_backups() -> list[Path]:
    """Return list of backup files sorted newest first."""
    if not BACKUP_DIR.is_dir():
        return []
    return sorted(BACKUP_DIR.glob("0. Steam Game Organizer_backup_*.7z"), key=lambda p: p.stat().st_mtime, reverse=True)


def list_contents(archive: Path) -> list[str]:
    """List all files in archive."""
    result = subprocess.run([str(SEVEN_ZIP), "l", str(archive)], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"7z list failed: {result.stderr}")
    lines = result.stdout.splitlines()
    in_files = False
    files = []
    for line in lines:
        if "----------" in line:
            in_files = True
            continue
        if in_files and line.strip():
            parts = line.split()
            if len(parts) >= 6:
                name = " ".join(parts[5:])
                files.append(name)
    return files


def search_all_backups(pattern: str) -> list[tuple[Path, list[str]]]:
    """Search all backups for files matching pattern. Returns list of (backup_path, matching_files)."""
    results = []
    for backup in list_backups():
        files = list_contents(backup)
        matches = [f for f in files if pattern.lower() in f.lower()]
        if matches:
            results.append((backup, matches))
    return results


def extract_file(archive: Path, internal_path: str, output_dir: Path) -> Path:
    """Extract a single file/folder from archive to output_dir."""
    result = subprocess.run([str(SEVEN_ZIP), "x", str(archive), f"-o{output_dir}", "-r", internal_path], capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"7z extract failed: {result.stderr}")
    return output_dir / Path(internal_path).name


def main():
    parser = argparse.ArgumentParser(description="Restore files from Steam Game Organizer backups")
    parser.add_argument("-l", "--list", action="store_true", help="List contents of selected backup")
    parser.add_argument("-f", "--file", help="File/folder path inside backup to extract (relative to project root)")
    parser.add_argument("-b", "--backup-index", type=int, default=1, help="Backup to use: 1=latest, 2=previous, etc. (default: 1)")
    parser.add_argument("-o", "--output", default=".", help="Output directory for extracted files (default: current dir)")
    parser.add_argument("-s", "--search", help="Search ALL backups for files matching pattern")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without extracting")
    args = parser.parse_args()

    backups = list_backups()
    if not backups:
        print("No backups found in backup/")
        return 1

    print(f"Found {len(backups)} backup(s):")
    for i, b in enumerate(backups, 1):
        mtime = datetime.fromtimestamp(b.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        size_mb = b.stat().st_size / 1_048_576
        print(f"  {i}. {b.name}  ({mtime}, {size_mb:.1f} MB)")

    # Search mode
    if args.search:
        print(f"\nSearching all backups for: {args.search}")
        results = search_all_backups(args.search)
        if not results:
            print("  No matches found.")
        else:
            for backup, matches in results:
                mtime = datetime.fromtimestamp(backup.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                print(f"\n  {backup.name} ({mtime}):")
                for m in sorted(matches):
                    print(f"    {m}")
        return 0

    if args.backup_index < 1 or args.backup_index > len(backups):
        print(f"Invalid backup index {args.backup_index} (1-{len(backups)})")
        return 1

    selected = backups[args.backup_index - 1]
    print(f"\nUsing backup: {selected.name}")

    if args.list or not args.file:
        print("\nContents:")
        files = list_contents(selected)
        for f in sorted(files):
            print(f"  {f}")
        if not args.file:
            return 0

    if args.dry_run:
        print(f"\nWould extract: {args.file} -> {args.output}/{args.file}")
        return 0

    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nExtracting '{args.file}' to {output_dir}...")
    try:
        extracted = extract_file(selected, args.file, output_dir)
        print(f"[OK] Extracted to: {extracted}")
    except Exception as e:
        print(f"[ERROR] Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
