# CustomTkinter Migration Plan

## Goal
Replace Tkinter with CustomTkinter across all UI screens to give the app a modern
dark-mode-first look with rounded corners, hover effects, and smooth DPI scaling.

## Migration Strategy

CustomTkinter widgets can coexist with Tkinter widgets in the same process, but NOT
reliably in the same top-level window (visual glitches occur). Therefore we migrate
one screen (toplevel window) at a time.

## Screen Migration Order (simplest to most complex)

| Order | Screen | File | Complexity | Notes |
|-------|--------|------|------------|-------|
| 1 | Setup Wizard | `ui/setup_window.py` | Low | Simple form, 3 fields, 3 buttons |
| 2 | Extract Result | `ui/extract_result_window.py` | Low | Simple dialog, progress bar, result display |
| 3 | Extract Progress | `ui/extract_result_window.py` | Low | Progress dialog (same file) |
| 4 | Add Category | `ui/review_view.py` | Low | Small dialog within review screen |
| 5 | Done | `ui/done_view.py` | Medium | Results page with status badges |
| 6 | Artwork | `ui/artwork_view.py` | Medium | Grid of artwork cards with canvas |
| 7 | Batch Extract | `ui/batch_extract_window.py` | Medium | Table with treeview |
| 8 | Review | `ui/review_view.py` | High | Complex multi-panel layout |
| 9 | Scan | `ui/scan_view.py` | High | Complex layout with progress bars |
| 10 | Organize | `ui/organize_view.py` | High | Complex live updating panel |

## Widget Mapping

| Tkinter/ttk | CustomTkinter | Notes |
|-------------|---------------|-------|
| `tk.Tk` | `CTk` | Main application window |
| `tk.Toplevel` | `CTkToplevel` | Popup windows |
| `tk.Frame` | `CTkFrame` | Container with rounded corners |
| `tk.Label` | `CTkLabel` | Text label |
| `tk.Button` / `ttk.Button` | `CTkButton` | Styled button with hover |
| `tk.Entry` / `ttk.Entry` | `CTkEntry` | Text input |
| `ttk.Combobox` | `CTkComboBox` | Dropdown |
| `ttk.Scrollbar` | `CTkScrollbar` | Themed scrollbar |
| `tk.Text` | `CTkTextbox` | Multi-line text |
| `tk.Checkbutton` / `ttk.Checkbutton` | `CTkCheckBox` | Checkbox |
| `tk.Radiobutton` | `CTkRadioButton` | Radio button |
| `ttk.Progressbar` | `CTkProgressBar` | Progress bar |
| `tk.Canvas` | `CTkCanvas` | Drawing canvas |

## Colour Mapping

CustomTkinter uses `fg_color`, `text_color`, `hover_color`, `border_color` instead of
Tkinter's `bg`, `fg`, `highlightbackground`, etc.

| Tkinter | CustomTkinter |
|---------|---------------|
| `bg=PANEL` | `fg_color=PANEL` |
| `fg=TEXT` | `text_color=TEXT` |
| `highlightbackground=BORDER` | `border_color=BORDER` |
| `highlightthickness=1` | `border_width=1` |
| `borderwidth=0` | `border_width=0` |

## Implementation Steps Per Screen

1. Change import: `from ui.theme import ...` → `from ui.custom_theme import ...`
2. Replace class inheritance: `tk.Frame` → `CTkFrame`, `tk.Toplevel` → `CTkToplevel`
3. Replace widget constructors: `tk.Label(...)` → `CTkLabel(...)`, etc.
4. Replace style configuration: Remove `ttk.Style.configure(...)` calls (CustomTkinter
   handles styling via widget kwargs)
5. Replace `.pack()`, `.grid()`, `.place()` calls (same API, works identically)
6. Replace `.configure(bg=..., fg=...)` with `.configure(fg_color=..., text_color=...)`
7. Test the screen independently

## Quick Win Checklist

- [ ] Install customtkinter (done)
- [ ] Create `ui/custom_theme.py` (done)
- [ ] Create migration plan (done)
- [ ] Migrate `setup_window.py` to CustomTkinter
- [ ] Migrate `extract_result_window.py` to CustomTkinter
- [ ] Add dark mode toggle to MainWindow
- [ ] Add async scanning (asyncio.to_thread for 7z operations)
- [ ] Add keyboard shortcuts (Ctrl+O library, Ctrl+E extract, etc.)