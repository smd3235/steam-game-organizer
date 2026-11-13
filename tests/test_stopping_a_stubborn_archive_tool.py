"""Extracted from tests/test_services.py.

    TestStoppingAStubbornArchiveTool was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from core.logger import AppLogger
from services.extract_service import ExtractService
from services.organizer_service import OrganizerService


class TestStoppingAStubbornArchiveTool(unittest.TestCase):
    """Ending a tool that will not die must not raise on the way out.

    Both helpers ask politely, then kill, then wait with a timeout. The wait is the only one of the three
    that can raise `subprocess.TimeoutExpired`, which descends from `SubprocessError` and therefore from
    `Exception` - not from `OSError`. A `suppress(OSError, AttributeError)` written for the two signals
    therefore let it straight through, out of a `finally` block, where it replaces whatever was already
    failing: the cancellation or the build error is lost and a traceback about the shutdown arrives instead.
    """

    class _Stubborn:
        """Running, ignores both signals, and so is the wait that finally gives up."""

        def __init__(self):
            self.terminated = False
            self.killed = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd="7z", timeout=timeout or 0)

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.logger = AppLogger(Path(self.folder.name) / "log.log")

    def test_the_organizers_stop_does_not_raise_when_the_wait_gives_up(self):
        process = self._Stubborn()
        OrganizerService._stop_tool(process, grace=0.01)
        self.assertTrue(process.terminated, "the tool was not asked to stop politely first")
        self.assertTrue(process.killed, "kill() was not used as the backstop for a tool that ignored the first ask")

    def test_the_extractors_stop_does_not_raise_when_the_wait_gives_up(self):
        process = self._Stubborn()
        ExtractService._stop(process, grace=0.01)
        self.assertTrue(process.killed)
