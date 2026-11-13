#!/usr/bin/env python3
# The entry point puts its own folder on the path itself, the way
# tools/install_protocol_handler.py does, so it runs from any interpreter and any
# working directory. A normal launch adds the script's folder for free, but the
# bundled runtime ships a python313._pth that replaces the search path entirely,
# so without this the bundled interpreter could not find core/ beside the script.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# PyInstaller marks services/catalog_service.py as an "invalid module" and cannot freeze it, so the
# frozen build pre-loads it - and services/extract_service.py - from the bundle's own filesystem.
#
# Frozen builds only, and never over a module that is already imported. This used to run for every
# launch, and replacing sys.modules["services.extract_service"] with a second module object gave the
# process two distinct ExtractService classes: whoever imported the class first kept the one it had,
# while every later `from services.extract_service import ExtractService` inside a function got the
# other. Patching one then had no effect on code holding the other - in the suite that made three
# tool-lookup tests run against the real bundled 7z.exe instead of the stubs they had planted. From
# source a normal import has always worked, so the pre-load has no reason to run there at all.
if getattr(sys, "frozen", False):
    import importlib.util as _iu

    _bundle_dir = Path(__file__).resolve().parent.parent
    for _name in ("catalog_service", "extract_service"):
        _qualified = f"services.{_name}"
        if _qualified in sys.modules:
            continue
        _spec = _iu.spec_from_file_location(_qualified, str(_bundle_dir / "services" / f"{_name}.py"))
        _module = _iu.module_from_spec(_spec)
        _spec.loader.exec_module(_module)
        sys.modules[_qualified] = _module

def build_name_map(logger, library_root) -> dict:
    """Build a map of archive Path -> (steam_name, release_date) from catalog metadata.

    Walks the whole library once through CatalogService._collect(), which is now cached
    module-wide (services/catalog_service.py:_COLLECT_CACHE) so callers within the same
    process reuse a single walk instead of each re-walking the library.
    """
    from services.catalog_service import CatalogService

    name_map = {}
    try:
        _svc = CatalogService(logger, extract_folders=[])
        _categories = _svc._collect(library_root)
        for _cat_name, _games in _categories.items():
            for _g in _games:
                _archive_path = str(_g.get("_archive_path", ""))
                if _archive_path:
                    _name = _g.get("name") or ""
                    _date = _g.get("release_date") or ""
                    name_map[Path(_archive_path)] = (_name, _date)
    except Exception as exc:
        logger.warning("EXTRACT", f"NAME_MAP_FAILED error={type(exc).__name__}: {exc}")
        name_map = {}
    return name_map

from core.constants import APP_NAME, NO_WINDOW
def _open_setup(config, logger, prefill=None):
    """Open the three-folder setup wizard. Returns None on success, 0 if cancelled.

    A Toplevel on a withdrawn root, like the batch window: the protocol handler runs with no main window, and
    this is the only thing that has to appear. tkinter is imported here rather than at module scope for the
    same reason the single-extract path avoids it.
    """
    import tkinter as tk
    from ui.setup_window import SetupWindow

    root = tk.Tk()
    root.withdraw()
    # The window is the point of the call; the root's mainloop is
    # what keeps it open until the reader closes it.
    window = SetupWindow(root, config, logger, prefill=prefill)
    root.mainloop()
    root.destroy()
    # If the wizard was closed without saving (or was cancelled), return an
    # error so the app stays in setup mode on the next launch. If the save
    # succeeded, propagate None so the caller launches the main window.
    return None if window.saved else 0

def _handle_open_extracted_uri(uri, config, logger):
    """Opens the extracted game/installer folder."""
    from core.uri_actions import UriRefused
    from core.parse_open_extracted_uri import parse_open_extracted_uri

    try:
        folder = parse_open_extracted_uri(uri, config.extract_folders)
    except UriRefused as refused:
        logger.warning("EXTRACT", f"URI_REFUSED uri=[{uri[:160]}] reason=[{refused}]")
        print(f"{APP_NAME}: {refused}")
        return 2
    logger.info("EXTRACT", f"URI_ACCEPTED action=open-extracted path=[{folder}]")
    try:
        import os

        os.startfile(str(folder))
    except OSError as exc:
        print(f"{APP_NAME}: Could not open {folder}: {exc}")
        return 1
    return 0

