"""Capture one PNG per screen of the app into docs/screenshots/ for the README.

Capturing a screen needs three things this script supplies and nothing else in the project does:
the app's real windows (not a mock of them), pixel data (`PIL.ImageGrab`), and a safe place to run
them. So it builds the actual `Application` over a throwaway sandbox project root, seeds it with
fictional games, drives each view into a realistic state, and grabs the window's client area.

    python tools\\capture_screens.py                     # every screen into docs/screenshots/
    python tools\\capture_screens.py --only review done  # just those screens
    python tools\\capture_screens.py --size 1440x900 --out docs/screenshots
    python tools\\capture_screens.py --keep-sandbox      # leave the temp library for inspection
    python tools\\capture_screens.py --ocr               # also OCR-verify each captured screen

Two kinds of screen are captured. Tk windows are grabbed from the live app (`ImageGrab`), while the
generated `Game Library.html` catalog is a browser page, so it is rendered by headless Microsoft Edge
(`--screenshot` + `--virtual-time-budget`) rather than by Tk.

The working library is created under `temp/` in this repository, never in `%TEMP%`: AGENTS.md requires
scratch files to stay in the project, and the default output is the committed `docs/screenshots/` gallery.

Rules this script obeys, because a screenshot is an artifact like any other:
- The developer's real `config/`, `cache/` and `logs/` are never written: `Application` is built with
  an `AppConfig` rooted in a temp folder, exactly as `tests/tk_support.py:sandbox_app` does for tests.
- Every PNG is written to a `.tmp` and `os.replace`d into place, so an interrupted run cannot leave a
  half-written image that looks like a screenshot.
- A flat capture (one colour, no widgets painted) is reported as a failure, not accepted as an image.
  That is what a grab of an unmapped/occluded window returns, and it is indistinguishable from a blank
  panel by eye at small sizes.
- Screenshots are output for the README, so they are expected to be kept; this is the one place the
  "delete every screenshot" rule does not apply, and the default output folder says so.

Environment requirements: an interactive Windows desktop. `ImageGrab` reads the composited screen, so
a session with no visible desktop (a service, a locked RDP session) cannot capture anything.

When --ocr is given, each captured PNG is also run through Tesseract OCR to verify expected UI text
is present and no Python error dialogs / traceback windows are visible. OCR results are reported
alongside capture results; missing required text or forbidden error text is a failure.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent

from PIL import Image, ImageDraw, ImageFont, ImageGrab, ImageStat, ImageOps

import app.application as application
from core.catalog_utils import asset_prefix
from core.config import AppConfig
from core.models import ArtworkResult, GameArchive, ScanResult, SteamMatch
from utils.filename_utils import identity_key, normalize_name

# Expected UI header text per screen for OCR verification (matches tools/ocr_test.py)
OCR_SCREEN_HEADERS: dict[str, list[str]] = {
    "scan": ["STEAM GAME ORGANIZER", "SCAN"],
    "scan-running": ["STEAM GAME ORGANIZER", "SCAN"],
    "review": ["STEAM GAME ORGANIZER", "GAME REVIEW"],
    "review-category": ["STEAM GAME ORGANIZER", "GAME REVIEW"],
    "add-category": ["STEAM GAME ORGANIZER"],
    "organize": ["STEAM GAME ORGANIZER", "ORGANIZE"],
    "artwork": ["STEAM GAME ORGANIZER", "ARTWORK"],
    "catalog": ["STEAM GAME ORGANIZER"],
    "done": ["STEAM GAME ORGANIZER", "DONE"],
    "setup": ["STEAM GAME ORGANIZER"],
    "batch-extract": ["STEAM GAME ORGANIZER", "EXTRACT"],
    "extract-progress": ["STEAM GAME ORGANIZER", "EXTRACT"],
    "extract-result": ["STEAM GAME ORGANIZER", "EXTRACT"],
}

OCR_FORBIDDEN = [
    "traceback", "raise systemexit", "filenotfounderror", "modulenotfounderror",
    "permissionerror", "keyerror", "indexerror", "typeerror", "valueerror",
    "attributeerror", "importerror", "oserror", "runtimeerror",
    "python.exe", "pythonw.exe", "unhandled exception", "fatal error",
]


def _ocr_check(image_path: Path, screen_name: str) -> tuple[list[str], list[str], list[str], float]:
    """Run OCR on a captured image and return (found_required, missing_required, found_forbidden, confidence)."""
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    except ImportError:
        return [], [], ["pytesseract_not_installed"], 0.0

    try:
        image = Image.open(image_path)
    except Exception as exc:
        return [], [], [f"cannot_open_image: {exc}"], 0.0

    try:
        gray = ImageOps.grayscale(image)
        w, h = gray.size
        if w < 1400:
            scale = 1400 / w
            gray = gray.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        gray = ImageOps.autocontrast(gray, cutoff=1)
    except Exception:
        pass

    best_text = ""
    best_confidence = 0.0
    for psm in [6, 11, 12]:
        try:
            data = pytesseract.image_to_data(
                gray,
                output_type=pytesseract.Output.DICT,
                config=f"--psm {psm}",
            )
            words = []
            confs = []
            for i, conf in enumerate(data["conf"]):
                if conf > 0 and data["text"][i].strip():
                    words.append(data["text"][i])
                    confs.append(conf)
            text = " ".join(words)
            conf = sum(confs) / len(confs) if confs else 0.0
            score = len(words) * (conf / 100)
            if score > len(best_text.split()) * (best_confidence / 100):
                best_text = text
                best_confidence = conf
        except Exception:
            continue

    text_lower = " ".join(best_text.split()).lower()
    found_required: list[str] = []
    missing_required: list[str] = []
    for header in OCR_SCREEN_HEADERS.get(screen_name, []):
        header_words = header.lower().split()
        if len(header_words) == 1:
            if header.lower() in text_lower:
                found_required.append(header)
            else:
                missing_required.append(header)
        else:
            if all(w in text_lower for w in header_words):
                found_required.append(header)
            else:
                missing_required.append(header)

    found_forbidden: list[str] = []
    for forb in OCR_FORBIDDEN:
        if forb in text_lower:
            found_forbidden.append(forb)

    return found_required, missing_required, found_forbidden, best_confidence

# Fictional games only. A screenshot shipped in a public repository must not show somebody's real
# library, so every name, AppID and category here is invented.
GAMES = [
    ("Sir Beats Alot", "901001", "Action", ["Action", "Indie"], ["Single-player", "Steam Achievements", "Full controller support"], "A rhythm-brawler about a knight who fights to a beat.", ("#1b2838", "#2a6f97")),
    ("Nebula Online", "901002", "RPG", ["Massively Multiplayer", "RPG"], ["Multi-player", "PvP", "Steam Cloud"], "A cooperative space opera across a dying cluster of stars.", ("#1a1a2e", "#7b2cbf")),
    ("Emberfall Tactics", "901003", "Strategy", ["Strategy", "Indie"], ["Single-player", "Steam Workshop"], "Turn-based skirmishes in a kingdom buried under ash.", ("#3d1f0a", "#c1550e")),
    ("Harbor Lights", "901004", "Simulation", ["Simulation", "Casual"], ["Single-player", "Steam Cloud"], "Run a lighthouse, a ferry and a very small town.", ("#0b2b33", "#2f8f83")),
    ("Verdant Depths", "901005", "Adventure", ["Adventure", "Indie"], ["Single-player", "Steam Achievements"], "A diving expedition into a forest that grows underwater.", ("#102a18", "#3f8f4a")),
    ("Iron Meridian", "901006", "Action", ["Action", "Racing"], ["Single-player", "Multi-player", "Full controller support"], "Armoured trains racing across a fractured continent.", ("#241b12", "#9c6b2f")),
    ("Paper Kingdoms", "901007", "Strategy", ["Strategy", "Casual"], ["Single-player", "Steam Cloud"], "Fold, cut and conquer a world made of card stock.", ("#2c2436", "#a97fb5")),
    ("Signal Drift", "901008", "Adventure", ["Adventure", "Simulation"], ["Single-player", "Remote Play Together"], "Decode a radio signal that may be your own future.", ("#121c26", "#3b7ea1")),
]

OUTPUT_NAMES = [
    "scan",
    "scan-running",
    "review",
    "review-category",
    "add-category",
    "organize",
    "artwork",
    "done",
    "catalog",
    "setup",
    "batch-extract",
    "extract-progress",
    "extract-result",
]

_FLAT_STDDEV = 2.0


def _min_png_bytes(width: int, height: int) -> int:
    """The "this is not a blank panel" size floor, scaled to the capture area.

    A fixed 4 KB floor rejected the 183x86 Add Category prompt, which is a real screen that simply has
    very few pixels. Scaling with the area keeps the check meaningful for a full window and honest for
    a small dialog.
    """
    return max(1024, (width * height) // 60)


def _dpi_aware() -> None:
    """Make Tk coordinates and grabbed pixels agree on a scaled display.

    Without this, a 150% display reports Tk widget coordinates in logical pixels while `ImageGrab`
    returns device pixels, so every bbox this script computes lands offset and the capture shows the
    wrong part of the window. Must run before `tk.Tk()` is created.
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _sandbox_application(root: tk.Tk, sandbox: Path) -> application.Application:
    """Build the real app against a temp project root, so no real state is written."""
    games = sandbox / "Games"
    games.mkdir(parents=True, exist_ok=True)
    extract = sandbox / "Extracted"
    extract.mkdir(parents=True, exist_ok=True)
    def build_config(*_args, **_kwargs) -> AppConfig:
        # AppConfig has no extract_folder constructor argument - it is a property over `settings` -
        # so the destination is assigned after construction, inside the sandbox.
        config = AppConfig(sandbox, library_root=games)
        config.extract_folders = [extract]
        return config

    with patch.object(application, "AppConfig", build_config):
        # mock=True keeps Steam lookups and archive discovery in-process: no network, no 7z runs.
        return application.Application(root, mock=True)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("segoeuib.ttf", "arialbd.ttf", "segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(str(Path("C:/Windows/Fonts") / name), size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_art(path: Path, width: int, height: int, title: str, top: str, bottom: str, logo: bool = False) -> None:
    """A plausible piece of game artwork, so the review and artwork screens are not empty panels.

    Fictional games have no Steam CDN art. Generating a gradient card with the game's name on it keeps
    the screenshots honest - nobody mistakes a placeholder for a real game - while still exercising the
    same image path the app uses with downloaded artwork.
    """
    colour_a = tuple(int(top.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    colour_b = tuple(int(bottom.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        mix = y / max(1, height - 1)
        draw.line([(0, y), (width, y)], fill=tuple(int(colour_a[i] + (colour_b[i] - colour_a[i]) * mix) for i in range(3)))
    # A couple of soft bands so the capture has more than one flat colour to detect. The inset is
    # measured from the shorter side: a 400x600 portrait capsule is narrower than it is tall, and a
    # height-based inset would invert the rectangle and raise ValueError.
    for step in range(3):
        inset = int(min(width, height) * (0.10 + step * 0.14))
        if width - inset <= inset + 2:
            continue
        draw.rectangle([inset, inset, width - inset, inset + 2], fill=(255, 255, 255, 60))
    if not logo:
        draw.text((int(width * 0.06), int(height * 0.72)), title, font=_font(max(16, height // 12)), fill=(255, 255, 255))
    else:
        draw.text((int(width * 0.1), int(height * 0.36)), title.upper(), font=_font(max(18, height // 6)), fill=(255, 255, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "JPEG", quality=88)


def _artwork_for(app: application.Application, appid: str, title: str, top: str, bottom: str) -> ArtworkResult:
    cache = app.config.artwork_dir
    header = cache / f"{appid}.jpg"
    assets = {
        "header_image": header,
        "library_hero": cache / f"{appid}_library_hero.jpg",
        "library_capsule": cache / f"{appid}_library_capsule.jpg",
        "library_logo": cache / f"{appid}_library_logo.jpg",
    }
    _draw_art(header, 640, 300, title, top, bottom)
    _draw_art(assets["library_hero"], 800, 450, title, top, bottom)
    _draw_art(assets["library_capsule"], 400, 600, title, top, bottom)
    _draw_art(assets["library_logo"], 420, 180, title.upper(), top, bottom, logo=True)
    return ArtworkResult(status="ok", path=header, source="steamgriddb", assets=assets)


def _seed(app: application.Application) -> list[GameArchive]:
    """A small, complete-looking library: archives on disk, Steam metadata, artwork, categories."""
    games = app.config.library_root
    for category in ("Action", "Adventure", "Strategy", "RPG"):
        (games / category).mkdir(exist_ok=True)
    archives: list[GameArchive] = []
    for title, appid, category, genres, categories, description, colours in GAMES:
        path = games / f"{title} v1.zip"
        with zipfile.ZipFile(path, "w") as bundle:
            bundle.writestr("game/data.bin", b"x" * 4096)
        archive = GameArchive(path, title, title.lower(), identity_key(normalize_name(path.name)), ".zip")
        archive.steam = SteamMatch(
            found=True,
            appid=appid,
            name=title,
            genres=genres,
            categories=categories,
            description=description,
            tags=genres + ["Atmospheric"],
            release_date="12 Mar, 2024",
            confidence="High",
            source="steam-store",
            developer="Paper Lantern Studio",
            publisher="Paper Lantern Studio",
            score=0.98,
        )
        archive.decision.accepted = True
        archive.decision.category = category
        archive.size = path.stat().st_size
        archive.artwork = _artwork_for(app, appid, title, colours[0], colours[1])
        archives.append(archive)
    return archives


def _fit(root: tk.Tk, width: int, height: int) -> None:
    """Normalise the window and size it, matching what the geometry tests have to do.

    `MainWindow._maximize()` leaves Windows in the zoomed state, and while zoomed `geometry()` is
    ignored - the same trap `tools/layout_audit.py` documents at length.
    """
    try:
        root.state("normal")
    except tk.TclError:
        pass
    root.geometry(f"{width}x{height}+40+40")
    root.update_idletasks()
    root.update()


def _raise_window(window: tk.Misc) -> None:
    window.update_idletasks()
    window.update()
    try:
        window.lift()
    except tk.TclError:
        pass
    try:
        window.attributes("-topmost", True)
    except tk.TclError:
        pass
    window.update()
    # The compositor applies the topmost switch a frame later; grabbing immediately can capture the
    # window underneath. 150ms is enough on every desktop this has run on and is not a poll loop.
    time.sleep(0.15)
    window.update()


def _capture(window: tk.Misc, target: Path, extra_boxes: tuple[tuple[int, int, int, int], ...] = ()) -> int:
    """Grab the window's client area, verify it is a real image, and commit it atomically.

    `extra` covers windows that belong to the screen but are not children of it - a posted ttk
    combobox dropdown is a separate override window that drops below the widget, often past the
    window's bottom edge. Without including its box, the capture would be the plain screen again.
    """
    if not window.winfo_viewable():
        raise RuntimeError(f"{window.winfo_class()} is not viewable - no interactive desktop to capture")
    _raise_window(window)
    boxes = [(window.winfo_rootx(), window.winfo_rooty(), window.winfo_width(), window.winfo_height())]
    # Extra boxes describe windows that are not tkinter widgets we own (a ttk combobox popdown is a Tk
    # path, not a Python object), so they arrive as raw screen rectangles.
    boxes.extend(box for box in extra_boxes if box[2] > 0 and box[3] > 0)
    if not boxes:
        raise RuntimeError("nothing on screen to capture")
    left = min(b[0] for b in boxes)
    top = min(b[1] for b in boxes)
    right = max(b[0] + b[2] for b in boxes)
    bottom = max(b[1] + b[3] for b in boxes)
    x, y = left, top
    width, height = right - left, bottom - top
    if width < 120 or height < 80:
        # Dialogs are small on purpose (the Add Category prompt is about 380x140), so this only rejects a
        # widget that was never mapped at all - a 1x1 placeholder cannot be a laid-out screen.
        raise RuntimeError(f"{window.winfo_class()} measured {width}x{height}; it was never laid out")
    image = ImageGrab.grab(bbox=(x, y, x + width, y + height), all_screens=True)
    spread = max(ImageStat.Stat(image.convert("RGB")).stddev)
    if spread < _FLAT_STDDEV:
        raise RuntimeError(
            f"{target.name}: capture is a single flat colour (stddev {spread:.2f}), so the window was "
            "occluded or unmapped. Run this on an interactive desktop with the app visible."
        )
    tmp = target.with_name(target.name + ".tmp")
    image.save(tmp, "PNG", optimize=True)
    size = tmp.stat().st_size
    if size < _min_png_bytes(width, height):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"{target.name}: PNG is only {size} bytes, which is a blank panel not a screen")
    os.replace(tmp, target)
    try:
        window.attributes("-topmost", False)
    except tk.TclError:
        pass
    return size


def _capture_main(app: application.Application, name: str, out: Path) -> int:
    app.root.update()
    return _capture(app.root, out / f"{name}.png")


def _show_scan(app: application.Application) -> None:
    scan = app.window.views["scan"]
    app.window.show("scan")
    scan.set_library(app.config.library_root)
    scan.api_var.set("")
    app.root.update()


def _show_scan_running(app: application.Application) -> None:
    _show_scan(app)
    scan = app.window.views["scan"]
    scan.begin_scan()
    app.root.update()
    for event in [
        {"stage": "cleanup_done", "message": "Reclaimed 4 item(s), freed 1.2 GB"},
        {"stage": "dedupe_done", "message": "Kept one archive per game folder"},
        {"stage": "repair_done", "message": "Repair pass finished - 3 archive(s) converted"},
        {"stage": "discover_done", "message": "Found 8 archive(s)"},
    ]:
        app.window._scan_progress(event)
    app.root.update()


def _show_review(app: application.Application, archives: list[GameArchive]) -> None:
    app.window.state.update(scan_result=ScanResult(archives=archives))
    app.window.show("review")
    review = app.window.views["review"]
    review.load(archives, download_artwork=False)
    review.cancel_lookup()
    review._verified(archives)
    review.select(archives[0])
    app.root.update()


def _show_review_category(app: application.Application, archives: list[GameArchive]) -> tuple[str, tuple[int, int, int, int] | None]:
    """Review, with the CATEGORY list posted, so the picking UI itself is the subject.

    Returns the state and the popdown's screen rectangle. A ttk combobox list is a Tk path, not a
    tkinter widget, and it opens below the widget - often past the window's bottom edge - so the capture
    has to be widened to include it. Without that box the image would be identical to the plain review
    screenshot.
    """
    _show_review(app, archives)
    review = app.window.views["review"]
    # Same game as the plain review capture on purpose: then the only difference between the two images
    # is the posted list, so a reviewer can see that this screenshot adds something.
    review.select(archives[0])
    app.root.update()
    combo = review.category
    combo.focus_set()
    app.root.update()
    # Tk's ttk::combobox class binding opens the popup on Button-1 anywhere in the widget; aiming at
    # the arrow area is where a user would click, and it keeps the list below the box.
    combo.event_generate("<Button-1>", x=max(8, combo.winfo_width() - 10), y=combo.winfo_height() // 2)
    app.root.update()
    time.sleep(0.2)
    app.root.update()
    try:
        path = str(app.root.tk.call("ttk::combobox::PopdownWindow", combo))
        if not path:
            return "closed", None
        box = (
            int(app.root.tk.call("winfo", "rootx", path)),
            int(app.root.tk.call("winfo", "rooty", path)),
            int(app.root.tk.call("winfo", "width", path)),
            int(app.root.tk.call("winfo", "height", path)),
        )
        return "open", box
    except (tk.TclError, ValueError):
        return "closed", None


def _unpost_category(app: application.Application) -> None:
    try:
        app.root.tk.call("ttk::combobox::Unpost", app.window.views["review"].category)
    except tk.TclError:
        pass


def _descendants(widget: tk.Misc):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def _capture_add_category(app: application.Application, target: Path) -> None:
    """The Add Category prompt, captured from inside its own modal loop.

    `simpledialog.askstring` blocks in `wait_window`, so the capture is scheduled first: the `after`
    callback runs inside that loop, fills the entry with a plausible name, grabs the dialog and closes
    it, which lets `add_category()` return.
    """

    def fill_and_grab(attempt: int = 0) -> None:
        dialogs = [child for child in app.root.winfo_children() if isinstance(child, tk.Toplevel) and child.title() == "Add Category"]
        if not dialogs:
            # The dialog is built a moment after askstring starts; give it a few frames rather than
            # assuming the first callback lands after it exists.
            if attempt < 10:
                app.root.after(100, lambda: fill_and_grab(attempt + 1))
            return
        dialog = dialogs[-1]
        for widget in _descendants(dialog):
            if isinstance(widget, tk.Entry):
                widget.insert(0, "Roguelike")
                break
        dialog.update_idletasks()
        dialog.update()
        try:
            _capture(dialog, target)
        except Exception as exc:
            # A callback exception in Tk is reported through `report_callback_exception` and otherwise
            # vanishes; print it so a failed dialog capture names its cause.
            print(f"add-category capture failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        finally:
            dialog.destroy()

    app.root.after(400, fill_and_grab)
    app.window.views["review"].add_category()


def _seed_organized(app: application.Application, archives: list[GameArchive]) -> None:
    """File each archive into a library folder, the way a completed organize run leaves it.

    The catalog page is generated from organized folders (`.game-info.json` + banner + archive), not
    from loose archives, so the catalog screenshot needs this shape on disk. It uses the real
    `write_metadata()` writer rather than a hand-built dict, so the page is built from the same
    metadata an actual run produces.
    """
    library = app.config.library_root
    for archive in archives:
        title = archive.steam.name or archive.display_name
        folder = library / archive.decision.category / f"{title} - 2024-03-12"
        folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(folder / f"{title}.zip", "w") as bundle:
            bundle.writestr("game/data.bin", b"x" * 4096)
        app.services.organizer.write_metadata(folder, archive)
        header = archive.artwork.assets.get("header_image")
        if header and header.is_file():
            # The name the catalog's banner lookup expects: <asset prefix>_grid.jpg.
            shutil.copyfile(header, folder / f"{asset_prefix(folder, {'name': title})}_grid.jpg")
        archive.organized_path = folder
        archive.created_game_dir = True


def _find_edge() -> Path | None:
    """Locate Microsoft Edge, the only browser guaranteed on Windows 10/11 with a headless screenshot mode."""
    roots = [os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")]
    for root in roots:
        if not root:
            continue
        candidate = Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        if candidate.is_file():
            return candidate
    found = shutil.which("msedge")
    return Path(found) if found else None


def _capture_catalog(app: application.Application, target: Path, sandbox: Path, width: int, height: int) -> int:
    """Render the generated Game Library.html in headless Edge and keep the viewport as a PNG.

    The catalog is a browser page, not a Tk window, so it needs a browser to photograph. Edge's
    headless `--screenshot` writes the viewport at `--window-size`, and `--virtual-time-budget` lets the
    page's own JS finish painting first. A private `--user-data-dir` keeps the developer's real profile
    out of the run.
    """
    written = app.services.catalog.generate(app.config.library_root, False) or []
    pages = [Path(path) for path in written if str(path).lower().endswith(".html")]
    if not pages:
        raise RuntimeError("catalog.generate() wrote no HTML page")
    html = pages[0].resolve()
    edge = _find_edge()
    if edge is None:
        raise RuntimeError("Microsoft Edge not found; the catalog is a browser page and needs it to be rendered")
    tmp = target.with_name(target.stem + ".tmp.png").resolve()
    # Edge resolves the --screenshot path against its own working directory, so it must be absolute;
    # given a relative path it exits 0 and writes nothing.
    profile = sandbox / "edge-profile"
    command = [
        str(edge),
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        "--force-device-scale-factor=1",
        f"--user-data-dir={profile}",
        f"--window-size={width},{height}",
        "--virtual-time-budget=6000",
        f"--screenshot={tmp}",
        html.as_uri(),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=180)
    if not tmp.is_file():
        raise RuntimeError(
            "Edge wrote no screenshot for the catalog page "
            f"(exit {completed.returncode}): {(completed.stderr or completed.stdout or '')[-400:]}"
        )
    with Image.open(tmp) as image:
        spread = max(ImageStat.Stat(image.convert("RGB")).stddev)
    if spread < _FLAT_STDDEV:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"{target.name}: the catalog page rendered as a single flat colour (stddev {spread:.2f})")
    size = tmp.stat().st_size
    if size < _min_png_bytes(width, height):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"{target.name}: catalog PNG is only {size} bytes")
    os.replace(tmp, target)
    return size


def _capture_extract_progress(app: application.Application, archive: GameArchive, target: Path) -> int:
    """The extraction progress dialog, held open mid-run.

    `ExtractProgressDialog` starts a real extraction thread in its constructor, which would either
    unpack a real archive or fail instantly. `ExtractService` is patched with a stub whose `extract()`
    blocks on an event that is never set, so the dialog stays in its running state long enough to be
    photographed; the thread is a daemon and dies with the process.
    """
    from ui.extract_result_window import ExtractProgressDialog

    release = threading.Event()

    class _BlockingExtract:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def extract(self, *_args, **_kwargs) -> None:
            # Never released: the dialog only has to stay in its running state, and this is a daemon
            # thread that dies with the process.
            release.wait(120)

    with patch("services.extract_service.ExtractService", _BlockingExtract):
        dialog = ExtractProgressDialog(
            app.root,
            archive.path,
            app.config.extract_folder / archive.display_name,
            app.logger,
        )
        app.root.update()
        dialog._bar["value"] = 64
        dialog._file_label.configure(text="game/pak0.pak")
        dialog._elapsed.configure(text="00:03:12 elapsed")
        app.root.update()
        try:
            return _capture(dialog, target)
        finally:
            try:
                dialog.grab_release()
            except tk.TclError:
                pass
            dialog.destroy()


def _show_organize(app: application.Application, archives: list[GameArchive]) -> None:
    app.window.state.update(scan_result=ScanResult(archives=archives))
    app.window.show("organize")
    view = app.window.views["organize"]
    view.stage_counts = {}
    view.current = None
    view.work.grid()
    view.timeline.reset()
    view.feed.clear()
    app.root.update()
    for event in [
        {"stage": "organizing", "file": "Sir Beats Alot v1.zip", "source_suffix": ".zip", "game": "Sir Beats Alot", "category": "Action", "index": 1, "total": 8},
        {"stage": "extracting", "file": "Sir Beats Alot v1.zip", "source_bytes": 4_100_000_000},
        {"stage": "compressing", "file": "Sir Beats Alot v1.zip", "extracted_bytes": 8_200_000_000},
        {"stage": "converted", "file": "Sir Beats Alot v1.7z", "target_bytes": 2_000_000_000, "target_name": "Sir Beats Alot v1.7z"},
        {"stage": "organizing", "file": "Nebula Online v1.zip", "game": "Nebula Online", "category": "RPG", "index": 2, "total": 8},
        {"stage": "compressing", "file": "Nebula Online v1.zip", "extracted_bytes": 1_800_000_000},
    ]:
        view.progress_update(event)
    app.root.update()


def _mark_outcomes(archives: list[GameArchive]) -> None:
    for archive in archives[:4]:
        archive.conversion.status = "converted"
        archive.conversion.source_format = "ZIP"
        archive.conversion.target_format = "7Z"
        archive.conversion.final_size = 2_000_000_000
        archive.conversion.final_name = archive.path.name.replace(".zip", ".7z")
    archives[4].conversion.status = "not_needed"
    archives[5].conversion.status = "failed"
    archives[5].conversion.message = "7z build exited 255: Break signaled"
    archives[5].conversion.free_bytes_at_failure = 2_000_000
    for archive in archives[6:]:
        archive.conversion.status = "converted"
        archive.conversion.source_format = "ZIP"
        archive.conversion.target_format = "7Z"
        archive.conversion.final_size = 1_200_000_000
        archive.conversion.final_name = archive.path.name.replace(".zip", ".7z")


def _show_done(app: application.Application, archives: list[GameArchive]) -> None:
    app.window.views["done"].show(archives)
    app.window.show("done")
    app.root.update()


def _show_artwork(app: application.Application, archives: list[GameArchive]) -> None:
    app.window.views["artwork"].show(archives)
    app.window.show("artwork")
    app.root.update()


def _capture_setup(app: application.Application, width: int, height: int) -> object:
    from ui.setup_window import SetupWindow

    window = SetupWindow(app.root, app.config, app.logger)
    window.geometry(f"680x540+{max(40, width // 2 - 340)}+{max(40, height // 2 - 270)}")
    app.root.update()
    return window


def _capture_batch(app: application.Application) -> object:
    from services.batch_extract_service import DONE, EXTRACTING, FAILED, QUEUED, BatchPlan
    from services.batch_item import BatchItem
    from ui.batch_extract_window import BatchExtractWindow

    destination = app.config.extract_folder
    items = [
        BatchItem(destination=destination / "Sir Beats Alot", name="Sir Beats Alot", size=4_900_000_000, state=DONE, detail="unpacked 1,842 files"),
        BatchItem(destination=destination / "Nebula Online", name="Nebula Online", size=8_100_000_000, state=EXTRACTING, detail="game/pak0.pak", percent=64),
        BatchItem(destination=destination / "Emberfall Tactics", name="Emberfall Tactics", size=2_400_000_000, state=DONE, detail="unpacked 902 files"),
        BatchItem(destination=destination / "Harbor Lights", name="Harbor Lights", size=1_100_000_000, state=FAILED, detail="wrong password or unsupported method"),
        BatchItem(destination=destination / "Verdant Depths", name="Verdant Depths", size=6_300_000_000, state=QUEUED, detail="waiting"),
    ]
    plan = BatchPlan(
        items=items,
        total_bytes=sum(item.size for item in items),
        destination=destination,
        category="Action",
        already_done=3,
    )
    window = BatchExtractWindow(app.root, plan=plan, logger=app.logger)
    window._render_all()
    window.remaining.configure(text=f"{sum(1 for item in items if item.finished)} of {len(items)} done  -  2 remaining")
    window.bar["value"] = 40
    window.metrics.configure(text="9.1 GB unpacked  -  00:14:22  -  210 MB/s  -  412 GB free on the drive")
    app.root.update()
    return window


def _capture_extract_result(app: application.Application, archive: GameArchive, shot: Path) -> None:
    """The result popup blocks in `wait_window`, so the capture is scheduled before it is built.

    `ExtractResultWindow.__init__` runs its own event loop until the window is destroyed, which would
    hang this script. A Tk `after` callback fires inside that loop: it finds the newest Toplevel,
    captures it, and destroys it, which lets the constructor return.
    """
    from ui.extract_result_window import ExtractResultWindow

    def grab_and_close() -> None:
        windows = [child for child in app.root.winfo_children() if isinstance(child, tk.Toplevel)]
        if not windows:
            return
        window = windows[-1]
        try:
            _capture(window, shot)
        finally:
            try:
                window.grab_release()
            except tk.TclError:
                pass
            window.destroy()

    app.root.after(600, grab_and_close)
    ExtractResultWindow(
        app.root,
        archive=archive.path,
        destination=app.config.extract_folder / archive.display_name,
        ok=True,
        message="Unpacked 1,842 files (6.2 GB) in 3m 12s.",
    )


def _parse_size(text: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in text.lower().split("x"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("size must look like 1600x1000") from exc
    if width < 800 or height < 560:
        raise argparse.ArgumentTypeError("size must be at least 800x560, the app's own minimum")
    return width, height


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture one PNG per app screen for the README")
    parser.add_argument("--out", default="docs/screenshots", help="output folder (default docs/screenshots)")
    parser.add_argument("--size", type=_parse_size, default=(1600, 1000), help="main window size, e.g. 1600x1000")
    parser.add_argument("--only", nargs="*", default=None, help="capture only these screens: " + " ".join(OUTPUT_NAMES))
    parser.add_argument("--keep-sandbox", action="store_true", help="do not delete the temporary library")
    parser.add_argument("--ocr", action="store_true", help="also OCR-verify each captured screen for expected UI text")
    args = parser.parse_args(argv)

    wanted = set(args.only) if args.only else None
    unknown = sorted((wanted or set()) - set(OUTPUT_NAMES))
    if unknown:
        parser.error(f"unknown screen(s): {', '.join(unknown)}. Choose from: {', '.join(OUTPUT_NAMES)}")

    _dpi_aware()
    width, height = args.size
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sandbox = PROJECT_ROOT / "temp" / f"capture-screens-{os.getpid()}"
    sandbox.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    app = _sandbox_application(root, sandbox)
    results: list[tuple[str, int]] = []
    failures: list[str] = []

    def want(name: str) -> bool:
        return wanted is None or name in wanted

    try:
        _fit(root, width, height)
        archives = _seed(app)

        if want("scan"):
            _show_scan(app)
            results.append(("scan", _capture_main(app, "scan", out)))
        if want("scan-running"):
            _show_scan_running(app)
            results.append(("scan-running", _capture_main(app, "scan-running", out)))
        if want("review"):
            _show_review(app, archives)
            results.append(("review", _capture_main(app, "review", out)))
        if want("review-category"):
            state, box = _show_review_category(app, archives)
            results.append(("review-category", _capture(app.root, out / "review-category.png", extra_boxes=(box,) if box else ())))
            _unpost_category(app)
            if state != "open":
                # The capture is still a real review screen, but its subject - the posted list - is
                # missing, so say so rather than publish a duplicate under a new name.
                failures.append("review-category: the CATEGORY list did not open, so the capture shows the plain review screen")
        if want("add-category"):
            _capture_add_category(app, out / "add-category.png")
            path = out / "add-category.png"
            if path.is_file():
                results.append(("add-category", path.stat().st_size))
            else:
                failures.append("add-category: the Add Category dialog never produced a capture")
        if want("organize"):
            _show_organize(app, archives)
            results.append(("organize", _capture_main(app, "organize", out)))
        if want("artwork"):
            _show_artwork(app, archives)
            results.append(("artwork", _capture_main(app, "artwork", out)))
        if want("catalog"):
            _seed_organized(app, archives)
            results.append(("catalog", _capture_catalog(app, out / "catalog.png", sandbox, width, height)))
        if want("done"):
            _mark_outcomes(archives)
            _show_done(app, archives)
            results.append(("done", _capture_main(app, "done", out)))
        if want("setup"):
            window = _capture_setup(app, width, height)
            try:
                results.append(("setup", _capture(window, out / "setup.png")))
            finally:
                window.destroy()
        if want("batch-extract"):
            window = _capture_batch(app)
            try:
                results.append(("batch-extract", _capture(window, out / "batch-extract.png")))
            finally:
                window.destroy()
        if want("extract-progress"):
            results.append(("extract-progress", _capture_extract_progress(app, archives[0], out / "extract-progress.png")))
        if want("extract-result"):
            _capture_extract_result(app, archives[0], out / "extract-result.png")
            path = out / "extract-result.png"
            if path.is_file():
                results.append(("extract-result", path.stat().st_size))
            else:
                failures.append("extract-result: the popup never produced a capture")
    except Exception as exc:
        failures.append(f"{type(exc).__name__}: {exc}")
    finally:
        try:
            app.shutdown()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass
        if not args.keep_sandbox:
            # The sandbox holds only generated files, a throwaway Edge profile and logs. It lives under
            # temp/ in the project (gitignored) because AGENTS.md forbids writing scratch files to
            # %TEMP%\kilo or anywhere outside this repository.
            shutil.rmtree(sandbox, ignore_errors=True)

    print(f"=== screen captures -> {out.resolve()} ===")
    for name, size in results:
        print(f"  {name + '.png':<22} {size / 1024:8.1f} KB")

    if args.ocr:
        print(f"\n=== OCR verification -> {out.resolve()} ===")
        ocr_failures = 0
        for name, _size in results:
            image_path = out / f"{name}.png"
            if not image_path.is_file():
                continue
            found_required, missing_required, found_forbidden, confidence = _ocr_check(image_path, name)
            if missing_required or found_forbidden:
                ocr_failures += 1
                print(f"  OCR FAIL  {name + '.png':<22} confidence={confidence:.1f}%")
                for missing in missing_required:
                    print(f"    MISSING required text: '{missing}'")
                for forbidden in found_forbidden:
                    print(f"    FORBIDDEN text found: '{forbidden}'")
            else:
                print(f"  OCR OK    {name + '.png':<22} confidence={confidence:.1f}%  required={len(found_required)}")
        if ocr_failures > 0:
            failures.append(f"OCR: {ocr_failures} screen(s) had missing required or forbidden text")
        print(f"ocr checked {len(results)} screen(s)")

    if failures:
        for failure in failures:
            print(f"  FAILED  {failure}", file=sys.stderr)
        return 1
    if not results:
        print("  nothing captured", file=sys.stderr)
        return 1
    print(f"captured {len(results)} screen(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
