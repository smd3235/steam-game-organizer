"""Extracted from tests/test_batch_extract.py.

    RunningABatchReportsEveryGame was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import tempfile
import unittest
from pathlib import Path
from core.logger import AppLogger
from services import batch_extract_service
from services.batch_extract_service import CANCELLED
from services.batch_extract_service import DONE
from services.batch_extract_service import EXTRACTING
from services.batch_extract_service import FAILED
from services.batch_extract_service import BatchExtractJob
from services.batch_extract_service import plan_batch
from services.extract_service import ExtractResult
from tests.test_batch_extract import _game
from services.extract_service import ExtractService


class RunningABatchReportsEveryGame(unittest.TestCase):
    """The queue's contract with the window, exercised without Tk and without a real 7-Zip.

    What is under test is the shape of what comes back - one verdict per game, a transition attributed to the
    right game, and a run that continues past a failure - because those are what the window is built on and none
    of them is visible from the catalog page.
    """

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "Games"
        self.dest = Path(temporary.name) / "Out"
        self.dest.mkdir(parents=True)
        self.logger = AppLogger(Path(temporary.name) / "x.log")
        self.seen = []
        self._fake_tool(fail_for=())

    def _fake_tool(self, fail_for=()):
        """Replace the 7z call with something that reports progress and obeys cancel.

        Written as a real class taking the constructor the job actually calls, so on_progress stays bound rather
        than being bypassed - a stub that ignored the callback would pass a test about progress attribution.
        """

        class _Fake:
            def __init__(self, logger, on_progress=None):
                self.on_progress = on_progress

            def extract(self, archive, destination, password="", cancel=None):
                for percent in (10, 50, 90):
                    if cancel and cancel():
                        return ExtractResult(archive, destination, False, "stopped part-way")
                    if self.on_progress:
                        self.on_progress(stage="extracting", percent=percent, name=archive.stem)
                if any(word in archive.stem for word in fail_for):
                    return ExtractResult(archive, destination, False, "Extraction failed (exit 2)", code=2)
                destination.mkdir(parents=True, exist_ok=True)
                (destination / "game.bin").write_bytes(b"a" * 1000)
                return ExtractResult(archive, destination, True, "Extracted 1 file(s)", extracted_bytes=1000, file_count=1, code=0)

        self.addCleanup(setattr, batch_extract_service, "ExtractService", batch_extract_service.ExtractService)
        batch_extract_service.ExtractService = _Fake

    def _games(self, *names):
        for name in names:
            _game(self.root, "Idle", name, 4096)

    def _run(self, category="", cancel_after=None, fail_for=()):
        if fail_for:
            self._fake_tool(fail_for=fail_for)
        plan = plan_batch(self.root, self.dest, category, self.logger)
        job = BatchExtractJob(plan, self.logger)
        started = []

        def record(stage="", item=None, detail=""):
            if item is not None:
                self.seen.append((stage, item.name, item.state))
                if cancel_after and item.state == "extracting":
                    started.append(item.name)
                    if len(started) >= cancel_after:
                        job.cancel()

        job.on_progress = record
        job.run()
        return job

    def test_every_game_gets_a_verdict(self):
        self._games("Alpha", "Beta", "Gamma")
        job = self._run()
        self.assertEqual([item.state for item in job.plan.items], [DONE, DONE, DONE])
        self.assertEqual(job.succeeded, 3)

    def test_each_game_reports_its_own_transitions(self):
        """Progress attributed to the wrong row is worse than no progress: it makes the window look stuck on one
        game while a different one is actually being unpacked."""
        self._games("Alpha", "Beta")
        self._run()
        self.assertEqual({name for _, name, _ in self.seen}, {"Alpha", "Beta"})
        for name in ("Alpha", "Beta"):
            with self.subTest(game=name):
                # On the row's state, not the event name. The job reports "progress" for every tick of a running
                # extraction and "item" when the verdict lands, so a test keyed on the stage would read a game that
                # was being unpacked continuously as one that never reported itself - which is the assertion
                # reading the wrong field rather than the window being wrong.
                self.assertTrue(any(n == name and state == EXTRACTING for _, n, state in self.seen), f"{name} never reported itself as extracting; saw {sorted({(n, state) for _, n, state in self.seen})}")

    def test_one_failing_game_does_not_stop_the_rest(self):
        """The same rule the organize run was given after one unmovable archive aborted a whole library."""
        self._games("Alpha", "Broken", "Gamma")
        job = self._run(fail_for=("Broken",))
        states = {item.name: item.state for item in job.plan.items}
        self.assertEqual(states, {"Alpha": DONE, "Broken": FAILED, "Gamma": DONE})
        self.assertEqual((job.succeeded, job.failed), (2, 1))

    def test_a_failure_names_its_reason(self):
        """ "Failed" with no reason is an outcome nobody can act on."""
        self._games("Broken")
        job = self._run(fail_for=("Broken",))
        self.assertIn("exit 2", job.plan.items[0].detail)

    def test_a_cancelled_run_marks_the_games_it_never_reached(self):
        """Anything still queued when the run ends was never started, and a row that stays 'Waiting' forever is
        how a stopped run comes to look like a hung one."""
        self._games("Alpha", "Beta", "Gamma")
        job = self._run(cancel_after=1)
        states = [item.state for item in job.plan.items]
        self.assertNotIn("queued", states, f"a game was left queued after the run ended: {states}")
        self.assertTrue(any(state == CANCELLED for state in states), f"nothing was marked cancelled: {states}")

    def test_a_cancel_stops_the_tool_rather_than_only_the_next_game(self):
        """Cancelling between games would still leave the current archive running to completion, which for a 4 GB
        unpack is most of the wait the user asked to stop."""
        self._games("Alpha", "Beta")
        job = self._run(cancel_after=1)
        self.assertEqual(job.cancelled, 2)
        self.assertEqual(job.succeeded, 0, "the run finished games after being asked to stop")

    def test_the_summary_counts_what_happened(self):
        self._games("Alpha", "Broken", "Gamma")
        job = self._run(fail_for=("Broken",))
        text = job.summary()
        self.assertIn("2 extracted", text)
        self.assertIn("1 failed", text)

    def test_an_installer_game_is_flagged_in_the_row_and_the_run(self):
        """An installer repack is unpacked, not installed, and that has to read on both the row and the summary."""
        from services.extract_service import ExtractResult

        class _InstallerFake:
            def __init__(self, logger, on_progress=None):
                self.on_progress = on_progress

            def extract(self, archive, destination, password="", cancel=None):
                destination.mkdir(parents=True, exist_ok=True)
                (destination / "setup.exe").write_bytes(b"MZ")
                (destination / "setup-1.bin").write_bytes(b"a" * 1000)
                return ExtractResult(archive, destination, True, "Extracted 2 files", extracted_bytes=2000, file_count=2, code=0, needs_install=True)

        self._games("Repack")
        batch_extract_service.ExtractService = _InstallerFake
        job = self._run()
        item = job.plan.items[0]
        self.assertEqual(item.state, DONE)
        self.assertIn("needs install", item.detail.lower(), f"the row's detail did not flag the installer: {item.detail!r}")
        self.assertEqual(job.needs_install, 1, "the run did not count the installer")
        self.assertIn("need install", job.summary().lower(), "the summary did not surface installers at the run level")

    def test_remaining_drains_to_zero(self):
        self._games("Alpha", "Beta")
        job = self._run()
        self.assertEqual(job.remaining(), 0, "the window's remaining count would never reach zero")

    def test_an_empty_plan_finishes_cleanly_rather_than_hanging(self):
        """Every game already unpacked is the state the button is in on its second click, and it must report
        itself finished rather than waiting for an archive that will never come."""
        self._games("Alpha")
        destination = self._plan_and_fill()
        job = BatchExtractJob(destination, self.logger)
        job.run()
        self.assertTrue(job.done.is_set())
        self.assertEqual(job.summary().split()[0], "0")

    def _plan_and_fill(self):
        plan = plan_batch(self.root, self.dest, "Idle", self.logger)
        for item in plan.items:
            item.destination.mkdir(parents=True, exist_ok=True)
            (item.destination / "done.bin").write_bytes(b"x")
        return plan_batch(self.root, self.dest, "Idle", self.logger)
