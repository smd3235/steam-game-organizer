import tkinter as tk
from ui.theme import ACCENT_HI,MUTED,PANEL,TEXT,human_size,pill
class MetadataPanel(tk.Frame):
    def __init__(self,parent): super().__init__(parent,bg=PANEL); self.cells=[]
    def show(self,a,copies=None):
        for w in self.winfo_children():w.destroy()
        s=a.steam
        tk.Label(self,text='STEAM DETAILS',bg=PANEL,fg=ACCENT_HI,font=('TkDefaultFont',9,'bold')).pack(anchor='w',padx=14,pady=(9,5))
        identity=tk.Frame(self,bg=PANEL); identity.pack(fill='x',padx=14,pady=(0,5))
        identity.columnconfigure(1,weight=3); identity.columnconfigure(3,weight=1); identity.columnconfigure(5,weight=1); identity.columnconfigure(7,weight=1); identity.columnconfigure(9,weight=1); identity.columnconfigure(11,weight=1)
        vals=[('Steam Title',s.name or 'Unresolved'),('AppID',s.appid or '—'),('Release',s.release_date or '—'),('Confidence',s.confidence or '—'),('Score',f'{s.score:.0%}' if s.score else '—'),('Suggested',a.decision.suggested_category or a.decision.category)]
        for i,(key,value) in enumerate(vals):
            column=i*2
            tk.Label(identity,text=key.upper(),bg=PANEL,fg=MUTED,font=('TkDefaultFont',7,'bold')).grid(row=0,column=column,sticky='w',padx=(0,4))
            tk.Label(identity,text=value,bg=PANEL,fg=TEXT,font=('TkDefaultFont',8),anchor='w').grid(row=0,column=column+1,sticky='ew',padx=(0,9))
        own=int(getattr(a,'size',0) or 0)
        group=list(copies) if copies else [a]
        total=sum(int(getattr(c,'size',0) or 0) for c in group)
        size_text=human_size(own) if own else '—'
        if len(group)>1:
            size_text=f'{size_text}  •  {human_size(total)} across {len(group)} copies'
        rows=[('Genres',', '.join(s.genres) or '—'),('Steam Categories',', '.join(s.categories) or '—')]
        if s.tags: rows.append(('Tags',', '.join(s.tags) or '—'))
        rows.extend([('Source / Developer',f'{s.source or chr(8212)}  •  {s.developer or chr(8212)}'),('Publisher',s.publisher or '—'),('Archive / Detected',f'{a.path.name}  •  {a.normalized_title}'),('Archive Size',size_text)])
        detail=tk.Frame(self,bg=PANEL); detail.pack(fill='x',padx=14,pady=(0,6)); detail.columnconfigure(1,weight=1)
        for row,(key,value) in enumerate(rows):
            tk.Label(detail,text=key.upper(),bg=PANEL,fg=MUTED,font=('TkDefaultFont',7,'bold')).grid(row=row,column=0,sticky='nw',padx=(0,8),pady=2)
            tk.Label(detail,text=value,bg=PANEL,fg=TEXT,font=('TkDefaultFont',8),anchor='w',wraplength=760,justify='left').grid(row=row,column=1,sticky='ew',pady=2)
        if s.source or s.confidence or s.reason:
            trust=tk.Frame(self,bg=PANEL); trust.pack(fill='x',padx=14,pady=(0,6))
            tk.Label(trust,text='MATCH TRUST',bg=PANEL,fg=ACCENT_HI,font=('TkDefaultFont',8,'bold')).pack(anchor='w',pady=(0,4))
            chips=tk.Frame(trust,bg=PANEL); chips.pack(fill='x',pady=(0,4))
            if s.source:
                conf_kind={'High':'good','Medium':'warn','Low':'bad'}.get(s.confidence,'muted') if s.confidence else 'muted'
                pill(chips,s.source,conf_kind).pack(side='left',padx=(0,6))
            if s.confidence:
                conf_kind={'High':'good','Medium':'warn','Low':'bad'}.get(s.confidence,'muted')
                pill(chips,s.confidence,conf_kind).pack(side='left',padx=(0,6))
            if s.score:
                tk.Label(chips,text=f'score {s.score:.0%}',bg=PANEL,fg=TEXT,font=('TkDefaultFont',8)).pack(side='left',padx=(0,6))
            if s.reason:
                tk.Label(trust,text=s.reason,bg=PANEL,fg=MUTED,font=('TkDefaultFont',8),anchor='w',wraplength=400,justify='left').pack(fill='x',pady=(2,0))




