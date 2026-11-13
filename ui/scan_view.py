"""The scan screen: phases, progress bar, activity feed, and the Convert Archives toggle.

ScanView shows the live timeline of cleanup, dedupe, repair, discover, audit and catalog; draws a
progress bar split into extract/compress/verify slices keyed off SCAN_STAGE_SPAN; and renders the
activity feed as work completes. It owns the on-scan, on-choose, on-cancel and on-scan-artwork
callbacks that MainWindow wires up, plus the Convert Archives checkbox whose saved state feeds the
organize pass.
"""

import tkinter as tk
from tkinter import ttk
from urllib.request import Request, urlopen
import os
import shutil
from pathlib import Path
from .theme import ACCENT_HI, ActivityFeed, BG, BORDER, CYAN, GREEN, MUTED, ORANGE, PANEL, PANEL2, PhaseTimeline, RED, TEXT, bind_wheel, human_size, panel, radio, scroll_text
from core.constants import USER_AGENT
from core.scan_view_utils import ago, space_delta, size

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


class ScanView(tk.Frame):
    def __init__(self, parent, on_scan, on_choose=None, on_cancel=None, on_scan_artwork=None, scan_summary=None):
        super().__init__(parent, bg=BG)
        self.on_scan = on_scan
        self.on_choose = on_choose
        self.on_cancel = on_cancel
        self.on_scan_artwork = on_scan_artwork
        self.scanning = False
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
        tk.Label(self, text="COMMAND CENTER", bg=BG, fg=ACCENT_HI, font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(self, text="Game Archive Scanner", bg=BG, fg=TEXT, font=("TkDefaultFont", 24, "bold")).grid(row=1, column=0, sticky="nw", pady=(2, 0))
        body = tk.Frame(self, bg=BG)
        body.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        body.columnconfigure(0, weight=1, minsize=550)
        body.columnconfigure(1, weight=0, minsize=350)
        body.rowconfigure(0, minsize=90)
        body.rowconfigure(1, weight=1, minsize=220)
        cfg = panel(body)
        cfg.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        cfg.configure(height=90)
        cfg.grid_propagate(False)
        cfg.columnconfigure(1, weight=1)  # The path gets its own full-width row. Sharing one row with the mode radios and three checkboxes left
        # it 100px on a narrow window, so the Games directory the app was about to read was unreadable.
        tk.Label(cfg, text="GAMES DIRECTORY", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8, "bold")).grid(row=0, column=0, padx=(10, 4), pady=(6, 1), sticky="w")
        self.library = tk.Label(cfg, text="", bg=PANEL, fg=TEXT, font=("TkDefaultFont", 9), anchor="w")
        self.library.grid(row=0, column=1, sticky="ew", pady=(6, 1))
        ttk.Button(cfg, text="Browse / Change", style="Secondary.TButton", command=on_choose).grid(row=0, column=2, padx=8)
        # The strip ran the full window width but only ever used its left half. Three at-a-glance counts describe
        # the library the next scan will read: how many game folders exist, how many archives already sit in
        # them, and whether there is room for the run. All three answer questions users asked of the scanner.
        stats = tk.Frame(cfg, bg=PANEL)
        stats.grid(row=0, column=3, columnspan=3, sticky="e", padx=(10, 14))
        self.lib_stats = {}
        for key, title in (("folders", "FOLDERS"), ("archives", "ARCHIVES"), ("free", "FREE")):
            cell = tk.Frame(stats, bg=PANEL)
            cell.pack(side="left", padx=(0, 12))
            tk.Label(cell, text=title, bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8)).pack(side="left")
            value = tk.Label(cell, text="—", bg=PANEL, fg=TEXT, font=("TkDefaultFont", 8, "bold"))
            value.pack(side="left", padx=(5, 0))
            self.lib_stats[key] = value
        mode = tk.Frame(cfg, bg=PANEL)
        mode.grid(row=1, column=0, columnspan=2, sticky="w", padx=14, pady=(0, 4))
        self.mode_var = tk.StringVar(value="All")
        self._radio(mode, "ALL ARCHIVES", "All").pack(side="left")
        self._radio(mode, "NEW ONLY", "New Only").pack(side="left")
        self.preview_var = tk.BooleanVar(value=False)
        self.art_var = tk.BooleanVar(value=True)
        self.convert_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(cfg, text="Preview Only", variable=self.preview_var).grid(row=1, column=2, padx=3)
        # Conversion is the expensive part of a scan and needs three times the archive size in free disk while
        # it works, so it is a control of its own rather than something buried in a settings dialog. On by
        # default, which is what every existing user already had. Conversion unlocks password-protected ZIPs
        # ('123') as part of the same pass, so there is no separate toggle for it.
        ttk.Checkbutton(cfg, text="Convert ZIP/RAR to 7z", variable=self.convert_var).grid(row=1, column=3, padx=3)
        ttk.Checkbutton(cfg, text="Download Artwork", variable=self.art_var).grid(row=1, column=5, padx=3)
        # The strip left the rest of its second row blank. What pressing Scan will actually do, spelled out
        # from the toggles above it, is the thing worth confirming beforehand - especially now that
        # conversion is a control rather than fixed behaviour the user has to remember.
        self.plan_label = tk.Label(cfg, text="", bg=PANEL, fg=CYAN, font=("TkDefaultFont", 8), anchor="w")
        self.plan_label.grid(row=2, column=0, columnspan=6, sticky="w", padx=14, pady=(0, 4))
        # The quick-scan button is a secondary action that needs a line of context so users reach for the right
        # tool: SCAN LIBRARY rechecks everything, NEW + ARTWORK only finds new games and fetches their art.
        self.artwork_hint = tk.Label(cfg,
            text='Or press "NEW + ARTWORK" to find new games, download their artwork, clean up '
                 'leftovers, collapse duplicates, convert ZIP/RAR to 7z, and rebuild the catalog.',
            bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8), anchor="w", wraplength=420,
            justify="left")
        self.artwork_hint.grid(row=3, column=0, columnspan=6, sticky="w", padx=14, pady=(0, 6))
        for var in (self.mode_var, self.preview_var, self.art_var, self.convert_var):
            var.trace_add("write", lambda *a: self._refresh_plan())
        # Keep config.convert_archives in sync with the checkbox immediately, so organize
        # (which may run without a preceding scan) sees the current setting rather than the
        # stale value loaded from settings.json at startup.
        self.convert_var.trace_add("write", lambda *a: self.sync_convert_setting())
        rail = tk.Frame(body, bg=BG)
        rail.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        rail.columnconfigure(0, weight=1)
        # The API panel needs ~236px once its padding is counted, so a 196px slot silently clipped its last
        # explanation line. The panel below it scrolls now, so it can shrink instead of being crushed.
        rail.rowconfigure(0, minsize=180)
        rail.rowconfigure(1, weight=1, minsize=90)
        self.api = panel(rail)
        self.api.grid(row=0, column=0, sticky="nsew")
        self.api.grid_propagate(False)
        self.api.columnconfigure(1, weight=1)
        tk.Label(self.api, text="STEAMGRIDDB API  (optional)", bg=PANEL, fg=ACCENT_HI, font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(8, 4))
        self.api_var = tk.StringVar()
        self.api_entry = tk.Entry(self.api, textvariable=self.api_var, show="•", bg=PANEL2, fg=TEXT, disabledforeground=MUTED, insertbackground=TEXT, relief="flat", highlightbackground=BORDER, highlightthickness=1)
        self.api_entry.grid(row=1, column=0, columnspan=3, sticky="ew", padx=14, pady=(0, 4))
        btns = tk.Frame(self.api, bg=PANEL)
        btns.grid(row=2, column=0, columnspan=3, sticky="ew", padx=14, pady=(0, 6))
        ttk.Button(btns, text="Save API", style="Secondary.TButton", command=self.save_api).pack(side="left")
        ttk.Button(btns, text="Test API", style="Secondary.TButton", command=self.test_api).pack(side="left", padx=(6, 0))
        self.api_status = tk.Label(self.api, text="Not configured", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8))
        self.api_status.grid(row=3, column=0, columnspan=3, sticky="w", padx=14, pady=(0, 6))
        # The panel was three widgets tall inside a fixed-height frame, so over half of it was blank. Artwork
        # coverage answers the question the key raises: what did the key actually buy me on this library?
        tk.Frame(self.api, bg=BORDER, height=1).grid(row=4, column=0, columnspan=3, sticky="ew", padx=14, pady=(0, 6))
        tk.Label(self.api, text="ARTWORK COVERAGE", bg=PANEL, fg=CYAN, font=("TkDefaultFont", 8, "bold")).grid(row=5, column=0, columnspan=3, sticky="w", padx=14, pady=(0, 2))
        self.art_label = tk.Label(self.api, text="No artwork downloaded yet", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8), wraplength=352, justify="left", anchor="w")
        self.art_label.grid(row=6, column=0, columnspan=3, sticky="ew", padx=14, pady=(0, 2))
        tk.Label(self.api, text="A free key from steamgriddb.com adds grid, hero and icon art to game cards.",
            bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8), wraplength=352, justify="left",
            anchor="w").grid(row=7, column=0, columnspan=3, sticky="ew", padx=14, pady=(0, 6))
        self._art_ok = set()
        # The rail cannot grow to fit this panel. With the conversion rows and the stage grid added it needed
        # 519px in a 271px slot, so everything below the first few counts was silently clipped to zero height
        # and never drawn. It scrolls instead, which also keeps it usable at the minimum window size.
        self.dash = panel(rail)
        self.dash.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        tk.Label(self.dash, text="LIVE SCAN DATA", bg=PANEL, fg=CYAN, font=("TkDefaultFont", 9, "bold")).pack(anchor="w", padx=14, pady=(8, 2))
        dash_canvas = tk.Canvas(self.dash, bg=PANEL, highlightthickness=0, bd=0)
        dash_scroll = ttk.Scrollbar(self.dash, orient="vertical", command=dash_canvas.yview)
        dash_canvas.configure(yscrollcommand=dash_scroll.set)
        dash_canvas.pack(side="left", fill="both", expand=True)
        dash_scroll.pack(side="right", fill="y")
        self.dash_body = tk.Frame(dash_canvas, bg=PANEL)
        dash_window = dash_canvas.create_window((0, 0), window=self.dash_body, anchor="nw")
        self.dash_body.bind("<Configure>", lambda e: dash_canvas.configure(scrollregion=dash_canvas.bbox("all")))
        dash_canvas.bind("<Configure>", lambda e: dash_canvas.itemconfigure(dash_window, width=e.width))
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            dash_canvas.bind(sequence, lambda e: self._dash_wheel(e, dash_canvas), add="+")
        self._dash_canvas = dash_canvas

        # Live stats - essential information at a glance
        stats_frame = tk.Frame(self.dash_body, bg=PANEL)
        stats_frame.pack(fill="x", padx=14, pady=(0, 6))
        self._stat(stats_frame, "Archives Discovered", "archives")
        self._stat(stats_frame, "Total Size", "size")
        self._stat(stats_frame, "Supported", "supported")
        self._stat(stats_frame, "Scanned", "scanned")
        self._stat(stats_frame, "Elapsed", "elapsed")

        # Separator
        tk.Frame(self.dash_body, bg=BORDER, height=1).pack(fill="x", padx=14, pady=(8, 4))

        # Active work - current operation details
        tk.Label(self.dash_body, text="ACTIVE WORK", bg=PANEL, fg=ACCENT_HI, font=("TkDefaultFont", 8, "bold")).pack(anchor="w", padx=14)
        self.current = tk.Label(self.dash_body, text="Ready to scan.", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8), wraplength=330, justify="left", height=4, anchor="nw")
        self.current.pack(fill="x", padx=14, pady=(4, 6))
        self.progress = ttk.Progressbar(self.dash_body, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=14, pady=(0, 4))
        self.stage_row = tk.Label(self.dash_body, text="phase: idle", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8), anchor="w")
        self.stage_row.pack(fill="x", padx=14, pady=(0, 6))

        # Work details - file and conversion progress
        work_details = tk.Frame(self.dash_body, bg=PANEL)
        work_details.pack(fill="x", padx=14, pady=(0, 6))
        tk.Label(work_details, text="Current File:", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8)).pack(side="left")
        self._stat(work_details, "", "repair_size")
        tk.Label(work_details, text="Extracted:", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8)).pack(side="left", padx=(10, 0))
        self._stat(work_details, "", "repair_extracted")
        tk.Label(work_details, text="Stage:", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8)).pack(side="left", padx=(10, 0))
        self._stat(work_details, "", "repair_percent")

        # Conversion results
        conversion_results = tk.Frame(self.dash_body, bg=PANEL)
        conversion_results.pack(fill="x", padx=14, pady=(0, 6))
        tk.Label(conversion_results, text="Converted:", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8)).pack(side="left")
        self._stat(conversion_results, "", "repair_count")
        tk.Label(conversion_results, text="7z Level:", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8)).pack(side="left", padx=(10, 0))
        self._stat(conversion_results, "", "repair_level")

        # Disk impact - most important for assessing value
        disk_impact = tk.Frame(self.dash_body, bg=PANEL)
        disk_impact.pack(fill="x", padx=14, pady=(0, 6))
        tk.Label(disk_impact, text="Space Impact:", bg=PANEL, fg=ACCENT_HI, font=("TkDefaultFont", 8, "bold")).pack(side="left")
        self._stat(disk_impact, "", "repair_saved")
        tk.Label(disk_impact, text="Archives Grown:", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8)).pack(side="left", padx=(10, 0))
        self._stat(disk_impact, "", "repair_grown")

        # Separator
        tk.Frame(self.dash_body, bg=BORDER, height=1).pack(fill="x", padx=14, pady=(8, 4))

        # Conversion history
        tk.Label(self.dash_body, text="CONVERSIONS THIS RUN", bg=PANEL, fg=ACCENT_HI, font=("TkDefaultFont", 8, "bold")).pack(anchor="w", padx=14)
        self.conversions = tk.Frame(self.dash_body, bg=PANEL)
        self.conversions.pack(fill="x", padx=14, pady=(4, 4))
        self.conversion_rows = []
        self.repair_note = tk.Label(self.dash_body, text="", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8), wraplength=330, justify="left", anchor="w")
        self.repair_note.pack(fill="x", padx=14, pady=(2, 10))
        self._bind_dash_wheel()
        activity = panel(body)
        activity.grid(row=1, column=0, sticky="nsew")
        activity.grid_propagate(False)
        activity.columnconfigure(0, weight=1)
        activity.rowconfigure(3, weight=1)
        self._activity_panel = activity
        tk.Label(activity, text="SCAN ACTIVITY", bg=PANEL, fg=ACCENT_HI, font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0, sticky="w", padx=14, pady=(10, 5))

        # The pipeline timeline shows all six scan phases at once, so a long phase is never mistaken for a hang
        # and a finished phase stays visible instead of being overwritten by the next status line.
        self.timeline = PhaseTimeline(activity, SCAN_PHASES, bg=PANEL)
        self.timeline.grid(row=2, column=0, sticky="w", padx=14, pady=(0, 4))
        self.last_scan = self._build_last_scan(activity)
        if self.last_scan is not None:
            self.last_scan.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 6))
        self.activity = tk.Text(activity, bg=PANEL, fg=TEXT, relief="flat", bd=0, wrap="none", height=8)
        self.activity.grid(row=3, column=0, sticky="nsew", padx=14, pady=(0, 6))
        self.activity.configure(state="disabled")
        bind_wheel(self.activity, lambda e: scroll_text(self.activity, e))
        self.feed = ActivityFeed(self.activity, limit=400)
        buttons = tk.Frame(activity, bg=PANEL)
        buttons.grid(row=4, column=0, sticky="ew", padx=14, pady=(0, 6))
        self.scan_btn = ttk.Button(buttons, text="SCAN LIBRARY  ›", style="Primary.TButton", command=on_scan)
        self.scan_btn.pack(side="left")
        self.artwork_scan_btn = ttk.Button(buttons, text="NEW + ARTWORK  ›", style="Secondary.TButton", command=on_scan_artwork) if on_scan_artwork else None
        (self.artwork_scan_btn.pack(side="left", padx=6) if self.artwork_scan_btn else None)
        self.cancel_btn = ttk.Button(buttons, text="CANCEL / STOP", style="Danger.TButton", command=on_cancel)
        self.cancel_btn.pack(side="left", padx=6)
        self.cancel_btn.configure(state="disabled")
        self._refresh_plan()

    # Pure functions now live in core.scan_view_utils; these thin wrappers keep existing callers working.
    def _ago(self, stamp):
        return ago(stamp)

    def _space_delta(self, event):
        return space_delta(event)

    def _size(self, n):
        return size(n)

    def sync_convert_setting(self):
        """Keep config.convert_archives in step with the checkbox the moment it is toggled.

        The controller is attached by MainWindow after construction, and the initial set() that shows the
        saved value happens before that, so there is nothing to write to yet and nothing to write - the value
        being shown came from the config in the first place.
        """
        if self.controller is None:
            return
        self.controller.config.convert_archives = bool(self.convert_var.get())

    def _build_last_scan(self, parent):
        """A standing report of the last scan, for the panel's idle state.

        Returns None when there is no summary - on a first run there is nothing to report, and an empty box
        labelled LAST SCAN would be worse than the blank panel it replaced.
        """
        summary = self.scan_summary
        if not summary or not summary.get("recorded_at"):
            return None
        box = tk.Frame(parent, bg=PANEL2, highlightbackground=BORDER, highlightthickness=1)
        head = tk.Frame(box, bg=PANEL2)
        head.pack(fill="x", padx=12, pady=(9, 0))
        tk.Label(head, text="LAST SCAN", bg=PANEL2, fg=CYAN, font=("TkDefaultFont", 8, "bold")).pack(side="left")
        tk.Label(head, text=self._ago(summary["recorded_at"]), bg=PANEL2, fg=MUTED, font=("TkDefaultFont", 8)).pack(side="right")
        # Two columns of label/value pairs. Six numbers in one wide row would be a strip of unreadable figures;
        # in a grid each one is a cell with its label attached, which is what makes it readable at a glance.
        grid = tk.Frame(box, bg=PANEL2)
        grid.pack(fill="x", padx=12, pady=(7, 0))
        for index in range(0, 3):
            grid.columnconfigure(index * 2, weight=0)
            grid.columnconfigure(index * 2 + 1, weight=1, uniform="cell")
        cells = (
            ("Archives", human_size(summary.get("total_bytes", 0)) + " on disk" if summary.get("archives") else "0", f"{summary.get('archives', 0)} game folders"),
            ("Steam matched", f"{summary.get('matched', 0)} of {summary.get('archives', 0)}", f"{summary.get('unmatched', 0)} with no match"),
            ("Artwork ready", str(summary.get("artwork", 0)), "downloaded to the game folder"),
            ("Scan errors", str(summary.get("errors", 0)), "reported on the Done screen"),
            ("Stale folders", str(summary.get("stale_dirs", 0)), f"{human_size(summary.get('stale_bytes', 0))} reclaimable" if summary.get("stale_dirs") else "none left over"),
            ("Library", Path(summary.get("library_root", "")).name or "—", "the folder this scan read"),
        )
        for row, (label, value, detail) in enumerate(cells):
            tk.Label(grid, text=label, bg=PANEL2, fg=MUTED, font=("TkDefaultFont", 8), anchor="w").grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
            cell = tk.Frame(grid, bg=PANEL2)
            cell.grid(row=row, column=1, sticky="ew", pady=2)
            tk.Label(cell, text=value, bg=PANEL2, fg=TEXT, font=("TkDefaultFont", 8, "bold"), anchor="w").pack(side="left")
            tk.Label(cell, text=detail, bg=PANEL2, fg=MUTED, font=("TkDefaultFont", 7), anchor="w").pack(side="left", padx=(6, 0))
        tk.Label(box, text="Scan Library to refresh these numbers.", bg=PANEL2, fg=MUTED, font=("TkDefaultFont", 7)).pack(anchor="w", padx=12, pady=(8, 10))
        return box

    def _dash_wheel(self, event, canvas):
        """Scrolls the live data panel. The rail has a fixed share of the window height, so at the minimum
        window size the conversion rows below the fold are only reachable with the wheel."""
        first, last = canvas.yview()
        if (getattr(event, "delta", 0) > 0 or getattr(event, "num", 0) == 4) and first <= 0:
            return "break"
        if (getattr(event, "delta", 0) < 0 or getattr(event, "num", 0) == 5) and last >= 1.0:
            return "break"
        scroll_text(canvas, event)
        return "break"

    def _bind_dash_wheel(self, widget=None):
        """Puts the wheel handler on the live data panel's contents, not only on its canvas.

        The panel's rows are a frame placed on the canvas as a window item, so a wheel event over a label goes
        to that label and Tk propagates to ancestors - which never include the canvas. Binding the canvas alone
        therefore left the panel scrollable only over bare canvas and the scrollbar, which is what made it look
        frozen. Bindings are replaced rather than added, so re-walking after new rows appear is idempotent.
        """
        widget = self.dash_body if widget is None else widget
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(sequence, lambda e: self._dash_wheel(e, self._dash_canvas))
        for child in widget.winfo_children():
            self._bind_dash_wheel(child)

    def _radio(self, parent, text, value):
        return radio(parent, text, value, self.mode_var, padx=8)

    def _live_detail(self, event):
        """Formats what is known about an archive while it is still being worked on.

        The finished "what it became" line cannot run during a conversion, because the target size does not
        exist until the archive is done - and that is fifteen minutes at level 9. The other half is known the
        whole time: the source size from the moment extraction starts, and the extracted total once
        compression begins. This is that half, so the file being converted is never just a filename.

        Returns '' when the event carries none of it, so a stage that has reported nothing yet is left alone
        rather than padded with a placeholder that reads like a real measurement.
        """
        bits = []
        source = int(event.get("source_bytes") or 0)
        extracted = int(event.get("extracted_bytes") or 0)
        if source:
            bits.append(human_size(source))
        if extracted:
            bits.append(f"{human_size(extracted)} extracted")
        return "   •   ".join(bits)

    def _add_conversion_row(self, name, event):
        """Keeps the most recent conversions listed with both sizes, newest first.

        Bounded, because an overnight run is hundreds of archives and this panel scrolls inside a fixed rail.
        """
        source = int(event.get("source_bytes") or 0)
        target = int(event.get("target_bytes") or 0)
        src_fmt = str(event.get("source_format") or "").upper()
        row = tk.Frame(self.conversions, bg=PANEL)
        delta = target - source
        good = delta <= 0
        # Show format conversion prominently
        fmt_text = f"({src_fmt} → 7Z)" if src_fmt else ""
        tk.Label(row, text=f"{name[:30]} {fmt_text}", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8), anchor="w").pack(side="left", fill="x", expand=True)
        tk.Label(row, text=f"{human_size(source)} → {human_size(target)}", bg=PANEL, fg=TEXT, font=("TkDefaultFont", 8), anchor="e").pack(side="right")
        tk.Label(row, text=f"  {human_size(abs(delta))}", bg=PANEL, fg=GREEN if good else ORANGE, font=("TkDefaultFont", 8, "bold"), anchor="e").pack(side="right")
        row.pack(fill="x", pady=1)
        self.conversion_rows.append(row)
        while len(self.conversion_rows) > 8:
            oldest = self.conversion_rows.pop(0)
            try:
                oldest.destroy()
            except tk.TclError:
                pass
        # New rows have to inherit the wheel binding, or the list is scrollable only over bare canvas again.
        self._bind_dash_wheel()

    def _stat(self, parent, label, key):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", padx=14, pady=3)
        tk.Label(row, text=label, bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8)).pack(side="left")
        lab = tk.Label(row, text="0", bg=PANEL, fg=TEXT, font=("TkDefaultFont", 9, "bold"))
        lab.pack(side="right")
        setattr(self, key + "_label", lab)

    def _append_activity(self, text, kind="muted"):
        # Thin wrapper kept so the remaining callers read the same; the feed owns the buffer cap and pinning.
        self.feed.write(text.rstrip("\n"), kind)

    def set_library(self, path):
        self.library_root = path
        self.library.configure(text=str(path))
        self.refresh_library_summary()
        self._refresh_plan()

    def refresh_library_summary(self):
        """Top-level only, so a library of any size still answers instantly.

        A recursive walk would be the wrong tool here: the strip must repaint the moment a scan starts.
        """
        from utils.formatting import human_size

        root = getattr(self, "library_root", None) or Path(str(self.library.cget("text")) if str(self.library.cget("text")).strip() else ".")
        folders = archives = -1
        free = None
        try:
            if Path(root).is_dir():
                with os.scandir(root) as entries:
                    for entry in entries:
                        if entry.is_dir():
                            folders += 1
                        elif Path(entry.name).suffix.lower() in (".7z", ".zip", ".rar"):
                            archives += 1
                free = shutil.disk_usage(str(root)).free
        except OSError:
            pass
        for key, value in (("folders", str(folders) if folders >= 0 else "—"), ("archives", str(archives) if archives >= 0 else "—"), ("free", human_size(free) if free else "—")):
            self.lib_stats[key].configure(text=value)

    def _refresh_plan(self):
        """Spells out what pressing Scan will do, from the current toggles. Nothing on the strip said what
        any of the options would actually do, so the only way to know was to press the button and watch."""
        if not hasattr(self, "plan_label"):
            return
        scope = "New Only (organized folders are skipped)" if self.mode_var.get() == "New Only" else "All archives"
        parts = [scope]
        if self.preview_var.get():
            parts.append("PREVIEW ONLY — no files will be moved or converted")
        else:
            if self.convert_var.get():
                parts.append("ZIP/RAR rebuilt as 7z (password 123 zips unlocked first)")
            else:
                parts.append("ZIP/RAR left in place (conversion off)")
            parts.append("artwork refreshed" if self.art_var.get() else "no artwork")
        self.plan_label.configure(text="Next scan:  " + "   •   ".join(parts), fg=ORANGE if self.preview_var.get() else CYAN)

    def begin_scan(self, quick=False):
        # The last scan's report describes a run that has now been superseded, and the panel it sits in is about
        # to fill with this one's telemetry. Hidden rather than left to be contradicted by a live counter beside
        # it - "171 of 176 matched" from two hours ago reads as current.
        if self.last_scan is not None and self.last_scan.winfo_manager():
            self.last_scan.grid_remove()
        # last_scan (row 2) carried the only row weight, so once it was hidden at scan start the panel above the
        # feed grew blank and the 8-line activity log stayed pinned at the bottom. Give the weight to the feed row
        # instead, so it expands to fill the panel while a scan runs and the live log stops being squeezed into its
        # last eight lines - which is what hid "Verifying Steam matches" above the artwork downloads.
        self._activity_panel.rowconfigure(1, weight=0)
        self._activity_panel.rowconfigure(3, weight=1)
        for label in (self.archives_label, self.supported_label, self.scanned_label):
            label.configure(text="0")
        self.size_label.configure(text="0 B")
        self.elapsed_label.configure(text="00:00")
        self.progress.configure(value=0)
        self.current.configure(text="Preparing scan…")
        self.feed.clear()
        self.feed.break_run()
        self.timeline.reset()
        self.repair_note.configure(text="")
        self._art_ok = set()
        self._refresh_artwork()
        self.scanning = True
        self.scan_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.repair_done = 0
        self.repair_free = 0
        self.repair_total = 0
        self.repair_index = 0
        self.repair_grown = 0
        self.stage_row.configure(text="phase: discover" if quick else "phase: cleanup", fg=ACCENT_HI)
        for key in ("repair_size", "repair_extracted", "repair_percent", "repair_count", "repair_level", "repair_saved", "repair_grown"):
            getattr(self, key + "_label").configure(text="—")
        for row in self.conversion_rows:
            row.destroy()
        self.conversion_rows = []

    def set_result(self, result):
        self.scanning = False
        self.scan_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.feed.write(f"Scan complete — {len(result.archives)} archives discovered", "good")
        # ScanResult.errors was collected by the scanner and then referenced nowhere, so a scan that hit a
        # real problem still reported a clean completion. Failures are stated explicitly instead.
        errors = list(getattr(result, "errors", []) or [])
        for message in errors:
            self.feed.write(f"Scan problem: {message}", "bad")
        # Abandoned build folders hold real disk space and are invisible otherwise. Stating them keeps the
        # scan honest about what it found without the app deleting anything on its own initiative.
        stale_dirs = int(getattr(result, "stale_build_dirs", 0) or 0)
        if stale_dirs:
            self.feed.write(f"{stale_dirs} abandoned build folder(s) — {human_size(getattr(result, 'stale_build_bytes', 0) or 0)} reclaimable", "warn")
        if errors:
            self.repair_note.configure(text=f"{len(errors)} problem(s) during scan", fg=RED)
            self.current.configure(text=f"Scan finished with {len(errors)} problem(s): {errors[0]}", fg=RED)
        else:
            self.current.configure(text="Scan complete. Starting automatic Steam verification…")
        # Restore the idle layout: un-hide the last scan report. The feed row keeps its weight so the
        # panel does not collapse to the last_scan's natural height and leave a blank gap below it.
        if self.last_scan is not None and not self.last_scan.winfo_manager():
            self.last_scan.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 6))
        self._activity_panel.rowconfigure(1, weight=0)
        self._activity_panel.rowconfigure(3, weight=1)
        self.scan_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")

    def finish_artwork_scan(self, archives):
        """UI state after a quick artwork scan completes.

        The scan buttons are left in their running state (scan disabled, cancel enabled)
        because background verification is starting next — _end() will restore them when
        that verification finishes, mirroring how scan_done/set_result handle the full scan."""
        count = len(archives)
        with_art = sum(1 for a in archives if getattr(a, "artwork", None) and a.artwork.present())
        self.scanning = False
        kind = "good" if count > 0 else "muted"
        if count == 0:
            self.feed.write("Artwork scan complete — no new archives found — cache is fresh", kind)
            self.current.configure(text="Artwork scan complete — no new archives")
        else:
            self.feed.write(f"Artwork scan complete — {count} new archive(s) — {with_art} with artwork", kind)
            self.current.configure(text=f"Artwork scan complete — {count} new archive(s), {with_art} with artwork")
        if self.last_scan is not None and not self.last_scan.winfo_manager():
            self.last_scan.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 6))
        self._activity_panel.rowconfigure(1, weight=0)
        self._activity_panel.rowconfigure(3, weight=1)

    def verification_update(self, index, total, archive, steam_match):
        self.scanned_label.configure(text=f"Steam {index}/{total}" if total else f"Steam {index}")
        self.progress.configure(value=(index / total * 100) if total else 0)
        status = f"✓ {steam_match.name}" if steam_match.found else "Needs Review"
        # Confidence and source decide whether a match can be trusted, and that is exactly what a user wants
        # to catch while it is still one line in a live feed rather than after the run has finished.
        if steam_match.found:
            confidence = (steam_match.confidence or "").strip()
            source = (steam_match.source or "").strip()
            detail = "   •   ".join(part for part in (f"confidence {confidence}" if confidence else "", f"via {source}" if source else "") if part)
            if detail:
                status = f"{status}  ({detail})"
        self.current.configure(text=f"Verifying Steam matches: {index}/{total}\n{archive.display_name}\n{status}")
        kind = "good" if steam_match.found else "warn"
        self._append_activity(f"• Steam {index}/{total}: {archive.display_name} — {status}", kind)

    def progress_update(self, count, index, total, size, supported, skipped, path):
        self.scanning = True
        self.scan_btn.configure(state="disabled")
        (self.artwork_scan_btn.configure(state="disabled") if self.artwork_scan_btn else None)
        self.cancel_btn.configure(state="normal")
        self.archives_label.configure(text=str(count))
        self.size_label.configure(text=self._size(size))
        self.supported_label.configure(text=str(supported))
        self.scanned_label.configure(text=f"{index}/{total}" if total else str(index))
        self.progress.configure(value=(index / total * 100) if total else 0)
        self.current.configure(text="Scanning: " + (str(path) if path else "finishing scan"))
        self.activity.configure(state="normal")
        if path:
            self._append_activity(f"• {path.name}\n")

    def artwork_update(self, index, total, archive, event):
        """Reports each artwork asset as it is fetched. Cover art downloads dominate verification time, so
        without this the scan looked stalled on a large library with no indication anything was happening."""
        state = event.get("state", "start")
        name = event.get("asset", "cover")
        detail = event.get("detail", "")
        verb = {"start": "Downloading cover", "downloaded": "Downloaded", "cached": "Cached", "failed": "Failed"}.get(state, "Working")
        color = {"downloaded": GREEN, "cached": MUTED, "failed": RED}.get(state, CYAN)
        self.current.configure(text=f"Artwork {index} of {total}  •  {archive.display_name}\n{verb} {name} {('  •  ' + detail) if detail else ''}", fg=color)
        self.scanned_label.configure(text=f"Steam {index}/{total}" if total else f"Steam {index}")
        self.feed.write(f"Artwork: {archive.display_name} — {verb.lower()} {name}{('  ' + detail) if detail else ''}", "good" if state == "downloaded" else ("bad" if state == "failed" else "muted"))
        appid = event.get("appid") or getattr(archive.steam, "appid", "")
        if state in ("downloaded", "cached") and appid:
            self._art_ok.add(str(appid))
        self._refresh_artwork(total)

    def _refresh_artwork(self, total=0):
        have = len(self._art_ok)
        if not have:
            self.art_label.configure(text="No artwork downloaded yet", fg=MUTED)
            return
        share = f"{have / total:.0%}" if total else f"{have} game(s)"
        color = GREEN if total and have >= total else CYAN
        self.art_label.configure(text=f"{have} of {total} games have artwork  •  {share}" if total else f"{have} game(s) have artwork", fg=color)

    def repair_update(self, event):
        """Shows the background .zip/.rar -> .7z repair pass that runs in both scan modes, so leftovers left
        by earlier runs are visibly corrected instead of the scan appearing to do nothing.

        This pass is the longest thing a scan does and it previously moved nothing at all: the bar was owned
        by discovery, which had long since finished, so a scan that spent an hour converting looked frozen.
        The bar is now shared, and driven by 7z's own progress within the archive being worked on.
        """
        if isinstance(event, str):
            event = {"message": event, "stage": "working"}
        stage = event.get("stage", "working")
        label = {
            "extracting": "Converting", "compressing": "Compressing", "verifying": "Verifying",
            "converted": "Converted", "failed": "Failed", "skipped": "Skipped",
            "repair_plan": "Queued", "repair_start": "Converting"}.get(stage, "Repairing")
        name = event.get("file") or ""
        # The count is the point: this pass can run for an hour over twenty archives, and "3 converted" alone
        # cannot say whether three of twenty are done or three of three hundred. The service now reports the
        # total it fixed before the first rebuild, so the screen can say what is left, not only what is behind.
        index = event.get("index")
        total = event.get("total")
        if isinstance(total, int) and total:
            self.repair_total = total
            self.repair_index = index if isinstance(index, int) else self.repair_index
        percent = event.get("tool_percent")
        sizes = self._space_delta(event)
        in_flight = stage in ("extracting", "compressing", "verifying")
        # Both halves of the conversion are assembled here rather than only the finished one. Extraction has
        # already reported the source size and compression the extracted total, so there was never a reason to
        # show a bare filename for the quarter of an hour the tool spends on it.
        lines = [f"{label}{f' {percent}%' if percent is not None else ''}{f'   •   {index} of {total}' if total else ''}   •   {name}"]
        entry = Path(event.get("tool_file") or "").name
        if entry:
            lines.append(entry)
        detail = self._live_detail(event) if in_flight else sizes
        if detail:
            lines.append(detail)
        self.current.configure(text="\n".join(lines))
        color = {"converted": GREEN, "failed": RED, "skipped": ORANGE}.get(stage, MUTED)
        # Accumulate before the bar is drawn. The completion event is what carries the finished count, so a bar
        # computed before this point was always one archive behind: it could never reach 100% on the last
        # archive, which read as a run that had not finished when it had.
        if stage == "converted":
            self.repair_done += 1
            source_bytes = int(event.get("source_bytes") or 0)
            target_bytes = int(event.get("target_bytes") or 0)
            # Signed on purpose. Clamping this at zero reported a .7z that came out larger than the .zip it
            # replaced as "0 B saved", so a run that was quietly costing disk space looked like a harmless one.
            self.repair_free += source_bytes - target_bytes
            if source_bytes and target_bytes > source_bytes:
                self.repair_grown += 1
        if stage in ("converted", "failed", "skipped"):
            self.feed.break_run()
        bits = []
        if percent is not None:
            bits.append(f"{percent}%")
        if event.get("tool_file"):
            bits.append(Path(event["tool_file"]).name)
        if event.get("level"):
            bits.append(f"level {event['level']}")
        suffix = f"   {'   '.join(bits)}" if bits else ""
        if stage in ("converted", "failed", "skipped"):
            # The size line is the whole point of the conversion, so it goes in the feed next to the name
            # rather than only on a panel nobody has open while the run streams.
            detail = f"   —   {sizes}" if sizes else ""
            self.feed.write(f"• {label}: {name}{suffix}{detail}", "good" if stage == "converted" else ("bad" if stage == "failed" else ("warn" if stage == "skipped" else "muted")))
        elif stage == "repair_plan":
            self.feed.break_run()
            self.feed.write(f"• {event.get('message') or label}", "muted")
        elif stage == "repair_start":
            self.feed.break_run()
            self.feed.write(f"• {event.get('message') or label}", "muted")
        else:
            # The feed is what a user is actually watching while a conversion runs, so the size the extraction
            # and compression stages already reported belongs on its line too - the finished "what it became"
            # line is fifteen minutes away and only ever arrives once.
            live = self._live_detail(event)
            self.feed.update(f"repair:{name}", f"• {label}{f' ({index} of {total})' if total else ''}: {name}{f'   {live}' if live else ''}{suffix}", "muted")
        # Live data for the conversion, not just its name: what is happening, how big, and how far along.
        if event.get("source_bytes"):
            self.repair_size_label.configure(text=self._size(event["source_bytes"]))
        if percent is not None:
            self.repair_percent_label.configure(text=f"{percent}%")
        if event.get("extracted_bytes"):
            self.repair_extracted_label.configure(text=self._size(event["extracted_bytes"]))
        # The level is reported from the first stage onwards, not only once an archive finishes, because the
        # moment it steps down is exactly when a user watching an unattended run needs to know.
        if event.get("level"):
            self.repair_level_label.configure(text=str(event["level"]))
        # "2 of 9 converted  •  7 left" reads as a countdown. Left is simply what has not finished yet: the
        # finished count has already been incremented by the time this runs, so anything that counted the
        # archive in flight as well would report one too few.
        total = getattr(self, "repair_total", 0) or 0
        done = self.repair_done
        left = max(0, total - done)
        count = f"{done} of {total} converted" if total else f"{done} converted"
        if total and left:
            count += f"   •   {left} left"
        self.repair_count_label.configure(text=count)
        # Saved is signed, and it is filled in from the first completed conversion rather than staying at a
        # placeholder: a run that has freed nothing yet and a run whose total cannot be computed are different
        # things, and the second one used to look exactly like the first.
        self.repair_saved_label.configure(
            text=(f"{self._size(self.repair_free)} freed" if self.repair_free >= 0
                  else f"{self._size(-self.repair_free)} LOST"),
            fg=GREEN if self.repair_free >= 0 else ORANGE)
        self.repair_grown_label.configure(text=str(self.repair_grown), fg=ORANGE if self.repair_grown else TEXT)
        if stage in ("converted", "failed", "skipped") and event.get("source_bytes") and event.get("target_bytes"):
            self._add_conversion_row(name, event)
        # The bar covers the whole repair phase: archives finished, plus how far through the one in flight the
        # tool says it is. Each stage owns a slice of a single archive and reports a real percentage inside it,
        # so the bar moves continuously instead of sitting still for the fifteen minutes one archive takes.
        within = 0.0
        if percent is not None and stage in ("extracting", "compressing", "verifying"):
            low, high = SCAN_STAGE_SPAN.get(stage, (0.0, 1.0))
            within = low + (high - low) * (max(0.0, min(100.0, percent)) / 100.0)
        settled = done if stage == "repair_plan" else max(0, done - (1 if stage in ("converted", "failed", "skipped") else 0))
        fraction = 1.0 if stage in ("converted", "failed", "skipped") else within
        self.progress.configure(value=min(100.0, (settled + fraction) / total * 100) if total else min(100.0, fraction * 100))
        # Conversion is the repair phase, so the stage row and the timeline follow it rather than sitting on
        # whatever phase discovery happened to leave behind.
        if stage in ("extracting", "compressing", "verifying", "repair_plan", "repair_start"):
            self.stage_row.configure(text="phase: repair (converting)", fg=ACCENT_HI)
            self.timeline.set_state("repair", "active")
        elif stage == "converted":
            self.stage_row.configure(text="phase: repair (done)", fg=GREEN)
        elif stage in ("failed", "skipped"):
            self.stage_row.configure(text=f"phase: repair ({stage})", fg=RED if stage == "failed" else ORANGE)
        self.repair_note.configure(text=event.get("message") or f"{label} {name}", fg=color)

    def set_elapsed(self, text):
        self.elapsed_label.configure(text=text)

    def phase_update(self, event):
        """Renders one scan-pipeline phase record. Phases that used to run silently now mark the timeline,
        announce their real outcome in the feed, and surface any that failed instead of only logging it."""
        stage = event.get("stage", "")
        message = event.get("message", "")
        finished = stage.endswith("_done")
        phase = stage[:-5] if finished else stage
        known = dict(SCAN_PHASES)
        if phase in known:
            if finished:
                self.timeline.set_state(phase, "failed" if event.get("failed") else ("skipped" if event.get("skipped") else "done"))
            else:
                self.timeline.set_state(phase, "active")
            if not finished:
                self.stage_row.configure(text=f"phase: {known[phase].lower()}", fg=ACCENT_HI)
        kind = "bad" if event.get("failed") else ("muted" if event.get("skipped") else ("good" if finished else "info"))
        self.feed.write(f"{known[phase]}: {message}" if phase in known and finished else message, kind)
        self.current.configure(text=message, fg=RED if event.get("failed") else (MUTED if event.get("skipped") else TEXT))
        # Audit is the one phase after discovery that knows how much work is left: it walks a fixed list of
        # game folders, so the bar can show real progress. It used to be an indeterminate wait that reported
        # one line and then nothing for minutes, which is the worst of both - no movement and no reason.
        if not finished and phase == "audit":
            total = event.get("total") or 0
            index = event.get("index") or 0
            if total:
                self.progress.configure(value=min(100.0, index / total * 100))
            if index and total:
                self.stage_row.configure(text=f"phase: audit ({index} of {total})", fg=ACCENT_HI)
        elif finished and phase == "audit":
            self.stage_row.configure(text="phase: audit (done)", fg=GREEN)
        # Discovery owns the percentage bar; the other phases are indeterminate work the bar cannot express.
        elif phase in ("discover", "discover_done") and not finished:
            self.progress.configure(value=0)

    def load_api(self, value):
        value = (value or "").strip()
        self.api_var.set(value)
        self.api_status.configure(text="Configured" if value else "Not configured", fg=GREEN if value else MUTED)

    def save_api(self):
        self.api_status.configure(text="API key ready for saved configuration" if self.api_var.get().strip() else "API not configured", fg=GREEN if self.api_var.get().strip() else MUTED)
        return self.api_var.get().strip()

    def test_api(self):
        key = self.api_var.get().strip()
        if not key:
            self.api_status.configure(text="Enter an API key first", fg=ORANGE)
            return
        self.api_status.configure(text="Testing SteamGridDB API…", fg=ACCENT_HI)

        def worker():
            try:
                req = Request("https://www.steamgriddb.com/api/v2/search/autocomplete/steam", headers={"Authorization": f"Bearer {key}", "Accept": "application/json", "User-Agent": USER_AGENT})
                # Read the body before letting the response close. Closing without draining it does not shut
                # the SSL socket down cleanly - it is left for the garbage collector, and every key test left
                # a ResourceWarning behind. This was the only HTTP call site in the app that read only the
                # status line; the response is a few bytes of autocomplete JSON, so draining it costs nothing.
                with urlopen(req, timeout=12) as r:
                    code = getattr(r, "status", 200)
                    r.read()
                ok = code in (200, 204)
                msg = "✓ API connection successful" if ok else f"API returned HTTP {code}"
            except Exception as exc:
                ok = False
                msg = f"API test failed: {type(exc).__name__}"
            # RuntimeError as well as TclError: this runs on a worker thread, and tkinter raises
            # "main thread is not in main loop" rather than a TclError when a cross-thread after() has no
            # mainloop to hand it to. Uncaught in a thread that is all it amounts to - a traceback on stderr
            # from a daemon nobody is joining, and an API status line left saying "Testing...".
            try:
                self.after(0, lambda: self.api_status.configure(text=msg, fg=GREEN if ok else RED))
            except (tk.TclError, RuntimeError):
                pass

        import threading

        threading.Thread(target=worker, daemon=True).start()
