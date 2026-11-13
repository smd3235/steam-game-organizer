"""Extracted from services/batch_extract_service.py.

    plan_batch was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from pathlib import Path
from core.safe_folder_name import safe_folder_name
from services.archive_service import ArchiveService
from services.batch_extract_service import BatchPlan
from services.batch_item import BatchItem
from services.catalog_status import already_extracted
from services.installer_detect import NEEDS_INSTALL_DIRNAME


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
    result = service.discover(root / category, use_cache=False) if category else service.discover(root, use_cache=False)

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
