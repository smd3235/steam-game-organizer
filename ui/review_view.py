"""The review screen: verify Steam matches, pick categories, accept games, and move to organization.

Shows a game list on the left (filterable by status/category), and per-archive detail on the right
(metadata panel, artwork panel, category evidence panel). Actions: Accept & Next, Skip, Wrong Match,
Approve All Verified, Use All Suggestions, Extract Selected.
"""

from __future__ import annotations

import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from utils.desktop import open_url
from .widgets.game_list import GameList
from .widgets.metadata_panel import MetadataPanel
from .widgets.artwork_panel import ArtworkPanel
from .widgets.category_evidence_panel import CategoryEvidencePanel

from .custom_theme import CTk, CTkToplevel, CTkFrame, CTkLabel, CTkButton, CTkEntry, CTkComboBox, CTkScrollbar, CTkTextbox, CTkCheckBox, CTkRadioButton, CTkProgressBar, CTkCanvas, Theme, panel, pill, wheel_step, bind_wheel, pin_bottom
from core.canonical_category import canonical_category
from core.constants import DEFAULT_CATEGORIES, SUPPLEMENTAL_CATEGORIES
from services.installer_detect import NEEDS_INSTALL_DIRNAME
from core.models import ArtworkResult, SteamMatch
from services.batch_extract_service import BatchPlan, BatchItem
from ui.batch_extract_window import run_batch_window

# Additional imports for extract_selected
from services.archive_service import ArchiveService
from services.catalog_status import already_extracted
from core.safe_folder_name import safe_folder_name
from pathlib import Path


class ReviewView(ctk.CTkFrame):
    def __init__(self, parent, controller, state, logger, jobs, on_next=None, on_verified=None, on_verification_progress=None):
        super().__init__(parent, fg_color=BG)
        self.controller = controller
        self.state = state
        self.logger = logger
        self.jobs = jobs
        self.on_next = on_next
        self.on_verified = on_verified
        self.on_verification_progress = on_verification_progress
        self.selected = None
        self.verify_ctx = None
        self.archives = []
        self.search_var = ctk.StringVar()
        self.filter_var = ctk.StringVar(value="All")
        self.mode_var = ctk.StringVar(value="New Only")
        # Column widths: left panel (games list) takes ~34%, right panel (details) takes ~66%.
        # minsize keeps both panels usable at narrow window sizes.
        self.columnconfigure(0, weight=34, minsize=350)
        self.columnconfigure(1, weight=66)
        self.rowconfigure(2, weight=1)
        head = CTkFrame(self, fg_color=BG)
        head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 7))
        CTkLabel(head, text="GAME REVIEW", fg_color=PANEL, text_color=ACCENT_HI, font=("TkDefaultFont", 9, "bold")).pack(side="left")
        self.progress = CTkLabel(head, text="Verification idle", fg_color=BG, text_color=MUTED, font=("TkDefaultFont", 9, "bold"))
        self.progress.pack(side="right")
        self.summary = CTkLabel(head, text="", fg_color=BG, text_color=TEXT, font=("TkDefaultFont", 8, "bold"))
        self.summary.pack(side="right", padx=18)
        controls = panel(self)
        controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        controls.columnconfigure(0, weight=1)

        # Search group
        search_frame = CTkFrame(controls, fg_color=PANEL)
        search_frame.grid(row=0, column=0, sticky="w", padx=(0, 10))
        CTkLabel(search_frame, text="SEARCH", fg_color=PANEL, text_color=MUTED, font=("TkDefaultFont", 8, "bold")).pack(side="left")
        CTkEntry(search_frame, textvariable=self.search_var, fg_color=PANEL2, text_color=TEXT,
                 disabledforeground=MUTED, insertbackground=TEXT, border_width=0, corner_radius=6, width=18).pack(
                      side="left", padx=(5, 0))
        self.search_var.trace_add("write", lambda *_: self._filters_changed())
        # Filter group
        filter_frame = CTkFrame(controls, fg_color=PANEL)
        filter_frame.grid(row=0, column=1, sticky="w", padx=(0, 10))
        CTkLabel(filter_frame, text="FILTER", fg_color=PANEL, text_color=MUTED, font=("TkDefaultFont", 8, "bold")).pack(side="left")
        f = CTkComboBox(filter_frame, textvariable=self.filter_var, values=["All", "Needs Review", "Verified", "New Only", "Artwork"], width=14)
        f.pack(side="left", padx=(5, 0))
        f.bind("<<ComboboxSelected>>", lambda e: self._filters_changed())
        # Action group
        action_frame = CTkFrame(controls, fg_color=PANEL)
        action_frame.grid(row=0, column=3, sticky="e")
        CTkButton(action_frame, text="＋ Add Category", command=self.add_category, fg_color=PANEL2, text_color=TEXT,
                  font=("TkDefaultFont", 9), hover_color=PANEL3, height=32, width=100).pack(side="left", padx=(0, 4))
        CTkButton(action_frame, text="Use All Suggestions", command=self.use_all_suggestions, fg_color=PANEL2, text_color=TEXT,
                  font=("TkDefaultFont", 9), hover_color=PANEL3, height=32, width=120).pack(side="left", padx=(0, 4))
        self.approve_all_button = CTkButton(action_frame, text="Approve All Verified", command=self.approve_all, fg_color=ACCENT_HI, text_color=TEXT,
                font=("TkDefaultFont", 9, "bold"), hover_color=ACCENT_HOVER, height=32, width=110)
        self.approve_all_button.pack(side="left", padx=(4, 0))
        self.retry_failed_button = CTkButton(action_frame, text="Retry Failed", command=self.retry_failed, fg_color=PANEL2, text_color=TEXT,
                font=("TkDefaultFont", 9), hover_color=PANEL3, height=32, width=100)
        self.retry_failed_button.pack(side="left", padx=(4, 0))
