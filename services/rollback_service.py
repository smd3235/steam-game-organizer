import json
from pathlib import Path
import os
import re
import shutil
import tempfile
import time
# Imports split one per line for GitHub readability.
from core.constants import ARCHIVE_EXTENSIONS


def _within(path, root):
    """Whether `path` is `root` or something under it, after both are resolved.

    Resolving both sides is the point: it settles ..\\ segments and symlinks, so a journal naming
    library\\..\\Windows\\System32 is not inside the library and says so. Returns False rather than raising
    on an unresolvable path, because the answer a delete needs is "no".
    """
    try:
        resolved = Path(path).resolve()
        base = Path(root).resolve()
    except OSError:
        return False
    return resolved == base or base in resolved.parents


class RollbackService:
    """Small JSON journal for the last organization transaction."""

    def __init__(self, project_root, logger, organizer=None):
        self.journal = Path(project_root) / "config" / "last-organization.json"
        self.logger = logger
        # Held only to answer one question: may this folder be removed? OrganizerService._folder_is_disposable()
        # owns that allow-list, and duplicating it here would be a second copy of the rule that decides what
        # gets deleted from a user's library - exactly the kind of second answer this codebase keeps removing.
        # Optional, because half the test suite builds this service on its own, and without it nothing is
        # pruned rather than something being pruned on a guess.
        self.organizer = organizer
        self.journal.parent.mkdir(parents=True, exist_ok=True)

    def record(self, moves, owned_dirs=None):
        """Writes the journal atomically, the way the settings file and the Steam cache are written.

        A plain write_text is truncated if the app is killed or the disk fills part-way through, and this file
        is the only record of where a run put things. Losing the tail of it is what turned an interrupted run
        into an Undo that raised instead of undoing, so the temp-and-replace dance is what keeps a half-written
        journal from existing at all.

        Returns True when the journal reached the disk, and False when it did not. Every call site in
        controller.py calls this after committing a move and ignores the result, so a silent failure here means
        the run carries on moving files with no record of where they went, and Undo afterwards reports that
        there is nothing to undo having undone nothing. That is the one outcome worse than a failed run, so it
        is reported rather than absorbed - and logged at ERROR, with the error detail, because the previous
        version logged a bare "PermissionError" at WARN, which does not distinguish a file locked by a sync
        client from a read-only directory and cost real time to diagnose. The nine failures in this repository's
        own log were all WinError 5 on the project's OneDrive folder: transient, and clearable by waiting.

        `owned_dirs` holds the game folders this run created. It travels in the journal because ownership is
        not recoverable afterwards: the two facts an undo needs about a folder are "the run emptied it" and
        "the run made it", and only the first survives in a source/target pair. A folder that was already
        there belongs to the user whatever it contains, so its row is still written - that is how the archive
        gets restored - and refused for the prune. A row carrying no `owned` flag, which is every journal
        written by an earlier release, counts as not owned: it restores its archives and removes nothing
        rather than guessing at a folder it cannot prove it created.
        """
        owned = set(map(str, owned_dirs or ()))
        payload = json.dumps([{"source": str(a), "target": str(b), "owned": str(Path(b).parent) in owned} for a, b in moves], indent=2)
        temp = None
        try:
            self.journal.parent.mkdir(parents=True, exist_ok=True)
            # A unique temp name, not with_suffix('.tmp'). Two instances of the app share this journal, and a
            # fixed name meant the loser's cleanup unlinked the winner's temp file before it could be replaced
            # - losing the record of a completed organize with nothing reported anywhere.
            fd, name = tempfile.mkstemp(prefix="last-organization.", suffix=".tmp", dir=str(self.journal.parent))
            temp = Path(name)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            for attempt in range(4):
                try:
                    os.replace(temp, self.journal)
                    return True
                except PermissionError:
                    if attempt == 3:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        except OSError as exc:
            detail = re.sub(r"\s+", " ", str(exc)).strip()[:200]
            self.logger.error("ROLLBACK", f"JOURNAL_WRITE_FAILED path=[{self.journal}] error=[{type(exc).__name__}] errno=[{getattr(exc, 'errno', None)}] detail=[{detail}] moves=[{len(moves)}]")
            return False
        finally:
            if temp is not None:
                try:
                    temp.unlink()
                except OSError:
                    pass
        return False

    def _rows(self):
        """The moves this journal can still undo, as a list of dicts with usable source/target paths.

        Read defensively because this file is written while the app is running and can be left unusable by an
        interrupted write, a partial disk, or a version that wrote a different shape. None of those is a reason
        to raise: pending_count() is polled live during a run to show what Undo will restore, and undo_last() is
        a button, so an unreadable journal has to read as "nothing to undo" rather than take either down. Note
        that a JSON string here is a real trap - len() of one reported how many moves a five-character file
        would restore. A row is kept when it names both ends of a move; `owned` rides along and is read by
        _prune_emptied, defaulting to False so a journal from an earlier release removes nothing.
        """
        try:
            rows = json.loads(self.journal.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict) and row.get("source") and row.get("target")]

    def pending_count(self):
        """How many moves the last transaction can still undo. Surfaced live during a run so the user knows
        what Undo will actually restore before they finish."""
        return len(self._rows())

    def undo_last(self, library_root=None):
        if not self.journal.is_file():
            return {"moved": 0, "pruned": 0, "reason": "No organization transaction to undo"}
        rows = self._rows()
        if not rows:
            return {"moved": 0, "pruned": 0, "reason": "The last organization record could not be read, so there is nothing to undo"}
        moved = 0
        pruned = 0
        for row in reversed(rows):
            src = Path(row["source"])
            dst = Path(row["target"])
            # The organized file may have been repacked (.zip -> .rar) after the move, so its extension can
            # differ from the recorded source; restore using the current extension, not the stale one.
            restore = src if src.suffix == dst.suffix else src.with_suffix(dst.suffix)
            if dst.exists() and not restore.exists():
                restore.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dst), str(restore))
                moved += 1
            if self._prune_emptied(dst.parent, bool(row.get("owned")), library_root):
                pruned += 1
        if moved == len(rows):
            try:
                self.journal.unlink()
            except OSError:
                self.logger.warning("ROLLBACK", f"JOURNAL_CLEAR_FAILED path=[{self.journal}]")
        self.logger.info("ROLLBACK", f"UNDO moved={moved} pruned={pruned}")
        return {"moved": moved, "pruned": pruned, "reason": "Rollback complete"}

    def _prune_emptied(self, game_dir, owned=False, library_root=None):
        """Move the game folder this rollback just emptied to Archive, and report whether it did.

        The archive goes home and the folder the run created stays behind holding what the run wrote into it -
        the metadata, the Steam link, the artwork. That folder names a game it does not contain, no scan
        reports it, and the user has to delete it by hand. Verified over a 13-game organize: Undo restored all
        13 archives and left 12 such folders behind.

        Three things have to hold before anything is moved, and each one closes a way this can delete a
        folder the user is relying on:

        - `owned` - the journal has to say this run created the folder. OrganizerService.move() deliberately
          reuses a folder that is already there, so a source/target pair alone cannot distinguish the two,
          and a folder the user made is theirs whatever it now holds. This is the same rule
          AppController._prune_rolled_back_folder() applies, from the same `created_game_dir` flag.
        - `library_root` - the folder has to resolve inside the library the caller named. The journal is a
          file in config/, and both ends of every row flow from it into shutil.move and shutil.rmtree.
        - the organizer's own answer to whether the folder holds nothing but what the app wrote, asked
          rather than reimplemented so the allow-list that protects a player's saves stays in one place.

        A folder still holding an archive was not emptied by this undo. One holding anything the app did not
        write is never moved.
        """
        game_dir = Path(game_dir)
        if not owned:
            self.logger.info("ROLLBACK", f"KEPT_EMPTY_GAME_DIR path=[{game_dir}] reason=[this run did not create it]")
            return False
        try:
            if library_root is not None and not _within(game_dir, Path(library_root)):
                self.logger.warning("ROLLBACK", f"KEPT_EMPTY_GAME_DIR path=[{game_dir}] reason=[outside the library]")
                return False
            if not game_dir.is_dir():
                return False
            if any(item.suffix.lower() in ARCHIVE_EXTENSIONS for item in game_dir.iterdir()):
                return False
            if self.organizer is None:
                return False
            if not self.organizer._folder_is_prunable(game_dir):
                return False
            archive_dir = Path(library_root).expanduser().resolve() / "Archive" if library_root is not None else None
            if archive_dir is not None:
                archive_dir.mkdir(parents=True, exist_ok=True)
                target = archive_dir / game_dir.name
                n = 2
                while target.exists():
                    target = archive_dir / f"{game_dir.name} ({n})"
                    n += 1
                shutil.move(str(game_dir), str(target))
            else:
                shutil.rmtree(game_dir)
            self.logger.info("ROLLBACK", f"PRUNED_EMPTY_GAME_DIR path=[{game_dir}]")
            return True
        except OSError as prune_error:
            self.logger.warning("ROLLBACK", f"PRUNE_FAILED path=[{game_dir}] error=[{type(prune_error).__name__}]")
            return False
