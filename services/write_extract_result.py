"""Extracted from services/catalog_status.py.

    write_extract_result was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from services.catalog_status import STATUS_NAME
from services.catalog_status import status_javascript
from pathlib import Path


def write_extract_result(config, archive, result, logger=None) -> Path:
    """Write a single extract's outcome next to the catalog, so a headless handler leaves a durable answer.

    The protocol handler runs with no window in the foreground: it prints to stdout and exits, and the
    console the browser opened vanishes before the message is read. A file on disk outlives the window
    and is where the reader can look when nothing appeared on screen. The page reads it the next time
    the catalog is opened, so the result is visible without regenerating anything.
    """
    from datetime import datetime

    path = Path(config.library_root) / STATUS_NAME
    status = {
        "ran_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "category": "",
        "destination": str(result.destination),
        "total": 1,
        "extracted": 1 if result.ok else 0,
        "skipped": 0,
        "failed": 0 if result.ok else 1,
        "cancelled": 0,
        "already_done": 0,
        "needs_install": 0,
        "elapsed": "",
        "single_archive": str(archive),
        "single_message": result.message,
    }
    try:
        path.write_text(status_javascript(status), encoding="utf-8")
    except OSError as exc:
        if logger:
            logger.warning("CATALOG", f"STATUS_WRITE_FAILED path=[{path}] error={type(exc).__name__}")
        return None
    if logger:
        logger.info("CATALOG", f"SINGLE_EXTRACT_STATUS_WRITTEN path=[{path}] ok={result.ok}")
    return path
