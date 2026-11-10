"""Probe Tk from inside the frozen executable and write what it finds.

Run by PyInstaller as a runtime_hook, so it executes in the frozen process before the app's own
main() runs. The point is to see, from inside the frozen context, whether tkinter imports, whether
Tk() returns, and what TCL_LIBRARY/TK_LIBRARY resolve to - all of which the app's own --health
cannot tell you, because that path never touches Tk.
"""

import os
import sys
import traceback
from pathlib import Path

OUT = Path(sys._MEIPASS if getattr(sys, "frozen", False) else ".") / "tk_probe.txt"


def _probe():
    lines = []
    lines.append("python: " + sys.executable)
    lines.append("frozen: " + str(getattr(sys, "frozen", False)))
    lines.append("MEIPASS: " + str(getattr(sys, "_MEIPASS", None)))
    lines.append("TCL_LIBRARY env: " + str(os.environ.get("TCL_LIBRARY")))
    lines.append("TK_LIBRARY env: " + str(os.environ.get("TK_LIBRARY")))
    try:
        import tkinter as tk

        lines.append("import tkinter: OK")
        root = tk.Tk()
        lines.append("Tk() returned: " + repr(root))
        lines.append("title: " + repr(root.title()))
        try:
            root.update_idletasks()
            lines.append("update_idletasks: OK")
        except Exception as exc:
            lines.append("update_idletasks FAILED: " + repr(exc))
        try:
            root.destroy()
            lines.append("destroy: OK")
        except Exception as exc:
            lines.append("destroy FAILED: " + repr(exc))
    except Exception:
        lines.append("Tk probe raised:")
        lines.append(traceback.format_exc())
    OUT.write_text("\n".join(lines), encoding="utf-8")


_probe()
