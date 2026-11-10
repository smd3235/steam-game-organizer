import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
import shutil
from .theme import ACCENT_HI,BG,BORDER,CHART_COLORS,CYAN,GREEN,MUTED,ORANGE,PANEL,PANEL2,RED,TEXT,human_duration,human_size,panel,pin_bottom,reveal_staggered,tooltip

# Outcome styling for the run report. Failures are the loudest thing on the screen on purpose: they are the
# only rows the user has to act on, so they must never be scrolled past unnoticed.
CONVERSION_BADGE={
    'converted':('converted to 7Z',GREEN),
    'rebuilt':('rebuilt as 7Z',CYAN),
    'skipped':('left as-is',ORANGE),
    'failed':('FAILED',RED),
    'not_needed':('already correct',MUTED),
    'archived':('filed under Archive/',MUTED),
    'pending':('',MUTED),
}

def badge_for(status):
    """Label for a conversion status. The named sections carry their own wording in their headings, but the
    catch-all NO CONVERSION RESULT section has to describe whatever status it finds, so it reads the label
    from here instead of inventing one. Unknown statuses fall back to the raw status text."""
    return CONVERSION_BADGE.get(status,CONVERSION_BADGE['pending'])

def _saved_bytes(note):
    """Bytes actually reclaimed by one conversion.

    Only meaningful once both sizes are known. A rebuild of an existing .7z has no saving, and a failed or
    skipped conversion saved nothing, so reporting a number there would be inventing one.
    """
    before=int(getattr(note,'source_size',0) or 0); after=int(getattr(note,'final_size',0) or 0)
    return before-after if before>after>0 else 0

def _saved_label(note):
    """Human-readable size delta for one conversion.

    Positive deltas show as 'saved', negative ones as 'expanded by' (an archive that
    grew is worth flagging rather than hiding), and a zero or no-data conversion
    yields nothing — inventing a number there would be worse than silence.
    """
    saved=_saved_bytes(note)
    before=int(getattr(note,'source_size',0) or 0)
    after=int(getattr(note,'final_size',0) or 0)
    if saved>0:
        share=f' ({saved/before:.0%})' if before else ''
        return f'saved {human_size(saved)}{share}'
    if before and after and after>before:
        share=f' ({abs(after-before)/before:.0%})'
        return f'expanded by {human_size(after-before)}{share}'
    return ''

