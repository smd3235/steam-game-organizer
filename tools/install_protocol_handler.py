"""Installs the steamgameorganizer:// handler, so the catalog's Extract button can reach the machine.

A web page cannot run a program, open a folder or write a file - that is a real security boundary, not a
limitation to work around. A registered protocol handler is the one supported way a page can ask the desktop
to do something, and the browser still asks the user to confirm before it hands the link over.

Registration is per-user and needs no administrator rights: entries under HKCU\\Software\\Classes, which every
process for this user can write.

The page itself needs no platform-specific code: it is one <a href="steamgameorganizer://...">, which every
browser treats the same way.

    python tools/install_protocol_handler.py            install for this machine
    python tools/install_protocol_handler.py --check    report what is registered now
    python tools/install_protocol_handler.py --export   write a .reg for installing on another PC

This was not registered on the machine that generated the library, and the catalog held 491 Extract links
pointing at a scheme Windows had never heard of. Running this is not optional setup: without it every Extract
button in the generated page is a dead link.
"""
from pathlib import Path
import argparse
import os
import sys

# The scheme is defined once, next to the code that parses these links. Importing it rather than repeating the
# string here is what stops the page, the parser and the registry entry from quietly disagreeing - and it is
# also what this file was missing: SCHEME was used eight times and defined nowhere, so the module raised
# NameError before it could print a single line. Nothing in the test suite imports this directory, which is how
# a tool that cannot run survived.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.uri_actions import SCHEME
from core.constants import APP_NAME, ENTRY_POINT

APP_LABEL = APP_NAME

# One backslash, always. Written as a raw string with two it is a doubled separator, which is not a path any
# registry API documents, and the places that need this used to spell it three different ways.
REGISTRY_ROOT = r"Software\Classes"


def _registered_command():
    """The command Windows currently has for this scheme, or None when nothing is registered.

    One definition of the key, so the check that runs before an install and the check that runs after it
    cannot disagree about where the value lives - which is the same reason the path is not spelled out a
    third time here.
    """
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_ROOT + "\\" + SCHEME + r"\shell\open\command") as key:
            return str(winreg.QueryValueEx(key, None)[0])
    except OSError:
        return None


def _py_association_command():
    """The command Windows currently has for double-clicking a .py, or None."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_ROOT + r"\SGO.Python.File\shell\open\command") as key:
            return str(winreg.QueryValueEx(key, None)[0])
    except OSError:
        return None


def check():
    command = _registered_command()
    if command:
        print(f"  registry handler : {command}")
    else:
        print(f"  registry handler : (nothing registered for {SCHEME}:// - Extract links will not work)")
    py = _py_association_command()
    if py:
        print(f"  .py association  : {py}")
    else:
        print("  .py association  : (nothing registered - double-clicking steam_game_organizer.py opens as text)")
    print(f"  archive tool     : {_archive_tool()}")


def _archive_tool():
    """Whether this machine can actually unpack what the handler is being asked to extract."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from services.extract_service import ExtractService
    found, reason = ExtractService.find_tool()
    return f"{found}" if found else f"NO ({reason})"


def _build_command(python: str, entry: Path) -> str:
    """Build the HKCU command for the protocol handler.

    In a frozen build the interpreter IS the entry point (sys.executable resolves to
    the .exe), so the command is just '"<exe>" --uri "%1"'. In a source checkout the
    interpreter and entry point are separate, so both appear.
    """
    if getattr(sys, "frozen", False):
        return f'"{python}" --uri "%1"'
    return f'"{python}" "{entry}" --uri "%1"'

def install_windows(python: str, entry: Path):
    """Register the scheme under HKCU, which is per-user and needs no elevation."""
    import winreg
    key_path = REGISTRY_ROOT + "\\" + SCHEME
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, f"URL:{APP_LABEL}")
        # An empty value under this name is what makes Windows treat the key as a protocol, not a file type.
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + r"\shell\open\command") as key:
        command = _build_command(python, entry)
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, command)
    print(f"  registered HKCU\\{key_path}\\shell\\open\\command")
    # Read the value back instead of asserting that it worked. This line used to say "verified" and mean
    # "the two writes did not raise" - so a key Windows declined, or a value something else had rewritten,
    # was reported as a working handler. This is the one setup step the README calls mandatory, and the
    # symptom when it silently failed is a dead Extract button with nothing to show for it.
    read_back=_registered_command()
    if read_back==command:
        print(f"  verified: {SCHEME}:// now opens python with --uri")
    else:
        print(f"  WARNING: that key does not read back as written. It currently reads: {read_back!r}")
    _install_py_association(entry)

