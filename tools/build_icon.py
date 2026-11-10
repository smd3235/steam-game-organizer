"""Renders the app icon into a Windows .ico.

The artwork existed as assets/icon.svg and was only ever going to be rasterized by `rsvg-convert`, which is a
Linux package. So on this machine it was never rendered at all: the desktop shortcut fell back to the default
Python icon, and the icon people saw was a stock interpreter glyph rather than anything to do with this app.

This draws the same design directly, reading every colour from ui.theme rather than repeating hex values. That
is the part worth keeping: the icon is meant to look like the app, and a hardcoded copy of the palette is a
copy that goes stale the next time the theme moves. The palette is imported, so regenerating after a theme
change is the only step needed.

    python tools/build_icon.py

Sizes are the ones Windows actually asks a shortcut or Explorer for. Small ones are rendered by downsampling
from one large master rather than drawn per-size: a 16px icon drawn separately is a different icon, and the
detail that survives at 16px is not the detail that survives at 48.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ui.theme import ACCENT, ACCENT_HI, BG, BORDER, CYAN, GREEN, ORANGE, PANEL2, PANEL3

# What Explorer, taskbar and shortcut renderers request. 256 is the largest any of them pick up.
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

MASTER = 1024          # Drawn once, big, then downsampled. Smooth edges come from here, not from more code.
GRID = 512             # The SVG's own coordinate space, so the numbers below match the original artwork.
OUT = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"


def _rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _vertical_gradient(size, top, bottom):
    """A top-to-bottom gradient, built by hand.

    Image.linear_gradient exists but is 256 rows that then need resizing, and resizing a gradient is how you
    get banding back. One row per output pixel is cheaper and exact.
    """
    strip = Image.new("RGB", (1, size))
    strip.putdata([_lerp(top, bottom, y / (size - 1)) for y in range(size)])
    return strip.resize((size, size))


def _lerp(a, b, t):
    """Blend two colours channel by channel.

    strict=True because every colour here comes from ui.theme as an RGB triple: silently dropping or padding a
    channel would produce a wrong shade rather than an error, which is exactly the drift the palette import
    exists to prevent.
    """
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b, strict=True))


def _fill_shape(canvas, mask_draw, colour):
    """Fill whatever `mask_draw` has drawn on `mask` with a flat colour, through its alpha."""
    canvas.paste(Image.new("RGB", canvas.size, colour), (0, 0), mask_draw)


def build():
    k = MASTER / GRID
    image = Image.new("RGBA", (MASTER, MASTER), (0, 0, 0, 0))

    # Background: the app's panel colour falling away to its page background, so the icon reads as a window.
    bg_gradient = _vertical_gradient(MASTER, _rgb(PANEL3), _rgb(BG))
    mask = Image.new("L", (MASTER, MASTER), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, MASTER - 1, MASTER - 1], radius=int(116 * k), fill=255)
    image.paste(bg_gradient, (0, 0), mask)

    draw = ImageDraw.Draw(image)
    # A hairline inside the edge. Without it the icon has no defined border on a dark desktop and the
    # rounded corners dissolve into the background.
    draw.rounded_rectangle([10 * k, 10 * k, (GRID - 10) * k, (GRID - 10) * k],
                           radius=int(106 * k), outline=_rgb(BORDER) + (140,), width=max(1, int(2 * k)))

    # Folder back, with the raised tab that makes the silhouette read as a folder and not a box.
    back = Image.new("L", (MASTER, MASTER), 0)
    back_draw = ImageDraw.Draw(back)
    tab = [(112, 214), (112, 178), (134, 156), (204, 156), (230, 172), (248, 192), (416, 192), (416, 230)]
    back_draw.polygon([(int(x * k), int(y * k)) for x, y in tab], fill=255)
    back_draw.rounded_rectangle([112 * k, 186 * k, 416 * k, 372 * k], radius=int(22 * k), fill=255)
    _fill_shape(image, back, _rgb(PANEL2))
    draw = ImageDraw.Draw(image)
    draw.line([(int(x * k), int(y * k)) for x, y in tab], fill=_rgb(BORDER) + (255,), width=max(1, int(5 * k)),
              joint="curve")
    draw.rounded_rectangle([112 * k, 186 * k, 416 * k, 372 * k], radius=int(22 * k), outline=_rgb(BORDER) + (255,),
                           width=max(1, int(5 * k)))

    # Game cases going in, drawn over the folder back and under its front, so they sit inside it.
    for x, top, height, colour in ((146, 118, 132, CYAN), (214, 96, 154, GREEN), (282, 126, 124, ORANGE)):
        draw.rounded_rectangle([x * k, top * k, (x + 54) * k, (top + height) * k], radius=int(12 * k),
                               fill=_rgb(colour))
        # A label on each, dark enough to read as a spine rather than a highlight.
        draw.rounded_rectangle([(x + 14) * k, (top + 18) * k, (x + 40) * k, (top + 24) * k], radius=int(3 * k),
                               fill=_rgb(BG) + (90,))

    # Folder front. A trapezoid rather than a rectangle, which is what gives the icon its perspective.
    front = Image.new("L", (MASTER, MASTER), 0)
    ImageDraw.Draw(front).polygon([(int(88 * k), int(236 * k)), (int(424 * k), int(236 * k)),
                                   (int(406 * k), int(406 * k)), (int(106 * k), int(406 * k))], fill=255)
    _fill_shape(image, front, _rgb(ACCENT_HI))
    front_gradient = _vertical_gradient(MASTER, _rgb(ACCENT_HI), _rgb(ACCENT))
    image.paste(front_gradient, (0, 0), front)

    # A bright lip along the top edge of the front, the way light catches a folder's folded edge.
    lip = Image.new("L", (MASTER, MASTER), 0)
    ImageDraw.Draw(lip).polygon([(int(88 * k), int(236 * k)), (int(424 * k), int(236 * k)),
                                 (int(421 * k), int(256 * k)), (int(91 * k), int(256 * k))], fill=255)
    image.paste(Image.new("RGB", image.size, (255, 255, 255)), (0, 0), Image.eval(lip, lambda v: int(v * 0.18)))
    return image


def main():
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        sys.exit("Pillow is required to build the icon: pip install pillow")
    global Image, ImageDraw  # build() uses them by name.

    master = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    master.save(OUT, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"  wrote {OUT}  ({OUT.stat().st_size:,} bytes)")
    with Image.open(OUT) as check:
        got = sorted({s[0] for s in check.info["sizes"]})
        print(f"  sizes embedded: {got}")
        missing = [s for s in SIZES if s not in got]
        if missing:
            sys.exit(f"icon is missing {missing} - Explorer would fall back to another size")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
