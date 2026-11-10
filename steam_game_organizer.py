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
if getattr(sys, 'frozen', False):
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
    name_map={}
    try:
        _svc=CatalogService(logger,extract_folders=[])
        _categories=_svc._collect(library_root)
        for _cat_name,_games in _categories.items():
            for _g in _games:
                _archive_path=str(_g.get('_archive_path',''))
                if _archive_path:
                    _name=_g.get('name') or ''
                    _date=_g.get('release_date') or ''
                    name_map[Path(_archive_path)] = (_name, _date)
    except Exception as exc:
        logger.warning('EXTRACT',f'NAME_MAP_FAILED error={type(exc).__name__}: {exc}')
        name_map={}
    return name_map
import argparse
import subprocess
import threading
from core.constants import APP_NAME,VERSION,NO_WINDOW
from core.config import AppConfig
from core.logger import AppLogger
from core.state import StateStore
from debug.diagnostics import Diagnostics

def _open_setup(config,logger,prefill=None):
    """Open the three-folder setup wizard. Returns None on success, 0 if cancelled.

    A Toplevel on a withdrawn root, like the batch window: the protocol handler runs with no main window, and
    this is the only thing that has to appear. tkinter is imported here rather than at module scope for the
    same reason the single-extract path avoids it.
    """
    import tkinter as tk
    from ui.setup_window import SetupWindow
    root=tk.Tk(); root.withdraw()
    # The window is the point of the call; the root's mainloop is
    # what keeps it open until the reader closes it.
    window=SetupWindow(root,config,logger,prefill=prefill)
    root.mainloop()
    root.destroy()
    # If the wizard was closed without saving (or was cancelled), return an
    # error so the app stays in setup mode on the next launch. If the save
    # succeeded, propagate None so the caller launches the main window.
    return None if window.saved else 0

