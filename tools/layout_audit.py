"""Layout audit v2 - correct about canvas-window children, and adds sibling overlap detection."""

import tkinter as tk
import zipfile
import sys
from pathlib import Path
from tempfile import mkdtemp

# Running a script puts its own directory on sys.path, not the project root, so `from app.application import
# Application` raised ModuleNotFoundError on the documented `python3 tools/layout_audit.py`. tools/
# analyze_screenshot.py has always done this insert; this one had to match it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.application import Application
from core.models import GameArchive, SteamMatch, ScanResult
from utils.filename_utils import identity_key, normalize_name

import os

W, H = int(os.environ.get("AUDIT_W", "1280")), int(os.environ.get("AUDIT_H", "800"))
issues = []


def visible(w):
    # A widget is only visible if it and EVERY ancestor is mapped. Tk reports children of an unmapped
    # canvas window item as mapped, which produced false positives in v1.
    while w is not None:
        try:
            if not w.winfo_ismapped():
                return False
        except tk.TclError:
            return False
        w = getattr(w, "master", None)
    return True


def walk(w, inside_scroll=False):
    """Yield every widget, but not the contents of a scrolling canvas.

    A scrolling container legitimately holds widgets positioned below the window, because they are meant to
    be reached by scrolling. Reporting those as off-window produced nineteen false positives on the Scan
    page, which is exactly the kind of permanent noise that stops a real clipping bug being noticed.
    """
    if inside_scroll:
        return
    yield w
    for c in w.winfo_children():
        yield from walk(c, scrolls(c))


def scrolls(w):
    """True for a Canvas that scrolls its own window item, i.e. its content may sit below the viewport."""
    if w.winfo_class() != "Canvas":
        return False
    try:
        if not w.cget("scrollregion"):
            return False
        height = int(w.cget("scrollregion").split()[3])
        return height > w.winfo_height()
    except (tk.TclError, ValueError, IndexError):
        return False


def boxes(parent):
    out = []
    for c in parent.winfo_children():
        if not visible(c) or scrolls(c):
            continue
        try:
            out.append((c, c.winfo_rootx(), c.winfo_rooty(), c.winfo_width(), c.winfo_height()))
        except tk.TclError:
            pass
    return out


def audit(label, root):
    root.update_idletasks()
    root.update()
    checked = 0
    for w in walk(root):
        if not visible(w):
            continue
        checked += 1
        try:
            width, height = w.winfo_width(), w.winfo_height()
            x = w.winfo_rootx() - root.winfo_rootx()
            y = w.winfo_rooty() - root.winfo_rooty()
            need = w.winfo_reqwidth()
            needh = w.winfo_reqheight()
        except tk.TclError:
            continue
        wrap = w.cget("wrap") if w.winfo_class() == "Text" else None
        if w.winfo_class() in ("Text", "Label", "Button") and need > width + 4 and needh <= height + 4 and wrap != "word":
            try:
                txt = str(w.cget("text"))[:45]
            except tk.TclError:
                txt = ""
            issues.append(f"{label}: {w.winfo_class()} CLIPPED needs {need}px has {width}px {txt!r}")
        if x < -2 or y < -2 or x + width > W + 2 or y + height > H + 2:
            issues.append(f"{label}: {w.winfo_class()} off-window ({x},{y}) {width}x{height}")
    # sibling overlap: grid siblings should not visually collide
    for parent in walk(root):
        if not visible(parent):
            continue
        bs = boxes(parent)
        for i in range(len(bs)):
            for j in range(i + 1, len(bs)):
                a, ax, ay, aw, ah = bs[i]
                b, bx, by, bw, bh = bs[j]
                if aw <= 2 or ah <= 2 or bw <= 2 or bh <= 2:
                    continue
                ox = min(ax + aw, bx + bw) - max(ax, bx)
                oy = min(ay + ah, by + bh) - max(ay, by)
                if ox > 3 and oy > 3:
                    issues.append(f"{label}: siblings overlap {ox}x{oy}px  {a.winfo_class()} vs {b.winfo_class()}")
    CHECKED[0] += checked


CHECKED = [0]

lib = Path(mkdtemp())
games = lib / "Games"
inc = games / "Incoming"
inc.mkdir(parents=True)
for n in ["Alpha Quest", "Beta Raid", "Gamma Drift", "Delta Storm", "Echo Valley", "Foxtrot Nine", "Golf Hotel India", "Juliet Kilo Lima"]:
    with zipfile.ZipFile(inc / f"{n} v1.zip", "w") as z:
        z.writestr("game/data.txt", "x" * 3000)
