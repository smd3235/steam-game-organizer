"""The scan screen: phases, progress bar, activity feed, and the Convert Archives toggle.

ScanView shows the live timeline of cleanup, dedupe, repair, discover, audit and catalog; draws a
progress bar split into extract/compress/verify slices keyed off SCAN_STAGE_SPAN; and renders the
activity feed as work completes. It owns the on-scan, on-choose, on-cancel and on-scan-artwork
callbacks that MainWindow wires up, plus the Convert Archives checkbox whose saved state feeds the
organize pass.
"""

from __future__ import annotations

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog
from urllib.request import Request, urlopen
from urllib.parse import urlparse
import os
import shutil
from pathlib import Path
from .custom_theme import CTk, CTkToplevel, CTkFrame, CTkLabel, CTkButton, CTkEntry, CTkComboBox, CTkScrollbar, CTkTextbox, CTkCheckBox, CTkRadioButton, CTkProgressBar, CTkCanvas, Theme, panel, pill, wheel_step, bind_wheel, pin_bottom
from .theme import BG, PANEL, PANEL2, PANEL3, TEXT, MUTED, ACCENT_HI, ACCENT_HOVER, ACCENT, ORANGE, RED, CYAN
from .theme import BG, PANEL, PANEL2, TEXT, MUTED, ACCENT_HI, ACCENT
from core.constants import USER_AGENT
from core.scan_view_utils import ago, space_delta, size

