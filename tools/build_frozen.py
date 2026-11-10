"""Build the frozen Steam Game Organizer and lay the bundle out the way the app expects it.

`steam_game_organizer.spec` is a onedir build, so PyInstaller writes the exe into
`dist/steam_game_organizer.exe` and the bundle into `dist/steam_game_organizer/`. The app
resolves its project root as `Path(__file__).resolve().parent` and expects core/, services/,
runtime/, config/, cache/ and logs/ to be siblings of the entry point - the same layout a
source checkout has. Leaving the exe outside the bundle would put the runtime one folder out
of reach and every extraction would report no 7z.exe.

PyInstaller's COLLECT stage puts every data and binary into `_internal/` by default, which is
right for a frozen app that only needs its own files, but wrong here: the app's own code walks
its project root looking for `runtime/7z.exe` and the other sibling folders. This script moves
those folders out of `_internal/` and into the bundle root after the build, which is the layout
the source tree already has and the only one the app can find without being told.

It is a post-build step rather than a spec change because PyInstaller has no documented way to
tell COLLECT to leave a data tree at the bundle root; the destination paths in `datas` are
relative to `_internal/`, not to the bundle.
"""

import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "steam_game_organizer.spec"
DIST = ROOT / "dist"
BUNDLE = DIST / "steam_game_organizer"
EXE = BUNDLE / "steam_game_organizer.exe"

# User data directories that must survive a rebuild. Deleting the bundle on
# every build wipes config/settings.json and cache/artwork, forcing a full
# re-setup each time. These are backed up before rmtree and restored after.
USER_DATA = ("config", "cache", "logs")

# Folders the app resolves at runtime by walking its own project root. Anything not in this
# list stays inside _internal/, where PyInstaller puts it and where the app never looks.
SIBLINGS = ("core", "services", "ui", "utils", "app", "debug", "tools", "assets", "runtime")
FILES = ("VERSION.txt", "AGENTS.md", "ARCHITECTURE.md", "CHANGELOG.md", "README.md", "ruff.toml")


def run_backup_if_needed():
    """Run auto_backup.py after successful build if conditions are met."""
    try:
        # Import and run the backup logic
        sys.path.insert(0, str(ROOT / "tools"))
        from auto_backup import latest_backup_age_days, run_tests, create_backup, delete_old_backups

        # Check if backup needed (no backup in last 3 days)
        age = latest_backup_age_days()
        if age is not None and age < 3:
            print(f"Backup skipped: latest backup is {age:.1f} days old (< 3 days)")
            # Still clean old backups
            deleted = delete_old_backups(30)
            if deleted:
                print(f"Cleaned {deleted} old backup(s)")
            return 0

        # Run tests first
        print("Running test suite before backup...")
        if not run_tests():
            print("ERROR: Tests failed. Backup aborted.")
            return 1
        print("Tests passed.")

        # Create backup
        create_backup()

        # Clean old backups
        deleted = delete_old_backups(30)
        if deleted:
            print(f"Cleaned {deleted} old backup(s)")

        return 0
    except Exception as e:
        print(f"Backup error (non-fatal): {e}")
        return 0  # Don't fail the build if backup fails


def main():
    backup = {}
    tmp = tempfile.mkdtemp()
    if BUNDLE.exists():
        for name in USER_DATA:
            src = BUNDLE / name
            if src.exists():
                dst = str(Path(tmp) / name)
                shutil.copytree(str(src), dst)
                backup[name] = dst
    if DIST.exists():

        def _on_rmtree_error(func, path, exc_info):
            # Some files (e.g. runtime/7z.exe) may be locked by a running process.
            # Try to clear the read-only attribute and retry once.
            try:
                os.chmod(path, stat.S_IWRITE)
                func(path)
            except OSError:
                pass

        # Retry the rmtree a few times: Windows Defender or an indexer can hold
        # a DLL open just long enough to fail the first pass.
        for _ in range(5):
            try:
                shutil.rmtree(DIST, onexc=_on_rmtree_error)
                break
            except PermissionError:
                import time

                time.sleep(1)
        else:
            # PyInstaller will overwrite whatever it can; stale files are harmless.
            pass
    try:
        result = subprocess.run(
            [sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm", "--clean"],
            cwd=ROOT,
            check=False,
        )
        if result.returncode != 0:
            return result.returncode

        # Restore backed-up user data (settings.json, cache/artwork, logs).
        for name, path in backup.items():
            dst = BUNDLE / name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.move(str(path), str(dst))

        # If there was no previous bundle to back up from, seed config/settings.json
        # from the source tree so the frozen app has the same defaults as running from source.
        config_src = ROOT / "config" / "settings.json"
        config_dst = BUNDLE / "config" / "settings.json"
        if config_src.is_file() and not config_dst.exists():
            config_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(config_src), str(config_dst))
    finally:
        shutil.rmtree(tmp)

    stray = DIST / "steam_game_organizer.exe"
    if stray.exists():
        if EXE.exists():
            EXE.unlink()
        shutil.move(str(stray), EXE)
    if not EXE.is_file():
        print(f"build produced no executable at {EXE}", file=sys.stderr)
        return 1

    internal = BUNDLE / "_internal"
    for name in SIBLINGS:
        src = internal / name
        dst = BUNDLE / name
        if not src.exists():
            print(f"bundle is missing {src}", file=sys.stderr)
            return 1
        if dst.exists():
            shutil.rmtree(dst)
        shutil.move(str(src), str(dst))
    for name in FILES:
        src = internal / name
        dst = BUNDLE / name
        if src.exists():
            if dst.exists():
                dst.unlink()
            shutil.move(str(src), str(dst))

    missing = [name for name in SIBLINGS if not (BUNDLE / name).exists()]
    if missing:
        print(f"bundle is missing {missing}", file=sys.stderr)
        return 1
    if not (BUNDLE / "runtime" / "7z.exe").is_file():
        print("the frozen app has no 7z.exe to unpack with", file=sys.stderr)
        return 1

    print(f"built {EXE} ({EXE.stat().st_size} bytes)")

    # Run automated backup if conditions are met (no backup in 3 days, tests pass)
    print("Checking backup conditions...")
    run_backup_if_needed()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