class DoneView(tk.Frame):
    def __init__(self,parent,on_scan,on_undo=None,on_open_library=None,state=None,rollback=None,config=None,on_scan_artwork=None):
        super().__init__(parent,bg=BG); self.on_scan=on_scan; self.on_undo=on_undo; self.on_open_library=on_open_library; self.state=state
        # The rollback service and the library path are asked for directly rather than read off the state
        # snapshot, which never carried them. They used to be pulled out of it with getattr(snap,'config') and
        # getattr(snap,'rollback_pending') - two names AppState has never had, so both silently read None and the
        # screen reported "nothing to undo" and an em dash for the library on every run, including a run with a
        # full journal waiting to be rolled back. That is the one fact on this screen a user comes to check.
        # The whole config is held rather than the one path, because a Path is an immutable snapshot: MainWindow
        # rebinds config.library_root when the Games directory changes and pushes the new value into the scan
        # screen, and a value taken here at construction could never follow it - this screen would name the
        # previous directory and report the previous volume's free space for the rest of the session.
        self.rollback=rollback; self.config=config
        self.columnconfigure(0,weight=1); self.rowconfigure(3,weight=1)
        tk.Label(self,text='DONE',bg=BG,fg=GREEN,font=('TkDefaultFont',9,'bold')).grid(row=0,column=0,sticky='w')
        tk.Label(self,text='Run complete',bg=BG,fg=TEXT,font=('TkDefaultFont',24,'bold')).grid(row=1,column=0,sticky='w')
        self.card=panel(self); self.card.grid(row=2,column=0,sticky='ew',pady=(18,0)); self.card.columnconfigure(0,weight=1)
        
        # Header section with summary and counters
        header_frame=tk.Frame(self.card,bg=PANEL); header_frame.grid(row=0,column=0,sticky='ew',padx=18,pady=(18,8)); header_frame.columnconfigure(0,weight=1)
        self.summary=tk.Label(header_frame,text='No completed run yet.',bg=PANEL,fg=MUTED,font=('TkDefaultFont',11),justify='left',anchor='w',wraplength=980)
        self.summary.grid(row=0,column=0,sticky='ew')
        
        # Counters make a bad run obvious before the user reads a single line of detail.
        counters_frame=tk.Frame(header_frame,bg=PANEL); counters_frame.grid(row=1,column=0,sticky='ew',pady=(8,0))
        self.tiles={}
        for key,label in (('organized','organized'),('converted','converted'),('skipped','skipped'),('failed','failed')):
            tile=tk.Frame(counters_frame,bg=PANEL2,highlightbackground=BORDER,highlightthickness=1)
            tile.pack(side='left',padx=(0,8))
            value=tk.Label(tile,text='0',bg=PANEL2,fg=TEXT,font=('TkDefaultFont',16,'bold'))
            value.pack(padx=14,pady=(8,0))
            tk.Label(tile,text=label,bg=PANEL2,fg=MUTED,font=('TkDefaultFont',7,'bold')).pack(padx=14,pady=(0,6))
            self.tiles[key]=value
        self.body=panel(self); self.body.grid(row=3,column=0,sticky='nsew',pady=(12,0))
        self.body.columnconfigure(0,weight=1); self.body.rowconfigure(0,weight=1); self.body.columnconfigure(1,weight=0)
        # A run of any size left most of this panel blank, because the per-game report is a narrow column of
        # text in a very wide box. A side rail carries the facts that belong to the run as a whole - how long
        # it took, what it cost in disk, whether it can be undone - plus the category split as real bars.
        # Rail is responsive: minimum 200px, grows with content, never exceeds 35% of body width.
        rail_container=tk.Frame(self.body,bg=PANEL); rail_container.grid(row=0,column=1,sticky='ns',padx=(0,14)); rail_container.grid_propagate(False)
        self.rail=tk.Frame(rail_container,bg=PANEL); self.rail.pack(fill='both',expand=True)
        self.rail.configure(width=220)  # initial; will adapt via <Configure>
        self.body.bind('<Configure>',self._adapt_rail)
        
        # RUN FACTS section
        facts_header=tk.Frame(self.rail,bg=PANEL); facts_header.pack(fill='x',pady=(0,4))
        tk.Frame(facts_header,bg=BORDER,height=1).pack(fill='x',padx=0,pady=(0,0))
        tk.Label(facts_header,text='RUN FACTS',bg=PANEL,fg=ACCENT_HI,font=('TkDefaultFont',9,'bold')).pack(anchor='w',pady=(0,4))
        self.facts={}
        for key,title in (('duration','Duration'),('compressed','Converted'),('saved','Space saved'),('free','Free space'),('undo','Undo available'),('where','Library')):
            row=tk.Frame(self.rail,bg=PANEL); row.pack(fill='x',pady=2)
            tk.Label(row,text=title,bg=PANEL,fg=MUTED,font=('TkDefaultFont',8)).pack(side='left')
            value=tk.Label(row,text='—',bg=PANEL,fg=TEXT,font=('TkDefaultFont',8,'bold'),anchor='e'); value.pack(side='right')
            self.facts[key]=value
        tk.Frame(self.rail,bg=BORDER,height=1).pack(fill='x',pady=(12,10))
        
        # BY CATEGORY section
        category_header=tk.Frame(self.rail,bg=PANEL); category_header.pack(fill='x',pady=(0,6))
        tk.Label(category_header,text='BY CATEGORY',bg=PANEL,fg=CYAN,font=('TkDefaultFont',9,'bold')).pack(anchor='w',pady=(0,6))
        self.bars=tk.Frame(self.rail,bg=PANEL); self.bars.pack(fill='both',expand=True)
        self.details=tk.Text(self.body,bg=PANEL,fg=TEXT,relief='flat',wrap='word',bd=0,padx=16,pady=12,spacing1=1,spacing3=2)
        self.details.grid(row=0,column=0,sticky='nsew'); self.details.configure(state='disabled')
        self.details.tag_configure('heading',foreground=ACCENT_HI,font=('TkDefaultFont',9,'bold'),spacing1=10,spacing3=6)
        self.details.tag_configure('fail',foreground=RED)
        self.details.tag_configure('warn',foreground=ORANGE)
        self.details.tag_configure('good',foreground=GREEN)
        self.details.tag_configure('dim',foreground=MUTED)
        self.details.tag_configure('path',foreground=MUTED,font=('TkDefaultFont',8))
        self.details.tag_configure('file',foreground=CYAN,font=('TkDefaultFont',8))
        for sequence in ('<MouseWheel>','<Button-4>','<Button-5>'): self.details.bind(sequence,self._wheel,add='+')
        actions=tk.Frame(self,bg=BG); actions.grid(row=4,column=0,sticky='ew',pady=18)
        self.undo_btn=ttk.Button(actions,text='UNDO LAST ORGANIZATION',style='Danger.TButton',command=on_undo); self.undo_btn.pack(side='left')
        if on_scan_artwork:
            b=ttk.Button(actions,text='NEW + ARTWORK  ›',style='Secondary.TButton',command=on_scan_artwork); b.pack(side='right',padx=(0,6)); tooltip(b, 'Start a new scan and download artwork')
        b_scan=ttk.Button(actions,text='START ANOTHER SCAN  ›',style='Primary.TButton',command=on_scan); b_scan.pack(side='right'); tooltip(b_scan, 'Begin a new scan of your Games directory')
        b_lib=ttk.Button(actions,text='Open Library Folder',style='Secondary.TButton',command=self._open_library); b_lib.pack(side='left',padx=10); tooltip(b_lib, 'Open your Games directory in Explorer')
        b_save=ttk.Button(actions,text='Save Run Report',style='Secondary.TButton',command=self._export_report); b_save.pack(side='left',padx=10); tooltip(b_save, 'Export this run report to a text file')
        tooltip(self.undo_btn, 'Reverse the last organization run')
        self._last_archives=[]
        reveal_staggered(list(self.tiles.values()) + [self.card], self, stagger=100)

    def _open_library(self):
        if self.on_open_library:self.on_open_library()

    def _adapt_rail(self,event=None):
        """Adjust rail width to content, clamped between 200px and 35% of body width."""
        try:
            body_w=self.body.winfo_width()
            if body_w>100:
                max_w=int(body_w*0.35)
                # Measure rail content width
                self.rail.update_idletasks()
                content_w=self.rail.winfo_reqwidth()
                target=min(max(content_w,200),max_w)
                self.rail.configure(width=target)
        except tk.TclError:
            pass

    def _paint_facts(self,archives,converted,failed):
        """Run-level numbers, kept out of the scrolling report so the outcome list stays scannable."""
        state=getattr(self,'state',None); snap=state.get() if state is not None else None
        seconds=float(getattr(snap,'run_seconds',0) or 0)
        self.facts['duration'].configure(text=human_duration(seconds) if seconds>0 else 'not recorded')
        written=sum(int(getattr(getattr(a,'conversion',None),'final_size',0) or 0) for a in converted)
        # Only conversions that actually shrank count towards both the saving and its share; adding every
        # source size would mix in archives that were rebuilt at the same size and understate the percentage.
        shrunk=[a for a in converted if _saved_bytes(getattr(a,'conversion',None))>0]
        total_saved=sum(_saved_bytes(getattr(a,'conversion',None)) for a in shrunk)
        total_before=sum(int(getattr(getattr(a,'conversion',None),'source_size',0) or 0) for a in shrunk)
        self.facts['compressed'].configure(text=human_size(written) if written else 'none')
        if total_saved>0 and total_before>0:
            self.facts['saved'].configure(text=f'{human_size(total_saved)}  ({total_saved/total_before:.0%})',fg=GREEN)
        else:
            self.facts['saved'].configure(text='none' if converted else '—',fg=MUTED)
        library=self.config.library_root if self.config is not None else None
        root=Path(library) if library else None
        free=0
        if root:
            try: free=shutil.disk_usage(str(root)).free
            except OSError: free=0
        self.facts['free'].configure(text=human_size(free) if free else '—',fg=RED if free and free<5*1024**3 else TEXT)
        # Read the journal rather than a remembered count: undo_last() consumes it, so the file is the only
        # thing that cannot disagree with what the button would actually do. No handler around it, because
        # a caught failure turned into pending=0 and the row then rendered "nothing to undo" - the one
        # statement this row exists not to make. _rows() already treats an unreadable journal as an empty
        # one, and it logs when the file is there and cannot be read, so the answer is deliberate here.
        pending=self.rollback.pending_count() if self.rollback is not None else 0
        self.facts['undo'].configure(text=f'{pending} move(s)' if pending else 'nothing to undo',fg=ORANGE if pending else MUTED)
        self.undo_btn.configure(state='normal' if pending else 'disabled')
        self.facts['where'].configure(text=str(root) if root else '—',fg=MUTED)

    def _paint_bars(self,cats):
        """Category split as proportional bars. A single dim sentence listing counts made a twenty-game run
        and a two-game run look identical; the shape of the distribution is the point of the section."""
        for child in self.bars.winfo_children(): child.destroy()
        if not cats:
            tk.Label(self.bars,text='No organized games yet.',bg=PANEL,fg=MUTED,font=('TkDefaultFont',8),anchor='w').pack(anchor='w'); return
        ordered=sorted(cats.items(),key=lambda item:(-item[1],item[0]))
        top=max(count for _,count in ordered) or 1
        palette=CHART_COLORS
        track=208
        for index,(name,count) in enumerate(ordered):
            row=tk.Frame(self.bars,bg=PANEL); row.pack(fill='x',pady=3)
            head=tk.Frame(row,bg=PANEL); head.pack(fill='x')
            bar_color=palette[index%len(palette)]
            tk.Label(head,text=name,bg=PANEL,fg=bar_color,font=('TkDefaultFont',8)).pack(side='left')
            tk.Label(head,text=str(count),bg=PANEL,fg=TEXT,font=('TkDefaultFont',8,'bold')).pack(side='right')
            lane=tk.Frame(row,bg=PANEL2,height=6); lane.pack(fill='x',pady=(2,0)); lane.pack_propagate(False)
            width=max(2,int(round(track*count/top)))
            tk.Frame(lane,bg=palette[index%len(palette)],width=width,height=6).pack(side='left',fill='y')

    def _export_report(self):
        """Writes the whole run report to a text file. When something goes wrong after the fact, the on-screen
        report is gone with the window and the log is not organised by game, so this is the artifact worth
        keeping before reporting a problem."""
        archives=self._last_archives
        if not archives:
            messagebox.showinfo('Nothing to save','This run has no completed work to write out yet.',parent=self.winfo_toplevel()); return
        default=f'organizer-run-{datetime.datetime.now().strftime("%Y%m%d-%H%M%S")}.txt'
        target=filedialog.asksaveasfilename(parent=self.winfo_toplevel(),title='Save run report',defaultextension='.txt',initialfile=default,filetypes=[('Text file','*.txt'),('All files','*')])
        if not target: return
        try:
            Path(target).write_text(self.details.get('1.0','end'),encoding='utf-8')
        except OSError as exc:
            messagebox.showerror('Could not save report',f'{target}\n\n{exc}',parent=self.winfo_toplevel()); return
        # The details Text is read-only, so writing straight into it silently did nothing; re-enable it for
        # the confirmation or the user gets no evidence the save happened.
        self.details.configure(state='normal')
        self._write(f'\nReport saved to {target}\n','muted')
        pin_bottom(self.details)
        self.details.configure(state='disabled')

    def _wheel(self,event):
        self.details.yview_scroll(-1 if getattr(event,'delta',0)>0 or getattr(event,'num',0)==4 else 1,'units'); return 'break'

    def _write(self,text,tag=''):
        if tag: self.details.insert('end',text,tag)
        else: self.details.insert('end',text)

    def show(self,archives):
        self._last_archives=list(archives or [])
        accepted=[a for a in archives if a.decision.accepted]
        skipped=[a for a in archives if not a.decision.accepted and a.decision.skipped]
        not_accepted=[a for a in archives if not a.decision.accepted and not a.decision.skipped]

        failed=[]; converted=[]; left_as_is=[]; already=[]; archived=[]; pending=[]
        for archive in accepted:
            status=getattr(getattr(archive,'conversion',None),'status','pending')
            if status=='failed': failed.append(archive)
            elif status in ('converted','rebuilt'): converted.append(archive)
            elif status=='skipped': left_as_is.append(archive)
            elif status=='not_needed': already.append(archive)
            # A duplicate deliberately filed into Archive/ is a completed outcome and gets its own
            # section; only archives that never reached a conversion decision are genuinely pending.
            elif status=='archived': archived.append(archive)
            # Anything else means an accepted archive reached the end of a run with no recorded outcome.
            # Those used to fall through every bucket: counted as organized, shown in BY CATEGORY, but
            # never named, so the run looked finished while silently hiding work.
            else: pending.append((archive,status))

        artwork=sum(1 for a in accepted if a.artwork.present())
        links=sum(1 for a in accepted if a.steam.appid)
        # An accepted archive counts as organized only if it actually got filed. A game whose move failed - a
        # file open in Explorer, a permission the library does not grant - is handed back to this screen so it
        # can be named, and counting it as organized would report a game the run never placed.
        organized=[a for a in accepted if getattr(getattr(a,'conversion',None),'status','')!='failed']
        # Duplicates filed into Archive/ are accepted archives, so they are part of the organized count;
        # naming them separately stops that total from implying every one of them became a game folder.
        archived_note=f'  •  {len(archived)} duplicate(s) filed under Archive/' if archived else ''
        outcome='Completed with problems' if failed else ('Organized' if accepted else 'Nothing to do')
        color=RED if failed else (GREEN if accepted else MUTED)
        self.summary.configure(text=f'{len(organized)} game(s) organized  •  {artwork} artwork copied  •  {links} Steam links created  •  {len(skipped)} skipped{archived_note}',fg=color)
        self.summary_heading=outcome
        for key,value in (('organized',len(organized)),('converted',len(converted)),('skipped',len(left_as_is)+len(skipped)),('failed',len(failed))):
            self.tiles[key].configure(text=str(value),fg=RED if key=='failed' and value else (ORANGE if key=='skipped' and value else TEXT))

        self._paint_facts(archives,converted,failed)
        if not archives: self._paint_bars({})
        self.details.configure(state='normal'); self.details.delete('1.0','end')
        if not archives:
            self._write('No archives were processed in this run.\n','dim')
        # Failures first, so a broken run cannot be mistaken for a clean one by scrolling.
        if failed:
            self._write(f'FAILED  ({len(failed)})\n','heading')
            for archive in failed:
                note=archive.conversion
                self._write(f'  ✗ {archive.steam.name or archive.display_name}\n','fail')
                self._write(f'      {note.message or "conversion failed"}\n','fail')
                self._write(f'      {note.final_name or archive.path.name}',''); self._write('\n','file')
                if note.source_format: self._write(f'   was {note.source_format}   •   ',''); self._write(f'{human_size(note.final_size)}\n','path')
                if note.free_bytes_at_failure: self._write(f'   free disk space when it failed: {human_size(note.free_bytes_at_failure)}\n','path')
                if archive.organized_path: self._write(f'   {archive.organized_path}\n','path')
                self._write('\n')
        if left_as_is:
            self._write(f'LEFT AS-IS  ({len(left_as_is)}) — not converted\n','heading')
            for archive in left_as_is:
                note=archive.conversion
                self._write(f'  ! {archive.steam.name or archive.display_name} — {note.message or "left unchanged"}\n','warn')
        if converted:
            self._write(f'CONVERTED TO 7Z  ({len(converted)})\n','heading')
            for archive in converted:
                note=archive.conversion
                self._write(f'  ✓ {archive.steam.name or archive.display_name}  ','')
                self._write(f'{note.source_format} → {note.target_format}  {human_size(note.final_size)}\n','good')
                # Per-game saving is the number people actually want: "this one got smaller by 1.2 GB".
                saved=_saved_label(note)
                if saved: self._write(f'      {saved}\n', 'warn' if saved.startswith('expanded') else 'good')
                if archive.organized_path: self._write(f'      {archive.organized_path}\n','path')
        if already:
            self._write(f'ALREADY CORRECT  ({len(already)}) — no rebuild needed\n','heading')
            for archive in already:
                self._write(f'  ✓ {archive.steam.name or archive.display_name}\n','dim')
        if archived:
            self._write(f'ARCHIVED AS DUPLICATE  ({len(archived)}) — filed under Archive/\n','heading')
            for archive in archived:
                note=archive.conversion
                self._write(f'  ▪ {archive.steam.name or archive.display_name}  ','')
                self._write(f'{note.source_format or "archive"} kept as-is\n','dim')
                if note.final_name: self._write(f'      Archive/{note.final_name}\n','path')
        if pending:
            self._write(f'NO CONVERSION RESULT  ({len(pending)}) — outcome was never recorded\n','heading')
            for archive,status in pending:
                note=getattr(archive,'conversion',None)
                label=badge_for(status)[0]
                self._write(f'  ○ {archive.steam.name or archive.display_name}  ','')
                self._write(f'{label or status}\n','warn')
                if note and note.message: self._write(f'      {note.message}\n','warn')
        if accepted:
            cats={}
            for archive in accepted: cats[archive.decision.category]=cats.get(archive.decision.category,0)+1
            self._paint_bars(cats)
        if skipped:
            self._write(f'SKIPPED BY YOU  ({len(skipped)})\n','heading')
            for archive in skipped: self._write(f'  ↷ {archive.display_name}\n','dim')
        if not_accepted:
            self._write(f'NOT ACCEPTED  ({len(not_accepted)})\n','heading')
            for archive in not_accepted: self._write(f'  ○ {archive.display_name}\n','dim')
        self.details.configure(state='disabled')


