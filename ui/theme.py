"""The shared look of every screen: colors, fonts, CTk widgets, and the widgets built on them.
Theme holds the visual vocabulary in one place so every screen reads the same and a change to one
color propagates everywhere instead of hunting through fifteen views. It also re-exports the formatting
helpers (human_size, human_duration, clock_stamp) so views import one module instead of two.
The ActivityFeed, PhaseTimeline, Sparkline and pill widgets live here because several screens share them,
and placing them beside the styles that paint them keeps the color-and-widget pairing visible together.
"""

from __future__ import annotations

import customtkinter as ctk
import tkinter as tk

# Re-export CustomTkinter classes so views import one module
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

# Re-exported so views keep importing one module, while the single implementation lives outside the UI layer
# where the controller can use it too.
from utils.formatting import human_size, human_duration, clock_stamp
from .palette import (
    ACCENT, ACCENT_HI, ACCENT_HOVER, BG, BORDER, CHART_COLORS, CYAN, DANGER,
    DANGER_HOVER, DANGER_TEXT, ENTRY_BG, GREEN, MUTED, ORANGE, PANEL, PANEL2,
    PANEL3, PILL_KINDS, PINK, RED, SKY, TEXT)
# PhaseTimeline extracted to ui/phase_timeline.py — see that module for its definition.
# Imported after pill (below) to avoid a circular import: phase_timeline imports pill from theme.

__all__ = [
    "ACCENT",
    "ACCENT_HI",
    "ACCENT_HOVER",
    "ActivityFeed",
    "BG",
    "BORDER",
    "CHART_COLORS",
    "CYAN",
    "CTk",
    "CTkButton",
    "CTkCanvas",
    "CTkCheckBox",
    "CTkComboBox",
    "CTkEntry",
    "CTkFrame",
    "CTkLabel",
    "CTkProgressBar",
    "CTkRadioButton",
    "CTkScrollbar",
    "CTkToplevel",
    "CTkTextbox",
    "DANGER",
    "DANGER_HOVER",
    "DANGER_TEXT",
    "ENTRY_BG",
    "GREEN",
    "MUTED",
    "ORANGE",
    "PANEL",
    "PANEL2",
    "PANEL3",
    "PILL_KINDS",
    "PINK",
    "PhaseTimeline",
    "RED",
    "SKY",
    "Sparkline",
    "StatusBar",
    "TEXT",
    "Theme",
    "bind_wheel",
    "center_window",
    "clock_stamp",
    "human_duration",
    "human_size",
    "panel",
    "panel2",
    "pill",
    "pin_bottom",
    "radio",
    "radio",
    "reveal_staggered",
    "scroll_text",
    "tooltip",
    "wheel_step",
]


class Theme:
    """CustomTkinter theme manager.

    Replaces tkinter ttk.Style configuration. Call Theme(root) once at app startup
    to set the appearance mode and colour theme. All widget classes in ui/custom_theme.py
    inherit their colours from this theme automatically.
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


def radio(parent, text, value, variable, command=None, padx=8):
    """Radio button widget with consistent styling."""
    return CTkRadioButton(parent, text=text, value=value, variable=variable, fg_color=PANEL,
        text_color=TEXT, hover_color=ACCENT_HOVER, border_color=BORDER,
        font=("TkDefaultFont", 8, "bold"), padx=padx, pady=5, command=command)


def pill(parent, text, kind="accent"):
    """Pill-shaped label matching the HTML catalog's data-tip callout."""
    bg, fg = PILL_KINDS.get(kind, PILL_KINDS["accent"])
    return CTkLabel(parent, text=text, fg_color=bg, text_color=fg, corner_radius=12,
                    font=("TkDefaultFont", 8, "bold"), padx=9, pady=4)


