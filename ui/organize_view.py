import shutil
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from .theme import ACCENT, ACCENT_HI, ActivityFeed, BG, BORDER, CYAN, GREEN, MUTED, ORANGE, PANEL, PANEL2, PhaseTimeline, RED, TEXT, bind_wheel, human_duration, human_size, panel, pill, pin_bottom, scroll_text
from services.organizer_service import OrganizerService

# Visual treatment per processing stage. 'failed' is deliberately the loudest color so a conversion that
# did not happen is impossible to miss while scrolling past.
STAGE_STYLE = {
    "organizing": (ACCENT, "ORGANIZING"),
    "extracting": (CYAN, "EXTRACTING"),
    "compressing": (ACCENT_HI, "COMPRESSING"),
    "verifying": (CYAN, "VERIFYING"),
    "converted": (GREEN, "CONVERTED"),
    "skipped": (ORANGE, "SKIPPED"),
    "failed": (RED, "FAILED"),
}

# The per-file pipeline, in order. A stage timeline shows where the current archive is instead of relying on
# one overwritable sentence, so a slow LZMA2 compress reads as progress rather than as a hang.
STAGE_PHASES = (("move", "Move"), ("extract", "Extract"), ("compress", "Compress"), ("verify", "Verify"))
STAGE_TO_PHASE = {"organizing": "move", "extracting": "extract", "compressing": "compress", "verifying": "verify"}
PHASE_KIND = {"extracting": "info", "compressing": "info", "verifying": "info", "converted": "good", "skipped": "warn", "failed": "bad", "organizing": "info"}

# What share of one archive's wall-clock each stage actually costs, and where that stage starts within the
# archive. Measured from real runs: extraction is I/O bound and quick, LZMA2 compression dominates, and
# verification is a short read-back. Without these weights the bar jumped 34% -> 72% on a stage change and
# then sat frozen for the several minutes a large compress genuinely takes. Named for the bar it drives, because
# the scan bar weighs the same stages differently and the two used to share one name with different numbers.
ORGANIZE_STAGE_SPAN = {"extracting": (0.00, 0.30), "compressing": (0.30, 0.85), "verifying": (0.85, 1.00), "organizing": (0.00, 0.10)}


