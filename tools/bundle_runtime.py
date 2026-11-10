r"""Assembles the runtime folder that lets a copied app folder work on a PC with nothing installed.

The catalog page itself needs nothing - it is a static file a browser opens. What a friend's PC
lacks is the pair of things an Extract button needs behind it: a Python to run the
steamgameorganizer:// handler, and a 7-Zip to unpack the archive. This tool copies both into
`runtime/` beside the app, from the Python that runs it and the 7-Zip that machine has, so the
folder can be copied to a disk, handed to a friend, and opened with no installation step.

The copy keeps the layout a Windows Python install uses (python.exe, DLLs/, Lib/, tcl/, tk/),
which is the one _tkinter.pyd knows how to find Tcl in - the setup wizard needs Tk, and the
embeddable distribution ships without it. The standard library travels without its test suite
and the desktop tools nothing here imports, which is most of the size.

    python tools/bundle_runtime.py                 build runtime/ from this interpreter's install
    python tools/bundle_runtime.py --check         report what runtime/ holds
    python tools/bundle_runtime.py --from DIR      build from a specific Python install
    python tools/bundle_runtime.py --sevenzip PATH bundle a specific 7z.exe

The handler registration still cannot travel: the registry is per-machine, so the first run on
a new PC is `runtime\python.exe tools\install_protocol_handler.py`, which registers the bundled
interpreter - the one command a copied folder still needs.
"""
from pathlib import Path
from dataclasses import dataclass
import argparse
import shutil
import subprocess
import sys
import sysconfig

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from services.extract_service import ExtractService

APP_ROOT = Path(__file__).resolve().parent.parent
RUNTIME = APP_ROOT / "runtime"

# Directories of the standard library a desktop app never imports. `test` alone is most of the
# weight of Lib; the rest are a GUI playground, a refactoring tool and a demo, none of which
# anything in the app or its handler path touches.
LIB_EXCLUDES = ("test", "idlelib", "lib2to3", "turtledemo", "site-packages")

# Pillow is a runtime dependency that ships a C extension inside its package directory,
# so it must be copied tree-by-tree rather than excluded with the standard library.
# The build only proceeds when Pillow is importable; the probe in execute() will fail
# on a host that lacks it, which is the intended error (the app cannot render JPEG artwork).
PIL_LOCATIONS = ("PIL",)

NOTICES = """Python is the Python Software Foundation's implementation of the language,
distributed under the PSF License Agreement: https://docs.python.org/3/license.html

7-Zip is Igor Pavlov's archiver, distributed under the GNU LGPL:
https://www.7-zip.org/license.txt

Pillow is the friendly PIL fork, distributed under the HPND license:
https://github.com/python-pillow/Pillow/blob/main/LICENSE
Only the core package (Image, ImageTk) is bundled; JPEG artwork from Steam
requires it because tk.PhotoImage cannot decode JPEG.
"""


@dataclass
class CopyStep:
    """One operation of the build: a file, a directory tree, or a small file written here.

    The plan is data rather than a sequence of copies so a test can hold it up against a fake
    install tree without copying anything - the layout is the contract between this tool and
    the folder a friend receives, and a silent change to it is a runtime that starts nowhere.
    """
    kind: str
    destination: Path
    source: Path = None
    exclude: tuple = ()
    content: str = ""


def build_plan(source: Path, destination: Path, sevenzip: Path = None):
    """The operations that turn a Python install into a self-contained runtime folder."""
    version = sysconfig.get_config_var("LDVERSION") or f"python{sys.version_info.major}{sys.version_info.minor}"
    plan = []
    for name in ("python.exe", "pythonw.exe", f"{version}.dll", "python3.dll",
                 "vcruntime140.dll", "vcruntime140_1.dll"):
        if (source / name).is_file():
            plan.append(CopyStep("file", destination / name, source / name))
    for folder in ("DLLs", "tcl", "tk"):
        if (source / folder).is_dir():
            plan.append(CopyStep("tree", destination / folder, source / folder))
    plan.append(CopyStep("tree", destination / "Lib", source / "Lib", exclude=LIB_EXCLUDES))
    # Pillow ships a C extension inside its package directory, so the whole PIL/ package
    # must be copied into Lib/ (not excluded as site-packages). The _pth already puts
    # Lib on the path, so the bundled interpreter finds it without changes.
    pil_source = _find_pillow(source)
    if pil_source:
        plan.append(CopyStep("tree", destination / "Lib" / "PIL", pil_source))
    # The paths _pth declares are the whole of sys.path for this interpreter - the registry
    # entry a normal install relies on does not exist on the friend's machine, so the layout
    # below is what makes the copied standard library findable at all.
    plan.append(CopyStep("write", destination / f"{version}._pth", content=".\nLib\nDLLs\n"))
    plan.append(CopyStep("write", destination / "THIRD-PARTY-NOTICES.txt", content=NOTICES))
    if (source / "LICENSE.txt").is_file():
        plan.append(CopyStep("file", destination / "LICENSE.txt", source / "LICENSE.txt"))
    if sevenzip:
        plan.append(CopyStep("file", destination / "7z.exe", sevenzip))
    return plan


