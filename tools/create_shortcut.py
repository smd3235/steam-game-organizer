#!/usr/bin/env python3
"""Create or update the Steam Game Organizer desktop/start menu shortcut."""
from pathlib import Path
import os
import sys
import subprocess

PROJECT = Path(__file__).resolve().parent.parent


def _find_target():
    exe = PROJECT / "dist" / "steam_game_organizer" / "steam_game_organizer.exe"
    if exe.is_file():
        return exe
    py = PROJECT / "steam_game_organizer.py"
    if py.is_file():
        return py
    raise FileNotFoundError("No launch target found")


def create_shortcut(name="Steam Game Organizer.lnk", location=None, use_desktop=True):
    target = _find_target()
    if os.name != "nt":
        raise RuntimeError("Shortcuts only supported on Windows")
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        if location is None:
            location = Path(shell.SpecialFolders("Desktop")) / name if use_desktop else PROJECT / name
        shortcut = shell.CreateShortCut(str(location))
        shortcut.Targetpath = str(target)
        shortcut.WorkingDirectory = str(target.parent)
        if target.suffix.lower() == ".exe":
            shortcut.IconLocation = str(target)
        shortcut.save()
        return location
    except Exception:
        lnk = Path(location) if location is not None else (Path(os.environ.get("USERPROFILE", "")) / "Desktop" / name if use_desktop else PROJECT / name)
        vbs = PROJECT / "_create_shortcut_temp.vbs"
        vbs.write_text(
            "Set oWS = WScript.CreateObject(\"WScript.Shell\")\r\n"
            f"sLinkFile = \"{str(lnk).replace(chr(92), chr(92)+chr(92))}\"\r\n"
            "Set oLink = oWS.CreateShortcut(sLinkFile)\r\n"
            f"oLink.TargetPath = \"{str(target).replace(chr(92), chr(92)+chr(92))}\"\r\n"
            f"oLink.WorkingDirectory = \"{str(target.parent).replace(chr(92), chr(92)+chr(92))}\"\r\n"
            f"oLink.IconLocation = \"{str(target).replace(chr(92), chr(92)+chr(92))}\"\r\n"
            "oLink.Save\r\n",
            encoding="ascii",
        )
        try:
            subprocess.call(["cscript", "//nologo", str(vbs)], shell=False)
        finally:
            try:
                vbs.unlink()
            except Exception:
                pass
        return lnk


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--name", default="Steam Game Organizer.lnk")
    p.add_argument("--no-desktop", action="store_true", help="Create in project root instead of Desktop")
    args = p.parse_args()
    try:
        loc = create_shortcut(args.name, use_desktop=not args.no_desktop)
        print(loc)
    except Exception as e:
        print(e, file=sys.stderr)
        sys.exit(1)
