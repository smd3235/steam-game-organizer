import tkinter as tk
from ui.theme import PANEL,PANEL3,TEXT,MUTED,ACCENT,ACCENT_HI,GREEN,ORANGE,CYAN,BORDER,CHART_COLORS
from core.constants import DEFAULT_CATEGORIES

# Category-to-color mapping for the left accent strip. Cycles through CHART_COLORS
# so every category gets a distinct, palette-approved hue.
_CATEGORY_COLORS={}
for _i,_cat in enumerate(DEFAULT_CATEGORIES):
    _hue=CHART_COLORS[_i % len(CHART_COLORS)]
    _CATEGORY_COLORS[_cat]=_hue
_CATEGORY_COLORS['Unsorted']=MUTED

class GameCard(tk.Frame):
    def __init__(self,parent,archive,on_select,selected=False):
        super().__init__(parent,bg=PANEL,highlightbackground=BORDER,highlightthickness=1,padx=12,pady=10)
        self.archive=archive; self.on_select=on_select; self.selected=selected
        self._pulse_id=None
        # Left accent strip: a thin colored bar showing the matched category at a glance.
        # Matches the HTML catalog's category-colored card headers. The strip is hidden
        # when no category has been assigned yet (Unsorted), since every card being grey
        # says nothing.
        cat=archive.decision.category or 'Unsorted'
        strip_color=_CATEGORY_COLORS.get(cat, MUTED)
        self._strip=tk.Frame(self,bg=strip_color,height=14)
        self._strip.pack(anchor='w',fill='x',pady=(0,4))
        top=tk.Frame(self,bg=PANEL); top.pack(fill='x')
        self.title=tk.Label(top,text=(archive.steam.name or archive.display_name),bg=PANEL,fg=TEXT,anchor='w',justify='left',wraplength=260,font=('TkDefaultFont',10,'bold')); self.title.pack(side='left',fill='x',expand=True)
        self.badge=tk.Label(top,text='NEW',bg=ACCENT,fg='white',font=('TkDefaultFont',7,'bold'),padx=6,pady=3); self.badge._fixed_bg=True; self.badge.pack(side='right')
        # How sure the match is, as a pill rather than a word in the meta line. It used to be there as text -
        # "Medium confidence" in the same grey as the file extension beside it - so a match the app itself was
        # unsure of looked exactly as settled as one it was sure of, and the only way to notice was to read the
        # small print. Amber next to green is the whole point of showing it.
        self.conf=tk.Label(top,text='',bg=PANEL,fg=MUTED,font=('TkDefaultFont',7,'bold'),padx=6,pady=3); self.conf._fixed_bg=True
        self.conf.pack(side='right',padx=(0,6))
        self.status=tk.Label(self,text='Steam match pending',bg=PANEL,fg=MUTED,anchor='w',font=('TkDefaultFont',8)); self.status.pack(fill='x',pady=(6,0))
        self.meta=tk.Label(self,text=archive.extension.upper().lstrip('.')+'  •  '+archive.path.name,bg=PANEL,fg=MUTED,anchor='w',font=('TkDefaultFont',7)); self.meta.pack(fill='x',pady=(4,0))
        self._overlay=None
        self._make_overlay()
        self._bind_widgets(self)
        self.select(selected)
        self.update_status()

    def _make_overlay(self):
        """Hover overlay showing genre and release date metadata, matching the HTML catalog's .card-hover.
        Shown on mouse-enter / mouse-leave; hidden by default."""
        self._overlay=tk.Label(self,bg=PANEL3,fg=TEXT,font=('TkDefaultFont',7),justify='left',anchor='w',padx=8,pady=6,relief='flat',highlightthickness=1,highlightbackground=BORDER)
        self._overlay.pack_forget()
        self.bind('<Enter>',self._on_enter,add='+')
        self.bind('<Leave>',self._on_leave,add='+')

    def _on_enter(self,_event=None):
        self._show_overlay()
        if not self.selected:
            self._set_bg_recursive(self, PANEL3)

    def _on_leave(self,_event=None):
        self._hide_overlay()
        if not self.selected:
            self._set_bg_recursive(self, PANEL)

    def _set_bg_recursive(self,widget,bg):
        """Apply a background colour to this card and every child, so a hover or
        selection change never leaves a stale strip behind.

        Two children carry a semantic colour that must survive a hover — the badge
        and the confidence pill — so they are marked _fixed_bg and skipped, which
        keeps their green/amber/accent fills intact instead of painting them the
        card's panel colour."""
        if getattr(widget, '_fixed_bg', False): return
        try:
            widget.configure(bg=bg)
        except tk.TclError:
            pass
        for c in widget.winfo_children():
            self._set_bg_recursive(c,bg)

    def _start_badge_pulse(self):
        """Animate the badge background with a subtle breathing effect."""
        badge=self.badge
        colors=[ACCENT,ACCENT_HI]
        state={'i':0,'run':True}
        def _step():
            if not state['run']:
                return
            state['i']=(state['i']+1)%len(colors)
            try:
                badge.configure(bg=colors[state['i']])
                self._pulse_id=self.after(800,_step)
            except tk.TclError:
                state['run']=False
        self._pulse_id=self.after(0,_step)

    def _stop_badge_pulse(self):
        """Stop the badge breathing animation if it is running."""
        if self._pulse_id:
            try:
                self.after_cancel(self._pulse_id)
            except tk.TclError:
                pass
            self._pulse_id=None

    def _show_overlay(self,_event=None):
        s=self.archive.steam
        lines=[]
        if getattr(s,'release_date',''):
            lines.append(f'Release: {s.release_date}')
        if getattr(s,'genres',[]):
            lines.append(f'Genres: {", ".join(s.genres[:3])}')
        if getattr(s,'developer',''):
            lines.append(f'Dev: {s.developer}')
        if self.archive.decision.category:
            lines.append(f'Category: {self.archive.decision.category}')
        self._overlay.configure(text='\n'.join(lines) if lines else 'No preview metadata')
        self._overlay.pack(fill='x',pady=(6,0))

    def _hide_overlay(self,_event=None):
        self._overlay.pack_forget()
    def _bind_widgets(self,w):
        w.bind('<Button-1>',lambda e:self.on_select(self.archive),add='+')
        for c in w.winfo_children(): self._bind_widgets(c)
    def select(self,value):
        self.selected=value; bg=PANEL3 if value else PANEL; border=ACCENT_HI if value else BORDER
        self.configure(bg=bg,highlightbackground=border,highlightthickness=2 if value else 1)
        self._stop_badge_pulse()
        self._set_bg_recursive(self,bg)
    def update_status(self):
        s=self.archive.steam
        self.conf.configure(text='')
        self._stop_badge_pulse()
        if s.found:
            self.title.configure(text=s.name or self.archive.display_name); self.status.configure(text=f'✓  {s.name}  •  AppID {s.appid}',fg=GREEN)
            self.badge.configure(text='MATCHED',bg=GREEN,fg='#071b12')
            self._show_confidence(s)
        else:
            self.status.configure(text='!  Steam match not found',fg=ORANGE if s.reason else MUTED)
            self.badge.configure(text='REVIEW',bg=ORANGE,fg='#211505')
        if self.archive.decision.skipped:
            self.status.configure(text='↷  Skipped — archive will remain untouched',fg=MUTED); self.badge.configure(text='SKIPPED',bg=PANEL3,fg=MUTED)
            # _show_confidence ran a line ago, inside the `if s.found` branch, and this branch runs after it,
            # so a skipped archive that had matched Steam was left showing SKIPPED beside an amber "Medium
            # 0.70". A skipped archive is not being filed under anything, so there is no match to be unsure
            # of and the pill goes - colour as well as text, because an emptied pill that keeps the warning
            # fill paints a warning badge-shaped hole next to the badge. Reset to the construction values.
            self.conf.configure(text='',bg=PANEL,fg=MUTED)
        elif s.found:
            edited=' • edited' if self.archive.decision.changed_from_suggestion else ''
            self.meta.configure(text=f'{self.archive.decision.category}{edited}  •  {self.archive.path.name}',fg=CYAN if edited else MUTED)
        elif not self.archive.decision.skipped:
            # Badge pulse for unreviewed cards: a subtle breathing animation
            # that draws attention to archives needing a decision.
            self._start_badge_pulse()

    def _show_confidence(self,s):
        """The confidence pill: a colour, and the score when there is one.

        Only "High" earns green. Anything else - a Medium match, or one whose confidence was never set at all -
        is amber, because the pill's job is to make a doubtful match look doubtful before it is filed under the
        wrong name. The score is shown when it exists because "Medium" on its own does not say how close the call
        was, and a reader deciding whether to trust it is deciding on exactly that.
        """
        level=(s.confidence or '').strip().casefold()
        score=getattr(s,'score',0) or 0
        text=level.title() if level else 'Unscored'
        if score: text=f'{text} {score:.2f}'
        if level=='high':
            self.conf.configure(text=text,bg=GREEN,fg='#071b12')
        else:
            self.conf.configure(text=text,bg=ORANGE,fg='#211505')


