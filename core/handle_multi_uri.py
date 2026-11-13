"""Extracted from steam_game_organizer.py.

    _handle_multi_uri was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import subprocess
import threading
from core.constants import APP_NAME
from steam_game_organizer import _cancel_planning
from steam_game_organizer import build_name_map
from core.constants import NO_WINDOW


def _handle_multi_uri(uri, config, logger):
    """A selection of games from the catalog, unpacked in one batch window.

    Each archive in the request has already been validated by parse_multi_uri against
    the library root. The plan is built directly rather than by scanning a category,
    so the multi-select can span categories or pick individual games.
    """
    from core.uri_actions import UriRefused
    from core.parse_multi_uri import parse_multi_uri
    from core.safe_folder_name import safe_folder_name

    try:
        request = parse_multi_uri(uri, config.library_root, config.extract_folders)
    except UriRefused as refused:
        logger.warning("EXTRACT", f"URI_REFUSED uri=[{uri[:160]}] reason=[{refused}]")
        print(f"{APP_NAME}: {refused}")
        return 2
    from services.batch_extract_service import BatchPlan, BatchItem
    from ui.batch_extract_window import run_batch_window
    import tkinter as tk
    import tkinter.messagebox as messagebox
    from services.extract_service import ExtractService

    root = tk.Tk()
    root.withdraw()
    outcome = {"code": 0}

    # Pre-validate every archive is readable by 7z before opening any UI. If 7z cannot
    # open one (corrupt download, locked by another process, antivirus holding it,
    # wrong archive format) the window would just flash and close - show a clear
    # dialog instead so the reader knows exactly what is wrong.
    tool, _tool_reason = ExtractService.find_tool()
    if tool:
        for archive, _pre_dest in request.archives:
            probe = subprocess.run([tool, "l", str(archive)], stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", creationflags=NO_WINDOW)
            if probe.returncode != 0:
                detail = (probe.stdout + probe.stderr).strip()[-300:]
                messagebox.showerror(
                    "Cannot open archive",
                    f"7-Zip could not read {archive.name}.\n\nThe archive may be corrupt, still "
                    f"being copied, open in another program, or locked by antivirus on this PC.\n"
                    f"\n\n7-Zip said: {detail or '(no detail)'}")
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

    plan_holder = {}
    window = run_batch_window(root, logger=logger, password=str(config.settings.get("zip_password", "") or ""), scanning=True)
    window.cancel_btn.configure(state="disabled", text="CANCEL")
    window.cancel_btn.configure(command=lambda: _cancel_planning(window, plan_holder, root, outcome))

    def _plan():
        # Build a name_map from catalog metadata so extraction folders use the clean
        # Steam name + release date instead of the messy archive filename stem.
        name_map = build_name_map(logger, config.library_root)

        plan = BatchPlan(destination=request.destination, category=f"{len(request.archives)} selected games")

        used = set()
        for archive, pre_dest in request.archives:
            # Use the clean Steam name + release date from catalog metadata when available,
            # falling back to the archive stem.
            entry = name_map.get(archive)
            if entry:
                steam_name, release_date = entry
                clean = f"{steam_name or archive.stem}"
                if release_date:
                    clean = f"{clean} - {release_date.replace(',', '')}"
                leaf = safe_folder_name(clean)
            else:
                leaf = pre_dest.name
            if leaf in used:
                suffix = 2
                while f"{leaf} ({suffix})" in used:
                    suffix += 1
                leaf = f"{leaf} ({suffix})"
            used.add(leaf)
            target = request.destination / leaf
            try:
                size = archive.stat().st_size
            except OSError:
                size = 0
            plan.items.append(BatchItem(archive=archive, destination=target, name=archive.stem, size=size))
        plan.total_bytes = sum(item.size for item in plan.items)
        root.after(0, lambda: window.set_plan(plan) if not window._closed else None)

    threading.Thread(target=_plan, name="plan-multi", daemon=True).start()

    def finished(job):
        outcome["code"] = 0 if job.succeeded else 1
        from services.catalog_status import status_from_run, write_status

        write_status(config.library_root, status_from_run(job.plan, job), logger)
        if job.succeeded:
            root.quit()

    window.on_finished = finished
    root.mainloop()
    return outcome["code"]
