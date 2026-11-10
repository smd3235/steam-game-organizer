"""The single window: layout, lifecycle, and the view stack.

MainWindow owns the Tk root, maximizes it on start (the app is full-screen only), subscribes to
EventBus failures and cancellations, builds all six views (scan, review, organize, artwork, done)
and swaps between them. It also drives the idle clock and the per-phase timer that ticks while
a scan or organize run is in progress.
"""

from pathlib import Path
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from .theme import ACCENT, ACCENT_HI, ACCENT_HOVER, BG, MUTED, ORANGE, PANEL, PANEL2, PANEL3, TEXT, Theme, panel, tooltip
from core.constants import APP_NAME, VERSION
from debug.diagnostics import Diagnostics
from .scan_view import ScanView, SCAN_PHASES
from .review_view import ReviewView
from .organize_view import OrganizeView
from .artwork_view import ArtworkView
from .done_view import DoneView


class MainWindow:
    def __init__(self, root, config, state, bus, controller, logger, jobs):
        self.root = root
        self.config = config
        self.state = state
        self.bus = bus
        self.controller = controller
        self.logger = logger
        self.jobs = jobs
        self.current = "scan"
        self.views = {}
        self.closing = False
        self.busy = False
        self.started_at = None
        self.timer_id = None
        self._pulse_id = None
        self.run_preview_only = False
        self.run_unlock_zip = False
        self.run_archives = None
        root.title(f"{APP_NAME} v{VERSION}")
        root.geometry("1280x760")
        root.minsize(1100, 680)
        root.report_callback_exception = self._callback_error
        Theme(root)
        self._maximize()
        self.bus.subscribe("operation_failed", self._operation_failed)
        self.bus.subscribe("operation_cancelled", self._operation_cancelled)
        self.build()
        self._tick()

    def _maximize(self):
        try:
            self.root.state("zoomed")
            self.root.update_idletasks()
            if self.root.state() == "zoomed":
                return
        except tk.TclError:
            pass
        # Some window managers ignore the 'zoomed' wm state that Windows honours; fall back to
        # sizing the window to the full screen directly so the app always fills the display.
        try:
            self.root.geometry(f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0")
        except tk.TclError:
            pass

    def _callback_error(self, exc, val, tb):
        import traceback

        if self.closing or isinstance(val, tk.TclError) and not self._root_alive():
            return
        self.logger.error("UI", "CALLBACK_ERROR " + "".join(traceback.format_exception(exc, val, tb)))

    def _root_alive(self):
        try:
            return bool(self.root.winfo_exists()) and not self.closing
        except tk.TclError:
            return False

    def shutdown(self):
        self.closing = True
        try:
            self.views.get("review") and self.views["review"].shutdown()
        except Exception:
            pass
        self.jobs.cancel_all()
        self._cancel_timer()
        self._cancel_pulse()

    def _cancel_timer(self):
        if self.timer_id:
            try:
                self.root.after_cancel(self.timer_id)
            except tk.TclError:
                pass
            self.timer_id = None

    def _tick(self):
        if self.closing:
            return
        if self.busy and self.started_at:
            e = int(time.monotonic() - self.started_at)
            self.runtime.configure(text=f"RUNNING  •  {e // 60:02d}:{e % 60:02d}")
            if self.current == "scan":
                self.views["scan"].set_elapsed(f"{e // 60:02d}:{e % 60:02d}")
        self.timer_id = self.root.after(500, self._tick)

    def build(self):
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True, padx=14, pady=8)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)
        head = tk.Frame(outer, bg=BG)
        head.grid(row=0, column=0, sticky="ew")
        tk.Label(head, text=APP_NAME.upper(), bg=BG, fg=ACCENT_HI, font=("TkDefaultFont", 9, "bold")).pack(side="left")
        tk.Label(head, text=f"v{VERSION}", bg=BG, fg=MUTED, font=("TkDefaultFont", 8, "bold")).pack(side="right")
        nav = panel(outer)
        nav.grid(row=1, column=0, sticky="ew", pady=(4, 6))
        self.nav_buttons = {}
        for key, label in [("scan", "SCAN"), ("review", "REVIEW"), ("organize", "ORGANIZE"), ("artwork", "ARTWORK"), ("done", "DONE")]:
            # Navigation tabs - clickable, keyboard accessible, with clear active state.
            # Numbering removed: workflow is non-linear (users jump back to Scan from Review, etc.)
            b = tk.Button(nav, text=label, bg=PANEL2, fg=MUTED, activebackground=PANEL3,
                activeforeground=TEXT, font=("TkDefaultFont", 9, "bold"), padx=22, pady=10,
                relief="flat", bd=0, highlightthickness=0, cursor="hand2", takefocus=True)
            b.pack(side="left", padx=2, pady=4)
            b.configure(command=lambda k=key: self._nav(k))
            b.bind("<Return>", lambda e, k=key: self._nav(k))
            b.bind("<KP_Enter>", lambda e, k=key: self._nav(k))
            self.nav_buttons[key] = b
        self.nav_summary = tk.Label(nav, text="", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8, "bold"))
        self.nav_summary.pack(side="right", padx=14)
        self.body = tk.Frame(outer, bg=BG)
        self.body.grid(row=2, column=0, sticky="nsew")
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(0, weight=1)
        self.views["scan"] = ScanView(self.body, self.scan, self.choose, self.cancel_run, on_scan_artwork=self.scan_new_artwork, scan_summary=self.config.load_scan_summary())
        self.views["scan"].set_library(self.config.library_root)
        self.views["scan"].load_api(self.config.settings.get("steamgriddb_api_key", ""))
        # The checkbox has to show the saved value on open, not default to on every launch - otherwise
        # turning conversion off looks like it worked until the next restart silently re-enabled it.
        self.views["scan"].convert_var.set(self.config.convert_archives)
        # Attached after the set() above on purpose: the trace on convert_var writes config.convert_archives,
        # and saving settings on every launch - for a value just read from them - is a needless write. From
        # here on, a toggle saves immediately, which is what the comment above promises.
        self.views["scan"].controller = self.controller
        self.views["review"] = ReviewView(self.body, self.controller, self.state, self.logger,
            self.jobs, on_next=self._go_to_organize, on_verified=self.verification_done,
            on_verification_progress=self.verification_progress)
        self.views["organize"] = OrganizeView(self.body, self.controller, self.state, self.finish, self.cancel_run, on_start=self._begin_organize)
        self.views["artwork"] = ArtworkView(self.body, self.goto_done, on_review=lambda: self.show("review"))
        self.views["done"] = DoneView(self.body, lambda: self.show("scan"), self.undo_last,
            self.open_library, self.state, rollback=self.controller.services.rollback,
            config=self.config, on_scan_artwork=self.scan_new_artwork)
        foot = tk.Frame(outer, bg=BG)
        foot.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        self.status = tk.Label(foot, text="Ready — configure options and scan your Games directory.", bg=BG, fg=MUTED, font=("TkDefaultFont", 8), anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        self.setup_btn = ttk.Button(foot, text="Setup", style="Secondary.TButton", command=self.open_setup)
        self.setup_btn.pack(side="right", padx=(0, 6))
        tooltip(self.setup_btn, "Set up game library, app folder, and extract folder")
        self._pulse_setup_btn()
        self.regen_btn = ttk.Button(foot, text="Regenerate HTML", style="Secondary.TButton", command=self.regenerate_html)
        self.regen_btn.pack(side="right", padx=(6, 0))
        tooltip(self.regen_btn, "Rewrite Game Library.html from the current library without scanning")
        health_btn = ttk.Button(foot, text="System Health", style="Secondary.TButton", command=self.health)
        health_btn.pack(side="right", padx=(6, 0))
        tooltip(health_btn, "Check configuration and environment")
        diag_btn = ttk.Button(foot, text="Diagnostics", style="Secondary.TButton", command=self.diagnostics)
        diag_btn.pack(side="right", padx=(6, 0))
        tooltip(diag_btn, "Full diagnostic report for troubleshooting")
        self.runtime = tk.Label(foot, text="READY", bg=BG, fg=ACCENT_HI, font=("TkDefaultFont", 8, "bold"))
        self.runtime.pack(side="right", padx=(0, 6))
        self.show("scan")

    def _pulse_setup_btn(self):
        """One-shot pulse animation on the Setup button, matching the HTML catalog's
        setup-pulse CSS animation (a soft glow that expands and fades over ~2s).

        Tkinter has no box-shadow, so the glow is simulated with a colored frame
        placed immediately behind the button. Its border width grows from 0px to
        8px and back to 0px over two animation halves, using ACCENT_HI.
        """
        glow = tk.Frame(self.setup_btn.master, bg=BG, highlightbackground=ACCENT_HI, highlightthickness=0)
        glow.place(in_=self.setup_btn, x=-4, y=-4, relx=0, rely=0, anchor="nw", bordermode="outside")
        glow.lower(self.setup_btn)

        steps = 24
        max_thick = 8
        self._pulse_id = None

        def _animate(step):
            if step < steps // 2:
                thick = int(max_thick * (step / (steps // 2)))
                try:
                    glow.configure(highlightthickness=thick)
                    self._pulse_id = self.root.after(25, lambda: _animate(step + 1))
                except tk.TclError:
                    glow.destroy()
            elif step < steps:
                thick = int(max_thick * (1 - (step - steps // 2) / (steps // 2)))
                try:
                    glow.configure(highlightthickness=thick)
                    self._pulse_id = self.root.after(25, lambda: _animate(step + 1))
                except tk.TclError:
                    glow.destroy()
            else:
                glow.destroy()

        self._pulse_id = self.root.after(1000, lambda: _animate(0))

    def _cancel_pulse(self):
        """Cancel the pulse animation if it is still pending, to avoid callbacks
        firing on a destroyed root."""
        if self._pulse_id:
            try:
                self.root.after_cancel(self._pulse_id)
            except tk.TclError:
                pass
            self._pulse_id = None

    def open_setup(self):
        """Open the three-folder wizard from the app's own toolbar.

        The catalog's Set up on this PC button cannot reach here - it goes through the protocol
        handler, which has no main window - so this is the way a reader who already has the app
        running re-points it: at the game library, at the app folder, and at the extract folder.
        The app box defaults to the copy that is running, which is the one that knows where it
        lives, so moving the app folder and opening this shows the new location without typing.
        """
        from ui.setup_window import SetupWindow

        SetupWindow(self.root, self.config, self.logger)

    def choose(self):
        if self.busy:
            return
        p = filedialog.askdirectory(title="Select game archive library", initialdir=str(self.config.library_root or Path.home()), parent=self.root)
        if p:
            self.config.library_root = Path(p).resolve()
            self.config.save()
            self.views["scan"].set_library(self.config.library_root)
            self.status.configure(text="Games directory changed")

    def save_api(self):
        key = self.views["scan"].api_var.get().strip()
        self.config.settings["steamgriddb_api_key"] = key
        self.config.save()
        self.controller.services.artwork.set_api_key(key)

    def open_library(self):
        root = self.config.library_root
        if not root or not root.is_dir():
            return
        # Was shutil.which('xdg-open'), which is the Linux opener: on Windows the lookup found nothing and the
        # button did nothing at all. utils.desktop.open_folder knows about both platforms and reports whether
        # anything was actually launched.
        from utils.desktop import open_folder

        open_folder(root)

    def _nav(self, key):
        """Nav buttons became clickable, so they must respect an in-flight run. Jumping screens mid-run would
        reset the Organize panel's stage timeline and recompute the plan, discarding the live progress the
        user is watching."""
        if self.busy and key != self.current:
            self.status.configure(text=f"A run is in progress — finish or cancel it before switching screens (currently on {self.current})")
            return
        self.show(key)

    def show(self, key):
        for v in self.views.values():
            try:
                v.grid_remove()
            except Exception:
                pass
            try:
                v.pack_forget()
            except Exception:
                pass
            try:
                v.place_forget()
            except Exception:
                pass
        target = self.views.get(key)
        if not target:
            return
        target.grid(row=0, column=0, sticky="nsew")
        self.current = key
        self.logger.info("UI", f"SCREEN_SHOW screen=[{key}]")
        self.logger.debug("UI", f"SHOW_STACK for [{key}]:\n" + "".join(__import__("traceback").format_stack(limit=12)))
        for k, b in self.nav_buttons.items():
            is_active = k == key
            b.configure(
                bg=ACCENT if is_active else PANEL2, fg="white" if is_active else MUTED,
                    activebackground=ACCENT_HOVER if is_active else PANEL3,
                    activeforeground="white" if is_active else TEXT,
                    relief="flat" if is_active else "flat", bd=2 if is_active else 0,
                    highlightthickness=2 if is_active else 0,
                    highlightbackground=ACCENT if is_active else BG,
                    highlightcolor=ACCENT if is_active else BG
            )
        if key == "organize":
            self.views[key].set_preview_only(self.run_preview_only)
            self.views[key].refresh()
        self._update_nav_summary()

    def _go_to_organize(self):
        """Switch to the organize view and, if there are accepted games, open the confirmation
        bar directly so the user only has one click ('Confirm & Organize') left instead of two
        ('Organize Accepted Games' then 'Confirm & Organize')."""
        self.show("organize")
        accepted = [a for a in self.state.get().scan_result.archives if a.decision.accepted]
        if accepted:
            ov = self.views["organize"]
            ov.confirm_label.configure(
                text=f"Organize {len(accepted)} accepted archive(s) into dated game folders? "
                     f"The newest version becomes active, older versions move to the library "
                     f"Archive folder, and artwork + Steam links are included.")
            ov.confirm_bar.grid()
            ov.organize_button.configure(state="disabled")

    def _update_nav_summary(self):
        archives = self.state.get().scan_result.archives
        if not archives:
            self.nav_summary.configure(text="")
            return
        verified = sum(1 for a in archives if a.steam.found)
        accepted = sum(1 for a in archives if a.decision.accepted)
        self.nav_summary.configure(text=f"{len(archives)} archives  •  {verified} verified  •  {accepted} ready to organize")

    def _start(self, text):
        self.busy = True
        self.started_at = time.monotonic()
        self.views["scan"].scanning = True
        self.views["scan"].cancel_btn.configure(state="normal")
        self.status.configure(text=text)
        self.runtime.configure(text="RUNNING  •  00:00")

    def _end(self, text):
        self.busy = False
        self.started_at = None
        scan = self.views["scan"]
        scan.cancel_btn.configure(state="disabled")
        scan.scan_btn.configure(state="normal")
        if scan.artwork_scan_btn:
            scan.artwork_scan_btn.configure(state="normal")
        self.status.configure(text=text)
        self.runtime.configure(text="READY")

    def _begin_organize(self, text):
        """Mark an organize run as in flight, the way _start() does for a scan.

        Only scan() and undo_last() called _start(), so MainWindow.busy stayed False for the whole of an
        organize run - and cancel_run() returns immediately when it is not busy. That made the Organize
        screen's STOP RUN button do nothing at all: it went to STOPPING, the status line said stopping, and
        the run carried on to organize every game.

        The scan half of _start() is deliberately not reused. It marks the *scan* screen as scanning, and
        during an organize run the scan screen is not the one doing the work; leaving that flag set is how a
        later navigation to Scan finds a screen that thinks a run is in progress.
        """
        self.busy = True
        self.started_at = time.monotonic()
        self.status.configure(text=text)
        self.runtime.configure(text="RUNNING  •  00:00")

    def cancel_run(self):
        if not self.busy:
            return
        self.logger.info("UI", f"CANCEL_REQUEST screen=[{self.current}] phase=[{self.state.get().phase}]")
        self.jobs.cancel_all()
        self.views["review"].cancel_lookup()
        # Update whichever screen is actually being watched. The cancel button used to live only on Scan, so a
        # cancel raised from Organize updated a label nobody could see.
        message = "Cancel requested — stopping safely…"
        if self.current == "scan":
            self.views["scan"].current.configure(text=message)
        if self.current == "organize":
            self.views["organize"].detail_label.configure(text=message, fg=ORANGE)
        self.status.configure(text="Cancel requested — no further files will be moved")
        self.runtime.configure(text="STOPPING  •  00:00")

    def scan(self):
        if self.closing or self.busy:
            return
        if not self.config.library_root or not self.config.library_root.is_dir():
            messagebox.showinfo("Games directory required", f"Choose a valid Games directory first. The default is {self.config.default_library_root()}.", parent=self.root)
            return
        self.save_api()
        self.run_preview_only = self.views["scan"].preview_var.get()
        self.run_unlock_zip = self.views["scan"].convert_var.get()
        # Saved on every scan rather than on a change callback, so the stored value can never drift from
        # what the next run will actually do, and turning it off survives a restart.
        self.config.convert_archives = bool(self.views["scan"].convert_var.get())
        self.views["scan"].begin_scan()
        self._start("Scanning Games…")
        self.show("scan")
        new_only = self.views["scan"].mode_var.get() == "New Only"
        self.logger.info(
            "UI",
            f"SCAN_REQUEST root=[{self.config.library_root}] mode=[{'new' if new_only else 'all'}] "
            f"preview_only={int(self.run_preview_only)} unlock_zip={int(self.run_unlock_zip)} "
            f"convert_archives={int(self.config.convert_archives)} "
            f"artwork={int(self.views['scan'].art_var.get())}")
        self.controller.scan(self.config.library_root, self.scan_done, self._scan_progress, new_only=new_only, unlock_zip=self.run_unlock_zip, preview_only=self.run_preview_only, download_artwork=self.views["scan"].art_var.get())

    def scan_new_artwork(self):
        """Quick scan: discover new archives and download their artwork.

        Runs cleanup, dedupe, repair (ZIP/RAR → 7z), and catalog generation
        so nothing is left behind. Keeps discovery itself on New Only mode so
        it stays fast on large libraries; the full-library artwork audit is
        skipped here and only runs on a full scan."""
        if self.closing or self.busy:
            return
        if not self.config.library_root or not self.config.library_root.is_dir():
            messagebox.showinfo("Games directory required", f"Choose a valid Games directory first. The default is {self.config.default_library_root()}.", parent=self.root)
            return
        self.save_api()
        self.views["scan"].begin_scan(quick=True)
        self._start("Scanning new archives + artwork…")
        self.show("scan")
        self.logger.info("UI", f"ARTWORK_SCAN_REQUEST root=[{self.config.library_root}]")
        self.controller.scan_new_artwork(self.config.library_root, scan_progress=self._scan_progress, verify_progress=self.verification_progress, done=self._scan_new_artwork_done, download_artwork=True)

    def _scan_new_artwork_done(self, archives):
        if self.closing:
            return
        self.views["scan"].finish_artwork_scan(archives)
        # The quick scan already looked up Steam info and downloaded artwork to cache, but the Review
        # screen still needs verify_all to set category suggestions and populate the decision UI.
        # Since artwork is cached, verification finishes quickly from cache. Mirroring scan_done(): the
        # run stays in progress until verification_done() calls _end and advances to Review.
        self.views["review"].load(archives, download_artwork=True)
        self.status.configure(text=f"Artwork scan complete  -  {len(archives)} new archive(s)  -  verification running in background")
        self.show("scan")

    def _scan_progress(self, event):
        """Scan telemetry arrives in three shapes: positional discovery counts, a structured conversion-repair
        record, and a structured pipeline-phase record. Route each to the widget that knows how to render it."""
        if isinstance(event, dict):
            stage = event.get("stage", "")
            # Splitting the stage on '_' sent repair_plan and repair_start to the phase view, because both
            # begin with the pipeline's own "repair" name. They are conversion records, not phase records, and
            # the conversion panel carries branches for both that could therefore never run. Matching the whole
            # stage against the phase names keeps "repair" and "repair_done" on the pipeline timeline and hands
            # everything else to the conversion panel.
            if stage in dict(SCAN_PHASES) or stage.endswith("_done") or stage == "artwork":
                self.views["scan"].phase_update(event)
            else:
                self.views["scan"].repair_update(event)
        else:
            self.views["scan"].progress_update(*event)

    def scan_done(self, result):
        if self.closing:
            return
        self.run_archives = None
        self.views["scan"].set_result(result)
        # set_result() disables cancel for the hand-off; re-enable it because verification is about to start
        # in the background and the user must be able to stop it.
        self.views["scan"].cancel_btn.configure(state="normal")
        self.views["review"].load(result.archives, download_artwork=self.views["scan"].art_var.get())
        self.status.configure(text=f"Scan complete  •  {len(result.archives)} archives  •  verification running in background")
        self.show("scan")

    def verification_done(self, archives):
        if not self.closing:
            self._end(f"Verification complete  •  {len(archives)} archives reviewed")
            self.show("review")

    def verification_progress(self, index, total, archive, steam_match, artwork=None, asset_event=None):
        if self.closing:
            return
        # The extra arguments are optional: artwork reports arrive while a download is still in flight.
        if asset_event is not None:
            self.views["scan"].artwork_update(index, total, archive, asset_event)
            return
        self.status.configure(text=f"Verifying {index} of {total}  •  {archive.display_name}")
        self.views["scan"].verification_update(index, total, archive, steam_match)
        self._update_nav_summary()

    def _operation_failed(self, event):
        self.controller.dispatch(lambda: self._show_operation_failed(event))

    def _show_operation_failed(self, event):
        if self.closing:
            return
        operation = event.payload.get("operation", "operation")
        self._end(f"{operation.capitalize()} failed — see Diagnostics for details")
        if operation == "organize":
            self.views["organize"].run_ended()
            self.views["organize"].refresh()
            self.show("organize")
        elif operation in ("scan", "verify", "artwork"):
            self.show("scan" if operation in ("scan", "artwork") else "review")

    def _operation_cancelled(self, event):
        self.controller.dispatch(lambda: self._show_operation_cancelled(event))

    def _show_operation_cancelled(self, event):
        if self.closing:
            return
        operation = event.payload.get("operation", "operation")
        self._end(f"{operation.capitalize()} cancelled — no further files were moved")
        if operation == "organize":
            self.views["organize"].run_ended()
            self.views["organize"].refresh()
        self.show("scan" if operation in ("scan", "verify", "artwork") else self.current)

    def finish(self, archives):
        self.run_archives = list(archives)
        self._end(f"Organization complete  •  {len(archives)} accepted")
        self.views["artwork"].show(archives)
        self.show("artwork")

    def goto_done(self):
        # The Done screen was never being handed the run results, so it always showed its empty placeholder.
        # Feed it the archives from this run (or the last completed run, if the user navigated back).
        self.views["done"].show(self.run_archives if self.run_archives is not None else self.state.get().scan_result.archives)
        self.show("done")

    def undo_last(self):
        if self.busy:
            return
        if not messagebox.askyesno("Undo Organization", "Move the most recent organized archives back to their original locations?", parent=self.root):
            return
        self._start("Undoing last organization…")
        self.controller.undo_last(self.config.library_root, self.undo_done)

    def undo_done(self, result):
        moved = int(result.get("moved", 0) or 0)
        pruned = int(result.get("pruned", 0) or 0)
        # Both numbers, because the second is the one the user cannot check: the archives are back in the
        # folder they came from and visible, while N game folders being removed is a deletion this app made
        # on its own and has to say out loud.
        self._end(f"Undo complete  •  {moved} archive(s) restored  •  {pruned} game folder(s) removed")
        self.show("scan")

    def regenerate_html(self):
        """Regenerate Game Library.html without running a scan.

        The build runs on a background thread so the window does not freeze; the scan panel's live line,
        the status bar and the RUNNING timer show progress while it works, and the button is disabled until
        the write finishes so a second press cannot stack a run on top of this one."""
        if self.busy:
            return
        root = self.config.library_root
        if not root or not root.is_dir():
            messagebox.showinfo("Games directory required", f"Choose a valid Games directory first. The default is {self.config.default_library_root()}.", parent=self.root)
            return
        self.busy = True
        self.started_at = time.monotonic()
        self.views["scan"].current.configure(text="Regenerating catalog…")
        self.status.configure(text="Regenerating catalog…")
        self.runtime.configure(text="RUNNING  •  00:00")
        try:
            self.regen_btn.configure(state="disabled")
        except (AttributeError, tk.TclError):
            pass
        self.logger.info("UI", f"CATALOG_REGENERATE_REQUEST root=[{root}]")

        def work(ctx):
            return self.controller.services.catalog.generate(root, self.controller.services.organizer.needs_catalog_launcher()) or []

        def done(written):
            self.busy = False
            self.started_at = None
            try:
                self.regen_btn.configure(state="normal")
            except (AttributeError, tk.TclError):
                pass
            scan = self.views["scan"]
            scan.cancel_btn.configure(state="disabled")
            scan.scan_btn.configure(state="normal")
            if scan.artwork_scan_btn:
                scan.artwork_scan_btn.configure(state="normal")
            if written:
                scan.current.configure(text=f"Catalog regenerated — {written[0].name}")
                self.status.configure(text=f"Catalog regenerated — {written[0].name}")
            else:
                scan.current.configure(text="Catalog regenerated")
                self.status.configure(text="Catalog regenerated")
            self.runtime.configure(text="READY")
            self.logger.info("UI", f"CATALOG_REGENERATED root=[{root}] files={len(written)}")

        def fail(exc):
            self.busy = False
            self.started_at = None
            try:
                self.regen_btn.configure(state="normal")
            except (AttributeError, tk.TclError):
                pass
            scan = self.views["scan"]
            scan.cancel_btn.configure(state="disabled")
            scan.scan_btn.configure(state="normal")
            if scan.artwork_scan_btn:
                scan.artwork_scan_btn.configure(state="normal")
            self.status.configure(text="Catalog regenerate failed — see Diagnostics")
            self.runtime.configure(text="READY")
            self.logger.error("UI", f"CATALOG_REGENERATE_FAILED error={type(exc).__name__}")

        self.jobs.submit(work, lambda job, result: self.controller.dispatch(lambda: done(result)), lambda job, exc: self.controller.dispatch(lambda: fail(exc)))

    def diagnostics(self):
        d = Diagnostics(self.config, self.state, self.logger)
        w = tk.Toplevel(self.root)
        w.title("Diagnostics")
        w.geometry("920x680")
        w.configure(bg=BG)
        w.transient(self.root)
        outer = panel(w)
        outer.pack(fill="both", expand=True, padx=12, pady=12)
        wrap = tk.Frame(outer, bg=PANEL)
        wrap.pack(fill="both", expand=True, padx=12, pady=12)
        t = tk.Text(wrap, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief="flat", wrap="none")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=t.yview, style="Dark.Vertical.TScrollbar")
        t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        t.insert("1.0", d.report())
        t.configure(state="disabled")
        ttk.Button(outer, text="Close", style="Secondary.TButton", command=w.destroy).pack(anchor="e", padx=12, pady=(0, 12))

    def health(self):
        d = Diagnostics(self.config, self.state, self.logger)
        w = tk.Toplevel(self.root)
        w.title("System Health")
        w.geometry("920x680")
        w.configure(bg=BG)
        outer = panel(w)
        outer.pack(fill="both", expand=True, padx=12, pady=12)
        text = tk.Text(outer, bg=PANEL, fg=TEXT, relief="flat", wrap="word")
        sb = ttk.Scrollbar(outer, orient="vertical", command=text.yview, style="Dark.Vertical.TScrollbar")
        text.configure(yscrollcommand=sb.set)
        text.pack(side="left", fill="both", expand=True, padx=12, pady=12)
        sb.pack(side="right", fill="y", pady=12)
        text.insert("1.0", d.health_text())
        text.configure(state="disabled")
        ttk.Button(w, text="Close", style="Secondary.TButton", command=w.destroy).pack(anchor="e", padx=18, pady=(0, 12))
