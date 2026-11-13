"""Extracted from services/batch_extract_service.py.

    BatchItem was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from services.batch_extract_service import CANCELLED
from services.batch_extract_service import DONE
from services.batch_extract_service import FAILED
from services.batch_extract_service import QUEUED
from services.batch_extract_service import SKIPPED
from pathlib import Path


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
