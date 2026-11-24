"""Artwork review screen: shows each accepted game's downloaded artwork assets (hero/grid/logo/icon)
with a clickable card per game and an "Open Game Folder" button that launches the archive's folder."""

from __future__ import annotations

import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
from ui.theme import ACCENT_HI, BG, BORDER, GREEN, MUTED, ORANGE, PANEL, PANEL2, TEXT, Theme, panel, pin_bottom
from .widgets.artwork_panel import ArtworkPanel
from ui.custom_theme import CTkToplevel, CTkFrame, CTkLabel, CTkButton, CTkCanvas

from services.organizer_service import OrganizerService


def _asset_prefix_for(archive):
    """The filename prefix this game's artwork actually carries on disk.

    Taken from OrganizerService._asset_prefix, which is what writes the files, rather than a second opinion
    formed here. The screen used to collapse whitespace with ' '.join(name.split()), which agrees with the
    sanitiser on ordinary names and disagrees on every name holding a character the sanitiser removes - so
    'Settlements: Legacy' was listed as 'Settlements: Legacy_grid.jpg' while the file on disk was
    'Settlements Legacy_grid.jpg', and a name that is nothing but punctuation was listed as '???' against a
    file called 'Unnamed Game'. Four of twelve real Steam names were wrong.
    """
    # Delegated to OrganizerService._asset_prefix(), which is the function move() writes the filenames with,
    # rather than a copy of its body. A second copy of that expression is exactly how this screen came to name
    # files that do not exist: the prefix here had drifted from the prefix there. _asset_prefix() reads no
    # instance state, so it can be called on an unbound instance.
    return OrganizerService._asset_prefix(archive)


