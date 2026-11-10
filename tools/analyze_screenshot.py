"""Pixel-level screenshot analysis with no third-party dependencies.

The host has no PIL, numpy or tesseract, but Tk 8.6 decodes PNG natively and can return individual pixels, so
a real visual check is possible: sample the region each widget occupies in a captured screenshot, measure how
much content is actually painted there, and confirm the theme colour that region should be showing.

That catches the class of defect geometry cannot see - a panel that laid out correctly but rendered as a flat
block of background, or a themed colour that never reached the screen.

Run directly against captured screenshots:  python3 tools/analyze_screenshot.py shot.png
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui.theme import BG, PANEL, PANEL2, PANEL3, BORDER, ACCENT, ACCENT_HOVER, ACCENT_HI, CYAN, GREEN, ORANGE, RED, TEXT

NAMED = {"white": (255, 255, 255)}


def hex_to_rgb(value):
    if value in NAMED:
        return NAMED[value]
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


# Palette the app is expected to paint. Anything far from all of these means a region rendered off-theme.
PALETTE = {"BG": hex_to_rgb(BG), "PANEL": hex_to_rgb(PANEL), "PANEL2": hex_to_rgb(PANEL2), "PANEL3": hex_to_rgb(PANEL3), "BORDER": hex_to_rgb(BORDER), "ACCENT": hex_to_rgb(ACCENT), "ACCENT_HOVER": hex_to_rgb(ACCENT_HOVER), "ACCENT_HI": hex_to_rgb(ACCENT_HI), "CYAN": hex_to_rgb(CYAN), "GREEN": hex_to_rgb(GREEN), "ORANGE": hex_to_rgb(ORANGE), "RED": hex_to_rgb(RED), "TEXT": hex_to_rgb(TEXT)}


def distance(a, b):
    return sum((int(a[i]) - int(b[i])) ** 2 for i in range(3)) ** 0.5


def nearest_palette_name(rgb_value, tolerance=44):
    best_name, best = None, None
    for name, colour in PALETTE.items():
        d = distance(rgb_value, colour)
        if best is None or d < best:
            best_name, best = name, d
    return best_name if best is not None and best <= tolerance else None


class Shot:
    """A decoded screenshot with sampling helpers."""

    def __init__(self, path):
        root = tk.Tk()
        root.withdraw()
        self._root = root
        self.image = tk.PhotoImage(file=str(path))
        self.width, self.height = self.image.width(), self.image.height()

    def close(self):
        try:
            self._root.destroy()
        except tk.TclError:
            pass

    def pixel(self, x, y):
        value = self.image.get(x, y)
        return tuple(int(part) for part in value[:3]) if isinstance(value, str) else tuple(value)

    def region(self, x, y, w, h, step=2):
        """Histogram of colours in a rectangle, sampled on a grid."""
        counts = Counter()
        x = max(0, int(x))
        y = max(0, int(y))
        x2 = min(self.width, int(x + w))
        y2 = min(self.height, int(y + h))
        for py in range(y, y2, step):
            for px in range(x, x2, step):
                counts[self.pixel(px, py)] += 1
        return counts

    def describe(self, label, x, y, w, h, step=2):
        """Dominant colours plus how much of the region is off-palette (i.e. content or an anomaly)."""
        counts = self.region(x, y, w, h, step)
        total = sum(counts.values())
        if not total:
            return None
        off = 0
        named = Counter()
        for rgb_value, count in counts.items():
            name = nearest_palette_name(rgb_value)
            if name:
                named[name] += count
            else:
                off += count
        dominant = ", ".join(f"{n} {c / total * 100:.0f}%" for n, c in named.most_common(4))
        return {"label": label, "total": total, "off_palette_pct": off / total * 100, "dominant": dominant or "(none matched palette)"}


def scan(path, regions=None):
    shot = Shot(path)
    try:
        print(f"{Path(path).name}: {shot.width}x{shot.height}")
        rows = []
        for label, box in regions or []:
            info = shot.describe(label, *box)
            if info:
                rows.append(info)
        print(f"\n{'region':<26}{'off-palette':>12}  dominant colours")
        for info in rows:
            print(f"{info['label']:<26}{info['off_palette_pct']:11.1f}%  {info['dominant']}")
        blanks = [i["label"] for i in rows if i["off_palette_pct"] < 1.0]
        if blanks:
            print(f"\nWARNING - regions with effectively no rendered content: {', '.join(blanks)}")
        return rows
    finally:
        shot.close()


if __name__ == "__main__":
    # Without explicit regions, report the overall palette mix of the capture.
    target = sys.argv[1] if len(sys.argv) > 1 else "_shot_1_scan.png"
    if not Path(target).is_file():
        print(f"{target} not found")
        sys.exit(2)
    shot = Shot(target)
    try:
        print(f"{target}: {shot.width}x{shot.height}")
        counts = shot.region(0, 0, shot.width, shot.height, step=6)
        total = sum(counts.values())
        named = Counter()
        off = 0
        for rgb_value, count in counts.items():
            name = nearest_palette_name(rgb_value)
            if name:
                named[name] += count
            else:
                off += count
        print(f"\nsampled {total} pixels (step 6)")
        for name, count in named.most_common(14):
            print(f"  {name:<12} {count / total * 100:5.2f}%")
        print(f"  {'off-palette':<12} {off / total * 100:5.2f}%")
    finally:
        shot.close()