def _handle_uri(uri,config,logger):
    """Entry point for a steamgameorganizer:// link. Returns a process exit code.

    A single extract shows a small result dialog so the reader can see what happened; a batch
    extract shows the progress window. A refusal shows nothing on screen - the message is printed
    to stdout for the brief console the browser opens - because there is nothing to do.
    """
    from core.uri_actions import UriRefused,parse_uri,parse_setup_uri
    from urllib.parse import urlsplit
    parts=urlsplit(str(uri))
    action=(parts.netloc or parts.path.lstrip('/')).strip().casefold()
    try:
        if action=='open-folder': return _handle_open_folder_uri(uri,config,logger)
        if action=='open-extracted': return _handle_open_extracted_uri(uri,config,logger)
        if action=='play': return _handle_play_uri(uri,config,logger)
        if action=='pick-launcher': return _handle_pick_launcher_uri(uri,config,logger)
        if action=='mark-installed': return _handle_mark_installed_uri(uri,config,logger)
        if action=='extract-all': return _handle_batch_uri(uri,config,logger)
        if action=='extract-multi': return _handle_multi_uri(uri,config,logger)
        if action=='setup':
            # The catalog's "Set up on this PC" button. The link carries the
            # folder paths the page's own boxes hold, so the wizard opens on
            # the folders this reader already typed rather than the ones the
            # page was generated with.
            result=_open_setup(config,logger,prefill=parse_setup_uri(uri))
            # Regenerate the catalog so the page's folder boxes reflect the
            # new config values instead of showing stale ones from before setup.
            if result is None:
                try:
                    from services.catalog_service import CatalogService
                    svc=CatalogService(logger,extract_folders=config.extract_folders)
                    svc.generate(config.library_root)
                except Exception as exc:
                    logger.warning('SETUP',f'CATALOG_REGEN_FAILED error={type(exc).__name__}: {exc}')
            return result
        if action=='refresh-catalog':
            # The page is static and cannot re-scan disk itself, so regeneration
            # has to happen in the app. Re-walk the library, re-check what is
            # unpacked against the extract folder, and re-write the page.
            from services.catalog_service import CatalogService
            try:
                svc=CatalogService(logger,extract_folders=config.extract_folders)
                svc.generate(config.library_root)
                html=config.library_root/CatalogService.CATALOG_NAME
                if html.is_file():
                    import os
                    os.startfile(str(html))
            except Exception as exc:
                logger.warning('REFRESH',f'CATALOG_REFRESH_FAILED error={type(exc).__name__}: {exc}')
                print(f"{APP_NAME}: {exc}")
                return 1
            return 0
        request=parse_uri(uri,config.library_root,config.extract_folders)
    except UriRefused as refused:
        # Refusals are normal and expected: a stale bookmarked link, or a path that has moved. They are not
        # crashes and must never print a traceback into whatever terminal the handler inherited.
        logger.warning('EXTRACT',f'URI_REFUSED uri=[{uri[:160]}] reason=[{refused}]')
        print(f"{APP_NAME}: {refused}")
        return 2
    logger.info('EXTRACT',f'URI_ACCEPTED src=[{request.archive}] dest=[{request.destination}]')
    from services.batch_extract_service import BatchPlan,BatchItem
    from services.catalog_service import CatalogService
    from ui.batch_extract_window import run_batch_window
    import tkinter as tk
    import tkinter.messagebox as messagebox
    from services.extract_service import ExtractService
    root=tk.Tk(); root.withdraw()
    outcome={'code':0}

    # Pre-validate the archive is readable by 7z before opening any UI. If 7z cannot
    # open it (corrupt download, locked by another process, antivirus holding it,
    # wrong archive format) the window would just flash and close - show a clear
    # dialog instead so the reader knows exactly what is wrong.
    tool, _tool_reason = ExtractService.find_tool()
    if tool:
        probe = subprocess.run([tool, 'l', str(request.archive)],
                               stdin=subprocess.DEVNULL, capture_output=True,
                               text=True, errors='replace', creationflags=NO_WINDOW)
        if probe.returncode != 0:
            detail = (probe.stdout + probe.stderr).strip()[-300:]
            messagebox.showerror(
                "Cannot open archive",
                f"7-Zip could not read {request.archive.name}.\n\n"
                f"The archive may be corrupt, still being copied, open in another "
                f"program, or locked by antivirus on this PC.\n\n"
                f"7-Zip said: {detail or '(no detail)'}"
            )
            try:
                root.destroy()
            except tk.TclError:
                pass
            return 1
    else:
        messagebox.showerror(
            "No extraction tool",
            "The bundled 7z.exe is missing beside the app, so nothing can be unpacked.\n\n"
            "The app's runtime folder should contain 7z.exe. This copy may be incomplete."
        )
        try:
            root.destroy()
        except tk.TclError:
            pass
        return 1

    # Open the window immediately so the reader sees something is working, even on
    # a big library where walking every archive for catalog names takes minutes.
    # The name map and the plan are built on a background thread, then set_plan()
    # swaps in the real rows and starts extraction - same arrangement batch mode uses.
    plan_holder={}
    window=run_batch_window(root,logger=logger,
                            password=str(config.settings.get("zip_password","") or ""),
                            scanning=True)
    window.cancel_btn.configure(state="disabled", text="CANCEL")
    window.cancel_btn.configure(command=lambda: _cancel_planning(window, plan_holder, root, outcome))

    def _plan():
        # Build a name_map from catalog metadata so the extraction folder uses the clean
        # Steam name + release date ("Game Name - 2024-01-01") instead of the messy
        # archive filename stem. Archives not in the catalog fall back to the stem.
        name_map=build_name_map(logger, config.library_root)

        # Override the destination with the clean folder name when catalog metadata is available.
        entry=name_map.get(request.archive)
        dest=request.destination
        if entry:
            steam_name, release_date = entry
            clean = f"{steam_name or request.archive.stem}"
            if release_date:
                clean = f"{clean} - {release_date.replace(',', '')}"
            from services.batch_extract_service import safe_folder_name
            dest = dest.parent / safe_folder_name(clean)

        try:
            size=request.archive.stat().st_size
        except OSError:
            size=0
        plan=BatchPlan(destination=dest,
                        category=request.archive.stem,
                        items=[BatchItem(archive=request.archive,destination=dest,name=request.archive.stem,size=size)],
                        total_bytes=size)
        plan.already_done=0
        root.after(0, lambda: window.set_plan(plan) if not window._closed else None)

    threading.Thread(target=_plan, name="plan-single", daemon=True).start()
    def finished(job):
        outcome['code']=0 if job.succeeded else 1
        from services.catalog_status import status_from_run,write_status
        write_status(config.library_root,status_from_run(job.plan,job),logger)
        if job.succeeded:
            root.quit()
    window.on_finished=finished
    root.mainloop()
    return outcome['code']

