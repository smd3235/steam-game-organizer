"""The catalog's batch Extract: a per-category Extract all and a whole-library Extract all.

The rule that shapes all of this is in core/uri_actions.py and is asserted here rather than assumed. A batch link
names a category and nothing else - no archive paths - so the app enumerates the library itself. If the link could
carry its own list, the registered handler would be a way for any web page the user visits to choose what gets
unpacked on their machine, and the "is this inside the library" check that makes the single extract safe would
have to hold once per entry instead of once.

The rest is about the two things a batch has that a single extract does not: it runs for hours, so it has to
report where it is and be stoppable; and it touches many archives, so one bad one must not cost the rest.
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from core.constants import LIBRARY_RESERVED_DIRS
from core.logger import AppLogger
from core.uri_actions import UriRefused
from core.parse_batch_uri import parse_batch_uri
from services import batch_extract_service
from services.batch_extract_service import CANCELLED, DONE, EXTRACTING, FAILED, BatchExtractJob
from services.plan_batch import plan_batch
from services.catalog_service import CatalogService
from services.extract_service import ExtractResult, ExtractService
from tests.test_services import _write_stub
from tests.test_helpers import _game

# RunningABatchReportsEveryGame extracted to tests\running_a_batch_reports_every_game.py — see that module for its definition.
from tests.test_running_a_batch_reports_every_game import RunningABatchReportsEveryGame

# A stub archiver that ignores the real 7z argument list and just prints progress lines, so extract() can be
# driven end to end - real Popen, real pipe, real cancel check - without a real 7-Zip. Written through the
# project's own _write_stub so it is a form this platform can actually execute.
_STUB_PROGRESS = """#!/usr/bin/env python3
import sys
for line in ("10% 1 - a", "50% 2 - b", "90% 3 - c"):
    print(line)
    sys.stdout.flush()
sys.exit(0)
"""

class CancelReachesTheArchiveTool(unittest.TestCase):
    """extract() accepted a cancel callable and never called it.

    A Cancel button wired to a parameter nothing reads looks real and does nothing: 7z runs to the end of the
    archive. Asserted against the real extract() driving a real child process, because asserting it against a
    stub would only prove the stub is cancellable.
    """

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.logger = AppLogger(self.root / "x.log")
        self.archive = self.root / "Game.zip"
        with zipfile.ZipFile(self.archive, "w") as handle:
            handle.writestr("game/data.bin", b"a" * 5000)
        bin_dir = self.root / "bin"
        _write_stub(bin_dir, "7z", _STUB_PROGRESS)
        self.tool = bin_dir / ("7z.bat" if os.name == "nt" else "7z")
        self.assertTrue(self.tool.is_file(), f"the stub archiver was not written where it can be run: {self.tool}")

    def _service(self):
        service = ExtractService(self.logger)
        service.find_tool = lambda: (str(self.tool), None)
        # The real check needs a writable destination and enough room; neither is what this is testing.
        service.check_space = lambda archive, destination: ""
        return service

    def test_a_cancel_stops_the_run_instead_of_being_ignored(self):
        result = self._service().extract(self.archive, self.root / "out", cancel=lambda: True)
        self.assertFalse(result.ok, "a cancelled extraction reported success")
        self.assertIn("part-way", result.message, f"a cancelled extraction did not say where its files are: {result.message!r}")

    def test_a_cancel_that_never_arrives_still_completes(self):
        """The other half: the fix cannot simply refuse to run, or every extraction would report cancelled."""
        result = self._service().extract(self.archive, self.root / "out", cancel=lambda: False)
        self.assertTrue(result.ok, f"an uncancelled extraction failed: {result.message}")

    def test_no_cancel_callable_behaves_as_before(self):
        result = self._service().extract(self.archive, self.root / "out")
        self.assertTrue(result.ok, f"extraction without a cancel callable failed: {result.message}")

if __name__ == "__main__":
    unittest.main()

