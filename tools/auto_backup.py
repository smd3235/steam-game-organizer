#!/usr/bin/env python3
"""Automated backup tool for Steam Game Organizer.

Creates timestamped 7z backups in backup/ directory with retention policy:
- Only creates backup if no backup exists in last 3 days
- Only backs up if tests pass (no errors)
- Deletes backups older than 30 days
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUP_DIR = ROOT / "backup"
SEVEN_ZIP = ROOT / "runtime" / "7z.exe"


def run_tests() -> bool:
    """Run test suite and return True if all pass."""
    result = subprocess.run(
        [str(ROOT / "runtime" / "python.exe"), "-c",
         "import sys,unittest; sys.path.insert(0,'.'); "
         "result=unittest.TextTestRunner(verbosity=0).run("
         "unittest.defaultTestLoader.discover('tests', pattern='test_*.py')); "
         "sys.exit(0 if result.wasSuccessful() else 1)"],
        cwd=ROOT,
        capture_output=True,
        timeout=180,
    )
    return result.returncode == 0


def latest_backup_age_days() -> float | None:
    """Return age in days of most recent backup, or None if no backups exist."""
    if not BACKUP_DIR.is_dir():
        return None
    backups = list(BACKUP_DIR.glob("0. Steam Game Organizer_backup_*.7z"))
    if not backups:
        return None
    latest = max(backups, key=lambda p: p.stat().st_mtime)
    age = datetime.now() - datetime.fromtimestamp(latest.stat().st_mtime)
    return age.total_seconds() / 86400


def delete_old_backups(max_age_days: int = 30) -> int:
    """Delete backups older than max_age_days. Returns count deleted."""
    if not BACKUP_DIR.is_dir():
        return 0
    cutoff = datetime.now() - timedelta(days=max_age_days)
    deleted = 0
    for backup in BACKUP_DIR.glob("0. Steam Game Organizer_backup_*.7z"):
        mtime = datetime.fromtimestamp(backup.stat().st_mtime)
        if mtime < cutoff:
            backup.unlink()
            deleted += 1
            print(f"Deleted old backup: {backup.name}")
    return deleted


def create_backup() -> Path:
    """Create timestamped 7z backup. Returns path to created archive."""
    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_name = f"0. Steam Game Organizer_backup_{timestamp}.7z"
    archive_path = BACKUP_DIR / archive_name

    # Exclude build artifacts, caches, logs, debug, and previous backups
    exclude_patterns = [
        "-xr!build",
        "-xr!dist",
        "-xr!__pycache__",
        "-xr!.pytest_cache",
        "-xr!.ruff_cache",
        "-xr!.agent-cache",
        "-xr!cache",
        "-xr!logs",
        "-xr!debug",
        "-xr!backup",
        "-xr!*.png",
        "-xr!*.7z",
        "-xr!*.zip",
    ]

    cmd = [str(SEVEN_ZIP), "a", "-t7z", "-mx=5", str(archive_path), str(ROOT) + "\\*", *exclude_patterns]

    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"7z failed: {result.stderr}")

    print(f"Created backup: {archive_name}")
    create_manifest(archive_path)
    return archive_path


def create_manifest(archive: Path) -> Path:
    """Create a manifest.txt file listing all files in the archive."""
    result = subprocess.run([str(SEVEN_ZIP), "l", str(archive)], capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"7z list failed: {result.stderr}")

    manifest_path = archive.with_suffix(".manifest.txt")
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(f"Manifest for {archive.name}\n")
        f.write(f"Created: {datetime.now().isoformat()}\n")
        f.write(f"Size: {archive.stat().st_size / 1_048_576:.1f} MB\n")
        f.write("=" * 80 + "\n")
        f.write(result.stdout)
    print(f"Created manifest: {manifest_path.name}")

    # Also create JSON manifest for programmatic access
    create_json_manifest(archive, result.stdout)
    return manifest_path


def create_json_manifest(archive: Path, listing_output: str) -> Path:
    """Create a structured JSON manifest with file metadata."""
    import json

    files = []
    lines = listing_output.splitlines()
    in_files = False
    for line in lines:
        if "----------" in line:
            in_files = True
            continue
        if in_files and line.strip():
            parts = line.split()
            if len(parts) >= 6:
                try:
                    date_str = parts[0]
                    time_str = parts[1]
                    attr = parts[2]
                    size = int(parts[3])
                    compressed = int(parts[4])
                    name = " ".join(parts[5:])
                    is_dir = attr.startswith("D")
                    files.append({"path": name, "size": size, "compressed": compressed, "modified": f"{date_str} {time_str}", "is_dir": is_dir, "attributes": attr})
                except (ValueError, IndexError):
                    pass

    json_path = archive.with_suffix(".manifest.json")
    manifest_data = {
        "archive": archive.name, "created": datetime.now().isoformat(),
        "size_bytes": archive.stat().st_size,
        "size_mb": round(archive.stat().st_size / 1_048_576, 1),
        "file_count": len([f for f in files if not f["is_dir"]]),
        "dir_count": len([f for f in files if f["is_dir"]]),
        "total_uncompressed": sum(f["size"] for f in files if not f["is_dir"]),
        "files": files,
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)
    print(f"Created JSON manifest: {json_path.name}")
    return json_path


def main():
    parser = argparse.ArgumentParser(description="Automated backup with retention")
    parser.add_argument("--max-age-days", type=int, default=30, help="Delete backups older than this (default: 30)")
    parser.add_argument("--min-interval-days", type=int, default=3, help="Minimum days between backups (default: 3)")
    parser.add_argument("--skip-tests", action="store_true", help="Skip test run (not recommended)")
    parser.add_argument("--force", action="store_true", help="Force backup even if recent backup exists")
    args = parser.parse_args()

    # Check if backup needed
    if not args.force:
        age = latest_backup_age_days()
        if age is not None and age < args.min_interval_days:
            print(f"Latest backup is {age:.1f} days old (min interval: {args.min_interval_days} days). Skipping.")
            # Still clean old backups
            deleted = delete_old_backups(args.max_age_days)
            if deleted:
                print(f"Cleaned {deleted} old backup(s)")
            return 0

    # Run tests unless skipped
    if not args.skip_tests:
        print("Running test suite...")
        if not run_tests():
            print("ERROR: Tests failed. Backup aborted.")
            return 1
        print("Tests passed.")

    # Create backup
    try:
        create_backup()
    except Exception as e:
        print(f"ERROR: Backup failed: {e}")
        return 1

    # Clean old backups
    deleted = delete_old_backups(args.max_age_days)
    if deleted:
        print(f"Cleaned {deleted} old backup(s)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