def _handle_multi_uri(uri,config,logger):
    """A selection of games from the catalog, unpacked in one batch window.

    Each archive in the request has already been validated by parse_multi_uri against
    the library root. The plan is built directly rather than by scanning a category,
    so the multi-select can span categories or pick individual games.
    """
    from core.uri_actions import UriRefused,parse_multi_uri,safe_folder_name
    try:
        request=parse_multi_uri(uri,config.library_root,config.extract_folders)
    except UriRefused as refused:
        logger.warning('EXTRACT',f'URI_REFUSED uri=[{uri[:160]}] reason=[{refused}]')
        print(f"{APP_NAME}: {refused}")
        return 2
    from services.batch_extract_service import BatchPlan,BatchItem
    from ui.batch_extract_window import run_batch_window
    import tkinter as tk
    import tkinter.messagebox as messagebox
    from services.extract_service import ExtractService
    root=tk.Tk(); root.withdraw()
    outcome={'code':0}

    # Pre-validate every archive is readable by 7z before opening any UI. If 7z cannot
    # open one (corrupt download, locked by another process, antivirus holding it,
    # wrong archive format) the window would just flash and close - show a clear
    # dialog instead so the reader knows exactly what is wrong.
    tool, _tool_reason = ExtractService.find_tool()
    if tool:
        for archive, _pre_dest in request.archives:
            probe = subprocess.run([tool, 'l', str(archive)],
                                   stdin=subprocess.DEVNULL, capture_output=True,
                                   text=True, errors='replace', creationflags=NO_WINDOW)
            if probe.returncode != 0:
                detail = (probe.stdout + probe.stderr).strip()[-300:]
                messagebox.showerror(
                    "Cannot open archive",
                    f"7-Zip could not read {archive.name}.\n\n"
                    f"The archive may be corrupt, still being copied, open in another "
                    f"program, or locked by antivirus on this PC.\n\n"
                    f"7-Zip said: {detail or '(no detail)'}"
                )
                try:
                    root.destroy()
                except tk.TclError:
                    pass
                return 1
    else:
        messagebox.showerror(
            "No extraction tool",
            "The bundled 7z.exe is missing beside the app, so nothing can be unpacked.\n\n"
            "The app's runtime folder should contain 7z.exe. This copy may be incomplete."
        )
        try:
            root.destroy()
        except tk.TclError:
            pass
        return 1

    plan_holder={}
    window=run_batch_window(root,logger=logger,
                            password=str(config.settings.get("zip_password","") or ""),
                            scanning=True)
    window.cancel_btn.configure(state="disabled", text="CANCEL")
    window.cancel_btn.configure(command=lambda: _cancel_planning(window, plan_holder, root, outcome))

    def _plan():
        # Build a name_map from catalog metadata so extraction folders use the clean
        # Steam name + release date instead of the messy archive filename stem.
        name_map=build_name_map(logger, config.library_root)

        plan=BatchPlan(destination=request.destination,
                        category=f"{len(request.archives)} selected games")

        used=set()
        for archive,pre_dest in request.archives:
            # Use the clean Steam name + release date from catalog metadata when available,
            # falling back to the archive stem.
            entry=name_map.get(archive)
            if entry:
                steam_name, release_date = entry
                clean = f"{steam_name or archive.stem}"
                if release_date:
                    clean = f"{clean} - {release_date.replace(',', '')}"
                leaf = safe_folder_name(clean)
            else:
                leaf = pre_dest.name
            if leaf in used:
                suffix=2
                while f"{leaf} ({suffix})" in used: suffix+=1
                leaf=f"{leaf} ({suffix})"
            used.add(leaf)
            target=request.destination/leaf
            try: size=archive.stat().st_size
            except OSError: size=0
            plan.items.append(BatchItem(archive=archive,destination=target,
                                        name=archive.stem,size=size))
        plan.total_bytes=sum(item.size for item in plan.items)
        root.after(0, lambda: window.set_plan(plan) if not window._closed else None)

    threading.Thread(target=_plan, name="plan-multi", daemon=True).start()
    def finished(job):
        outcome['code']=0 if job.succeeded else 1
        from services.catalog_status import status_from_run,write_status
        write_status(config.library_root,status_from_run(job.plan,job),logger)
        if job.succeeded:
            root.quit()
    window.on_finished=finished
    root.mainloop()
    return outcome['code']

