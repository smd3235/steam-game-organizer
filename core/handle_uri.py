"""Extracted from steam_game_organizer.py.

    _handle_uri was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import subprocess
import threading
from core.constants import APP_NAME
from core.constants import NO_WINDOW
from core.handle_batch_uri import _handle_batch_uri
from core.handle_multi_uri import _handle_multi_uri
from core.handle_open_folder_uri import _handle_open_folder_uri
from core.handle_pick_launcher_uri import _handle_pick_launcher_uri
from steam_game_organizer import _cancel_planning
from steam_game_organizer import _handle_mark_installed_uri
from steam_game_organizer import _handle_open_extracted_uri
from steam_game_organizer import _handle_play_uri
from steam_game_organizer import _open_setup
from steam_game_organizer import build_name_map


def _handle_uri(uri, config, logger):
    """Entry point for a steamgameorganizer:// link. Returns a process exit code.

    A single extract shows a small result dialog so the reader can see what happened; a batch
    extract shows the progress window. A refusal shows nothing on screen - the message is printed
    to stdout for the brief console the browser opens - because there is nothing to do.
    """
    from core.uri_actions import UriRefused, parse_uri, parse_setup_uri
    from urllib.parse import urlsplit

    parts = urlsplit(str(uri))
    action = (parts.netloc or parts.path.lstrip("/")).strip().casefold()
    try:
        if action == "open-folder":
            return _handle_open_folder_uri(uri, config, logger)
        if action == "open-extracted":
            return _handle_open_extracted_uri(uri, config, logger)
        if action == "play":
            return _handle_play_uri(uri, config, logger)
        if action == "pick-launcher":
            return _handle_pick_launcher_uri(uri, config, logger)
        if action == "mark-installed":
            return _handle_mark_installed_uri(uri, config, logger)
        if action == "extract-all":
            return _handle_batch_uri(uri, config, logger)
        if action == "extract-multi":
            return _handle_multi_uri(uri, config, logger)
        if action == "setup":
            # The catalog's "Set up on this PC" button. The link carries the
            # folder paths the page's own boxes hold, so the wizard opens on
            # the folders this reader already typed rather than the ones the
            # page was generated with.
            result = _open_setup(config, logger, prefill=parse_setup_uri(uri))
            # Regenerate the catalog so the page's folder boxes reflect the
            # new config values instead of showing stale ones from before setup.
            if result is None:
                try:
                    from services.catalog_service import CatalogService

                    svc = CatalogService(logger, extract_folders=config.extract_folders)
                    svc.generate(config.library_root)
                except Exception as exc:
                    logger.warning("SETUP", f"CATALOG_REGEN_FAILED error={type(exc).__name__}: {exc}")
            return result
        if action == "refresh-catalog":
            # The page is static and cannot re-scan disk itself, so regeneration
            # has to happen in the app. Re-walk the library, re-check what is
            # unpacked against the extract folder, and re-write the page.
            from services.catalog_service import CatalogService

            try:
                svc = CatalogService(logger, extract_folders=config.extract_folders)
                svc.generate(config.library_root)
                html = config.library_root / CatalogService.CATALOG_NAME
                if html.is_file():
                    import os

                    os.startfile(str(html))
            except Exception as exc:
                logger.warning("REFRESH", f"CATALOG_REFRESH_FAILED error={type(exc).__name__}: {exc}")
                print(f"{APP_NAME}: {exc}")
                return 1
            return 0
        request = parse_uri(uri, config.library_root, config.extract_folders)
    except UriRefused as refused:
        # Refusals are normal and expected: a stale bookmarked link, or a path that has moved. They are not
        # crashes and must never print a traceback into whatever terminal the handler inherited.
        logger.warning("EXTRACT", f"URI_REFUSED uri=[{uri[:160]}] reason=[{refused}]")
        print(f"{APP_NAME}: {refused}")
        return 2
    logger.info("EXTRACT", f"URI_ACCEPTED src=[{request.archive}] dest=[{request.destination}]")
    from services.batch_extract_service import BatchPlan, BatchItem
    from services.catalog_service import CatalogService
    from ui.batch_extract_window import run_batch_window
    import tkinter as tk
    import tkinter.messagebox as messagebox
    from services.extract_service import ExtractService

    root = tk.Tk()
    root.withdraw()
    outcome = {"code": 0}

    # Pre-validate the archive is readable by 7z before opening any UI. If 7z cannot
    # open it (corrupt download, locked by another process, antivirus holding it,
    # wrong archive format) the window would just flash and close - show a clear
    # dialog instead so the reader knows exactly what is wrong.
    tool, _tool_reason = ExtractService.find_tool()
    if tool:
        probe = subprocess.run([tool, "l", str(request.archive)], stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", creationflags=NO_WINDOW)
        if probe.returncode != 0:
            detail = (probe.stdout + probe.stderr).strip()[-300:]
            messagebox.showerror(
                "Cannot open archive",
                f"7-Zip could not read {request.archive.name}.\n\nThe archive may be corrupt, "
                f"still being copied, open in another program, or locked by antivirus on this "
                f"PC.\n\n7-Zip said: {detail or '(no detail)'}")
            try:
                root.destroy()
            except tk.TclError:
                pass
            return 1
    else:
        messagebox.showerror("No extraction tool", "The bundled 7z.exe is missing beside the app, so nothing can be unpacked.\n\nThe app's runtime folder should contain 7z.exe. This copy may be incomplete.")
        try:
            root.destroy()
        except tk.TclError:
            pass
        return 1

    # Open the window immediately so the reader sees something is working, even on
    # a big library where walking every archive for catalog names takes minutes.
    # The name map and the plan are built on a background thread, then set_plan()
    # swaps in the real rows and starts extraction - same arrangement batch mode uses.
    plan_holder = {}
    window = run_batch_window(root, logger=logger, password=str(config.settings.get("zip_password", "") or ""), scanning=True)
    window.cancel_btn.configure(state="disabled", text="CANCEL")
    window.cancel_btn.configure(command=lambda: _cancel_planning(window, plan_holder, root, outcome))

    def _plan():
        # Build a name_map from catalog metadata so the extraction folder uses the clean
        # Steam name + release date ("Game Name - 2024-01-01") instead of the messy
        # archive filename stem. Archives not in the catalog fall back to the stem.
        name_map = build_name_map(logger, config.library_root)

        # Override the destination with the clean folder name when catalog metadata is available.
        entry = name_map.get(request.archive)
        dest = request.destination
        if entry:
            steam_name, release_date = entry
            clean = f"{steam_name or request.archive.stem}"
            if release_date:
                clean = f"{clean} - {release_date.replace(',', '')}"
            from services.batch_extract_service import safe_folder_name

            dest = dest.parent / safe_folder_name(clean)

        try:
            size = request.archive.stat().st_size
        except OSError:
            size = 0
        plan = BatchPlan(destination=dest, category=request.archive.stem, items=[BatchItem(archive=request.archive, destination=dest, name=request.archive.stem, size=size)], total_bytes=size)
        plan.already_done = 0
        root.after(0, lambda: window.set_plan(plan) if not window._closed else None)

    threading.Thread(target=_plan, name="plan-single", daemon=True).start()

    def finished(job):
        outcome["code"] = 0 if job.succeeded else 1
        from services.catalog_status import status_from_run, write_status

        write_status(config.library_root, status_from_run(job.plan, job), logger)
        if job.succeeded:
            root.quit()

    window.on_finished = finished
    root.mainloop()
    return outcome["code"]
