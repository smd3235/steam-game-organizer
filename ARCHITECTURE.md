# Architecture — v9.33

[![Version 9.33](https://img.shields.io/badge/version-9.33-blue.svg)](CHANGELOG.md)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-green.svg)](README.md)
[![Lint: ruff](https://img.shields.io/badge/lint-ruff-important.svg)](ruff.toml)
[![Tests: unittest](https://img.shields.io/badge/tests-unittest-success.svg)](tests/)

---

## 📖 Table of contents

| If you want to… | Go to section |
|-----------------|---------------|
| Read this doc first (start here) | [📖 How to use this document](#-how-to-use-this-document) |
| Find where a behavior lives | [🗺️ Layer map](#-layer-map) |
| Trace a service call through the app | [🚪 Entry point & wiring](#-entry-point--wiring) |
| Read what a specific module does | [🔧 core](#-core) · [🛠️ services](#-services) · [🖼️ ui](#-ui) · [🛠️ utils](#-utils) · [🐞 debug](#-debug) · [🛠️ tools](#-tools) · [🧪 tests](#-tests) |
| See how the frozen exe is built | [🏗️ Frozen build](#-frozen-build) |
| See how the bundled runtime ships | [📦 Bundled runtime](#-bundled-runtime) |
| See service interactions and safety invariants | [🔗 Service interactions](#-service-interactions) |

---

## 🗂️ Documentation map

This file is one of four project docs. If a reader acts on any of them, they must match the code — update all four together when behavior changes.

| File | Purpose | Link |
|------|---------|------|
| **AGENTS.md** | Operating manual: how to build, test, lint, run, commit, and push on Windows | [`AGENTS.md`](AGENTS.md) |
| **ARCHITECTURE.md** | Module map and service inventory: what each module does and how they wire together | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| **project_overview.md** | What the app does, data flow, key decisions, catalog page mechanics | [`project_overview.md`](project_overview.md) |
| **README.md** | User-facing install, run, workflow, other-PC, and development-check instructions | [`README.md`](README.md) |
| **CHANGELOG.md** | Dated change log under `## 9.33` (newest first) | [`CHANGELOG.md`](CHANGELOG.md) |

**Rule:** when a change alters behavior, architecture, commands, test counts, or frozen build layout, update the affected doc(s) in the same change — not later. See [📐 Keeping Project Docs Accurate](#-keeping-project-docs-accurate) in [`AGENTS.md`](AGENTS.md).

---

## 📖 How to use this document

This file is the service inventory: what each module does and how they wire together. Read it when you need to find where a behavior lives or which services a change touches. It complements [`AGENTS.md`](AGENTS.md) (how to build, test, lint, run) and [`project_overview.md`](project_overview.md) (data flow, key decisions, catalog mechanics).

---

## ⚠️ Rules at a glance

These come from [`AGENTS.md`](AGENTS.md) and apply here too:

- **Windows only** — no POSIX paths, no `xdg-open`, `/home/`, flatpak. Anything branching on platform should raise or refuse rather than keep a second implementation.
- **Comment on every change** — every changed file must include a comment explaining what changed and why.
- **Push to GitHub on every change** — commit + verify (lint + tests + build) then push; never leave work committed locally only.
- **Changelog with every change** — add a dated entry under `## 9.33` in [`CHANGELOG.md`](CHANGELOG.md) at the same time as the code change.

---

## 🗺️ Layer map

The app is organized in four layers. Data flows from the entry point into `app/` composition, which owns the services; services talk to `core/` for config/constants/models/URI/logging; `ui/` owns the windows; `utils/` and `debug/` are helper modules; `tools/` are build/repair scripts.

| Layer | Directory | What it owns |
|-------|-----------|--------------|
| Entry point | root | `steam_game_organizer.py` — CLI flags, protocol-handler target, frozen pre-load |
| Composition / lifecycle | `app/` | `application.py` (builds services, owns window), `controller.py` (phase orchestration, journals moves), `jobs.py` (cancellable workers), `events.py` (progress observer) |
| Core | `core/` | `config.py`, `constants.py`, `models.py`, `uri_actions.py`, `logger.py`, `state.py`, `exceptions.py` |
| Business services | `services/` | `archive_service.py`, `batch_extract_service.py`, `catalog_service.py`, `catalog_status.py`, `extract_service.py`, `installer_detect.py`, `library_service.py`, `organizer_service.py`, `rollback_service.py`, `setup_service.py`, `steam_service.py`, `artwork_service.py`, `banner_art.py` |
| UI | `ui/` | `main_window.py` (shell + nav rail), 5 views, `batch_extract_window.py`, `setup_window.py`, `theme.py`, `palette.py`, `widgets/` |
| Utilities | `utils/` | `filename_utils.py`, `formatting.py`, `desktop.py`, `treewalk.py` |
| Diagnostics | `debug/` | `diagnostics.py` |
| Build / repair scripts | `tools/` | `build_frozen.py`, `bundle_runtime.py`, `install_protocol_handler.py`, `overnight_repair.py`, visual audits, backup tools, misc |
| Tests | `tests/` | guard, static, and runtime test modules |

---

## 🚪 Entry point & wiring

`steam_game_organizer.py` is the process entry point. It accepts these flags:

| Flag | Behavior |
|------|----------|
| `--setup` | Opens the three-folder setup wizard (library root, extract folder, app folder) |
| `--uri steamgameorganizer://...` | Parses a protocol request via `core/uri_actions.py` |
| `--version` | Prints `VERSION` |
| `--diagnostics` | Runs `debug/diagnostics.py` health output |
| `--health` | Health check output |
| `--mock` | Mock Steam backend (no network) |
| no flags | Launches tkinter `MainWindow`, maximized |

**Composition root:** `app/application.py` builds all services (`catalog`, `extract`, `library`, `organizer`, `rollback`, `setup`) and owns the main window. `app/controller.py` orchestrates the phases (cleanup → dedupe → cross-category duplicate sweep → discover → audit → catalog) and journals every move via `rollback_service.py` so the whole run can be undone. Progress is published on `app/events.py`; cancellable work runs through `app/jobs.py`.

**Core dependency direction:** services read `core/config.py` for project-root-derived paths and `core/constants.py` for version/archive-extensions/categories. `core/uri_actions.py` owns `SCHEME` and `SYSTEM_PATHS` (the folders a typed destination may not sit inside) and parses `steamgameorganizer://` URIs into `ExtractRequest` objects. `core/logger.py` provides `AppLogger`; `core/state.py` provides `StateStore`; `core/exceptions.py` provides `OrganizerError` and `CancellationError`.

**Service interactions:**

| Service | Interacts with | Safety invariants |
|---------|---------------|-------------------|
| `catalog_service.py` | `core/config.py`, `core/constants.py`, `services/banner_art.py`, `services/catalog_status.py` | `LibrarySummary` index retained so screens can ask placement questions without re-walking; `_COLLECT_CACHE` cleared on regeneration |
| `extract_service.py` | `core/constants.py`, `core/uri_actions.py` | Archive integrity confirmed — no silent data loss; `.sgo-extract-info` markers written beside extracted content |
| `organizer_service.py` | `core/config.py`, `core/constants.py`, `services/archive_service.py`, `services/library_service.py` | Never deletes — `rmtree` only a fallback when `library_root` is unknown; `_manifest_cache` keyed by `(path, size, mtime_ns)` |
| `library_service.py` | `core/config.py`, `services/artwork_service.py`, `services/organizer_service.py` | Whole-library audit: Steam link normalization, artwork refresh, empty-category sweep to `Archive/` |
| `rollback_service.py` | `core/config.py`, `services/organizer_service.py` | JSON transaction journal: `last-organization.json`; restores archived files to source on Undo; ownership gating via `created_game_dir` |
| `setup_service.py` | `core/config.py`, `core/uri_actions.py` | Validates three folders (library with no games, app with no entry point, extract folder inside library are refused); registers `steamgameorganizer://` under `HKCU` (registry write injectable for tests) |
| `steam_service.py` | `core/constants.py`, `core/uri_actions.py` | Direct Steam Store search/details API with mock backend; `_appid_in_archive_cache` keyed by `(path, size, mtime_ns)` |
| `artwork_service.py` | `core/config.py` | Cached Steam artwork retrieval with source fallback; 10-day expiry cache; stale entries deleted on re-init |
| `banner_art.py` | `core/constants.py` | Composes the banner image; falls back to generated name-keyed banner so no card is ever a flat grey block |
| `installer_detect.py` | `core/constants.py` | Recognizes Windows installer archives (`setup.exe` + `.bin`, or mountable `.iso`) → `Needs Install` |

---

## 🏗️ Frozen build

After any source change, rebuild with:

```powershell
python tools\build_frozen.py
```

> [!IMPORTANT]
> **MANDATORY:** Always rebuild the exe after any code change. The user runs only the frozen exe in `dist/steam_game_organizer/`, never from source.

`tools\build_frozen.py` runs PyInstaller on `steam_game_organizer.spec` (a hand-written onedir spec whose datas are listed explicitly, not inferred from an import scan — that would drag in the stdlib test suite and whole tcl/tk tree). After COLLECT, it lifts `core/`, `services/`, `ui/`, `utils/`, `app/`, `debug/`, `tools/`, `assets/`, `runtime/` out of `_internal/` into the bundle root, because `steam_game_organizer.py` resolves its project root as `Path(__file__).resolve().parent` and walks it for those siblings. Leaving them in `_internal/` puts `runtime/7z.exe` one folder out of reach and every extraction reports no archiver.

The exe is moved into the bundle folder (not beside it) to restore the source-checkout layout the app already assumes. Before wiping the old bundle it backs up `config/`, `cache/`, `logs/` to a temp dir and restores them after; it retries `rmtree` up to 5 times (Windows Defender/indexer locks) and verifies `runtime/7z.exe` exists before reporting success. The build is onedir, not onefile — onefile repacks the interpreter into a temp folder on every launch, which is slow and unnecessary.

`dist/` and `build/` are build artifacts, not shipped source, and are excluded from lint and version scans.

---

## 📦 Bundled runtime

`runtime/` at the project root is a **vendored product, not this project's code**: `tools\bundle_runtime.py` copies Python 3.13 (with Tcl/Tk, so the setup wizard opens) and 7-Zip into it from the machine's own installs. The same tree ships inside the frozen bundle as `dist/steam_game_organizer/runtime/`.

> [!TIP]
> **It must ship.** Nothing a user's PC needs is installed, so a `.gitignore` entry or a build step that drops `runtime/` breaks every copied folder. `.gitignore` deliberately has no entry for it.

| Item | Requirement |
|------|-------------|
| `runtime/7z.exe` | Required. `build_frozen.py` verifies it exists before reporting success; without it extraction tools report no archiver. |
| Lint / version scan | Excluded (`runtime` and `dist`). `ruff.toml` excludes them; [`tests/test_release_structure.py`](tests/test_release_structure.py) skips them in `NOT_SOURCE` because their files declare Python's and 7-Zip's versions — findings that are not this app's to fix. |
| Interpreter path | The bundled `python313._pth` makes `sys.path` exactly what the file says. Any new entry point or tool meant to run under the bundled interpreter must insert its own folder into `sys.path`, or it dies with `ModuleNotFoundError` on a copy. |

---

## 🔧 core

| Module | Role | Key invariants |
|--------|------|----------------|
| [`core/config.py`](core/config.py) | Settings, library paths, extract folders. `AppConfig.load()` auto-resolves `library_root` to the folder beside the app when the stored path does not exist — the library always lives next to the app whatever drive letter a borrowed HD gets. Every path the app writes is derived from the project root, so a test can point `AppConfig` at a temp tree (`tests/tk_support.py:sandbox_app`) instead of writing the developer's real `config/`, `cache/` and `logs/`. | Atomic writes via temp-file + `os.replace` with retry on `PermissionError` for OneDrive locks |
| [`core/constants.py`](core/constants.py) | `VERSION`, `USER_AGENT`, archive extensions, categories, compression and memory-threshold tables, `APP_NAME`, `ENTRY_POINT`, `NO_WINDOW`, reserved directory set. Values that appear in multiple places live here once — e.g. `DEFAULT_ZIP_PASSWORD`. | `DEFAULT_ZIP_PASSWORD` used consistently across archive/organizer/controller/test_services |
| [`core/models.py`](core/models.py) | Plain-data containers with no logic: `GameArchive`, `SteamMatch`, `ArtworkResult`, `ConversionResult`, `OrganizationDecision`, `ScanResult`, `AppState`. | No business logic — pure data containers |
| [`core/library_summary.py`](core/library_summary.py) | `LibrarySummary` frozen dataclass — pure-data index of what the library already looks like (categories, genre placement, developer precedent, archive sizes, total games), built from the catalog walk so screens can ask placement questions without re-walking. No I/O, no logging, no service state. | `built_at > 0` means indexed; `categories_for_genres()` and `precedent_for()` answer placement questions from retained data only |
| [`core/uri_actions.py`](core/uri_actions.py) | Parses `steamgameorganizer://` URIs into `ExtractRequest` objects (or refuses them). Owns `SCHEME` and `SYSTEM_PATHS`. Also handles `setup`, `refresh-catalog`, `open-folder`, and `open-extracted`. | Every field treated as hostile input — source must resolve inside the configured library root, must exist with an archive extension, destination must not sit inside a system folder or the library itself |
| [`core/logger.py`](core/logger.py) | `AppLogger` — timestamped, component-tagged logging; thread-locked; failed writes are swallowed so logging never kills the run. `install_excepthook()` routes uncaught exceptions through the logger. | One timestamped log file per launch under `logs/`; rotates by size (5 MB, keeping `.1` and `.2` rolled files); last 10 rotated logs kept |
| [`core/state.py`](core/state.py) | `StateStore` — thread-safe in-memory app state with deepcopy. | `get()` returns a deep copy so callers can rearrange without touching concurrent state |
| [`core/exceptions.py`](core/exceptions.py) | `OrganizerError`, `CancellationError`. | `CancellationError` propagates through all worker layers without being swallowed |

---

## 🛠️ services

| Module | Role | Key invariants |
|--------|------|----------------|
| [`services/archive_service.py`](services/archive_service.py) | Archive discovery and scan telemetry; installer sniff cached per archive identity. | Mock backend returns four deterministic archives (`Alpha Forge`, `Gamma Quest`, `Delta Realm Incremental`, `Epsilon Online`) |
| [`services/batch_extract_service.py`](services/batch_extract_service.py) | Plans and runs batch extractions outside the library: smallest-first sort, `(n)` collision handling, installer archives routed to `Needs Install`, skip-if-already-extracted. | Skip logic skips games already unpacked to the destination |
| [`services/catalog_service.py`](services/catalog_service.py) | Generates `Game Library.html` + banner art; holds embedded HTML/CSS/JS; `LibrarySummary` index; clears `_COLLECT_CACHE` on regeneration. | Single self-contained HTML file (embedded CSS + vanilla JS, no build step, no external requests) |
| [`services/catalog_status.py`](services/catalog_status.py) | Writes `Game Library.status.js` after every batch/run; `.sgo-extract-info` marker helpers (`read_extract_marker`, `resolve_extracted_root`, `archive_has_changed_since_extraction`, `get_launch_target`, `update_extract_marker`, `mark_setup_done`); `discover_game_launchers()` scans extracted root (max depth 3, 250 candidates) filtering non-game executables. | Launcher discovery filters installers/uninstallers/crash handlers/redistributables/helper tools; scores by depth/name/size |
| [`services/extract_service.py`](services/extract_service.py) | Finds the archive tool and performs extraction; writes `.sgo-extract-info`; preserves `launch_target`/`setup_done`/`installed_at` across re-extract. Collects destination files once via `rglob("*")` and reuses across installer detection and wrapper flattening. | Finds tool via `find_tool()` / `find_unrar()` — checking `PATH` then real install folders (`C:\Program Files\7-Zip`, `%ProgramFiles%\WinRAR`) |
| [`services/installer_detect.py`](services/installer_detect.py) | Recognizes Windows installer archives (setup.exe + .bin, or mountable .iso) → `Needs Install`. | Archives that unpack to an installer repack are routed to a `Needs Install` subfolder with an amber badge |
| [`services/library_service.py`](services/library_service.py) | Whole-library audit (Steam link normalization, artwork refresh); `_sweep_empty_categories()` moves empty game folders/categories to `Archive/`; `convert_pending_archives()` accepts pre-computed candidates to avoid double-walking. | Empty game folders and empty categories moved to `Archive/` rather than deleted |
| [`services/organizer_service.py`](services/organizer_service.py) | Category moves, collision-safe filenames, zip/rar → 7z conversion; empty source folders moved to `Archive/` not deleted; `_manifest_cache` keyed by `(path, size, mtime_ns)`. | Older copies and re-categorized leftovers go to `Archive/` (with `(n)` collision suffixes) for review before deleting |
| [`services/rollback_service.py`](services/rollback_service.py) | JSON transaction journal: writes/reads `last-organization.json`, restores archived files to source on Undo, prunes emptied folders this run created into `Archive/` (never deletes a folder it didn't make). | Ownership gating via `created_game_dir` — pre-existing folders belong to the user whatever they hold |
| [`services/setup_service.py`](services/setup_service.py) | Setup wizard checks and answers: validates the three folders (library with no games, app with no entry point, extract folder inside library are refused), saves library root + extract folder, registers `steamgameorganizer://` under `HKCU` (registry write is injectable for tests). | Registry write reads the value back afterwards to confirm the write succeeded |
| [`services/steam_service.py`](services/steam_service.py) | Direct Steam Store search/details API, with mock backend; `_appid_in_archive_cache` keyed by `(path, size, mtime_ns)`. | Mock backend used only in `--mock` offline test mode with fictional game data — never ships to users |
| [`services/artwork_service.py`](services/artwork_service.py) | Cached Steam artwork retrieval with source fallback. | Keyed per AppID with a 10-day expiry cache; deletes stale cache entries on re-init |
| [`services/banner_art.py`](services/banner_art.py) | Composes the banner image. | Falls back to generated name-keyed banner so no card is ever a flat grey block |

---

## 🖼️ ui

| Module | Role | Key invariants |
|--------|------|----------------|
| [`ui/main_window.py`](ui/main_window.py) | Fixed single-window workflow shell and left nav rail; owns the 5 views + `theme.py` + `palette.py`. | Maximizes itself on start (`state('zoomed')`) — full screen only |
| [`ui/scan_view.py`](ui/scan_view.py) | Discover archives — shows live timeline of cleanup, dedupe, repair, discover, audit, catalog. | Hard-coded widget heights avoided — flexible rows with smaller floor |
| [`ui/review_view.py`](ui/review_view.py) | Accept / override / skip per detected game. | `approve_all()` only approves archives with `steam.found` — skipped archives remain in Incoming |
| [`ui/organize_view.py`](ui/organize_view.py) | Category moves — progress bar, stage pill, confirm bar. | Fraction calculation accounts for `stage_progress` and `archive_bytes` |
| [`ui/artwork_view.py`](ui/artwork_view.py) | Download artwork — per-game card with archive info and Open buttons. | Displays folder path and assets status per archive |
| [`ui/done_view.py`](ui/done_view.py) | Moved / failed / skipped report with Open buttons. | Offers save run report via `filedialog.asksaveasfilename` |
| [`ui/batch_extract_window.py`](ui/batch_extract_window.py) | Batch extraction queue window (`Toplevel`) — hours of 7z needs a visible queue. | Confirm on evidence (count, archive size, destination) before starting |
| [`ui/setup_window.py`](ui/setup_window.py) | Three-folder setup wizard (`Toplevel`); the protocol handler runs with no main window so this is the only thing that has to appear. | Prefills text boxes from `steamgameorganizer://setup` URI links |
| [`ui/theme.py`](ui/theme.py) | ttk theme + shared widgets (`PhaseTimeline`, `ActivityFeed`, `Sparkline`, wheel/scroll helpers); re-exports palette. | Theme colours reach a view only through explicit import — no star imports |
| [`ui/palette.py`](ui/palette.py) | Colours in one place, outside the UI layer so the controller can use them too. | All colour pairs audited by `tests/test_contrast.py` |
| [`ui/widgets/`](ui/widgets/) | `game_card`, `game_list`, `artwork_panel`, `metadata_panel`. | Widget state (checked/unchecked, highlighted/dimmed) tracked separately from model |

Theme colours reach a view only through an explicit import. They were star-imports until 9.8, which meant every view silently depended on every colour anyone had ever added.

---

## 🛠️ utils

| Module | Role | Key invariants |
|--------|------|----------------|
| [`utils/filename_utils.py`](utils/filename_utils.py) | `normalize_name`, `identity_key`, `version_key` — title normalization, identity matching, version ordering. | `identity_key` folds to lowercase alphanumerics so two spellings of one game match |
| [`utils/formatting.py`](utils/formatting.py) | Human-readable sizes and durations. | Used by catalog and logs for display |
| [`utils/desktop.py`](utils/desktop.py) | `os.startfile`-based folder and URL opening (Windows only; no `xdg-open`). | `CREATE_NO_WINDOW` flag used to avoid flashing console windows |
| [`utils/treewalk.py`](utils/treewalk.py) | Junction/symlink-safe recursive walk (no infinite loops). | Skips the app's own project folder so the app never sweeps itself |

---

## 🐞 debug

| Module | Role | Key invariants |
|--------|------|----------------|
| [`debug/diagnostics.py`](debug/diagnostics.py) | Diagnostics and health report output. | Backs `--diagnostics` and `--health` CLI flags; prints environment info, Python version, 7-Zip availability, runtime paths |

---

## 🛠️ tools

Development and installation scripts, not part of the application:

| Tool | Role |
|------|------|
| [`tools/build_frozen.py`](tools/build_frozen.py) | Runs the PyInstaller spec, lifts the exe out of `_internal/`, backs up/restores `config/`, `cache/`, `logs/`. |
| [`tools/bundle_runtime.py`](tools/bundle_runtime.py) | Copies Python + Tcl/Tk and 7-Zip into `runtime/`. Writes `python313._pth`, `THIRD-PARTY-NOTICES.txt`, `LICENSE.txt`. |
| [`tools/install_protocol_handler.py`](tools/install_protocol_handler.py) | Registers `steamgameorganizer://` under `HKCU\Software\Classes` (per user, no elevation); reads the value back to confirm. No `.desktop`/`xdg-mime` path — that platform is no longer a target. |
| [`tools/overnight_repair.py`](tools/overnight_repair.py) | Space-checked, one-at-a-time archive repair (smallest-first, refuses to start archives whose peak requirement won't fit). |
| [`tools/analyze_screenshot.py`](tools/analyze_screenshot.py) · [`tools/layout_audit.py`](tools/layout_audit.py) · [`tools/dead_space_audit.py`](tools/dead_space_audit.py) | Visual checks: palette/off-palette sampling, clipping & overlap, unused space. |
| [`tools/build_icon.py`](tools/build_icon.py) · [`tools/verify_archives.py`](tools/verify_archives.py) · [`tools/tk_probe.py`](tools/tk_probe.py) | Miscellaneous development tools. |
| [`tools/auto_backup.py`](tools/auto_backup.py) · [`tools/compare_backups.py`](tools/compare_backups.py) · [`tools/create_shortcut.py`](tools/create_shortcut.py) · [`tools/restore_backup.py`](tools/restore_backup.py) · [`tools/review_backups.py`](tools/review_backups.py) · [`tools/run_tests_parallel.py`](tools/run_tests_parallel.py) | Backup management, shortcuts, parallel test runner. |

---

## 🧪 tests

`runtime\python.exe -m unittest discover -q` — expect `OK` with no skips. PyInstaller is installed in the bundled runtime so the frozen-build test runs; any other skip is a bug.

| Test | Role | Key invariants |
|------|------|----------------|
| [`tests/tk_support.py:sandbox_app`](tests/tk_support.py) | Roots `AppConfig` in a temp tree; `close_root` cancels pending Tk `after` callbacks before `destroy()` so geometry tests don't leave `invalid command name _tick` noise. | Never construct the real app against the real `config/` in tests |
| [`tests/test_project_state_guard.py`](tests/test_project_state_guard.py) | Snapshots every file under `config/`, exercises `AppConfig`, `save()`, `remember_category()`, scan summary, undo journal, real window against a temp tree; fails if any byte or mtime moved under real `config/`. | `PROJECT_UNDER_TEST = None` → temp tree; `ROOT` → watch both tests fail and prove the guard works |
| [`tests/test_zero_skips.py`](tests/test_zero_skips.py) | AST scan of every test file; fails on any `unittest.skip`/`skipIf`/`skipUnless`/`expectedFailure`/`SkipTest`/`self.skipTest`. | Only exemption: `tests/test_frozen_build.py`'s `@unittest.skipUnless(HAS_PYINSTALLER)` |
| [`tests/test_platform.py`](tests/test_platform.py) | Bans `xdg-open`, `xdg-mime`/`mimeapps.list`, `flatpak`, `/proc/meminfo`, `/home/`, `/root/`, `/usr/bin`, Linux browser package names from production code strings; scans test code too. | Legacy `.desktop` filenames the app deletes are exempt |
| [`tests/test_dead_code.py`](tests/test_dead_code.py) | Asserts superseded names (`wait_for_cancel`, `CATEGORY_GENRES`, `ConfigurationError`, `ServiceError`, `_steam_link`, `STAGE_COST`, `_activity_wheel`) are gone; each entry documents what replaced it. | Each entry documents what replaced the removed name |
| [`tests/test_release_structure.py`](tests/test_release_structure.py) | Walks the tree (excluding `cache/`, `logs/`, `config/`, `runtime/`, `build/`, `dist/`, `__pycache__`, `.git`, `Processing`); fails if production code declares a version anywhere except `VERSION.txt`, `USER_AGENT`, `CHANGELOG.md`. | `# vX.Y change log:` comments and `## X.Y` markdown headings are prose (exempt via `code_before_comment` / fenced-block handling) |
| [`tests/test_render_integrity.py`](tests/test_render_integrity.py) | Asks what a widget was told to paint rather than how big it is — catches panels that laid out correctly but rendered blank. | Widget-level rendering audit |
| [`tests/test_contrast.py`](tests/test_contrast.py) | A `TestCase`, not a script — the audit cannot quietly stop running. | Reports WCAG contrast ratios for every colour pair the app paints |
| [`tests/test_frozen_build.py`](tests/test_frozen_build.py) | Runs `build_frozen.main()` against a scratch tree; asserts exe lands inside bundle with `core/`, `services/`, `runtime/`, `VERSION.txt`, `runtime/7z.exe` present. | Because the app resolves its project root as `Path(__file__).resolve().parent` and walks it for those siblings |

A test that cannot run is worse than no test, because it is reported as present. `tests/test_displayed_data.py` imported a module that does not exist, so unittest collected it as one error and executed none of its 21 tests.

---

## 🔄 Proving a change

Every regression is proved by reverting its fix and watching the test fail, then restoring and watching it pass. Record the failure count, not just that it failed.

---
