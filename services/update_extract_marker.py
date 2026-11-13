"""Extracted from services/catalog_status.py.

    update_extract_marker was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import json
from services.catalog_status import extract_marker_path
from services.catalog_status import read_extract_marker
from pathlib import Path


def update_extract_marker(destination, *, logger=None, **updates):
    """Merge updates into an existing `.sgo-extract-info` marker.

    Best-effort and non-destructive: preserves existing fields and only writes when the
    marker already exists or `create_if_missing=True` is passed. Returns the updated
    marker dict on success, else None.
    """
    create_if_missing = bool(updates.pop("create_if_missing", False))
    dest = Path(destination)
    marker = extract_marker_path(dest)
    data = read_extract_marker(dest)
    if data is None:
        if not create_if_missing or not dest.is_dir():
            return None
        data = {"extracted_root": str(dest)}
    changed = False
    for key, value in updates.items():
        if value is None:
            if key in data:
                data.pop(key, None)
                changed = True
            continue
        if data.get(key) != value:
            data[key] = value
            changed = True
    if not changed and marker.exists():
        return data
    try:
        marker.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        if logger:
            logger.warning("CATALOG", f"MARKER_UPDATE_FAILED path=[{marker}] error={type(exc).__name__}")
        return None
    return data
