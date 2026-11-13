"""Extracted from tests/test_workflow_smoke.py.

    wait_for_organize was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import time
from tests.wait_until import wait_until


def wait_for_organize(window, seconds=180.0):
    """Wait for the organize run's real completion signal.

    Not `not window.busy`: MainWindow._start() is what sets busy, and only the scan and the undo call it, so
    busy is already False before an organize run begins and a wait on it returns instantly - reporting a
    finished run while the first archive is still being moved. The signal that actually means the run ended
    is OrganizeView._done clearing ctx and handing the archives to MainWindow.finish.
    """
    import tkinter as tk

    root = getattr(wait_until, "_root", None)
    organize = window.views["organize"]
    deadline = time.monotonic() + seconds
    saw_a_ctx = False
    while time.monotonic() < deadline:
        if organize.ctx is not None:
            saw_a_ctx = True
        elif saw_a_ctx:
            return True
        if root is not None:
            try:
                root.update()
            except tk.TclError:
                pass
        time.sleep(0.02)
    raise AssertionError(f"the organize run never finished within {seconds:.0f}s (ctx={'set' if organize.ctx else 'cleared'}, started={saw_a_ctx})")