# 2026-11-20: Bandit B310 — validate URL scheme before urlopen to prevent
# file:// or custom scheme attacks. The SteamGridDB URL is hardcoded https,
# but bandit cannot statically confirm this.
def _safe_urlopen(req, timeout=12):
    parsed = urlparse(req.full_url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsafe URL scheme: {parsed.scheme}")
    return urlopen(req, timeout=timeout)  # nosec B310 — scheme validated above

# Every phase a scan runs through, in order. Shown as a live timeline so the user can always see which step
# is running, which already finished, and which were skipped (Preview Only).
SCAN_PHASES = (("cleanup", "Cleanup"), ("dedupe", "Dedupe"), ("repair", "Repair"), ("discover", "Discover"), ("audit", "Audit"), ("catalog", "Catalog"))

# Each stage owns a slice of ONE archive's conversion, so the bar can place the tool's own percentage inside
# it and move continuously. Extraction is cheap against compression at level 9, so it gets the first quarter
# and compression - the part that takes fifteen minutes - gets most of the slice. This is the scan pass's own
# weights and they are deliberately not the organize pass's, measured on a different run: ORGANIZE_STAGE_SPAN
# in organize_view.py gives verification a larger share because that pass re-reads a rebuilt archive. The two
# shared the name STAGE_SPAN while holding different numbers, so editing one silently left the other alone.
SCAN_STAGE_SPAN = {"extracting": (0.0, 0.25), "compressing": (0.25, 0.92), "verifying": (0.92, 1.0)}


class ScanView(ctk.CTkFrame):
    def __init__(self, parent, on_scan, on_choose=None, on_cancel=None, on_scan_artwork=None, scan_summary=None):
        super().__init__(parent, fg_color=BG)
        self.on_scan = on_scan
        self.on_choose = on_choose
        self.on_cancel = on_cancel
        self.on_scan_artwork = on_scan_artwork
        self.scanning = False
        self.config = None
        self.library_root = None
        # Attached by MainWindow.build() once the view exists. The convert_var trace below fires on the
        # initial `set()` that shows the saved setting, which happens before there is a controller to
        # write to, so the callback has to tolerate its absence - it used to dereference self.controller
        # from a lambda and raise AttributeError into Tk on every launch.
        self.controller = None
        # What the previous scan found, read once at construction. Shown while this one has not started, which is
        # when the activity panel below has nothing in it: the panel is about 840px tall at idle and its content is
        # 212px, so it is either holding the running run's telemetry or holding nothing at all.
        self.scan_summary = scan_summary or {}
        # Live conversion telemetry. The repair pass can run for an hour over a large library, and none of
        # this was recorded, so the panel could only ever name the file it was on.
        self.repair_done = 0
        self.repair_free = 0
        self.repair_total = 0
        self.repair_index = 0
        self.repair_grown = 0
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        CTkLabel(self, text="COMMAND CENTER", fg_color=PANEL, text_color=ACCENT_HI, font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0, sticky="w")
        CTkLabel(self, text="Game Archive Scanner", fg_color=BG, text_color=TEXT, font=("TkDefaultFont", 24, "bold")).grid(row=1, column=0, sticky="nw", pady=(2, 0))
        body = CTkFrame(self, fg_color=BG)
        body.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        body.columnconfigure(0, weight=1, minsize=550)
        body.columnconfigure(1, weight=0, minsize=350)
        body.rowconfigure(0, minsize=90)
        body.rowconfigure(1, weight=1, minsize=220)
        cfg = panel(body)
        cfg.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        cfg.configure(height=90)

        # Convert Archives checkbox + two buttons side by side
        conv_row = CTkFrame(cfg, fg_color=BG)
        conv_row.pack(fill="x", padx=14, pady=(6, 0))
        conv_row.columnconfigure(0, weight=1)
        self.convert_var = ctk.BooleanVar(value=self.config.convert_archives if self.config else False)
        self.convert_var.trace_add("write", self._on_convert_change)
        self.convert_cb = CTkCheckBox(conv_row, text="Convert Archives", variable=self.convert_var,
                                      fg_color=PANEL2, text_color=TEXT, hover_color=ACCENT_HOVER,
                                      font=("TkDefaultFont", 9))
        self.convert_cb.pack(side="left", padx=(0, 10))
        self.scan_btn = CTkButton(conv_row, text="Start Scan", command=self.scan,
                                  fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=TEXT,
                                  font=("TkDefaultFont", 9, "bold"), height=32, width=120)
        self.scan_btn.pack(side="left", padx=(0, 6))
        self.art_btn = CTkButton(conv_row, text="Scan + Artwork", command=self.scan_new_artwork,
                                 fg_color=PANEL2, hover_color=PANEL3, text_color=TEXT,
                                 font=("TkDefaultFont", 9), height=32, width=120)
        self.art_btn.pack(side="left", padx=(0, 0))
        # preview-only checkbox on the right
        self.preview_var = ctk.BooleanVar(value=self.run_preview_only)
        self.preview_cb = CTkCheckBox(conv_row, text="Preview Only", variable=self.preview_var,
                                      fg_color=PANEL2, text_color=TEXT, hover_color=ACCENT_HOVER,
                                      font=("TkDefaultFont", 9))
        self.preview_cb.pack(side="right")

        # Phase timeline strip under the toolbar
        row_frame = CTkFrame(body, fg_color=BG)
        row_frame.pack(fill="x", padx=14, pady=(0, 6))
        CTkLabel(row_frame, text="PHASES", fg_color=MUTED, text_color=MUTED, font=("TkDefaultFont", 8, "bold")).pack(side="left", pady=(0, 4))
        self._phase_labels = {}
        for i, (key, label) in enumerate(SCAN_PHASES):
            lbl = CTkLabel(row_frame, text=label, fg_color=BG, text_color=MUTED, font=("TkDefaultFont", 8), anchor="center", width=12)
            lbl.pack(side="left", expand=True)
            self._phase_labels[key] = lbl

        # Progress bar
        prog_frame = CTkFrame(body, fg_color=BG)
        prog_frame.pack(fill="x", padx=14, pady=(2, 8))
        self.progress = CTkProgressBar(prog_frame, width=500, height=16)
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.progress.set(0)
        self.stage_label = CTkLabel(prog_frame, text="Idle", fg_color=BG, text_color=MUTED, font=("TkDefaultFont", 8))
        self.stage_label.pack(side="left")

        # Right column: activity feed
        right = CTkFrame(body, fg_color=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        CTkLabel(right, text="SCAN ACTIVITY", fg_color=PANEL, text_color=ACCENT_HI, font=("TkDefaultFont", 9, "bold")).pack(anchor="w", padx=10, pady=(8, 4))
        self.activity = CTkTextbox(right, width=280, height=200, fg_color=ENTRY_BG, text_color=TEXT,
                                   font=("TkDefaultFont", 8), corner_radius=6, border_width=0)
        self.activity.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.activity.configure(state="disabled")

        # status line at bottom
        self.current = CTkLabel(body, text="Idle", fg_color=BG, text_color=TEXT, font=("TkDefaultFont", 9))
        self.current.pack(fill="x", padx=14, pady=(2, 6))

        # Runtime button row (hidden until scanning starts)
        self._run_controls = CTkFrame(body, fg_color=BG)
        self._run_controls.pack(fill="x", padx=14, pady=(0, 8))
        self._run_controls.pack_forget()
        self.cancel_btn = CTkButton(self._run_controls, text="Cancel Scan", command=self.cancel_run,
                                    fg_color=RED, hover_color="#c0392b", text_color="white",
                                    font=("TkDefaultFont", 9, "bold"), height=30)
        self.cancel_btn.pack(side="left")

    def _on_convert_change(self, *_args):
        """Called when the Convert Archives checkbox changes. Writes through to config immediately
        so the value survives restarts."""
        if self.controller:
            try:
                self.controller.services.archive.convert_archives = bool(self.convert_var.get())
            except AttributeError:
                pass

    # ------------------------------------------------------------------ behaviour

    def begin_scan(self, quick=False):
        self.scan_dir = None
        self.scan_files = None
        self.files_to_scan = None
        self.current_index = 0
        self.files_remaining = 0
        self.current_file = None
        self.archive_queue.clear()
        self.pending_lookups.clear()
        self.current_archive = None
        self.current_archive_index = None
        self.current_file_index = None
        self.current_archive_name = None
        self.current_size = None
        self.current_size_str = None
        self.cancelled = False
        self.active_task = None
        self.last_progress_ts = None
        self.last_progress_interval = None
        self.bytes_read = 0
        self.total_size = None
        self._stop_event = None
        self._stop_event = threading.Event()
        self.active_job = None

    def scanning(self):
        return self._scan_state == "scanning"

    def set_library(self, path):
        self.library_root = path

    def load_api(self, key):
        self.api_key = key

    def cancel_run(self):
        if not self.scanning:
            return
        self.cancelled = True
        if self._stop_event:
            self._stop_event.set()
        self.status.configure(text="Cancel requested — stopping safely…")

    def accept_archive(self, archive):
        pass

    def skip_archive(self, archive):
        pass

    def _set_phase(self, phase):
        for key, label in SCAN_PHASES:
            if key == stage:
                lbl.configure(fg_color=ACCENT_HI, text_color="white")
            else:
                lbl.configure(fg_color=BG, text_color=MUTED)

    def set_elapsed(self, text):
        if self.current == "scan":
            self.current.configure(text=f"RUNNING  •  {text}")

    def _start(self, text):
        self.busy = True
        self.started_at = time.monotonic()
        self.views["scan"].scanning = True
        self.views["scan"].cancel_btn.configure(state="normal")
        self.status.configure(text=text)
        self.runtime.configure(text="RUNNING  •  00:00")
