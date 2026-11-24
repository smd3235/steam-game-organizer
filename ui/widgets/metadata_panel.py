"""The metadata panel on the Review screen — shows Steam match details (title, AppID,
release date, confidence, score, suggested category) and artwork-related metadata (genres,
tags, source, publisher, archive path/size) beneath the game card."""

from __future__ import annotations

import customtkinter as ctk
import tkinter as tk
from ui.theme import ACCENT_HI, BG, BORDER, GREEN, MUTED, ORANGE, PANEL, PANEL2, PANEL3, RED, TEXT, Theme, human_size, pill


class MetadataPanel(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color=PANEL)
        self.cells = []

    def show(self, a, copies=None):
        for w in self.winfo_children():
            w.destroy()
        s = a.steam
        CTkLabel(self, text="STEAM DETAILS", fg_color=PANEL, text_color=ACCENT_HI, font=("TkDefaultFont", 9, "bold")).pack(anchor="w", padx=14, pady=(9, 5))
        identity = CTkFrame(self, fg_color=PANEL)
        identity.pack(fill="x", padx=14, pady=(0, 5))
        identity.columnconfigure(1, weight=3)
        identity.columnconfigure(3, weight=1)
        identity.columnconfigure(5, weight=1)
        identity.columnconfigure(7, weight=1)
        identity.columnconfigure(9, weight=1)
        identity.columnconfigure(11, weight=1)
        vals = [("Steam Title", s.name or "Unresolved"), ("AppID", s.appid or "—"),
            ("Release", s.release_date or "—"), ("Confidence", s.confidence or "—"),
            ("Score", f"{s.score:.0%}" if s.score else "—"),
            ("Suggested", a.decision.suggested_category or a.decision.category)]
        for i, (key, value) in enumerate(vals):
            column = i * 2
            CTkLabel(identity, text=key.upper(), fg_color=PANEL, text_color=MUTED, font=("TkDefaultFont", 7, "bold")).grid(row=0, column=column, sticky="w", padx=(0, 4))
            CTkLabel(identity, text=value, fg_color=PANEL, text_color=TEXT, font=("TkDefaultFont", 8), anchor="w").grid(row=0, column=column + 1, sticky="ew", padx=(0, 9))
        own = int(getattr(a, "size", 0) or 0)
        group = list(copies) if copies else [a]
        total = sum(int(getattr(c, "size", 0) or 0) for c in group)
        size_text = human_size(own) if own else "—"
        if len(group) > 1:
            size_text = f"{size_text}  •  {human_size(total)} across {len(group)} copies"
        rows = [("Genres", ", ".join(s.genres) or "—"), ("Steam Categories", ", ".join(s.categories) or "—")]
        if s.tags:
            rows.append(("Tags", ", ".join(s.tags) or "—"))
        rows.extend([
            ("Source / Developer", f"{s.source or chr(8212)}  •  {s.developer or chr(8212)}"),
            ("Publisher", s.publisher or "—"),
            ("Archive / Detected", f"{a.path.name}  •  {a.normalized_title}"),
            ("Archive Size", size_text)])
        detail = CTkFrame(self, fg_color=PANEL)
        detail.pack(fill="x", padx=14, pady=(0, 6))
        detail.columnconfigure(1, weight=1)
        for row, (key, value) in enumerate(rows):
            CTkLabel(detail, text=key.upper(), fg_color=PANEL, text_color=MUTED, font=("TkDefaultFont", 7, "bold")).grid(row=row, column=0, sticky="nw", padx=(0, 8), pady=2)
            CTkLabel(detail, text=value, fg_color=PANEL, text_color=TEXT, font=("TkDefaultFont", 8), anchor="w", wraplength=760, justify="left").grid(row=row, column=1, sticky="ew", pady=2)
        if s.source or s.confidence or s.reason:
            trust = CTkFrame(self, fg_color=PANEL)
            trust.pack(fill="x", padx=14, pady=(0, 6))
            CTkLabel(trust, text="MATCH TRUST", fg_color=PANEL, text_color=ACCENT_HI, font=("TkDefaultFont", 8, "bold")).pack(anchor="w", pady=(0, 4))
            chips = CTkFrame(trust, fg_color=PANEL)
            chips.pack(fill="x", pady=(0, 4))
            if s.source:
                conf_kind = {"High": "good", "Medium": "warn", "Low": "bad"}.get(s.confidence, "muted") if s.confidence else "muted"
                pill(chips, s.source, conf_kind).pack(side="left", padx=(0, 6))
            if s.confidence:
                conf_kind = {"High": "good", "Medium": "warn", "Low": "bad"}.get(s.confidence, "muted") if s.confidence else "muted"
                pill(chips, s.confidence, conf_kind).pack(side="left", padx=(0, 6))
            if s.score:
                CTkLabel(chips, text=f"score {s.score:.0%}", fg_color=PANEL, text_color=TEXT, font=("TkDefaultFont", 8)).pack(side="left", padx=(0, 6))
            if s.reason:
                CTkLabel(trust, text=s.reason, fg_color=PANEL, text_color=MUTED, font=("TkDefaultFont", 8), anchor="w", wraplength=400, justify="left").pack(fill="x", pady=(2, 0))