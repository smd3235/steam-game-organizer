"""Extracted from steam_game_organizer.py.

    _handle_pick_launcher_uri was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from steam_game_organizer import _regenerate_catalog_and_open
from core.constants import APP_NAME


def _handle_pick_launcher_uri(uri, config, logger):
    from pathlib import Path
    from core.uri_actions import UriRefused
    from core.parse_pick_launcher_uri import parse_pick_launcher_uri

    try:
        marker_dir = parse_pick_launcher_uri(uri, config.extract_folders)
    except UriRefused as refused:
        logger.warning("PLAY", f"URI_REFUSED uri=[{uri[:160]}] reason=[{refused}]")
        print(f"{APP_NAME}: {refused}")
        return 2
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
        from services.catalog_status import resolve_extracted_root, update_extract_marker, _path_within

        root = tk.Tk()
        root.withdraw()
        try:
            initial = resolve_extracted_root(marker_dir, config.extract_folders) or marker_dir
            picked = filedialog.askopenfilename(
                parent=root,
                title="Choose the game launcher (.exe)",
                initialdir=str(initial),
                filetypes=[("Game/application", "*.exe"), ("All files", "*.*")],
            )
            if not picked:
                return 0
            exe = Path(picked)
            bases = [Path(b).expanduser() for b in (config.extract_folders or [])]
            if exe.suffix.lower() != ".exe" or not exe.is_file() or not any(_path_within(exe, b) for b in bases):
                messagebox.showerror(APP_NAME, "Please choose a .exe file inside the extracted game folder.")
                return 2
            update_extract_marker(marker_dir, logger=logger, launch_target=str(exe.resolve()))
            logger.info("PLAY", f"LAUNCHER_SET marker=[{marker_dir}] exe=[{exe}]")
        finally:
            try:
                root.destroy()
            except Exception:
                pass
    except Exception as exc:
        logger.warning("PLAY", f"PICK_LAUNCHER_FAILED marker=[{uri[:120]}] error={type(exc).__name__}: {exc}")
        print(f"{APP_NAME}: {exc}")
        return 1
    _regenerate_catalog_and_open(config, logger)
    return 0