class OrganizeView(tk.Frame):
    def __init__(self, parent, controller, state, on_done, on_cancel=None, on_start=None):
        super().__init__(parent, bg=BG)
        self.controller = controller
        self.state = state
        self.on_done = on_done
        self.on_cancel = on_cancel
        self.on_start = on_start
        self.ctx = None
        self.preview_only = False
        self.started_at = 0.0
        self.done_bytes = 0
        self.total_bytes = 0
        self.stage_counts = {}
        self.convert_total = 0
        self.convert_seen = set()
        self.current = None
        self._reset_live_state()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        tk.Label(self, text="ORGANIZE", bg=BG, fg=ACCENT_HI, font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(self, text="Ready to organize", bg=BG, fg=TEXT, font=("TkDefaultFont", 24, "bold")).grid(row=1, column=0, sticky="nw")
        self.card = panel(self)
        self.card.grid(row=2, column=0, sticky="nsew", pady=(18, 0))
        self.card.rowconfigure(4, weight=1)
        self.card.rowconfigure(5, minsize=45)
        self.card.rowconfigure(6, minsize=0)
        self.card.columnconfigure(0, weight=1)
        self.summary = tk.Label(self.card, text="Accept games on the Review page to build the organization plan.", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 10), justify="left")
        self.summary.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 10))
        self.summary.configure(wraplength=900)

        # Live per-file panel: stage timeline, progress bar, running totals, timestamped feed, stop button.
        # Organized into three visual zones: HEADER (stage + file), BODY (bar + timeline + feed), FOOTER (metrics + space).
        self.work = tk.Frame(self.card, bg=PANEL2, highlightbackground=BORDER, highlightthickness=1)
        self.work.grid(row=1, column=0, sticky="ew", padx=18)
        self.work.grid_remove()
        self.work.columnconfigure(0, weight=1)

        # ── HEADER ── Stage pill + file name + game name
        header_frame = tk.Frame(self.work, bg=PANEL2)
        header_frame.grid(row=0, column=0, sticky="ew", padx=(12, 0), pady=(10, 0))
        header_frame.columnconfigure(1, weight=1)
        self.stage_pill = pill(header_frame, "WORKING", "muted")
        self.stage_pill.grid(row=0, column=0, padx=(0, 10), pady=0, sticky="w")
        self.file_label = tk.Label(header_frame, text="", bg=PANEL2, fg=TEXT, font=("TkDefaultFont", 10, "bold"), anchor="w")
        self.file_label.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=0)
        self.game_label = tk.Label(header_frame, text="", bg=PANEL2, fg=MUTED, font=("TkDefaultFont", 8), anchor="w")
        self.game_label.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(0, 0), pady=(2, 0))

        # ── BODY ── Progress bar + stage timeline + detail + feed
        body_frame = tk.Frame(self.work, bg=PANEL2)
        body_frame.grid(row=1, column=0, sticky="ew", padx=(12, 0), pady=(0, 6))
        body_frame.columnconfigure(0, weight=1)

        # Progress bar and timeline
        progress_frame = tk.Frame(body_frame, bg=PANEL2)
        progress_frame.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        progress_frame.columnconfigure(0, weight=1)
        self.bar = ttk.Progressbar(progress_frame, mode="determinate", maximum=100, length=100)
        self.bar.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 2))
        self.timeline = PhaseTimeline(progress_frame, STAGE_PHASES, bg=PANEL2)
        self.timeline.grid(row=1, column=0, sticky="w", padx=0, pady=(0, 4))

        # Detail information
        detail_frame = tk.Frame(body_frame, bg=PANEL2)
        detail_frame.grid(row=2, column=0, sticky="ew", pady=(0, 4))
        detail_frame.columnconfigure(0, weight=1)
        self.stage_info = tk.Label(detail_frame, text="", bg=PANEL2, fg=MUTED, font=("TkDefaultFont", 8), anchor="w")
        self.stage_info.grid(row=0, column=0, sticky="w", padx=(0, 0), pady=(0, 2))
        self.detail_label = tk.Label(detail_frame, text="", bg=PANEL2, fg=MUTED, font=("TkDefaultFont", 8), anchor="w", wraplength=800, justify="left")
        self.detail_label.grid(row=1, column=0, sticky="ew", padx=(0, 0), pady=(0, 2))

        # Feed ── Timestamped activity log
        self.work.rowconfigure(2, weight=1, minsize=200)
        self.log = tk.Text(self.work, bg=PANEL, fg=TEXT, relief="flat", bd=0, wrap="word", highlightthickness=1, highlightbackground=BORDER)
        self.log.grid(row=2, column=0, sticky="nsew", padx=12)
        self.log.configure(state="disabled")
        bind_wheel(self.log, lambda e: scroll_text(self.log, e))
        self.feed = ActivityFeed(self.log, limit=300)

        # ── FOOTER ── Metrics row (throughput + ETA), Pressure row (disk + RAM + level), Space bar
        footer_frame = tk.Frame(self.work, bg=PANEL2)
        footer_frame.grid(row=3, column=0, sticky="ew", padx=(12, 0), pady=(6, 4))
        footer_frame.columnconfigure(1, weight=1)

        # Metrics row
        metrics_frame = tk.Frame(footer_frame, bg=PANEL2)
        metrics_frame.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        metrics_frame.columnconfigure(0, weight=1)
        self.counters = tk.Label(metrics_frame, text="", bg=PANEL2, fg=TEXT, font=("TkDefaultFont", 8, "bold"), anchor="w")
        self.counters.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 2))

        self.metrics = tk.Label(metrics_frame, text="", bg=PANEL2, fg=MUTED, font=("TkDefaultFont", 8), anchor="w")
        self.metrics.grid(row=1, column=0, sticky="ew", padx=0, pady=(0, 2))

        # Pressure row
        pressure_frame = tk.Frame(footer_frame, bg=PANEL2)
        pressure_frame.grid(row=1, column=0, sticky="ew", pady=(0, 2))
        pressure_frame.columnconfigure(0, weight=1)
        self.pressure = tk.Label(pressure_frame, text="", bg=PANEL2, fg=CYAN, font=("TkDefaultFont", 8), anchor="w")
        self.pressure.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 2))

        # Space bar
        space_frame = tk.Frame(footer_frame, bg=PANEL2)
        space_frame.grid(row=2, column=0, sticky="ew", pady=(0, 2))
        space_frame.columnconfigure(0, weight=1)
        self.space = ttk.Progressbar(space_frame, mode="determinate", maximum=100)
        self.space.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 2))
        self.space_label = tk.Label(space_frame, text="", bg=PANEL2, fg=MUTED, font=("TkDefaultFont", 8), anchor="w")
        self.space_label.grid(row=1, column=0, sticky="ew", padx=0, pady=(0, 2))

        self.stop_btn = ttk.Button(self.work, text="STOP RUN", style="Danger.TButton", command=self._stop)
        self.stop_btn.grid(row=0, column=2, rowspan=4, pady=(10, 0), padx=(0, 12))

        actions_top = tk.Frame(self.card, bg=PANEL)
        actions_top.grid(row=3, column=0, sticky="ew", padx=18, pady=(14, 4))
        self.tally = tk.Label(actions_top, text="", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8), anchor="w")
        self.tally.pack(side="left")
        self.list = tk.Text(self.card, bg=PANEL, fg=TEXT, relief="flat", wrap="word", height=20)
        self.list.grid(row=4, column=0, sticky="nsew", padx=18, pady=8)
        self.list.configure(state="disabled")
        self.list.tag_configure("convert", foreground=ORANGE, font=("TkDefaultFont", 9, "bold"))
        self.list.tag_configure("no_convert", foreground=GREEN, font=("TkDefaultFont", 9))
        self.list.tag_configure("preview", foreground=MUTED, font=("TkDefaultFont", 9))
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.list.bind(sequence, self._wheel, add="+")
        actions = tk.Frame(self.card, bg=PANEL)
        actions.grid(row=5, column=0, sticky="ew", padx=18, pady=(8, 18))
        ttk.Button(actions, text="PREVIEW CHANGES", style="Secondary.TButton", command=self.preview).pack(side="left")
        self.organize_button = ttk.Button(actions, text="ORGANIZE ACCEPTED GAMES  ›", style="Primary.TButton", command=self.request_organize)
        self.organize_button.pack(side="right")
        self.confirm_bar = tk.Frame(self.card, bg=PANEL2, highlightbackground=ORANGE, highlightthickness=1)
        self.confirm_bar.grid(row=6, column=0, sticky="ew", padx=18, pady=(0, 18))
        self.confirm_bar.grid_remove()
        self.confirm_label = tk.Label(self.confirm_bar, text="", bg=PANEL2, fg=TEXT, font=("TkDefaultFont", 9), anchor="w", justify="left", wraplength=760)
        self.confirm_label.pack(side="left", fill="x", expand=True, padx=12, pady=10)
        ttk.Button(self.confirm_bar, text="CANCEL", style="Secondary.TButton", command=self._cancel_confirm).pack(side="right", padx=(6, 12), pady=10)
        ttk.Button(self.confirm_bar, text="CONFIRM & ORGANIZE", style="Primary.TButton", command=self._confirm_organize).pack(side="right", padx=6, pady=10)

    def _reset_live_state(self):
        """Live state for the in-flight archive. The bar is drawn from these on every tick, so it keeps
        moving between progress events instead of only when a stage happens to change. Initialised here as
        well as at the start of a run, because progress records can arrive before any run begins."""
        self.archive_bytes = 0
        self.stage = ""
        self.stage_progress = 0.0
        self.stage_started = 0.0
        self.saved_bytes = 0
        self.tool_file = ""
        self.level = ""
        self.done_bytes = 0
        self.total_bytes = 0

    def _accepted(self):
        return [a for a in self.state.get().scan_result.archives if a.decision.accepted]

    def _wheel(self, event):
        self.list.yview_scroll(-1 if getattr(event, "delta", 0) > 0 or getattr(event, "num", 0) == 4 else 1, "units")
        return "break"

    def set_preview_only(self, value):
        self.preview_only = bool(value)

    def _stop(self):
        """Cancels the run in flight. The pre-flight CANCEL only covered the confirmation step, so once work
        started a long LZMA2 repack had no way to be stopped from the screen actually being watched."""
        if not self.ctx:
            return
        self.stop_btn.configure(state="disabled", text="STOPPING…")
        self.feed.write("Stop requested — finishing the current archive, then stopping", "warn")
        self.detail_label.configure(text="Cancelling safely; no further archives will be started", fg=ORANGE)
        if self.on_cancel:
            self.on_cancel()
        else:
            self.controller.jobs.cancel_all()

    def _free_bytes(self):
        """Free space on the volume that actually holds the library. Repacking writes the new archive beside
        the old one, so this is the disk that has to survive the run - and it is the resource whose exhaustion
        produced the '7z build exited 255: Break signaled' failures."""
        root = getattr(self.controller.config, "library_root", None)
        for candidate in (root, Path(root) if root else None):
            if not candidate:
                continue
            try:
                return shutil.disk_usage(str(candidate)).free
            except OSError:
                continue
        return None

    def _overall_fraction(self):
        """Fraction of the whole run completed, counting the in-flight archive by its own real progress.

        Bytes finished so far alone cannot move a bar during a single long compress, which is exactly when
        the user needs to see that something is happening. The stage weights convert 7z's own percentage
        into a share of the run, so the bar advances continuously instead of in four jumps per archive.
        """
        if not self.total_bytes:
            return 0.0
        span = ORGANIZE_STAGE_SPAN.get(getattr(self, "stage", ""))
        fraction = span[0] + (span[1] - span[0]) * max(
            0.0, min(1.0, float(getattr(self, "stage_progress", 0.0) or 0.0))
        ) if span and self.archive_bytes else (
            1.0 if self.stage in ("converted", "failed", "skipped") else 0.0)
        return max(0.0, min(1.0, (self.done_bytes + self.archive_bytes * fraction) / self.total_bytes))

    def _refresh_metrics(self):
        """Called on a timer while a run is active so elapsed time, throughput and free space keep moving
        even between progress events - a single LZMA2 compress can be silent for minutes."""
        if not self.ctx:
            return
        elapsed = max(0.001, time.monotonic() - self.started_at)
        done = self.done_bytes
        total = self.total_bytes
        # The bar is redrawn from the tick, not only from progress events. A single LZMA2 compress can be
        # silent between 7z's own reports, and a bar that only moves on a stage change reads as a hang.
        self.bar.configure(value=self._overall_fraction() * 100)
        parts = [f"running {human_duration(elapsed)}"]
        if done and total:
            share = min(100.0, done / total * 100)
            rate = done / elapsed
            parts.append(f"{share:.0f}% of {human_size(total)}")
            parts.append(f"{human_size(rate)}/s")
            if rate > 0 and total > done:
                remaining = (total - done) / rate
                parts.append(f"~{human_duration(remaining)} left" if remaining < 3600 else f"~{remaining / 3600:.1f}h left")
        elif total:
            parts.append(f"{human_size(total)} queued")
        # What the compressor is doing right now, which is the part that was missing entirely: a stage name on
        # its own said nothing for the minutes a large archive spends inside it.
        stage_hold = f"  •  {human_duration(max(0.0, time.monotonic() - self.stage_started))} in stage" if self.stage_started else ""
        if self.stage_progress:
            parts.append(f"stage {self.stage_progress * 100:.0f}%{stage_hold}")
        elif stage_hold:
            parts.append(stage_hold.removeprefix("  •  "))
        try:
            depth = self.controller.services.rollback.pending_count()
            if depth:
                parts.append(f"undo covers {depth} move(s)")
        except Exception:
            pass
        self.metrics.configure(text="   •   ".join(parts))
        # Free space, memory headroom and the compression level in force: all three decide whether the next
        # archive can finish, and the level is the one that silently steps down under pressure.
        free = self._free_bytes()
        try:
            available, swap_free = OrganizerService._available_ram(OrganizerService.__new__(OrganizerService))
        except Exception:
            available = swap_free = None
        detail = []
        if free is not None:
            detail.append(f"free {human_size(free)}")
        if available is not None:
            detail.append(f"RAM {human_size(available)} free" + (f" / swap {human_size(swap_free)}" if swap_free is not None else ""))
        if self.level:
            detail.append(f"7z level {self.level}")
        if self.tool_file:
            detail.append(f"writing {Path(self.tool_file).name}")
        self.pressure.configure(text="   •   ".join(detail) if detail else "")
        # Live detail beside the stage timeline. The pills show which stage is active; this shows how long it
        # has been running and how far through it is, which is what tells a slow compress from a stuck one.
        if self.stage:
            held = max(0.0, time.monotonic() - self.stage_started)
            text = f"{self.stage}  •  {human_duration(held)} in this stage"
            if self.archive_bytes:
                text += f"  •  {self._size(self.archive_bytes)} archive"
            if self.stage_progress:
                text += f"  •  {self.stage_progress * 100:.0f}% complete"
            if self.tool_file:
                text += f"  •  {Path(self.tool_file).name}"
            self.stage_info.configure(text=text)
        else:
            self.stage_info.configure(text="")
        free = self._free_bytes()
        if free is not None:
            try:
                capacity = shutil.disk_usage(str(self.controller.config.library_root)).total
            except OSError:
                capacity = 0
            free_ratio = free / capacity * 100 if capacity else 0
            self.space.configure(value=min(100.0, free_ratio))
            # Warn well before a repack can fail on a full volume rather than after it already has.
            level = RED if free < 2 * 1024**3 else ORANGE if free < 8 * 1024**3 else GREEN
            self.space_label.configure(text=f"Free space on library volume: {human_size(free)}   •   {'low - a conversion may fail' if free < 8 * 1024**3 else 'healthy'}", fg=level)
        self.after(1000, self._refresh_metrics)

    def _size(self, value):
        return human_size(value)

    def refresh(self):
        self.work.grid_remove()
        self.stage_counts = {}
        self.convert_total = 0
        self.convert_seen = set()
        self.current = None
        self.bar.configure(value=0)
        accepted = self._accepted()
        self.confirm_bar.grid_remove()
        will_convert = sum(1 for a in accepted if a.path.suffix.lower() not in (".7z", ".7Z"))
        if self.preview_only:
            summary_text = f"{len(accepted)} archive(s) ready — Preview only: no files will be moved or converted"
        elif will_convert:
            summary_text = f"{len(accepted)} archive(s) ready • {will_convert} ZIP/RAR will be rebuilt as 7Z • newest version active, older versions move to library / Archive"
        else:
            summary_text = f"{len(accepted)} archive(s) ready • all already 7Z • newest version active, older versions move to library / Archive"
        self.summary.configure(text=summary_text, fg=MUTED)
        self.list.configure(state="normal")
        self.list.delete("1.0", "end")
        planned = dict(self.controller.services.organizer.preview(accepted, self.controller.config.library_root))
        self.tally.configure(text="")
        for a in accepted:
            target = planned.get(a.path, a.path)
            folder = target.parent
            artwork = "artwork included" if a.artwork.present() else "artwork unavailable"
            shortcut = "Steam Chrome link included" if a.steam.appid else "no Steam link"
            source_kind = a.path.suffix.lower().lstrip(".").upper() or "archive"
            name = a.steam.name or a.display_name
            self.list.insert("end", f"• {name}\n")
            will_convert = source_kind != "7Z"
            if self.preview_only:
                self.list.insert("end", f"   {source_kind} → 7Z (PREVIEW)\n", "preview")
            elif will_convert:
                self.list.insert("end", f"   {source_kind} → 7Z  •  Category: {a.decision.category}\n", "convert")
            else:
                self.list.insert("end", f"   {source_kind} (no conversion needed)  •  Category: {a.decision.category}\n", "no_convert")
            self.list.insert("end", f"   Folder: {folder}\n   Archive: {target.name}\n   {artwork} • {shortcut}\n\n")
        if not accepted:
            self.list.insert("end", "No accepted games yet. Return to Review and accept at least one game.")
        self.list.configure(state="disabled")
        self.organize_button.configure(
            text="PREVIEW ONLY — NO MOVE" if self.preview_only else "ORGANIZE ACCEPTED GAMES  ›",
            state="disabled" if self.preview_only else ("normal" if accepted else "disabled"))
        pin_bottom(self.list)

    def run_ended(self):
        """Release the run after it stopped for any reason, not only after it succeeded.

        _done clears ctx, but it is the *success* callback. A run that was cancelled - or that failed - is
        reported through the controller's event stream instead and never reaches _done, so ctx stayed set for
        the rest of the session: the 1s metrics ticker kept recomputing against a run that no longer existed,
        and STOP RUN stayed armed on a screen with nothing left to stop.
        """
        self.ctx = None

    def preview(self):
        accepted = self._accepted()
        if not accepted:
            return
        destination = self.controller.config.library_root
        changes = self.controller.services.organizer.preview(accepted, destination)
        lines = ["Planned changes:", ""] + [f"{src}\n  → {dst}" for src, dst in changes]
        messagebox.showinfo("Organization Preview", "\n\n".join(lines), parent=self.winfo_toplevel())

    def organize(self):
        """Deprecated alias. The button handlers call request_organize directly, so this existed only as a
        second entry point that could silently drift from the real flow."""
        return self.request_organize()

    def request_organize(self):
        accepted = self._accepted()
        if not accepted:
            return
        if self.preview_only:
            self.preview()
            return
        if not self.controller.config.library_root:
            self.summary.configure(text="Choose the library first — no games directory is configured.", fg=ORANGE)
            return
        self.confirm_label.configure(
            text=f"Organize {len(accepted)} accepted archive(s) into dated game folders? The newest "
                 f"version becomes active, older versions move to the library Archive folder, and "
                 f"artwork + Steam links are included.")
        self.confirm_bar.grid()
        self.organize_button.configure(state="disabled")

    def _cancel_confirm(self):
        self.confirm_bar.grid_remove()
        self.organize_button.configure(state="normal" if self._accepted() else "disabled")

    def _confirm_organize(self):
        self.confirm_bar.grid_remove()
        accepted = self._accepted()
        if not accepted:
            return
        self.organize_button.configure(state="disabled")
        self.summary.configure(text="Organizing accepted games…", fg=MUTED)
        self.stage_counts = {}
        self.convert_total = 0
        self.convert_seen = set()
        self.current = None
        self.work.grid()
        self.bar.configure(value=0)
        self.tally.configure(text="")
        self.timeline.reset()
        self.feed.clear()
        self.stop_btn.configure(state="normal", text="STOP RUN")
        # Totals for throughput and ETA come from the accepted set up front, so the estimate is meaningful
        # before the first archive finishes rather than only once it is too late to plan around.
        self.started_at = time.monotonic()
        self.done_bytes = 0
        self.ticker = None
        self.total_bytes = sum((a.path.stat().st_size for a in accepted if a.path.is_file()), 0)
        self._reset_live_state()
        self.file_label.configure(text="Preparing archive conversion…")
        self.game_label.configure(text="")
        self.detail_label.configure(text="")
        self.counters.configure(text="")
        self.metrics.configure(text="")
        self.space_label.configure(text="")
        self.space.configure(value=0)
        self.stage_pill.configure(text="WORKING")
        self.stage_pill.restyle("muted")
        self.ctx = self.controller.organize(accepted, self.controller.config.library_root, self._done, self.progress_update)
        # Tell the window a run is in flight. Without it MainWindow.busy stayed False for the whole organize,
        # and MainWindow.cancel_run() returns immediately when it is not busy - so this screen's STOP RUN
        # button changed to STOPPING, the label said it was cancelling, and the run organized every game.
        if self.on_start:
            self.on_start("Organizing accepted games…")
        self._refresh_metrics()

    def progress_update(self, event):
        """Renders one structured progress record. Accepts a plain string too, so an older caller that still
        sends a sentence keeps working instead of crashing the UI."""
        if isinstance(event, str):
            event = {"message": event, "stage": "working"}
        stage = event.get("stage", "working")
        color, label = STAGE_STYLE.get(stage, (ACCENT, "WORKING"))
        self.work.grid()
        self.stage_pill.configure(text=label)
        self.stage_pill.restyle("accent" if stage not in ("converted", "skipped", "failed") else {"converted": "good", "skipped": "warn", "failed": "bad"}[stage])
        name = event.get("file") or ""
        suffix = event.get("source_suffix", "").upper() if event.get("source_suffix") else ""
        # Prominent conversion indicator during active conversion stages
        if stage in ("extracting", "compressing", "verifying") and suffix and suffix != "7Z":
            self.file_label.configure(text=f"{name}  ({suffix} → 7Z)", fg=ORANGE)
            self.stage_pill.configure(text=f"{label}  ({suffix} → 7Z)")
        elif stage == "converted" and suffix and suffix != "7Z":
            self.file_label.configure(text=f"{name}  ({suffix} → 7Z)", fg=GREEN)
            self.stage_pill.configure(text=f"{label}  ({suffix} → 7Z)")
        else:
            self.file_label.configure(text=name, fg=TEXT)
            if stage not in ("converted", "failed", "skipped"):
                self.stage_pill.configure(text=label)
        game = event.get("game")
        category = event.get("category")
        index = event.get("index")
        total = event.get("total")
        if stage == "organizing":
            self.game_label.configure(text=f"{game or ''}{f'  •  {category}' if category else ''}   •   game {index} of {total}" if index else (game or ""))
            self.timeline.reset()
        else:
            self.game_label.configure(text=game or "")
        phase = STAGE_TO_PHASE.get(stage)
        if phase:
            # Entering a new stage means the previous one finished, so record it as done before starting the
            # next. Otherwise a run that died during compression marked every earlier stage failed too.
            if self.current and self.timeline.states.get(self.current) == "active":
                self.timeline.set_state(self.current, "done")
            self.timeline.set_state(phase, "active")
            self.current = phase
        if stage in ("converted", "failed", "skipped"):
            if stage == "failed":
                if self.current:
                    self.timeline.set_state(self.current, "failed")
            else:
                for key in STAGE_TO_PHASE.values():
                    self.timeline.set_state(key, "done")
        # Track the in-flight archive so the ticker can draw a bar that moves through a long stage.
        if stage in ORGANIZE_STAGE_SPAN:
            if stage != self.stage:
                self.stage_started = time.monotonic()
            self.stage = stage
            self.stage_progress = float(event.get("progress") or 0.0)
            self.archive_bytes = int(event.get("source_bytes") or 0)
        if event.get("tool_file"):
            self.tool_file = event["tool_file"]
        if event.get("level"):
            self.level = event["level"]
        # Determinate across the three known stages so the bar means something instead of flickering.
        self.bar.configure(value=self._overall_fraction() * 100)
        detail = []
        if event.get("source_bytes"):
            detail.append(f"source {self._size(event['source_bytes'])}")
        if event.get("extracted_bytes"):
            detail.append(f"extracted {self._size(event['extracted_bytes'])}")
        if event.get("target_bytes"):
            detail.append(f"new {self._size(event['target_bytes'])}")
        if event.get("target_name"):
            detail.append(event["target_name"])
        if stage == "failed":
            # The reason a conversion failed is the whole point of watching it; the organizer already sends it.
            reason = event.get("message_text") or event.get("message") or "conversion failed"
            detail.insert(0, reason)
        self.detail_label.configure(text="   •   ".join(detail), fg=RED if stage == "failed" else ORANGE if stage == "skipped" else MUTED)
        # Every stage transition is echoed into the timestamped feed, so the user can scroll back through the
        # run instead of watching a single line that is overwritten dozens of times per archive. Within a
        # stage the same line is redrawn in place: the stage reports about once a second, and appending each
        # of those produced the repeated "Converting: <same file>" entries that buried the real transitions.
        bits = []
        if event.get("tool_percent") is not None:
            bits.append(f"{event['tool_percent']}%")
        if event.get("tool_file"):
            bits.append(Path(event["tool_file"]).name)
        if event.get("target_bytes"):
            bits.append(self._size(event["target_bytes"]))
        suffix = f"   {'   '.join(bits)}" if bits else ""
        if stage in ("converted", "failed", "skipped"):
            self.feed.break_run()
            display_name = event.get("target_name") or name or (game or "")
            self.feed.write(f"{label}: {display_name}{suffix}".rstrip(": "), PHASE_KIND.get(stage, "info"))
        else:
            self.feed.update(f"{stage}:{name}", f"{label}: {name or (game or '')}{suffix}", PHASE_KIND.get(stage, "info"))
        # Accumulate finished bytes so throughput and ETA reflect real completed work, not elapsed guesses.
        if stage == "converted":
            self.done_bytes += int(event.get("target_bytes") or event.get("source_bytes") or 0)
            # Running total of what the repack has actually reclaimed, which is the whole point of it and was
            # only ever visible one archive at a time.
            self.saved_bytes += max(0, int(event.get("source_bytes") or 0) - int(event.get("target_bytes") or 0))
        if stage in ("converted", "failed", "skipped"):
            self.stage_counts[stage] = self.stage_counts.get(stage, 0) + 1
        # Conversions still to come, which is a different number from games still to come: a run can work
        # through twenty games and rebuild only two of them, and "game 7 of 20" then says nothing about the
        # rebuild that is the only slow part. The count the run reports up front is over archives that will
        # really be rebuilt, so a finished game that needed no work never moves it.
        if event.get("conversions") is not None:
            self.convert_total = int(event["conversions"])
        parts = []
        for key, text in (("converted", "converted"), ("skipped", "skipped"), ("failed", "failed")):
            if self.stage_counts.get(key):
                parts.append(f"{self.stage_counts[key]} {text}")
        if self.saved_bytes:
            parts.append(f"{self._size(self.saved_bytes)} saved")
        counter_text = "   •   ".join(parts) if parts else ""
        if stage in ("converted", "failed", "skipped"):
            # Counted by the run's own ordinal for this archive, and only once it has finished: a game moved
            # without a rebuild reports a terminal stage too, and counting events rather than ordinals would
            # both count it as a conversion and show the current one as finished before it is.
            ordinal = event.get("conversion")
            if isinstance(ordinal, int) and ordinal > 0:
                self.convert_seen.add(ordinal)
        left = max(0, self.convert_total - len(self.convert_seen))
        conversion_text = f"{len(self.convert_seen)} of {self.convert_total} converted" + (f"   •   {left} left" if left else "")
        self.counters.configure(text=(f"game {index} of {total}   •   " if index else "") + (f"{conversion_text}   •   " if self.convert_total else "") + counter_text)
        # Compression ratio: the concrete payoff of the whole repack, and the only way to tell at a glance
        # whether an archive converted sensibly or ballooned.
        source = int(event.get("source_bytes") or 0)
        target = int(event.get("target_bytes") or 0)
        if stage == "converted" and source and target:
            ratio = target / source * 100
            ratio_color = GREEN if target < source else ORANGE if target > source else MUTED
            self.detail_label.configure(text="   •   ".join(detail + [f"{ratio:.0f}% of original ({human_size(source)} → {human_size(target)})"]), fg=ratio_color)

    def _done(self, archives):
        self.work.grid_remove()
        self.bar.configure(value=0)
        self.ctx = None
        # Only run_seconds was ever read back: the Done screen recomputes written and saved totals from each
        # archive's ConversionResult, which is the authoritative record. run_bytes and run_written were
        # published here but read by nothing, and run_written was additionally guaranteed to be 0 because
        # written_bytes was never assigned. Two fields that look like a report but cannot be is worse than
        # no fields, so they are gone.
        if getattr(self, "started_at", 0):
            self.state.update(run_seconds=max(0.0, time.monotonic() - self.started_at))
        self.on_done(archives)
