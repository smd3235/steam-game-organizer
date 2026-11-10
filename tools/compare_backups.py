#!/usr/bin/env python3
"""Compare files across all backups to find regressions and recover good code.

Usage:
    runtime\python.exe tools\compare_backups.py -f services/steam_service.py
    runtime\python.exe tools\compare_backups.py -f services/steam_service.py --auto-recover
    runtime\python.exe tools\compare_backups.py -f services/steam_service.py --diff
    runtime\python.exe tools\compare_backups.py --list-changed  # Find files that changed across backups
"""
from __future__ import annotations

import argparse
import difflib
import subprocess
import sys
import tempfile
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


def extract_file(archive: Path, internal_path: str, output_dir: Path) -> Path:
    """Extract a single file from archive to output_dir."""
    result = subprocess.run(
        [str(SEVEN_ZIP), "x", str(archive), f"-o{output_dir}", "-r", internal_path],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        return None
    # 7z preserves directory structure, so file is at output_dir / internal_path
    return output_dir / internal_path


def get_file_versions(file_path: str) -> list[tuple[datetime, Path, bytes]]:
    """Get all versions of a file across backups. Returns list of (timestamp, backup_path, file_content)."""
    versions = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for backup in list_backups():
            # Extract to a subdirectory named after backup
            extract_dir = tmp / backup.stem
            extract_dir.mkdir(parents=True, exist_ok=True)
            extracted = extract_file(backup, file_path, extract_dir)
            if extracted and extracted.exists():
                mtime = datetime.fromtimestamp(backup.stat().st_mtime)
                content = extracted.read_bytes()
                versions.append((mtime, backup, content))
    return sorted(versions, key=lambda x: x[0])  # oldest first


def show_diff_from_content(old_content: bytes, new_content: bytes, context: int = 3):
    """Show unified diff between two file contents."""
    old_lines = old_content.decode('utf-8', errors='replace').splitlines(keepends=True)
    new_lines = new_content.decode('utf-8', errors='replace').splitlines(keepends=True)
    
    diff = list(difflib.unified_diff(old_lines, new_lines, n=context))
    if diff:
        # Replace problematic characters for Windows console
        for line in diff:
            line = line.replace('\u2192', '->').replace('\u2705', '[OK]').replace('\u274c', '[FAIL]')
            try:
                sys.stdout.write(line)
            except UnicodeEncodeError:
                sys.stdout.write(line.encode('ascii', 'replace').decode('ascii'))
    else:
        print("  (no differences)")


def compare_all_versions(file_path: str, show_diff_output: bool = False):
    """Compare file across all backups."""
    versions = get_file_versions(file_path)
    if not versions:
        print(f"File not found in any backup: {file_path}")
        return
    
    print(f"Found {len(versions)} version(s) of {file_path}:")
    for i, (mtime, backup, content) in enumerate(versions):
        print(f"  {i+1}. {backup.name} ({mtime.strftime('%Y-%m-%d %H:%M')}) - {len(content)} bytes")
    
    if show_diff_output and len(versions) >= 2:
        print("\n--- Diffs (oldest -> newest) ---")
        for i in range(len(versions) - 1):
            old_mtime, old_backup, old_content = versions[i]
            new_mtime, new_backup, new_content = versions[i + 1]
            print(f"\n=== {old_backup.name} -> {new_backup.name} ===")
            show_diff_from_content(old_content, new_content)


def auto_recover(file_path: str, test_cmd: str = None) -> bool:
    """Auto-recover: test each version from newest to oldest until one passes."""
    versions = get_file_versions(file_path)
    if not versions:
        print(f"File not found in any backup: {file_path}")
        return False
    
    
    # Test from newest to oldest (skip current/newest if it's the broken one)
    for i in range(len(versions) - 1, -1, -1):
        mtime, backup, content = versions[i]
        print(f"Testing version {i+1}/{len(versions)}: {backup.name} ({mtime.strftime('%Y-%m-%d %H:%M')})")
        
        # Write to actual location
        target = ROOT / file_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        
        if test_cmd:
            print(f"  Running test: {test_cmd}")
            # Parse command into list for proper Windows execution
            import shlex
            try:
                cmd_list = shlex.split(test_cmd, posix=False)
            except ValueError:
                cmd_list = test_cmd.split()
            result = subprocess.run(cmd_list, cwd=ROOT, capture_output=True, text=True, timeout=180)
            if result.returncode == 0:
                print(f"  [OK] PASSED - Recovered from {backup.name}")
                return True
            print(f"  [FAIL] FAILED - {result.stderr[:200]}")
        else:
            print("  (No test command provided - manual verification needed)")
    
    print("No working version found in backups")
    return False


def list_changed_files() -> dict[str, int]:
    """Find files that have different content across backups."""
    backups = list_backups()
    if len(backups) < 2:
        return {}
    
    # Use manifest files for quick comparison
    file_sizes = {}
    for backup in backups:
        manifest = backup.with_suffix(".manifest.txt")
        if not manifest.exists():
            continue
        with open(manifest, encoding='utf-8', errors='replace') as f:
            for line in f:
                if '....A' in line or 'D....' in line:
                    parts = line.split()
                    if len(parts) >= 6:
                        name = ' '.join(parts[5:])
                        if '....A' in line:  # file
                            size = int(parts[3])
                            if name not in file_sizes:
                                file_sizes[name] = set()
                            file_sizes[name].add((backup.name, size))
    
    # Find files with multiple sizes across backups
    changed = {}
    for name, versions in file_sizes.items():
        if len(versions) > 1:
            changed[name] = len(versions)
    
    return dict(sorted(changed.items(), key=lambda x: -x[1]))


def main():
    parser = argparse.ArgumentParser(description="Compare and recover files across backups")
    parser.add_argument("-f", "--file", help="File path to compare/recover (relative to project root)")
    parser.add_argument("--diff", action="store_true", help="Show diffs between versions")
    parser.add_argument("--auto-recover", action="store_true", help="Auto-recover: test versions until one passes")
    parser.add_argument("--test-cmd", help="Test command for auto-recover (e.g., 'runtime\\python.exe -m pytest tests/test_steam_service.py -q')")
    parser.add_argument("--list-changed", action="store_true", help="List files that changed across backups")
    args = parser.parse_args()

    backups = list_backups()
    if not backups:
        print("No backups found")
        return 1

    print(f"Found {len(backups)} backup(s) spanning {(datetime.now() - datetime.fromtimestamp(backups[-1].stat().st_mtime)).days} days\n")

    if args.list_changed:
        changed = list_changed_files()
        if not changed:
            print("No files with size changes detected (via manifests)")
        else:
            print(f"Files with changes across backups ({len(changed)}):")
            for name, count in list(changed.items())[:50]:
                print(f"  {name} - {count} versions")
        return 0

    if not args.file:
        parser.print_help()
        return 1

    if args.auto_recover:
        if not args.test_cmd:
            print("ERROR: --auto-recover requires --test-cmd")
            return 1
        success = auto_recover(args.file, args.test_cmd)
        return 0 if success else 1

    compare_all_versions(args.file, show_diff_output=args.diff)
    return 0


if __name__ == "__main__":
    sys.exit(main())