def execute(plan):
    for step in plan:
        step.destination.parent.mkdir(parents=True, exist_ok=True)
        if step.kind == "file":
            shutil.copy2(step.source, step.destination)
        elif step.kind == "tree":
            if step.destination.exists():
                shutil.rmtree(step.destination)
            shutil.copytree(step.source, step.destination,
                            ignore=shutil.ignore_patterns(*step.exclude))
        else:
            step.destination.write_text(step.content, encoding="utf-8")


def _source_install(explicit):
    source = Path(explicit).resolve() if explicit else Path(sys.prefix).resolve()
    if source.resolve() == RUNTIME.resolve():
        sys.exit("the runtime cannot be built from itself; point --from at a full Python install")
    if not (source / "Lib" / "os.py").is_file() or not (source / "DLLs").is_dir():
        sys.exit(f"{source} is not a full Python install (no Lib/os.py or DLLs/); "
                 "run this tool with an interpreter that has them, or pass --from DIR")
    return source


def _find_pillow(source: Path):
    """Locate the PIL package directory in the host or source Python's site-packages.

    Returns None when Pillow is not installed, so the build can skip it gracefully
    and the probe will catch the missing dependency at runtime.
    """
    import importlib.util
    spec = importlib.util.find_spec("PIL")
    if spec and spec.submodule_search_locations:
        return Path(spec.submodule_search_locations[0])
    return None


def _locate_sevenzip(explicit):
    if explicit:
        return Path(explicit)
    found = shutil.which("7z")
    if found:
        return Path(found)
    return next(iter(ExtractService._windows_candidates(("7-Zip", "7z.exe"))), None)


def _probe(destination):
    """The bundled interpreter, asked to import the things the app cannot live without."""
    python = destination / "python.exe"
    if not python.is_file():
        sys.exit("the runtime was built without python.exe")
    probe = subprocess.run([str(python), "-c",
                            "import sys, tkinter, urllib.request, PIL; print(sys.version.split()[0])"],
                           capture_output=True, text=True)
    if probe.returncode != 0:
        if "No module named 'PIL'" in probe.stderr:
            sys.exit("Pillow is missing from the bundled runtime - artwork cannot be decoded.\n"
                     "Rebuild with: python tools/bundle_runtime.py")
        sys.exit(f"the bundled interpreter cannot import its own standard library:\n{probe.stderr.strip()}")
    return probe.stdout.strip()


def check():
    python = RUNTIME / "python.exe"
    if not python.is_file():
        print("runtime : not built - run: python tools/bundle_runtime.py")
        return 1
    version = _probe(RUNTIME)
    sevenzip = RUNTIME / "7z.exe"
    total = sum(p.stat().st_size for p in RUNTIME.rglob("*") if p.is_file())
    print(f"runtime : python {version} with tkinter, {total / 1e6:.1f} MB in {RUNTIME}")
    print(f"  7z.exe   : {'bundled' if sevenzip.is_file() else 'NOT bundled - Extract needs 7-Zip installed'}")
    from tools.install_protocol_handler import _registered_command
    command = _registered_command()
    hint = "runtime\\python.exe tools\\install_protocol_handler.py"
    print(f"  handler  : {command if command else 'not registered - run: ' + hint}")
    if command and str(RUNTIME) in command:
        print("  the registered interpreter is the bundled one, so the folder travels as a unit")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="source", metavar="DIR",
                        help="build from a specific Python install (default: this interpreter's)")
    parser.add_argument("--sevenzip", metavar="PATH",
                        help="bundle this 7z.exe (default: the one this machine has)")
    parser.add_argument("--check", action="store_true",
                        help="report what runtime/ holds, build nothing")
    arguments = parser.parse_args()
    if arguments.check:
        return check()
    source = _source_install(arguments.source)
    sevenzip = _locate_sevenzip(arguments.sevenzip)
    if not sevenzip:
        print("warning: no 7-Zip found on this machine; building the runtime without 7z.exe",
              file=sys.stderr)
    plan = build_plan(source, RUNTIME, sevenzip)
    execute(plan)
    version = _probe(RUNTIME)
    end_to_end = subprocess.run([str(RUNTIME / "python.exe"),
                                 str(APP_ROOT / "steam_game_organizer.py"), "--version"],
                                capture_output=True, text=True)
    if end_to_end.returncode != 0:
        sys.exit(f"the bundled interpreter cannot run the app:\n{end_to_end.stderr.strip()}")
    files = [p for p in RUNTIME.rglob("*") if p.is_file()]
    print(f"built {RUNTIME}: python {version}, {len(files)} files, "
          f"{sum(p.stat().st_size for p in files) / 1e6:.1f} MB"
          + (", 7z.exe bundled" if sevenzip else ", no 7z.exe (none found)"))
    print(f"end-to-end: {end_to_end.stdout.strip()}")
    print("next step on this machine: runtime\\python.exe tools\\install_protocol_handler.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
