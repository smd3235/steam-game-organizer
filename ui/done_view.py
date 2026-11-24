"""The done screen: final run summary with per-archive conversion results, artwork links, and action buttons.

DoneView shows the outcome of an organize run: which archives were converted, skipped, failed, or
not needed, with per-file byte savings and folder links. It also offers Undo (roll back the whole
run), Open Library, and Scan Again actions.
"""

from __future__ import annotations

import customtkinter as ctk
import tkinter as tk
import datetime
from pathlib import Path
import shutil
from .custom_theme import CTk, CTkToplevel, CTkFrame, CTkLabel, CTkButton, CTkEntry, CTkComboBox, CTkScrollbar, CTkTextbox, CTkCheckBox, CTkRadioButton, CTkProgressBar, CTkCanvas, Theme, panel, pill, wheel_step, bind_wheel, pin_bottom
from .theme import ACCENT_HI, BG, BORDER, CYAN, GREEN, MUTED, ORANGE, PANEL, PANEL2, RED, TEXT, human_duration, human_size
from core.constants import DEFAULT_CATEGORIES, SUPPLEMENTAL_CATEGORIES

# Outcome styling for the run report. Failures are the loudest thing on the screen on purpose: they are the
# only rows the user has to act on, so they must never be scrolled past unnoticed.
CONVERSION_BADGE = {
    "converted": ("converted to 7Z", GREEN),
    "rebuilt": ("rebuilt as 7Z", CYAN),
    "skipped": ("left as-is", ORANGE),
    "failed": ("FAILED", RED),
    "not_needed": ("already correct", MUTED),
    "archived": ("filed under Archive/", MUTED),
    "pending": ("", MUTED),
}


def badge_for(status):
    """Label for a conversion status. The named sections carry their own wording in their headings, but the
    catch-all NO CONVERSION RESULT section has to describe whatever status it finds, so it reads the label
    from here instead of inventing one. Unknown statuses fall back to the raw status text."""
    return CONVERSION_BADGE.get(status, CONVERSION_BADGE["pending"])


def _saved_bytes(note):
    """Bytes actually reclaimed by one conversion.

    Only meaningful once both sizes are known. A rebuild of an existing .7z has no saving, and a failed or
    skipped conversion saved nothing, so reporting a number there would be inventing one.
    """
    before = int(getattr(note, "source_size", 0) or 0)
    after = int(getattr(note, "final_size", 0) or 0)
    return before - after if before > after > 0 else 0


def _saved_label(note):
    """Human-readable size delta for one conversion.

    Positive deltas show as 'saved', negative ones as 'expanded by' (an archive that
    grew is worth flagging rather than hiding), and a zero or no-data conversion
    yields nothing — inventing a number there would be worse than silence.
    """
    saved = _saved_bytes(note)
    before = int(getattr(note, "source_size", 0) or 0)
    after = int(getattr(note, "final_size", 0) or 0)
    if saved > 0:
        share = f" ({saved / before:.0%})" if before else ""
        return f"saved {human_size(saved)}{share}"
    if before and after and after > before:
        share = f" ({abs(after - before) / before:.0%})"
        return f"expanded by {human_size(after - before)}{share}"
    return ""


class DoneView(ctk.CTkFrame):
    def __init__(self, parent, on_scan, on_undo=None, on_open_library=None, state=None, rollback=None, config=None, on_scan_artwork=None):
        super().__init__(parent, fg_color=BG)
        self.on_scan = on_scan
        self.on_undo = on_undo
        self.on_open_library = on_open_library
        self.state = state
        # The rollback service and the library path are asked for directly rather than read off the state
        # snapshot, which never carried them. They used to be pulled out of it with getattr(snap,'config') and
        # getattr(snap,'rollback_pending') - two names AppState has never had, so both silently read None and the
        # screen reported "nothing to undo" and an em dash for the library on every run, including a run with a
        # full journal waiting to be rolled back. That is the one fact on this screen a user comes to check.
        # The whole config is held rather than the one path, because a Path is an immutable snapshot: MainWindow
        # rebinds config.library_root when the Games directory changes and pushes the new value into the scan
        # screen, and a value taken here at construction could never follow it - this screen would name the
        # previous directory and report the previous volume's free space for the rest of the session.
        self.rollback = rollback
        self.config = config
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        CTkLabel(self, text="DONE", fg_color=PANEL, text_color=GREEN, font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0, sticky="w")
        CTkLabel(self, text="Run complete", fg_color=BG, text_color=TEXT, font=("TkDefaultFont", 24, "bold")).grid(row=1, column=0, sticky="nw")
        self.card = panel(self)