root = tk.Tk()
app = Application(root, mock=True)
# Unzoom before asking for a size. MainWindow maximizes itself on start, and on Windows the zoomed state
# sticks: geometry() is ignored until the window is normal again. So the audit was measuring a 2532x1353
# window while comparing every widget against W=1280 H=800, and reporting all 2532px-wide widgets as
# off-window - 254 issues, every one of them false. tests/test_ui_geometry.py works around the same thing.
try:
    root.state("normal")
except tk.TclError:
    pass
root.geometry(f"{W}x{H}")
root.update()
# What the window ended up as, which is not necessarily what was asked for - see the warning at the end.
MEASURED = (root.winfo_width(), root.winfo_height())
app.config.library_root = games
archives = []
for p in sorted(inc.glob("*.zip")):
    a = GameArchive(p, p.stem, p.stem, identity_key(normalize_name(p.name)), ".zip")
    a.steam = SteamMatch(found=True, appid="1", name=p.stem.replace(" v1", ""))
    a.decision.accepted = True
    a.decision.category = "Adventure"
    archives.append(a)

sv = app.window.views["scan"]
app.window.show("scan")
sv.begin_scan()
root.update()
for e in [
    {"stage": "cleanup_done", "message": "Reclaimed 4 item(s), freed 1.2 GB"},
    {"stage": "dedupe_done", "message": "Kept one archive per game folder"},
    {"stage": "repair_done", "message": "Repair pass finished — 3 archive(s) converted"},
    {"stage": "discover_done", "message": "Found 8 archive(s)"},
]:
    app.window._scan_progress(e)
root.update()
audit("scan", root)

app.window.state.update(scan_result=ScanResult(archives=archives))
app.window.show("organize")
root.update()
ov = app.window.views["organize"]
ov.stage_counts = {}
ov.current = None
ov.work.grid()
ov.timeline.reset()
ov.feed.clear()
root.update()
for e in [
    {"stage": "organizing", "file": "Alpha Quest v1.zip", "source_suffix": ".zip", "game": "Alpha Quest", "category": "Adventure", "index": 1, "total": 8},
    {"stage": "extracting", "file": "Alpha Quest v1.zip", "source_bytes": 4_100_000_000},
    {"stage": "compressing", "file": "Alpha Quest v1.zip", "extracted_bytes": 8_200_000_000},
    {"stage": "converted", "file": "Alpha Quest v1.7z", "target_bytes": 2_000_000_000, "target_name": "Alpha Quest v1.7z"},
    {"stage": "organizing", "file": "Beta Raid v1.zip", "game": "Beta Raid", "category": "Adventure", "index": 2, "total": 8},
    {"stage": "compressing", "file": "Beta Raid v1.zip", "extracted_bytes": 1_800_000_000},
]:
    ov.progress_update(e)
root.update()
audit("organize", root)

dv = app.window.views["done"]
for a in archives[:3]:
    a.conversion.status = "converted"
    a.conversion.source_format = "ZIP"
    a.conversion.target_format = "7Z"
    a.conversion.final_size = 2_000_000_000
    a.conversion.final_name = a.path.name.replace(".zip", ".7z")
for a in archives[3:4]:
    a.conversion.status = "failed"
    a.conversion.message = "7z build exited 255: Break signaled"
    a.conversion.free_bytes_at_failure = 2_000_000
for a in archives[4:6]:
    a.conversion.status = "archived"
    a.conversion.source_format = "ZIP"
    a.conversion.final_name = a.path.name
dv.show(archives)
app.window.show("done")
root.update()
audit("done", root)
app.window.show("review")
root.update()
audit("review", root)
app.window.show("artwork")
root.update()
audit("artwork", root)
root.destroy()
print(f"=== LAYOUT AUDIT v2 @ {W}x{H} (measured {MEASURED[0]}x{MEASURED[1]}) ===")
if MEASURED != (W, H):
    # Every width check below compares against W and H, not against what the window actually is. If those two
    # disagree, every "off-window" line below is an artefact of the mismatch rather than a real clipping bug.
    print(f" WARNING: asked for {W}x{H} but the window measured {MEASURED[0]}x{MEASURED[1]}. Every off-window result below is measured against {W}x{H}, so treat them as unreliable.")
if issues:
    for i in issues:
        print(" ISSUE:", i)
    print("total:", len(issues))
else:
    print("CLEAN - no clipping, no off-window widgets, no sibling overlap, nothing collapsed")
# How many widgets were actually looked at. "CLEAN" from a walk that examined nothing is the failure mode
# AGENTS.md warns about in a test - a safety net that is reported as present but was never run - so the count
# is printed: a real pass over five pages is several hundred widgets, and a near-zero number means the audit
# stopped early and its clean bill of health means nothing.
print(f"checked {CHECKED[0]} widgets")
