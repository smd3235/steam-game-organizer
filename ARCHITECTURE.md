# Architecture — v9.33

Windows is the only platform. Pure standard library for everything except image decoding: Pillow is a runtime dependency, because tkinter's own `PhotoImage` reads PNG and GIF and the artwork Steam serves is JPEG.

## Entry point

- `steam_game_organizer.py` — process entry point. Also the `--uri` target for `steamgameorganizer://` links, the source of `--setup` (the three-folder setup wizard), and of `--version`, `--diagnostics`, `--health` and `--mock`, which run without tkinter. On a frozen launch it pre-loads `services/catalog_service.py` and `services/extract_service.py` from the bundle's own filesystem because PyInstaller marks them as "invalid module"; on source launches they import normally and the pre-load is skipped.
- `steam_game_organizer.exe` — the frozen form of the entry point, produced by `tools/build_frozen.py` from `steam_game_organizer.spec`. It is the thing a reader double-clicks; the `.py` is what the protocol handler and the catalog's fallback command run, and it needs Python installed.

## Frozen build

- `steam_game_organizer.spec` — a PyInstaller onedir spec, written by hand. The datas are listed explicitly so the contents are reviewable rather than inferred from an import scan, which would drag in the stdlib test suite and the whole tcl/tk tree.
- `tools/build_frozen.py` — runs the spec, then moves the exe into the bundle folder and lifts `core/`, `services/`, `runtime/` and the rest out of `_internal/`. PyInstaller's COLLECT stage puts every data and binary into `_internal/` by default, which is wrong here: the app resolves its project root as `Path(__file__).resolve().parent` and walks it for `runtime/7z.exe` and the other sibling folders, so a build that left those inside `_internal/` would ship an app that cannot unpack anything. The destination paths in `datas` are relative to `_internal/`, so the lift is a post-build step rather than a spec change.
- The exe lives inside the bundle, not beside it. The default onedir layout puts the exe at `dist/<name>.exe` and the bundle at `dist/<name>/`, which would leave the runtime one folder out of reach; moving the exe restores the source-checkout layout the app already assumes.
- `dist/` and `build/` are build artefacts, not shipped source: a fresh build writes an `EXE-00.toc` whose XML declaration reads `<?xml version="1.0"`, which the release-structure version scanner reports as a declared version. `tests/test_release_structure.py` excludes both directories from its walk.
- `runtime/` at the project root is the vendored Python 3.13 (with Tcl/Tk) plus 7-Zip, copied in by `tools/bundle_runtime.py`. The same tree ships inside the frozen bundle as `dist/steam_game_organizer/runtime/`. It must ship: `build_frozen.py` verifies `runtime/7z.exe` exists before reporting success, because without it extraction tools report no archiver. `runtime/` is excluded from lint and version scans; its files declare Python's and 7-Zip's versions, which are not this app's version.
- The build is `onedir`, not `onefile`: a one-file build repacks the interpreter into a temp folder on every launch, which is slow and unnecessary since the bundled runtime already ships a full interpreter for extraction tools to call.

## Wiring

- `app/application.py` — composition root and lifecycle owner; builds the services and the window.
- `app/controller.py` — asynchronous workflow orchestration. Owns the phases a scan runs through — cleanup, dedupe, cross-category duplicate sweep, discover, audit, catalog — and journals every move so the whole run can be undone.
- `app/jobs.py` — cancellable worker execution.
- `app/events.py` — the small observer the controller publishes progress on.

## core

