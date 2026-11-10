"""Headless, space-aware conversion runner.

The GUI can convert leftover .zip/.rar archives, but it needs a display and a person watching it. This runs the
same repair pass unattended, which is what an overnight run needs.

It is deliberately space-aware. Converting an archive needs room for three things at once: the original, the
extracted content, and the rebuilt .7z. On a volume that is nearly full, converting largest-first fills the disk
and then fails, so this converts smallest-first and refuses to start an archive whose peak requirement does not
fit in the free space. Anything skipped is reported rather than silently dropped, and the next run picks it up.

    python3 tools/overnight_repair.py --root /path/to/Games
    python3 tools/overnight_repair.py --root /path/to/Games --dry-run
"""

from __future__ import annotations

import argparse
import shutil
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.jobs import JobContext
from core.exceptions import CancellationError
from core.config import AppConfig
from core.logger import AppLogger
from services.library_service import LibraryService, _RepairArchive
from services.organizer_service import OrganizerService
from utils.formatting import human_size

# Peak disk a repack needs, as a multiple of the source archive. Three copies can exist at once: the original,
# the extracted content, and the rebuilt .7z. An already-compressed .zip often barely shrinks, so the ceiling is
# closer to 3x than to the ~1.5x a compressing format would suggest. Deliberately pessimistic: on a nearly full
# volume, skipping a large archive is much cheaper than filling the disk.
PEAK_FACTOR = 3.0
# Never start a conversion unless this much space is left afterwards. On a 91%-full volume an 8GB floor keeps
# the machine usable (and keeps /home writable for everything else) while the run works through the small
# archives, which is where the bulk of the count is. Anything skipped here fits on a later pass.
RESERVE_BYTES = 8 * 1024**3

# The password these archives ship with, matching the app's "Remove ZIP password 123" option.
ZIP_PASSWORD = "123"


