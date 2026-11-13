"""Extracted from steam_game_organizer.py.

    _handle_batch_uri was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

import threading
from steam_game_organizer import _cancel_planning
from steam_game_organizer import build_name_map
from core.constants import APP_NAME


def _handle_batch_uri(uri, config, logger):
    """A category's Extract All, or the whole library's.

    The only difference from a single extract is that this one opens a window. A single archive finishes in a
    minute and a window per click would be worse than no feedback, which is why _handle_uri stays headless; a
    category is twenty games and the library is a hundred and seventy-six, which is hours, and silence over hours
    is indistinguishable from a hung run. So the batch gets the window and the single keeps not having one.

    tkinter is imported here rather than at module scope for the same reason the single path avoids it: a
    console invocation of --uri must not pay for Tk it will not use.
    """
    from core.uri_actions import UriRefused
    from core.parse_batch_uri import parse_batch_uri

    try:
        request = parse_batch_uri(uri, config.library_root, config.extract_folders)
    except UriRefused as refused:
        logger.warning("EXTRACT", f"URI_REFUSED uri=[{uri[:160]}] reason=[{refused}]")
        print(f"{APP_NAME}: {refused}")
        return 2

    from services.plan_batch import plan_batch
    from services.catalog_status import status_from_run, write_status

    import tkinter as tk
    from ui.batch_extract_window import run_batch_window

    root = tk.Tk()
    root.withdraw()
    outcome = {"code": 0}

    # Build a name_map from catalog metadata so extraction folders use the clean
    # Steam name + release date ("Game Name - 2024-01-01") instead of the messy
    # archive filename stem. Archives not in the catalog fall back to the stem.
    name_map = build_name_map(logger, config.library_root)

    # plan_batch scans every archive and sniffs each for an installer signature before the first game is
    # unpacked - minutes on a real library. The window opens first showing "Scanning library" so the reader
    # gets feedback immediately, and planning runs on a worker thread; set_plan() swaps in the real rows
    # and starts extraction when planning is done.
    plan_holder = {}
    window = run_batch_window(root, logger=logger, password=str(config.settings.get("zip_password", "") or ""), scanning=True)
    window.cancel_btn.configure(state="disabled", text="CANCEL")
    window.cancel_btn.configure(command=lambda: _cancel_planning(window, plan_holder, root, outcome))

    def finished(job):
        # Non-zero only when nothing usable came out. A run of 176 with three failures produced 173 working game
        # folders, and reporting the whole run as failed would train people to ignore the exit code.
        outcome["code"] = 0 if job.succeeded else 1
        # Written when the run ends, not while it is going. Nothing on the page is watching for this - the
        # file is only read the next time somebody opens the catalog - so the window is the live readout and
        # this is the durable one. A failure to write it is swallowed inside write_status: the games are
        # already unpacked by now and a browser that cannot be told must not fail the run.
        write_status(config.library_root, status_from_run(job.plan, job), logger)
        if job.succeeded:
            root.quit()

    window.on_finished = finished

    def _plan():
        plan_holder["plan"] = plan_batch(config.library_root, request.destination, request.category, logger, name_map=name_map)
        # set_plan also swaps in the real destination if the empty-folder check changed it.
        root.after(0, lambda: window.set_plan(plan_holder["plan"]) if not window._closed else None)

    threading.Thread(target=_plan, name="plan-batch", daemon=True).start()

    root.mainloop()
    # A closed window mid-run leaves the job cancelling itself; the code reflects what was actually unpacked.
    return outcome["code"]
