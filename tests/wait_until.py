"""Extracted from tests/test_workflow_smoke.py.

    wait_until was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import time


def wait_until(predicate, seconds=90.0, what="condition"):
    """Poll until the predicate holds. The Tk thread has to keep turning, so this updates as it waits."""
    import tkinter as tk

    root = getattr(wait_until, "_root", None)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if predicate():
                return True
        except Exception:
            pass
        if root is not None:
            try:
                root.update()
            except tk.TclError:
                pass
        time.sleep(0.02)
    raise AssertionError(f"{what} did not happen within {seconds:.0f}s")
