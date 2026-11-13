"""Regression tests for Steam API behaviour.

These tests were extracted from tests/test_regressions.py to keep each test module
focused on one area of the app: API key socket drain behaviour.
"""

from __future__ import annotations

import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import tkinter as tk

from ui.scan_view import ScanView


def _tmp_dir(test_case):
    """A temporary directory that is cleaned up when the test finishes."""
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    test_case.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
    return tmp


class TestApiKeyCheckDoesNotLeakTheSocket(unittest.TestCase):
    """The SteamGridDB connection test read the status code and left the response body undrained.

    `with urlopen(...) as r: code=getattr(r,'status',200)` never touched `r.read()`. Closing the response
    without consuming the body does not shut the SSL socket down cleanly - the connection is left for the
    garbage collector, and every key test printed `ResourceWarning: unclosed <ssl.SSLSocket>` to stderr. It
    was the only one of the five HTTP call sites in the app that skipped the read; the rest all drain.

    This is a leak rather than a crash, which is exactly why it needs a test: nothing fails on its own, and
    an undrained socket per key test is invisible until someone watches the file descriptors.
    """

    def setUp(self):
        from tests.tk_support import require_tk, close_root, sandbox_app
        require_tk(self)
        self.root = tk.Tk()
        self.addCleanup(close_root, self.root)
        self.view = ScanView(tk.Frame(self.root), lambda: None, lambda: None, lambda: None)

    def _run_test_api(self, response, run_mainloop=True):
        """Drive test_api() and wait for the worker thread it spawns.

        Two things this has to get right, both of which hid a failure when it was left to chance:

        test_api posts its result with after(0) from the worker thread, and tkinter refuses a cross-thread after()
        that has no mainloop to hand it to - so with run_mainloop the window runs a short bounded mainloop, and
        without it the update is expected to fail, which is what the RuntimeError test is about.

        And the worker has to be *joined*. Sleeping and hoping left the assertion running before the thread had
        reached its update, which reads as "no exception escaped" every time - a test that cannot fail.
        """
        captured = {}
        tracked = threading.Thread

        class _Tracked(tracked):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                captured["worker"] = self

        with patch("ui.scan_view.urlopen", return_value=response), patch.object(
            threading, "Thread", _Tracked
        ):
            self.view.api_var.set("a-key")
            self.view.test_api()
            if run_mainloop:
                self.root.after(400, self.root.quit)
                self.root.mainloop()
            worker = captured.get("worker")
            if worker is not None:
                worker.join(timeout=5)
            self.root.update()

    def test_the_api_test_drains_the_response_before_closing_it(self):
        calls = []

        class _Response:
            status = 200

            def read(self, *args):
                calls.append("read")
                return b'{"results":[]}'

            def close(self):
                calls.append("close")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        self._run_test_api(_Response())
        self.assertIn("read", calls, "the API test never read the response body, so the socket is never released")
        if "close" in calls:
            self.assertLess(
                calls.index("read"),
                calls.index("close"),
                "the API test closed the response before reading it, so the socket is never released",
            )

    def test_a_successful_api_test_still_reports_success(self):
        """The drain must not cost the check its answer.

        Reading the body is the fix; losing the status code that makes the button say "connection successful"
        would be a regression traded for a clean socket, which is not a trade worth making.
        """

        class _Response:
            status = 200

            def read(self, *args):
                return b'{"results":[]}'

            def close(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        self._run_test_api(_Response())
        self.assertIn("successful", self.view.api_status.cget("text"))

    def test_a_cross_thread_update_that_cannot_land_does_not_kill_the_worker_with_a_traceback(self):
        """The worker posts its result with after(0) from a non-Tk thread.

        When there is no mainloop to hand that to, tkinter raises RuntimeError("main thread is not in main loop")
        rather than a TclError - and the handler only caught TclError, so the exception escaped a daemon thread
        nobody joins. The visible result is a traceback on stderr with no indication of what it was, from a code
        path whose whole job is to report a status.

        threading.excepthook is what decides whether that is silent or noisy, so that is what this watches.
        """
        class _Response:
            status = 200

            def read(self, *args):
                return b"{}"

            def close(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        escaped = []
        previous = threading.excepthook
        threading.excepthook = lambda args: escaped.append(args.exc_type)
        try:
            self._run_test_api(_Response(), run_mainloop=False)
        finally:
            threading.excepthook = previous
        self.assertEqual(
            escaped,
            [],
            f"the API worker died with {escaped} on a cross-thread update it could not deliver",
        )