def _handle_batch_uri(uri,config,logger):
    """A category's Extract All, or the whole library's.

    The only difference from a single extract is that this one opens a window. A single archive finishes in a
    minute and a window per click would be worse than no feedback, which is why _handle_uri stays headless; a
    category is twenty games and the library is a hundred and seventy-six, which is hours, and silence over hours
    is indistinguishable from a hung run. So the batch gets the window and the single keeps not having one.

    tkinter is imported here rather than at module scope for the same reason the single path avoids it: a
    console invocation of --uri must not pay for Tk it will not use.
    """
    from core.uri_actions import UriRefused,parse_batch_uri
    try:
        request=parse_batch_uri(uri,config.library_root,config.extract_folders)
    except UriRefused as refused:
        logger.warning('EXTRACT',f'URI_REFUSED uri=[{uri[:160]}] reason=[{refused}]')
        print(f"{APP_NAME}: {refused}")
        return 2

    from services.batch_extract_service import plan_batch
    from services.catalog_status import status_from_run,write_status

    import tkinter as tk
    from ui.batch_extract_window import run_batch_window
    root=tk.Tk(); root.withdraw()
    outcome={'code':0}

    # Build a name_map from catalog metadata so extraction folders use the clean
    # Steam name + release date ("Game Name - 2024-01-01") instead of the messy
    # archive filename stem. Archives not in the catalog fall back to the stem.
    name_map=build_name_map(logger, config.library_root)

    # plan_batch scans every archive and sniffs each for an installer signature before the first game is
    # unpacked - minutes on a real library. The window opens first showing "Scanning library" so the reader
    # gets feedback immediately, and planning runs on a worker thread; set_plan() swaps in the real rows
    # and starts extraction when planning is done.
    plan_holder={}
    window=run_batch_window(root,logger=logger,
                            password=str(config.settings.get("zip_password","") or ""),
                            scanning=True)
    window.cancel_btn.configure(state="disabled", text="CANCEL")
    window.cancel_btn.configure(command=lambda: _cancel_planning(window, plan_holder, root, outcome))

    def finished(job):
        # Non-zero only when nothing usable came out. A run of 176 with three failures produced 173 working game
        # folders, and reporting the whole run as failed would train people to ignore the exit code.
        outcome['code']=0 if job.succeeded else 1
        # Written when the run ends, not while it is going. Nothing on the page is watching for this - the
        # file is only read the next time somebody opens the catalog - so the window is the live readout and
        # this is the durable one. A failure to write it is swallowed inside write_status: the games are
        # already unpacked by now and a browser that cannot be told must not fail the run.
        write_status(config.library_root,status_from_run(job.plan,job),logger)
        if job.succeeded:
            root.quit()

    window.on_finished = finished

    def _plan():
        plan_holder['plan']=plan_batch(config.library_root,request.destination,request.category,logger,name_map=name_map)
        # set_plan also swaps in the real destination if the empty-folder check changed it.
        root.after(0, lambda: window.set_plan(plan_holder['plan']) if not window._closed else None)
    threading.Thread(target=_plan, name="plan-batch", daemon=True).start()

    root.mainloop()
    # A closed window mid-run leaves the job cancelling itself; the code reflects what was actually unpacked.
    return outcome['code']


