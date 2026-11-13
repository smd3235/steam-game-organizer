"""Pure utility functions extracted from AppController.

These functions have no dependency on AppController instance state and can be
imported and tested independently. They were previously methods on AppController
that took all their inputs as parameters.
"""

from __future__ import annotations

from pathlib import Path

from core.path_safety import DeletionGuard, PathOutsideAllowedRoot


def artwork_present(archive) -> bool:
    """Whether one archive has artwork, counting an unreadable artwork object as having none.

    Counted per archive rather than inline, because a generator inside the dict literal that builds the
    summary shares an expression with every other number in it: one artwork object that raised took all
    of them down, so a single bad entry cost the archive count, the byte total and the match count as
    well. The worst this can now cost is one game counted as having no picture, which is what a game with
    no picture counts as anyway.
    """
    try:
        return bool(getattr(getattr(archive, "artwork", None), "present", lambda: False)())
    except Exception:
        return False


def primary(group, promotion_key):
    """The copy a group will move: its newest version, chosen exactly as the move itself will choose it.

    Takes a promotion_key callable rather than reaching into services, so it can be tested with a stub.
    Previously AppController._primary.
    """
    return max(group, key=promotion_key)


def needs_conversion(archive, convert_archives: bool) -> bool:
    """True when moving this archive will actually rebuild it into a .7z."""
    if not convert_archives:
        return False
    if archive.path.suffix.lower() == ".7z":
        return False
    try:
        return archive.path.is_file()
    except OSError:
        return False


def primary_size(group, promotion_key) -> int:
    """Size of the archive a group would actually move, i.e. its newest copy. Missing files sort last."""
    primary_archive = primary(group, promotion_key)
    try:
        return primary_archive.path.stat().st_size
    except OSError:
        return 1 << 62


def prune_rolled_back_folder(game_dir, owned, library_root=None, logger=None):
    """Drop a game folder that a rollback has emptied.

    Rolling a game back returns its archive to where it came from but leaves the folder the run created, and
    what stays in it is what this run wrote there: the metadata, and the Steam link and artwork beside it. A
    failed or cancelled run therefore littered the library with folders that describe a game they do not
    hold, which no scan can see and the user has to delete by hand. Only a folder this run created is ever
    removed - one that was already there belongs to the user whatever it contains.
    The folder is moved to Archive/ rather than deleted, so the user can review it before deleting.
    """
    import shutil

    from core.constants import ARCHIVE_EXTENSIONS

    if not owned:
        return
    game_dir = Path(game_dir)
    root = Path(library_root).expanduser().resolve() if library_root is not None else None
    if root is None:
        if logger:
            logger.warning("ORGANIZER", f"ROLLBACK_FOLDER_KEPT path=[{game_dir}] reason=[no library root to prove containment]")
        return
    # A DeletionGuard built from the library root alone: nothing may be pruned outside it.
    guard = DeletionGuard([root])
    try:
        guard.refuse_outside(game_dir, "prune")
        if not game_dir.is_dir():
            return
        if any(item.suffix.lower() in ARCHIVE_EXTENSIONS for item in game_dir.iterdir()):
            if logger:
                logger.info("ORGANIZER", f"ROLLBACK_FOLDER_KEPT path=[{game_dir}] reason=[still holds an archive]")
            return
        archive_dir = root / "Archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        target = archive_dir / game_dir.name
        n = 2
        while target.exists():
            target = archive_dir / f"{game_dir.name} ({n})"
            n += 1
        shutil.move(str(game_dir), str(target))
        if logger:
            logger.info("ORGANIZER", f"ROLLBACK_PRUNED_EMPTY_GAME_DIR path=[{game_dir}] destination=[{target}]")
    except PathOutsideAllowedRoot as refused:
        if logger:
            logger.warning("ORGANIZER", f"ROLLBACK_FOLDER_KEPT path=[{game_dir}] reason=[{refused}]")
    except OSError as prune_error:
        if logger:
            logger.warning("ORGANIZER", f"ROLLBACK_PRUNE_FAILED path=[{game_dir}] error=[{type(prune_error).__name__}]")