def _regenerate_catalog_and_open(config, logger):
    """Regenerate catalog after a state-changing action and open it (best-effort)."""
    try:
        from services.catalog_service import CatalogService

        CatalogService(logger, extract_folders=config.extract_folders).generate(config.library_root)
        html = config.library_root / CatalogService.CATALOG_NAME
        if html.is_file():
            import os

            os.startfile(str(html))
    except Exception as exc:
        logger.warning("CATALOG", f"CATALOG_REGEN_FAILED error={type(exc).__name__}: {exc}")

def _handle_play_uri(uri, config, logger):
    from core.uri_actions import UriRefused
    from core.parse_play_uri import parse_play_uri

    try:
        req = parse_play_uri(uri, config.extract_folders)
    except UriRefused as refused:
        logger.warning("PLAY", f"URI_REFUSED uri=[{uri[:160]}] reason=[{refused}]")
        print(f"{APP_NAME}: {refused}")
        return 2
    logger.info("PLAY", f"URI_ACCEPTED exe=[{req.exe}] marker=[{req.marker_dir}]")
    try:
        import subprocess

        subprocess.Popen([str(req.exe)], cwd=str(req.exe.parent), creationflags=NO_WINDOW)
    except OSError as exc:
        logger.warning("PLAY", f"LAUNCH_FAILED exe=[{req.exe}] error={type(exc).__name__}: {exc}")
        print(f"{APP_NAME}: Could not launch {req.exe.name}: {exc}")
        return 1
    return 0

def _handle_mark_installed_uri(uri, config, logger):
    from core.uri_actions import UriRefused
    from core.parse_mark_installed_uri import parse_mark_installed_uri

    try:
        marker_dir = parse_mark_installed_uri(uri, config.extract_folders)
    except UriRefused as refused:
        logger.warning("SETUP_DONE", f"URI_REFUSED uri=[{uri[:160]}] reason=[{refused}]")
        print(f"{APP_NAME}: {refused}")
        return 2
    try:
        from services.catalog_status import mark_setup_done

        mark_setup_done(marker_dir, extract_folders=config.extract_folders, logger=logger)
        logger.info("SETUP_DONE", f"MARKED marker=[{marker_dir}]")
    except Exception as exc:
        logger.warning("SETUP_DONE", f"MARK_FAILED marker=[{marker_dir}] error={type(exc).__name__}: {exc}")
        print(f"{APP_NAME}: {exc}")
        return 1
    _regenerate_catalog_and_open(config, logger)
    return 0

def _cancel_planning(window, plan_holder, root, outcome):
    """Cancel a scan or run in progress."""
    if window.job and not window.job.done.is_set():
        window.job.cancel()
        window.title("Stopping the current game, then closing...")
        window.cancel_btn.configure(state="disabled", text="STOPPING...")
        return
    window._closed = True
    if window._pump:
        try:
            window.after_cancel(window._pump)
        except (RuntimeError, ValueError):
            pass
        window._pump = None
    window.destroy()
    root.quit()

def _extract_to_disk(args, config, logger):
    """The --extract command line: extract, print where it went, and exit."""
    # config.extract_folder is already the folder extracted games go in - it is what the catalog's Extract
    # button writes to and what the protocol handler is restricted to. It used to have "Extracted" appended
    # again, so every --extract without an explicit --dest landed one level deeper than the same game
    # extracted from the catalog, and the app's own message named the doubled path: "Extracted 2 file(s) to
    # C:\Users\...\Downloads\Extracted\Extracted".
    destination = Path(args.dest).expanduser() if args.dest else config.extract_folder
    result = _extract(Path(args.extract), destination, config, logger, args_password=args.zip_password)
    print(result.message)
    return 0 if result.ok else 1

def _extract(archive, destination, config, logger, args_password=""):
    from services.extract_service import ExtractService

    service = ExtractService(logger)
    result = service.extract(archive, destination, password=args_password or str(config.settings.get("zip_password", "") or ""))
    print(result.message)
    return result

def _needs_setup(config):
    """Whether this PC has ever been configured: a saved library root that exists on disk.

    settings.json is written only by the wizard, so on a copied folder it does not exist at all -
    and the default library root is a path that does not exist either. Both mean the same thing to
    a reader opening the app: nothing is configured, so nothing will scan.
    """
    if not config.settings_file.is_file():
        return True
    root = config.library_root
    return not root or not root.is_dir()

from core.main import main

# Re-exported so tests can patch them: patch.object(steam_game_organizer, "AppConfig", ...)
from core.config import AppConfig  # noqa: F401
from core.logger import AppLogger  # noqa: F401

if __name__ == "__main__":
    raise SystemExit(main())