- `core/config.py` — settings, library paths, extract folders. Defaults come from `Path.home()`, not `/home/deck`. `AppConfig.load()` auto-resolves `library_root` to the folder beside the app when the stored path does not exist on this machine — the library always lives next to the app whatever drive letter a borrowed HD gets. Extract folders are kept as stored so the borrower chooses where extraction goes through the Setup wizard rather than having a path silently rewritten. Every path the app writes is derived from the project root, so a test can point `AppConfig` at a temp tree (`tests/tk_support.py:sandbox_app`) instead of writing the developer's real `config/`, `cache/` and `logs/`.
- `core/constants.py` — version, archive extensions, categories, compression and memory-threshold tables, `APP_NAME`, `ENTRY_POINT`, `VERSION`, `USER_AGENT`, `NO_WINDOW`, and the reserved directory set.
- `core/models.py` — `GameArchive`, `SteamMatch`, `ArtworkResult`, `ConversionResult`, `OrganizationDecision`, `ScanResult`, `AppState`, `LibrarySummary` — plain-data containers with no logic.
- `core/uri_actions.py` — parses a `steamgameorganizer://` URI into an `ExtractRequest`, or refuses it. Owns `SCHEME`, the one definition of the scheme, and `SYSTEM_PATHS`, the folders a typed destination may not sit inside — the Windows folders read from the environment. Also parses `setup` (three folder prefills), `refresh-catalog` (regenerates `Game Library.html` against the live library), `open-folder` (library source folder), and `open-extracted` (extracted/installer folder; validated under configured extract folders and resolved).
- `core/logger.py` — `AppLogger` — timestamped, component-tagged, correlation-id'd file logging.
- `core/state.py` — `StateStore` — thread-safe in-memory app state with deepcopy.
- `core/exceptions.py` — `OrganizerError`, `CancellationError`.

## services

- `services/archive_service.py` — archive discovery and scan telemetry.
- `services/batch_extract_service.py` — plans and runs batch extractions outside the library; smallest-first sort, `(n)` collision handling, installer archives routed to `Needs Install`, skip-if-already-extracted.
- `services/catalog_status.py` — writes `Game Library.status.js` beside the catalog after every batch/run and provides marker helpers for `.sgo-extract-info` (`read_extract_marker`, `resolve_extracted_root`, `archive_has_changed_since_extraction`) so catalog/status/URI logic can resolve actual extracted roots safely.
- `services/catalog_service.py` — generates the browsable library page (`Game Library.html`) and the artwork banner. Holds the embedded HTML, CSS and JavaScript. The page carries a **Refresh catalog** button (`steamgameorganizer://refresh-catalog`) because a `file://` page cannot re-scan disk; unpacked/needs-install/stale state is resolved at generation time across configured extract roots using extraction markers (`extracted_root`/timestamps/`launch_target`/`setup_done`) and conventional layouts. Cards expose dynamic actions (Play/Pick launcher/Mark installed when applicable, Extract/Re-extract, Open installer/Open extracted, Open source) and embed `data-extracted-path`/`data-marker-dir`/`data-launch-target`/`data-play`/`data-pick-launcher`/`data-mark-installed` for secure protocol links.
- `services/extract_service.py` — finds the archive tool and performs extraction. `find_tool()` / `find_unrar()` check `PATH` and then the real install folders (`C:\Program Files\7-Zip`, `%ProgramFiles%\WinRAR`), because 7-Zip is not on `PATH` on a normal PC. It writes `.sgo-extract-info` (archive size/mtime, extracted root, `needs_install`) and preserves compatible user-state fields (`launch_target`, `setup_done`, `installed_at`) from prior marker candidates across re-extract while recomputing extraction facts.
- `services/installer_detect.py` — recognises archives that unpack to a Windows installer (setup.exe + .bin, or a mountable .iso) so they are relocated to `Needs Install` rather than left as a game folder holding no runnable game.
- `services/library_service.py` — the whole-library audit — Steam link normalization plus artwork refresh, which reports per folder as it goes. Runs `_sweep_empty_categories()` after scans: empty game folders and empty categories are moved to `Archive/` rather than deleted, so the user can review them before deleting.
- `services/organizer_service.py` — category moves, collision-safe filenames, and zip/rar → 7z conversion. Empty source folders left behind by a re-categorise are moved to `Archive/` rather than deleted.
- `services/rollback_service.py` — Python JSON transaction journal. Writes/reads `last-organization.json`, restores each archived file to its source, and prunes emptied folders this run created into `Archive/` (never deletes a folder it did not make).
- `services/setup_service.py` — the checks behind the setup wizard and the one place its answers are saved. Validates the three folders (a library that holds no games, an app folder with no entry point, an extract folder inside the library are all refused), saves the library root and extract folder, and registers the `steamgameorganizer://` handler against the chosen app folder. The registry write is injectable, so a test watches a registration without touching `HKCU`.
- `services/steam_service.py` — direct Steam Store search/details API, with a mock backend.
- `services/artwork_service.py` — cached Steam artwork retrieval with source fallback.
- `services/banner_art.py` — composes the banner image.
- `services/catalog_status.py` — writes `Game Library.status.js` beside the catalog after every batch/run and provides marker helpers for `.sgo-extract-info` (`read_extract_marker`, `resolve_extracted_root`, `archive_has_changed_since_extraction`, `get_launch_target`, `update_extract_marker`, `mark_setup_done`) so catalog/status/URI logic can resolve actual extracted roots and launcher/user state safely. `discover_game_launchers()` conservatively scans the extracted root (max depth 3, 250 candidates) for playable `.exe` files, filtering installers/uninstallers/crash handlers/redistributables/helper tools (Unity crash handlers, `BugReporter`, `elevate`, `createdump`, `UEPrereqSetup`, `QuickSFV`, `ffmpeg`, `Spatial Media Metadata Injector`, full JRE toolchain) and scoring by depth/name/size; returns a ranked list for user choice via Pick launcher.
- `core/uri_actions.py` — parses a `steamgameorganizer://` URI into validated requests or refuses it. Owns `SCHEME`, the one definition of the scheme, and `SYSTEM_PATHS`, the folders a typed destination may not sit inside — the Windows folders read from the environment. Parses `setup`, `refresh-catalog`, `open-folder` (library source folder), `open-extracted` (extracted/installer folder, resolved under configured extract folders), `play` (validated `.exe`/marker launch target under configured extract folders), `pick-launcher` (marker path), and `mark-installed` (marker path).

