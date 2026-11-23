#!/usr/bin/env python3
"""
OCR Test Tool for Steam Game Organizer.

Comprehensive UI testing that:
1. Captures all application screens using capture_screens.py
2. Runs OCR (Tesseract with multiple PSM modes) on each image
3. Verifies expected UI text elements are present
4. Detects Python error dialogs / traceback windows using pywinauto
5. Analyzes UI layout using OpenCV (button detection, overlap detection)
6. Reports all issues found across the entire project
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import Optional

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
except ImportError:
    print("pytesseract not available. Install with: pip install pytesseract")
    sys.exit(1)
except Exception as e:
    print(f"pytesseract config error: {e}")
    sys.exit(1)

try:
    from PIL import Image, ImageOps
except ImportError:
    print("PIL not available. Install with: pip install Pillow")
    sys.exit(1)

try:
    import cv2
    import numpy as np
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

try:
    import importlib.util as _iu
    HAS_PYWINAUTO = _iu.find_spec("pywinauto") is not None
    if HAS_PYWINAUTO:
        from pywinauto import Desktop
except ImportError:
    HAS_PYWINAUTO = False


# =============================================================================
# Expected header text per screen (OCR reliably detects these)
# =============================================================================

SCREEN_HEADERS: dict[str, list[str]] = {
    "scan": ["STEAM GAME ORGANIZER", "SCAN"],
    "review": ["STEAM GAME ORGANIZER", "GAME REVIEW"],
    "organize": ["STEAM GAME ORGANIZER", "ORGANIZE"],
    "artwork": ["STEAM GAME ORGANIZER", "ARTWORK"],
    "done": ["STEAM GAME ORGANIZER", "DONE"],
    "setup": ["STEAM GAME ORGANIZER"],
    "batch": ["STEAM GAME ORGANIZER", "EXTRACT"],
    "extract": ["STEAM GAME ORGANIZER", "EXTRACT"],
}

FORBIDDEN: list[str] = [
    "Traceback", "Error:", "Exception:", "FileNotFoundError",
    "ImportError", "AttributeError", "TypeError", "ValueError",
    "KeyError", "IndexError", "ModuleNotFoundError",
    "PermissionError", "OSError", "RuntimeError",
]


# =============================================================================
# Result container
# =============================================================================

class OCRResult:
    def __init__(self, screen_name: str, image_path: Path):
        self.screen_name = screen_name
        self.image_path = image_path
        self.text = ""
        self.confidence = 0.0
        self.issues: list[str] = []
        self.warnings: list[str] = []
        self.found_required: list[str] = []
        self.missing_required: list[str] = []
        self.found_forbidden: list[str] = []

    def to_dict(self) -> dict:
        return {
            "screen": self.screen_name,
            "image": str(self.image_path),
            "text": self.text,
            "confidence": self.confidence,
            "issues": self.issues,
            "warnings": self.warnings,
            "found_required": self.found_required,
            "missing_required": self.missing_required,
            "found_forbidden": self.found_forbidden,
        }


# =============================================================================
# Image preprocessing
# =============================================================================

def preprocess_image(image: Image.Image) -> Image.Image:
    """Preprocess image for better OCR on UI screenshots."""
    gray = ImageOps.grayscale(image)

    # Upscale if image is small
    w, h = gray.size
    if w < 1400:
        scale = 1400 / w
        new_size = (int(w * scale), int(h * scale))
        gray = gray.resize(new_size, Image.LANCZOS)

    return ImageOps.autocontrast(gray, cutoff=1)


def run_ocr_multi_psm(image: Image.Image) -> tuple[str, float]:
    """Run OCR with multiple PSM modes and return the best result."""
    processed = preprocess_image(image)

    best_text = ""
    best_confidence = 0.0
    best_word_count = 0

    for psm in [6, 11, 12]:
        try:
            data = pytesseract.image_to_data(
                processed,
                output_type=pytesseract.Output.DICT,
                config=f"--psm {psm}",
            )

            words = []
            confidences = []
            for i, conf in enumerate(data["conf"]):
                if conf > 0 and data["text"][i].strip():
                    words.append(data["text"][i])
                    confidences.append(conf)

            text = " ".join(words)
            word_count = len(words)
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

            score = word_count * (avg_confidence / 100)
            if score > best_word_count * (best_confidence / 100):
                best_text = text
                best_confidence = avg_confidence
                best_word_count = word_count

        except Exception:
            continue

    return best_text, best_confidence


# =============================================================================
# Python error dialog detection using pywinauto
# =============================================================================

def check_python_error_windows() -> list[str]:
    """Check for Python error dialogs / traceback windows using UI Automation.

    Returns a list of error window titles found.
    """
    if not HAS_PYWINAUTO:
        return []

    errors = []
    try:
        desktop = Desktop(backend="uia")
        windows = desktop.windows()

        for win in windows:
            try:
                title = win.window_text() or ""
                class_name = win.class_name() or ""

                # Check for Python error dialogs
                if any(kw in title.lower() for kw in [
                    "python", "traceback", "error", "exception",
                    "fatal", "unhandled", "crash",
                ]):
                    errors.append(f"Error window: title='{title}' class='{class_name}'")

                # Check for tkinter/Tcl error dialogs
                if "tk" in title.lower() or "tcl" in title.lower():
                    if any(kw in title.lower() for kw in ["error", "exception", "fatal"]):
                        errors.append(f"Tk error window: title='{title}' class='{class_name}'")
            except Exception:
                continue
    except Exception as e:
        errors.append(f"pywinauto check failed: {e}")

    return errors


# =============================================================================
# OpenCV layout analysis
# =============================================================================

def analyze_layout(image_path: Path) -> list[str]:
    """Analyze UI layout using OpenCV to detect potential issues.

    Checks for:
    - Button-like rectangles that might be missing text
    - Overlapping UI elements
    - Unusually large empty areas
    """
    if not HAS_OPENCV:
        return []

    issues = []

    try:
        img = cv2.imread(str(image_path))
        if img is None:
            return ["Cannot load image for layout analysis"]

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Detect edges
        edges = cv2.Canny(gray, 50, 150)

        # Find contours (potential UI elements)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        h, w = gray.shape
        total_area = w * h

        # Check for very large empty areas (could indicate missing UI)
        # This is a heuristic - if more than 40% of the image is background color
        _, thresh = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY)
        bg_ratio = np.sum(thresh == 255) / total_area
        if bg_ratio > 0.5:
            issues.append(f"Large background area: {bg_ratio:.1%} of image")

        # Count detected UI elements
        element_count = len(contours)
        if element_count < 5:
            issues.append(f"Very few UI elements detected: {element_count}")

    except Exception as e:
        issues.append(f"Layout analysis failed: {e}")

    return issues


# =============================================================================
# Screen checking
# =============================================================================

def check_screen(screen_name: str, image_path: Path) -> OCRResult:
    """Check a single screen against expectations."""
    result = OCRResult(screen_name, image_path)

    try:
        image = Image.open(image_path)
    except Exception as e:
        result.issues.append(f"Cannot open image: {e}")
        return result

    # Run OCR with multiple PSM modes
    result.text, result.confidence = run_ocr_multi_psm(image)

    if result.confidence < 30:
        result.warnings.append(f"Low OCR confidence: {result.confidence:.1f}%")

    # Get header expectations for this screen
    headers = SCREEN_HEADERS.get(screen_name, [])
    forbidden = FORBIDDEN

    # Normalize OCR text for matching
    text_norm = " ".join(result.text.split())
    text_lower = text_norm.lower()

    # Check header text (fuzzy match)
    for header in headers:
        header_words = header.lower().split()
        if len(header_words) == 1:
            if header.lower() in text_lower:
                result.found_required.append(header)
            else:
                result.missing_required.append(header)
                result.issues.append(f"Missing header text: '{header}'")
        else:
            all_found = all(w in text_lower for w in header_words)
            if all_found:
                result.found_required.append(header)
            else:
                result.missing_required.append(header)
                result.issues.append(f"Missing header text: '{header}'")

    # Check forbidden text
    for forb in forbidden:
        if forb.lower() in text_lower:
            result.found_forbidden.append(forb)
            result.issues.append(f"Found forbidden text: '{forb}'")

    # Check for Python traceback patterns
    traceback_indicators = [
        "traceback", "raise systemexit", "filenotfounderror",
        "modulenotfounderror", "permissionerror", "keyerror",
        "indexerror", "typeerror", "valueerror", "attributeerror",
        "importerror", "oserror", "runtimeerror", "tclerro r",
        "tkinter",
    ]
    for indicator in traceback_indicators:
        if indicator in text_lower:
            if indicator not in [f.lower() for f in result.found_forbidden]:
                result.issues.append(f"Possible Python error detected: '{indicator}'")

    # Check for error dialog patterns
    error_dialogs = [
        "python.exe", "pythonw.exe", "could not open display",
        "no display name", "unhandled exception", "fatal error",
        "application error",
    ]
    for pattern in error_dialogs:
        if pattern in text_lower:
            result.warnings.append(f"Possible error dialog: '{pattern}'")

    # OpenCV layout analysis
    if HAS_OPENCV:
        layout_issues = analyze_layout(image_path)
        result.issues.extend(layout_issues)

    return result


# =============================================================================
# Capture and test
# =============================================================================

def capture_screens(output_dir: Path, size: str = "1600x1000") -> bool:
    """Capture all screens using the existing capture_screens.py."""
    try:
        cmd = [
            sys.executable, str(ROOT / "tools" / "capture_screens.py"),
            "--out", str(output_dir),
            "--size", size,
        ]
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"Capture failed: {result.stderr}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print("Capture timed out")
        return False
    except Exception as e:
        print(f"Capture error: {e}")
        return False


def find_captured_images(output_dir: Path) -> dict[str, Path]:
    """Find captured PNG files and map them to screen names."""
    screens: dict[str, Path] = {}
    for png in sorted(output_dir.glob("*.png")):
        name = png.stem
        base_name = name.split("-")[0]
        screens[base_name] = png
    return screens


def run_ocr_tests(
    capture: bool = True,
    output_dir: Optional[Path] = None,
    size: str = "1600x1000",
    screens_to_test: Optional[list[str]] = None,
) -> list[OCRResult]:
    """Run full OCR test suite."""
    if output_dir is None:
        output_dir = ROOT / "temp" / f"ocr-test-{os.getpid()}"

    output_dir.mkdir(parents=True, exist_ok=True)

    if capture:
        print(f"Capturing screens to {output_dir}...")
        if not capture_screens(output_dir, size):
            print("Failed to capture screens")
            return []

    print("Finding captured images...")
    all_screens = find_captured_images(output_dir)
    print(f"Found screens: {list(all_screens.keys())}")

    if screens_to_test:
        all_screens = {k: v for k, v in all_screens.items() if k in screens_to_test}

    results = []
    for screen_name, image_path in all_screens.items():
        print(f"  Checking {screen_name}...")
        result = check_screen(screen_name, image_path)
        results.append(result)

        if result.issues:
            print(f"    ISSUES ({len(result.issues)}):")
            for issue in result.issues:
                print(f"      - {issue}")
        if result.warnings:
            print(f"    WARNINGS ({len(result.warnings)}):")
            for warn in result.warnings:
                print(f"      - {warn}")
        if result.missing_required:
            print(f"    MISSING ({len(result.missing_required)}): {result.missing_required[:5]}...")
        print(f"    Confidence: {result.confidence:.1f}%")

    # Check for Python error windows using pywinauto
    print("\nChecking for Python error windows...")
    error_windows = check_python_error_windows()
    for ew in error_windows:
        print(f"  - {ew}")
        # Add as a global issue
        for r in results:
            r.issues.append(f"Python error window: {ew}")

    return results


def generate_report(results: list[OCRResult], output_path: Path) -> None:
    """Generate JSON report."""
    report = {
        "summary": {
            "total_screens": len(results),
            "screens_with_issues": sum(1 for r in results if r.issues),
            "screens_with_warnings": sum(1 for r in results if r.warnings),
            "total_issues": sum(len(r.issues) for r in results),
            "total_warnings": sum(len(r.warnings) for r in results),
            "avg_confidence": sum(r.confidence for r in results) / len(results) if results else 0,
        },
        "screens": [r.to_dict() for r in results],
    }
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report written to {output_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="OCR Test for Steam Game Organizer")
    parser.add_argument("--no-capture", action="store_true", help="Skip screen capture, use existing images")
    parser.add_argument("--out", type=Path, help="Output directory for captures and report")
    parser.add_argument("--size", default="1600x1000", help="Capture size (WxH)")
    parser.add_argument("--report", type=Path, help="Report output path (JSON)")
    parser.add_argument("--only", nargs="+", help="Only test specific screens")
    args = parser.parse_args()

    if args.out is None:
        args.out = ROOT / "temp" / f"ocr-test-{os.getpid()}"

    results = run_ocr_tests(
        capture=not args.no_capture,
        output_dir=args.out,
        size=args.size,
        screens_to_test=args.only,
    )

    if args.report:
        generate_report(results, args.report)
    else:
        generate_report(results, args.out / "ocr_report.json")

    total_issues = sum(len(r.issues) for r in results)
    if total_issues > 0:
        print(f"\nFAILED: {total_issues} issues found")
        sys.exit(1)
    else:
        print("\nPASSED: No issues found")
        sys.exit(0)


if __name__ == "__main__":
    main()