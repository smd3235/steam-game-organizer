# project_overview.md — v9.33

[![Version 9.33](https://img.shields.io/badge/version-9.33-blue.svg)](CHANGELOG.md)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-green.svg)](README.md)
[![Lint: ruff](https://img.shields.io/badge/lint-ruff-important.svg)](ruff.toml)
[![Tests: unittest](https://img.shields.io/badge/tests-unittest-success.svg)](tests/)

---

## 📖 How to use this document

This file describes what the app does, how a run flows through its six phases, how the catalog page works, which design decisions are locked, and what commands/testing conventions apply. It is reference material — jump to a section by intent.

| If you want to… | Go to section |
|-----------------|---------------|
| Understand what the app does | [**What it does**](#-what-it-does) |
| Trace a run through six phases | [**Data flow**](#-data-flow) |
| See which decisions are locked | [**Key decisions already made**](#-key-decisions-already-made) |
| Run tests / lint / build | [**Commands**](#-commands) |
| Read the testing rules | [**Testing conventions**](#-testing-conventions) |
| Module inventory + service wiring | [**ARCHITECTURE.md**](ARCHITECTURE.md) |
| Platform and comment rules | [**AGENTS.md**](../AGENTS.md) (Windows only, comment style, frozen-exe rebuild) |

---

## 🎯 What it does

Scans a user's game library (a folder full of `.zip/.rar/.7z` archives organized into category folders), matches each archive against Steam's store API, files the archive into the right category alongside Steam links, metadata, and artwork, generates a clickable HTML catalog, and offers Undo for the whole run.

> [!IMPORTANT]
> The app runs full-screen on Windows only, from a frozen PyInstaller exe. A "library" is a folder the user points the app at; the app itself lives in a project root beside it and writes its own state under `config/`, `cache/`, `logs/`. Version is declared in [`VERSION.txt`](VERSION.txt) and mirrored into [`core/constants.py`](core/constants.py) (`VERSION`) and `USER_AGENT`.

---

## 🔄 Data flow

A run walks the library through six phases:

| Phase | What happens | Code |
|-------|--------------|------|
| **1. Discover** | [`CatalogService._collect`](services/catalog_service.py) walks category folders under the library root, skips anything without an archive, skips the app's own project folder, reads `.game-info.json` sidecars, records banner art and installer signature per game. | [`services/catalog_service.py`](services/catalog_service.py) |
| **2. Organize** | [`AppController.organize`](app/controller.py) / [`OrganizerService.move`](services/organizer_service.py) groups archives by identity key, promotes the newest version, archives older copies and re-categorized leftovers to `Archive/`, repacks `.zip/.rar` → `.7z` (adaptive compression level against real memory headroom), writes metadata + Steam shortcut + artwork into each game folder. | [`services/organizer_service.py`](services/organizer_service.py) — [`app/controller.py`](app/controller.py) |
| **3. Catalog** | [`CatalogService.generate`](services/catalog_service.py) writes `Game Library.html` plus `Game Library.status.js` beside the library root; retains a `LibrarySummary` index (categories, genres, developers, archive sizes) so screens can ask placement questions without re-walking. | [`services/catalog_service.py`](services/catalog_service.py) — [`services/catalog_status.py`](services/catalog_status.py) |
| **4. Done screen** | Reports what a run moved/failed/skipped; buttons open library folder or game folder. | [`ui/done_view.py`](ui/done_view.py) |
| **5. Undo** | [`RollbackService`](services/rollback_service.py) reads `config/last-organization.json`, restores each archived file to its source, prunes emptied folders this run created into `Archive/` (never deletes a folder it didn't make). | [`services/rollback_service.py`](services/rollback_service.py) |
| **6. Batch extract** | [`services/batch_extract_service.py`](services/batch_extract_service.py) unpacks archives to user-chosen folders outside the library, relocates installer layouts to `Needs Install`, writes per-result status next to the catalog. | [`services/batch_extract_service.py`](services/batch_extract_service.py) — [`ui/batch_extract_window.py`](ui/batch_extract_window.py) |

Phases run in order: Discover → Organize → Catalog → Done. Undo and Batch extract are independent entry points (Undo reads `last-organization.json`; Batch extract is triggered from the catalog page via `steamgameorganizer://` URI).

---

## 🔌 URI / protocol handler

The app registers `steamgameorganizer://` under `HKCU\Software\Classes` (per user, no elevation). Supported actions:

| Action | Behavior | Code |
|--------|----------|------|
| `extract` | Parse into an `ExtractRequest` via `core/uri_actions.py` (owns `SCHEME` and `SYSTEM_PATHS`, the folders a typed destination may not sit inside) | [`core/uri_actions.py`](core/uri_actions.py) |
| `extract-all` / `extract-multi` | Category or whole library / hand-picked selection → opens `BatchExtractWindow` (hours of 7z needs a visible queue) | [`services/batch_extract_service.py`](services/batch_extract_service.py) — [`ui/batch_extract_window.py`](ui/batch_extract_window.py) |
| `setup` | Prefill the three-folder setup wizard text boxes | [`services/setup_service.py`](services/setup_service.py) — [`ui/setup_window.py`](ui/setup_window.py) |
| `open-extracted` | `steamgameorganizer://open-extracted?path=<folder>` — opens an extracted/installer folder; path must resolve under a configured extract folder (validated/normalized by the handler) | [`core/uri_actions.py`](core/uri_actions.py) |
| `play` | `steamgameorganizer://play?exe=<file>&path=<marker-folder>` or `?path=<marker-folder>` — launches a validated `.exe` under configured extract folders; when `exe` is omitted, the handler uses the marker's persisted `launch_target` | [`core/uri_actions.py`](core/uri_actions.py) — [`services/catalog_status.py`](services/catalog_status.py) |
| `pick-launcher` | `steamgameorganizer://pick-launcher?path=<marker-folder>` — opens a file picker constrained to the resolved extracted root, validates the chosen `.exe`, persists `launch_target` in `.sgo-extract-info`, then regenerates/opens the catalog | [`services/catalog_status.py`](services/catalog_status.py) |
| `mark-installed` | `steamgameorganizer://mark-installed?path=<marker-folder>` — persists setup completion (`setup_done`, `installed_at`, `needs_install=false`) and regenerates/opens the catalog | [`services/catalog_status.py`](services/catalog_status.py) |
| `refresh-catalog` | Regenerate `Game Library.html` against the live library and re-open it (the page's Unpacked badges are decided at generation time; a `file://` page cannot re-scan the folder itself) | [`services/catalog_service.py`](services/catalog_service.py) |
| `open-folder` | `steamgameorganizer://open-folder?path=<folder>` — opens the game/library source folder in Explorer; path validated against the library root | [`core/uri_actions.py`](core/uri_actions.py) — [`utils/desktop.py`](utils/desktop.py) |

On a first run with no settings, `_needs_setup` detects a missing `settings.json` / nonexistent library root and opens `setup_window.py` before the GUI — the catalog's own setup button cannot install the protocol handler, so the wizard is the first-run fallback.

> [!WARNING]
> URI actions treat every field as hostile input — a link can be crafted by any page, so the source must resolve inside the configured library root, must exist with an archive extension, and the destination must not sit inside a system folder or the library itself.

### Launcher discovery

[`services/catalog_status.py`](services/catalog_status.py)`discover_game_launchers` conservatively scans the extracted root (max depth 3, 250 candidates) for playable `.exe` files, filtering installers/uninstallers/crash handlers/redistributables/helper tools (Unity crash handlers, `BugReporter`, `elevate`, `createdump`, `UEPrereqSetup`, `QuickSFV`, `ffmpeg`, `Spatial Media Metadata Injector`, full JRE toolchain) and scoring by depth/name/size; returns a ranked list for user choice via Pick launcher. The chosen `launch_target` persists to `.sgo-extract-info` and subsequent Play actions use it.

---

## 🖼️ Game Library.html — what the generated page does

`CatalogService.generate` writes `Game Library.html` plus `Game Library.status.js` beside the library root. The page is a single self-contained HTML file (embedded CSS + vanilla JS, no build step, no external requests) that a reader opens in a browser.

### Browse and filter the library

- Category rail on the left, with category → release year → recently added (7/14/30 day) → genre → tag chips. Counts beside each chip are counted from what is actually on disk, not from a fixed vocabulary, so a rail never shows filters that match nothing.
- Search box filters against a per-card `data-search` haystack (name, category, developer, publisher, archive, release date, archive created, description, genres, tags). Cards hide/show inline; category counts recount themselves as filters narrow (`data-toc-count`), and empty sections grey out instead of vanishing so the library shape stays visible.
- Sort by Name / Newest / Oldest / Largest / Smallest / Recently added / Longest owned, reordering each category's own grid. "Newest" and "Oldest" use the Steam release date; "Recently added" and "Longest owned" use when the archive file landed on disk. Tie-breaks fall back to name so the order never reshuffles arbitrarily.
- Card-size preset (small/medium/large), theme toggle (dark/light), both saved to `localStorage` so they survive a reload.
- Keyboard: `/` focuses search, `Escape` clears all filters and multi-select, `Home` goes to top, `Enter` commits a typed path box.

### Know the state of each game

- Hero stats: total games, categories, with artwork, on-disk bytes, plus "Missing art", "To extract", "New version", "Hide extracted" — the last three are real toggle buttons when there is something to filter, plain tiles when there is nothing to act on.
- Each card shows: artwork (Steam banner, or a generated name-keyed banner so no card is a flat grey block), release date, developer, archive created, archive file name + size, genre + tag chips (tags capped at four, overflow shown as `+N`), description truncated at 220 chars.
- Status badges drawn from the same predicate the batch planner skips on, so a badge never claims a game is done that Extract all would unpack again:
  - green `Unpacked` — archive unpacked into the configured destination folder
  - amber `Needs install` — unpacked but still an installer repack (payload relocated to a `Needs Install` folder)
  - `New version` — unpacked but the archive on disk has changed size/mtime since extraction
  - `Installer` — archive is an installer repack not yet unpacked
  - `No Steam match` — no AppID found (card still shows artwork/archive/size/path buttons; only the two Steam actions are missing)

> [!NOTE]
> Because `file://` pages cannot stat any folder, these badges are decided against the default destination folder at generation time. Typing a different destination retracts them immediately (`syncUnpackedBadges`) — a claim about a folder the reader just changed is taken back rather than left standing.

### Open games, folders, and Steam

- Card art link → Steam store page (`store.steampowered.com/app/<appid>`), or opens nothing with a clear reason when there is no Steam match.
- `Open in Steam` → `steam://run/<appid>` Steam client link.
- `Open` → `steamgameorganizer://open-folder?path=<folder>` opens the game's folder in Explorer, path rebuilt from the typed game-folder root so it follows a moved library.
- `Copy path` → copies the full archive path to the clipboard (`execCommand` fallback, since `file://` pages are not a secure context and `navigator.clipboard` is unavailable).

### Extract games through the app (the page cannot unpack anything itself)

`file://` pages cannot open folders or run programs — that boundary is the whole point of the sandbox. Every extract goes through a `steamgameorganizer://extract` link, which the browser hands to the desktop after a confirmation.

- Single `Extract` per card: source percent-encoded (library names are full of spaces/ampersands/quotes), destination taken from the typed box at click time (falls back to the first configured folder). No confirmation prompt — one archive is small and reversible.
- `Extract all` / `Extract remaining` per category or whole library: confirmed on evidence (count, archive size, destination) before the run starts — `Extract all` on a 176-game library is one click from filling a drive. Skip logic skips games already unpacked there.
- Multi-select mode: reveal checkboxes, pick two or more games, extract them together as one `extract-multi://` batch.
- The destination box offers configured folders as datalist suggestions but starts on the first; paths are rebuilt from the typed root at click time so they follow a moved library rather than being frozen to the machine that ran the scan.

### Setup and refresh

- `Set up on this PC` → `steamgameorganizer://setup`, carrying the typed game folder and extract destination so the wizard starts on them. A command-line fallback shows if the protocol never opened.
- `Refresh catalog` → `steamgameorganizer://refresh-catalog`: re-walks the library and rewrites the page so Unpacked badges match what is actually on disk now. Needed because an extraction done outside the app leaves stale badges until regenerated.
- `run-status` banner shows the last batch run result (`Game Library.status.js`, rewritten by the app after every batch run), summarised as a one-line chip in the rail so it stays visible when scrolled past.

### Why this is one HTML file with embedded JS

- A `file://` page cannot `fetch`/`XHR` anything, so a classic `<script src>` beside itself is the one external load allowed — that is `Game Library.status.js`, loaded before the inline script so batch results are on `window` when the script reads them.
- `localStorage` is wrapped in try/catch because it throws outright on `file://` in some browsers rather than returning null.
- `color-scheme` is set explicitly as `dark`/`light` rather than relying on OS preference, because the generated banner art and card scrims are tuned for dark.

---

## 🔒 Key decisions already made (do not re-litigate without cause)

| Decision | Rationale | Code |
|----------|-----------|------|
| **Move to `Archive/`, never delete.** | Empty game folders, empty categories, re-categorized source folders, and rollback-emptied folders are moved into `Archive/` (with `(n)` collision suffixes) so the user can review before deleting. `rmtree` is only a fallback when `library_root` is unknown. | [`services/organizer_service.py`](services/organizer_service.py) — [`services/rollback_service.py`](services/rollback_service.py) |
| **Two folder rules.** | `_folder_is_disposable` (download folder, any image OK) and `_folder_is_prunable` (organized game folder, app-shaped artwork only) are deliberately different. Never merge them. | [`services/organizer_service.py`](services/organizer_service.py) |
| **Ownership gating.** | Undo only prunes folders `created_game_dir` says this run made. A folder already there belongs to the user whatever it holds. | [`services/rollback_service.py`](services/rollback_service.py) |
| **Reserved dirs.** | `Archive` and `Processing` under the library root are never treated as categories. The app's own project folder is never swept. | [`services/catalog_service.py`](services/catalog_service.py) |
| **Frozen exe rebuild required.** | After any code change: `python tools\build_frozen.py`. The user runs only the frozen exe. | [`tools/build_frozen.py`](tools/build_frozen.py) |
| **Atomic writes.** | `settings.json`, `scan-state.json`, and the rollback journal all use temp-file + `os.replace` with retry on `PermissionError` (OneDrive locks). | [`core/config.py`](core/config.py) |
| **`runtime/` ships with the exe** | and is excluded from lint/version scans; it is not this project's code. See [**ARCHITECTURE.md → Bundled runtime**](ARCHITECTURE.md#-bundled-runtime) for how it ships inside the frozen bundle. | [`tools/bundle_runtime.py`](tools/bundle_runtime.py) |

---

## 🖥️ Commands

| Command | Purpose | Code |
|---------|---------|------|
| `runtime\python.exe -m unittest discover -q` | Tests — expect `OK` with no skips — PyInstaller is installed in the bundled runtime so the frozen-build test runs; any other skip is a bug | [`tests/`](tests/) |
| `ruff check .` | Lint | [`ruff.toml`](ruff.toml) |
| `python tools\build_frozen.py` | Rebuild frozen exe — see [**ARCHITECTURE.md → Frozen build**](ARCHITECTURE.md#-frozen-build) for the build pipeline and why it's mandatory | [`tools/build_frozen.py`](tools/build_frozen.py) |
| `runtime\python.exe tools\layout_audit.py` | Layout audit (clipping, off-window widgets, sibling overlap) | [`tools/layout_audit.py`](tools/layout_audit.py) |
| `runtime\python.exe tools\analyze_screenshot.py <shot.png>` | Contrast audit (after theme changes) | [`tools/analyze_screenshot.py`](tools/analyze_screenshot.py) |

---

## 🧪 Testing conventions

| Convention | Rule | Code |
|------------|------|------|
| **No test may skip.** | `tests/test_zero_skips.py` parses every test file with `ast` and fails on any `unittest.skip`, `skipIf`, `skipUnless`, `expectedFailure`, `SkipTest`, or `self.skipTest`. The only exemption is `tests/test_frozen_build.py`'s `@unittest.skipUnless(HAS_PYINSTALLER)` build test — PyInstaller is installed in the bundled runtime so it runs rather than skips. Expected result: `OK`. A skip that is not that one is a bug. | [`tests/test_zero_skips.py`](tests/test_zero_skips.py) |
| **Tests must not write this project's own state.** | `tests/test_project_state_guard.py` snapshots every file under `config/`, exercises `AppConfig.save()`, `remember_category()`, the scan summary, the undo journal, and a real window, and fails if any byte or mtime moved under the real `config/`. `PROJECT_UNDER_TEST = None` aims writes at a temp tree; point it at `ROOT` to watch both tests fail and prove the guard works. | [`tests/test_project_state_guard.py`](tests/test_project_state_guard.py) |
| **Every check must actually run.** | `Ran 0 tests` from a collected module is a bug — `tests/test_contrast.py` was once a script with a `main()` that discovery ran zero tests from. | [`tests/test_contrast.py`](tests/test_contrast.py) |
| **Archiver stubs are cross-platform.** | `tests/test_services.py:_write_stub` writes each fake 7-Zip/unrar stub in whatever form the platform can execute (a shebang script with no extension is invisible to `shutil.which()` on Windows). The conversion pipeline is exercised against a tar-backed fake rather than real 7-Zip, so tests behave identically with or without 7-Zip installed, and a stub can be made to fail in one specific place. | [`tests/test_services.py`](tests/test_services.py) |
| **No POSIX absolute paths aimed at writing constructors.** | `tests/test_platform.py` scans code strings (not comments/docstrings) for `AppConfig(Path('/tmp/...'))`, `AppLogger(Path('/tmp')/...)`, `ArtworkService(...)`, `RollbackService(...)` — on Windows a leading slash resolves against the current drive, so each writes outside the repository. Test code is scanned too. | [`tests/test_platform.py`](tests/test_platform.py) |
| **Windows-only platform.** | `tests/test_platform.py` bans `xdg-open`, `xdg-mime`/`mimeapps.list`, `flatpak`, `/proc/meminfo`, `/home/`, `/root/`, `/usr/bin`, and Linux browser package names from production code strings. Legacy cleanup lists (`.desktop` links, old catalog launchers) are deliberately not banned — they are the names this app deletes. | [`tests/test_platform.py`](tests/test_platform.py) |
| **Version structure is scanned.** | `tests/test_release_structure.py` walks the tree (excluding `cache/`, `logs/`, `config/`, `runtime/`, `build/`, `dist/`, `__pycache__`, `.git`, `Processing`) and fails if production code declares a version number anywhere except `VERSION.txt`, `USER_AGENT`, or `CHANGELOG.md`. `# vX.Y change log:` comments and `## X.Y` markdown headings are prose (exempt via `code_before_comment` / fenced-block handling), not version declarations. | [`tests/test_release_structure.py`](tests/test_release_structure.py) |
| **No dead code.** | `tests/test_dead_code.py` asserts superseded names (`wait_for_cancel`, `CATEGORY_GENRES`, `ConfigurationError`, `ServiceError`, `_steam_link`, `STAGE_COST`, `_activity_wheel`) are gone — each entry documents what replaced it. | [`tests/test_dead_code.py`](tests/test_dead_code.py) |
| **No zero-skips evasion.** | `tests/test_zero_skips.py` uses AST (not grep) so comments and docstrings naming skip constructs don't trigger it — this repository documents its own removals at length. | [`tests/test_zero_skips.py`](tests/test_zero_skips.py) |
| **The frozen build is tested.** | `tests/test_frozen_build.py` runs `build_frozen.main()` against a scratch tree and asserts the exe lands inside the bundle with `core/`, `services/`, `runtime/`, `VERSION.txt`, and `runtime/7z.exe` present — because the app resolves its project root as `Path(__file__).resolve().parent` and walks it for those siblings. | [`tests/test_frozen_build.py`](tests/test_frozen_build.py) |

Use [`tests/tk_support.py:sandbox_app`](tests/tk_support.py) to root `AppConfig` in a temp tree — never construct the real app against the real `config/` in tests (tests race on `settings.json`; `test_project_state_guard.py` enforces this). `sandbox_app` patches `app.application.AppConfig` to point at a temporary tree; `close_root` cancels pending Tk `after` callbacks before `destroy()` so geometry tests don't leave `invalid command name _tick` noise on stderr.