## ui

- `ui/main_window.py` — fixed single-window workflow shell and the left nav rail.
- `ui/scan_view.py`, `ui/review_view.py`, `ui/organize_view.py`, `ui/artwork_view.py`, `ui/done_view.py` — the five views.
- `ui/batch_extract_window.py` — the batch extraction queue window — hours of 7z needs a visible queue.
- `ui/setup_window.py` — the three-folder setup wizard. A `Toplevel`, like the batch window, because the protocol handler runs with no main window and this is the only thing that has to appear.
- `ui/theme.py` — the ttk theme and the shared widgets (`PhaseTimeline`, `ActivityFeed`, `Sparkline`, the wheel and scroll helpers). Re-exports the palette.
- `ui/palette.py` — the colours, in one place, outside the UI layer so the controller can use them too.
- `ui/widgets/` — `game_card`, `game_list`, `artwork_panel`, `metadata_panel`.

Theme colours reach a view only through an explicit import. They were star-imports until 9.8, which meant every view silently depended on every colour anyone had ever added.

## utils

- `utils/filename_utils.py` — `normalize_name`, `identity_key`, `version_key` — title normalization, identity matching, version ordering.
- `utils/formatting.py` — human-readable sizes and durations.
- `utils/desktop.py` — `os.startfile`-based folder and URL opening (Windows only; no `xdg-open`).
- `utils/treewalk.py` — junction/symlink-safe recursive walk (no infinite loops).

## debug

- `debug/diagnostics.py` — diagnostics and health report output.

## tools

Development and installation scripts, not part of the application:

