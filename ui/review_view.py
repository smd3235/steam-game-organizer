import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from utils.desktop import open_url
from .widgets.game_list import GameList
from .widgets.metadata_panel import MetadataPanel
from .widgets.artwork_panel import ArtworkPanel
from .widgets.category_evidence_panel import CategoryEvidencePanel

from .theme import ACCENT_HI, BG, BORDER, GREEN, MUTED, ORANGE, PANEL, PANEL2, RED, TEXT, human_size, panel, radio, scroll_text
from core.constants import DEFAULT_CATEGORIES, SUPPLEMENTAL_CATEGORIES, canonical_category
from services.installer_detect import NEEDS_INSTALL_DIRNAME
from core.models import ArtworkResult, SteamMatch
from services.batch_extract_service import BatchPlan, BatchItem
from ui.batch_extract_window import run_batch_window

# Additional imports for extract_selected
from services.archive_service import ArchiveService
from services.catalog_status import already_extracted
from core.uri_actions import safe_folder_name
from pathlib import Path


class ReviewView(tk.Frame):
    def __init__(self, parent, controller, state, logger, jobs, on_next=None, on_verified=None, on_verification_progress=None):
        super().__init__(parent, bg=BG)
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
        self.search_var = tk.StringVar()
        self.filter_var = tk.StringVar(value="All")
        self.mode_var = tk.StringVar(value="New Only")
        self.columnconfigure(0, weight=34, minsize=350)
        self.columnconfigure(1, weight=66)
        self.rowconfigure(2, weight=1)
        head = tk.Frame(self, bg=BG)
        head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 7))
        tk.Label(head, text="GAME REVIEW", bg=BG, fg=ACCENT_HI, font=("TkDefaultFont", 9, "bold")).pack(side="left")
        self.progress = tk.Label(head, text="Verification idle", bg=BG, fg=MUTED, font=("TkDefaultFont", 9, "bold"))
        self.progress.pack(side="right")
        self.summary = tk.Label(head, text="", bg=BG, fg=TEXT, font=("TkDefaultFont", 8, "bold"))
        self.summary.pack(side="right", padx=18)
        controls = panel(self)
        controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        controls.columnconfigure(0, weight=1)

        # Search group
        search_frame = tk.Frame(controls, bg=PANEL)
        search_frame.grid(row=0, column=0, sticky="w", padx=(0, 10))
        tk.Label(search_frame, text="SEARCH", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8, "bold")).pack(side="left")
        tk.Entry(search_frame, textvariable=self.search_var, bg=PANEL2, fg=TEXT, disabledforeground=MUTED, insertbackground=TEXT, relief="flat", highlightbackground=BORDER, highlightthickness=1, width=18).pack(side="left", padx=(5, 0))
        self.search_var.trace_add("write", lambda *_: self._filters_changed())
        # Filter group
        filter_frame = tk.Frame(controls, bg=PANEL)
        filter_frame.grid(row=0, column=1, sticky="w", padx=(0, 10))
        tk.Label(filter_frame, text="FILTER", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8, "bold")).pack(side="left")
        f = ttk.Combobox(filter_frame, textvariable=self.filter_var, state="readonly", values=["All", "Needs Review", "Verified", "New Only", "Artwork"], width=14)
        f.pack(side="left", padx=(5, 0))
        f.bind("<<ComboboxSelected>>", lambda e: self._filters_changed())
        # Mode group
        mode_frame = tk.Frame(controls, bg=PANEL)
        mode_frame.grid(row=0, column=2, sticky="w", padx=(0, 10))
        self._radio(mode_frame, "ALL", "All").pack(side="left", padx=(0, 2))
        self._radio(mode_frame, "NEW ONLY", "New Only").pack(side="left", padx=(2, 0))
        # Action group
        action_frame = tk.Frame(controls, bg=PANEL)
        action_frame.grid(row=0, column=3, sticky="e")
        ttk.Button(action_frame, text="＋ Add Category", style="Secondary.TButton", command=self.add_category).pack(side="left", padx=(0, 4))
        ttk.Button(action_frame, text="Use All Suggestions", style="Secondary.TButton", command=self.use_all_suggestions).pack(side="left", padx=(0, 4))
        self.approve_all_button = ttk.Button(action_frame, text="Approve All Verified", style="Primary.TButton", command=self.approve_all)
        self.approve_all_button.pack(side="left", padx=(4, 0))
        ttk.Button(action_frame, text="Extract Selected", style="Primary.TButton", command=self.extract_selected).pack(side="left", padx=(4, 0))
        self.list = GameList(self, self.select)
        self.list.grid(row=2, column=0, sticky="nsew", padx=(0, 10))
        right = panel(self)
        right.grid(row=2, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        viewport = tk.Frame(right, bg=PANEL)
        viewport.grid(row=0, column=0, columnspan=2, sticky="nsew")
        viewport.columnconfigure(0, weight=1)
        viewport.rowconfigure(0, weight=1)
        self.detail_canvas = tk.Canvas(viewport, bg=PANEL, highlightthickness=0)
        self.detail_scroll = ttk.Scrollbar(viewport, orient="vertical", command=self.detail_canvas.yview, style="Dark.Vertical.TScrollbar")
        self.detail_canvas.configure(yscrollcommand=self.detail_scroll.set)
        self.detail_canvas.grid(row=0, column=0, sticky="nsew")
        self.detail_scroll.grid(row=0, column=1, sticky="ns")
        self.detail_inner = tk.Frame(self.detail_canvas, bg=PANEL)
        self.detail_win = self.detail_canvas.create_window((0, 0), window=self.detail_inner, anchor="nw")
        self.detail_inner.bind("<Configure>", lambda e: self.detail_canvas.configure(scrollregion=self.detail_canvas.bbox("all")))
        self.detail_canvas.bind("<Configure>", lambda e: self.detail_canvas.itemconfigure(self.detail_win, width=max(1, e.width)))
        tk.Label(self.detail_inner, text="GAME DETAILS", bg=PANEL, fg=ACCENT_HI, font=("TkDefaultFont", 9, "bold")).pack(anchor="w", padx=14, pady=(10, 4))
        # Title section
        title_section = tk.Frame(self.detail_inner, bg=PANEL)
        title_section.pack(fill="x", padx=14, pady=(0, 4))
        self.title_var = tk.StringVar(value="")
        self.title_entry = tk.Entry(title_section, textvariable=self.title_var, bg=PANEL2, fg=TEXT, disabledforeground=MUTED, insertbackground=TEXT, relief="flat", highlightbackground=BORDER, highlightthickness=1, font=("TkDefaultFont", 16, "bold"))
        self.title_entry.pack(side="left", fill="x", expand=True)
        self.title_search = ttk.Button(title_section, text="SEARCH STEAM", style="Secondary.TButton", command=self.search_again)
        self.title_search.pack(side="left", padx=(8, 0))
        self.subtitle = tk.Label(self.detail_inner, text="The discovered list is verified automatically.", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 9), wraplength=900, justify="left", anchor="w")
        self.subtitle.pack(fill="x", padx=14, pady=(3, 6))
        # Action buttons
        detail_actions = tk.Frame(self.detail_inner, bg=PANEL)
        detail_actions.pack(fill="x", padx=14, pady=(0, 4))
        self.search_button = ttk.Button(detail_actions, text="Search Again", style="Secondary.TButton", command=self.search_again)
        self.search_button.pack(side="left", padx=(0, 6))
        self.wrong_button = ttk.Button(detail_actions, text="Wrong Match", style="Secondary.TButton", command=self.wrong_match)
        self.wrong_button.pack(side="left", padx=6)
        self.reevaluate_button = ttk.Button(detail_actions, text="Re-evaluate", style="Secondary.TButton", command=self.re_evaluate)
        self.reevaluate_button.pack(side="left", padx=6)
        self.open_button = ttk.Button(detail_actions, text="Open Steam", style="Secondary.TButton", command=self.open_steam)
        self.open_button.pack(side="left", padx=6)
        # Hero section - artwork and metadata
        hero = tk.Frame(self.detail_inner, bg=BG)
        hero.pack(fill="x", padx=14, pady=(0, 7))
        hero.columnconfigure(0, weight=3)
        hero.columnconfigure(1, weight=2)  # Artwork gets more space
        self.art = ArtworkPanel(hero)
        self.art.configure(height=420)
        self.art.grid(row=0, column=0, sticky="nsew", pady=(0, 7))
        self.art.grid_propagate(False)
        self.meta = MetadataPanel(hero)
        self.meta.grid(row=0, column=1, sticky="nsew", pady=(0, 7), padx=(10, 0))
        # Evidence panel
        self.evidence_panel = CategoryEvidencePanel(self.detail_inner)
        self.evidence_panel.pack(fill="x", padx=14, pady=(0, 7))
        # Description section
        desc = panel(self.detail_inner)
        desc.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        tk.Label(desc, text="DESCRIPTION / EVIDENCE", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8, "bold")).pack(anchor="w", padx=12, pady=(10, 4))
        self.detail = tk.Text(desc, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief="flat", bd=0, wrap="word")
        self.detail.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        self.detail.configure(state="disabled")
        actions = tk.Frame(right, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        # Category selection group
        category_group = tk.Frame(actions, bg=PANEL)
        category_group.pack(side="left", padx=(12, 0), pady=9)
        tk.Label(category_group, text="CATEGORY", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8, "bold")).pack(side="left", padx=(0, 6))
        self.category = ttk.Combobox(category_group, values=DEFAULT_CATEGORIES, state="readonly", width=22)
        self.category.pack(side="left", pady=7)
        self.category.bind("<<ComboboxSelected>>", lambda e: self._update_suggestion_hint())
        self.suggestion_label = tk.Label(category_group, text="", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8))
        self.suggestion_label.pack(side="left", padx=(10, 4))
        self.use_suggested_button = ttk.Button(category_group, text="Use Suggested", style="Secondary.TButton", command=self.use_suggested)
        self.use_suggested_button.pack(side="left", padx=(0, 6))
        self.category.bind("<<ComboboxSelected>>", self._category_changed)
        # Action buttons group
        action_group = tk.Frame(actions, bg=PANEL)
        action_group.pack(side="right", padx=(0, 12), pady=6)
        ttk.Button(action_group, text="Skip", style="Secondary.TButton", command=self.skip).pack(side="left", padx=(0, 6))
        ttk.Button(action_group, text="Cancel Lookup", style="Danger.TButton", command=self.cancel_lookup).pack(side="left", padx=6)
        self.accept_button = ttk.Button(action_group, text="ACCEPT & NEXT  >", style="Primary.TButton", command=self.accept)
        self.accept_button.pack(side="left", padx=6)
        self.continue_button = ttk.Button(action_group, text="CONTINUE TO ORGANIZATION  >", style="Secondary.TButton", command=self.continue_to_organize)
        self.continue_button.pack(side="left", padx=6)
        self._wheel_root = self.winfo_toplevel()
        self._wheel_bindings = []
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self._wheel_bindings.append((sequence, self._wheel_root.bind(sequence, self._route_wheel, add="+")))
        self._update_continue_state()

    def _is_descendant(self, widget, parent):
        while widget is not None:
            if widget == parent:
                return True
            try:
                widget = widget.master
            except AttributeError:
                return False
        return False

    def _route_wheel(self, event):
        widget = getattr(event, "widget", None)
        if widget is None or str(getattr(widget, "winfo_class", lambda: "")()) in ("Tk", "Toplevel"):
            widget = self.winfo_containing(getattr(event, "x_root", 0) or 0, getattr(event, "y_root", 0) or 0)
        if widget is None:
            return None
        widget_class = str(getattr(widget, "winfo_class", lambda: "")())
        if widget_class == "Listbox":
            return None
        if widget_class in ("TCombobox", "Entry", "TEntry"):
            return "break"
        if self._is_descendant(widget, self.list):
            delta = int(getattr(event, "delta", 0))
            step = -max(1, abs(delta) // 120) * (1 if delta > 0 else -1) if delta else (-1 if getattr(event, "num", 0) == 4 else 1)
            self.list.canvas.yview_scroll(step, "units")
            return "break"
        if self._is_descendant(widget, self.detail_inner):
            if isinstance(widget, tk.Text):
                return scroll_text(widget, event)
            delta = int(getattr(event, "delta", 0))
            step = -max(1, abs(delta) // 120) * (1 if delta > 0 else -1) if delta else (-1 if getattr(event, "num", 0) == 4 else 1)
            self.detail_canvas.yview_scroll(step, "units")
            return "break"
        if self._is_descendant(widget, self.detail_canvas):
            canvas = self.detail_canvas
            delta = int(getattr(event, "delta", 0))
            step = -max(1, abs(delta) // 120) * (1 if delta > 0 else -1) if delta else (-1 if getattr(event, "num", 0) == 4 else 1)
            canvas.yview_scroll(step, "units")
            return "break"
        return None

    def _radio(self, parent, text, value):
        return radio(parent, text, value, self.mode_var, command=self._filters_changed)

    def add_category(self):
        n = simpledialog.askstring("Add Category", "Enter the new category name:", parent=self.winfo_toplevel())
        if n:
            n = n.strip()
            if n and n not in self.category["values"]:
                self.category["values"] = list(self.category["values"]) + [n]
                self.category.set(n)
                self._category_changed()

    def use_all_suggestions(self):
        for archive in self.archives:
            if archive.steam.found and not archive.decision.skipped:
                self._apply_group_decision(archive, archive.decision.category, accepted=True, skipped=False)
        self.list.refresh()
        self._update_summary()
        if self.on_next and all(archive.steam.found or archive.decision.skipped for archive in self.archives):
            self.on_next()

    def approve_all(self):
        approved = set()
        for archive in self.archives:
            if archive.identity_key in approved or not archive.steam.found or archive.decision.skipped:
                continue
            self.controller.remember_category(archive.identity_key, archive.decision.category, archive.steam.appid if archive.steam.found else None)
            archive.decision.accepted = True
            approved.add(archive.identity_key)
        if approved:
            self.progress.configure(text=f"Approved {len(approved)} verified game(s) with their selected categories")
        if not self.selected:
            return
        chosen = canonical_category(self.category.get() or "Unsorted")
        if self.selected.identity_key != chosen:
            self.selected.decision.changed_from_suggestion = bool(self.selected.decision.suggested_category) and chosen != self.selected.decision.suggested_category
            self.selected.decision.category = chosen
        self.controller.remember_category(self.selected.identity_key, chosen, self.selected.steam.appid if self.selected.steam.found else None)
        self.list.refresh()
        self._update_summary()
        self._update_suggestion_hint()

    def _filters_changed(self):
        self.list.set_filter(self.search_var.get(), "New Only" if self.mode_var.get() == "New Only" else self.filter_var.get())

    def load(self, archives, download_artwork=True):
        self.cancel_lookup()
        self.archives = list(archives)
        self.list.set_auto_scroll(True)
        self.list.set_items(self.archives)
        self._filters_changed()
        self.selected = None
        self.title_var.set("Automatic verification in progress...")
        self.subtitle.configure(text="Select a game to inspect.")
        self.progress.configure(text=f"Verifying 0 of {len(self.archives)}...")
        self.detail_canvas.yview_moveto(0)
        self._update_summary()
        self._update_continue_state()
        # An empty list is the normal outcome of New Only with nothing new. Going through the thread
        # pool for zero items is wasteful and, in conditions where the pool is briefly full, the
        # completion callback can stall behind audit-progress events queued by the scan that just
        # finished - the screen reads as hung on "Verifying 0 of 0". Schedule the completion on the
        # next Tk tick instead so scan_done's show('scan') has already run when _verified switches
        # back to the review screen.
        if not self.archives:
            self.verify_ctx = None
            self.after(0, lambda: self._verified([]))
        else:
            self.verify_ctx = self.controller.verify_all(self.archives, self._progress, self._verified, download_artwork=download_artwork)

    def _progress(self, i, total, a, m, art, event=None):
        if not self.winfo_exists():
            return
        if event:
            asset = (event.get("asset") or "artwork").replace("_", "-")
            state = event.get("state") or ""
            detail = event.get("detail") or ""
            name = a.steam.name or a.display_name
            if state == "failed":
                self.progress.configure(text=f"Artwork {asset} failed  -  {detail or name}", fg=RED)
            elif state in ("downloaded", "cached"):
                tail = f"  -  {detail}" if state == "downloaded" and detail else ("  -  from cache" if state == "cached" else "")
                self.progress.configure(text=f"Artwork ready  -  {name}  -  {asset}{tail}", fg=GREEN)
            else:
                self.progress.configure(text=f"Artwork {asset} {state}  -  {name}  -  {i} of {total}", fg=ACCENT_HI)
            if self.on_verification_progress:
                self.on_verification_progress(i, total, a, m, None, event)
            return
        self.progress.configure(text=f"Verifying {i} of {total}  -  {i / total:.0%}" if total else "Verification idle", fg=MUTED)
        if self.winfo_ismapped():
            self.list.refresh()
            self._update_summary()
        if self.on_verification_progress:
            self.on_verification_progress(i, total, a, m)
        if self.winfo_ismapped() and self.selected is a:
            self._show_selected(a, reset=False)

    def _verified(self, archives):
        self.list.set_auto_scroll(False)
        self.archives = list(archives)
        self.progress.configure(text=f"Verification complete  -  {len(archives)} games")
        self.list.refresh()
        self._update_summary()
        self._update_continue_state()
        self.verify_ctx = None
        if self.on_verified:
            self.on_verified(archives)
        if archives and not self.selected:
            self.select(archives[0])
        # An empty list is the normal outcome of New Only with nothing new, not a stuck run. Say so on
        # the screen rather than leaving a blank list with a disabled button, which reads as a hang.
        if not archives:
            self.subtitle.configure(text="No new archives this run — the library audit and catalog already ran. Press CONTINUE TO ORGANIZATION to finish.")

    def select(self, archive):
        self.selected = archive
        self.list.select_archive(archive)
        self._show_selected(archive, reset=True)
        self.logger.info("UI", f"REVIEW_SELECT title=[{archive.display_name}]")

    def _update_summary(self):
        groups = {a.identity_key for a in self.archives}
        verified = {a.identity_key for a in self.archives if a.steam.found}
        skipped = {a.identity_key for a in self.archives if a.decision.skipped}
        low = {a.identity_key for a in self.archives if a.steam.found and a.steam.confidence not in ("High", "")}
        overridden = {a.identity_key for a in self.archives if a.decision.changed_from_suggestion}
        self.summary.configure(text=f"{len(self.archives)} archives  -  {len(groups)} logical  -  {max(0, len(self.archives) - len(groups))} collapsed  -  {len(verified)} verified  -  {len(groups - verified - skipped)} need Steam  -  {len(low)} low confidence  -  {len(overridden)} category overridden  -  {len(skipped)} skipped")
        self.approve_all_button.configure(state="normal" if any(a.steam.found and not a.decision.skipped and not a.decision.accepted for a in self.archives) else "disabled")

    def _update_continue_state(self):
        # Enabled when there is nothing left to resolve, not only when the list is non-empty. Under New
        # Only a scan that finds nothing new hands an empty list here, and the run is genuinely done -
        # the audit and catalog phases already ran and wrote their pages. Gating the button on the list
        # being non-empty left a scan that had nothing to do with no way to finish: the only button
        # available was Approve All Verified, which was itself disabled, so the screen could not be
        # left at all and the run appeared to hang on the verify screen.
        unfinished = [a for a in self.archives if not a.decision.accepted and not a.decision.skipped]
        done = not unfinished
        self.continue_button.configure(state="normal" if done else "disabled")
        self.accept_button.configure(state="disabled" if done else "normal")
        # When nothing is left to accept, Accept & Next greys out and Continue to Organization becomes
        # the highlighted (purple) primary action so the user's next step is obvious.
        if done:
            self.accept_button.configure(style="Secondary.TButton")
            self.continue_button.configure(style="Primary.TButton")
        else:
            self.accept_button.configure(style="Primary.TButton")
            self.continue_button.configure(style="Secondary.TButton")

    def _update_suggestion_hint(self):
        a = self.selected
        if not a or not a.decision.suggested_category or a.decision.suggested_category == "Unsorted":
            self.suggestion_label.configure(text="No Steam suggestion yet", fg=MUTED)
            self.use_suggested_button.configure(state="disabled")
            return
        matches = canonical_category(self.category.get() or "") == a.decision.suggested_category
        self.suggestion_label.configure(text=f"Suggested: {a.decision.suggested_category}", fg=GREEN if matches else ORANGE)
        self.use_suggested_button.configure(state="disabled" if matches else "normal")

    def _category_changed(self, event=None):
        self._update_suggestion_hint()

    def use_suggested(self):
        if self.selected and self.selected.decision.suggested_category:
            self.category.set(self.selected.decision.suggested_category)
            self._category_changed()

    def _show_selected(self, a, reset=False):
        choices = sorted(set(DEFAULT_CATEGORIES + SUPPLEMENTAL_CATEGORIES + list(self.category["values"]) + [canonical_category(value) for value in a.steam.genres]), key=lambda value: (value.casefold(), value))
        self.category.configure(values=choices)
        copies = [archive for archive in self.archives if archive.identity_key == a.identity_key]
        formats = ", ".join(sorted({archive.extension.upper().lstrip(".") for archive in copies}))
        versions = ", ".join(sorted({".".join(map(str, archive.version)) for archive in copies if archive.version != (0,)})) or "undated"
        parts = [f"Automatic category: {a.decision.category}", f"Steam genres: {chr(44).join(a.steam.genres) or chr(8212)}"]
        if a.steam.description:
            parts.append(chr(10) + a.steam.description)
        elif a.steam.reason:
            parts.append(chr(10) + a.steam.reason)
            parts.append(chr(10) + "No additional Steam information available.")
        evidence = chr(10).join(parts)
        own = int(getattr(a, "size", 0) or 0)
        self.title_var.set(a.steam.name or a.display_name)
        self.subtitle.configure(text=f"{len(copies)} archive copy(s) - {human_size(own) if own else 'size unknown'} - Formats: {formats or 'unknown'} - Versions: {versions} - Selected: {a.path.name} - {'Verified Steam match' if a.steam.found else 'Steam match needs attention'}")
        self.meta.show(a, copies)
        self.evidence_panel.show(a.decision, a.steam.genres)
        self.category.set(a.decision.category)
        self.art.update_idletasks()
        self.art.show(a.artwork)
        self._set_detail(evidence)
        self.open_button.configure(state="normal" if a.steam.found else "disabled")
        self._update_suggestion_hint()
        self.detail_canvas.update_idletasks()
        self.detail_canvas.configure(scrollregion=self.detail_canvas.bbox("all"))
        if reset:
            self.detail_canvas.yview_moveto(0)

    def _set_detail(self, text):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    def _single_done(self, archive):
        self.list.set_auto_scroll(False)
        self.verify_ctx = None
        self.list.refresh()
        self._update_summary()
        self._update_continue_state()
        self.select(archive)
        self.progress.configure(text="Single-game verification complete")

    def _single_lookup(self, title):
        if not self.selected or not title.strip():
            return
        self.cancel_lookup()
        self.progress.configure(text=f"Searching Steam for {title.strip()}...")
        self.verify_ctx = self.controller.verify_one(self.selected, title.strip(), self._single_done)

    def search_again(self):
        if not self.selected:
            return
        title = self.title_var.get().strip()
        if title:
            self._single_lookup(title)

    def re_evaluate(self):
        if self.selected:
            self._single_lookup(self.selected.normalized_title)

    def wrong_match(self):
        self.selected.steam = SteamMatch()
        self.selected.artwork = ArtworkResult()
        self.selected.decision.accepted = False
        self.selected.decision.skipped = False
        self.selected.decision.category = "Unsorted"
        self.selected.decision.suggested_category = ""
        self.list.refresh()
        self._update_summary()
        self._update_continue_state()
        self._show_selected(self.selected)

    def open_steam(self):
        if not self.selected or not self.selected.steam.appid:
            return
        url = f"https://store.steampowered.com/app/{self.selected.steam.appid}/"
        if not open_url(url):
            messagebox.showwarning("Could not open a browser", "Nothing on this machine was able to open the Steam page. Open it manually, or set a default browser for http links.", parent=self.winfo_toplevel())

    def shutdown(self):
        self.cancel_lookup()
        for sequence, funcid in getattr(self, "_wheel_bindings", []):
            try:
                self._wheel_root.unbind(sequence, funcid)
            except tk.TclError:
                pass

    def cancel_lookup(self):
        if self.verify_ctx is not None:
            try:
                self.verify_ctx.cancel()
            except Exception:
                pass
            self.verify_ctx = None

    def skip(self):
        if self.selected:
            self._apply_group_decision(self.selected, "Unsorted", accepted=False, skipped=True)
            self.list.refresh()
            self._update_summary()
            self._update_continue_state()
            self._advance()

    def accept(self):
        if not self.selected.steam.found:
            messagebox.showwarning("Steam identification required", "Verify the Steam match first, or choose Skip to leave this archive untouched.", parent=self.winfo_toplevel())
            return
        chosen = canonical_category(self.category.get() or "Unsorted")
        self._apply_group_decision(self.selected, chosen, accepted=True, skipped=False)
        self.controller.remember_category(self.selected.identity_key, chosen, self.selected.steam.appid if self.selected.steam.found else None)
        self.list.refresh()
        self._update_summary()
        self._update_continue_state()
        self._advance()

    def _apply_group_decision(self, archive, category, accepted, skipped):
        archive.decision.changed_from_suggestion = bool(archive.decision.suggested_category) and category != archive.decision.suggested_category
        archive.decision.category = category
        archive.decision.accepted = accepted
        archive.decision.skipped = skipped

    def continue_to_organize(self):
        unresolved = [a for a in self.archives if not a.steam.found and not a.decision.skipped]
        pending = [a for a in self.archives if a.steam.found and not a.decision.accepted and not a.decision.skipped]
        if unresolved:
            messagebox.showwarning("Steam identification required", f"{len(unresolved)} game(s) still need a verified Steam identity. Resolve or skip them first.", parent=self.winfo_toplevel())
            return
        if pending:
            messagebox.showwarning("Review decisions required", f"{len(pending)} verified game(s) still need a category decision. Use Accept & Next or Use All Suggestions first.", parent=self.winfo_toplevel())
            return
        if self.on_next:
            self.on_next()

    def _advance(self):
        try:
            idx = self.archives.index(self.selected)
        except ValueError:
            idx = -1
        for candidate in self.archives[idx + 1 :]:
            if candidate.identity_key == self.selected.identity_key:
                continue
            if candidate.decision.accepted or candidate.decision.skipped:
                continue
            self.select(candidate)
            return

    def extract_selected(self):
        """Extract all selected games in a batch window."""
        selected_archives = list(self.list.selected_archives)
        if not selected_archives:
            from tkinter import messagebox

            messagebox.showwarning("No Selection", "Please select games to extract.", parent=self)
            return

        # Get extract folder from config
        if not self.controller.config.extract_folders:
            from tkinter import messagebox

            messagebox.showwarning("No Extract Folder", "Please configure an extract folder in Settings first.", parent=self)
            return
        extract_root = self.controller.config.extract_folders[0]

        # Create batch plan
        plan = BatchPlan(destination=extract_root, category=f"{len(selected_archives)} selected games")
        # Add each selected archive to the plan
        archive_svc = ArchiveService(self.logger)
        for archive in selected_archives:
            try:
                size = archive.stat().st_size
            except OSError:
                size = 0
            # Use the archive's steam name + release date when available, falling back to stem
            name = archive.steam.name or archive.display_name or archive.stem
            release_date = archive.steam.release_date or ""
            clean = name
            if release_date:
                clean = f"{clean} - {release_date.replace(',', '')}"
            # Compute destination the same way plan_batch does
            leaf = safe_folder_name(clean)
            is_installer = archive_svc.archive_installer_kind(archive.path) is not None
            target = extract_root / (Path(NEEDS_INSTALL_DIRNAME) / leaf if is_installer else leaf)

            # Skip if already extracted (matching batch service behavior)
            if already_extracted(target):
                continue

            plan.items.append(BatchItem(archive=archive.path, destination=target, name=name, size=size))

        if not plan.items:
            from tkinter import messagebox

            messagebox.showinfo("Nothing to Extract", "All selected games are already extracted.", parent=self)
            return

        plan.total_bytes = sum(item.size for item in plan.items)
        # Launch batch extract window
        run_batch_window(
            None,  # master - we'll use None and let it create its own root
            logger=self.logger,
            password="",
            plan=plan,
            scanning=False,
        )
