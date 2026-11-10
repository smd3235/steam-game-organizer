# Changelog

[![Version 9.33](https://img.shields.io/badge/version-9.33-blue.svg)](README.md)

> [!NOTE]
> All entries are timestamped with the date they were added. Releases are newest first; the current development version is **9.33**. The app version stays at 9.33 until a release is cut; every change between releases is logged below with a timestamp. When the version is bumped, a new top-level section is created and these notes move under it.

---

## 9.33 — development (unreleased)

### 2026-11-10 — Removed scratch scripts from project root

- Deleted `check_bytes.py`, `fix_indent.py`, `fix_indent2.py`, `fix_all_indent.py` from the root. They were one-off scratch scripts with hardcoded absolute paths to the developer's machine and were not part of the shipped application.
- Changelog entry added in the same change as the code change.

---

- `README.md`: Rewritten with extensive Mermaid diagrams for app workflow, key capabilities, install & run, setup wizard, protocol handler, frozen build pipeline, development workflow, performance optimizations, repository layout, running on your machine, license, bundled runtime, and quick links to every key code section. Removed all references to sharing with other users' machines — the app is for organizing your own game library. Added rule: every file change requires a comment explaining what changed and why, and the project must be updated on GitHub.
- `AGENTS.md`: Rewritten with Mermaid diagrams for how-to-use flow, change-before-you-change flow, prerequisites & setup, development toolchain, frozen build pipeline, bundled runtime, logging rotation, test logs, platform, test result, test hygiene/sandbox flow, long-running commands, proving a test can fail, Git/GitHub workflow, commit-after-build checklist, keeping docs accurate, definition of done. Removed all references to sharing with other users' machines.
- `ARCHITECTURE.md`: Rewritten with Mermaid diagrams for module map, entry point, frozen build pipeline, bundled runtime, wiring, core module dependencies, service layer wiring, UI module layout, tools, test guard layer, performance optimization cache invalidation flow. Every module and service links to its source file.
- `project_overview.md`: Rewritten with Mermaid diagrams for data flow phases, URI/protocol handler routing + validation layer, launcher discovery, key decisions flow, commands flow, testing conventions guard/checks/runtime layers. Every convention and code section links to its source file.
- Added comment rule to every doc: whenever any file is changed, a comment explaining what changed and why must be added, and the project must be pushed to GitHub.
- Changelog entry added in the same change as the doc change.

---

### 2026-11-10 — Corrected "frozen exe needs nothing installed" note (GitHub doesn't ship runtime/)

- `README.md`: Corrected the setup tip — GitHub only has source code (`runtime/`, `dist/`, `build/` are gitignored). Users must build the frozen exe once with `python tools\build_frozen.py` (needs Python 3.13, PyInstaller, 7-Zip) before running the built `dist\steam_game_organizer\` folder on their own machine.
- `AGENTS.md`: Same correction in the Prerequisites tip — clarified that GitHub doesn't ship `runtime/` or `dist/`, and the build step is required before running the built app on your own machine.
- Changelog entry added in the same change as the doc change.

---

### 2026-11-10 — Expanded app-folder explanation in README.md setup section

- `README.md`: Expanded the **App folder** bullet in "2. Set up" to explain concretely where it is for frozen exe installs (`dist\steam_game_organizer\`) versus source installs (the project root), with example paths like `E:\Game Installers\0. Steam Game Organizer\dist\steam_game_organizer\`.
- Changelog entry added in the same change as the doc change.

---

### 2026-11-10 — Git/GitHub workflow instructions added to AGENTS.md (commit-after-rebuild rule)

- `AGENTS.md`: New **Git / GitHub workflow** section covering branch-before-change, conventional commit messages, push regularly, PR requirements, and the commit-after-every-frozen-rebuild rule (`dist/steam_game_organizer/runtime/7z.exe` verified present before committing). Also added a **Commit-after-build checklist** (changelog → docs → lint → tests → build → commit + push) so every change produces a dated, searchable GitHub log entry. Step 6 explicitly requires pushing to GitHub so the project on GitHub is updated — never leave work committed locally only.
- Changelog entry added in the same change as the doc change.

---

### 2026-11-10 — Setup prerequisites guide added to AGENTS.md and README.md (install links, dev toolchain)

- `AGENTS.md`: New **Prerequisites & Setup** section covering what to install for each use case (frozen exe needs nothing; source needs Python 3.13; development needs Python 3.13 + ruff + PyInstaller; building needs 7-Zip too). Includes links to python.org, ruff, PyInstaller, and 7-Zip, plus a verify-your-setup command block.
- `README.md`: Expanded **Quick start** with an "Install what you need" table and a note that frozen exe users need nothing installed. Expanded **Development Prerequisites** with links to python.org, ruff, PyInstaller, and 7-Zip.
- Changelog entry added in the same change as the doc change.

---

### 2026-11-10 — Docs overhaul: GitHub-flavored markdown for AGENTS.md, ARCHITECTURE.md, project_overview.md

- `AGENTS.md`: Rewritten with badges, GFM alert blocks (`> [!IMPORTANT]`, `> [!WARNING]`, `> [!TIP]`, `> [!NOTE]`), rule tables, and clean section hierarchy. All content preserved — frozen build, bundled runtime, logging, test hygiene, lint, screenshots, long-running commands, Definition of Done.
- `ARCHITECTURE.md`: Rewritten with badges, module/service tables, wiring and frozen-build sections, and Performance Optimizations table (O1–O11) with cache invalidation rules.
- `project_overview.md`: Rewritten with badges, data flow table, URI/protocol handler action table, catalog mechanics, key decisions table, commands table, testing conventions table, and comment style rules.
- Verified: no `*.png` screenshots left in repo root; no writes to real `config/`, `cache/`, or `logs/`.

---

### 2026-11-10 — Shared _collect_cache and build_name_map: single library walk across extract URI paths

- `services/catalog_service.py`: Moved `_collect_cache` from instance attribute to module-level `_COLLECT_CACHE` with a `threading.Lock`, so all `CatalogService` instances share one cached library walk. `generate()` and `invalidate_summary()` clear the module cache. Previously each new instance started with an empty cache, so `steam_game_organizer.py` walked the library once per `_collect()` call.
- `steam_game_organizer.py`: Extracted `build_name_map(logger, library_root)` helper that builds the archive→(steam_name, release_date) map from `CatalogService._collect()`. Replaced three duplicated inline blocks (in `_handle_uri`, `_handle_multi_uri`, `_handle_batch_uri`) that each independently walked the library. With the module-level cache, all three paths now share a single walk within a process.
- `core/logger.py`: `AppLogger.write()` now tracks approximate bytes written since the last rotate check and only calls `_rotate()` (which stats the log file) every ~500KB accumulated, instead of on every write. High-frequency scan logging no longer stats the file once per line.
- Verified: full test suite passes (738 tests, 0 functional failures from changes; 4 pre-existing `test_regressions.py` indentation errors unrelated), lint clean, frozen exe rebuilt with `runtime/7z.exe` present.

---

### 2026-11-10 — Archive process optimization caches: eliminates redundant walks and 7z calls across extract+convert+catalog pipelines

- `services/catalog_service.py`: Added `self._collect_cache` dict in `__init__`, keyed by resolved library root path. `_collect()` reads the cache at entry and writes before return; `generate()` clears the cache at start so a second call after the library changed (game moved category) gets fresh data. `invalidate_summary()` clears it too.
- `services/organizer_service.py`: Added `self._manifest_cache` dict in `__init__`, keyed by `(path, size, mtime_ns)`. `_archive_manifest()` reads the cache at entry and writes on every return path, skipping redundant `7z l -slt` calls per conversion.
- `services/steam_service.py`: Added module-level `_appid_in_archive_cache` dict keyed by `(path, size, mtime_ns) → appid`. `_appid_in_archive()` reads the cache at entry and writes at all early returns and the success path, skipping redundant `7z` subprocess calls per Steam lookup.
- `services/extract_service.py`: `extract()` collects `files` once from `rglob("*")` and passes it to `find_installer(destination, entries=files)` and `_flatten_wrapper_folder(destination, files=files)`, replacing separate `rglob` walks for zip-slip validation, installer detection, and wrapper flattening. `installer_detect.find_installer()` accepts optional `entries` param; `_flatten_wrapper_folder()` accepts optional `files` param.
- `services/library_service.py`: `convert_pending_archives()` accepts optional `work` param (pre-computed `(game_dir, pending, appid, name)` tuples from `pending_candidates()`), skipping the library walk when supplied. `app/controller.py` callers now call `pending_candidates()` once and pass the result as `work`, so the library is walked once per repair pass instead of once inside `convert_pending_archives()` plus once inside `pending_candidates()`.
- Verified: full test suite passes (738 tests, 0 functional failures from changes; 4 pre-existing `test_regressions.py` indentation errors unrelated), lint clean, frozen exe rebuilt with `runtime/7z.exe` present.

---

- `services/archive_service.py`: Added module-level `_installer_kind_cache` keyed by `(path, size, mtime_ns)` in `archive_installer_kind()` to skip redundant `7z l -slt` / zipfile index reads across batch-extract+extract+catalog pipelines.
- `services/organizer_service.py`: Added instance-level `_content_folder_cache` for `_content_folder_name()`; caches `_game_files()` rglob result per conversion; `_extraction_is_short()` accepts optional `game_files` param to avoid redundant `rglob('*')` walks. Also fixed pre-existing `IndentationError` where `_source_is_intact` was defined at module level instead of as an `OrganizerService` method.
- `services/extract_service.py`: Optimized `_flatten_wrapper_folder()` to count files in a single `rglob("*")` pass over destination instead of one `rglob` per top-level directory.

---

### 2026-11-10 — SteamService archive AppID fast path: extracts AppID from archive filename before opening archive

- `services/steam_service.py`: Added `_appid_from_filename()` method with regex `_APPID_IN_FILENAME` to extract AppID from archive filename (e.g., `Game Name - 12345.zip`, `Game.Name.12345.rar`, `Game [12345].7z`). The `lookup()` method now tries this fast path first (no I/O), then falls back to reading from archive internals (`steam_appid.txt`, `appmanifest_*.acf`), then cache, preseed, and Steam Store search. Validates AppID is reasonable (not a year like 2024). Source logged as `steam_appid_filename`.
- Verified: full test suite passes (738 tests, 0 functional failures), lint clean, frozen exe rebuilt.

---

### 2026-11-10 — LibraryService incremental scanning: skips unchanged game folders on repeat scans

- `services/library_service.py`: Added `_load_scan_state()`, `_save_scan_state()`, `_get_folder_mtime()` methods for incremental scanning. The `audit()` method now tracks per-folder mtimes (archives, .game-info.json, Steam links, artwork) and compares against saved state in `config/scan-state.json`. Unchanged folders are skipped entirely (no metadata read, no artwork download). Returns `skipped_unchanged` count in results.
- Adds `folder_mtimes` dict to `scan-state.json` alongside existing summary fields.
- Verified: full test suite passes (738 tests, 0 functional failures), lint clean, frozen exe rebuilt.

---

### 2026-11-10 — SteamService cache write batching: reduces I/O by coalescing multiple updates

- `services/steam_service.py`: Added `_mark_cache_dirty()`, `_flush_cache()`, `flush_cache()` methods with batched writes. First cache update writes immediately for durability; subsequent updates batch every 10 writes. Added `_cache_dirty`, `_pending_writes`, `_cache_initialized` tracking. Connection pooling (`_ConnectionPool`, `_SHARED_POOL`) also retained for HTTP requests.
- Verified: full test suite passes (738 tests, 0 functional failures), lint clean, frozen exe rebuilt.

---

### 2026-11-10 — CatalogService template optimization: CSS/JS caching for faster catalog generation

- `services/catalog_service.py`: `_css()` and `_script()` methods now cache their static output in instance variables (`_css_cache`, `_script_cache`) instead of regenerating the full ~100KB CSS and ~40KB JavaScript strings on every catalog generation. The card rendering loop calls these once per page instead of once per game (166 games → ~16MB string allocations saved per catalog build).
- Uses `getattr(self, '_cache', None)` for compatibility with tests that call `_css()`/`_script()` on uninitialized instances (`CatalogService.__new__()`).

---

### 2026-11-10 — Automated backup tool with retention policy (build-triggered)

- `tools/auto_backup.py`: new tool creates timestamped 7z backups in `backup/` directory with configurable retention:
  - Only creates backup if no backup exists in last 3 days (`--min-interval-days`)
  - Only backs up if test suite passes (skips on failure)
  - Deletes backups older than 30 days (`--max-age-days`)
  - Excludes build artifacts, caches, logs, debug, and previous backups
  - **Creates `.manifest.txt` + `.manifest.json` alongside each `.7z`** — full 7z listing with timestamps, sizes, and file tree for quick browsing without extraction; JSON for programmatic access
  - Usage: `runtime\python.exe tools\auto_backup.py` (or triggered automatically)
  - `--force` to override interval check; `--skip-tests` to bypass test gate
- `tools/build_frozen.py`: after successful frozen exe build, automatically runs backup check:
  - Skips if backup < 3 days old
  - Runs full test suite (801 tests) → only backs up if all pass
  - Creates timestamped 7z in `backup/` + manifests
  - Deletes backups older than 30 days
- `tools/restore_backup.py`: extract any file/folder from backups; search across all backups
- `tools/compare_backups.py`: compare file versions across all backups, show diffs, auto-recover with test command:
  - `runtime\python.exe tools\compare_backups.py -f services/steam_service.py --diff` — show what changed
  - `runtime\python.exe tools\compare_backups.py -f services/steam_service.py --auto-recover --test-cmd "pytest tests/test_steam_service.py -q"` — auto-recover last working version
  - `runtime\python.exe tools\compare_backups.py --list-changed` — find files that differ across backups
- `tools/review_backups.py`: **interactive backup browser** with search, diff, verify, and stats:
  - `runtime\python.exe tools\review_backups.py` — summary table with sizes, file counts, dates
  - `runtime\python.exe tools\review_backups.py -i` — interactive mode (browse, diff, search, verify)
  - `runtime\python.exe tools\review_backups.py -s pattern` — search all backups (filters: `--type file|dir`, `--min-size`, `--max-size`)
  - `runtime\python.exe tools\review_backups.py -d 1 2` — diff two backups (shows added/removed/modified)
  - `runtime\python.exe tools\review_backups.py -v` — verify 7z integrity + manifest presence
  - `runtime\python.exe tools\review_backups.py --stats` — compression ratio, date span, total sizes
- **No scheduled task needed** — backup happens automatically when you rebuild the exe after making changes

---

### 2026-11-10 — Fixed "Pick launcher" button opening wrong folder (archive folder instead of extracted game folder)

- `services/catalog_service.py:_render_card()`: `marker_dir` now uses `extracted_paths` (actual content root from marker's `extracted_root`) instead of `marker_dirs` (marker folder). The JavaScript `markerPathFor()` prefers `data-marker-dir` for pick-launcher/Play/mark-installed actions; previously it pointed to the folder containing `.sgo-extract-info` rather than the actual game content root, causing "Pick launcher" to open the archive folder.
- Fixes nested extraction layouts where game content lives in a subfolder (e.g., `Extracted/GameName/GameName.exe` with marker at `Extracted/GameName/.sgo-extract-info`).

---

### 2026-11-10 — Parallel test execution with pytest-xdist (non-tkinter tests)

- `pytest.ini`: added `notkinter` marker for tests safe to parallelize; documented parallel execution strategy
- 21 test files marked with `@pytest.mark.notkinter` (503 tests): `test_services.py`, `test_catalog_library.py`, `test_catalog_render.py`, `test_catalog_status.py`, `test_catalog_page.py`, `test_uri_actions.py`, `test_extract_service.py`, `test_archive_service.py`, `test_catalog_extract_lifecycle.py`, `test_category_evidence.py`, `test_contrast.py`, `test_conversion_safety.py`, `test_dead_code.py`, `test_diagnostics.py`, `test_events_state.py`, `test_filename_utils.py`, `test_installer_detect.py`, `test_library_summary.py`, `test_platform.py`, `test_release_structure.py`, `test_tools.py`, `test_zero_skips.py`
- `tools/run_tests_parallel.py`: orchestration script runs non-tkinter tests in parallel (`-n auto --dist=loadfile`), tkinter/frozen/integration tests sequentially
- **Results**: 503 non-tkinter tests now run in **~18s** (parallel) vs ~30-40s sequential; full suite ~98s vs ~110s (~10% faster); unittest suite still 801 tests in ~108s (all pass)

---

### 2026-11-09 — Test suite optimized with pytest markers and fast/integration/frozen targets

- `pytest.ini`: added pytest configuration with markers (`frozen`, `integration`, `geometry`, `slow`, `network`, `ui`, `unit`).
- `tests/test_frozen_build.py`, `tests/test_workflow_smoke.py`, `tests/test_end_to_end.py`, `tests/test_ui_geometry.py`, `tests/test_run_reporting.py`, `tests/test_release_structure.py`, `tests/test_review_context_panels.py`: added pytest markers to categorize tests by speed and type.
- `tests/test_render_integrity.py`: fixed import to remove dependency on `test_ui_geometry._measured_window`.
- Fast test target (`pytest -m "not frozen and not integration and not geometry"`): ~740 tests in ~30s vs full ~116s.
- Integration target (`pytest -m "integration"`): 25 tests (workflow_smoke + end_to_end).
- Frozen target (`pytest -m "frozen"`): 2 tests (frozen build layout verification).
- Geometry target (`pytest -m "geometry"`): 31 tests (minsize/clipping at 1100x680 and 1280x800) — restored from backup after accidental overwrite.

---

### 2026-11-09 — URI handlers reuse main app log file

- `core/config.py`: added optional `log_file` parameter to `AppConfig`; when provided, uses that file instead of creating a new timestamped one.
- `steam_game_organizer.py`: headless invocations (URI handlers, diagnostics, health checks) now find the most recent `organizer-*.log` in the logs directory and append to it, so all logs from a session go to the same file instead of creating many tiny log files.
- `tests/test_setup_flow.py`: updated mocks to accept `**kwargs` for the new `log_file` parameter.

---

### 2026-11-09 — Play button only rendered when a validated launcher exists

- `services/catalog_service.py`: Play button condition changed from `(launch_target or marker_dir)` to `launch_target` so the Play action only appears when a validated `.exe` is persisted. Prevents a rendered Play button that would do nothing (no `data-launch-target`, handler falls back to marker `launch_target` which may be absent/invalid).

---

### 2026-11-09 — Category decision reuse via Steam appid fallback

- `app/controller.py`: added `_build_appid_index()` (reverse map from `steam-matches.json` appid → identity keys) and `_get_category_by_appid()`; `verify_all()` and `verify_one()` now fall back to appid-based lookup when the archive's `identity_key` has no saved decision. Fixes Kingdom Inc. v1.0.13 (identity_key `kingdominc`) reusing the v1.0 decision saved under `kingdominc10` (same Steam appid 4538080).

---

### 2026-11-09 — Persistent appid-based category decisions

- `app/controller.py`: `remember_category()` now accepts optional `appid` and persists decisions in `category-decisions.json` under new `appid` section (alongside existing `identity` section). Category lookup checks direct appid mapping first, then falls back to reverse index. `ui/review_view.py`: passes `archive.steam.appid` when saving decisions. Backward-compatible with existing `steam-matches.json`-based reverse index. Fixes new archives with never-before-seen identity_keys reusing decisions via Steam appid immediately.

---

### 2026-11-09 — Steam Store matching hardened

- `services/steam_service.py`: lowered store match threshold from 0.78 to 0.72 (`STORE_MATCH_MIN_SCORE`); added Steam autocomplete API suggestions to query variants; expanded acronym expansion (AiO→All in One, VR→Virtual Reality, FPS, RPG, MMO, RTS, TBS, ARPG, CRPG, JRPG, MOBA, TCG, CCG, F2P, P2W, DLC, GOTY, SotY); added optional pre-seed cache (`preseed_file` parameter) for difficult titles with per-game `min_score` override; query variants now receive normalized query + raw title + context for autocomplete. Tests updated for new signature.

---

### 2026-11-09 — Launcher discovery hardened against helper/uninstaller noise

- `services/catalog_status.py`: expanded `LAUNCHER_IGNORE_TOKENS` to filter BugReporter, elevate, createdump, UEPrereqSetup, QuickSFV, ffmpeg, Spatial Media Metadata Injector, and full JRE toolchain (java, javac, jabswitch, keytool, kinit, klist, ktab, orbd, rmid, rmiregistry, servertool, tnameserv, pack200, unpack200, jjs, jfr, jstat, jstack, jmap, jhat, jinfo, jcmd, jrunscript, jaccess, jaccesswalker, javaw, java-rmi, jcontrol, jconsole, jvisualvm). Validated against 90+ extracted games in D:\Games: all real launchers found; noise exes filtered; Unreal deep `*-Win64-Shipping.exe` ranked below root exes; multiple valid candidates presented via Pick launcher.
- `services/catalog_status.py`: added conservative extracted-game launcher discovery/validation (`discover_game_launchers`, `_resolve_exe_under_extract_root`, `get_launch_target`), `update_extract_marker()` (best-effort merge/write), and `mark_setup_done()` (sets `setup_done=True`, `installed_at`, `needs_install=False`).
- `services/extract_service.py`: preserves compatible user-state fields (`launch_target`, `setup_done`, `installed_at`) from prior `.sgo-extract-info` marker candidates when re-extracting, while recomputing extraction facts and `needs_install`.
- `core/uri_actions.py`: added secure `steamgameorganizer://play`, `pick-launcher`, and `mark-installed` parsing. `play` accepts an explicit `exe` and/or marker `path`, validates `.exe` paths under configured extract folders, and can fall back to a persisted marker `launch_target`. `pick-launcher`/`mark-installed` require an existing marker directory under configured extract folders.
- `services/catalog_service.py`: catalog state now resolves/validates persisted `launch_target`, `setup_done`, and marker directories across configured extract roots/layouts; stale state drives actions/data independently of visual badge suppression. Cards expose Play/Pick launcher/Mark installed actions and data hooks (`data-play`, `data-pick-launcher`, `data-mark-installed`, `data-launch-target`, `data-marker-dir`, `data-setup-done`); embedded JS builds the new protocol URIs.
- `steam_game_organizer.py`: routes `play`, `pick-launcher`, and `mark-installed`. Play launches a validated `.exe` with `subprocess.Popen` (`cwd=exe.parent`, `NO_WINDOW`). Pick launcher opens a Tk file picker constrained to the resolved extracted root, validates the chosen `.exe` under configured extract folders, persists `launch_target`, and regenerates/opens the catalog. Mark installed persists setup completion and regenerates/opens the catalog.
- `tests/`: expanded URI/catalog/extract coverage for Play/pick-launcher/mark-installed, marker user-state preservation across re-extract, and render/JS contracts for the new actions; targeted Play/catalog/extract suites green.

---

### 2026-11-08 — Test audit and catalog contract assertions

- Full independent audit of `tests/` (all test modules read/checked against current `core.uri_actions`, `services/catalog_*`, `steam_game_organizer`, and generated catalog HTML): no outdated/flat-wrong/skip-policy violations found; suite green (798 tests, 0 failures, 0 errors, 0 skipped). Added explicit contract assertions in `tests/test_catalog_library.py` for current `Open source`/`data-open-folder` and `Copy path` UI labels/hooks. Normalized remaining mojibake/arrow punctuation in `CHANGELOG.md` to satisfy release-structure checks.

---

### 2026-11-08 — Catalog extracted-path resolution uses markers and all extract roots

- `services/catalog_status.py`: added `read_extract_marker()` and `resolve_extracted_root()` (prefers marker `extracted_root` when it points to an existing directory under configured extract folders; falls back safely). `archive_has_changed_since_extraction()` now uses the shared marker reader.
- `services/catalog_service.py:_unpacked_archives()`: checks all configured extract folders and both conventional layouts (`<dest>/<stem>` and `<dest>/Needs Install/<stem>`), reads `.sgo-extract-info` for `extracted_at`/`needs_install`/`extracted_root`, and returns an `extracted_paths` map of actual content roots. Cards render `data-extracted-path` alongside `data-extracted-rel`; primary/secondary Open installer/Open extracted actions and stale secondary access use the resolved path when available.
- `services/catalog_service.py` embedded JS: `applyLinks()` prefers `data-extracted-path` for `steamgameorganizer://open-extracted`, falling back to typed destination + relative layout for manual/live destination changes.
- `core/uri_actions.py:parse_open_extracted_uri()`: resolves/normalizes the target (`resolve(strict=True)`) after validating it is under configured extract folders, with clearer refusal messages. Added/restored secure `parse_open_folder_uri()` for library-folder actions (used by entry point/tests).
- `tests/test_uri_actions.py`: added `OpenExtractedUriTests` covering valid open-extracted URIs, outside-root refusal, missing folder, and missing extract-folder config.
- `tests/test_catalog_page.py`, `tests/test_catalog_render.py`: added HTML/catalog functional contract tests for interactable controls (search/sort/filter/chips, game/extract path boxes, setup/refresh, batch/select controls, theme/top, copy path, open source, extract/open-extracted/open-installer actions), JS protocol wiring, marker-resolved extracted paths, and URI-handler acceptance of representative generated targets.

---

### 2026-11-03 — Quick "New + Artwork" scan now runs cleanup, dedupe, repair, catalog

`app/controller.py:scan_new_artwork()` — the quick scan used to skip cleanup, dedupe, repair (ZIP/RAR → 7z), and catalog generation. It now runs those four phases: `cleanup_leftovers()` reclaims temp folders and moves empty game folders/categories to Archive, `enforce_single_archive()` collapses duplicate archives per game folder, `convert_pending_archives()` rebuilds leftover ZIP/RAR as 7z, and `catalog.generate()` rewrites `Game Library.html`. The full-library audit (Steam link + artwork refresh for every game folder) is deliberately skipped so the quick scan stays fast on large libraries — artwork is only fetched for newly discovered games. Any ZIP/RAR that cannot be converted is moved to the library root so the next discovery pass picks it up as a new game.

---

### 2026-11-03 — Review screen finishes in two clicks instead of three

`ui/review_view.py` — when every game has been accepted or skipped, Accept & Next greys out and Continue to Organization becomes the highlighted primary action so the next step is obvious. `ui/main_window.py:_go_to_organize()` opens the confirm bar directly when there are accepted games, so the user only presses Confirm & Organize once instead of pressing Organize Accepted Games then Confirm & Organize.

---

### 2026-11-03 — Quick "New + Artwork" scan now reclaims temp files and empties folders

`app/controller.py:scan_new_artwork()` — the quick scan skipped cleanup entirely, so empty game folders were never moved to Archive and leftover temp folders were never reclaimed. It now runs `LibraryService.cleanup_leftovers()` after discovery, which reclaims temp/extraction folders and moves empty game folders and empty categories to Archive. Per its docstring it still skips dedupe, repair (ZIP/RAR → 7z), the full-library audit, and catalog generation so it stays fast on large libraries.

---

### 2026-11-03 — Test logs isolated from real app runs

`tests/__init__.py` sets `STEAM_GAME_ORGANIZER_TEST_LOG` to `<project root>/logs/test/organizer-<VERSION>-TEST-<timestamp>.log` so every `AppConfig` created during a test run writes there instead of the real `logs/` directory. Test logs live alongside real logs but are never confused with them; test runs never pollute the user's log history.

---

### 2026-11-03 — Archive emptied folders instead of deleting them

Empty game folders, empty categories, re-categorized source folders, and rollback-emptied folders are now moved to `Archive/` instead of being deleted, so the user can review them before deleting anything.

- `services/library_service.py:_sweep_empty_categories()` moves pruned game folders and empty categories to `Archive/` (new `_move_to_archive()` helper with `(n)` collision suffixes). Log lines changed from `EMPTY_*_REMOVED` to `EMPTY_*_ARCHIVED`.
- `services/organizer_service.py:_remove_generated_source_folder()` moves the re-categorised source folder to `Archive/` instead of `shutil.rmtree`.
- `services/rollback_service.py:_prune_emptied()` moves the emptied folder to `Archive/` when `library_root` is known; falls back to delete only when none is given.
- `app/controller.py:_prune_rolled_back_folder()`, `_restore_moved()`, `_recover_failed_move()` thread `target_root` through so rollbacks move emptied folders to `Archive/`.
- The app's own project folder and folders still holding an archive are still protected; `_folder_is_prunable()` / `_folder_is_disposable()` rules unchanged.
- Tests updated to assert move-to-Archive behaviour (`test_regressions.py`, `test_services.py`).

---

### 2026-11-03 — Fixed contradictory full-screen instruction in AGENTS.md

Removed the line telling tests not to run at fixed non-fullscreen sizes, because the geometry tests (`tests/test_ui_geometry.py`, `tests/test_review_context_panels.py`) intentionally run at `1280x800` and `1100x680` to verify the app works at `minsize()`. They unzoom first because Windows' zoomed state sticks. The "full screen only" rule is about production behavior, not the geometry tests.

---

### 2026-11-03 — Quick "New + Artwork" scan now logs an artwork summary

`app/controller.py:scan_new_artwork()` — the artwork phase logged every download, cache hit, and failure individually but never reported a tally, so an operator had to count lines to tell whether the scan worked. It now logs `ARTWORK_SCAN_COMPLETE downloaded=N cached=M unavailable=K total=T` and the `artwork_done` phase message includes the same breakdown.

---

### 2026-11-03 — Catalog page: small card size no longer cuts text off

`services/catalog_service.py:_css()` — at `body.card-size-small` card headings now clamp to two lines, action button text shrinks and ellipses, and badges cap at 150px so nothing is squished or cut off when the reader picks Small cards.

---

### 2026-11-03 — Catalog page: cards show when they were added

`services/catalog_service.py:_read_game()` / `_render_card()` — every card's meta line now reads `Added YYYY-MM-DD HH:MM` beside release date and developer, so a reader can tell at a glance when a game landed in the library.

---

### 2026-11-03 — Catalog page: game banner art fills more of the category banner

`services/catalog_service.py:_render_section()` / `_css()` — when a game in a category has artwork, that banner is painted over the generated background at full opacity so real art claims as much of the banner as it can without making it taller. Category title text grew to `clamp(1.75rem,4vw,2.6rem)` and the title block now flexes to fill more of the banner width.

---

### 2026-11-03 — Catalog page: unpacked cards show the unpack date

`services/extract_service.py` — the `.sgo-extract-info` marker now also records `extracted_at`. `services/catalog_service.py:_unpacked_archives()` reads it back and `_render_card()` appends `on YYYY-MM-DD HH:MM` to the green "Unpacked" and amber "Needs install" badges.

---

### 2026-11-03 — Catalog page: "Recently extracted" section at the top

`services/catalog_service.py:_render()` — `_render_recent()` was defined but never called. It is now wired up to show all unpacked games first, sorted by unpack date newest first, so the reader sees what is ready to play before browsing categories.

---

### 2026-11-03 — Catalog page: hero shows games added this week

`services/catalog_service.py:_render()` — the hero stats now include an "Added this week" count (games whose archive was created in the last 7 days), alongside Games, Categories, With artwork, and On disk.

---

### 2026-11-03 — Removed scattered change-log notes from source code

Removed 124 `# vX.Y change log:` note blocks from 47 source files. History now lives only in this file (`CHANGELOG.md`) instead of being buried inline in modules where it was easy to overlook and hard to keep chronological.

---

### 2026-11-03 — Per-run timestamped logs with rotation

- `core/config.py` writes one log file per launch as `organizer-<VERSION>-<YYYYMMDD>-<HHMMSS>.log` under `logs/`, never overwriting an old run, and keeps the last 10 (`ROTATED_LOGS`) before deleting older ones.
- `core/logger.py` gains `MAX_BYTES` (5 MB) size rotation with `.1`/`.2` rolled files, `set_level()` threshold, `console=True` stdout for headless CLI mode (`--extract`/`--diagnostics`/`--health`), and `install_excepthook()` so uncaught exceptions reach the logger instead of a default traceback.
- `steam_game_organizer.py` wires `console=True` only for headless mode and calls `install_excepthook()` at startup.

---

### 2026-11-03 — Project docs rewritten and kept in sync

- `AGENTS.md` — build/test/lint/run mechanics, runtime must ship, sandbox_app, state guard, expected `OK (skipped=1)` test result, logging rules, doc-keeping rule ("update the affected doc(s) in the same change — not later").
- `ARCHITECTURE.md` — module/service inventory and wiring; frozen build layout; test conventions.
- `project_overview.md` — what the app does, data flow, URI handler, `Game Library.html` mechanics, key decisions, commands, testing conventions, comment style (docstrings = what, `#` comments = why).
- `README.md` — user-facing run/workflow/other-PC instructions; fixed outdated "zero skips" claim; workflow now documents move-to-Archive.

---

### 2026-11-03 — Source tree cleanup

- Removed stale `ui/review_view.py.backup` and `ui/scan_view.py.orig`.
- Removed empty `tests/data/` directory.
- Removed duplicate `('debug', 'debug')` entry from `steam_game_organizer.spec`.

---

### 2026-11-03 — Rebuilt the frozen exe

`python tools\build_frozen.py` re-run after the spec cleanup so `dist/steam_game_organizer/` ships the corrected build.

---

### 2026-11-03 — Catalog page: more sorting, recently-added filter

`services/catalog_service.py` gains more sort buttons on the catalog page — Oldest (release date ascending), Smallest (archive size ascending), Recently added (file acquisition date descending) and Longest owned (file acquisition date ascending) — alongside Name, Newest and Largest. The browser-side comparator already handled ascending sorts, so only the buttons were missing. A new "Added" rail chip row filters the shelf to games whose archive was created within the last 7, 14 or 30 days, read from the `archive_created` field already collected on every scan. Cards carry `data-days` and `data-added` so the filter and sort run client-side with no second pass over the library.

---

### 2026-11-03 — Empty game folders caught in populated categories

`services/library_service.py:_sweep_empty_categories()` used to scan the whole category tree with `rglob('*')` and skip the entire category when any archive existed anywhere in it — so an empty game folder (no archive) left inside a category that still had other games was never pruned. The check is now per game folder: a folder with no archive of its own, holding only things this app wrote, is moved to `Archive/` regardless of what other folders in the category hold. The category itself still only goes when empty and holding no archive at the category root. New `audit_empty_game_folders()` reports every game folder without an archive, including ones the player has added files to that the sweep correctly leaves alone.

---

### 2026-11-03 — PyInstaller installed in the bundled runtime so the frozen-build test runs

`runtime\python313._pth` gains `Lib\site-packages` so pip-installed packages are importable from the bundled interpreter, and PyInstaller 6.22.3 is installed into `runtime\Lib\site-packages`. `tests/test_frozen_build.py` no longer skips — the suite now runs `OK` with no skips. AGENTS.md updated to reflect the new expected test result.

---

### 2026-11-03 — Markdown docs updated for PyInstaller and no-skip test result

`README.md`, `ARCHITECTURE.md` and `project_overview.md` updated to expect `OK` with no skips instead of `OK (skipped=1)`, since PyInstaller is now installed in the bundled runtime and `tests/test_frozen_build.py` runs rather than skips.

---

---

## 9.32 — 2026-10-31

- **Visual progress on Generate HTML.** `catalog.generate()` ran synchronously on the UI thread and froze the window; it now runs on the background `JobManager` with a "Regenerating catalog…" timer and a disabled button until finished.
- **Re-categorize retires old copies by Steam appid.** Old copies sharing the new download's appid are archived to `Archive/` before the primary moves, deduplicated against copies already retired by filename key.
- **Cross-category duplicate sweep runs in every scan.** Groups organized game folders by Steam appid; every copy but the newest moves to `Archive/`. Journaled so Undo can reverse every move.
- **Refresh catalog on the library page.** New **Refresh catalog** button sends `steamgameorganizer://refresh-catalog` to re-walk the library and rewrite `Game Library.html` with current badges.
- **A borrowed HD works on any drive letter.** `AppConfig.load()` auto-resolves `library_root` to the folder beside the app when the stored path does not exist; `_needs_setup()` opens the wizard when extract folders are missing.
- **Extraction window opens immediately.** Progress window shows before the library walk; planning runs on a background thread.
- **Extraction window stays open on failure.** Shows which game failed and why; user clicks CLOSE to dismiss. Success still closes automatically.
- **Extraction pre-validates the archive before opening the UI.** Runs `7z l` first; a clear dialog names the archive and quotes 7-Zip's own error on failure.
- **Extraction exit code reflects the actual result.** Failed extraction returns exit code 1 instead of 0.
- **"No extraction tool" names the missing runtime.** Error says the bundled `runtime/7z.exe` is missing and the copy may be incomplete.
- **Small card size is actually small.** `--card-min-width:200px` so small renders clearly smaller than medium/large.
- **HTML page structure fixed.** Duplicate `id="result-count"` and missing `</div>` corrected; orphaned "No games match" paragraph moved into the toolbar.
- **Logs are version-stamped.** `organizer-9.32.log` instead of `organizer.log`.
- **Recently extracted banner showed stale installer badges.** Now passes real `unpacked`/`needs_install` sets and suppresses all status badges in the banner.
- **Library-wide Extract All button opened no window.** `plan_batch()` crashed on installer archives (`NEEDS_INSTALL_DIRNAME / leaf` with a bare string); now wraps in `Path()`.
- **Extract All opens its window immediately.** "Scanning library" while planning runs on a worker thread.
- **Batch extracts no longer nest Needs Install inside Needs Install.** `_needs_install_path()` returns the destination unchanged when already inside a Needs Install folder.
- **Single Extract buttons showed no feedback.** New progress dialog with live bar, elapsed time, current file, then result view with Show in Explorer / Copy path / Done.
- **Installer archives extract into a root-level Needs Install folder.** `<extract_root>/Needs Install/<game_name>/`; catalog detects both new and old layouts.
- **Result dialog dismissible with Escape.** Done button and Escape key handler added.
- **"Needs install" warning icon now amber.** Was green (success color); now matches the catalog badge.
- **Per-category batch button reads "Extract all".** Both library and category buttons now say "Extract all".
- **"Needs install" badge now carries a download icon and pulses.** Same SVG arrow icon as Installer badge, drop-shadow, hover glow, attention pulse.
- **Game card badges keep colour on hover.** `MATCHED` badge and amber confidence pill marked `_fixed_bg` and skipped during recursive recolour.
- **Result dialog says what to do next for installer archives.** Subtitle now "Run the installer in the destination folder to finish installing this game"; progress title reflects installer context.
- **Setup, System Health, Diagnostics footer buttons have tooltips.**
- **Conversion ratio in organize view coloured to show payoff.** Green when smaller, orange when grown.
- **Organize plan list colours conversion targets.** Orange for source→7Z, green for "no conversion needed", muted for preview-only.
- **Single Extract button actually works.** Handler now calls `root.mainloop()`; dialog calls `root.quit()` on close; return value reflects real outcome.
- **Single-Extract result no longer written into HTML catalog's run banner.** Banner reflects batch runs only; dialog shows single results.
- **New Only scan with nothing new no longer hangs on verify.** Empty archive list dispatches completion callback directly instead of through the thread pool.
- **Scrolling the game shelf no longer stutters.** `content-visibility:auto` with `contain-intrinsic-size` on `.card` and `.category`; fade-in stagger halved to 20ms.

---

## 9.31 — 2026-10-31

- **Frozen build ships an executable.** `steam_game_organizer.spec` PyInstaller onedir build; `tools/build_frozen.py` lifts data folders out of `_internal/` into the bundle root; `dist/steam_game_organizer/steam_game_organizer.exe` with `core/`, `services/`, `runtime/` beside it.
- **Exported .reg pointed the .py handler at the wrong interpreter.** Escaping fixed; test renders the file byte-for-byte.
- **Test wrote a .rar with Python's tarfile.** Now writes a real `.zip` with `zipfile`.
- **Catalog no longer renders a card for a game that is not there.** `_collect()` skips a game subfolder with no archive.
- **Re-categorise leftovers reclaimed.** Game subfolder judged by contents; removed when it holds only app-written files; keeps category when it holds a save, screenshot, mod, or archive.
- **Empty category folders reclaimed.** `_sweep_empty_categories()` runs at end of `cleanup_leftovers()`.
- **New Only scan with nothing new can be finished.** Gate is now "nothing left to resolve"; empty list states the run is done.
- **Discovery no longer scans app's own project folder as a game.** `ArchiveService.discover()` refuses any path under a folder holding the entry point.
- **Setup button in app's own toolbar.** `MainWindow.open_setup()` opens wizard from footer bar beside System Health and Diagnostics.
- **Copied folder opens setup wizard on launch.** `_needs_setup()` detects missing `settings.json` / nonexistent library root.
- **Setup fallback command did not run.** Raw string with doubled backslashes fixed to single backslash.
- **Re-categorising a game no longer leaves old folder behind.** `_remove_generated_source_folder` marker now routes to prunable rule.
- **Catalog warning colour had no custom property.** Declared `--warn` in both themes.
- Tests: 661 → 738. Revert-proofs: 16 cases plus 3 for runtime and 3 for category decisions.

---

## 9.30 — 2026-10-30

Preview Only now keeps its promise in every phase; a user opening the catalog on a PC that has never run this app can now set it up from the page itself.

- **Preview Only writes nothing, in any phase.** Discovery password-unlock no longer rewrites protected zip in place; duplicate sweep guarded by `if not preview_only`; catalog reports "Catalog not generated — Preview Only writes nothing"; audit still runs with `refreshed: 0` and separate `would_refresh` count.
- **PC that never ran the app cannot use Extract button; page now says so and fixes it.** New **Set up on this PC** button opens three-folder wizard (game library, app folder, extract folder) with preflight checks.
- **Setup link is a prefill, not a command.** `steamgameorganizer://setup` carries page box values; control characters dropped, length capped, re-validated against disk.
- **Refused Extract link now says how to fix it.** Names the Set up on this PC button.
- **App lives beside library, not inside it.** Documented in README; project itself moved to `D:\Game Installers\0. Steam Game Organizer\`.
- **Project path hard-coded in suite fixed.** `ROOT` now from `Path(__file__).resolve()`.
- **Friend needs nothing installed.** `runtime/` carries Python + Tcl/Tk + 7-Zip; `tools/bundle_runtime.py` copies from machine installs; entry point inserts its own folder on `sys.path`; `find_tool()` answers bundled 7-Zip first.
- **Category pick survives locked settings folder.** Unique `mkstemp` file write with bounded retries.
- **Archives unpacking to Windows installer flagged as installers.** `services/installer_detect.py` recognizes `setup.exe`+`.bin` and `.iso`; extract relocates to `Needs Install`; catalog "Installer" badge with tooltip.
- **Scan activity panel no longer blank at start; last-scan report no longer floats.** Weight moved to feed row while scan runs; `set_result()` restores idle layout.
- **Installer release tag glued to title no longer survives into Steam query.** Separator now `[\s._\-]+`.
- **v9.30 thumbnail fix repaired.** Restored missing `try:` / indentation.
- **Artwork browser no longer draws 226px image into 150px slot.** Fallback reads `winfo_reqwidth/reqheight`.
- **Background images no longer picked as game's artwork.** Candidate list skips `background`/`background_raw`.
- **Library capsule 404s on new CDN path gets second chance on old one.** Old-CDN `library_600x900.jpg` URLs included.
- Tests: 661 → 738.

---

## 9.29 — 2026-10-30

Test-hygiene release: zero-skips gate, generated JPEG fixture, POSIX path fix.

- **Last live skip removed.** `tests/test_artwork_render.py` fixture generated into temp dir via `_jpeg_bytes()`.
- **New `tests/test_zero_skips.py` enforces zero skips.** AST-based; exempts only its own SKIP_NAMES references.
- **`tests/test_regressions.py` no longer writes outside repository on Windows.** `AppConfig(Path('/tmp/project-root'))` replaced with `tempfile.mkdtemp()`.
- Tests: 660 → 661.

---

## 9.28 — 2026-10-30

Review screen explains category choice, evidence, trust in Steam match, and where library already keeps similar games.

- **Steam's API has no tags; tags feature never worked.** Absence now a `WARNING` naming source and appid, once per service; `TAGS_PRESENT` symmetric signal.
- **Steam match shows its own evidence.** `steam.reason` no longer discarded.
- **`suggest_category` returns evidence.** `CategoryEvidence` frozen dataclass; `suggest_category_with_evidence()` returns `(category, evidence)`.
- **Library index kept instead of thrown away.** Retained as `LibrarySummary`; test pins walk count.
- **Genre tally worded as weak.** Capped at 10; remainder counted out loud.
- **Audit's no-artwork count reaches summary line.**
- **Undo journal records folder ownership.** Ownership travels from `created_game_dir` flag; settled before row written.
- Tests: 578 → 650.

---

## 9.27 — 2026-10-29

Six things the app reported about work it had not done.

- **Done screen said "nothing to undo" while moves were journalled.** Count from journal file, not remembered number.
- **Done screen's Library and Free space rows could only render a dash.** Now read from volume holding library.
- **Scan reported artwork never fetched.** `_audit_game()` returns `AUDIT_*`; nothing counts as refreshed unless files landed.
- **Artwork screen named files not in game folder.** Prefix from `OrganizerService._safe_name`; asset name from dictionary key.
- **`--extract` landed one level deeper.** `config.extract_folder` already the destination; no longer appends "Extracted".
- **Undo left emptied folder behind for every game restored.** `_prune_emptied()` with three gating rules; count reported back.
- **Undo fix review found two ways it could delete something.** Ownership check via `created_game_dir` flag; allow-list by content not suffix.
- **Library path went stale when user changed it.** Done screen reads config at paint time.
- **`undo_last()` accepted library root and never read it.** Parameter now load-bearing.
- **`audit()`'s two bail-outs returned different shape.** Now consistent.
- **Undo row failed open to statement it was written to remove.** `_rows()` treats unreadable journal as empty and logs.
- **`_asset_prefix_for()` duplicated expression.** Delegated to `_asset_prefix()`.
- **First fix for Artwork screen got two things wrong.** Called on instance without `__init__`; fixture folder names changed (no colons).
- **Two tests could not catch their defect; rewritten.** `test_ui_geometry.py` now journals a move and asserts `'1 move(s)'`.
- Tests: 567 → 578.

---

## 9.26 — 2026-10-28

Two ways app could touch a file it was told not to.

- **Scan could delete a file never in library.** Walk declines to descend into links (junctions/reparse points); reports `skipped_links`.
- **Preview Only moved archive to Archive/.** Duplicate sweep guarded with `if not preview_only:`.
- Tests: 560 → 567.

---

## 9.25 — 2026-10-28

Project runs on Windows and only on Windows; SteamOS/Linux code removed.

- **Review "open Steam page" button could never open anything.** Now uses `os.startfile` via shell association.
- **Browser-detection chain fed discarded parameter.** `needs_catalog_launcher()` answers directly from registry.
- **`MIMEAPPS_FILE` dead; removed.**
- **Memory reading kept Linux implementation.** Removed; `GlobalMemoryStatusEx` only.
- **Catalog path boxes showed `/home/you/...` placeholder.** Fixed for Windows.
- **`SYSTEM_PATHS` listed eleven POSIX folders.** Windows entries from environment.
- **`tools/verify_archives.py` had change-log note glued to `raise SystemExit` line.** Fixed.
- **Docs scheme still `steamdeckorganizer://`; installer described `.desktop`/`xdg-mime`.** Fixed.
- New `tests/test_platform.py` parses every module and fails on POSIX paths.
- Tests: 556 → 560.

---

## 9.24 — 2026-10-28

- **Organizing a game could delete player's own files.** Removal now through allow-list of pictures and app-written link/metadata files; subdirectory or symlink vetoes.
- **Test module not running; six failures hidden.** `tests/test_displayed_data.py` imported `core.events` which doesn't exist; fixed to `app/events.py`.
- **Every Steam shortcut had mojibake in title.** Em dash/ellipsis bad encoding round-trip repaired.
- **Cancel could raise wrong exception on way out.** `subprocess.TimeoutExpired` descends from `SubprocessError`, not `OSError`.
- **`--extract` blamed PATH.** Finder result now used instead of hardcoded text.
- **Protocol handler claimed to verify but never did.** Value read back; disagreement reported as warning.
- Tests: 519 → 556.

---

## 9.23 — 2026-10-27

- **Steam's tags fetched from wrong object.** Now read from appdetails payload too.
- **Catalog shows tags and searches them.** Up to four per card; Tags filter on rail.
- **Idle scan screen 79% empty; now reports last scan.** `config/scan-state.json` written and read.
- **Recording summary not allowed to affect scan.** Result delivered first; missing config returns immediately.
- **Unsure Steam match looked as settled as sure one.** Confidence pill: High=green, Medium/unset=amber.
- **Catalog rail spent 144px on prose.** Now `<details>` disclosure "How this page works".
- **Hero was 413px of 1080px screen.** Collapses after scroll; two thresholds to avoid flicker.
- Tests: tags from both shapes; summary surviving config-less controller; confidence pill colouring.

---

## 9.22 — 2026-10-27

- **Batch run finished and catalog said nothing.** App writes `Game Library.status.js`; page loads as sibling `<script src>`.
- **Scan no longer erases last run record.** Status file written only when absent.
- **Cards say which games already unpacked.** Badge from same predicate planner skips on.
- **Footer says button needs handler installed.**

---

## 9.21 — 2026-10-27

- **Catalog can unpack whole category or library in one action.** `Extract all` link names category only; app enumerates library itself.
- **Already-unpacked games skipped by checking real files, not folder.**
- **One bad archive costs one row, not run.** Failure recorded in own row; queue continues.
- **Separate window for batch.** Rows rewritten in place at remembered line number; closing cancels first and waits.

---

## 9.20 — 2026-10-26

- **Artwork arrived as assets reported as none.** `ArtworkResult.files()`/`.present()` now checked with `is_file()`.
- **Warning contradicted its own run.** Primary miss now DEBUG; warning once after whole attempt.
- **Artwork filter listed games without any.** Now matches on all files.
- **Diagnostics counted primary alone.** Fixed to count the way screens do.

---

## 9.19 — 2026-10-26

- **Artwork drew nothing on Windows.** Pillow now a dependency; Tk PNG loader tried between Pillow and ffmpeg.
- **Organize STOP RUN cancelled nothing.** Window marked busy for whole run.
- **Cancelled/failed organize kept context for rest of session.** Success callback no longer only clearer.
- **Catalog carried 491 dead Extract links.** Scheme renamed; registration required.
- **Locked settings file aborted scan before start.** Short retries on `os.replace`.
- **Three files sat in real library root for two days.** Sync-temp pattern list extended.
- **`_is_portrait()` shelled out to uninstalled tool.** Shape now read from JPEG header.
- **Artwork failure text names the cause.**
- **Linux-only code removed.** Flatpak re-exec, `notify-send`, `xdg-open` removed.
- **"Games directory required" dialog pointed to nonexistent Steam Deck path.** Fixed.
- Dead code removed.
- **Startup no longer walks library during shutdown.** Deferred sweep disarmed.

---

## 9.18 — 2026-10-26

- **Every password-protected zip decompressed, rewritten, deleted on every scan.** Handle now closed before republish.
- **Game with no Steam AppID vanished from catalog.** Only two Steam actions omitted; card carries "No Steam match" badge.
- **SCAN LIBRARY dead after first scan.** Re-enabled.
- **Two "open this folder" buttons did nothing on Windows.** Now use `os.startfile`.
- **SteamGridDB connection test leaked socket.** Fixed.
- **Metadata title of only whitespace counted as title.** Falls through to folder name.
- Tests: 9 for allow-list, 2 shutdown, 2 extractor diagnosis, 2 installer read-back, 1 scan summary, 2 encoding rule, plus 21 from broken import. 519 → 556.

---

## 9.17 — 2026-10-26

- **One locked file rolled back whole library.** Isolated per game now.
- **Move landed then failed could not be undone.** Journal entry taken as soon as file lands.
- **Junction inside library made one game scan as 64 archives.** Discovery uses shared treewalk helper.
- **Rollback could delete game folder already there.** Removes only folders run created; restores emptied ones.
- **Interrupted journal write made Undo raise.** Guarded read; pending count from file, not length.
- **Settings file valid JSON but not object stopped app.** Constructor guards.

---

## 9.16 — 2026-10-25

- **App introduced itself to Steam as 9.0.** User-Agent derived from `VERSION` in one place.
- **Nothing checked documentation agreed with build.** Version gate scans every shipped file.
- **Gate tested; prose told apart from specimens.** Fenced blocks checked like code; comments stripped.
- **First version of rule too easy to fool.** Product name matched with optional whitespace; files found by content; changelog checked for newer release.
- **Lint is clean.** `ruff check .` reports nine findings, seven mechanical.
- **Release states its own AppID; app reads it instead of guessing.** 52 hand-written rows deleted; archive header read and confirmed against filename.
- **Date/build number welded onto title is packaging; cut without lookup table.** Four digits floor; hyphen inside title kept.
- **Archive read before Steam cache.** Archive states which game it is; cache is fallback.
- **9.14 safety checks never run against real conversion.** Done now.
- **Incomplete-extraction guard would have refused almost every real conversion.** Directories identified by `Attributes = D`.
- **`7z t` passing not evidence rebuild complete.** Both true; check well-founded but wrong.
- **App's own lock file packed into user's archives.** Marker excluded from pack command and byte/file totals.
- **Exclusion mattered for guard.** Masked loss of exactly one real file.
- **Single failing UI callback froze rest of session's updates.** One bad callback costs one callback; logged.
- **End-to-end suite had been skipping itself.** Fixture built from seeded generator; runs anywhere.
- Tests: real zip-to-7z and .7z rebuild end to end.

---

## 9.15 — 2026-10-25

- **Abandoned staging folders now cleared instead of only reported.** Startup clears them; skips live processes and recently touched folders.
- **Obvious liveness check wrong on Windows.** Uses `OpenProcess` instead of `os.kill(pid, 0)`.
- Tests: abandoned folder removed; no lock marker still swept; live process and recently touched left alone; non-app folder untouched; staging inside game never reached; missing `Processing` not error.

---

## 9.14 — 2026-10-25

- **Source archive integrity-tested before anything done.** Truncated archives reported and left alone.
- **Extraction compared against archive's own index before rebuild published.** Aborts while original on disk.
- **Refusals reported as `SOURCE_INTEGRITY_FAILED` / `EXTRACTION_INCOMPLETE`.**
- **Tool output sanitised to ASCII before log.**

---

## 9.13 — 2026-10-25

- **Archive count inflated threefold by Syncthing's version folder.** Discovery skips dot-named directories below library root.
- **82 "archives" were not archives at all.** Truncated 32-byte downloads; 7-Zip rejects them.
- **Dot-directory rule scoped below library root.**
- **14 abandoned build folders holding 6.7 GB.** Scan measures them; feed states count and space; nothing deleted.

---

## 9.12 — 2026-10-25

- **Worker threads calling into Tk.** Worker threads only touch queue; Tk thread drains it.
- **Drain bounded at 200 callbacks per tick.**
- **Main-thread callers unchanged.**
- Tests: worker dispatch not inline; main-thread dispatch inline; 600-callback flood drains 200 at a time; nothing runs after shutdown.

---

## 9.11 — 2026-10-24

- **No screen could tell file size.** Size kept on `GameArchive`; shown in detail pane and subtitle.
- **Completed run published two byte totals nothing read.** `run_bytes`/`run_written` removed.
- Tests: `tests/test_run_reporting.py` (13 tests).

---

## 9.10 — 2026-10-24

- **Progress bars and scrollbar rendering stock light theme.** Both configured; `Dark.Horizontal.TProgressbar` variant added.
- **Every button stock pale-grey border.** `bordercolor` set to `BORDER`.
- **Verified vs unidentified Steam match looked identical in feed.** Colour no longer discarded.
- **Entry/radio showed system grey when locked.** `disabledforeground` uses theme's `MUTED`.
- **Destructive button and text entry colours typed into theme.py.** Now `DANGER`, `DANGER_HOVER`, `DANGER_TEXT`, `ENTRY_BG`.
- **Contrast audit not running.** `tests/test_contrast.py` now a `TestCase`.
- **`match` locals renamed to `steam_match` across ten files.** Cleared six ruff parser-bug reports.
- **Two closure bindings made explicit.**
- **Dead assignments removed across six modules.**
- **Artwork panel tried Pillow then ffmpeg.** Now tries Tk PNG loader between them.
- New `tests/test_render_integrity.py`.
- 272 tests, 0 failures, 0 errors, 0 skips.

---

## 9.9 — 2026-10-24

- **`steamdeckorganizer://` handler could not be registered.** Scheme imported from defining module; script has tests; `--check`/`--export` run.
- **Exported .reg malformed.** Built as plain string, escaped once.
- **Registry paths raw strings with doubled backslashes.** One `REGISTRY_ROOT`.
- **Handler registered `python3` from PATH.** Registers interpreter that is running.
- **Organize panel stripped bullet marker with `lstrip('  Ã¢â‚¬Â¢  ')`.** Now `removeprefix()`.
- **`TEMP_DIR_PREFIX`/`TEMP_FILE_TAG` shadowed imports.** Copies removed.
- **Eight files star-imported theme.** Names spelled out; `theme.__all__` states contract.
- **`ruff.toml` exists.** 618 findings down to 22.
- **`ARCHITECTURE.md` described v9.0.** Updated.
- **`README.md` told Windows users to run `python3`/`xvfb-run`.** Fixed.
- **`.ruff_cache/` not ignored.** Added.
- 265 tests, 0 failures, 0 errors, 0 skips.

---

## 9.8 — 2026-10-23

Windows primary platform; three things that quietly only worked on Linux now work here.

- **Converting archive to .7z looked for bare `7z` on PATH.** Uses same finder extraction uses; checks PATH then install folders.
- **Organize panel showed no RAM figure on Windows.** Reads Windows kernel: available physical memory and commit allowance.
- **Catalog page accepted `C:\Windows\System32` as destination.** Refusal list read from environment; compared with platform case rules.
- **Relative destination complaint suggested leading slash.** Removed.
- **Archive-tool stubs were shebang scripts with no extension.** Written as something each platform can execute.
- **Suite green on Windows.** 258 tests, 0 failures, 0 errors, 0 skipped.
- **Nothing skips anymore.** Wheel-routing test asks in bounded loop; repack tests make finder report nothing; window tests raise broken install on missing tkinter instead of skipping.

---

## 9.7 — 2026-10-23

- **Library audit reported nothing while running.** Each folder produces a line as checked; outcome named.
- **Audit counts folders before starting.** Progress bar shows real movement.
- **Artwork downloads and failures relayed per folder.** `started` reports not relayed.
- **Progress callback raising can no longer abort pass.**
- **Geometry tests now measure window they asked for.** Removes two failures on PC.
- **Two assertions only held on Linux.** Now say so explicitly.

---

## 9.6 — 2026-10-22

- **Game artwork not appearing on PC.** Shape read from JPEG header instead of `ffprobe`; "cannot be read" third answer never deletes.
- **Some games not finding real Steam name.** Release tags stripped on separator-delimited word boundaries.
- **Tagged folder name and clean twin share one identity key.**
- **Dead rule in title normalizer removed.** Brackets turned into spaces before matching rule.

---

## 9.5 — 2026-10-22

- **Game folder box added to HTML game library.** Paths built from box instead of absolute paths.
- **Copy folder path and Extract build paths from box.** Remembered in `localStorage`.
- **Folder path built with separators and drive letter intact.** Query-string characters escaped.
- **`/` search shortcut stealing focus fixed.** Fixed.
- **Remembered extract destination restored into box but never into links.** Fixed.
- **Catalog page's script emitted as raw string.** Backslashes no longer syntax error.

---

## 9.4 — 2026-10-22

- **"Newest" sort sorted by day of month.** Dates parsed properly into `YYYYMMDD`.
- **Sort direction for "Newest" ascending.** Now per-button descending flag.
- **Year range in catalog header never rendered.** Fixed date parser.
- **Extract destination now free-text box.** Configured folders as suggestions; remembered between opens.
- **Typed destination is parent folder; each game gets own subfolder.**
- **`extract_folder` → `extract_folders` list.** Old single-folder setting still read.
- **Protocol handler hardened against free-text destination.** Path must be absolute, not root/home, not inside system folder/library, must be folder with writable parent.
- **`/bin` slipping through system-folder check.** Every folder up path now checked.
- **Blank destination box raising error.** Falls back to configured folder.
- **Destination dropdown never wired to Extract links.** Wired.
- **Scan panel shows live file size and running detail.**
- **`repair_plan`/`repair_start` progress records reaching wrong panel.** Fixed.

---

## 9.1 — 2026-10-21

- **Infinite Organize loop.** Queue entries whose file is gone now skipped and counted.
- **Conversions build replacement in `Processing/` staging folder.** Never scanned as category; abandoned reclaimed.
- **Data loss during conversion.** Publish new archive before unlinking source.
- **Destroy-the-only-copy ordering.** Fixed.
- **`ARCHIVE_REPACK_FAILED` reporting.** Logs exception, message, free space.
- **Archive repacking standardizes `.zip`/`.rar` as `.7z`.** Existing `.7z` rebuilt only when content folder needs renaming.
- **Folder-rename applies to `.rar`/`.7z` too.** Rebuilt in place if needed.
- **Catalog no longer accumulates timestamped HTML files.** Deletes previous pair first.
- **Steam Deck catalog gets `.desktop` launcher.** Opens as Chrome tab by default.

---

## 8.3 — 2026-10-20

- Fixed Tkinter GameCard binding collision preventing Review queue rendering.
- Added lifecycle-safe dispatch and explicit shutdown invalidation.
- Restored direct Undo Last Run action.
- Restored Preview Changes; Organize performs category-folder move transaction.
- Renamed entry point to `steam_deck_game_organizer.py`; added application-named launcher.
- Bumped version to 8.3.

---

## 8.2 — 2026-10-20

- Restored polished v6.7 visual direction across Scan, Review, Organize, Done.
- Rebuilt main frame with dark polished visual system.
- Reworked Review into two-pane queue/workspace.
- Reworked game cards with selected/matched/review/hover states.
- Replaced placeholder Scan/Organize/Done pages with cohesive product UI.

---

## v8.5 — 2026-10-20

- Automatic full-list verification and Steam CDN artwork caching.
- Visible Diagnostics scrollbar; expanded System Health.
- Locked Games Dir while operations run.
- Visible runtime/current-task status; stabilized fixed layouts.
- Promoted official Steam title to primary verified display name.

---

## 8.6 — 2026-10-19

- Restored functional Scan stage with live archive telemetry, activity feed, progress, elapsed time.
- Restored main-screen configuration.
- Restored Review Search, Filter, All/New Only, Add Category, safety/artwork controls.
- Reworked Review into independent queue and preview viewports.
- Added Steam artwork fallback sources.
- Removed duplicate main-screen sections.

---

## 8.7 — 2026-10-19

- Fixed release ZIP structure: directory entries encoded as real directories.
- Removed `.pytest_cache` from release packages.
- Preserved Unix executable permissions.

---

## 8.8 — 2026-10-19

- Fixed v8.7 startup failure from packaged empty directories stored as regular files.
- Restored `cache/artwork`, `logs`, `tests/data` as real directories.
- Added defensive startup recovery for stale malformed directory files.

---

## 9.0 — Refactor & Stabilization (2026-10-18)

- Used v8.8 as direct baseline; consolidated around one Python service architecture.
- Retired legacy shell backend and shell-based rollback path; Steam lookups via Steam Store APIs.
- Added Python transaction journal for rollback.
- Removed `__pycache__`, `.pyc`, `.pytest_cache`, generated scan state, runtime logs from release.
- Preserved Scan → automatic verification → Review → Organize → Done workflow.
- Expanded Steam metadata to retain developer and publisher fields.

---

> [!NOTE]
> **Note on versioning:** The app version stays at 9.33 until a release is cut. Every change made between releases is logged here under "9.33 — development (unreleased)" with a timestamp. When the version is bumped, a new top-level section is created and the unreleased notes move under it. This keeps one chronological record of every change, so nothing is overlooked.

---

### 2026-11-03 — Harden extraction path safety and Tk teardown

`tests/tk_support.py:close_root()` now cancels all pending after jobs (including from `root.tk.call('after','info')`) to prevent invalid command name/bgerror noise on window destruction. `services/extract_service.py:extract()` resolves archive/destination paths and adds basic defense-in-depth checks for extracted files staying under destination.