class ArtworkView(ctk.CTkFrame):
    def __init__(self, parent, on_done, on_review=None):
        super().__init__(parent, fg_color=BG)
        self.on_done = on_done
        self.on_review = on_review
        self.archives = []
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        CTkLabel(self, text="ARTWORK", fg_color=PANEL, text_color=ACCENT_HI, font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0, sticky="w")
        CTkLabel(self, text="Artwork & Steam assets", fg_color=BG, text_color=TEXT, font=("TkDefaultFont", 24, "bold")).grid(row=1, column=0, sticky="nw")
        shell = panel(self)
        shell.grid(row=2, column=0, sticky="nsew", pady=(18, 0))
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)
        self.canvas = CTkCanvas(shell, fg_color=PANEL, highlightthickness=0)
        self.scroll = ttk.Scrollbar(shell, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=(12, 0), pady=12)
        self.scroll.grid(row=0, column=1, sticky="ns", pady=12)
        self.inner = CTkFrame(self.canvas, fg_color=PANEL)
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.winfo_toplevel().bind(seq, self._route_wheel, add="+")
        self._bind_content_wheel(self.inner)
        actions = CTkFrame(self, fg_color=BG)
        actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.summary = CTkLabel(actions, text="", fg_color=BG, text_color=MUTED, font=("TkDefaultFont", 9), anchor="w")
        self.summary.pack(side="left", fill="x", expand=True)
        CTkButton(actions, text="CONTINUE TO DONE  ›", fg_color=ACCENT_HI, hover_color=ACCENT_HOVER, text_color=TEXT,
                  font=("TkDefaultFont", 9, "bold"), command=self.on_done).pack(side="right")

    def _wheel(self, event):
        self.canvas.yview_scroll(-1 if getattr(event, "delta", 0) > 0 or getattr(event, "num", 0) == 4 else 1, "units")
        return "break"

    def _route_wheel(self, event):
        widget = self.winfo_containing(event.x_root, event.y_root)
        if widget is None:
            return None
        if str(getattr(widget, "winfo_class", lambda: "")()) in ("TCombobox", "Listbox", "Entry", "TEntry"):
            return "break" if str(getattr(widget, "winfo_class", lambda: "")()) != "Listbox" else None
        ancestor = widget
        while ancestor is not None:
            if ancestor in (self.canvas, self.inner):
                return self._wheel(event)
            try:
                ancestor = ancestor.master
            except AttributeError:
                return None
        return None

    def _bind_content_wheel(self, widget):
        if isinstance(widget, ttk.Button):
            return
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(sequence, self._wheel, add="+")
        for child in widget.winfo_children():
            self._bind_content_wheel(child)

    def _open_folder(self, path):
        # Was shutil.which('xdg-open'), so on Windows every "OPEN GAME FOLDER" press did nothing at all -
        # no file manager, no message, nothing logged. See utils/desktop.py.
        from utils.desktop import open_folder

        open_folder(path)

    def show(self, archives):
        self.archives = list(archives)
        for child in self.inner.winfo_children():
            child.destroy()
        artwork_count = 0
        asset_count = 0
        accepted_count = sum(1 for archive in self.archives if archive.decision.accepted)
        if not accepted_count:
            empty_frame = CTkFrame(self.inner, fg_color=PANEL)
            empty_frame.pack(fill="x", padx=30, pady=40)
            CTkLabel(empty_frame, text="No organized games have artwork to review.", fg_color=PANEL, text_color=MUTED, font=("TkDefaultFont", 11), justify="center").pack()
            CTkLabel(empty_frame, text="Return to Review, accept a verified game, and organize it first.", fg_color=PANEL, text_color=MUTED, font=("TkDefaultFont", 10), justify="center").pack(pady=(6, 14))
            if self.on_review:
                CTkButton(empty_frame, text="← Go to Review", fg_color=ACCENT_HI, hover_color=ACCENT_HOVER, text_color="white",
                          font=("TkDefaultFont", 9, "bold"), command=self.on_review).pack()
        for archive in self.archives:
            if not archive.decision.accepted:
                continue
            card = CTkFrame(self.inner, fg_color=PANEL2, border_color=BORDER, border_width=1)
            card.pack(fill="x", pady=(0, 6), padx=2)
            card.columnconfigure(1, weight=1)
            preview = ArtworkPanel(card)
            preview.grid(row=0, column=0, rowspan=3, sticky="nw", padx=10, pady=10)
            preview.configure(width=150, height=190)
            preview.grid_propagate(False)
            preview.show(archive.artwork)
            CTkLabel(card, text=archive.steam.name or archive.display_name, fg_color=PANEL2, text_color=TEXT,
                     font=("TkDefaultFont", 12, "bold"), anchor="w").grid(row=0, column=1,
                     sticky="ew", padx=(0, 12), pady=(12, 3))
            CTkLabel(card, text=f"Folder: {archive.path.parent}", fg_color=PANEL2, text_color=MUTED,
                     font=("TkDefaultFont", 8), anchor="w", wraplength=700,
                     justify="left").grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=2)
            prefix = _asset_prefix_for(archive)
            names = []
            if archive.artwork.path and archive.artwork.path.is_file():
                names.append(f"{prefix}_{archive.artwork.path.suffix}")
                artwork_count += 1
            # The asset name is the dict KEY, exactly as LibraryService._audit_game writes it. It used to be
            # recovered from the cached file's stem with stem.split('_',1)[-1], which is a guess that holds only
            # while the cache happens to prefix every filename with the AppID - and that coupling is between two
            # modules that never mention it. With no prefix the split eats the first part of the key, so
            # 'capsule_616x353' was listed as '616x353'.
            for key, path in archive.artwork.assets.items():
                if path.is_file():
                    names.append(f"{prefix}_{key}{path.suffix}")
                    asset_count += 1
            link = "Steam Chrome shortcut created" if archive.steam.appid else "No Steam shortcut"
            CTkLabel(card, text=f"{link}\nAssets: {', '.join(names) if names else 'No artwork downloaded'}",
                     fg_color=PANEL2, text_color=GREEN if names else ORANGE, font=("TkDefaultFont", 8),
                     anchor="w", wraplength=700, justify="left").grid(row=2, column=1,
                     sticky="ew", padx=(0, 12), pady=(2, 12))
            CTkButton(card, text="OPEN GAME FOLDER", fg_color=PANEL2, hover_color=PANEL3, text_color=TEXT,
                      font=("TkDefaultFont", 9), command=lambda path=archive.path.parent: self._open_folder(path)).grid(
                        row=0, column=2, rowspan=3, padx=(0, 12), pady=10)
        self._bind_content_wheel(self.inner)
        self.summary.configure(text=f"{artwork_count} primary artwork files • {asset_count} additional Steam assets • {accepted_count} organized games")
        self.inner.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        pin_bottom(self.canvas)