import queue
import threading
import tkinter as tk
from pathlib import Path
from core.config import AppConfig
from core.logger import AppLogger
from core.state import StateStore
from app.events import EventBus
from app.jobs import JobManager
from app.controller import AppController
from services.archive_service import ArchiveService
from services.steam_service import SteamService
from services.artwork_service import ArtworkService
from services.organizer_service import OrganizerService
from services.rollback_service import RollbackService
from services.library_service import LibraryService
from services.catalog_service import CatalogService
from ui.main_window import MainWindow
from core.constants import VERSION


class Application:
    def __init__(self, root, mock=False, config=None):
        self.root = root
        self._closed = False
        # Recorded on the Tk thread during construction, so _dispatch can tell an inline call from a worker.
        self._main_thread = threading.get_ident()
        self._pending = queue.Queue()
        self._pump_handle = None
        self._sweep_handle = None
        # Reuse the config from the entry point when one is passed in, so the
        # setup wizard and the main window share settings written to the same folder.
        if config is not None:
            self.config = config
        else:
            self.config = AppConfig(Path(__file__).resolve().parents[1])
        self.config.mock_mode = mock
        self.config.ensure_directories()
        self.logger = AppLogger(self.config.log_file)
        self.state = StateStore()
        self.state.update(developer_mode=self.config.developer_mode)
        self.bus = EventBus()
        self.jobs = JobManager()
        services = type("Services", (), {})()
        services.archive = ArchiveService(self.logger, mock=mock, config_dir=self.config.config_dir)
        services.steam = SteamService(self.logger, mock=mock, cache_file=self.config.config_dir / "steam-matches.json")
        services.artwork = ArtworkService(
            self.config.artwork_dir,
            self.logger,
            self.config.settings.get("steamgriddb_api_key", ""),
            self.config.settings.get("artwork_cache_days", 10),
        )
        services.organizer = OrganizerService(self.logger, convert_archives=lambda: self.config.convert_archives)
        services.rollback = RollbackService(self.config.project_root, self.logger, organizer=services.organizer)
        services.library = LibraryService(self.logger, config_dir=self.config.config_dir)
        services.catalog = CatalogService(self.logger, extract_folders=self.config.extract_folders)
        self.services = services
        self.controller = AppController(self.state, self.bus, self.logger, services, self.jobs, dispatch=self._dispatch)
        self.controller.config = self.config
        self.window = MainWindow(root, self.config, self.state, self.bus, self.controller, self.logger, self.jobs)
        # Done once at startup rather than per run: the links this app writes into the library are plain .html
        # files, and without a recorded handler the desktop offers to install a browser instead of opening one.
        # Skipped in mock mode so a test run never writes to the real user profile.
        # There is deliberately no handler registration here any more. It used to write the XDG mimeapps.list
        # on every launch, which is a Linux file this platform never reads - so every start wrote state nobody
        # looked at. Windows also refuses to let a program change a default file association, which is the
        # correct behaviour: an app that could do it would be hijacking every .html on the machine. The catalog
        # is plain .html and Windows already opens it.
        root.protocol("WM_DELETE_WINDOW", self.shutdown)
        # Starts the drain loop now rather than on the first worker update, so a callback queued before the
        # first progress event still runs even if no further event follows it.
        self._pump_handle = self.root.after(15, self._pump)
        # A killed or cancelled conversion leaves a staging folder of extracted game data behind, and it was
        # only ever reported, never cleared - so it sat on the library volume until someone noticed. Nothing
        # can be in flight at startup, which is the one moment clearing them is unambiguously safe. Deferred
        # off the constructor so walking a large folder never delays the window appearing. The handle is kept
        # so shutdown() can disarm it: this is a one-shot timer, so quitting inside the first 1200ms used to
        # leave it armed and walking the library folder during shutdown.
        self._sweep_handle = root.after(1200, self._sweep_stale_build_dirs)

    def _sweep_stale_build_dirs(self):
        # Belt and braces with the shutdown() cancellation below: if this runs after the app is closed it
        # walks the whole library folder for nothing, and any Tk call it makes from here is against a root
        # that no longer exists.
        if self._closed:
            return
        try:
            removed, reclaimed = self.services.organizer.sweep_stale_build_dirs(self.config.library_root)
        except Exception as exc:
            self.logger.warning("APPLICATION", f"STALE_BUILD_SWEEP_FAILED error={type(exc).__name__}")
            return
        if removed:
            self.logger.info("APPLICATION", f"STALE_BUILD_SWEEP_DONE folders={removed} bytes={reclaimed}")

    def _dispatch(self, fn):
        """Hand a UI update to the Tk thread.

        Scan, verification and organization all report progress from worker threads, and Tk is not
        thread-safe: calling into it from one is undefined, and the failure is not always a TclError. The
        original guard called winfo_exists() from whichever thread arrived, so a worker could raise
        RuntimeError("main thread is not in main loop") straight through the progress path and take the
        whole job down. Worker threads now only touch a queue, and the Tk thread drains it.

        A call that is already on the Tk thread still runs inline, so main-thread callers keep the
        immediate behaviour they had.
        """
        if self._closed:
            return
        if threading.get_ident() == self._main_thread:
            try:
                fn()
            except tk.TclError:
                pass
            return
        self._pending.put(fn)

    def _pump(self):
        """Drain queued UI work. Runs on the Tk thread only, and reschedules itself while the app is open."""
        self._pump_handle = None
        # Bounded per tick: an unbounded drain would starve the event loop on a run producing thousands of
        # progress records, which is the exact case the live display exists to serve.
        for _ in range(200):
            try:
                fn = self._pending.get_nowait()
            except queue.Empty:
                break
            if self._closed:
                return
            try:
                fn()
            except tk.TclError:
                pass
            except Exception as exc:
                # The drain reschedules itself at the end of this method, so an exception escaping here would
                # stop the loop for the rest of the session and every later UI update would be dropped in
                # silence while the worker carried on. One bad callback must cost one callback.
                self.logger.warning("APPLICATION", f"UI_UPDATE_FAILED error={type(exc).__name__} detail={str(exc)[:200]}")
        if not self._closed:
            self._pump_handle = self.root.after(15, self._pump)

    def run(self):
        self.logger.info("APPLICATION", f"START version={VERSION}")
        self.root.mainloop()
        return 0

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        self.state.update(phase="stopping", cancel_requested=True)
        self.logger.info("APPLICATION", "SHUTDOWN_REQUESTED")
        if self._pump_handle is not None:
            try:
                self.root.after_cancel(self._pump_handle)
            except tk.TclError:
                pass
            self._pump_handle = None
        if self._sweep_handle is not None:
            try:
                self.root.after_cancel(self._sweep_handle)
            except tk.TclError:
                pass
            self._sweep_handle = None
        try:
            self.window.shutdown()
        except Exception as exc:
            self.logger.debug("APPLICATION", f"WINDOW_SHUTDOWN_IGNORED {type(exc).__name__}")
        # wait=False, and this is the whole fix for "closing the window hangs". shutdown() ran on the Tk
        # thread with wait=True, so the window froze until every running job returned - and a conversion in
        # the middle of a multi-GB build could be twenty minutes away from returning. The cancel above now
        # reaches the archive tool itself through the cancel watcher, so the worker unwinds on its own while
        # the window closes immediately. Nothing left behind is written by a worker after this point: every
        # build is staged outside the game folder and swept by the job's own cleanup.
        self.jobs.shutdown(wait=False)
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        self.logger.info("APPLICATION", "SHUTDOWN_COMPLETE")