def wheel_step(event):
    """Turns a mouse-wheel event into a yview_scroll step, handling both X11 delta and Button-4/5."""
    delta = int(getattr(event, "delta", 0) or 0)
    if delta:
        return -max(1, abs(delta) // 120) * (1 if delta > 0 else -1)
    return -1 if getattr(event, "num", 0) == 4 else 1


def scroll_text(widget, event):
    widget.yview_scroll(wheel_step(event), "units")
    return "break"


def bind_wheel(widget, callback):
    for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        widget.bind(sequence, callback, add="+")


def pin_bottom(widget):
    """Keep a scrolling surface parked on its newest content while a run streams into it.
    Accepts either a Canvas or a Text widget, and stays silent if the widget is already destroyed
    or not yet laid out."""
    try:
        if isinstance(widget, tk.Text) or isinstance(widget, tk.Entry):
            widget.see("end")
        else:
            widget.yview_moveto(1.0)
    except tk.TclError:
        pass


from ui.phase_timeline import PhaseTimeline


class Sparkline(ctk.CTkCanvas):
    """A rolling throughput trace. A single number like '214 MB/s' is easy to read but easy to miss; the shape
    of the last minute shows whether the run is speeding up, stalling on a slow archive, or about to finish.
    Drawn on a Canvas rather than a widget image so it costs nothing to repaint once per tick.
    """

    def __init__(self, parent, bg=PANEL2, height=34, fg=CYAN, fill=None, points=60, **kw):
        super().__init__(parent, fg_color=bg, height=height, highlightthickness=0, border_width=0, **kw)
        self.values = []
        self.max_points = points
        self.fg = fg
        self.fill = fill or fg

    def push(self, value):
        if value is None:
            return
        self.values.append(float(value))
        if len(self.values) > self.max_points:
            self.values = self.values[-self.max_points:]
        self.redraw()

    def clear(self):
        self.values = []
        self.redraw()

    def redraw(self):
        self.delete("all")
        w = max(1, self.winfo_width())
        h = max(1, self.winfo_height())
        # A flat line in the middle reads as "no data yet" rather than as a genuine zero, which would be a lie:
        # a run that has produced nothing yet is not the same as a run moving at zero bytes per second.
        if len(self.values) < 2:
            self.create_line(0, h // 2, w, h // 2, fill=BORDER, dash=(3, 4))
            return
        peak = max(self.values) or 1.0
        span = len(self.values) - 1
        points = []
        for index, value in enumerate(self.values):
            x = index / span * w
            y = h - 2 - (value / peak) * (h - 4)
            points.extend((x, y))
        if self.fill:
            self.create_polygon(0, h, *points, w, h, fill=self.fill, stipple="gray25", outline="")
        self.create_line(*points, fill=self.fg, width=2, smooth=True)
        self.create_text(4, 4, anchor="nw", text=f"peak {human_size(peak)}/s", fill=MUTED, font=("TkDefaultFont", 7))


class ActivityFeed:
    """An append-only live event feed shared by the Scan and Organize screens.
    Every line is timestamped and colour-coded by kind, the newest line stays in view while a run streams
    into it, and the buffer is capped so a long scan cannot grow without bound. One implementation means the
    two screens cannot drift apart in how they present progress.
    """

    KINDS = ("info", "good", "warn", "bad", "muted", "head")

    def __init__(self, widget, limit=500, follow=True, stamp=True):
        self.widget = widget
        self.limit = limit
        self.follow = follow
        self.stamp = stamp
        for kind in self.KINDS:
            widget.tag_configure(kind, foreground=self._color(kind))

    def _color(self, kind):
        return {"info": TEXT, "good": GREEN, "warn": ORANGE, "bad": RED, "muted": MUTED, "head": ACCENT_HI}.get(kind, TEXT)

    def clear(self):
        self.widget.configure(state="normal")
        self.widget.delete("1.0", "end")
        self.widget.configure(state="disabled")

    def write(self, message, kind="info", when=None):
        """Appends one line. Safe to call from a progress callback that fires rapidly."""
        try:
            self.widget.configure(state="normal")
            if self.stamp:
                self.widget.insert("end", f"{clock_stamp(when)}  ", kind)
                self.widget.insert("end", f"{message}\n", kind)
            else:
                self.widget.insert("end", f"{message}\n", kind)
            lines = int(self.widget.index("end-1c").split(".")[0])
            if lines > self.limit:
                self.widget.delete("1.0", f"{lines - self.limit}.0")
            if self.follow:
                pin_bottom(self.widget)
            self.widget.configure(state="disabled")
        except tk.TclError:
            pass

    def update(self, key, message, kind="info", when=None):
        """Replaces the most recent line in place when it carries the same key, instead of appending.
        A conversion stage reports roughly once a second for minutes at a time, and appending each of those
        produced a feed of near-identical lines that buried the actual stage changes. Redrawing the live line
        keeps the running detail readable while still preserving every real transition underneath it.
        """
        if key == getattr(self, "_last_key", None) and int(self.widget.index("end-1c").split(".")[0]) > 1:
            try:
                last = int(self.widget.index("end-1c").split(".")[0])
                self.widget.configure(state="normal")
                self.widget.delete(f"{last - 1}.0", "end-1c")
                self.widget.configure(state="disabled")
            except tk.TclError:
                pass
        self._last_key = key
        self.write(message, kind, when)

    def break_run(self):
        """Forgets the live-line key so the next update starts a new line rather than overwriting the last."""
        self._last_key = None


def reveal_staggered(widgets, root, stagger=80, interval=16):
    """Sequentially reveal a list of widgets with a fade-in, matching the HTML catalog's
    IntersectionObserver .in-view animation.
    Each widget's border thickness animates from 0 to 1 over 20 steps. 'stagger' is the delay between
    each widget's start.
    """
    states = []
    for w in widgets:
        try:
            orig = int(w.cget("border_width") or 0)
        except tk.TclError:
            orig = 0
        states.append({"w": w, "step": 0, "orig": orig})

    def _tick(idx):
        s = states[idx]
        w = s["w"]
        if s["step"] <= 20:
            alpha = min(1.0, s["step"] / 20.0)
            try:
                w.configure(border_width=int(s["orig"] * alpha))
            except tk.TclError:
                pass
        if s["step"] < 20:
            s["step"] += 1
            root.after(interval, lambda: _tick(idx))
        else:
            try:
                w.configure(border_width=s["orig"])
            except tk.TclError:
                pass

    for idx in range(len(widgets)):
        root.after(idx * stagger, lambda i=idx: _tick(i))


class Tooltip:
    """Hover tooltip matching the HTML catalog's data-tip callout.
    Shows a small styled label below the widget on mouse-enter, removes it on
    mouse-leave. Used on buttons and icons where a short hint clarifies intent
    without consuming space in the layout.
    The Toplevel is created lazily on first show to avoid polluting the widget
    tree of tests that instantiate the full MainWindow."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<Button-1>", self._hide, add="+")

    def _create_tip(self):
        if self.tip is not None:
            return
        try:
            self.tip = ctk.CTkToplevel(bg=ACCENT_HI)
            self.tip.withdraw()
            self.tip.overrideredirect(True)
            self.tip.configure(fg_color=ACCENT_HI)
            label = ctk.CTkLabel(self.tip, text=self.text, fg_color=ACCENT_HI, text_color="white",
                                 font=("TkDefaultFont", 8, "bold"), padx=8, pady=4)
            label.pack()
        except tk.TclError:
            self.tip = None

    def _hide(self, _event=None):
        if self.tip is not None:
            try:
                self.tip.withdraw()
            except tk.TclError:
                self.tip = None

    def _show(self, _event=None):
        try:
            self._create_tip()
            x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
            y = self.widget.winfo_rooty() - 20
            self.tip.geometry(f"+{x}+{y}")
            self.tip.deiconify()
        except tk.TclError:
            pass


class StatusBar(ctk.CTkFrame):
    """A simple status bar at bottom of windows."""

    def __init__(self, parent, fg_color=BG, **kw):
        super().__init__(parent, fg_color=fg_color, border_width=1, border_color=BORDER, **kw)
        self.label = CTkLabel(self, text="", fg_color=fg_color, text_color=MUTED, anchor="w", padx=10)
        self.label.pack(fill="x")

    def set(self, text):
        self.label.configure(text=text)


def center_window(window, width=None, height=None):
    """Center a window on screen."""
    window.update_idletasks()
    if width is None:
        width = window.winfo_width()
    if height is None:
        height = window.winfo_height()
    x = (window.winfo_screenwidth() // 2) - (width // 2)
    y = (window.winfo_screenheight() // 2) - (height // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")
    return window


def tooltip(widget, text):
    """Attach a hover tooltip to a widget."""
    return Tooltip(widget, text)