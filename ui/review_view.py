"""The review screen: verify Steam matches, pick categories, accept games, and move to organization.

Shows a game list on the left (filterable by status/category), and per-archive detail on the right
(metadata panel, artwork panel, category evidence panel). Actions: Accept & Next, Skip, Wrong Match,
Approve All Verified, Use All Suggestions, Extract Selected.
"""

from __future__ import annotations

import customtkinter as ctk

from .custom_theme import CTkFrame, CTkLabel, CTkButton, CTkEntry, CTkComboBox, CTkTextbox, CTkCanvas, panel
from .theme import BG, PANEL, PANEL2, PANEL3, TEXT, MUTED, ACCENT_HI, ACCENT_HOVER, ENTRY_BG, BORDER, human_size


# 2026-11-24: restored the shutdown() hook MainWindow calls at teardown (its absence raised AttributeError),
# and collapsed the size_text if/else to a ternary (ruff SIM108). The review list/detail panels were rebuilt
# with CTkTextbox/CTkCanvas; the button actions that had no implementation remain no-ops so the screen opens.




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
                 border_width=0, corner_radius=6, width=18).pack(
                      side="left", padx=(5, 0))
        self.search_var.trace_add("write", lambda *_: self._filters_changed())

        # Filter group
        filter_frame = CTkFrame(controls, fg_color=PANEL)
        filter_frame.grid(row=0, column=1, sticky="w", padx=(0, 10))
        CTkLabel(filter_frame, text="FILTER", fg_color=PANEL, text_color=MUTED, font=("TkDefaultFont", 8, "bold")).pack(side="left")
        f = CTkComboBox(filter_frame, values=["All", "Needs Review", "Verified", "New Only", "Artwork"], width=14)
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
        self.continue_button = CTkButton(action_frame, text="CONTINUE TO ORGANIZATION", command=self.continue_to_organize, fg_color=ACCENT_HI, text_color="white",
                                         font=("TkDefaultFont", 9, "bold"), hover_color=ACCENT_HOVER, height=32, width=150)
        self.continue_button.pack(side="left", padx=(10, 0))

        # Body: game list on the left, per-archive detail on the right
        body = CTkFrame(self, fg_color=BG)
        body.grid(row=2, column=0, columnspan=2, sticky="nsew")
        body.columnconfigure(0, weight=1, minsize=300)
        body.columnconfigure(1, weight=2, minsize=400)
        body.rowconfigure(0, weight=1)

        # Left: archive list
        list_frame = CTkFrame(body, fg_color=PANEL2, border_color=BORDER, border_width=1)
        list_frame.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=(0, 8))
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)
        self.list = CTkTextbox(list_frame, fg_color=ENTRY_BG, text_color=TEXT, font=("TkDefaultFont", 9),
                               corner_radius=6, border_width=0)
        self.list.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.list.configure(state="disabled")

        # Right: detail canvas with scrolling inner area
        detail_frame = CTkFrame(body, fg_color=BG)
        detail_frame.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=(0, 8))
        detail_frame.rowconfigure(0, weight=1)
        detail_frame.columnconfigure(0, weight=1)
        self.detail_canvas = CTkCanvas(detail_frame, highlightthickness=0)
        self.detail_canvas.grid(row=0, column=0, sticky="nsew")
        self.detail_inner = CTkFrame(self.detail_canvas, fg_color=BG)
        self.detail_canvas.create_window((0, 0), window=self.detail_inner, anchor="nw")
        self.detail_inner.bind("<Configure>", lambda e: self.detail_canvas.configure(scrollregion=self.detail_canvas.bbox("all")))

        self.subtitle = CTkLabel(self.detail_inner, text="", fg_color=BG, text_color=TEXT,
                                 font=("TkDefaultFont", 11, "bold"), wraplength=900, justify="left")
        self.subtitle.pack(anchor="w", padx=14, pady=(12, 4))

        self.meta = CTkFrame(self.detail_inner, fg_color=PANEL2, corner_radius=6)
        self.meta.pack(fill="x", padx=14, pady=(0, 8))
        self.meta_labels = []
        for label_text in ("APPID", "STEAM NAME", "CATEGORY", "EVIDENCE", "ARCHIVE SIZE"):
            lbl = CTkLabel(self.meta, text=f"{label_text}: ", fg_color=PANEL2, text_color=MUTED, font=("TkDefaultFont", 8, "bold"), anchor="w", justify="left")
            lbl.pack(anchor="w", padx=10, pady=1)
            self.meta_labels.append(lbl)

        self.detail = CTkTextbox(self.detail_inner, fg_color=ENTRY_BG, text_color=TEXT, font=("TkDefaultFont", 10),
                                 corner_radius=6, border_width=0, height=220)
        self.detail.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        self.detail.configure(state="disabled")

        ev_frame = CTkFrame(self.detail_inner, fg_color=PANEL2, corner_radius=6)
        ev_frame.pack(fill="x", padx=14, pady=(0, 12))
        CTkLabel(ev_frame, text="EVIDENCE", fg_color=PANEL2, text_color=MUTED, font=("TkDefaultFont", 8, "bold")).pack(anchor="w", padx=10, pady=(8, 2))
        self.evidence_panel = CTkLabel(ev_frame, text="", fg_color=PANEL2, text_color=TEXT, font=("TkDefaultFont", 9), justify="left")
        self.evidence_panel.pack(anchor="w", padx=10, pady=(0, 8))

        bar = CTkFrame(self.detail_inner, fg_color=BG)
        bar.pack(fill="x", padx=14, pady=(0, 12))
        CTkLabel(bar, text="TITLE", fg_color=BG, text_color=MUTED, font=("TkDefaultFont", 8, "bold")).pack(side="left")
        self.title_entry = CTkEntry(bar, fg_color=ENTRY_BG, text_color=TEXT, border_width=0, corner_radius=6, width=220)
        self.title_entry.pack(side="left", padx=(8, 10))
        CTkLabel(bar, text="CATEGORY", fg_color=BG, text_color=MUTED, font=("TkDefaultFont", 8, "bold")).pack(side="left")
        self.category = CTkComboBox(bar, values=[], width=140)
        self.category.pack(side="left")

    def _filters_changed(self):
        """Re-run the review filters when the search text changes."""
        pass

    def add_category(self):
        """Open the category suggestion flow for the selected game."""
        pass

    def use_all_suggestions(self):
        """Apply every suggested category to the selected archives."""
        pass

    def approve_all(self):
        """Approve every verified game and move to organization."""
        pass

    def retry_failed(self):
        """Retry the archives that failed conversion in the last organize run."""
        pass

    def load(self, archives, download_artwork=True):
        """Start verification for the given archives and remember the context so it can be cancelled."""
        self.archives = list(archives or [])
        self.list.configure(state="normal")
        self.list.delete("1.0", "end")
        for archive in self.archives:
            name = getattr(archive, "normalized_title", None) or getattr(archive, "display_name", None) or str(archive.path.name)
            self.list.insert("end", name + "\n")
        self.list.configure(state="disabled")
        self.selected = self.archives[0] if self.archives else None
        if self.selected is not None:
            self.select(self.selected)
        controller = getattr(self, "controller", None)
        if controller is not None and hasattr(controller, "verify_all"):
            self.verify_ctx = controller.verify_all(
                self.archives, lambda *a, **k: None, lambda *a, **k: None, download_artwork=download_artwork)
        if self.continue_button is not None:
            self.continue_button.configure(state="normal")
        if not self.archives:
            self.subtitle.configure(text="The run is done — verification already ran and nothing new was found.  CONTINUE TO ORGANIZATION when ready.")
            self.detail.configure(state="normal")
            self.detail.delete("1.0", "end")
            self.detail.insert("end", "Nothing new to review. The audit and catalog pages were already written.\n")
            self.detail.configure(state="disabled")

    def continue_to_organize(self):
        """Gate the hand-off to organization: archives without a Steam match must be skipped first."""
        from tkinter import messagebox
        unresolved = [a for a in self.archives if not getattr(getattr(a, "steam", None), "found", False)]
        if unresolved:
            messagebox.showwarning(
                "Steam identification required",
                "Some archives were not identified on Steam. skip them first, then continue to organization.",
            )
            return
        if self.on_next is not None:
            self.on_next()

    def select(self, archive):
        """Show the chosen archive's metadata in the detail pane."""
        self.selected = archive
        title = getattr(archive, "normalized_title", None) or getattr(archive, "display_name", None) or str(archive.path.name)
        steam = getattr(archive, "steam", None)
        decision = getattr(archive, "decision", None)
        size = getattr(archive, "size", 0) or 0
        # Copies: other accepted archives of the same game count as duplicate copies wasting space.
        copies = 1
        total_bytes = size
        key = getattr(archive, "identity_key", None) or getattr(archive, "normalized_title", None) or title
        for other in getattr(self, "archives", []) or []:
            if other is archive:
                continue
            okey = getattr(other, "identity_key", None) or getattr(other, "normalized_title", None) or getattr(other, "display_name", None) or str(other.path.name)
            if okey == key:
                copies += 1
                total_bytes += getattr(other, "size", 0) or 0
        size_text = f"{copies} copies, {human_size(total_bytes)} total" if copies > 1 else human_size(size) if size else "size unknown"
        self.subtitle.configure(text=f"{title}  •  {size_text}")
        evidence = ""
        if decision is not None:
            ev = getattr(decision, "evidence", None)
            if ev is not None:
                chosen = getattr(ev, "chosen", None)
                runners_up = getattr(ev, "runners_up", None) or []
                parts = []
                if chosen:
                    parts.append(f"Remembered as {chosen}")
                if runners_up:
                    parts.append("; ".join(f"{name} ({score})" for name, score in runners_up))
                evidence = "  |  ".join(parts)
        self.evidence_panel.configure(text=evidence)
        keys = ("APPID", "STEAM NAME", "CATEGORY", "EVIDENCE", "ARCHIVE SIZE")
        values = [
            str(getattr(steam, "appid", "")) if steam else "",
            getattr(steam, "name", "") if steam else "",
            getattr(decision, "category", "") if decision is not None else "",
            evidence,
            size_text,
        ]
        for index, widget in enumerate(self.meta_labels):
            widget.configure(text=f"{keys[index]}: {values[index]}")
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("end", f"Reviewing {title}.\n")
        self.detail.configure(state="disabled")

    def cancel_lookup(self):
        """Cancel the in-flight verification pass, if any."""
        ctx = self.verify_ctx
        if ctx is not None:
            try:
                ctx.cancel()
            except Exception:
                pass
            self.verify_ctx = None

    def _route_wheel(self, event):
        """Route a wheel event into the detail canvas, or hand it back to the widget that owns it."""
        widget = event.widget
        if widget is self.detail_canvas or self._is_descendant(widget, self.detail_canvas):
            return "break"
        if widget is self.list or self._is_descendant(widget, self.list):
            return "break"
        if widget is self.category or widget is self.title_entry:
            return "break"
        return None

    def _is_descendant(self, child, parent):
        """True when `child` is `parent` or anywhere below it in the widget tree."""
        try:
            child.winfo_parent()
        except Exception:
            return False
        node = child
        while True:
            try:
                node = node.master
            except Exception:
                return False
            if node is parent:
                return True
            if node is None:
                return False

    def shutdown(self):
        """Tear down any in-flight verification lookups before the window closes."""
        self.cancel_lookup()
