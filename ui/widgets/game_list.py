import tkinter as tk
from tkinter import ttk
from .game_card import GameCard
from ui.theme import ACCENT_HI, BG, MUTED, pin_bottom


class GameList(tk.Frame):
    def __init__(self, parent, on_select):
        super().__init__(parent, bg=BG)
        self.on_select = on_select
        self.cards = []
        self.all_items = []
        self.visible_items = []
        self.selected_archives = set()
        self.auto_scroll = False
        hdr = tk.Frame(self, bg=BG)
        hdr.pack(fill="x", pady=(0, 7))
        tk.Label(hdr, text="GAME QUEUE TEST", bg=BG, fg=ACCENT_HI, font=("TkDefaultFont", 9, "bold")).pack(side="left")
        self.count = tk.Label(hdr, text="0", bg=BG, fg=MUTED, font=("TkDefaultFont", 8, "bold"))
        self.count.pack(side="right")
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        self.scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview, style="Dark.Vertical.TScrollbar")
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scroll.pack(side="right", fill="y")
        self.inner.bind("<Configure>", self._content_configure)
        self.canvas.bind("<Configure>", self._canvas_configure)
        self._bind_wheel_target(self)
        self._bind_wheel_target(self.inner)
        self._bind_wheel_target(self.canvas)

    def _content_configure(self, e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _canvas_configure(self, e):
        self.canvas.itemconfigure(self.win, width=max(1, e.width))

    def _wheel(self, e):
        if str(getattr(e.widget, "winfo_class", lambda: "")()) in ("TCombobox", "Listbox"):
            return None
        delta = int(getattr(e, "delta", 0))
        step = -max(1, abs(delta) // 120) * (1 if delta > 0 else -1) if delta else -1 if getattr(e, "num", 0) == 4 else 1
        self.canvas.yview_scroll(step, "units")
        return "break"

    def bind_scroll(self, w):
        if str(getattr(w, "winfo_class", lambda: "")()) in ("TCombobox", "Listbox", "Entry", "TEntry", "Text"):
            return
        self._bind_wheel_target(w)
        for child in w.winfo_children():
            self.bind_scroll(child)

    def _bind_wheel_target(self, w):
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            w.bind(sequence, self._wheel, add="+")

    def set_items(self, items):
        self.all_items = []
        seen = set()
        for archive in items:
            if archive.identity_key in seen:
                continue
            seen.add(archive.identity_key)
            self.all_items.append(archive)
        self.apply_filter(reset=True)

    def set_auto_scroll(self, enabled):
        self.auto_scroll = bool(enabled)

    def apply_filter(self, reset=False):
        q = getattr(self, "query_text", "").casefold()
        mode = getattr(self, "filter_mode", "All")
        items = [a for a in self.all_items if not q or q in a.display_name.casefold() or q in a.normalized_title.casefold() or q in a.path.name.casefold()]
        if mode == "Verified":
            items = [a for a in items if a.steam.found]
        elif mode == "Needs Review":
            items = [a for a in items if not a.steam.found and not a.decision.skipped]
        elif mode == "New Only":
            items = [a for a in items if not a.decision.accepted and not a.decision.skipped]
        elif mode == "Artwork":
            items = [a for a in items if a.artwork.present()]
        self.visible_items = items
        for c in self.cards:
            c.destroy()
        self.cards = []
        self.count.configure(text=f"{len(items)} / {len(self.all_items)}")
        for a in items:
            c = GameCard(self.inner, a, self.on_select, selected=(a in self.selected_archives))
            c.pack(fill="x", pady=(0, 7))
            self.cards.append(c)
            self.bind_scroll(c)
        self.inner.update_idletasks()
        self._content_configure()
        if reset:
            self.canvas.yview_moveto(0)

    def set_filter(self, text, mode=None):
        self.query_text = text
        self.filter_mode = mode or getattr(self, "filter_mode", "All")
        self.apply_filter(reset=True)

    def select_archive(self, a):
        if a in self.selected_archives:
            self.selected_archives.remove(a)
        else:
            self.selected_archives.add(a)
        for c in self.cards:
            c.select(c.archive in self.selected_archives)

    def refresh(self):
        # While a run is streaming into the queue, stay parked on the newest card instead of holding the
        # previous offset, which would otherwise leave the view stuck partway up as the list grows.
        if self.auto_scroll:
            self.apply_filter(reset=False)
            pin_bottom(self.canvas)
            return
        y = self.canvas.yview()[0] if self.canvas.winfo_exists() else 0
        self.apply_filter(reset=False)
        self.canvas.yview_moveto(min(y, 1.0))
