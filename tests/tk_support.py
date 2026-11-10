"""Shared tkinter availability handling for the test suite.

Headless machines have no tkinter at all, so the UI modules cannot even be imported without a stand-in.
That stand-in used to be installed unconditionally by one test module, which shadowed the *real* tkinter
whenever a GUI was available and silently downgraded every geometry test to a skip. That made a passing
suite look green while four real UI assertions never ran.

The stub is now only installed when tkinter genuinely cannot be imported, and it always declares Tk so
callers can distinguish "no GUI toolkit here" from "this module was stubbed".
"""

import shutil
import sys
import tempfile
import types
from pathlib import Path

TK_AVAILABLE = True
try:
    import tkinter as _tk

    TK_AVAILABLE = hasattr(_tk, "Tk")
except ModuleNotFoundError:
    TK_AVAILABLE = False

if not TK_AVAILABLE:

    class _Dummy:
        def __init__(self, *args, **kwargs):
            pass

    class _TclError(Exception):
        pass

    tkinter_stub = types.ModuleType("tkinter")
    tkinter_stub.__file__ = "<tkinter stub>"
    tkinter_stub.TclError = _TclError
    tkinter_stub.Tk = None
    tkinter_stub.Toplevel = _Dummy
    tkinter_stub.Frame = _Dummy
    tkinter_stub.Label = _Dummy
    tkinter_stub.Text = _Dummy
    tkinter_stub.Entry = _Dummy
    tkinter_stub.Canvas = _Dummy
    tkinter_stub.BooleanVar = lambda *args, **kwargs: _Dummy()
    tkinter_stub.StringVar = lambda *args, **kwargs: _Dummy()
    tkinter_stub.Radiobutton = _Dummy
    tkinter_stub.Checkbutton = _Dummy
    tkinter_stub.PhotoImage = _Dummy
    sys.modules.setdefault("tkinter", tkinter_stub)

    ttk_stub = types.ModuleType("tkinter.ttk")
    ttk_stub.Style = _Dummy
    ttk_stub.Button = _Dummy
    ttk_stub.Combobox = _Dummy
    ttk_stub.Progressbar = _Dummy
    ttk_stub.Scrollbar = _Dummy
    ttk_stub.Notebook = _Dummy
    ttk_stub.Label = _Dummy
    ttk_stub.Entry = _Dummy
    ttk_stub.LabelFrame = _Dummy
    sys.modules.setdefault("tkinter.ttk", ttk_stub)

    filedialog_stub = types.ModuleType("tkinter.filedialog")
    filedialog_stub.askdirectory = lambda *args, **kwargs: None
    sys.modules.setdefault("tkinter.filedialog", filedialog_stub)

    messagebox_stub = types.ModuleType("tkinter.messagebox")
    messagebox_stub.showinfo = lambda *args, **kwargs: None
    messagebox_stub.showwarning = lambda *args, **kwargs: None
    messagebox_stub.showerror = lambda *args, **kwargs: None
    messagebox_stub.askyesno = lambda *args, **kwargs: True
    sys.modules.setdefault("tkinter.messagebox", messagebox_stub)

    simpledialog_stub = types.ModuleType("tkinter.simpledialog")
    simpledialog_stub.askstring = lambda *args, **kwargs: None
    sys.modules.setdefault("tkinter.simpledialog", simpledialog_stub)


def require_tk(case):
    """Fail, naming the cause, when a test that builds a real window cannot run.

    This was a class-wide `skipUnless(TK_AVAILABLE)`, which had two faults. It hid tests that need no window
    at all, and on the platform this is run on it reported the suite green while the window assertions
    quietly did not run - the same failure AGENTS.md records removing from twenty-nine tests elsewhere. The
    application needs the Tk bindings to start, so a machine without them is a broken install, not a reason
    to skip.
    """
    if not TK_AVAILABLE:
        case.fail("tkinter could not be imported, so a test that builds a real window cannot run. The application needs the Tk bindings to start - this install is missing them.")


def close_root(root):
    """Tear a Tk root down without leaving timers behind, then destroy it.

    The app schedules several self-rescheduling `after` callbacks - the drain loop, the window's clock, the
    review and organize tickers, the metrics refresh. Each one re-arms itself for 15ms to 500ms later, so a
    root destroyed with any still pending makes Tk print `invalid command name ..._tick` to stderr as it fires
    against a dead interpreter. Thirty geometry tests each built a whole Application, which produced around
    two hundred lines of that: noise that trains you to ignore this suite's output, and it hides a real
    failing test in exactly the same place a real one would print.

    Cancelling everything pending before destroy() costs one round trip and silences all of it.
    """
    if root is None:
        return
    try:
        try:
            pending = root.tk.call("after", "info")
            if pending:
                # after info can return a tuple/list of pending ids
                for p in list(pending):
                    try:
                        root.after_cancel(p)
                    except Exception:
                        pass
        except Exception:
            pass
        # Also try to cancel common widget-level jobs if they exist
        try:
            for attr in ("_after_jobs", "_jobs"):
                jobs = getattr(root, attr, None)
                if jobs:
                    for job_id in list(jobs):
                        try:
                            root.after_cancel(job_id)
                        except Exception:
                            pass
                    try:
                        jobs.clear()
                    except Exception:
                        pass
        except Exception:
            pass
    except Exception:
        # A root that is already gone has nothing pending to cancel.
        pass
    try:
        root.destroy()
    except Exception:
        pass


def sandbox_app(case, root, mock=True, project_root=None):
    """An `Application` whose project root is a temporary tree instead of this repository.

    `Application.__init__` builds its own `AppConfig` from `Path(__file__).resolve().parents[1]`, so a test that
    constructs one the ordinary way inherits the developer's own project - and ordinary code paths write to it.
    `MainWindow.show()` appends a line to `logs/organizer.log` on every screen change, `MainWindow.scan()` calls
    `save_api()` and assigns `convert_archives` (each of which saves settings), a finished scan records a
    summary through `save_scan_summary()`, an organize run records into the undo journal, and
    `ArtworkService.__init__` prunes the artwork cache directory it was handed.

    Snapshotting those files and restoring them afterwards is not a fix, and this is why: two concurrent suite
    runs restore each other's writes, and that race left this repository's real `config/settings.json` holding
    `convert_archives: false` - which silently disables zip/rar -> 7z conversion on the next real run. The root
    is redirected instead, so the real files are never written in the first place.

    Patched rather than passed because `Application` reads the project path out of its own module, and adding a
    parameter for this would be a production change made to serve a test-hygiene fix. `project_root` is the
    seam `tests/test_project_state_guard.py` proves itself against: pointed at the real project, that guard has
    to fail, and that has to be a one-line edit somebody can actually make.
    """
    from unittest.mock import patch
    import app.application as application
    from core.config import AppConfig

    sandbox = Path(project_root) if project_root is not None else Path(tempfile.mkdtemp(prefix="organizer-test-root-"))
    games = sandbox / "Games"
    if project_root is None:
        case.addCleanup(shutil.rmtree, sandbox, ignore_errors=True)
        games.mkdir(parents=True, exist_ok=True)
    with patch.object(application, "AppConfig", lambda *_a, **_k: AppConfig(sandbox, library_root=games)):
        return application.Application(root, mock=mock)
