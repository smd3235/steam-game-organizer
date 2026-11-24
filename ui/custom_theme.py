"""CustomTkinter theme layer for Steam Game Organizer.

This module provides CustomTkinter-based replacements for the Tkinter theming in ui/theme.py.
CustomTkinter widgets (CTkFrame, CTkLabel, CTkButton, CTkEntry, CTkComboBox, CTkScrollbar,
CTkTextbox, CTkCheckBox, CTkRadioButton, CTkProgressBar) replace their Tkinter/ttk counterparts
to give the app a modern dark-mode-first UI with rounded corners, hover effects, and smooth
scaling on high-DPI displays.

Migration strategy:
  1. Import custom_theme instead of theme in individual view files
  2. Replace tk.Frame -> CTkFrame, tk.Label -> CTkLabel, tk.Button -> CTkButton, etc.
  3. Remove ttk.Style configuration (CustomTkinter handles styling natively)
  4. Test one screen at a time

Usage:
    from ui.custom_theme import CTkFrame, CTkLabel, CTkButton, BG, PANEL, ACCENT_HI, ...
    from ui.custom_theme import Theme, panel, pill

The Theme class wraps CustomTkinter's appearance mode system and provides the same
color constants as ui/palette.py so existing code keeps working.
"""

from __future__ import annotations

import customtkinter as ctk
import tkinter as tk

# ── Re-export CustomTkinter classes so views import one module ──────────────────
CTk = ctk.CTk
CTkToplevel = ctk.CTkToplevel
CTkFrame = ctk.CTkFrame
CTkLabel = ctk.CTkLabel
CTkButton = ctk.CTkButton
CTkEntry = ctk.CTkEntry
CTkComboBox = ctk.CTkComboBox
CTkScrollbar = ctk.CTkScrollbar
CTkTextbox = ctk.CTkTextbox
CTkCheckBox = ctk.CTkCheckBox
CTkRadioButton = ctk.CTkRadioButton
CTkProgressBar = ctk.CTkProgressBar
CTkCanvas = ctk.CTkCanvas

# ── Colour palette (same names as ui/palette.py so existing code keeps working) ─
BG = "#0f1117"
PANEL = "#171b24"
PANEL2 = "#1e2430"
PANEL3 = "#252d3a"
TEXT = "#f4f7fb"
MUTED = "#9aa6b7"
BORDER = "#303949"

ACCENT = "#7353f5"
ACCENT_HOVER = "#785af7"
ACCENT_HI = "#9b82ff"
CYAN = "#39c6d8"
GREEN = "#48d597"
ORANGE = "#ffb454"
RED = "#ff667d"

PINK = "#f472b6"
SKY = "#38bdf8"

CHART_COLORS = (ACCENT, CYAN, GREEN, ORANGE, PINK, SKY)

PILL_KINDS = {"accent": (ACCENT, "white"), "good": (GREEN, "#071b12"), "warn": (ORANGE, "#211705"), "bad": (RED, "#260a10"), "info": (CYAN, "#061b20"), "muted": (PANEL3, MUTED)}

DANGER = "#48202b"
DANGER_HOVER = "#602b39"
DANGER_TEXT = "#ffb2bd"
ENTRY_BG = "#11151c"


class Theme:
    """CustomTkinter theme manager.

    Replaces core.tkinter ttk.Style configuration. Call Theme(root) once at app startup
    to set the appearance mode and colour theme. All widget classes above inherit their
    colours from this theme automatically.
    """

    _instance = None

    def __init__(self, root: ctk.CTk, mode: str = "dark"):
        self.root = root
        self.mode = mode

        # CustomTkinter handles colour theming natively
        ctk.set_appearance_mode(mode)
        ctk.set_default_color_theme("blue")  # base theme; we override colours per-widget

        # Store reference so widgets can access theme colours
        self.bg = BG
        self.panel = PANEL
        self.panel2 = PANEL2
        self.text = TEXT
        self.muted = MUTED
        self.border = BORDER
        self.accent = ACCENT
        self.accent_hi = ACCENT_HI
        self.green = GREEN
        self.orange = ORANGE
        self.red = RED

    @classmethod
    def get_instance(cls) -> Theme:
        return cls._instance

    @classmethod
    def set_instance(cls, instance: Theme) -> None:
        cls._instance = instance


def panel(parent, **kw):
    """CTkFrame replacement with panel styling."""
    return CTkFrame(parent, fg_color=PANEL, corner_radius=8, **kw)


def panel2(parent, **kw):
    """Secondary panel with slightly different shade."""
    return CTkFrame(parent, fg_color=PANEL2, corner_radius=8, **kw)


def pill(parent, text, kind="accent"):
    """Pill-shaped label matching the HTML catalog's data-tip callout."""
    bg, fg = PILL_KINDS.get(kind, PILL_KINDS["accent"])
    return CTkLabel(parent, text=text, fg_color=bg, text_color=fg, corner_radius=12,
                     font=("TkDefaultFont", 8, "bold"), padx=9, pady=4)


def wheel_step(event):
    """Turns a mouse-wheel event into a yview_scroll step."""
    delta = int(getattr(event, "delta", 0) or 0)
    if delta:
        return -max(1, abs(delta) // 120) * (1 if delta > 0 else -1)
    return -1 if getattr(event, "num", 0) == 4 else 1


def bind_wheel(widget, callback):
    for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        widget.bind(sequence, callback, add="+")


def pin_bottom(widget):
    """Keep a scrolling surface parked on its newest content while a run streams into it."""
    try:
        if isinstance(widget, tk.Text) or isinstance(widget, tk.Entry):
            widget.see("end")
        else:
            widget.yview_moveto(1.0)
    except tk.TclError:
        pass


def human_size(n: int) -> str:
    """Human-readable byte count."""
    if n is None:
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"


def human_duration(seconds: float) -> str:
    """Human-readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    seconds = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours}h {minutes}m"


def clock_stamp(when=None) -> str:
    """ISO timestamp for log lines."""
    import datetime
    if when is None:
        when = datetime.datetime.now()
    return when.strftime("%H:%M:%S")