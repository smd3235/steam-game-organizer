"""The organize screen: takes accepted archives, converts ZIP/RAR to 7z, moves them into category folders,
writes artwork and catalog pages, and shows a live per-file progress bar with per-stage timing.

OrganizeView displays the batch organization run with a per-file timeline (Move/Extract/Compress/Verify),
a progress bar split across stages, and a live activity feed. It owns the on_done callback that MainWindow
wires to show the Done screen once organization completes.
"""

from __future__ import annotations

import customtkinter as ctk
import time
from .custom_theme import CTkFrame, CTkLabel, CTkTextbox, panel, pill
from .phase_timeline import PhaseTimeline
from .theme import ACCENT_HI, BG, BORDER, CYAN, ENTRY_BG, GREEN, MUTED, ORANGE, PANEL, PANEL2, RED, TEXT

# Visual treatment per processing stage. 'failed' is deliberately the loudest color so a conversion that
# did not happen is impossible to miss while scrolling past.
STAGE_STYLE = {
    "organizing": (ACCENT_HI, "ORGANIZING"),
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

# 2026-11-24: dropped unused locals (game/index/total/root) flagged by ruff F841, and added run_ended() so
# MainWindow's scan/fail/cancel handlers can call it without AttributeError. The live panel is reset on run end.




class OrganizeView(ctk.CTkFrame):
    def __init__(self, parent, controller, state, on_done, on_cancel=None, on_start=None):
        super().__init__(parent, fg_color=BG)
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
        CTkLabel(self, text="ORGANIZE", fg_color=PANEL, text_color=ACCENT_HI, font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0, sticky="w")
        CTkLabel(self, text="Ready to organize", fg_color=BG, text_color=TEXT, font=("TkDefaultFont", 24, "bold")).grid(row=1, column=0, sticky="nw")
        self.card = panel(self)
        self.card.grid(row=2, column=0, sticky="nsew", pady=(18, 0))
        self.card.rowconfigure(4, weight=1)
        self.card.rowconfigure(5, minsize=45)
        self.card.rowconfigure(6, minsize=0)
        self.card.columnconfigure(0, weight=1)
        self.summary = CTkLabel(self.card, text="Accept games on the Review page to build the organization plan.", fg_color=PANEL, text_color=MUTED, font=("TkDefaultFont", 10), justify="left")
        self.summary.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 10))
        self.list = CTkTextbox(self.card, fg_color=ENTRY_BG, text_color=TEXT, font=("TkDefaultFont", 9), corner_radius=6, border_width=0, width=1, height=1)
        self.list.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 10))
        self.list.configure(state="disabled")

        # Live per-file panel: stage timeline, progress bar, running totals, timestamped feed, stop button.
        # Organized into three visual zones: HEADER (stage + file), BODY (bar + timeline + feed), FOOTER (metrics + space).
        self.work = CTkFrame(self.card, fg_color=PANEL2, border_color=BORDER, border_width=1)
        self.work.grid(row=1, column=0, sticky="ew", padx=18)
        self.work.grid_remove()

        # ── HEADER ── Stage pill + file name + game name
        header_frame = CTkFrame(self.work, fg_color=PANEL2)
        header_frame.grid(row=0, column=0, sticky="ew", padx=(12, 0), pady=(10, 0))
        header_frame.columnconfigure(1, weight=1)
        self.stage_pill = pill(header_frame, "WORKING", "muted")
        self.stage_pill.grid(row=0, column=0, padx=(0, 10), pady=0, sticky="w")
        self.file_label = CTkLabel(header_frame, text="", fg_color=PANEL2, text_color=TEXT, font=("TkDefaultFont", 10, "bold"), anchor="w")
        self.file_label.grid(row=0, column=1, sticky="ew")

        # Per-file stage timeline and live feed
        self.timeline = PhaseTimeline(self.work, STAGE_PHASES)
        self.timeline.grid(row=1, column=0, sticky="ew", padx=12, pady=(10, 0))
        self.timeline.columnconfigure(0, weight=1)
        feed_frame = CTkFrame(self.work, fg_color=PANEL2)
        feed_frame.grid(row=2, column=0, sticky="nsew", padx=12, pady=(6, 10))
        feed_frame.rowconfigure(0, weight=1)
        feed_frame.columnconfigure(0, weight=1)
        self.feed = CTkTextbox(feed_frame, fg_color=ENTRY_BG, text_color=TEXT, font=("TkDefaultFont", 8), corner_radius=6, border_width=0, height=90)
        self.feed.grid(row=0, column=0, sticky="nsew")
        self.feed.configure(state="disabled")
        self.feed.clear = self._clear_feed

    def _clear_feed(self):
        self.feed.configure(state="normal")
        self.feed.delete("1.0", "end")
        self.feed.configure(state="disabled")

    def _feed(self, text):
        self.feed.configure(state="normal")
        self.feed.insert("end", text + "\n")
        self.feed.see("end")
        self.feed.configure(state="disabled")

    def progress_update(self, event):
        """Render one per-file pipeline event into the timeline and feed."""
        stage = event.get("stage", "")
        file = event.get("file", "")
        message = event.get("message", "")
        key = STAGE_TO_PHASE.get(stage)
        if key and key in self.timeline.states:
            self.timeline.start(key)
        if stage == "converted":
            if key and key in self.timeline.states:
                self.timeline.done(key)
        if message:
            self._feed(message)
        elif file:
            self._feed(f"{stage}: {file}")


    def _reset_live_state(self):
        """Reset the live per-run telemetry so a new run never inherits the last run's numbers."""
        self.ctx = None
        self.started_at = 0.0
        self.done_bytes = 0
        self.total_bytes = 0
        self.stage_counts = {}

    def set_preview_only(self, value):
        """Remember whether this run is preview-only (no files are actually moved or written)."""
        self.preview_only = bool(value)

    def refresh(self):
        """Rebuild the organize plan text from the current scan result and render it into the list."""
        archives = []
        state = getattr(self, "state", None)
        if state is not None:
            snapshot = state.get()
            scan_result = getattr(snapshot, "scan_result", None)
            if scan_result is not None:
                archives = list(getattr(scan_result, "archives", []) or [])
        lines = []
        for archive in archives:
            name = getattr(archive, "display_name", None) or getattr(archive, "normalized_title", None) or str(archive.path.name)
            artwork = getattr(archive, "artwork", None)
            has_art = artwork is not None and len(getattr(artwork, "files", lambda: [])()) > 0
            lines.append(f"{name}: {'artwork included' if has_art else 'artwork unavailable'}")
        self.list.configure(state="normal")
        self.list.delete("1.0", "end")
        if lines:
            self.list.insert("end", "\n".join(lines))
        else:
            self.list.insert("end", "No archives accepted yet.")
        self.list.configure(state="disabled")

    @staticmethod
    def _done(view, archives):
        """Mark the run complete: publish elapsed seconds and hand archives to the on_done callback.

        Deliberately does not publish run_bytes or run_written - those are never read and would report
        work the app did not actually do.
        """
        started_at = getattr(view, "started_at", 0.0)
        elapsed = time.monotonic() - started_at
        state = getattr(view, "state", None)
        if state is not None and hasattr(state, "update"):
            state.update(run_seconds=elapsed)
        on_done = getattr(view, "on_done", None)
        if on_done is not None:
            on_done(archives)

    def run_ended(self):
        """Called by MainWindow when an organize run ends (completed, failed, or cancelled).

        Resets the live per-file panel so the next run starts clean instead of inheriting
        the previous run's stage timeline and totals.
        """
        self._reset_live_state()
        try:
            self.work.grid_remove()
        except Exception:
            pass
