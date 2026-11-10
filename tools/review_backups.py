#!/usr/bin/env python3
"""Backup review tool - browse, search, diff, and verify backups.

Usage:
    runtime\python.exe tools\review_backups.py                    # List all backups with summary
    runtime\python.exe tools\review_backups.py -i                 # Interactive mode
    runtime\python.exe tools\review_backups.py -s pattern         # Search across all backups
    runtime\python.exe tools\review_backups.py -d backup1 backup2 # Diff two backups
    runtime\python.exe tools\review_backups.py -v                 # Verify integrity of all backups
    runtime\python.exe tools\review_backups.py --stats            # Show statistics
"""

from __future__ import annotations

import argparse
import json
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


def load_json_manifest(backup: Path) -> dict | None:
    """Load JSON manifest for a backup."""
    json_path = backup.with_suffix(".manifest.json")
    if not json_path.exists():
        return None
    try:
        with open(json_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def print_backup_summary():
    """Print summary of all backups."""
    backups = list_backups()
    if not backups:
        print("No backups found.")
        return

    print(f"Found {len(backups)} backup(s):\n")
    print(f"{'#':<3} {'Date':<20} {'Size':>10} {'Files':>8} {'Dirs':>6} {'Uncompressed':>14}")
    print("-" * 80)

    for i, backup in enumerate(backups, 1):
        manifest = load_json_manifest(backup)
        if manifest:
            date = manifest.get("created", "")[:19].replace("T", " ")
            size_mb = manifest.get("size_mb", 0)
            files = manifest.get("file_count", 0)
            dirs = manifest.get("dir_count", 0)
            uncompressed_mb = round(manifest.get("total_uncompressed", 0) / 1_048_576, 1)
            print(f"{i:<3} {date:<20} {size_mb:>8.1f} MB {files:>8} {dirs:>6} {uncompressed_mb:>12.1f} MB")
        else:
            mtime = datetime.fromtimestamp(backup.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            size_mb = backup.stat().st_size / 1_048_576
            print(f"{i:<3} {mtime:<20} {size_mb:>8.1f} MB {'?':>8} {'?':>6} {'?':>14}")


def search_backups(pattern: str, file_type: str = "all", min_size: int = 0, max_size: int = None):
    """Search all backups for files matching pattern."""
    backups = list_backups()
    pattern_lower = pattern.lower()
    results = []

    for backup in backups:
        manifest = load_json_manifest(backup)
        if not manifest:
            continue

        for file_info in manifest.get("files", []):
            if file_info["is_dir"] and file_type != "all" and file_type != "dir":
                continue
            if not file_info["is_dir"] and file_type != "all" and file_type != "file":
                continue
            if file_info["size"] < min_size:
                continue
            if max_size and file_info["size"] > max_size:
                continue
            if pattern_lower in file_info["path"].lower():
                results.append((backup, manifest, file_info))

    if not results:
        print(f"No matches for '{pattern}'")
        return

    print(f"Found {len(results)} match(es) for '{pattern}':\n")

    # Group by backup
    by_backup = {}
    for backup, manifest, file_info in results:
        if backup not in by_backup:
            by_backup[backup] = {"manifest": manifest, "files": []}
        by_backup[backup]["files"].append(file_info)

    for backup, data in by_backup.items():
        m = data["manifest"]
        date = m.get("created", "")[:19].replace("T", " ")
        print(f"\n  {backup.name} ({date})")
        for f in sorted(data["files"], key=lambda x: x["path"]):
            size_str = f"{f['size']:,} bytes" if not f["is_dir"] else "<dir>"
            print(f"    {f['path']} ({size_str})")


def diff_backups(backup1: Path, backup2: Path):
    """Show differences between two backups."""
    m1 = load_json_manifest(backup1)
    m2 = load_json_manifest(backup2)

    if not m1 or not m2:
        print("Error: JSON manifests not found for one or both backups")
        return

    files1 = {f["path"]: f for f in m1.get("files", [])}
    files2 = {f["path"]: f for f in m2.get("files", [])}

    all_paths = set(files1.keys()) | set(files2.keys())

    added = []
    removed = []
    modified = []

    for path in sorted(all_paths):
        f1 = files1.get(path)
        f2 = files2.get(path)

        if f1 and not f2:
            removed.append((path, f1))
        elif f2 and not f1:
            added.append((path, f2))
        elif f1 and f2 and (f1["size"] != f2["size"] or f1.get("modified") != f2.get("modified")):
            modified.append((path, f1, f2))

    print(f"Diff: {backup1.name} -> {backup2.name}\n")

    if added:
        print(f"Added ({len(added)}):")
        for path, f in added[:20]:
            size = f"{f['size']:,} bytes" if not f["is_dir"] else "<dir>"
            print(f"  + {path} ({size})")
        if len(added) > 20:
            print(f"  ... and {len(added) - 20} more")

    if removed:
        print(f"\nRemoved ({len(removed)}):")
        for path, f in removed[:20]:
            size = f"{f['size']:,} bytes" if not f["is_dir"] else "<dir>"
            print(f"  - {path} ({size})")
        if len(removed) > 20:
            print(f"  ... and {len(removed) - 20} more")

    if modified:
        print(f"\nModified ({len(modified)}):")
        for path, f1, f2 in modified[:20]:
            size1 = f"{f1['size']:,}" if not f1["is_dir"] else "<dir>"
            size2 = f"{f2['size']:,}" if not f2["is_dir"] else "<dir>"
            print(f"  ~ {path}: {size1} -> {size2}")
        if len(modified) > 20:
            print(f"  ... and {len(modified) - 20} more")

    if not added and not removed and not modified:
        print("No differences found.")


def verify_backups():
    """Verify integrity of all backups."""
    backups = list_backups()
    if not backups:
        print("No backups found.")
        return

    print(f"Verifying {len(backups)} backup(s)...\n")

    for backup in backups:
        print(f"  {backup.name}...", end=" ", flush=True)

        # Test archive integrity
        result = subprocess.run([str(SEVEN_ZIP), "t", str(backup)], capture_output=True, text=True, timeout=300)

        if result.returncode == 0:
            # Check manifest exists
            manifest = backup.with_suffix(".manifest.txt")
            json_manifest = backup.with_suffix(".manifest.json")
            manifest_ok = manifest.exists()
            json_ok = json_manifest.exists()

            if manifest_ok and json_ok:
                print("OK (archive + manifests)")
            elif manifest_ok:
                print("OK (archive + txt manifest only)")
            else:
                print("WARNING (archive OK, manifests missing)")
        else:
            print(f"FAILED - {result.stderr[:100]}")


def show_stats():
    """Show backup statistics."""
    backups = list_backups()
    if not backups:
        print("No backups found.")
        return

    total_size = sum(b.stat().st_size for b in backups)
    oldest = datetime.fromtimestamp(backups[-1].stat().st_mtime)
    newest = datetime.fromtimestamp(backups[0].stat().st_mtime)
    span = (newest - oldest).days

    # Load manifests for file stats
    total_files = 0
    total_uncompressed = 0

    for backup in backups:
        manifest = load_json_manifest(backup)
        if manifest:
            total_files += manifest.get("file_count", 0)
            total_uncompressed += manifest.get("total_uncompressed", 0)

    print("Backup Statistics:")
    print(f"  Total backups: {len(backups)}")
    print(f"  Date range: {oldest.strftime('%Y-%m-%d')} to {newest.strftime('%Y-%m-%d')} ({span} days)")
    print(f"  Total compressed size: {total_size / 1_048_576:.1f} MB")
    print(f"  Total uncompressed size: {total_uncompressed / 1_048_576:.1f} MB")
    print(f"  Total files (tracked): {total_files:,}")
    print(f"  Average backup size: {total_size / len(backups) / 1_048_576:.1f} MB")
    print(f"  Compression ratio: {total_size / max(total_uncompressed, 1):.2f}")


def interactive_mode():
    """Interactive backup browser."""
    backups = list_backups()
    if not backups:
        print("No backups found.")
        return

    while True:
        print_backup_summary()
        print("\nCommands: [#] view backup, [d] diff, [s] search, [v] verify, [q] quit")
        choice = input("> ").strip().lower()

        if choice == "q":
            break
        if choice == "v":
            verify_backups()
        elif choice == "s":
            pattern = input("Search pattern: ").strip()
            if pattern:
                search_backups(pattern)
        elif choice == "d":
            try:
                idx1 = int(input("First backup #: ")) - 1
                idx2 = int(input("Second backup #: ")) - 1
                if 0 <= idx1 < len(backups) and 0 <= idx2 < len(backups):
                    diff_backups(backups[idx1], backups[idx2])
            except ValueError:
                pass
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(backups):
                view_backup(backups[idx])
        else:
            print("Invalid choice")


def view_backup(backup: Path):
    """View details of a single backup."""
    manifest = load_json_manifest(backup)
    if not manifest:
        print("No JSON manifest available.")
        return

    print(f"\n{backup.name}")
    print(f"  Created: {manifest.get('created', 'unknown')}")
    print(f"  Compressed: {manifest.get('size_mb', 0):.1f} MB")
    print(f"  Files: {manifest.get('file_count', 0):,}")
    print(f"  Directories: {manifest.get('dir_count', 0):,}")
    print(f"  Uncompressed: {manifest.get('total_uncompressed', 0) / 1_048_576:.1f} MB")

    print("\nTop 20 largest files:")
    files = [f for f in manifest.get("files", []) if not f["is_dir"]]
    for f in sorted(files, key=lambda x: x["size"], reverse=True)[:20]:
        print(f"  {f['size']:>12,}  {f['path']}")


def main():
    parser = argparse.ArgumentParser(description="Review Steam Game Organizer backups")
    parser.add_argument("-i", "--interactive", action="store_true", help="Interactive mode")
    parser.add_argument("-s", "--search", help="Search all backups for pattern")
    parser.add_argument("-d", "--diff", nargs=2, help="Diff two backups by index (1=latest)")
    parser.add_argument("-v", "--verify", action="store_true", help="Verify all backup integrity")
    parser.add_argument("--stats", action="store_true", help="Show backup statistics")
    parser.add_argument("-t", "--type", choices=["all", "file", "dir"], default="all", help="File type filter for search")
    parser.add_argument("--min-size", type=int, default=0, help="Minimum file size for search")
    parser.add_argument("--max-size", type=int, help="Maximum file size for search")
    args = parser.parse_args()

    backups = list_backups()
    if not backups:
        print("No backups found in backup/")
        return 1

    if args.interactive:
        interactive_mode()
        return 0

    if args.search:
        search_backups(args.search, args.type, args.min_size, args.max_size)
        return 0

    if args.diff:
        try:
            idx1 = int(args.diff[0]) - 1
            idx2 = int(args.diff[1]) - 1
            if 0 <= idx1 < len(backups) and 0 <= idx2 < len(backups):
                diff_backups(backups[idx1], backups[idx2])
            else:
                print(f"Invalid backup index (1-{len(backups)})")
        except ValueError:
            print("Backup indices must be numbers")
        return 0

    if args.verify:
        verify_backups()
        return 0

    if args.stats:
        show_stats()
        return 0

    # Default: show summary
    print_backup_summary()
    return 0


if __name__ == "__main__":
    sys.exit(main())
