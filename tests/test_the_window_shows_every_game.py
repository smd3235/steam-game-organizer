"""Extracted from tests/test_batch_extract.py.

    TheWindowShowsEveryGame was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import tempfile
import time
import unittest
from pathlib import Path
from core.logger import AppLogger
from services.batch_extract_service import EXTRACTING
from services.batch_extract_service import BatchExtractJob


class TheWindowShowsEveryGame(unittest.TestCase):
    """The window is the only place the run is visible, so the things it promises are asserted on the widgets.

    Driven without the job: the queue is filled by hand and the rows rendered, which is what isolates the display
    from the extraction. The run itself is covered by RunningABatchReportsEveryGame.
    """

    def setUp(self):
        from tests.tk_support import close_root, require_tk

        require_tk(self)
        import tkinter as tk

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root_dir = Path(temporary.name)
        self.logger = AppLogger(self.root_dir / "x.log")

        self.root = tk.Tk()
        self.addCleanup(close_root, self.root)

    def _plan(self, already_done=0):
        from services.batch_extract_service import BatchItem, BatchPlan

        plan = BatchPlan(destination=self.root_dir / "Out", category="Idle", already_done=already_done)
        for index, name in enumerate(("Alpha", "Beta", "Gamma"), 1):
            plan.items.append(BatchItem(archive=Path(f"C:/library/{name}.zip"), destination=Path(f"C:/out/{name}"), name=name, size=index * 1024 * 1024))
        plan.total_bytes = sum(item.size for item in plan.items)
        return plan

    def _window(self, already_done=0):
        from ui.batch_extract_window import BatchExtractWindow

        self.plan = self._plan(already_done)
        self.window = BatchExtractWindow(self.root, self.plan, self.logger)
        return self.window

    def _text(self):
        # "end-1c", not "end". A Tk text always ends in a newline, so reading to "end" counts a phantom
        # empty row past the last game and every row count here would be one too high.
        return self.window.list.get("1.0", "end-1c")

    def _labels(self, widget):
        found = []
        for child in widget.winfo_children():
            try:
                found.append(str(child.cget("text")))
            except Exception:
                pass
            found.extend(self._labels(child))
        return found

    def test_every_game_in_the_plan_has_a_row_before_anything_runs(self):
        window = self._window()
        window._render_all()
        self.root.update()
        text = self._text()
        for name in ("Alpha", "Beta", "Gamma"):
            self.assertIn(name, text, f"{name} has no row, so there is no way to see its status")
        self.assertEqual(len(window.rows), 3, "a game in the plan has no row to update")

    def test_a_row_shows_the_name_the_size_and_the_status(self):
        window = self._window()
        window._render_all()
        self.root.update()
        line = self._text().splitlines()[0]
        self.assertIn("Alpha", line)
        self.assertIn("1 MB", line, f"the row does not show how big the game is: {line!r}")
        self.assertIn("Waiting", line, "a game that has not started does not say so")

    def test_a_row_is_rewritten_in_place_rather_than_reinserted(self):
        """Deleting and reinserting would shift every row below it, so the list would jump under the reader on
        every progress event - a hundred and seventy-six games would be unreadable."""
        window = self._window()
        window._render_all()
        self.root.update()
        before_lines = self._text().splitlines()
        item = window.plan.items[1]
        item.state = EXTRACTING
        item.percent = 42
        item.detail = "42%  game/data.bin"
        window._update_row(item)
        self.root.update()
        self.assertEqual(len(self.window.rows), 3, "the row map was rebuilt instead of the rows being updated")
        self.assertEqual(len(self._text().splitlines()), 3, "updating a row changed the number of rows")
        self.assertEqual(self._text().splitlines()[0], before_lines[0], "an earlier row moved")
        self.assertIn("Extracting", self._text().splitlines()[1], "the row did not take its new status")
        self.assertIn("42%", self._text().splitlines()[1], "the row did not take its new detail")

    def test_the_header_states_the_count_and_the_destination(self):
        window = self._window()
        text = " ".join(self._labels(window))
        self.assertIn("Extracting 3 games", text)
        self.assertIn(str(window.plan.destination), text)

    def test_the_header_says_how_many_were_left_alone(self):
        """A user who clicks Extract All on 176 games and watches 12 run has to know the other 164 were left
        alone on purpose, or the button looks broken."""
        window = self._window(already_done=164)
        self.root.update()
        self.assertIn("164 already unpacked", " ".join(self._labels(window)))

    def test_the_metrics_carry_the_numbers_a_long_run_needs(self):
        """Done, remaining, bytes unpacked, elapsed, throughput and free space. The last is the one that turns a
        healthy run into a failing one, and a batch is the run that can fill a disk."""
        window = self._window()
        window._render_all()
        job = BatchExtractJob(window.plan, self.logger)
        job.started_at = time.monotonic() - 30
        job.written = 50 * 1024 * 1024
        window.job = job
        window._refresh_metrics()
        self.root.update()
        metrics = str(window.metrics.cget("text"))
        self.assertIn("unpacked", metrics)
        self.assertIn("free on the drive", metrics)
        self.assertIn("/s", metrics, "no throughput is reported")
        self.assertIn("3 remaining", str(window.remaining.cget("text")))

    def test_the_stop_button_asks_the_job_to_stop_and_says_so(self):
        window = self._window()
        job = BatchExtractJob(window.plan, self.logger)
        window.job = job
        window._stop()
        self.root.update()
        self.assertTrue(job.cancel_requested, "the Stop button did not reach the job")
        self.assertIn("STOPPING", str(window.cancel_btn.cget("text")))
        self.assertEqual(str(window.cancel_btn.cget("state")), "disabled", "the Stop button stayed live while stopping, so it could be pressed twice")

    def test_closing_mid_run_cancels_first_rather_than_leaving_the_tool_writing(self):
        window = self._window()
        job = BatchExtractJob(window.plan, self.logger)
        window.job = job
        window._on_close()
        self.root.update()
        self.assertTrue(job.cancel_requested, "closing the window left a run going with no window to stop it")
        self.assertTrue(window.winfo_exists(), "the window closed while a run was still writing")

    def test_a_finished_run_names_the_games_that_failed(self):
        """A run of 176 with three failures is a success with caveats, and the caveats should not require
        scrolling through a hundred rows to find."""
        from services.batch_extract_service import FAILED as STATE_FAILED

        window = self._window()
        job = BatchExtractJob(window.plan, self.logger)
        window.job = job
        window.plan.items[1].state = STATE_FAILED
        window.plan.items[1].detail = "Extraction failed (exit 2)"
        job.failed = 1
        job.succeeded = 2
        window._finish()
        self.root.update()
        summary = str(window.summary.cget("text"))
        self.assertIn("Failed: Beta", summary)
        self.assertIn("2 extracted", summary)