def _handle_open_folder_uri(uri,config,logger):
    """Opens the game folder in Explorer/Files.

    A file:// page cannot open a folder, so this goes through the same
    steamgameorganizer:// protocol handler as Extract. The path is validated
    against the library root by parse_open_folder_uri, so a malicious page
    can only ask for a folder the user already owns.
    """
    from core.uri_actions import UriRefused,parse_open_folder_uri
    try:
        folder=parse_open_folder_uri(uri,config.library_root)
    except UriRefused as refused:
        logger.warning('EXTRACT',f'URI_REFUSED uri=[{uri[:160]}] reason=[{refused}]')
        print(f"{APP_NAME}: {refused}")
        return 2
    logger.info('EXTRACT',f'URI_ACCEPTED action=open-folder path=[{folder}]')
    try:
        import os
        os.startfile(str(folder))
    except OSError as exc:
        print(f"{APP_NAME}: Could not open {folder}: {exc}")
        return 1
    return 0


def _handle_open_extracted_uri(uri,config,logger):
    """Opens the extracted game/installer folder."""
    from core.uri_actions import UriRefused,parse_open_extracted_uri
    try:
        folder=parse_open_extracted_uri(uri,config.extract_folders)
    except UriRefused as refused:
        logger.warning('EXTRACT',f'URI_REFUSED uri=[{uri[:160]}] reason=[{refused}]')
        print(f"{APP_NAME}: {refused}")
        return 2
    logger.info('EXTRACT',f'URI_ACCEPTED action=open-extracted path=[{folder}]')
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
        logger.warning('CATALOG', f'CATALOG_REGEN_FAILED error={type(exc).__name__}: {exc}')


def _handle_play_uri(uri, config, logger):
    from core.uri_actions import UriRefused, parse_play_uri
    try:
        req = parse_play_uri(uri, config.extract_folders)
    except UriRefused as refused:
        logger.warning('PLAY', f'URI_REFUSED uri=[{uri[:160]}] reason=[{refused}]')
        print(f"{APP_NAME}: {refused}")
        return 2
    logger.info('PLAY', f'URI_ACCEPTED exe=[{req.exe}] marker=[{req.marker_dir}]')
    try:
        import subprocess
        subprocess.Popen([str(req.exe)], cwd=str(req.exe.parent), creationflags=NO_WINDOW)
    except OSError as exc:
        logger.warning('PLAY', f'LAUNCH_FAILED exe=[{req.exe}] error={type(exc).__name__}: {exc}')
        print(f"{APP_NAME}: Could not launch {req.exe.name}: {exc}")
        return 1
    return 0


