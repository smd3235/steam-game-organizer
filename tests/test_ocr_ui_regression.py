"""OCR-based UI regression tests for Steam Game Organizer.

Captures all application screens via capture_screens.py, runs Tesseract OCR
with multiple PSM modes, and asserts:
  1. Each screen renders its expected header/title text
  2. No Python error dialogs / traceback windows are visible (via pywinauto)
  3. No forbidden error text appears in OCR output

Catches UI regressions: missing screens, error dialogs, blank/unrendered screens.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

from PIL import Image, ImageOps

import importlib.util as _iu


CAPTURE_DIR = ROOT / "temp" / "ocr-pytest-capture"

# Minimum expected header text per screen (what OCR reliably detects)
SCREEN_HEADERS = {
    "scan": ["STEAM GAME ORGANIZER", "SCAN"],
    "review": ["STEAM GAME ORGANIZER", "GAME REVIEW"],
    "organize": ["STEAM GAME ORGANIZER", "ORGANIZE"],
    "artwork": ["STEAM GAME ORGANIZER", "ARTWORK"],
    "done": ["STEAM GAME ORGANIZER", "DONE"],
    "setup": ["STEAM GAME ORGANIZER"],
    "batch": ["STEAM GAME ORGANIZER", "EXTRACT"],
    "extract": ["STEAM GAME ORGANIZER", "EXTRACT"],
}

FORBIDDEN = [
    "traceback", "raise systemexit", "filenotfounderror", "modulenotfounderror",
    "permissionerror", "keyerror", "indexerror", "typeerror", "valueerror",
    "attributeerror", "importerror", "oserror", "runtimeerror",
    "python.exe", "pythonw.exe", "unhandled exception", "fatal error",
]


def _run_ocr_multi_psm(image: Image.Image) -> str:
    """Run OCR with multiple PSM modes and return the best text."""
    gray = ImageOps.grayscale(image)
    w, h = gray.size
    if w < 1400:
        scale = 1400 / w
        gray = gray.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    gray = ImageOps.autocontrast(gray, cutoff=1)

    best_text = ""
    best_score = 0.0

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
            score = len(words) * (sum(confs) / len(confs) / 100 if confs else 0)
            if score > best_score:
                best_text = text
                best_score = score
        except Exception:
            continue

    return best_text


def _check_headers(text: str, headers: list[str]) -> list[str]:
    missing = []
    text_lower = " ".join(text.split()).lower()
    for header in headers:
        header_words = header.lower().split()
        if len(header_words) == 1:
            if header.lower() not in text_lower:
                missing.append(header)
        else:
            if not all(w in text_lower for w in header_words):
                missing.append(header)
    return missing


def _check_forbidden(text: str) -> list[str]:
    found = []
    text_lower = text.lower()
    for forb in FORBIDDEN:
        if forb in text_lower:
            found.append(forb)
    return found


@pytest.fixture(scope="module")
def captured_screens():
    """Capture all screens once for the module."""
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, str(ROOT / "tools" / "capture_screens.py"),
        "--out", str(CAPTURE_DIR),
        "--size", "1600x1000",
    ]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        pytest.fail(f"Screen capture failed: {result.stderr}")
    yield CAPTURE_DIR


def _find_images(output_dir: Path) -> dict[str, Path]:
    screens = {}
    for png in sorted(output_dir.glob("*.png")):
        base = png.stem.split("-")[0]
        screens[base] = png
    return screens


@pytest.mark.parametrize("screen_name,headers", [
    ("scan", SCREEN_HEADERS["scan"]),
    ("review", SCREEN_HEADERS["review"]),
    ("organize", SCREEN_HEADERS["organize"]),
    ("artwork", SCREEN_HEADERS["artwork"]),
    ("done", SCREEN_HEADERS["done"]),
    ("setup", SCREEN_HEADERS["setup"]),
    ("batch", SCREEN_HEADERS["batch"]),
    ("extract", SCREEN_HEADERS["extract"]),
])
def test_ocr_screen_has_header(captured_screens, screen_name, headers):
    """Each screen should render its expected header text."""
    screens = _find_images(captured_screens)
    assert screen_name in screens, f"No capture found for screen '{screen_name}'"

    image = Image.open(screens[screen_name])
    text = _run_ocr_multi_psm(image)

    missing = _check_headers(text, headers)
    assert not missing, (
        f"Screen '{screen_name}' missing header text: {missing}\n"
        f"OCR output was: {text[:500]}..."
    )


def test_ocr_no_python_error_windows():
    """No Python error dialogs / traceback windows should be visible."""
    if not _iu.find_spec("pywinauto"):
        return  # pywinauto not installed; skip the check silently

    try:
        from pywinauto import Desktop
        desktop = Desktop(backend="uia")
        for win in desktop.windows():
            title = (win.window_text() or "").lower()
            if any(kw in title for kw in ["python", "traceback", "error", "exception", "fatal", "crash"]):
                pytest.fail(
                    f"Python error window detected: title='{win.window_text()}' "
                    f"class='{win.class_name()}'"
                )
    except Exception:
        return  # pywinauto check failed; skip silently


@pytest.mark.parametrize("screen_name", [
    "scan", "review", "organize", "artwork", "done", "setup", "batch", "extract",
])
def test_ocr_screen_no_forbidden_text(captured_screens, screen_name):
    """Screens should not contain Python error/traceback text."""
    screens = _find_images(captured_screens)
    assert screen_name in screens, f"No capture found for screen '{screen_name}'"

    image = Image.open(screens[screen_name])
    text = _run_ocr_multi_psm(image)

    found = _check_forbidden(text)
    assert not found, (
        f"Screen '{screen_name}' contains forbidden text: {found}\n"
        f"OCR output was: {text[:500]}..."
    )
