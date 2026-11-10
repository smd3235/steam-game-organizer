# Steam Game Organizer

Version **9.33**.

## Running

Double-click `dist/steam_game_organizer/steam_game_organizer.exe`. It ships with its own `runtime/` (Python 3.13, 7-Zip, Tcl/Tk), so a PC that has never had Python installed runs it as well as one that has.

The source form, `steam_game_organizer.py`, needs Python 3.13 and is what the protocol handler and the catalog's fallback command run.

Build the frozen exe with:

```sh
python tools/build_frozen.py
```

PyInstaller is a build-time dependency, not part of the app, and is installed in `runtime/Lib/site-packages` so the frozen-build layout test can run; a reader does not need to install it.

## Workflow

**Scan → Automatic Verification → Review → Organize → Artwork → Done**

Scan is a real operation; verification starts automatically after discovery and completes before the review queue is populated.

Accepted archives are assigned a category from their Steam genres by default and can be changed during Review. Organize creates `category/game - steam-release-date/` folders containing the archive, cached artwork, and a Steam store shortcut. Existing game-folder names receive a numbered suffix instead of being overwritten.

Steam matches, manual title corrections, and category decisions persist under `config/` for reuse on later scans. Artwork cache files expire according to `artwork_cache_days` in settings (10 days by default).

Organization never performs recursive cleanup. After moving an archive, it may remove only that archive's old immediate game folder, and only when every remaining entry in it is a picture or an organizer Steam shortcut the app wrote itself — one unrecognised file, one subdirectory, one symlink, any archive, or any folder the app did not create vetoes the removal. Empty folders left behind by a re-categorise, and empty categories after a sweep, are moved to `Archive/` rather than deleted, so they can be reviewed before anything is thrown away.

**Extract** unpacks an archive into its **Extract to** folder. Repacks that are installers rather than ready-to-play games — a `setup.exe` with one or more `.bin` files, or an archive holding an `.iso` — are recognised and relocated into a `Needs Install` subfolder, marked with the amber "Needs install" badge on the catalog page. Catalog actions are state-aware: **Extract** / **Re-extract** (stale/update), **Open installer** (needs install), **Play** (when a saved/valid launcher is available), **Pick launcher** (choose the main `.exe` once and persist it in `.sgo-extract-info`), **Mark installed** (explicit setup-complete persistence for needs-install flows), **Open extracted** (ready), and **Open source** (library/archive folder). Open extracted/installer and Play/Pick launcher/Mark installed use secure `steamgameorganizer://` handlers validated under configured extract folders; extraction markers preserve compatible `launch_target`/`setup_done` state across re-extract. Use **Refresh catalog** after external changes.

**Launcher discovery** (`services/catalog_status.py:discover_game_launchers`): conservatively scans the extracted root (max depth 3, 250 candidates) for playable `.exe` files, filtering installers/uninstallers/crash handlers/redistributables/helper tools (Unity crash handlers, `BugReporter`, `elevate`, `createdump`, `UEPrereqSetup`, `QuickSFV`, `ffmpeg`, `Spatial Media Metadata Injector`, full JRE toolchain) and scoring by depth/name/size; returns a ranked list for user choice via Pick launcher. The chosen `launch_target` persists to `.sgo-extract-info` and subsequent Play actions use it.

## Architecture

The application is Python-only. Services are composed in `app/application.py` and coordinated by `app/controller.py`.

Windows is the only platform. The GUI uses Tkinter; Pillow is the one runtime dependency because tkinter's `PhotoImage` cannot decode the JPEG artwork Steam serves. Headless commands (`--version`, `--diagnostics`, `--health`) run without Tkinter, and a machine with no Tkinter is reported by the test suite as a broken install rather than quietly skipping window tests.

## Release rules

- Entry point: `steam_game_organizer.py`
- Launcher: `Steam Game Organizer`
- Default Games directory: `Downloads/Games` (`%USERPROFILE%\Downloads\Games`), from `Path.home()`, not a hard-coded path
- No `main.py` entry point; no `.desktop` launcher
- `ruff check .` is the lint gate; each ignored rule carries its reason in `ruff.toml`

The suite is expected to report `OK` with no skips — anything else is a failure.

Register the `steamgameorganizer://` handler so the catalog's Extract button reaches the machine:

```text
python tools\install_protocol_handler.py            install for this machine
python tools\install_protocol_handler.py --check    report what is registered now
python tools\install_protocol_handler.py --export FILE   write a .reg for another PC
```

## Using the library on another PC

The whole library travels on one disk. Copy the folder that holds the games and the app together, and the copy has everything: the archives, the organized library, the app, and the catalog page.

On the new PC:

1. Start the app once from its own folder:

   ```text
   runtime\python.exe steam_game_organizer.py --setup
   ```

   Nothing needs to be installed first: the folder carries its own Python and 7-Zip in `runtime/`. The wizard opens with the three folders — game library, app folder, extract folder — each with a Browse button. The app folder is recognized automatically; the other two default to the app's current answers. Saving writes the three folders beside the app.

   Drive letters change between PCs. When the stored library path points at a drive that does not exist, the app auto-resolves the library root to the folder it is running beside — the library always lives next to the app — and the wizard opens so you pick where extraction goes. Nothing on disk is touched until you save.

2. Open `Game Library.html`. The Game folder and Extract to boxes are remembered by the browser and rebuild every Extract link from what they hold, and **Set up on this PC** carries both into the wizard, so a folder that still needs changing is changed in one place.

   The page's "Unpacked" badges are checked against your extract folder when the page is generated. If you delete an extraction outside the app, the page still shows the badge it baked in — a `file://` page cannot re-scan disk itself. Click **Refresh catalog** to regenerate the page and re-check what is unpacked against what is actually on disk now.

The `runtime/` folder makes the copy self-contained: a Python that runs the link handler and wizard (Tcl/Tk included), and a 7-Zip that unpacks the archives. It needs Windows 10 or later (the bundled Python uses the Universal C Runtime). It is rebuilt from a machine's installs with `python tools\bundle_runtime.py`; `runtime\python.exe tools\bundle_runtime.py --check` reports what it holds, including whether the registered interpreter is the bundled one. Licenses for everything inside are in `runtime\THIRD-PARTY-NOTICES.txt`. A PC that already has Python and 7-Zip works too: the app answers with the bundled copies first, so behaviour is the same either way.

If the disk arrives under a different drive letter, type the new folders, save, and the links work again.

**Where the app lives, relative to the games: beside the game library, never inside it.** Every walk of the library treats each subfolder as a game category, so an app folder inside the library would appear as a category of fake games, and the app's own `core/`, `services/` and `ui/` would be moved. Keep the app at `D:\Game Installers\0. Steam Game Organizer\` beside `D:\Game Installers\Steam Games\`.

The app must not rename its own folder: the link registration, the settings beside it, and the running process all point at the path it was started from, so the name is chosen when the folder is copied.