def _handle_pick_launcher_uri(uri, config, logger):
    from pathlib import Path
    from core.uri_actions import UriRefused, parse_pick_launcher_uri
    try:
        marker_dir = parse_pick_launcher_uri(uri, config.extract_folders)
    except UriRefused as refused:
        logger.warning('PLAY', f'URI_REFUSED uri=[{uri[:160]}] reason=[{refused}]')
        print(f"{APP_NAME}: {refused}")
        return 2
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
        from services.catalog_status import resolve_extracted_root, update_extract_marker, _path_within
        root = tk.Tk(); root.withdraw()
        try:
            initial = resolve_extracted_root(marker_dir, config.extract_folders) or marker_dir
            picked = filedialog.askopenfilename(
                parent=root,
                title='Choose the game launcher (.exe)',
                initialdir=str(initial),
                filetypes=[('Game/application', '*.exe'), ('All files', '*.*')],
            )
            if not picked:
                return 0
            exe = Path(picked)
            bases = [Path(b).expanduser() for b in (config.extract_folders or [])]
            if exe.suffix.lower() != '.exe' or not exe.is_file() or not any(_path_within(exe, b) for b in bases):
                messagebox.showerror(APP_NAME, 'Please choose a .exe file inside the extracted game folder.')
                return 2
            update_extract_marker(marker_dir, logger=logger, launch_target=str(exe.resolve()))
            logger.info('PLAY', f'LAUNCHER_SET marker=[{marker_dir}] exe=[{exe}]')
        finally:
            try:
                root.destroy()
            except Exception:
                pass
    except Exception as exc:
        logger.warning('PLAY', f'PICK_LAUNCHER_FAILED marker=[{uri[:120]}] error={type(exc).__name__}: {exc}')
        print(f"{APP_NAME}: {exc}")
        return 1
    _regenerate_catalog_and_open(config, logger)
    return 0


def _handle_mark_installed_uri(uri, config, logger):
    from core.uri_actions import UriRefused, parse_mark_installed_uri
    try:
        marker_dir = parse_mark_installed_uri(uri, config.extract_folders)
    except UriRefused as refused:
        logger.warning('SETUP_DONE', f'URI_REFUSED uri=[{uri[:160]}] reason=[{refused}]')
        print(f"{APP_NAME}: {refused}")
        return 2
    try:
        from services.catalog_status import mark_setup_done
        mark_setup_done(marker_dir, extract_folders=config.extract_folders, logger=logger)
        logger.info('SETUP_DONE', f'MARKED marker=[{marker_dir}]')
    except Exception as exc:
        logger.warning('SETUP_DONE', f'MARK_FAILED marker=[{marker_dir}] error={type(exc).__name__}: {exc}')
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

def _extract_to_disk(args,config,logger):
    """The --extract command line: extract, print where it went, and exit."""
    # config.extract_folder is already the folder extracted games go in - it is what the catalog's Extract
    # button writes to and what the protocol handler is restricted to. It used to have "Extracted" appended
    # again, so every --extract without an explicit --dest landed one level deeper than the same game
    # extracted from the catalog, and the app's own message named the doubled path: "Extracted 2 file(s) to
    # C:\Users\...\Downloads\Extracted\Extracted".
    destination=Path(args.dest).expanduser() if args.dest else config.extract_folder
    result=_extract(Path(args.extract),destination,config,logger,args_password=args.zip_password)
    print(result.message)
    return 0 if result.ok else 1

def _extract(archive,destination,config,logger,args_password=""):
    from services.extract_service import ExtractService
    service=ExtractService(logger)
    result=service.extract(archive,destination,password=args_password or str(config.settings.get("zip_password","") or ""))
    print(result.message)
    return result

def _needs_setup(config):
    """Whether this PC has ever been configured: a saved library root that exists on disk.

    settings.json is written only by the wizard, so on a copied folder it does not exist at all -
    and the default library root is a path that does not exist either. Both mean the same thing to
    a reader opening the app: nothing is configured, so nothing will scan.
    """
    if not config.settings_file.is_file(): return True
    root = config.library_root
    return not root or not root.is_dir()


