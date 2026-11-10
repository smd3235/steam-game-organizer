"""Dead-space audit.

Measures how much of each panel's area is not covered by any child widget. A large uncovered region is either
genuinely wasted space (a place to show more information) or a layout that is not filling its container, and
the two are worth telling apart.

Run directly:  python3 tools/dead_space_audit.py
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from tempfile import mkdtemp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tkinter as tk

from app.application import Application
from core.models import GameArchive, ScanResult, SteamMatch
from utils.filename_utils import identity_key, normalize_name

WIDTH, HEIGHT = 1280, 800


def descendants(widget):
    yield widget
    for child in widget.winfo_children():
        yield from descendants(child)


def fully_mapped(widget):
    current = widget
    while current is not None:
        try:
            if not current.winfo_ismapped():
                return False
        except tk.TclError:
            return False
        current = getattr(current, "master", None)
    return True


def container_for(widget):
    """The panel that actually encloses a widget.

    Views hand out their inner Text/Canvas directly, but a leaf widget is trivially 100% covered by itself, so
    measuring it says nothing. Ascend to the enclosing panel, whose children are what fill or waste the space.
    """
    if widget.winfo_class() in ("Text", "Canvas", "Label", "Button", "TButton", "Entry", "TEntry"):
        parent = getattr(widget, "master", None)
        if parent is not None and parent.winfo_class() not in ("Tk", "Toplevel"):
            return parent
    return widget


def coverage(panel, root, step=8):
    """Fraction of a panel covered by leaf widgets.

    Uses an explicit cell grid rather than sampling a set of points: filling with a hash set only works if the
    fill lattice and the sample lattice coincide, and they silently do not once widget offsets are odd.
    """
    width, height = panel.winfo_width(), panel.winfo_height()
    if width <= 0 or height <= 0:
        return 0.0, 0
    cols, rows = max(1, -(-width // step)), max(1, -(-height // step))
    grid = bytearray(cols * rows)
    px, py = panel.winfo_rootx() - root.winfo_rootx(), panel.winfo_rooty() - root.winfo_rooty()
    for widget in descendants(panel):
        if widget is panel or not fully_mapped(widget):
            continue
        # An empty plain Frame is decoration, not content; a Text/Canvas is content even with no children.
        if not widget.winfo_children() and widget.winfo_class() in ("Frame", "TFrame"):
            continue
        w, h = widget.winfo_width(), widget.winfo_height()
        if w <= 1 or h <= 1:
            continue
        x = widget.winfo_rootx() - root.winfo_rootx() - px
        y = widget.winfo_rooty() - root.winfo_rooty() - py
        c0, c1 = max(0, x // step), min(cols - 1, (x + w - 1) // step)
        r0, r1 = max(0, y // step), min(rows - 1, (y + h - 1) // step)
        for row in range(r0, r1 + 1):
            base = row * cols
            for col in range(c0, c1 + 1):
                grid[base + col] = 1
    return sum(grid) / len(grid), width * height


def report(label, root, panels):
    print(f"\n=== {label} ===")
    print(f"{'panel':<30}{'area':>9}{'covered':>9}{'empty':>9}")
    for name, widget in panels:
        panel = container_for(widget)
        pct, area = coverage(panel, root)
        if area <= 0:
            continue
        flag = "  <-- room to use" if pct < 0.55 and area > 20000 else ""
        print(f"{name:<30}{area:>9}{pct * 100:8.1f}%{(1 - pct) * 100:8.1f}%{flag}")
        if widget.winfo_class() == "Text":
            filled = widget.index("end-1c").split(".")[0]
            lines = int(filled) + 1
            visible = max(1, int(widget.winfo_height() / 15))
            print(f"{'':<30}text content: {lines} line(s), ~{visible} visible" + ("   <-- underfilled" if lines < visible else ""))


def build():
    library = Path(mkdtemp()) / "Games"
    incoming = library / "Incoming"
    incoming.mkdir(parents=True)
    archives = []
    for name in ["Alpha Quest", "Beta Raid", "Gamma Drift", "Delta Storm", "Echo Valley", "Foxtrot Nine"]:
        path = incoming / f"{name} v1.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("game/data.txt", "x" * 4000)
        item = GameArchive(path, path.stem, path.stem, identity_key(normalize_name(path.name)), ".zip")
        item.steam = SteamMatch(found=True, appid="1", name=name, confidence="High", source="steam_search")
        item.decision.accepted = True
        item.decision.category = "Adventure"
        archives.append(item)
    root = tk.Tk()
    app = Application(root, mock=True)
    root.geometry(f"{WIDTH}x{HEIGHT}")
    root.update()
    app.config.library_root = library
    app.window.state.update(scan_result=ScanResult(archives=archives))
    return root, app, archives


def main():
    root, app, archives = build()
    try:
        window = app.window
        scan = window.views["scan"]
        window.show("scan")
        scan.begin_scan()
        root.update()
        for event in ({"stage": "cleanup_done", "message": "Reclaimed 4 item(s), freed 1.2 GB"}, {"stage": "discover_done", "message": "Found 6 archive(s)"}):
            window._scan_progress(event)
        root.update()
        report("SCAN", root, [("scan activity", scan.activity), ("live data", scan.dash), ("api", scan.api), ("config strip", scan.library.master)])

        organize = window.views["organize"]
        window.show("organize")
        root.update()
        organize.stage_counts = {}
        organize.current = None
        organize.work.grid()
        organize.timeline.reset()
        organize.feed.clear()
        root.update()
        for event in (
            {"stage": "organizing", "file": "Alpha Quest v1.zip", "game": "Alpha Quest", "index": 1, "total": 6},
            {"stage": "converting" if False else "compressing", "file": "Alpha Quest v1.zip"},
        ):
            organize.progress_update(event)
        root.update()
        report("ORGANIZE", root, [("work panel", organize.work), ("plan list", organize.list)])

        done = window.views["done"]
        for item in archives[:3]:
            item.conversion.status = "converted"
            item.conversion.source_format = "ZIP"
            item.conversion.target_format = "7Z"
            item.conversion.final_size = 2_000_000_000
            item.conversion.final_name = item.path.name.replace(".zip", ".7z")
        done.show(archives)
        window.show("done")
        root.update()
        report("DONE", root, [("details", done.details)])

        review = window.views["review"]
        window.show("review")
        root.update()
        review.archives = archives
        report("REVIEW", root, [("detail pane", review.detail)])

        artwork = window.views["artwork"]
        window.show("artwork")
        root.update()
        artwork.show(archives)
        window.show("artwork")
        root.update()
        report("ARTWORK", root, [("artwork list", getattr(artwork, "list", None) or artwork)])
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


if __name__ == "__main__":
    main()
