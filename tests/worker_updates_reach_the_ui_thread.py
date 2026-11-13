"""Extracted from tests/test_run_reporting.py.

    WorkerUpdatesReachTheUiThread was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import tkinter as tk
import threading
import unittest
from tests.tk_support import sandbox_app
from tests.tk_support import close_root


class WorkerUpdatesReachTheUiThread(unittest.TestCase):
    """Scan, verification and organization all report progress from worker threads. Tk is not thread-safe,
    so the reporting path must never call into it directly."""

    def setUp(self):
        self.root = tk.Tk()
        self.app = sandbox_app(self, self.root)

    def tearDown(self):
        try:
            self.app.shutdown()
        except Exception:
            pass
        close_root(self.root)

    def test_a_worker_thread_dispatch_does_not_run_the_callback_inline(self):
        reached = threading.Event()

        def worker():
            self.app._dispatch(reached.set)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(5)
        self.assertFalse(reached.is_set(), "a worker-thread dispatch ran the callback on the worker")
        for _ in range(10):
            self.root.update()
            if reached.is_set():
                break
        self.assertTrue(reached.is_set(), "a queued update never reached the Tk thread")

    def test_the_tk_thread_still_updates_inline(self):
        seen = []
        self.app._dispatch(lambda: seen.append(1))
        self.assertEqual(seen, [1], "a main-thread dispatch stopped running inline")

    def test_the_drain_is_bounded_so_a_flood_cannot_starve_the_event_loop(self):
        count = []

        def worker():
            for index in range(600):
                self.app._dispatch(lambda i=index: count.append(i))

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(5)
        # Driving one drain directly is the only way to observe the boundary: root.update() re-fires timers
        # that fall due while it is running, so several drains can legitimately happen inside one call.
        self.app._pump()
        self.assertEqual(len(count), 200, "a single drain did not stop at its bound")
        for _ in range(30):
            self.root.update()
        self.assertEqual(len(count), 600, "queued updates were dropped rather than drained")

    def test_one_bad_callback_does_not_stop_the_drain_loop(self):
        """The drain reschedules itself at the end, so an exception escaping a callback used to stop every
        later UI update for the rest of the session: the worker carried on and the screen froze."""
        reached = []

        def worker():
            self.app._dispatch(lambda: (_ for _ in ()).throw(ValueError("boom")))
            self.app._dispatch(lambda: reached.append(1))

        threading.Thread(target=worker, daemon=True).start()
        for _ in range(10):
            self.root.update()
        self.assertEqual(reached, [1], "a failing callback stopped the drain loop")

    def test_shutdown_stops_the_drain_loop(self):
        self.app.shutdown()
        count = []
        worker = threading.Thread(target=lambda: self.app._dispatch(lambda: count.append(1)))
        worker.start()
        worker.join(5)
        for _ in range(5):
            self.root.update()
        self.assertEqual(count, [], "a queued update ran after shutdown")