def main():
    parser=argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--mock",action="store_true",help="Run deterministic mock data; no real library changes")
    parser.add_argument("--diagnostics",action="store_true")
    parser.add_argument("--health",action="store_true")
    parser.add_argument("--version",action="store_true")
    parser.add_argument("--uri",nargs="?",const="",default=None,
                        help="Handle a steamgameorganizer:// link. Empty means launch the GUI, so one "
                             "desktop entry can serve both the menu and the protocol handler")
    parser.add_argument("--extract",help="Extract an archive to the extract folder, then exit")
    parser.add_argument("--setup",action="store_true",
                        help="Open the setup wizard: set the game library, app folder and "
                             "extract folder for this PC, then exit")
    parser.add_argument("--dest",help="Destination folder for --extract (default: the extract folder)")
    parser.add_argument("--zip-password",default="",help="Password for an encrypted .zip or .rar")
    args=parser.parse_args()
    if args.version: print(VERSION); return 0
    # Resolve the project root so logs, config and cache always land in the same
    # place whether running from source or the frozen exe. On a borrowed HD the
    # drive letter changes but the directory layout does not: steam_game_organizer.py
    # is always at the project root, so walk up from the exe until we find it.
    exe_dir=Path(__file__).resolve().parent
    if getattr(sys,'frozen',False):
        root_path=exe_dir
        for candidate in [exe_dir]+list(exe_dir.parents):
            if (candidate/"steam_game_organizer.py").is_file():
                root_path=candidate
                break
    else:
        root_path=exe_dir
    headless=args.version or args.diagnostics or args.health or args.uri is not None or args.extract
    # For headless invocations (URI handlers, diagnostics, etc.), reuse the most recent log file
    # instead of creating a new timestamped one, so all logs from a session go to the same file.
    log_file = None
    if headless:
        log_dir = root_path / "logs"
        if log_dir.is_dir():
            recent = sorted(log_dir.glob("organizer-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
            if recent:
                log_file = recent[0]
    config=AppConfig(root_path, log_file=log_file); config.mock_mode=args.mock; config.ensure_directories()
    logger_kwargs={"console": True} if headless else {}
    logger=AppLogger(config.log_file,**logger_kwargs)
    logger.install_excepthook()
    if args.diagnostics: print(Diagnostics(config,StateStore(),logger).report()); return 0
    if args.health: print(Diagnostics(config,StateStore(),logger).health_text()); return 0
    # The URI handler opens a result dialog for single extracts and the batch window for batch
    # extracts, so it needs Tk. It is kept before the main GUI launch so a protocol-handler click
    # from the catalog shows feedback without first drawing the full application window.
    if args.uri is not None and args.uri: return _handle_uri(args.uri,config,logger)
    if args.extract: return _extract_to_disk(args,config,logger)
    # The setup wizard is the one path that opens a window without a main window, and it is
    # the first-run path on a PC where the protocol handler is not registered yet - which is
    # exactly when the catalog's own setup button cannot be clicked.
    if args.setup: return _open_setup(config,logger)
    # A copied folder has never been configured: settings.json does not exist, and the default
    # library root is a path that is not there. Opening the GUI on that would put the reader in
    # the Scan screen looking at an empty folder with no indication of what to do, so the
    # wizard opens first. It is a Toplevel-free window of its own and exits when closed; the
    # reader then relaunches and the app opens normally.
    # wizard opens first. When the save succeeds the app hands off to the main
    # window without an extra launch; if the reader dismissed it without saving,
    # the wizard's 0 return keeps the app in setup mode until a save succeeds.
    needed_setup = _needs_setup(config)
    setup_result = _open_setup(config, logger) if needed_setup else None
    if setup_result is not None: return setup_result
    if needed_setup:
        try:
            from services.catalog_service import CatalogService
            CatalogService(logger, extract_folders=config.extract_folders).generate(config.library_root)
        except Exception as exc:
            logger.warning('SETUP', f'CATALOG_REGEN_FAILED error={type(exc).__name__}: {exc}')
    try:
        import tkinter as tk
        from app.application import Application
    except ModuleNotFoundError as exc:
        if exc.name == "tkinter":
            # The message names Windows because that is the only platform this runs on. It used to suggest
            # the Debian package python3-tk and re-exec through flatpak-spawn, neither of which exists here,
            # so a missing tkinter produced instructions for a different operating system.
            parser.error("Tkinter is required for the GUI. Re-run the Python installer and tick 'tcl/tk and IDLE'.")
        raise
    root=tk.Tk(); return Application(root, args.mock, config=config).run()
if __name__=="__main__": raise SystemExit(main())

