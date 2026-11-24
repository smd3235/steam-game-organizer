"""The organize screen: takes accepted archives, converts ZIP/RAR to 7z, moves them into category folders,
writes artwork and catalog pages, and shows a live per-file progress bar with per-stage timing.

OrganizeView displays the batch organization run with a per-file timeline (Move/Extract/Compress/Verify),
a progress bar split across stages, and a live activity feed. It owns the on_done callback that MainWindow
wires to show the Done screen once organization completes.
"""

from __future__ import annotations

import customtkinter as ctk
import shutil
import time
from pathlib import Path
from tkinter import filedialog, messagebox
from .custom_theme import CTk, CTkToplevel, CTkFrame, CTkLabel, CTkButton, CTkEntry, CTkComboBox, CTkScrollbar, CTkTextbox, CTkCheckBox, CTkRadioButton, CTkProgressBar, CTkCanvas, Theme, panel, pill, wheel_step, bind_wheel, pin_bottom
from .theme import ACCENT_HI, BG, BORDER, CYAN, GREEN, MUTED, ORANGE, PANEL, PANEL2, RED, TEXT
from services.organizer_service import OrganizerService

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