class SpaceGuard:
    """Cancels the run if free space drops below the reserve while a conversion is in flight.

    The pre-flight estimate keeps the runner from *starting* work that will not fit. This is the backstop for
    the case where the estimate was wrong, and it is checked on a timer because a single large repack can consume
    tens of GB between two checkpoints.
    """

    def __init__(self, root, ctx, reserve=RESERVE_BYTES, interval=5.0):
        self.root, self.ctx, self.reserve, self.interval = root, ctx, reserve, interval
        self.tripped = False
        self._stop = __import__("threading").Event()
        self._thread = None

    def free(self):
        return shutil.disk_usage(str(self.root)).free

    def _loop(self):
        while not self._stop.wait(self.interval):
            try:
                free = self.free()
            except OSError:
                continue
            if free < self.reserve:
                self.tripped = True
                print(f"\n!! free space fell to {human_size(free)} — cancelling to protect the volume.", flush=True)
                self.ctx.cancel()
                return

    def __enter__(self):
        self._thread = __import__("threading").Thread(target=self._loop, name="space-guard", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert leftover ZIP/RAR archives to 7z, headless.")
    parser.add_argument("--root", required=True, help="library root (the Games folder)")
    parser.add_argument("--dry-run", action="store_true", help="list what would convert and stop")
    parser.add_argument("--max-items", type=int, default=0, help="stop after N conversions (0 = no limit)")
    parser.add_argument("--min-free", type=float, default=0.0, metavar="GB", help="extra free-space requirement")
    parser.add_argument("--no-cleanup", action="store_true", help="skip reclaiming orphaned temp folders first")
    parser.add_argument("--force", action="store_true", help="convert even if the app's conversion setting is off")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        print(f"library root is not a directory: {root}")
        return 2

    log_path = Path(__file__).resolve().parent.parent / "logs" / "overnight-repair.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = AppLogger(log_path)
    library = LibraryService(logger)
    # This tool rewrites the user's library, so it honours the same on/off setting as the app. Without that,
    # switching conversion off in the UI would still be undone by any unattended run of this script.
    config = AppConfig(Path(__file__).resolve().parent.parent)
    if not config.convert_archives and not args.force:
        print("conversion is turned off in the app settings; nothing to do.")
        print("pass --force to convert anyway.")
        return 0
    organizer = OrganizerService(logger, convert_archives=config.convert_archives)
    ctx = JobContext("OVERNIGHT")

    # A killed run leaves its extraction folder behind: SIGTERM and SIGKILL never run Python's finally
    # blocks, so the temp directory survives. Those orphans are pure waste and they eat the free-space budget
    # this run depends on, so reclaim them before measuring anything.
    if not args.no_cleanup:
        reclaimed = library.cleanup_leftovers(root, ctx) or {}
        if reclaimed.get("removed"):
            print(f"reclaimed {reclaimed['removed']} orphaned temp item(s), {human_size(reclaimed.get('bytes_freed', 0))} freed")

    # Ctrl-C and a supervisor stop should end the run between archives, letting the organizer delete its
    # extraction folder. Without this the run dies holding up to a few GB of unpacked game data.
    def request_stop(signum, frame):
        print(f"\n{signal.Signals(signum).name} received - finishing the current archive, then stopping…", flush=True)
        ctx.cancel()

    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            try:
                signal.signal(getattr(signal, name), request_stop)
            except (ValueError, OSError):
                pass

    candidates = library.pending_candidates(root)
    free = shutil.disk_usage(str(root)).free
    print(f"library      : {root}")
    print(f"pending      : {len(candidates)} archive(s) needing conversion")
    print(f"pending size : {human_size(sum(item[2] for item in candidates))}")
    print(f"free space   : {human_size(free)}")
    print(f"log          : {log_path}")
    logger.info("OVERNIGHT", f"START root=[{root}] pending={len(candidates)} free={human_size(free)}")

    if not candidates:
        print("\nnothing to convert — every organized game folder is already 7z.")
        return 0

    if args.dry_run:
        print("\nDRY RUN — nothing will be written. Smallest first:\n")
        for _game_dir, pending, size, _appid, _name in candidates:
            need = int(size * PEAK_FACTOR) + RESERVE_BYTES
            fits = "fits" if need <= free else "SKIP (needs %s)" % human_size(need)
            print(f"  {human_size(size):>9}  {pending.name:<52} {fits}")
        return 0

    converted = skipped = failed = 0
    started = time.time()
    print("\nprocessing one archive at a time, smallest first (no parallel jobs)\n")
    with SpaceGuard(root, ctx):
        for index, (_game_dir, pending, size, appid, name) in enumerate(candidates, 1):
            if ctx.cancelled:
                print("\ncancelled; stopping cleanly.")
                break
            if args.max_items and converted >= args.max_items:
                print(f"\nreached --max-items={args.max_items}; stopping.")
                break
            need = int(size * PEAK_FACTOR) + RESERVE_BYTES
            if need > free + int(args.min_free * 1024**3):
                skipped += 1
                msg = f"need ~{human_size(need)} peak, only {human_size(free)} free"
                print(f"[{index}/{len(candidates)}] SKIP  {pending.name} — {msg}")
                logger.info("OVERNIGHT", f"SKIP path=[{pending.name}] reason=[{msg}]")
                continue

            print(f"[{index}/{len(candidates)}] converting {pending.name} ({human_size(size)})…", flush=True)
            archive = _RepairArchive(pending, appid, name)
            try:
                # These archives are password protected and use WinZip AES, which only 7z can read. The
                # password is passed to the extractor directly: rewriting the archive first to strip the
                # password would double the write volume for no benefit, and unzip cannot handle AES at all.
                after = organizer._repack_with_official_name(archive, ctx=ctx, zip_password=ZIP_PASSWORD)
                note = archive.conversion
                if after.suffix.lower() == ".7z" and after != pending:
                    converted += 1
                    freed = human_size(max(0, size - (after.stat().st_size if after.exists() else 0)))
                    print(f"         done → {after.name}  (saved {freed})")
                elif note.status == "skipped":
                    skipped += 1
                    # Say why. Reporting this as "no conversion needed" hid a real, repeatable failure.
                    print(f"         SKIPPED: {note.message or 'left unchanged'}")
                elif note.status == "failed":
                    failed += 1
                    print(f"         FAILED: {note.message or 'conversion failed'}")
                else:
                    skipped += 1
                    print("         no conversion needed")
            except CancellationError:
                print("\ncancelled mid-conversion; stopping.")
                break
            except Exception as exc:
                failed += 1
                print(f"         FAILED: {type(exc).__name__}: {str(exc)[:200]}")
                logger.warning("OVERNIGHT", f"FAILED path=[{pending.name}] error=[{type(exc).__name__}] message=[{str(exc)[:300]}]")
            free = shutil.disk_usage(str(root)).free

    elapsed = time.time() - started
    remaining = library.pending_candidates(root)
    summary = f"converted={converted} skipped={skipped} failed={failed} still_pending={len(remaining)} elapsed={round(elapsed)}s free={human_size(shutil.disk_usage(str(root)).free)}"
    print(f"\nDONE  {summary}")
    if remaining:
        print(f"{len(remaining)} archive(s) still need converting — run again once there is more free space.")
    logger.info("OVERNIGHT", f"DONE {summary}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())  # shape rather than read: the dry-run listing used two of the five, and the main loop never used game_dir.