- `tools/build_frozen.py` — runs the PyInstaller spec, lifts the exe out of `_internal/`, backs up `config/`, `cache/` and `logs/` before wiping the old bundle and restores them after.
- `tools/bundle_runtime.py` — copies Python + Tcl/Tk and 7-Zip into `runtime/`.
- `tools/install_protocol_handler.py` — registers `steamgameorganizer://` under `HKCU\Software\Classes`, per user, so no elevation is needed. It reads the value back afterwards rather than reporting the write as a success it did not check. There is no `.desktop`/`xdg-mime` path here; the only other platform that one ever applied to is no longer a target.
- `tools/overnight_repair.py` — space-checked, one-at-a-time archive repair.
- `tools/analyze_screenshot.py`, `tools/layout_audit.py`, `tools/dead_space_audit.py` — the visual checks behind the window geometry tests — palette/off-palette sampling, clipping and overlap, and unused space.
- `tools/build_icon.py`, `verify_archives.py`, `tk_probe.py`.

## tests

`runtime\python.exe -m unittest discover -q` — 781 tests, `OK` with no skips expected. The frozen-build test runs because PyInstaller is installed in the bundled runtime; any skip that is not that one is a bug.

- `tests/tk_support.py:sandbox_app` — roots `AppConfig` in a temporary tree; `close_root` cancels pending Tk `after` callbacks before `destroy()` so geometry tests don't leave `invalid command name _tick` noise on stderr.
- `tests/test_project_state_guard.py` — snapshots every file under `config/`, exercises `AppConfig`, `save()`, `remember_category()`, the scan summary, the undo journal and a real window against a temporary tree, and fails if any byte or mtime moved. `PROJECT_UNDER_TEST = None` aims writes at a temp tree; point it at `ROOT` to watch both tests fail and prove the guard works.
- `tests/test_zero_skips.py` — parses every test file with `ast` and fails on any `unittest.skip`, `skipIf`, `skipUnless`, `expectedFailure`, `SkipTest`, or `self.skipTest`. The only exemption is `tests/test_frozen_build.py`'s `@unittest.skipUnless(HAS_PYINSTALLER)` build test — PyInstaller is installed in the bundled runtime so it runs rather than skips. Uses AST rather than grep so comments and docstrings naming skip constructs don't trigger it — this repository documents its own removals at length.
- `tests/test_platform.py` — Windows is the only platform. Parses each source module and fails on a string literal naming `xdg-open`, `xdg-mime`, `mimeapps.list`, `flatpak`, `/proc/meminfo`, a POSIX home path, or a Linux browser package name. Skips comments and docstrings. Legacy `.desktop` filenames the app still deletes are exempt by design.
- `tests/test_dead_code.py` — asserts superseded names (`wait_for_cancel`, `CATEGORY_GENRES`, `ConfigurationError`, `ServiceError`, `_steam_link`, `STAGE_COST`, `_activity_wheel`) are gone; each entry documents what replaced it.
- `tests/test_release_structure.py` — walks every shipped file (excluding `cache/`, `logs/`, `config/`, `runtime/`, `build/`, `dist/`, `__pycache__`, `.git`, `Processing`) for versions declared in production code; fails if production code declares a version outside `VERSION.txt`, `USER_AGENT`, or `CHANGELOG.md`. Prose and `# vX.Y change log:` notes are exempt via `code_before_comment` / fenced-block handling.
- `tests/test_render_integrity.py` — asks what a widget was told to paint rather than how big it is, which is what catches a panel that laid out correctly and rendered blank.
- `tests/test_contrast.py` — a `TestCase`, not a script, so the audit cannot quietly stop running.

A test that cannot run is worse than no test, because it is reported as present. `tests/test_displayed_data.py` imported a module that does not exist, so unittest collected it as one error and executed none of its 21 tests — including the two that would have caught the skipped-card confidence pill and the all-or-nothing scan summary.

There is one composition path and no shell backend compatibility layer.

## Performance Optimizations (v9.33)

All optimizations below are in the current development version and are cumulative across work done earlier this cycle. Each one eliminates redundant work — repeated filesystem walks, repeated `7z` subprocess calls, or repeated log-file stats — rather than changing what the app produces.

### Caching

