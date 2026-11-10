"""Unpacks many archives in one run, one row of status per game.

A single Extract is a link, a 7z call and an exit. A category is twenty games and a whole library is a hundred
and seventy-six, which is hours - so this is a queue rather than a loop inline in the entry point: it has to be
able to report which game it is on, how many are left, and to stop between games.

Two decisions worth stating, because both were the alternative and both were worse:

  - The library is enumerated here, through ArchiveService.discover, rather than from a list in the link. The
    link names a category and nothing else, so there is no set of paths for a hostile page to choose, and
    discover is already the app's own definition of what counts as a game - which is what keeps dot-folders,
    the Processing folder and Archive/ out of a run that is meant to be the user's library.

  - A failure is recorded and the queue continues. One unreadable archive in a hundred and seventy-six must not
    cost the other hundred and seventy-five, which is the same lesson the organize run learned the hard way.

Skip-if-already-extracted is on by default. Without it, "Extract all" on a shelf of 176 games re-unpacks
everything already unpacked on every click, and the button stops being usable after the first hour.
"""

from dataclasses import dataclass, field
from pathlib import Path
import threading
import time

from core.exceptions import CancellationError
from core.uri_actions import safe_folder_name
from services.archive_service import ArchiveService
from services.catalog_status import already_extracted
from services.extract_service import ExtractService
from services.installer_detect import NEEDS_INSTALL_DIRNAME
from utils.formatting import human_size

# Per-game outcomes. QUEUED is the only one that is not finished; everything else is a verdict.
QUEUED = "queued"
EXTRACTING = "extracting"
DONE = "done"
FAILED = "failed"
SKIPPED = "skipped"
CANCELLED = "cancelled"


@dataclass
class BatchItem:
    """One game in the queue, and where it stands."""

    archive: Path
    destination: Path
    name: str = ""
    size: int = 0
    state: str = QUEUED
    detail: str = ""
    percent: int = 0
    written: int = 0
    files: int = 0

    @property
    def finished(self) -> bool:
        return self.state in (DONE, FAILED, SKIPPED, CANCELLED)


@dataclass
class BatchPlan:
    """Everything the window needs before the first archive is touched."""

    items: list[BatchItem] = field(default_factory=list)
    total_bytes: int = 0
    destination: Path = Path()
    category: str = ""
    already_done: int = 0

    @property
    def count(self) -> int:
        return len(self.items)


def plan_batch(library_root, destination, category="", logger=None, skip_existing=True, service=None, name_map=None):
    """Work out what a batch would do, without unpacking anything.

    Separate from running it so the window can show the real count, the real total size and the real destination
    before the user commits - a run of 176 games and 244 GB should be confirmable on the evidence, not on a
    promise made by a button label.

    name_map: optional dict mapping archive Path -> (steam_name, release_date). When provided, extraction
    folders are named "{steam_name} - {release_date}" instead of the messy archive filename stem.
    """
    service = service or ArchiveService(logger)
    root = Path(library_root)
    result = service.discover(root / category) if category else service.discover(root)

    # Sort by size, smallest first: a batch is hours of 7z, and a user watching it
    # wants the small games to land first so they can start playing while the big ones
    # grind on. Archives that could not be stat()'d (size=0) sort to the end.
    plan_archives = sorted(result.archives, key=lambda a: a.size)

    plan = BatchPlan(destination=Path(destination), category=category or "the whole library")
    archive_service = service
    # Two games can share a stem - a .7z and a .zip of the same title in different folders - and they would
    # otherwise unpack into one folder and interleave. The counter is on the name, not the path, because the
    # name is the folder.
    used: set[str] = set()
    for archive in plan_archives:
        # Use the clean Steam name + release date from catalog metadata when available,
        # falling back to the messy archive filename stem.
        entry = name_map.get(archive.path) if name_map else None
        if entry:
            steam_name, release_date = entry
            clean = f"{steam_name or archive.path.stem}"
            if release_date:
                clean = f"{clean} - {release_date.replace(',', '')}"
            leaf = safe_folder_name(clean)
        else:
            leaf = safe_folder_name(archive.path.stem)
        if leaf in used:
            suffix = 2
            while f"{leaf} ({suffix})" in used:
                suffix += 1
            leaf = f"{leaf} ({suffix})"
        used.add(leaf)
        # Installer archives go into <dest>/Needs Install/<leaf> instead of <dest>/<leaf>, so they
        # are separated from ready-to-play games at a glance. The signature is read from the archive
        # index (not its payload), so this is a header scan with no extraction cost.
        is_installer = archive_service.archive_installer_kind(archive.path) is not None
        target = Path(destination) / (Path(NEEDS_INSTALL_DIRNAME) / leaf if is_installer else leaf)
        try:
            size = archive.path.stat().st_size
        except OSError:
            size = 0
        if skip_existing and already_extracted(target):
            plan.already_done += 1
            continue
        plan.items.append(BatchItem(archive=archive.path, destination=target, name=archive.display_name or archive.path.stem, size=size))
    plan.total_bytes = sum(item.size for item in plan.items)
    return plan