def _install_py_association(entry: Path):
    """Make double-clicking steam_game_organizer.py run it, per-user.

    The protocol handler is registered by the wizard, so the catalog's Extract button reaches the app.
    This is the other half: on a PC that has never had Python, a .py file has no association at all and
    double-clicking the entry point opens it in Notepad. The bundled runtime is what travels with the
    library, so the open command points at it rather than at whatever python happens to be installed -
    which may be the Microsoft Store's python3.exe alias, and that one opens the Store.
    """
    import winreg
    runtime_python = str((entry.parent / "runtime" / "python.exe").resolve())
    if not Path(runtime_python).is_file():
        print(f"  WARNING: no bundled python at {runtime_python}; .py will still open as text")
        return
    ext_key = REGISTRY_ROOT + r"\.py"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, ext_key) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "SGO.Python.File")
    cmd_key = REGISTRY_ROOT + r"\SGO.Python.File\shell\open\command"
    command = f'"{runtime_python}" "%1"'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, cmd_key) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, command)
    print(f"  registered HKCU\\{cmd_key}")
    # Read it back the same way the scheme handler is verified.
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, cmd_key) as key:
            read_back = str(winreg.QueryValueEx(key, None)[0])
    except OSError as exc:
        print(f"  WARNING: the .py association did not read back: {type(exc).__name__}")
        return
    if read_back == command:
        print("  verified: double-clicking a .py now runs the bundled python")
    else:
        print(f"  WARNING: the .py association reads back as {read_back!r}, not {command!r}")


def _reg_escape(value: str) -> str:
    """Quote a value so regedit reads it back exactly as written.

    Backslashes are doubled before quotes are escaped, not after: doing it the other way round would double
    the backslash this function had just added to an escape and hand regedit a broken value back."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def export_windows_reg(destination: Path, python: str, entry: Path):
    """A .reg for a machine that cannot run this script itself.

    Written by hand rather than exported from a live registry so it can be reviewed before it is imported, and
    so it carries the correct interpreter path instead of whichever python happened to be running.
    """
    import sys
    if getattr(sys, "frozen", False):
        command = f'"{python}" --uri "%1"'
        py_command = f'"{python}" "%1"'
    else:
        command = f'"{python}" "{entry}" --uri "%1"'
        # The .py association points at the interpreter, not the entry point: it is what runs when someone
        # double-clicks any .py, and "%1" is the file they clicked. It must be the bundled runtime python,
        # because the target PC is the one that has no Python installed - the interpreter that ran this script
        # is this machine's, and it will not exist there. pythonw.exe avoids a console window.
        runtime_python = str(entry.parent / "runtime" / "python.exe")
        py_command = f'"{runtime_python}" "%1"'
    lines = [
        r"Windows Registry Editor Version 5.00",
        "",
        rf"[HKEY_CURRENT_USER\{REGISTRY_ROOT}\{SCHEME}]",
        f'"@"="URL:{APP_LABEL}"',
        r'"URL Protocol"=""',
        "",
        rf"[HKEY_CURRENT_USER\{REGISTRY_ROOT}\{SCHEME}\shell\open\command]",
        # A .reg file is not a Python string: it wants the value quoted, with the quotes inside it escaped and
        # every backslash in the paths doubled. Hand-writing that escaping is how the exported command came
        # out reading \"\"C:\... - a stray shell quote in the path rather than a path. Built plainly and
        # escaped once, in that order.
        f'"@"="{_reg_escape(command)}"',
        "",
        # The .py association, so double-clicking the entry point on the target PC runs it rather than
        # opening it in Notepad. A PC that has never had Python has no handler for .py at all.
        rf"[HKEY_CURRENT_USER\{REGISTRY_ROOT}\.py]",
        '"@"="SGO.Python.File"',
        "",
        rf"[HKEY_CURRENT_USER\{REGISTRY_ROOT}\SGO.Python.File\shell\open\command]",
        # Same escaping discipline as the scheme handler above: build the value plainly, then escape once.
        f'"@"="{_reg_escape(py_command)}"',
        "",
    ]
    destination.write_text("\n".join(lines), encoding="utf-16")
    print(f"  wrote {destination} (import it on the target PC with regedit)")


def main():
    if os.name != "nt":
        # Said plainly rather than attempted: the xdg-mime path this used to carry could not run here, and it
        # had never been exercised, so there is nothing to fall back to.
        sys.exit("this app is Windows-only; registration uses HKCU\\Software\\Classes")
    project = Path(__file__).resolve().parent.parent
    entry = project / ENTRY_POINT
    if not entry.is_file():
        sys.exit(f"cannot find the entry point at {entry}")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report what is registered, change nothing")
    parser.add_argument("--export", type=Path, metavar="FILE",
                        help="write a Windows .reg for another PC and exit")
    arguments = parser.parse_args()

    # The interpreter that registered the handler is the one that has to open the link. On Windows that is
    # this process, by definition. But python.exe opens a console window; pythonw.exe does not, which is what
    # a protocol handler that shows a Tk window wants. Use pythonw.exe wherever python.exe would open a console.
    python = sys.executable
    if not getattr(sys, "frozen", False):
        python = str(Path(python).with_name("pythonw.exe"))
        if not Path(python).is_file():
            python = sys.executable

    if arguments.export:
        export_windows_reg(arguments.export, python, entry)
        return 0
    if arguments.check:
        check()
        return 0

    install_windows(python, entry)
    print(f"  archive tool     : {_archive_tool()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