| # | File | Change | What It Eliminates | Impact |
|---|------|--------|-------------------|--------|
| O1 | `services/catalog_service.py` | Module-level `_COLLECT_CACHE` with `threading.Lock`, shared across all `CatalogService` instances | Full library walk re-done for every new `CatalogService()` instance | **High** — one walk per process instead of one per instance |
| O2 | `steam_game_organizer.py` | `build_name_map(logger, library_root)` helper; replaces 3 duplicated inline `_collect()` blocks in `_handle_uri`, `_handle_multi_uri`, `_handle_batch_uri` | 3 separate library walks per URI session (single / multi / batch extract paths) | **High** — 3× fewer full-library traversals |
| O3 | `services/organizer_service.py` | `_manifest_cache` keyed by `(path, size, mtime_ns)` in `_archive_manifest()` | Redundant `7z l -slt` calls per archive conversion | **Medium-High** — one manifest read per archive identity instead of N |
| O4 | `services/steam_service.py` | `_appid_in_archive_cache` keyed by `(path, size, mtime_ns) → appid` | Redundant `7z` subprocess calls per Steam AppID lookup | **High** — subprocess spawn avoided on cache hit |
| O5 | `services/archive_service.py` | `_installer_kind_cache` keyed by `(path, size, mtime_ns)` | Redundant `7z l -slt` / zipfile index reads across batch-extract + extract + catalog | **Medium-High** — installer sniff cached per archive identity |
| O6 | `services/organizer_service.py` | `_game_files()` cached per conversion; `_extraction_is_short(game_files=...)` accepts pre-computed result | Redundant `rglob('*')` walks during repack verification | **Medium** — one rglob instead of multiple per conversion |
| O7 | `services/organizer_service.py` | `_content_folder_cache` for `_content_folder_name()` | Redundant folder-name lookups | **Low** — small string op cached |

### Single-Walk Sharing

| # | File | Change | What It Eliminates | Impact |
|---|------|--------|-------------------|--------|
| O8 | `services/extract_service.py` | `extract()` collects `files` once via `rglob("*")` and passes it to `find_installer(destination, entries=files)` and `_flatten_wrapper_folder(destination, files=files)` | 3–4 separate `rglob("*")` walks over the same destination tree (count, zip-slip validation, installer detection, wrapper flattening) | **Low-Medium** — one walk instead of several |
| O9 | `services/installer_detect.py` | `find_installer(root, entries=None)` accepts pre-computed entries | Second `walk_files()` call inside installer detection | **Low-Medium** — reuse caller's file listing |
| O10 | `services/library_service.py` | `convert_pending_archives(work=...)` accepts pre-computed `(game_dir, pending, appid, name)` tuples from `pending_candidates()`; `app/controller.py` passes `work` | Library walked once inside `pending_candidates()` plus once inside `convert_pending_archives()` | **Low-Medium** — one walk instead of two per repair pass |

### I/O Reduction

| # | File | Change | What It Eliminates | Impact |
|---|------|--------|-------------------|--------|
| O11 | `core/logger.py` | `AppLogger.write()` tracks approximate bytes since last rotate check; `_rotate()` only invoked every ~500KB accumulated | `stat()` on the active log file on every `write()` call during high-frequency scan logging | **Low** — CPU overhead only, not user-facing |

### Cache Invalidation

- `CatalogService.generate()` clears `_COLLECT_CACHE` so a second call after the library changed (game moved category) gets fresh data.
- `CatalogService.invalidate_summary()` clears `_COLLECT_CACHE` for paths that change the library without regenerating the catalog (Undo).
- All stat-based caches (O3–O5) key on `(path, size, mtime_ns)` and self-invalidate when the file changes.

### Verification

- `ruff check .` — clean (no new errors; pre-existing `tests/test_regressions.py` indentation bugs are unrelated).
- `runtime\python.exe -m unittest discover -q` — 738 tests ran, 0 failures from changes (4 pre-existing `test_regressions.py` collection errors unrelated).
- `python tools/build_frozen.py` — frozen exe rebuilt; `dist/steam_game_organizer/runtime/7z.exe` verified present.
- Dated changelog entries added under `## 9.33` for each batch of changes.
