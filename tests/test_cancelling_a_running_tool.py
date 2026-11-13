"""Extracted from tests/test_services.py.

    TestCancellingARunningTool was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import sys
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from app.jobs import JobContext
from core.exceptions import CancellationError
from core.logger import AppLogger
from services.organizer_service import OrganizerService


class TestCancellingARunningTool(unittest.TestCase):
    """Cancel has to reach the archive tool, not just the Python that launched it.

    The worker spends minutes blocked reading the tool's progress pipe, so it cannot notice a cancel by
    looking for one. Without a watcher thread killing the child, Cancel and closing the window both sat
    there until a multi-GB build finished on its own - which is what "pressing cancel freezes the app"
    looked like from the outside.
    """

    # Stands in for a level-9 build: runs, produces nothing, and would never end on its own.
    NEVER_ENDING = "import time\nwhile True: time.sleep(0.05)"

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.service = OrganizerService(AppLogger(Path(self.folder.name) / "log.log"))

    def test_cancelling_a_job_stops_the_running_tool_and_raises(self):
        ctx = JobContext("CANCELME")
        result = {}

        def run():
            try:
                result["code"] = self.service._run_tool([sys.executable, "-c", self.NEVER_ENDING], "compressing", lambda *a, **k: None, ctx=ctx)
            except BaseException as exc:
                result["error"] = exc

        # Daemon, so a failure here can never leave this process waiting on a thread at exit.
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        time.sleep(0.5)
        self.assertTrue(worker.is_alive(), "the tool finished on its own, so nothing was being tested")
        cancel_at = time.monotonic()
        ctx.cancel()
        worker.join(timeout=25)
        self.assertFalse(worker.is_alive(), "the tool was still running 25s after the cancel")
        self.assertLess(time.monotonic() - cancel_at, 15, "the cancel took too long to take effect")
        self.assertIsInstance(result.get("error"), CancellationError, "a cancelled tool must not be reported as a normal exit code")
        self.assertNotIn("code", result)

    def test_a_tool_that_finishes_normally_reports_its_real_exit_code(self):
        code, detail = self.service._run_tool([sys.executable, "-c", 'print("built")'], "compressing", lambda *a, **k: None, ctx=JobContext("OK"))
        self.assertEqual(code, 0, "a tool that finishes on its own must report its real exit code")
        self.assertIn("built", detail)

    def test_the_watcher_releases_its_thread_when_the_tool_finishes_normally(self):
        # A watcher left waiting on the cancel event would leak one thread per conversion, and an overnight
        # run is hundreds of them.
        before = threading.active_count()
        for _ in range(20):
            self.service._run_tool([sys.executable, "-c", "pass"], "compressing", lambda *a, **k: None, ctx=JobContext("OK"))
        for _ in range(40):
            if threading.active_count() <= before:
                break
            time.sleep(0.05)
        self.assertLessEqual(threading.active_count(), before, "the cancel watcher thread was not released")

    def test_a_failed_tool_is_not_mistaken_for_a_cancelled_one(self):
        # The two look alike from outside - a non-zero exit and a signal - and reporting a cancel as a
        # conversion failure would blame the user for pressing Cancel, and vice versa.
        code, _ = self.service._run_tool([sys.executable, "-c", "raise SystemExit(3)"], "compressing", lambda *a, **k: None, ctx=JobContext("OK"))
        self.assertEqual(code, 3, "a genuine tool failure was swallowed or reported as a cancel")