class BatchExtractJob:
    """Runs a BatchPlan on a worker thread and reports each transition.

    The window owns the widgets and this owns the work, and the only thing crossing between them is
    on_progress(stage, item, detail) - the same shape the organize view already uses, so the two progress
    surfaces in the app behave alike.
    """

    def __init__(self, plan: BatchPlan, logger, on_progress=None, password=""):
        self.plan = plan
        self.logger = logger
        self.on_progress = on_progress or (lambda *args, **kwargs: None)
        self.password = password
        self._cancel = threading.Event()
        self.done = threading.Event()
        self.succeeded = 0
        self.failed = 0
        self.skipped = 0
        self.cancelled = 0
        # Counted off a finished run in the banner too: an installer repack is extracted, not installed, so the
        # run's top line can honestly say "N need install" without a reader having to open the per-row detail.
        self.needs_install = 0
        self.written = 0
        self.started_at = 0.0
        self.finished_at = 0.0

    # ------------------------------------------------------------- control

    def cancel(self):
        """Ask the run to stop. Takes effect on the next tool output line, or between games."""
        self._cancel.set()

    @property
    def cancel_requested(self) -> bool:
        return self._cancel.is_set()

    def remaining(self) -> int:
        return sum(1 for item in self.plan.items if not item.finished)

    # ------------------------------------------------------------- running

    def _emit(self, stage, item, detail=""):
        try:
            self.on_progress(stage=stage, item=item, detail=detail)
        except Exception:
            # A progress callback that raises must not take the run down with it; the window is a readout, and
            # losing the readout is not a reason to lose the extraction.
            pass

    def run(self):
        """The whole queue. Returns True when every game that ran succeeded."""
        self.started_at = time.monotonic()
        self.logger.info("BATCH", f"START dest=[{self.plan.destination}] games=[{self.plan.count}] category=[{self.plan.category}]")
        if not self.plan.items:
            self.finished_at = time.monotonic()
            self.done.set()
            self._emit("finished", None)
            return True

        total = len(self.plan.items)
        for index, item in enumerate(self.plan.items, 1):
            if self.cancel_requested:
                item.state = CANCELLED
                item.detail = "not started"
                self.cancelled += 1
                self._emit("item", item)
                continue

            item.state = EXTRACTING
            item.percent = 0
            self._emit("item", item, f"{index} of {total}")

            service = ExtractService(self.logger, on_progress=self._sub_progress(item))

            try:
                result = service.extract(item.archive, item.destination, password=self.password, cancel=self._cancel.is_set)
            except CancellationError:
                item.state = CANCELLED
                item.detail = "cancelled"
                self.cancelled += 1
                self._emit("item", item)
                continue
            except Exception as exc:
                # Same rule as the organize run: one game's failure is that game's problem. The exception text
                # goes in the row, because "failed" with no reason is the outcome nobody can act on.
                item.state = FAILED
                item.detail = f"{type(exc).__name__}: {exc}"
                self.failed += 1
                self.logger.warning("BATCH", f"ITEM_FAILED name=[{item.name}] error=[{type(exc).__name__}]")
                self._emit("item", item)
                continue

            self.written += result.extracted_bytes
            if result.ok:
                item.state = DONE
                item.detail = f"{result.file_count} files, {human_size(result.extracted_bytes)}"
                if result.needs_install:
                    # The row's verdict is still "Done" (the unpack succeeded); the detail is what says the
                    # folder still needs to be run before the game is playable. Kept on the same field so the
                    # window's one status column carries both the count and the caveat.
                    item.detail += " — installer, needs install"
                    self.needs_install += 1
                self.succeeded += 1
            elif self.cancel_requested:
                item.state = CANCELLED
                item.detail = result.message
                self.cancelled += 1
            else:
                item.state = FAILED
                item.detail = result.message
                self.failed += 1
                self.logger.warning("BATCH", f"ITEM_FAILED name=[{item.name}] reason=[{result.message[:200]}]")
            self._emit("item", item)

        # Everything still queued when the run ends was never reached, which is only possible after a cancel.
        for item in self.plan.items:
            if item.state == QUEUED:
                item.state = CANCELLED
                item.detail = "not started"
                self.cancelled += 1
                self._emit("item", item)

        self.finished_at = time.monotonic()
        self.logger.info("BATCH", f"FINISH ok=[{self.succeeded}] failed=[{self.failed}] skipped=[{self.skipped}] cancelled=[{self.cancelled}] seconds=[{int(self.finished_at - self.started_at)}]")
        self.done.set()
        self._emit("finished", None)
        return self.failed == 0 and self.cancelled == 0

    def _sub_progress(self, item):
        """The per-archive progress callback, bound to its row.

        Set on the service instance rather than passed through extract() because the callback identifies which
        game it belongs to, and the only thing that knows that is the row itself.
        """

        def report(stage="", percent=0, name=""):
            item.percent = int(percent or 0)
            if stage == "extracting" and name:
                item.detail = f"{item.percent}%  {name}"
            self._emit("progress", item)

        return report

    # ------------------------------------------------------------- summary

    def summary(self) -> str:
        """One sentence a person can act on, for the window and for the log."""
        # One clock read, and a run that never started reports 0s rather than the time since the process
        # booted. The finished stamp wins when there is one, so a finished job's elapsed time does not keep
        # growing while the reader is still looking at the window.
        end = self.finished_at or time.monotonic()
        elapsed = f"{int(end - self.started_at)}s" if self.started_at else "0s"
        parts = [f"{self.succeeded} extracted"]
        if self.skipped:
            parts.append(f"{self.skipped} already there")
        if self.failed:
            parts.append(f"{self.failed} failed")
        if self.cancelled:
            parts.append(f"{self.cancelled} not done")
        if self.needs_install:
            # Surfaced in the summary so a run that unpacks a shelf of repacks does not read as "all playable".
            parts.append(f"{self.needs_install} need install")
        written = human_size(self.written) if self.written else "0 B"
        return f"{', '.join(parts)} in {elapsed}  •  {written} unpacked"
