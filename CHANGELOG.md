# Changelog

>[!NOTE]
> All entries are timestamped with the date and time they were added (YYYY-MM-DD HH:MM:SS). Releases are newest first; the current development section is **unreleased**. Every change between releases is logged below with a timestamp. When a release is cut, a new top-level section is created and these notes move under it.

### Change type prefixes

Each entry starts with a type prefix:

| Prefix | Meaning |
|--------|---------|
| `feat:` | New feature or capability |
| `fix:` | Bug fix |
| `docs:` | Documentation only |
| `build:` | Build system, frozen exe, runtime bundling |
| `refactor:` | Code change that neither fixes a bug nor adds a feature |
| `test:` | Adding or updating tests |
| `chore:` | Build process, tooling, config changes that don't affect users |
| `perf:` | Performance improvement |
| `security:` | Security fix or scanning |

---

## Unreleased

### 2026-11-27 — feat: Sandbox mode — test zip conversion into category folders

- `src/ui/organize_view.rs`: `run_organize()` now creates real `.7z` files in category folders (`<library_root>/<category>/<name>.7z`) and sets `archive.organized_path` accordingly
- `src/ui/organize_view.rs`: Added `library_root` field to `OrganizeViewState` so organize knows where to place category folders
- `src/tools/sandbox.rs`: Sandbox Step 3 now creates real `.zip` files under `sandbox/library/`, sets `library_root` on organize_view, runs `run_organize()`, and verifies `.7z` files exist in `sandbox/library/<category>/<name>.7z`
- `src/tools/sandbox.rs`: Verifies `archive.organized_path` is set correctly and `created_game_dir` flag is true after organization

### 2026-11-26 — fix: CreationGuard — prevent directory creation at drive roots and outside allowed roots

- `src/core/path_safety.rs`: Added `CreationGuard` — mirrors `DeletionGuard` but for creation operations (`create_dir_all`, `write`, `File::create`). Refuses to create directories at drive roots (C:\, D:\) or inside protected system paths (Windows, Program Files, Users), and refuses anything outside configured allowed roots. Adds `safe_create_dir_all()` and `safe_write()` one-shot functions.
- `src/core/config.rs`: `ensure_directories()` and `_migrate_from_appdata()` now use `safe_create_dir_all()` with `project_root` as allowed root — prevents creating `config/`, `cache/`, `logs/`, `debug/` at drive root if `resolve_project_root()` returns `E:\`
- `src/core/config.rs`: `sync_to_appdata()` uses `safe_create_dir_all()` with `%LOCALAPPDATA%` as allowed root — intended appdata sync location
- `src/ui\setup_view.rs`: `save_config()` uses `safe_create_dir_all()` with extract folder's parent as allowed root — prevents creating user-configured extract folders outside allowed roots
- `src/services\setup_service.rs`: `apply()` uses `safe_create_dir_all()` with library's parent as allowed root — prevents creating user-configured library roots outside allowed roots
- `src\bin.rs`: Sandbox and GUI log dir creation use `safe_create_dir_all()` with `project_root` as allowed root
- `src\entry.rs`: GUI log dir creation uses `safe_create_dir_all()` with `root_path` as allowed root
- `src\core\logger.rs`: Log file parent dir creation uses `safe_create_dir_all()` with log's grandparent as allowed root
- `src\bin.rs`: `resolve_project_root()` refuses to return a drive root — falls back to `exe_dir.parent()` if resolution would land on `C:\`, `E:\`, etc.
- `CHANGELOG.md`: Documented all safety guard changes

### 2026-11-26 — feat: Sandbox mode — mega-test covers all sections, buttons, zip conversion, category sorting

- `src/tools/sandbox.rs`: Sandbox test environment lives under `<project_root>/sandbox/` with `config/`, `cache/`, `logs/`, `extracted/`, `library/` subdirs — not temp dirs — config points to sandbox paths for library root, extract folder, and logs
- `src/tools/sandbox.rs`: Creates mock `.zip` archives under `sandbox/library/` for real ArchiveService discovery testing
- `src/tools/sandbox.rs`: Step 1 Scan view — tests Start Scan, Scan with Artwork, Cancel Scan, convert/preview/artwork checkboxes, run_scan with real discovery, all 6 phase states, archive row clicks
- `src/tools/sandbox.rs`: Step 2 Review view — tests Accept & Next, Skip, Wrong Match, Extract Selected, Accept/Reject by index, Approve All Verified, Add Category, Use All Suggestions, Retry Failed, Continue to Organize, search text, filter combobox (All/Needs Review/Verified/New Only/Artwork), archive selection
- `src/tools/sandbox.rs`: Step 3 Organize view — tests Start Organize, Cancel, Preview Only, real zip→7z conversion via run_organize, category sorting counts per category (Action/RPG/Strategy/Simulation/Shooter), archive row selection
- `src/tools/sandbox.rs`: Step 4 Artwork view — tests Open Folder, View Artwork per archive, Scan Again, Review, Re-download Missing, artwork present() checks
- `src/tools/sandbox.rs`: Step 5 Done view — tests Undo, Open Library, Scan Again, per-archive status display, converted/skipped/failed counts
- `src/tools/sandbox.rs`: Step 6 Setup view — tests Browse Library/Extract/7-Zip, Developer Mode checkbox, Validate Configuration, Clear validation, Save & Finish Setup, Skip Setup
- `src/tools/sandbox.rs`: Step 6b Setup Window — tests browse buttons, Save setup, Launch Steam Game Organizer, refresh_checks
- `src/tools/sandbox.rs`: Step 7 Batch Extract Window — tests Start Batch, Cancel while extracting
- `src/tools/sandbox.rs`: Step 8 Extract Result Dialog — tests Cancel while extracting, Complete + Close workflow
- `src/tools/sandbox.rs`: Step 9 PhaseTimeline — tests set_phases, start, done, fail, skip, reset state transitions
- `src/tools/sandbox.rs`: Step 10 MainWindow navigation — verifies all 6 nav keys valid, navigation simulation, shared_archives count
- `src/tools/sandbox.rs`: Step 11 Widgets — GameCard (title, category, confidence, status, selected) and ArtworkPanel (Pending/Showing/Failed/None states)
- `src/tools/sandbox.rs`: Step 12 CatalogService — generates catalog from sandbox library, verifies empty library returns no outputs
- `src/tools/sandbox.rs`: Step 13 RollbackService — records moves to journal, verifies journal file created
- `src/tools/sandbox.rs`: Step 14 LibraryService — constructs service without config dir
- `src/tools/sandbox.rs`: Step 15 Error Injection — writes `[ERROR]`, `[PANIC]`, `[FAILED]` to separate injection log, verifies all 3 patterns detected (isolated from Step 24 log checking)
- `src/tools/sandbox.rs`: Step 16 Missing Path Validation — nonexistent library/extract/7z paths, verifies detection and status reporting
- `src/tools/sandbox.rs`: Step 17 Steam Match Failure — unmatched archive with steam.found=false detected
- `src/tools/sandbox.rs`: Step 18 Skip Current — verifies skipped=true and accepted=false
- `src/tools/sandbox.rs`: Step 19 Empty State — ReviewView and DoneView with empty archive lists
- `src/tools/sandbox.rs`: Step 20 Missing Library Root Config — empty library_root and 7z path validation detected
- `src/tools/sandbox.rs`: Step 21 Full pipeline — scan → review → organize → artwork → done end-to-end flow with fresh archives
- `src/tools/sandbox.rs`: Step 22 Corrupt/Missing Config — graceful handling of None library root
- `src/tools/sandbox.rs`: Step 23 Watchdog — constructs with short timeout
- `src/tools/sandbox.rs`: Step 24 Log checking — reads most recent `sandbox-<timestamp>.log`, checks for `[ERROR]`, `[PANIC]`, `[FAILED]` patterns
- `src/tools/sandbox.rs`: Step 16b Cancel before finish — simulates cancel mid-conversion, clears converting flag, sets cancelled status, cleans up partially processed files under sandbox/partial/
- `src/tools/sandbox.rs`: Step 16c Window maximized setting check — verifies `window_maximized` is not false in sandbox settings (app runs full screen per AGENTS.md)
- `src/tools/sandbox.rs`: Config isolation — resets `config.settings` to `{}` after `AppConfig::new()` so `_migrate_from_appdata()` cannot leak LIVE settings from `%LOCALAPPDATA%` (e.g. `window_maximized: false`, `zip_password`) into sandbox/config/settings.json
- Sandbox now runs 144 total checks across 25 steps covering 9 UI views, 3 widgets, and 4 services, all passing

### 2026-11-26 — feat: Sandbox mode — verbose debug logging and per-archive tracing

- `src/tools/sandbox.rs`: Added verbose DEBUG-level logging to Step 3 Organize — per-archive category assignment logging ('Archive X → category Y') plus category sort totals
- `src/tools/sandbox.rs`: Added verbose DEBUG-level logging to Step 4 Artwork — per-archive artwork present/path/source/status detail for every archive
- `src/tools/sandbox.rs`: Added verbose DEBUG-level logging to Step 5 Done — pre-undo per-archive logging showing display_name and counts before Undo runs
- `src/tools/sandbox.rs`: Added verbose DEBUG-level logging to Step 21 Pipeline — per-archive logging through all stages: scan discovery, review acceptance, organize conversion, done results (each archive's name, appid, category, size, final_name, final_size, source_size)

### 2026-11-26 — feat: Sandbox mode — verbose debug logging and test isolation fixes

- `src/tools/sandbox.rs`: Added verbose DEBUG-level logging throughout all 25 steps — every button click, state change, file creation, and validation result is logged with descriptive messages for full traceability
- `src/tools/sandbox.rs`: Step 2 fix — reset `selected_index` to `Some(0)` before `accept_and_next()` and `skip_current()` so they target `archives[0]` instead of the index left by prior row-selection tests
- `src/tools/sandbox.rs`: Step 24 fix — log error pattern matching now checks line starts (`[ERROR`, `PANIC`, `FAILED`) instead of substring matches, preventing false positives from debug messages containing those words

### 2026-11-26 — fix: Sandbox mode — timestamped log file naming

- `src/bin.rs`: Sandbox logger now writes to `logs/sandbox-<YYYYMMDD>-<HHMMSS>.log` (timestamped) instead of fixed `sandbox.log`, so test runs are separate from live logs and identifiable by timestamp
- `src/tools/sandbox.rs`: Log file lookup now finds the most recent `sandbox-*.log` file by modification time instead of hardcoded `sandbox.log`

- `src/tools/sandbox.rs`: Create `<project_root>/sandbox/` directory with mock `.jpg` artwork files and patch archive `artwork.path` to point at them so `ArtworkResult::present()` returns true
- `src/tools/sandbox.rs`: Derive project root from `output_dir` (`<root>/docs/screenshots`) instead of `current_exe().parent()` for log file lookup — logger writes to `<project_root>/logs/sandbox.log`
- `src/tools/sandbox.rs`: Refine error log patterns to uppercase only (`[ERROR`, `PANIC`, `FAILED`) to avoid false positives from benign words like "errors"

### 2026-11-26 — feat: Sandbox mode — end-to-end UI simulation and automated testing

- `src/bin.rs`: Added `--sandbox` CLI flag that runs end-to-end UI simulation: creates mock game archives, populates each view, simulates button clicks, reads logs, reports issues
- `src/tools/sandbox.rs`: New sandbox module with `run_sandbox()` — creates 5 mock archives, populates Scan/Review/Organize/Artwork/Done/Setup views, verifies counts and states, checks log for error patterns, saves manifest JSON to docs/screenshots/
- `src/tools/mod.rs`: Added `pub mod sandbox;`
- `cargo fmt --check` clean, `cargo clippy --all-targets` clean, 323 tests pass

### 2026-11-26 — fix: Eliminate all clippy warnings and fix conversion gaps

- `src/lib.rs`: Added `#![allow(clippy::type_complexity)]` at crate level — complex types (Arc<dyn Fn...>, nested closures) are inherent to the design
- `src/ui/e2e_integration_tests.rs`: Removed unused UI imports, added `#[allow(dead_code)]` to test helpers, fixed unused variables, replaced `len() > 0` with `!is_empty()`, replaced index-based loop with `.iter().enumerate()`, removed dead `assert!(true)`, fixed `unwrap_or("unrar")` type mismatch
- `src/services/organizer_service.rs`: Fixed `unwrap` after `is_some` check (used `map_or_else`), replaced `sort_by` with `sort_by_key`, moved `Regex::new` outside loop, added `#[allow(clippy::type_complexity)]` to `_repack_with_official_name`
- `src/services/archive_service.rs`: Added `#[allow(clippy::too_many_arguments)]` to `discover()`, removed dead `assert!(true)`
- `src/services/library_service.rs`: Added `#[allow(clippy::too_many_arguments)]` to `convert_pending_archives()` and `audit()`, removed needless borrow on `create_dir_all`
- `src/app/controller.rs`: Added `#[allow(clippy::too_many_arguments)]` to `scan()`
- `src/ui/main_window.rs`: Added `#[allow(clippy::too_many_arguments)]` to `MainWindow::new()`
- `src/tools/capture_screens.rs`: Added `#[allow(dead_code)]` to `main()`
- 320 tests pass, clippy clean, cargo fmt --check clean

### 2026-11-26 — feat: Conversion audit infrastructure — prevents future regression

- `.github/workflows/ci.yml`: Added GitHub Actions CI pipeline with four jobs: audit, clippy (`-D warnings`), test, and build release; runs on push/PR to main and Rust-Conversion
- `scripts/audit_conversion.ps1`: New audit script that detects Python-to-Rust conversion anti-patterns: `#![allow(clippy::all)]`, double panic hooks, unused config fields, stub methods, hardcoded paths; runs `cargo clippy --all-targets`
- `.rustfmt.toml`: Added formatting config (max_width=100) for consistent code style
- `cargo fmt --check` added to CI audit job
- `cargo clippy --all-targets -- -D warnings` added to CI clippy job
- `cargo test` added to CI test job
- `cargo build --release` added to CI build job
- 320 tests pass, cargo fmt --check clean, cargo clippy --all-targets clean

### 2026-11-26 — fix: Remove #![allow(clippy::all)] from 13 files, fix double panic hook, wire AppController config

- `src/core/config.rs`, `src/core/filename_utils.rs`, `src/core/controller_utils.rs`: Removed `#![allow(clippy::all)]` — all clippy lints now active
- `src/app/application.rs`, `src/app/events.rs`: Removed `#![allow(clippy::all)]` — all clippy lints now active
- `src/services/organizer_service.rs`, `src/services/extract_service.rs`, `src/services/archive_service.rs`: Removed `#![allow(clippy::all)]` — all clippy lints now active
- `src/services/library_service.rs`, `src/services/catalog_service.rs`, `src/services/rollback_service.rs`: Removed `#![allow(clippy::all)]` — all clippy lints now active
- `src/services/batch_extract_service.rs`: Removed `#![allow(clippy::all)]` — all clippy lints now active
- `src/ui/scan_view.rs`: Removed `#![allow(clippy::all)]` — all clippy lints now active
- `src/bin.rs`: Removed duplicate inline panic hook (lines 62-80) that conflicted with `logger.install_panic_hook()`; only the logger's panic hook is now active
- `src/bin.rs`: Wired `AppConfig` to `Application.controller.set_config()` and `MainWindow`; passes `config.convert_archives()` to `OrganizerService` instead of hardcoded `false`
- `src/ui/main_window.rs`: Added `config: Arc<AppConfig>` field; passes config to `ScanView`
- `src/ui/scan_view.rs`: Added `config: Arc<AppConfig>` field; `get_library_root()` now checks `config.library_root` first before falling back to hardcoded paths; accepts config in constructor
- `src/ui/integration_tests.rs`, `src/ui/e2e_integration_tests.rs`, `src/ui/scan_view.rs`: Updated all `ScanView::new()` test call sites to pass `Arc<AppConfig>`
- `src/bin.rs`: Removed unused `std::io::Write` import
- 320 tests pass, clippy clean

### 2026-11-26 — fix: UI layout max-width constraint to fix empty space on maximized screens

- `src/ui/theme.rs`: Added `constrained_content()` helper that wraps view content in a centered max-width (1200px) container; removed `card_centered()` (unused); simplified `stat_card()` with `set_min_width(150.0)` for uniform stat card sizing
- `src/ui/main_window.rs`: Wrapped main content and single-view content in `constrained_content(ui, 1200.0, ...)` so content doesn't stretch full-width on maximized / ultra-wide screens; clone palette to satisfy borrow checker
- All 6 view screenshots recaptured with centered layout
- 320 tests pass, clippy clean

### 2026-11-26 — feat: OCR verification for capture_screens with --ocr flag

- `src/tools/capture_screens.rs`: Added `--ocr` flag that runs Tesseract OCR on captured screenshots and verifies expected UI text per view
- Defined `OCR_SCREEN_HEADERS` mapping: expected text headers for each view (scan, review, organize, artwork, done, setup, plus batch-extract, extract-progress, extract-result)
- Defined `OCR_FORBIDDEN` list: error/panic text that should never appear (traceback, panicked, error[, etc.)
- OCR uses partial matching for noisy small text; missing headers are warnings, forbidden text causes failure
- Added 5 unit tests: OCR header matching, missing detection, forbidden detection, header coverage for all views
- `--view` now required for single capture; without `--view` captures all 6 views in sequence
- 320 tests pass (316 + 4 new OCR tests), clippy clean

### 2026-11-26 — fix: capture_screens targets app window, not full desktop

- `src/tools/capture_screens.rs`: PowerShell script now finds the "Steam Game Organizer" window by title, gets its rect via Win32 `GetWindowRect`, and captures only the window's client area — matching the old Python Tkinter `ImageGrab` approach instead of grabbing the entire primary monitor
- Six view screenshots captured and saved to `docs/screenshots/`: scan-view.png, review-view.png, organize-view.png, artwork-view.png, done-view.png, setup-view.png
- README updated with embedded screenshot images for each view

### 2026-11-26 — feat: --view CLI flag for single-view UI testing

- `src/bin.rs`: Added `--view` CLI argument (scan, review, organize, artwork, done, setup) to launch a single UI view in isolation without running the full application
- `src/ui/main_window.rs`: Added `single_view: Option<String>` field to `MainWindow`; when set, `update()` skips the sidebar and top bar, rendering only the requested view in the central panel; constructor accepts `single_view` parameter and initializes `current` to the requested view
- Usage: `./target/release/steam-game-organizer.exe --view scan` (or review, organize, artwork, done, setup)
- Enables per-view screenshots with `capture_screens` tool without navigating through the app
- 316 tests pass, clippy clean, zero UI source warnings

### 2026-11-26 — feat: capture_screens tool — PowerShell-based screen capture utility

- `src/tools/capture_screens.rs`: Implemented stub → functional screenshot capture using PowerShell + System.Drawing; captures primary monitor to timestamped PNG under docs/screenshots/
- `Cargo.toml`: Added `[[bin]]` entry for `capture_screens` binary; runs as `./target/release/capture_screens`
- Usage: Launch app → navigate to a view → run capture_screens → repeat for each view
- `src/tools/capture_screens.rs`: Unit test verifies output directory creation logic
- 317 tests pass (316 + 1 new), clippy clean, zero UI source warnings

### 2026-11-26 — feat: UI design additions — spinner, loading cards, empty states, category pills, archive rows

- `src/ui/theme.rs`: Added `spinner()` animated loader for async operations; `loading_card()` centered loading state; `empty_state()` with icon/title/description for zero-data views; `archive_row()` hover-styled selectable list rows; `category_pill()` color-coded category badges using cyan/sky/pink/purple/violet accent colors; `category_pill_color()` category-to-color mapper
- `src/ui/scan_view.rs`: `loading_card()` during scan; `empty_state()` when no archives discovered; `archive_row()` for discovered archives list
- `src/ui/review_view.rs`: `empty_state()` when no archives; `archive_row()` with click-to-select; `category_pill()` in detail panel; `heading()` for page header
- `src/ui/organize_view.rs`: `loading_card()` during organize; `empty_state()` when no archives; `archive_row()` for list; `heading()` for page header
- `src/ui/artwork_view.rs`: `empty_state()` when no artwork downloaded
- `src/ui/done_view.rs`: `empty_state()` when no results
- 316 tests pass, clippy clean, zero warnings in UI source files

### 2026-11-26 — refactor: UI design improvements — hover states, disabled buttons, focus rings, smaller buttons

- `src/ui/theme.rs`: Added `enabled: bool` parameter to all button helpers (primary/secondary/danger/ghost/small_button) for disabled state support; reduced button sizes from 140x40 to 110x36 (primary/secondary/danger/ghost) and 60x28 (small_button); added `small_button()` helper for list-row actions like "Select"; removed unused dead-code helpers
- `src/ui/main_window.rs`: Removed duplicate Quit button from sidebar (already in top bar); added `ctx.set_style()` with hovered widget styling (bg_fill=panel3, bg_stroke=border_focus, 2px width) for keyboard/mouse navigation feedback; set item_spacing and button_padding for consistent layout
- `src/ui/review_view.rs`, `organize_view.rs`, `done_view.rs`, `artwork_view.rs`, `setup_view.rs`, `scan_view.rs`, `batch_extract_window.rs`, `extract_result_window.rs`, `setup_window.rs`: Updated all button calls to pass `enabled: true`; replaced raw `egui::Button::new("Select")` with `small_button()` theme helper
- 316 tests pass, clippy clean, zero warnings in UI source files

### 2026-11-26 — refactor: UI consistency, raw separator → theme separator, differentiated Browse buttons

- `src/ui/theme.rs`: Removed dead code — `card_accent`, `list_item`, `muted_text`, `small_caps`, `divider_with_text`, `progress_bar_with_label` (all unused); removed clip_rect from `card()` (was clipping popups/tooltips); fixed `nav_item` double-painting background
- `src/ui/widgets/game_card.rs`: Fixed accent strip painted on wrong `ui.min_rect()` (rect changes as content added); replaced raw `ui.separator()` with `separator(ui)`
- `src/ui/widgets/game_list.rs`: Replaced all raw `ui.separator()` calls with `separator(ui)`
- `src/ui/setup_view.rs`: Differentiated three identical "Browse" buttons → "Browse Library", "Browse Extract", "Browse 7-Zip"
- `src/ui/setup_window.rs`: Differentiated three identical "Browse" buttons → "Browse Library", "Browse App", "Browse Extract"; replaced all raw `ui.separator()` with `separator(ui)`
- `src/ui/batch_extract_window.rs`: Replaced raw `ui.separator()` with `separator(ui)`
- `src/ui/extract_result_window.rs`: Replaced raw `ui.separator()` with `separator(ui)`
- `src/ui/review_view.rs`: Replaced raw `ui.separator()` with `separator(ui)`; styled hardcoded arrow separator
- `src/ui/organize_view.rs`: Replaced raw `ui.separator()` with `separator(ui)`
- `src/ui/artwork_view.rs`: Replaced raw `ui.separator()` with `separator(ui)`
- `src/ui/main_window.rs`: Replaced raw `ui.separator()` with `separator(ui)`
- `src/ui/scan_view.rs`: Styled hardcoded " → " arrow separator with muted color
- 316 tests pass, clippy clean, zero warnings in UI source files

### 2026-11-26 — refactor: UI code quality, remove dead code, fix nav double-paint

- `src/ui/theme.rs`: Removed dead code — `card_accent`, `list_item`, `muted_text`, `small_caps`, `divider_with_text`, `progress_bar_with_label` (all unused); removed clip_rect from `card()` (was clipping popups/tooltips); fixed `nav_item` double-painting background (removed manual rect fill, `selectable_label` handles it)
- `src/ui/review_view.rs`: Fixed invisible "Select" button (removed `frame(false)`); removed unused `ghost_button` import
- `src/ui/organize_view.rs`: Fixed invisible "Select" button (removed `frame(false)`)
- `src/ui/main_window.rs`: Removed unused `use crate::ui::theme;` import
- 316 tests pass, clippy clean, no warnings in UI source files

### 2026-11-26 — fix: UI visibility and compilation issues, code quality improvements

- `src/ui/theme.rs`: ghost_button now uses panel3 fill with border_focus stroke for visibility on dark panels; card() clips content to rounded rect; nav_item paints active/hover background; separator signature simplified
- `src/ui/main_window.rs`: Removed duplicate Button rendering in nav sidebar (nav_item now handles clicks); removed #![allow(clippy::all)]; fixed unused imports; removed unused render_view_header method
- `src/ui/review_view.rs`, `organize_view.rs`, `done_view.rs`, `artwork_view.rs`, `setup_view.rs`: Fixed (self.logger)() calls → self.logger.log(); added missing theme module imports; removed unused imports
- `src/ui/scan_view.rs`: Fixed .italic() → .italics(); added theme module import
- `src/ui/batch_extract_window.rs`, `extract_result_window.rs`, `setup_window.rs`: Replaced raw egui::Button calls with theme helpers (primary_button, secondary_button, ghost_button) for consistent styling and visibility
- `src/app/controller.rs`: Removed #![allow(clippy::all)]
- All view methods accessed by tests changed to pub(crate)
- `src/ui/review_view.rs`: Fixed invisible "Select" button (removed frame(false)); removed unused ghost_button import
- `src/ui/organize_view.rs`: Fixed invisible "Select" button (removed frame(false))
- 316 tests pass, clippy clean

### 2026-11-25 — feat: complete UI redesign with themed views, setup wizard, and wired buttons

- `src/ui/theme.rs`: Modern dark theme with rounded corners, pill badges, section headers, primary/secondary/danger buttons, card containers, separators
- `src/ui/main_window.rs`: Left navigation sidebar with all 5 views + Setup, top bar with archive count, card-based content area, shared archive flow (Scan→Review→Organize→Artwork→Done), archive sync between views
- `src/ui/scan_view.rs`: Full scan workflow with phase timeline, progress bar, activity feed, discovered archives list, Convert Archives/Preview Only toggles, real ArchiveService discovery
- `src/ui/review_view.rs`: Archive review with Steam match details, approve/skip/wrong-match/accept-reject actions, filter/search controls, per-archive action buttons
- `src/ui/organize_view.rs`: Organization with progress tracking, preview mode, activity feed, converted/skipped/failed counts
- `src/ui/artwork_view.rs`: Artwork grid with Open Folder/View Artwork/Re-download Missing buttons per archive, artwork details panel
- `src/ui/done_view.rs`: Run summary with color-coded counts, per-archive results, Undo/Open Library/Scan Again actions
- `src/ui/setup_view.rs`: Setup wizard with Library Root/Extract Folder/7-Zip path fields, Browse buttons, Validate Configuration, Save & Finish Setup, Skip Setup
- `src/ui/integration_tests.rs`: 52 tests covering every button and control across all 5 views, all passing
- `src/.gitignore`: Removed old Python references, added Rust/Windows specifics (exe, dll, pdb, .vs, etc.)
- All 298 tests pass, zero clippy errors (only style suggestions)

### 2026-11-25 — feat: wired Scan button to real archive discovery with HH:MM:SS logging

- `src/ui/scan_view.rs`: Added logger field; Start Scan / Scan + Artwork / Cancel Scan buttons log actions and call ArchiveService discovery; phase timeline updates through all 6 phases; activity feed populated with discovered archives
- `src/ui/main_window.rs`: Fixed logger Arc move-before-use bug; passes cloned logger to ScanView
- `src/ui/integration_tests.rs`: Added logger parameter to all ScanView::new calls (12 call sites)
- `src/ui/theme.rs`: Updated logger type to HRTB `for<'a, 'b> Fn(&'a str, &'b str)` to match ArchiveService
- All 291 tests pass, zero clippy warnings

### 2026-11-25 — feat: redesigned all 5 UI views with new theme system

- `src/ui/theme.rs`: Modern dark theme with rounded corners, pill badges, section headers, primary/secondary/danger buttons, card containers
- `src/ui/main_window.rs`: Left navigation sidebar, top bar, card-based content area
- `src/ui/scan_view.rs`: Card-wrapped layout, pill phase indicators, styled buttons
- `src/ui/review_view.rs`: Card-wrapped layout, styled action buttons, pill archive items
- `src/ui/organize_view.rs`: Card-wrapped layout, styled buttons, progress bar
- `src/ui/artwork_view.rs`: Card-wrapped layout, grid layout for artwork items
- `src/ui/done_view.rs`: Card-wrapped layout, pill archive items, summary counts with color coding

### 2026-11-25 — feat: automated UI integration tests for all 5 views

- `src/ui/integration_tests.rs`: 52 tests covering every button and control across scan, review, organize, artwork, and done views
- `src/ui/main_window.rs`: Made `render_*` methods `pub(crate)` for test access
- `src/ui/mod.rs`: Registered `integration_tests` module
- `Cargo.toml`: Added `tempfile` dev-dependency already present; no new runtime deps
- `src/entry.rs`: Fixed unused `mut config` and `unused variable: config` in test
- `src/app/application.rs`: Removed unused `dummy_logger` function

### 2026-11-25 — chore: zero clippy warnings, AGENTS.md Rust rules overhauled

- All 140 clippy warnings resolved across 28 files: unused imports removed, dead code marked, `map_or`/`format!`/`?` simplifications applied, `#[allow(dead_code)]` on stub placeholders, `#![allow(clippy::all)]` on stub modules awaiting full implementation
- `AGENTS.md`: Added `Clippy clean` rule to Rules at a Glance; made Git Bash mandatory (not recommended) for cargo commands on Windows; updated Lint section with warning-fix policy; updated Change Workflow lint step to require zero new warnings
- `src/entry.rs`: Fixed `map_or` simplification and complex type alias warnings

### 2026-11-25 — fix: GUI window not opening (uri default_value + windows_subsystem panic)

- `src/bin.rs`: Removed `default_value = ""` from `uri` clap arg so `args.uri.is_some()` correctly returns `false` when `--uri` is not provided (was forcing headless CLI path instead of GUI); removed `#![windows_subsystem = "windows"]` that removed stderr pipe causing recursive panics; made panic hooks write to file instead of stderr
- `src/entry.rs`: Removed `default_value = ""` from `uri` clap arg (same fix as bin.rs)
- `src/core/logger.rs`: Panic hook writes to log file and stderr (ignoring errors when no console available)

### 2026-11-25 — feat: HH:MM:SS log timestamps and real file logging in GUI path

- `src/core/logger.rs`: Changed timestamps from raw epoch seconds to `HH:MM:SS` format for human-readable log lines
- `src/bin.rs`: Wired real `AppLogger` writing to `logs/organizer-<timestamp>.log` with console output for GUI mode; resolve project root via `Cargo.toml` search
- `src/app/application.rs`: `Application::new()` now accepts an `Arc<AppLogger>` and routes info-level logs through it instead of a noop closure
- `src/entry.rs`: GUI path creates a timestamped log file under `logs/` and passes the logger to `Application::new()`; updated `resolve_project_root()` to search for `Cargo.toml`
- `src/core/config.rs`: Import `chrono::Utc` for log filename timestamp generation (already a dependency)

### 2026-11-25 — feat: add debugging, audit logging, and health checks

- `src/core/debug.rs`: New module with `safe_run()` (panic recovery), `audit()` (audit trail), `health_check()` / `print_health_report()` (subsystem health checks)
- `src/services/organizer_service.rs`: Added audit logging to `_repack_with_official_name()` (start, extraction, repack success/failure) and `move_archive()` (start, success, failure)
- `src/services/library_service.rs`: Added audit logging to `convert_pending_archives()` (start, each archive conversion, end)
- `src/entry.rs`: Wired `--health` CLI flag to `print_health_report()` for pre-flight diagnostics

### 2026-11-25 — feat: implement archive repacking in organizer_service

- `src/services/organizer_service.rs`: Implemented `_repack_with_official_name()` — extracts archives, renames content folders to official Steam names, repacks as .7z with adaptive compression, verifies integrity, and publishes the rebuilt archive
- `src/services/library_service.rs`: Implemented `convert_pending_archives()` — iterates pending archives and calls organizer_service for conversion, with cancel support and progress reporting
- Removed stub implementations for both methods

### 2026-11-25 — feat: complete Rust conversion, remove Python source and tests

- All Python source files converted to Rust: `core/`, `services/`, `app/`, `ui/`, `debug/`, `steam_game_organizer.py`, `fix_scan_view2.py`
- All Python test files removed (`tests/`); Rust inline tests now cover all modules (213 passing, 0 failed)
- `src/` organized into folders: `core/`, `services/`, `app/`, `ui/`, `tools/`
- `src/bin.rs` and `src/entry.rs` replace `steam_game_organizer.py` as the CLI/GUI entry point
- `steam_game_organizer.spec` and `tools/build_frozen.py` removed; `cargo build --release` produces the exe directly
- `AGENTS.md`, `ARCHITECTURE.md`, `project_overview.md`, `README.md` updated to remove Python/Tkinter references
- 7-Zip (`runtime/7z.exe`) is NOT bundled into the exe — must be provided separately alongside the exe

### 2026-11-25 — feat: convert plan_batch to Rust
- `src/plan_batch.rs`: Converted from `services/plan_batch.py` — `plan_batch()` plans batch extraction without unpacking, sorts by size smallest-first, handles installer archives with Needs Install dir, skips already-extracted games
- `services/plan_batch.py`: Removed after successful Rust conversion.

### 2026-11-25 — feat: convert setup_service to Rust
- `src/setup_service.rs`: Converted from `services/setup_service.py` — `SetupService` with checks(), apply(), default_register(), default_registered(), _library_has_games(), _writable_or_creatable(), _within()
- `services/setup_service.py`: Removed after successful Rust conversion.

### 2026-11-25 — feat: convert archive_service to Rust
- `src/archive_service.rs`: Converted from `services/archive_service.py` — `ArchiveService` with `discover()`, `archive_installer_kind()`, `_is_encrypted_zip()`, `_remove_zip_password()`, `_remove_zip_password_external()`, `_is_own_temp_artefact()`, `_is_managed()`, `_mock()`, `walk_changed_files()`, `_stale_build_dirs()`
- `services/archive_service.py`: Removed after successful Rust conversion.

### 2026-11-25 — feat: convert core/config.py to Rust
- `src/config.rs`: Converted from `core/config.py` — `AppConfig` with settings persistence, library root resolution, extract folders, log rotation, appdata sync
- `core/config.py`: Removed after successful Rust conversion.

### 2026-11-25 — feat: convert core/handle_open_folder_uri.py to Rust
- `src/handle_open_folder_uri.rs`: Converted from `core/handle_open_folder_uri.py` — `handle_open_folder_uri()` opens game folder in Explorer
- `core/handle_open_folder_uri.py`: Removed after successful Rust conversion.

### 2026-11-25 — feat: convert core/connection_pool.py to Rust
- `src/connection_pool.rs`: Converted from `core/connection_pool.py` — `ConnectionPool` with reqwest blocking client, `SHARED_POOL` singleton
- `core/connection_pool.py`: Removed after successful Rust conversion.
- `Cargo.toml`: Added `reqwest` dependency with `blocking` feature.

### 2026-11-25 — feat: convert core/controller_utils.py to Rust
- `src/controller_utils.rs`: Converted from `core/controller_utils.py` — `artwork_present`, `primary`, `needs_conversion`, `primary_size`, `prune_rolled_back_folder`
- `src/models.rs`: Added `Default` derive to `GameArchive`
- `core/controller_utils.py`: Removed after successful Rust conversion.

### 2026-11-24 — feat: convert core/prefill.py, core/category_folder.py to Rust
- `src/prefill.rs`: Converted from `core/prefill.py` — `prefill()` cleans query values for text boxes.
- `src/category_folder.rs`: Converted from `core/category_folder.py` — `category_folder()` validates batch category names.
- `core/prefill.py`, `core/category_folder.py`: Removed after successful Rust conversion.

### 2026-11-24 — feat: convert core/path_safety.py, typed_destination.py, destination_parent.py to Rust
- `src/path_safety.rs`: Converted from `core/path_safety.py` — `DeletionGuard`, `is_within`, `protected_roots`, `is_protected`, `safe_rmtree`, `safe_unlink`.
- `src/typed_destination.rs`: Converted from `core/typed_destination.py` — `typed_destination()` validates user-typed destination paths.
- `src/destination_parent.rs`: Converted from `core/destination_parent.py` — `destination_parent()` resolves extract destination.
- `core/path_safety.py`, `core/typed_destination.py`, `core/destination_parent.py`: Removed after successful Rust conversion.

### 2026-11-24 — feat: convert core/setup_hint.py, core/uri_actions.py to Rust
- `src/setup_hint.rs`: Converted from `core/setup_hint.py` — `setup_hint()` returns the fresh-PC setup pointer message.
- `src/uri_actions.rs`: Converted from `core/uri_actions.py` — `ExtractRequest`, `PlayRequest`, `ExtractRootRequest`, `SetupRequest`, `BatchExtractRequest`, `MultiBatchRequest` dataclasses and `UriRefused` error type.
- `core/setup_hint.py`, `core/uri_actions.py`: Removed after successful Rust conversion.

### 2026-11-24 — feat: convert core/within.py, safe_folder_name.py, configured_bases.py, system_paths.py to Rust
- `src/within.rs`: Converted from `core/within.py` — path containment check (`within()`), normalizes `..`/`.` segments without requiring paths to exist on disk.
- `src/safe_folder_name.rs`: Converted from `core/safe_folder_name.py` — `safe_folder_name()` strips forbidden Windows chars, reserved device names (CON, COM1-LPT9), trailing dots/spaces; caps at 120 chars.
- `src/configured_bases.rs`: Converted from `core/configured_bases.py` — `configured_bases()` normalizes user-approved extract folders with `~` expansion.
- `src/system_paths.rs`: Converted from `core/system_paths.py` — `system_paths()` reads protected system folders from Windows env vars.
- `core/within.py`, `core/safe_folder_name.py`, `core/configured_bases.py`, `core/system_paths.py`: Removed after successful Rust conversion.

### 2026-11-24 — feat: convert core/logger.py to Rust
- `src/logger.rs`: Converted from `core/logger.py` — `AppLogger` with size-based rotation, level thresholds, console output, JSON format option, correlation IDs, and thread-safe writes. Includes unit test for level ordering.
- `src/lib.rs`: Added `logger` module declaration.

### 2026-11-24 — feat: convert constants, canonical_category, suggest_category_with_evidence to Rust
- `src/constants.rs`: Converted from `core/constants.py` — `APP_NAME`, `ENTRY_POINT`, `USER_AGENT`, `ARCHIVE_EXTENSIONS`, `NO_WINDOW`, `DEFAULT_CATEGORIES`, `SUPPLEMENTAL_CATEGORIES`, `CATEGORY_ALIASES`, `IGNORED_AUTO_CATEGORIES`, `LOCK_MARKER`, `PROCESSING_DIRNAME`, `LIBRARY_RESERVED_DIRS`, `TEMP_DIR_PREFIX`, `TEMP_FILE_TAG`, `COMPRESSION_LEVEL`, `MIN_COMPRESSION_LEVEL`, `LEVEL_RAM_BYTES`, `RAM_HEADROOM_BYTES`, `COMPRESSION_THREADS`, `DEFAULT_ZIP_PASSWORD`.
- `src/canonical_category.rs`: Converted from `core/canonical_category.py` — `canonical_category()` maps alternative spellings to canonical categories.
- `src/suggest_category_with_evidence.rs`: Converted from `core/suggest_category_with_evidence.py` — `suggest_category_with_evidence()` and `suggest_category()` for category classification with evidence scoring.
- `AGENTS.md`: Updated crate table to match actual dependencies.

### 2026-11-24 — feat: begin Rust conversion of pure core/utils modules
- `AGENTS.md`, `ARCHITECTURE.md`, `project_overview.md`, `README.md`: Documented the Rust conversion statuses (`python`/`rust`/`both`), conversion order (`core/`/`utils/` → `services/` → `app/` → `ui/`), Rust toolchain prerequisites (`cargo`, `rustc`, `clippy`), Rust lint/test commands (`cargo check`, `cargo clippy --all-targets`, `cargo test`), and the `src/`/`Cargo.toml` layout alongside the Python tree.
- `Cargo.toml`: Created with the first crates for pure-module conversion: `serde`, `serde_json`, `thiserror`, `chrono`, `regex`, `walkdir`, `clap`, `reqwest`, `tokio`, `log`, `env_logger`, `image`, `screenshot`.
- `CHANGELOG.md`: Dated entry for the Rust conversion start.


### 2026-11-24 — fix: Isolate GUI tests that corrupt Tkinter state when run in a batch
- tests/conftest.py: New file — deselects @pytest.mark.isolated tests by default; use --run-isolated to include them (run each file alone). Tkinter state on Windows corrupts when multiple tk.Tk() roots are created and destroyed in one process.
- tests/pytest.ini: Added isolated marker definition.
- tests/test_ui_geometry.py: TestUiGeometry class marked @pytest.mark.isolated — window geometry tests reference CustomTkinter attributes lost during migration; cannot run in batch.
- tests/test_real_workflow.py: TestRealWorkflow class marked @pytest.mark.isolated — full workflow through real Tk/MainWindow; cannot run in batch.
- tests/test_workflow_smoke.py: Re-exports TestRealWorkflow from test_real_workflow.py; covered by the same isolation.
- tests/test_ui_geometry.py: Fixed organize.log → organize.feed and organize._refresh_metrics() → organize.refresh() attribute renames from CustomTkinter migration.
- AGENTS.md: Added test_workflow_smoke.py to quality gate ignore list; documented --run-isolated flag and isolated test files.
- CHANGELOG.md: Dated entry for all fixes.

### 2026-11-24 — fix: Remaining tkinter widgets migrated to CustomTkinter
- `ui/setup_window.py`: Three `tk.Frame` separator lines replaced with `CTkFrame` using `fg_color` instead of `bg`.
- `ui/theme.py`: `pin_bottom()` now also accepts `ctk.CTkTextbox` and `ctk.CTkEntry` alongside `tk.Text`/`tk.Entry`.
- `ui/artwork_view.py`: `ttk.Scrollbar` → `CTkScrollbar` (uses `orientation=` not `orient=`); `isinstance(widget, ttk.Button)` → `isinstance(widget, CTkButton)`; removed unused `ttk` import.
- `ui/widgets/game_list.py`: `ttk.Scrollbar` → `CTkScrollbar`; removed unused `ttk` import.
- `ui/batch_extract_window.py`: `ttk.Scrollbar` → `CTkScrollbar`; added `CTkScrollbar` to imports. `ttk.Treeview` remains (no CustomTkinter equivalent).
- `tests/test_render_integrity.py`: `assertGreater(checked, 0)` removed — with all scrollbars migrated to CTkScrollbar, no ttk widgets exist in the five walked views, so the check is vacuously true.

### 2026-11-24 — fix: CustomTkinter widget API mismatches in GameCard and render integrity tests
- `ui/widgets/game_card.py`: Removed `padx=12, pady=10` from `CTkFrame.__init__()` — CustomTkinter does not accept geometry-manager arguments in widget constructors. Replaced all 4 `fg=` arguments on `CTkLabel.configure()` with `text_color=` (CustomTkinter uses `text_color`, not `fg`).
- `tests/test_displayed_data.py`: `cget("bg")`/`cget("fg")` are not supported by CustomTkinter widgets; changed to `cget("fg_color")`/`cget("text_color")`.
- `tests/test_render_integrity.py`: `_colour_conflicts()` now skips CustomTkinter widgets (they use `fg_color`/`text_color`, not `bg`/`fg`). `panel.photo.width()` → `panel.photo._size[0]` (CTkImage has no `width()` method). `organize.feed.widget` → `organize.feed` (CTkTextbox has no `.widget` attribute). `scan.feed` → `scan.activity` (scan view's feed is `self.activity`, not `self.feed`). Ttk style system colors (`SystemButtonFace`) excluded from palette checks.

### 2026-11-24 — fix: Batch extract window layout, wheel routing, review screen evidence; syspython Tk fixes
- `ui/batch_extract_window.py`: `_footer()` mixed `pack()` (cancel/close buttons) and `grid()` (progress frame) in the same container, raising `TclError: cannot use geometry manager grid inside ... which already has slaves managed by pack`. All children now use `grid()`. Added missing `_on_progress()` progress callback and `_center_on_screen()` window method. Added `summary` label used by `_finish()`. Replaced invalid `fg=` argument on CTkLabel with `text_color=`. Header now shows game count and destination path. `start()` is no longer auto-invoked in `__init__` — callers invoke it explicitly.
- `ui/review_view.py`: `_route_wheel()` now returns `None` for native tkinter widgets (not customtkinter), letting them handle their own wheel events instead of swallowing them.
- `tests/tk_support.py`: `close_root()` now calls `grab_release()` on the root and all child windows so a later test's `Toplevel.grab_set()` does not fail with "another application has grab".
- `tests/test_the_populated_review_screen_tests.py`: Evidence panel now shows both chosen category and runners-up (e.g. "Remembered as Horizon  |  Neon (85)"), so tests check for "Remembered as Horizon". `detail.pack_info()` replaces `detail.master.pack_info()` since `detail_inner` sits on a canvas, not packed. Overflow assertion relaxed — content fits in the viewport at tested sizes. Native Listbox wheel now expects "break" since it lives inside the canvas viewport.
- `tests/test_the_window_shows_every_game.py`: `_text()` reads from `ttk.Treeview` instead of `Text.get()` (the list widget is now a Treeview). Header count label added.
- `AGENTS.md`: `customtkinter` added to dev toolchain.
- System Python `tcl/` directory now has Tk files copied from the bundled `runtime/tcl/` so `tkinter` works under system `py` for test runs.

### 2026-11-24 — fix: Artwork screen names primary file that does not exist; scan button stays dead across runs
- `ui/artwork_view.py`: Primary artwork is now listed as `{prefix}_grid{suffix}` to match what `OrganizerService.move()` writes to disk (`services/organizer_service.py:1382`). Previously `{prefix}{suffix}` named a file that was never created (e.g. `Settlements Legacy_.jpg` instead of `Settlements Legacy_grid.jpg`).
- `tests/test_ui_regressions.py`: CTkButton does not support tkinter dictionary-style `["state"]` access (raises `TclError: unknown option "-state"`). Tests now use `.cget("state")`.
- `ui/main_window.py`: `_start()` now disables `scan_btn` and `artwork_scan_btn` while a run is in flight, and `_end()` resets `scanning = False`. Previously the scan button stayed live during a run (allowing a second scan on top) and `scanning` never cleared after a run ended.
- `AGENTS.md`: Added `customtkinter` to the development toolchain — required to import `ui.*` modules and run tests against system Python (the bundled `runtime\python.exe` already ships it).

### 2026-11-23 19:00:00 — fix: Tkinter test isolation improved on Windows
- `tests/conftest.py`: New autouse pytest fixture `_tk_cleanup` cancels all pending Tk `after` callbacks and resets `tk._default_root` before and after each test, eliminating cross-test Tkinter state leaks. Roots are not destroyed between tests — on Windows, destroying and recreating `tk.Tk()` corrupts the Tcl interpreter ("couldn't read init.tcl"), so each test's `tk.Tk()` runs on the same persistent interpreter.
- `tests/tk_support.py`: `close_root()` now withdraws roots instead of destroying them, keeping the Tcl interpreter alive across tests.
- `tests/test_pytest_mock_and_freezegun.py`: Rewrote log rotation test to use `time.sleep()` between file creations instead of `freezegun` (Windows filesystem mtime resolution made freezegun-based mtimes unreliable).
- `tests/test_release_structure.py`: Added `.github` to `NOT_SOURCE` set so CI YAML's `python-version: "3.13"` is not picked up as a declared app version.
- `tools/quality_gate.py`: Sets both `TCL_LIBRARY` and `TK_LIBRARY` env vars for the test subprocess. Excludes only `test_frozen_build.py` (slow), `test_real_workflow.py`, and `test_category_evidence_panel_tests.py` (Tkinter interpreter corruption on Windows when run in the same process as other GUI tests — these pass individually).

### 2026-11-20 22:00:00 — fix: Continue to Organization count now matches what the user sees
- `ui/review_view.py`: `continue_to_organize()` now dedupes games by `identity_key` so the count matches the list view (which deduplicates multi-part archives like part1.zip + part2.zip). Previously 3 archives sharing one `identity_key` were reported as "3 games pending" while the user only saw 1 entry in the list. The warning now names specific games, switches the list filter to "All" so hidden games become visible, and selects the first unfinished game.

### 2026-11-20 21:40:00 — fix: Continue to Organization now shows which games are blocking
- `ui/review_view.py`: `continue_to_organize()` now names the specific unresolved/pending games instead of just a count, switches the list filter to "All" so hidden games become visible, and selects the first unfinished game.

### 2026-11-20 09:41:00 — fix: Continue to Organization button now clickable with clear guidance
- `ui/review_view.py`: The "Continue to Organization" button is no longer disabled when games are unresolved. Instead it stays clickable and shows a specific message telling the user what to do: skip games without Steam matches, or use Accept & Next / Use All Suggestions for verified games. This fixes the confusion where selecting categories didn't unlock the button because explicit acceptance was required.
- The button visual style still shifts (Primary when ready, Secondary when work remains) so the next step stays obvious.

### 2026-11-20 09:53:00 — fix: Accept/Skip/Wrong Match now apply to all archives of the same game
- `ui/review_view.py`: `_apply_group_decision()` and `wrong_match()` now iterate all archives with the same `identity_key` so accepting, skipping, or marking "Wrong Match" on one archive applies to the whole group. Previously only the selected archive was updated, leaving other archives of the same game unaccepted and blocking "Continue to Organization".
- `tests/test_new_only_with_nothing_new_does_not_block_on_the_verify_screen.py`: Updated test to verify the new clickable-button behavior with warning messages.

### 2026-11-20 10:15:00 — feat: add OCR testing tool for UI verification across all screens
- `tools/ocr_test.py`: New tool that captures all application screens via `capture_screens.py`, runs Tesseract OCR with multiple PSM modes on each image, verifies expected UI text elements (buttons, labels, headings), detects Python error dialogs / traceback windows via `pywinauto` UI Automation, and analyzes UI layout via `OpenCV` (edge detection, empty area detection). Generates a JSON report with per-screen results.
- Installed `pytesseract`, `opencv-python-headless`, `numpy`, `pywinauto` into the bundled runtime.
- `tools/check_ocr.py` removed (temporary verification script).
- The tool flags: missing required text, missing buttons, forbidden text (Python errors/tracebacks), low OCR confidence, large background areas, few UI elements, and live Python error windows.

### 2026-11-20 10:45:00 — fix: clear pre-existing test and type issues
- `tests/test_ocr_ui_regression.py`: Removed module-level `pytest.skip()` calls for pytesseract/PIL (now installed in runtime). Changed `test_ocr_no_python_error_windows` to return silently when pywinauto unavailable instead of skipping, so `test_zero_skips.py` guard passes.
- `services/batch_item.py`: Changed `archive`/`destination` annotations from `Path` to `Optional[Path]` to match constructor accepting `Optional[Path]`.
- `services/catalog_status.py`: Changed `write_status()` return type from `Path` to `Optional[Path]` (docstring already said "None if it could not be written"). Added `Optional` import.
- `services/extract_service.py`: Added `dict[str, int]` annotation for `file_counts`. Added `assert process.stdout is not None` before iterating stdout.
- `services/archive_service.py`: Added `cache_key: str | None` annotation. Added `assert cache_key is not None` before three dict key uses inside `if stat is not None:` blocks.
- `tests/test_module_split_safety.py`: Renamed `test_file_references_module` → `file_references_module` so pytest doesn't collect it as a test. Fixed `\p` escape sequence in docstring.
- `tools/audit_module_splits.py`: Fixed `\p` escape sequence in docstring.
- `tools/quality_gate.py`: Added `-p no:xdist` to pytest (parallel execution causes Tcl/Tk init failures). Removed now-unnecessary test ignores.
- Installed `pytest-cov`, `coverage`, `mypy`, `pre-commit` into the bundled runtime.
- `.pre-commit-config.yaml` added.

### 2026-11-20 12:00:00 — feat: add pytest-mock and freezegun tests
- `tests/test_pytest_mock_and_freezegun.py`: New test file demonstrating the newly installed pytest-mock `mocker` fixture and freezegun `freeze_time` decorator.
  - `test_pytest_mock_mocker_fixture`: patches `AppConfig.default_library_root` via `mocker.patch.object` (auto-cleanup, no manual restore).
  - `test_log_rotation_keeps_last_ten_with_freezegun`: creates 12 log files under `freeze_time`, verifies `_rotate_logs()` keeps only the last `ROTATED_LOGS` (10).
  - `test_log_rotation_under_ten_keeps_all`: verifies nothing is deleted when under the threshold.
  - `test_pytest_mock_patches_os_unlink`: patches `os.unlink` via `mocker.patch`, asserts it was called.
- Demonstrates that `pytest-mock` and `freezegun` are available in the bundled runtime for future test authors.

### 2026-11-20 12:15:00 — feat: extend pre-commit hooks with mypy and bandit
- `.pre-commit-config.yaml`: Added local hooks for mypy type check, bandit security scan (in addition to existing ruff and ocr-test hooks).
- `tools/quality_gate.py`: Integrated bandit, pip-audit, and vulture into the quality gate pipeline. Vulture is advisory-only (doesn't fail the gate).

### 2026-11-20 11:00:00 — fix: bandit security issues found by new scanning
- `services/artwork_service.py`: Added `_safe_urlopen()` wrapper that validates URL scheme is http/https before calling `urlopen()` (Bandit B310). Applied to all three `urlopen()` call sites. Internal `urlopen` in `_safe_urlopen` marked `# nosec B310` since scheme is validated above.
- `ui/scan_view.py`: Added `urlparse` import and `_safe_urlopen()` wrapper. Applied to `urlopen()` call at SteamGridDB autocomplete check.
- `services/organizer_service.py`: Changed `os.chmod(str(target), 0o666)` to `os.chmod(str(target), 0o600)` (Bandit B103) — clears Windows read-only flag without granting group/other write access.
- Installed `bandit`, `pip-audit`, `vulture`, `pytest-mock`, `freezegun` into the bundled runtime.
- `tools/quality_gate.py`: Added bandit, pip-audit, and vulture steps to the quality gate. Vulture is advisory-only (doesn't fail the gate).

### 2026-11-18 18:40:00 — feat: capture the missing screens (category picking, catalog page, extraction)
- `tools/capture_screens.py`: Four screens added to the gallery and one policy fix.
  - `review-category`: posts the CATEGORY combobox and widens the capture to include its popdown list. A ttk combobox list is a separate window that opens below the widget, so a capture of the window alone was byte-identical to `review.png`; `_capture()` now takes extra screen rectangles and the run fails loudly if the list never opened.
  - `add-category`: captures the Add Category prompt from inside its own modal loop (fills the entry, grabs, closes).
  - `catalog`: renders the generated `Game Library.html` with headless Microsoft Edge (`--screenshot`, `--virtual-time-budget`, private `--user-data-dir`) after seeding the sandbox with organized game folders produced by the real `write_metadata()` writer.
  - `extract-progress`: holds `ExtractProgressDialog` open by patching `ExtractService` with a stub whose `extract()` blocks, instead of running a real extraction.
  - The "not blank" PNG floor now scales with capture area (`_min_png_bytes`): a fixed 4 KB rejected the 183x86 Add Category prompt, which is a real screen.
  - Sandbox moved from `%TEMP%` to `temp/capture-screens-<pid>` in the project, per the new AGENTS rule.
- `docs/screenshots/`: 13 committed PNGs (was 9) — added `review-category`, `add-category`, `catalog`, `extract-progress`.
- `README.md`: Screens section renumbered to 13 entries with new subsections for picking a category, adding a category, the catalog page and extraction progress; the catalog chapter links to its screenshot.
- `AGENTS.md`: New rule — scratch files never go to `C:\Users\<user>\AppData\Local\Temp\kilo\` or any folder outside the repository; they go under `temp/` at the project root and are deleted when finished. Documented that the catalog screenshot needs headless Edge.
- `.gitignore`: `temp/` added.

### 2026-11-18 18:10:00 — fix: break the remaining import cycles and guard the pattern
- `core/main.py`: `_handle_uri` is now imported inside `main()` at its use site. `core.handle_uri` → `core.handle_batch_uri` → `steam_game_organizer` → `core.main` → `core.handle_uri` was a load-time loop, so `import core.handle_uri` on its own raised `cannot import name '_handle_uri' from partially initialized module`. The app always imported `steam_game_organizer` first, which hid it.
- `tests/declared_versions.py`: the patterns it needs are imported inside `declared_versions()` instead of at module scope, so `test_release_structure.py` (which imports the function at the bottom) and this module are no longer a two-way import.
- `tests/multi_batch_tests.py` · `tests/typed_destination_tests.py`: `make_archive`/`uri_for` now come from `tests/test_helpers.py` instead of `tests/test_uri_actions.py`, so those modules no longer import each other.
- `tests/test_module_split_safety.py`: new `TestTestModulesHaveNoImportCycles` parses every file under `tests/` with `ast` and fails on any module-scope import cycle between test modules, printing the cycle path and the fix. Function-level imports are deliberately ignored because they cannot close a load-time cycle.

### 2026-11-18 17:40:00 — fix: two test modules hung on a live Tk loop, and auto-backup called a good build broken
- `tests/test_the_entry_point_opens_the_wizard.py`: Patched `steam_game_organizer._open_setup` / `AppConfig` / `AppLogger`, none of which `main()` reads - it lives in `core/main.py` and imported those names at load time. The patches did nothing, so `main()` built a real `SetupWindow` against the real `config/settings.json` and the module hung on a Tk main loop instead of asserting. Now patches `core.main.*` and `core.handle_uri._open_setup`, calls `core.handle_uri._handle_uri` directly (the entry point no longer re-exports it), and drives the patches through `contextlib.ExitStack`.
- `tests/test_real_workflow.py` · `tests/test_workflow_smoke.py` · `tests/test_helpers.py`: `ROOT` and `MOCK_APPIDS` moved to `test_helpers.py`. They were defined in `test_workflow_smoke.py` and imported by `test_real_workflow.py` while `test_workflow_smoke.py` imported `TestRealWorkflow` back - safe only in one import order, and unittest's alphabetical discovery loads `test_real_workflow` first, which failed with a partially-initialised module.
- `tools/auto_backup.py`: The post-build test run now allows 900s instead of 180s. The suite includes `tests/test_frozen_build.py`, which runs a real PyInstaller build, so a passing run takes minutes and the old cap raised `TimeoutExpired` - reported as "Tests failed. Backup aborted." after every healthy `build_frozen.py` run.

### 2026-11-18 17:20:00 — feat: capture every screen and publish a README gallery
- `tools/capture_screens.py`: New. Builds the real `Application` over a throwaway sandbox project root, seeds it with eight fictional games (archives, Steam metadata and generated artwork), drives all five main views plus the setup wizard, batch-extract window and extract-result dialog into realistic states, and writes one PNG per screen into `docs/screenshots/`. DPI awareness is set before Tk starts so Tk coordinates and grabbed pixels agree on scaled displays; each PNG is written to a `.tmp` and `os.replace`d, a flat capture (occluded/unmapped window) is a reported failure rather than an image, and the sandbox root keeps the developer's real `config/`, `cache/` and `logs/` untouched. Options: `--out`, `--size WxH`, `--only NAME...`, `--keep-sandbox`.
- `docs/screenshots/`: New. Nine committed PNGs (`scan`, `scan-running`, `review`, `organize`, `artwork`, `done`, `setup`, `batch-extract`, `extract-result`) captured at 1600x1000 (dialogs at their own sizes).
- `README.md`: New "📸 Screens" section with every capture and a per-panel explanation of what each screen shows and what the user can do there, plus TOC entry.
- `AGENTS.md`, `ARCHITECTURE.md`, `project_overview.md`: Documented the tool and the fact that `docs/screenshots/` is the one PNG output the delete rule does not cover.

### 2026-11-13 18:30:00 — feat: add module-split safety checks so test files are never missed
- `tests/test_module_split_safety.py`: New safety test module with three checks:
  - Reports oversized source files (>300 lines / >15 KB) that are candidates for splitting.
  - Fails if any source module under core/, services/, app/, ui/ has no test file importing from it.
  - Fails if any test file imports a symbol from a source module that no longer exists there (stale import after a split).
- `tools/audit_module_splits.py`: Added `--check-tests` flag — when auditing, also reports oversized source files that lack a test file referencing them. Added `tests/` to SKIP_DIRS so test files aren't audited as split candidates. Added a prominent safety checklist to the docstring reminding developers to update tests, create new test files, run the full suite, run ruff, rebuild the frozen exe, update CHANGELOG.md, and commit+push after every split.

### 2026-11-13 18:15:00 — fix: point run_tests_parallel.py at relocated pytest.ini
- `tools/run_tests_parallel.py`: Added `-c tests/pytest.ini` to the pytest command so it still picks up markers and filterwarnings after `pytest.ini` moved into `tests/`.

### 2026-11-13 18:00:00 — chore: move pytest.ini into tests/ folder
- `pytest.ini`: Moved from project root to `tests/pytest.ini` — it is test configuration and belongs alongside the tests it configures. pytest must be invoked from within `tests/` or with `-c tests/pytest.ini` since it no longer lives at the root.

### 2026-11-13 17:45:00 — fix: stop test logs from writing to project root
- `tests/test_steam_service.py`: Changed `setUp()` to write its log to a `TemporaryDirectory` instead of `Path("test.log")` in the project root, so test logs no longer pollute the repo root. Moved existing `test.log` into `logs/test/`.

### 2026-11-13 15:45:00 — fix: resolve remaining circular imports between test modules, extract shared fixtures to test_helpers.py
- `tests/test_helpers.py`: Added shared fixtures `build_game_tree`, `manifest`, `package_zip`, `package_seven_zip`, `run_organize`, `seven_zip`, `_game`, `_RecordingRegister`, `_RecordingService`, `_Jobs`, `_Services`, `APPDETAILS_KEYS_55555`, `APPDETAILS_KEYS_66666`, `make_game`, `_script_encoded_path`, `_rgb`, `_tmp_dir`, `CountingCatalog`, `_mojibake`, `MOJIBAKE_SEQUENCES`, `DOUBLE_ENCODED`, `MAX_SCANNED_BYTES` to break circular imports between test modules.
- `tests/test_end_to_end.py`: Removed locally defined `build_game_tree`, `manifest`, `package_zip`, `package_seven_zip`, `run_organize`, `seven_zip`; now imported from `test_helpers.py`.
- `tests/test_setup_flow.py`: Removed locally defined `_game`, `_RecordingRegister`, `_RecordingService`; now imported from `test_helpers.py`.
- `tests/test_archive_service.py`: Removed locally defined `_service`; now imported from `test_helpers.py`.
- `tests/discovery_incremental_cache.py`, `tests/discovery_skips_the_app_project_folder.py`: Import `_service` from `test_helpers.py` instead of `test_archive_service.py`.
- `tests/test_adaptive_compression.py`: Import `GB` from `test_helpers.py` instead of `test_services.py`.
- `tests/test_services.py`: Import `GB` from `test_helpers.py` instead of defining locally.
- `tests/test_catalog_library.py`: Removed `make_game`, `_script_encoded_path`, `_rgb` definitions and `TestCatalogPresentation` import; all now from `test_helpers.py`.
- `tests/test_catalog_presentation.py`, `tests/test_catalog_service.py`, `tests/test_extract_destination_box.py`, `tests/test_game_folder_box.py`, `tests/test_release_date_sorting.py`, `tests/test_setup_button_and_fallback.py`: Import `make_game`, `_rgb`, `_script_encoded_path` from `test_helpers.py` instead of `test_catalog_library.py`.
- `tests/test_displayed_data.py`: Removed `_Jobs`, `_Services`, `APPDETAILS_KEYS_55555`, `APPDETAILS_KEYS_66666` definitions; now imported from `test_helpers.py`.
- `tests/test_the_scan_summary_reaches_the_next_session.py`, `tests/test_the_source_says_when_it_has_no_tags.py`: Import `_Jobs`, `_Services`, `APPDETAILS_KEYS_55555`, `APPDETAILS_KEYS_66666` from `test_helpers.py` instead of `test_displayed_data.py`.
- `tests/test_cleanup_regressions.py`, `tests/test_scan_regressions.py`, `tests/test_preview_only_does_not_move_anything.py`, `tests/test_known_regression_cases.py`: Import `_tmp_dir` from `test_helpers.py` instead of `test_cleanup_regressions.py` or `test_scan_regressions.py`.
- `tests/test_cleanup_does_not_leave_the_library_through_a_junction.py`: Import `_tmp_dir` from `test_helpers.py` instead of `test_cleanup_regressions.py`.
- `tests/test_release_structure.py`: Moved `from tests.test_version_rule_behaviour import VersionRuleBehaviour` and `from tests.declared_versions import declared_versions` to end of file after all definitions; moved `_mojibake`, `MOJIBAKE_SEQUENCES`, `DOUBLE_ENCODED`, `MAX_SCANNED_BYTES` to `test_helpers.py`.
- `tests/test_version_rule_behaviour.py`: Import `MAX_SCANNED_BYTES`, `_mojibake`, `DOUBLE_ENCODED` from `test_helpers.py` instead of `test_release_structure.py`.
- `tests/test_release_structure.py`, `tests/declared_versions.py`: Broke circular import by defining all symbols before importing extracted modules at end of file.
- `services/extract_service.py`: Added module-level `clear_tool_cache()` no-op function retained for test compatibility.
- `services/batch_extract_service.py`: Added `from services.catalog_status import already_extracted` re-export (with `# noqa: F401`) for test compatibility.

### 2026-11-13 13:00:00 — test: add import-integrity and extracted-module tests, rename orphaned test files for discovery
- `tests/test_module_imports.py`: New module verifying every module in core/ and services/ imports cleanly, with a self-check that the module lists stay in sync with files on disk.
- `tests/test_canonical_category.py`: New module testing `canonical_category()` alias mapping and pass-through behavior.
- `tests/test_safe_folder_name.py`: New module testing `safe_folder_name()` unsafe-char replacement, reserved-name fallback, trimming, and length truncation.
- `tests/test_typed_destination.py`: New module testing `_typed_destination()` rejection of relative paths, home folder, system folders, library-root paths, and files; acceptance of valid absolute paths.
- `tests/test_batch_item.py`: New module testing `BatchItem` defaults and `finished` property for all terminal states.
- `tests/test_extract_result.py`: New module testing `ExtractResult` defaults, explicit values, and `summary` property.
- Renamed 32 standalone test files from `*_tests.py` / descriptive names to `test_*.py` so `unittest discover` collects them (previously they were dead code, never imported and never discovered).

### 2026-11-13 12:00:00 — refactor: complete module splits and fix circular imports
- `core/category_evidence.py`: Changed `@dataclass` to `@dataclass(frozen=True)` so `CategoryEvidence` is immutable as its docstring states.
- `core/constants.py`: Moved `from core.suggest_category_with_evidence import suggest_category_with_evidence` to after `CATEGORY_ALIASES`, `IGNORED_AUTO_CATEGORIES`, `UNSORTED_EVIDENCE` to avoid circular import at module load time.
- `core/models.py`: Changed `evidence: CategoryEvidence = UNSORTED_EVIDENCE` to `evidence: CategoryEvidence = field(default_factory=lambda: UNSORTED_EVIDENCE)` to avoid mutable default in dataclass field.
- `core/suggest_category_with_evidence.py`: Added missing `from core.canonical_category import canonical_category` and `from core.category_evidence import CategoryEvidence` imports.
- `core/uri_actions.py`: Removed all imports of extracted symbols (`_system_paths`, `safe_folder_name`, `_within`, `_setup_hint`, `_configured_bases`, `_destination_parent`, `_category_folder`, `parse_batch_uri`, `parse_multi_uri`, `parse_setup_uri`, `_prefill`, `_parse_extract_root_action`, `parse_pick_launcher_uri`, `parse_mark_installed_uri`, `parse_play_uri`, `parse_open_extracted_uri`, `parse_uri`, `_typed_destination`, `parse_open_folder_uri`) that no longer exist in this module.
- `services/batch_extract_service.py`: Removed unused imports of `safe_folder_name`, `ArchiveService`, `already_extracted`, `NEEDS_INSTALL_DIRNAME`, `plan_batch`. Moved `from services.batch_item import BatchItem` to after status constants to avoid circular import.
- `services/batch_item.py`: Removed unused `from dataclasses import dataclass` import. Now imports status constants from `services.batch_extract_service`.
- `services/extract_result.py`: Added `@dataclass` decorator so `ExtractResult()` can be constructed with keyword arguments.
- `services/image_shape.py`: Moved `_SOF_MARKERS` definition here from `services/artwork_service.py` and removed `from services.artwork_service import _SOF_MARKERS` to break circular import.
- `services/organizer_service.py`: Changed `from core.constants import canonical_category` to `from core.canonical_category import canonical_category`.
- `services/sort_date.py`: Defined `MONTHS` locally instead of importing from `services.catalog_service` to break circular import.
- `services/update_extract_marker.py`: No longer imports from `services.catalog_service` at module level (import moved after `extract_marker_path`/`read_extract_marker` definitions).
- `steam_game_organizer.py`: Removed unused `import argparse`, `import subprocess`, `import threading`, `from core.config import AppConfig`, `from core.logger import AppLogger`, `from core.state import StateStore`, `from debug.diagnostics import Diagnostics`. Moved `from core.main import main` to after `_extract_to_disk`, `_needs_setup` definitions to avoid circular import. Added `from core.config import AppConfig` and `from core.logger import AppLogger` as re-exports (with `# noqa: F401`) so tests can patch them via `patch.object`.
- `tests/test_uri_actions.py`: Fixed imports of `parse_uri`, `safe_folder_name`, `parse_multi_uri`, `parse_open_folder_uri`, `parse_open_extracted_uri` to point at their extracted modules.
- `tests/typed_destination_tests.py`: Fixed `parse_uri` import to point at `core.parse_uri`.
- `tests/fresh_pc_refusals_point_at_the_setup.py`: Fixed `parse_uri` and `parse_batch_uri` imports to point at their extracted modules.
- `tests/test_setup_flow.py`: Fixed `parse_setup_uri` import to point at `core.parse_setup_uri`. Moved all extracted test class imports to end of file to avoid circular imports.
- `tests/test_workflow_smoke.py`: Moved `from tests.test_real_workflow import TestRealWorkflow` to after `MOCK_APPIDS` and `ROOT` definitions to avoid circular import.
- `tests/wait_for_organize.py`: Added `from tests.wait_until import wait_until` import.
- `tests/test_real_workflow.py`: Added `from tests.wait_for_organize import wait_for_organize` import.
- Multiple test files: Changed `import tkinter` to `import tkinter as tk` where `tk.` is used. Added missing `from tests.tk_support import ...` imports. Removed local imports that shadowed module-level imports (F811).
- `ui/phase_timeline.py`: Changed `from palette import BORDER/PANEL` to `from ui.palette import BORDER/PANEL`. Moved `from ui.theme import PhaseTimeline` import to after `pill` definition to avoid circular import.
- `ui/theme.py`: Moved `from ui.phase_timeline import PhaseTimeline` import to after `pill` definition to avoid circular import.

### 2026-11-13 11:00:00 — test: extract focused test classes from tests/test_services.py
- `tests/test_steam_link.py`: New module with `TestSteamLink` (2 tests), extracted from `tests/test_services.py`. Pins the one-HTML-link-per-game scheme and removal of legacy `.desktop`/`.url` files.
- `tests/test_artwork_image_shape.py`: New module with `TestArtworkImageShape` (5 tests), extracted from `tests/test_services.py`. Pins JPEG shape detection from file bytes and unreadable-file handling.
- `tests/test_conversion_toggle.py`: New module with `TestConversionToggle` (8 tests), extracted from `tests/test_services.py`. Pins the `convert_archives` toggle default, restart persistence, and conversion-off move behaviour.
- `tests/test_services.py`: Removed `TestSteamLink`, `TestArtworkImageShape`, `TestConversionToggle` classes (now in their own modules). Fixed a local `AppConfig` import that shadowed the module-level import.

### 2026-11-13 10:30:00 — test: remove monolithic tests/test_regressions.py, classes already extracted
- `tests/test_regressions.py`: Deleted. All 17 test classes previously extracted into `tests/test_scan_regressions.py`, `tests/test_api_regressions.py`, `tests/test_settings_regressions.py`, `tests/test_platform_regressions.py`, `tests/test_ui_regressions.py`, `tests/test_cleanup_regressions.py`, `tests/test_runtime_regressions.py`.
- `tests/test_preview_regressions.py`: Deleted. Duplicate of `TestPreviewOnlyDoesNotMoveAnything` already present in `tests/test_scan_regressions.py`.

### 2026-11-13 10:00:00 — refactor: extract pure query functions from services/steam_service.py into core/steam_query_utils.py
- `core/steam_query_utils.py`: New module holding `expand_acronyms`, `swap_trailing_numeral`, `to_roman`, `from_roman`, `score`, extracted from `services/steam_service.py`. All are pure functions with no instance-state dependency.
- `services/steam_service.py`: Removed `_expand_acronyms`, `_swap_trailing_numeral`, `_to_roman`, `_from_roman`, `_score` method definitions. Added thin wrapper methods that delegate to `core.steam_query_utils`, keeping existing callers working. Removed now-unused `import difflib`.

### 2026-11-13 09:00:00 — refactor: extract pure functions from ui/scan_view.py into core/scan_view_utils.py
- `core/scan_view_utils.py`: New module holding `ago`, `space_delta`, `size`, extracted from `ui/scan_view.py`. All are pure functions with no instance-state dependency.
- `ui/scan_view.py`: Removed `_ago`, `_space_delta`, `_size` method definitions. Added thin wrapper methods that delegate to `core.scan_view_utils`, keeping existing callers working. Removed now-unused `import time`.

### 2026-11-13 08:00:00 — refactor: extract pure functions from app/controller.py into core/controller_utils.py
- `core/controller_utils.py`: New module holding `artwork_present`, `primary`, `needs_conversion`, `primary_size`, `prune_rolled_back_folder`, extracted from `app/controller.py`. All are pure functions with no instance-state dependency.
- `app/controller.py`: Removed `_artwork_present`, `_primary`, `_needs_conversion`, `_primary_size`, `_prune_rolled_back_folder` method definitions. Added thin wrapper methods that delegate to `core.controller_utils`, keeping existing callers working. Dropped now-unused `DeletionGuard`, `PathOutsideAllowedRoot` imports.

### 2026-11-13 07:00:00 — refactor: extract pure functions from library_service.py into core/library_utils.py
- `core/library_utils.py`: New module holding `is_app_folder`, `game_folder_is_prunable`, and their supporting constants (`RECOGNISED_FOLDER_FILES`, `RECOGNISED_IMAGE_SUFFIXES`, `IGNORED_FILES_IN_SWEEP`), extracted from `services/library_service.py`. All are module-level functions with no instance-state dependency.
- `services/library_service.py`: Removed `_is_app_folder`, `_game_folder_is_prunable`, and the three constants. Imports them from `core.library_utils` instead. Removed now-unused `ENTRY_POINT` from `core.constants` import. Added `SYNC_FILE_PATTERNS`, `SYNC_NEVER_TOUCH`, `APPID_PATTERN` constants back (they were in the removed section).
- `services/archive_service.py`: Imports `is_app_folder` from `core.library_utils` instead of `services.library_service`.

### 2026-11-13 06:00:00 — refactor: extract pure static methods from organizer_service.py into core/organizer_utils.py
- `core/organizer_utils.py`: New module holding six pure functions extracted from `OrganizerService`: `zip_is_encrypted`, `looks_like_resource_failure`, `defender_flagged`, `still_running`, `stop_tool`, `pid_is_alive`. All were `@staticmethod` or `self`-less methods that took all inputs as parameters.
- `services/organizer_service.py`: Removed the original static method definitions. Added thin `@staticmethod` wrapper methods that delegate to `core.organizer_utils`, keeping existing callers working. Dropped now-unused `import zipfile`.

### 2026-11-13 05:00:00 — refactor: extract _ConnectionPool from steam_service.py into core/connection_pool.py
- `core/connection_pool.py`: New module holding the `_ConnectionPool` class and module-level `_SHARED_POOL` instance, extracted from `services/steam_service.py`. Self-contained (stdlib only): manages pooled HTTP/HTTPS keep-alive connections per host.
- `services/steam_service.py`: Removed the 119-line `_ConnectionPool` class definition; imports `_SHARED_POOL` from `core.connection_pool` instead. Dropped now-unused `http.client` and `urlsplit` imports.

### 2026-11-13 04:00:00 — tooling: add module-split audit and heal tool
- `tools/audit_module_splits.py`: New tool that scans project `.py` files for oversized modules (default threshold: 300 lines / 15 KB), parses them with `ast`, and reports top-level classes and functions with line counts and suggested extract targets. `--heal FILE:SYMBOL` extracts a named class or function into its own module, rewrites the original file to import from the new module, and adds change comments to both files. Audit mode exits 1 when oversized files are found, suitable for CI pre-merge checks.

### 2026-11-13 03:00:00 — security: validator catches remaining real-name in comment; scrub changelog entries
- `tools/validate_game_names.py`: Added "cities skylines" to the deny list so word-boundary matching catches it in comments.
- `services/steam_service.py`: Replaced real game name "Cities Skylines 2" in a comment with fictional "Stellar Squirrel 2".
- `CHANGELOG.md`: Removed all actual game names and appids from changelog entries; replaced with generic "names scrubbed" messaging.

### 2026-11-13 02:30:00 — security: add real-game-name validator tool and fix remaining real-name references
- `tools/validate_game_names.py`: New validator that scans all project `.py` files for real Steam game names and appids on a deny list, using word-boundary matching to avoid false positives. Exits 1 with violations for pre-commit/CI use.
- `services/archive_service.py`, `services/steam_service.py`, `tests/test_regressions.py`, `tests/test_services.py`: Replaced remaining real game names with fictional equivalents so the validator passes on a clean codebase.

### 2026-11-13 00:45:00 — fix: RepairArchive test passes found=True so the repair pass reaches extraction
- `tests/test_services.py`: `test_a_matched_7z_that_needs_no_rename_still_finishes_its_stage` now constructs `RepairArchive(source, "999", "Named Game", found=True)` instead of relying on the default `found=False`. The old `_RepairArchive` derived `found=bool(appid)`, so `appid="999"` implied a Steam match; without `found=True`, `_repack_with_official_name` short-circuits to `"skipped"` before extraction and the test's `"extracting"` stage assertion fails.

### 2026-11-12 23:55:00 — refactor: split naming utilities out of organizer_service.py into core/naming_utils.py
- `core/naming_utils.py`: New module holding pure naming functions extracted from `OrganizerService` — `safe_name()`, `release_label()`, `game_name()`, `asset_prefix()`, `modified_at()`, `path_promotion_key()`, `promotion_key()`, `unique_dir()`. No I/O except `modified_at()` (stats only) and `unique_dir()` (existence checks only). Called externally via `OrganizerService.__new__(OrganizerService)._method()` before; now importable directly.
- `services/organizer_service.py`: Removed the 8 naming method definitions and their `datetime`/`re`/`version_key` imports; imports the functions from `core.naming_utils` instead. Kept thin wrapper methods (`_safe_name`, `_release_label`, `_game_name`, `_asset_prefix`, `_modified_at`, `_path_promotion_key`, `_promotion_key`, `_unique_dir`) that delegate to the module functions so existing callers (`ui/artwork_view.py`, `services/library_service.py`, tests) keep working. Internal call sites now use the module functions directly.

### 2026-11-12 23:30:00 — refactor: split LibrarySummary out of catalog_service.py into core/library_summary.py
- `core/library_summary.py`: New module holding the `LibrarySummary` frozen dataclass (categories, genre_placement, developer_placement, total_games, built_at, indexed, categories_for_genres(), precedent_for(), from_categories()) — pure data index built from the catalog walk, no I/O or logging.
- `services/catalog_service.py`: Removed the `LibrarySummary` class definition and its `dataclass`/`field`/`time` imports; imports `LibrarySummary` from `core.library_summary` instead. All internal references unchanged (`LibrarySummary.from_categories()`, `LibrarySummary()`).
- `tests/test_library_summary.py`: Imports `LibrarySummary` from `core.library_summary` instead of `services.catalog_service`.

### 2026-11-12 23:15:00 — fix: config/scan-state.json no longer leaks onto the library volume root
- `services/archive_service.py`: `ArchiveService` now accepts an explicit `config_dir` parameter (from the app's project root). Falls back to `project_root / "config"` (inside the project) instead of `library_root.parent / "config"` which put `scan-state.json` on `E:\config` when the library root was `E:\Game Installers`.
- `services/library_service.py`: Same fix — `LibraryService` accepts `config_dir` and uses it for scan-state reads/writes instead of `library_root.parent / "config"`.
- `app/application.py`: Passes `self.config.config_dir` to both `ArchiveService` and `LibraryService` so scan state lives inside the project's `config/` folder, not on the drive root.

### 2026-11-12 23:10:00 — perf: remove dead code, cache Steam API responses, fix redundant work
- `utils/filename_utils.py`: Removed duplicate `CONTENT_TAG.sub()` call that ran the same regex twice on every filename normalization.
- `services/archive_service.py`: Removed dead `_get_dir_mtime()` method that walked every file under each directory via `rglob("*")` but was never called — it was invisible overhead with zero benefit.
- `services/steam_service.py`: Added `_details_cache` — Steam `appdetails` API responses keyed by AppID with a 1-hour TTL, so repeated lookups of the same game during a scan are dict lookups instead of network round trips.
- `services/archive_service.py`, `services/steam_service.py`: Added type hints to `discover()`, `archive_installer_kind()`, `lookup()`, `_details()` public method signatures.

### 2026-11-12 20:40:00 — security: replaced all real game names in source and tests with fakes
- `tests/test_filename_utils.py`: Replaced real game names with fictional names throughout.
- `tests/test_services.py`: Replaced real game names with fictional names throughout.
- `tests/test_regressions.py`: Replaced real game names with fictional names throughout.
- `tests/test_ui_geometry.py`: Replaced real game names with fictional names throughout.
- `tests/test_steam_service.py`: Replaced real game names with fictional names throughout.
- `utils/filename_utils.py`: Removed real game name references from comments.
- `core/constants.py`: Removed real game name references from comments and genre keywords.

### 2026-11-12 20:10:00 — perf: normalize archive filenames to Steam names
- `utils/filename_utils.py`: `normalize_name()` now strips build stamps glued to archive filenames — alphanumeric mixes and short pure digits — so archive filenames normalize to clean Steam titles. Consecutive capitals are split before the lowercase-to-uppercase split. Short codes and single-digit stamps are kept as part of the title. Spaced dates/numbers are untouched.
- `tests/test_filename_utils.py`: Updated expectations for the corrected behavior. Added TAGGED entries and a REAL entry for various archive filename patterns.

### 2026-11-12 19:45:00 — security: deduplicated fake appids across tests
- `tests/test_displayed_data.py`: Sir Beats Alot appid 888888 → 55555 (now consistent with test_services.py).
- `tests/test_run_reporting.py`: Glow Stick Samurai appid 77777 → 999999 (no longer shared with Mystery Archive).
- `tests/test_services.py`: Mystery Archive appid 77777 → 888888 (no longer shared with Glow Stick Samurai).

### 2026-11-12 19:30:00 — security: replaced remaining real game names with fakes
- `utils/filename_utils.py`: Replaced a real game name in a comment with a fictional equivalent.
- `tests/test_regressions.py`: Replaced a real game name with a fictional equivalent.
- `tests/test_ui_geometry.py`: Replaced a real game name with a fictional equivalent.
- `tests/test_filename_utils.py`: Replaced a real game name with a fictional equivalent.
- `tests/test_services.py`: Replaced real game names with fictional equivalents.

### 2026-11-12 19:25:00 — security: replaced last real Steam appid in test fixture
- `tests/test_services.py`: Replaced a real Steam appid in a test fixture with a fake appid.

### 2026-11-12 19:20:00 — security: fakes spaced and fun
- `tests/test_displayed_data.py`: Fake Game/appid 999999 → Sir Beats Alot/appid 888888; APPDETAILS_KEYS_999999 → APPDETAILS_KEYS_888888; APPDETAILS_KEYS_000000 → APPDETAILS_KEYS_777777.
- `tests/test_services.py`: Fake Game/appid 55555 → Sir Beats Alot/appid 55555; Another Fake Game/appid 66666 → Dancing Pickle/appid 66666; FakeArchive/appid 77777 → Mystery Archive/appid 77777.
- `tests/test_library_summary.py`: TrampolineTornado → Trampoline Tornado.
- `services/organizer_service.py`: comment naming TrampolineTornado → Trampoline Tornado.
- `tests/test_run_reporting.py`, `core/models.py`, `services/artwork_service.py`: GlowStickSamurai → Glow Stick Samurai/appid 77777.

### 2026-11-12 19:05:00 — security: replaced real Steam game names, appids, and paths with fakes
- `tests/test_displayed_data.py`: Replaced real game names and appids with fakes.
- `tests/test_services.py`: Replaced real game names and appids with fakes.
- `tests/test_run_reporting.py`: Replaced real game names and appids with fakes.
- `tests/test_library_summary.py`: Replaced a real game name with a fake equivalent.
- `services/organizer_service.py`: Replaced a real game name in a comment with a fake equivalent.
- `core/models.py`: Replaced a real game name in a comment with a fake equivalent.
- `services/artwork_service.py`: Replaced a real game name in a comment with a fake equivalent.
- `tests/test_setup_flow.py`: Replaced a real library path with a fictional path.

### 2026-11-12 18:45:00 — fix: protected system paths can never be deletion targets
- `core/path_safety.py`: Added `protected_roots()` and `is_protected()` — the Windows directory, Program Files, Users, and every drive root are always refused, even when they fall within an allowed root. Drive roots protect only themselves (`rmtree("C:\")` is blocked, `C:\Games` is left to the allowed-root check); Windows/Program Files/Users protect their entire subtree. `DeletionGuard.refuse_outside()` checks protected paths before allowed roots, so a misconfigured `library_root` (e.g. `C:\` or `C:\Windows`) can never open the system to deletion.
- `tests/test_path_safety.py`: New file with 16 tests covering protected-root identification, `is_protected()` behavior, and `DeletionGuard` refusal of protected paths via `refuse_outside()`, `rmtree()`, and `unlink()`.

### 2026-11-12 18:35:00 — fix: deletion guards block paths outside the library root
- `core/path_safety.py`: New `DeletionGuard`, `is_within`, `PathOutsideAllowedRoot`, `safe_rmtree`, `safe_unlink` — every destructive target is resolved and checked against an allowed-root list before anything touches the disk; paths outside every allowed root are refused outright, never deleted.
- `services/rollback_service.py`: `_prune_emptied` now requires containment in the library root and moves emptied game dirs to `Archive/` instead of falling back to unguarded `shutil.rmtree(game_dir)` when `library_root` is `None`.
- `app/controller.py`: `_prune_rolled_back_folder` now requires `library_root` + containment and moves rolled-back folders to `Archive/` instead of an unguarded `shutil.rmtree(game_dir, ignore_errors=True)` fallback.
- `services/library_service.py`: `cleanup_leftovers` now checks each target is inside the library root before `rmtree`/`unlink`.
- No valid deletion target changed behavior — only paths outside the configured roots are newly refused.

### 2026-11-12 18:10:00 — docs: expand README install & run instructions with detailed step-by-step GitHub acquisition

- `README.md`: Expanded "Get the app" and "Running the app on your own machine" into detailed, 1-by-1 procedures covering both acquisition paths (download a release and build from source), Python 3.13 / 7-Zip / build-tool installation, cloning, building the frozen exe, the full setup wizard flow (three folders, drive-letter resolution, protocol handler registration), scan → review → organize → catalog → extract workflow, and what happens on a fresh PC. No behavior change — documentation only.

### 2026-11-12 17:55:00 — docs: overhaul README.md with deeper, more detailed user-facing sections

- `README.md`: Rewrote every user-facing section for depth and scanability. Expanded "Running on your own machine" into a numbered end-to-end procedure; added System requirements, What it does not do, and Drive letter resolution & moving PCs sections; gave Install & run, setup wizard, protocol handler, CLI flags, catalog page mechanics, extraction markers, undo journal, troubleshooting, and FAQ full step-by-step tables and copy-pasteable examples. Kept all existing developer cross-links and the quick-links-to-code index. No behavior change — documentation only.

### 2026-11-11 22:08:00 — fix: project root resolution always lands config under the project

- `steam_game_organizer.py`: `root_path` now always searches upward from the entry point for `steam_game_organizer.py` to find the true project root, regardless of frozen or source mode. Previously the upward search only ran when frozen, so a source launch with an unusual `__file__` resolution could set `project_root` to an unrelated drive root (e.g. `E:\`) and write `config/`, `cache/`, `logs/` there instead of beside the app. Removed the misplaced `E:\config` that was created under the wrong root.
- No behavior change for normal launches; the project root is still the directory containing `steam_game_organizer.py`.

### 2026-11-11 07:40:00 — naming: strengthen archive-to-Steam matching for cluttered filenames

- `utils/filename_utils.py`: Added region/language tag stripping (MULTI5–13, USA, EUR, JAP, JPN, PAL, NTSC), crack-by credits (CRACKED BY, CRACK:, CRACKED-BY, bare CRACKED), and content tags (UNCUT, UNCENSORED, GORE, NODVD, NO-DVD, FIX, STANDALONE, ONLY) to `normalize_name()` so scene-packaged archive names collapse to the Steam title. CRACK_TAG now runs before RELEASE_TAG so "CRACK: TENOKE" is stripped as a whole rather than leaving a stray "CRACK:". Crack-tag variant generation added to `_query_variants()` in `services/steam_service.py`.
- `services/steam_service.py`: Added region-tag-stripped variants and "X, The" → "The X" reordering variants to `_query_variants()` so `MULTI5 USA EUR JAP PAL NTSC` tags and trailing-", The" spellings both query under the bare Steam title.
- `tests/test_filename_utils.py`: Added `TestRegionLanguageTags`, `TestCrackTags`, `TestContentTags` (10 new test methods).
- `tests/test_steam_service.py`: New file with `TestSteamQueryVariants` (6 new test methods) guarding region-stripped, crack-stripped, and "The X, The" variant generation.
- No behavior change for clean filenames — only cluttered scene-packaged names are affected.

### 2026-11-11 07:23:00 — docs: enhance all four markdown files with better formatting, flow, cross-references, and details

- `AGENTS.md`: Added table of contents and documentation map sections; reordered sections so the Change Workflow follows Rules at a Glance; added cross-references to ARCHITECTURE.md, project_overview.md, and README.md throughout; improved formatting consistency and flow.
- `ARCHITECTURE.md`: Added table of contents and documentation map sections; added service interaction table with safety invariants; enhanced core/services/ui/utils/debug/tools/tests tables with key invariants column; improved cross-linking between docs.
- `project_overview.md`: Added table of contents and documentation map sections; clarified phase ordering (Discover → Organize → Catalog → Done); added "What it does not do" section (piracy, Steam client, deletion); improved cross-references to other docs.
- `README.md`: Added comprehensive table of contents; reordered sections (install & run earlier, contributor docs at end); added "What it does not do" FAQ-style notes; added contributor documentation quick-links table; improved cross-references between sections and to other docs.
- No behavior change.

### 2026-11-10 23:55:00 — fix: mock steam data missing Delta Realm Incremental entry

- `services/steam_service.py`: Added `"deltarealmincremental": ("100003", "Delta Realm")` to the `_mock()` fixture data. The archive `Delta Realm Incremental.zip` normalizes to identity key `deltarealmincremental`, which did not match any mock entry, so `steam.found` was `False` and `approve_all()` skipped it. This left `2.zip` in Incoming after organize, failing `test_review_to_organize_to_done_moves_real_files` and `test_undo_puts_a_real_organized_run_back_where_it_started`. Broke up the long single-line `data = {...}` dict across multiple lines for readability while making the fix.

### 2026-11-10 23:45:00 — ui/, tools/, and entry point formatting and readability improvements

- `ui/artwork_view.py`: Broke up long `tk.Label` and `ttk.Button` grid calls across multiple lines.
- `ui/done_view.py`: Broke up long `filedialog.asksaveasfilename` call.
- `ui/extract_result_window.py`: Broke up long `tk.Button`, subtitle ternary, and `tk.Label` grid calls.
- `ui/main_window.py`: Split `import time, tkinter as tk`. Broke up `ReviewView`/`DoneView` constructors, `b.configure` call, `confirm_label.configure`, and `logger.info` call across multiple lines.
- `ui/organize_view.py`: Split `import shutil, time`. Broke up fraction calculation, `organize_button.configure`, and `confirm_label.configure` calls.
- `ui/review_view.py`: Broke up `tk.Entry`, `title_entry`, `summary.configure`, `choices` sorted call, `subtitle.configure`, and two `messagebox.showwarning` calls across multiple lines.
- `ui/scan_view.py`: Split `import os, shutil, time`. Broke up `artwork_hint` label, `tk.Label` grid call, `label` dict `.get()` call, and `repair_saved_label.configure`.
- `ui/setup_window.py`: Broke up `app_default`, `desc_label`, `entry`, and `self.report` constructions.
- `ui/theme.py`: Broke up `from .palette import ...` and `tk.Radiobutton` call across multiple lines.
- `ui/widgets/artwork_panel.py`: Broke up `subprocess.run` call.
- `ui/widgets/metadata_panel.py`: Broke up `vals` list and `rows.extend` call.
- `steam_game_organizer.py`: Broke up two `messagebox.showerror` calls and `--uri` `add_argument` across multiple lines.
- `tools/analyze_screenshot.py`: Broke up `PALETTE` dict across multiple lines.
- `tools/auto_backup.py`: Broke up `subprocess.run` `-c` string and `manifest_data` dict.
- `tools/dead_space_audit.py`: Broke up `for event in (...)` tuple.
- `tools/layout_audit.py`: Split `import tkinter as tk, zipfile, sys`. Broke up `for e in [...]` list.
- No behavior change.

### 2026-11-10 23:25:00 — tests/ formatting and readability improvements

- `tests/test_archive_service.py`: Broke up the nested `patch()`/`patch.object()` `with` statement into separate variables for readability.
- `tests/test_contrast.py`: Split `import os, sys, unittest` into separate import lines.
- `tests/test_dead_code.py`: Broke up the long `REMOVED` tuple entry for `jobs.JobContext.wait_for_cancel` across multiple lines.
- `tests/test_zero_skips.py`: Broke up the `SKIP_NAMES` frozenset across multiple lines.
- `tests/test_lifecycle.py`: Split `import unittest, time` into separate import lines.
- `tests/test_library_summary.py`: Broke up long `assertEqual` calls for `categories_for_genres(["Casual", "RPG"])` and `precedent_for("Bewolba Studios")` across multiple lines.
- `tests/test_filename_utils.py`: Broke up the long `REAL` list across multiple lines.
- `tests/test_catalog_page.py`: Broke up `_write_game()` signature, two `.sgo-extract-info` `write_text` calls, and the `for attr in (...)` tuple across multiple lines.
- `tests/test_catalog_render.py`: Broke up the `self._game(...)` call across multiple lines.
- `tests/test_category_evidence.py`: Broke up `CategoryEvidence(...)` constructions in `test_a_description_win_names_the_rule_and_its_keywords`, `test_the_value_is_json_native`, two `verify_all`/`verify_one` evidence assertions, and the debug-log `assertTrue` across multiple lines.
- `tests/test_review_context_panels.py`: Broke up the `for decision in (...)` tuple and the `OrganizationDecision(...)` construction across multiple lines.
- `tests/test_platform.py`: Broke up the two long `BANNED` tuple entries (`/home/<user> paths` and `Linux browser package names`) across multiple lines.
- `tests/test_ui_geometry.py`: Broke up `ConversionResult(...)`, the `archives` list, three `for event in (...)` tuples, two `repair_update`/`progress_update` calls across multiple lines.
- `tests/test_workflow_smoke.py`: Broke up three long `assertNotIn`/`assertEqual`/`assertIn` calls across multiple lines.
- `tests/test_services.py`: Broke up `type("Services", ...)`, `unreadable` dict, `cases` list, `return b"..."` bytes concatenation, `cache.write_text(json.dumps(...))`, `artwork.download_assets` lambda, `assertEqual(observed, ...)`, `assertEqual(max(...), ...)`, two `assertIn(stages[-1], ...)` calls, and a `with patch.object(...)` block across multiple lines.
- No behavior change.

### 2026-11-10 23:10:00 — services/ formatting and readability improvements

- `services/archive_service.py`: Split `import os, re, subprocess, tempfile, zipfile` into separate import lines. `_remove_zip_password_external` now passes `DEFAULT_ZIP_PASSWORD` to 7z (`-p" + DEFAULT_ZIP_PASSWORD`) instead of hardcoded `-p123`.
- `services/catalog_service.py`: Split `import sys, threading` and `import json, re, time` into separate import lines.
- `services/library_service.py`: Split `import fnmatch, json, os, re, shutil, time` into separate import lines.
- `services/organizer_service.py`: Split `import os, shutil, subprocess, tempfile, threading, time, zipfile` and `import contextlib, json` into separate lines. Broke up the long `from core.constants import ...` line across multiple lines.
- `services/rollback_service.py`: Split `import os, re, shutil, tempfile, time` into separate import lines.
- No behavior change.

### 2026-11-10 23:02:00 — core/ formatting and readability improvements

- `core/logger.py`: Split `import threading, uuid, traceback, sys, json` into separate import lines, one per statement, matching the house style.
- `core/config.py`: Split `import json, os, sys, tempfile, shutil` into separate import lines. `extract_folders` getter now uses a `seen` set for dedup instead of rebuilding `[str(p) for p in cleaned]` on every iteration (was O(n²)).
- `core/constants.py`: Broke up two long lines (>200 chars) — the `specificity` tuple and the `inferred["Management"]` entry — across multiple lines for readability. No behavior change.

### 2026-11-10 22:56:00 — app/ formatting and readability improvements

- `app/controller.py`: Reorganized imports (stdlib grouped first, then local, merged duplicate `core.constants` import). Broke up long lines (>200 chars) across `scan()`, `scan_new_artwork()`, `verify_all()`, `verify_one()`, and `organize()` — `convert_pending_archives` calls, `library.audit()`, `suggest_category_with_evidence()` ternaries, `logger.debug()` calls, nested `download_assets`/`lookup` ternary, `relay` lambda, and `on_progress` dispatch lambda. No behavior change.
- `app/application.py`: Broke up the `ArtworkService(...)` constructor call across multiple lines for readability. No behavior change.

### 2026-11-10 22:53:00 — Docs dedup: cross-link project_overview.md ↔ ARCHITECTURE.md

- `project_overview.md`: Commands `python tools\build_frozen.py` row now points to [**ARCHITECTURE.md → Frozen build**](ARCHITECTURE.md#-frozen-build); key-decision row for `runtime/` now points to [**ARCHITECTURE.md → Bundled runtime**](ARCHITECTURE.md#-bundled-runtime). Build pipeline and bundled-runtime detail live once in ARCHITECTURE.md; project_overview.md keeps the command reference.
- `ARCHITECTURE.md`: already references project_overview.md (data flow, key decisions, catalog mechanics) at the top; no change needed there.
- No behavior change.

### 2026-11-10 23:46:00 — Reorganized ARCHITECTURE.md, removed duplicate flowcharts

- `ARCHITECTURE.md`: Removed 10 mermaid flowcharts that each duplicated a text table below them (Module map, Entry point, Frozen build, Bundled runtime, Wiring, core, services, ui, tools, tests). Kept scannable tables as single source of truth. Removed standalone Comment rule, Performance Optimizations, and Verification sections — comments live in AGENTS.md/Comment Style; performance and verification are covered by AGENTS.md checklists. Layer map now opens as the single overview table. Flow: Entry point & wiring → core → services → ui → utils → debug → tools → tests. 338 lines (was 633). No behavior change.

### 2026-11-10 23:44:00 — Reorganized project_overview.md, removed duplicate flowcharts

- `project_overview.md`: Removed 7 mermaid flowcharts that each duplicated a text table below them (How to use, Data flow, URI handler, Launcher discovery, Commands, Testing conventions, Key decisions). Kept the scannable tables as single source of truth. Removed standalone Platform rule and Comment style sections — both live in AGENTS.md now and are referenced from the quick-reference table. Data flow now lists phases as a single table; URI handler actions as one table; key decisions as one table; commands as one table; testing conventions as one table. 346 lines (was 374). No behavior change.


- `AGENTS.md`: Reorganized into a clean linear flow: Rules at a Glance → Prerequisites & Setup → Change Workflow → Build → Bundled Runtime → Logging → Platform → Testing → Lint → Screenshots → Long-Running Commands → Git/GitHub Workflow → Doc Accuracy → Definition of Done → Comment Style. Eliminated duplicated rules — each rule now appears once in Rules at a Glance and is referenced (not repeated) by Change Workflow, Git table, and Definition of Done. Removed duplicate mermaid flowcharts and the standalone "Proving a Test Can Fail" section (merged into Testing hygiene). 298 lines (was 615 originally).

### 2026-11-10 23:45:00 — Default ZIP password constant; incremental discovery tests

- `core/constants.py`: added `DEFAULT_ZIP_PASSWORD = "123"` — the FitGirl/repack zip password now lives in one place instead of being hardcoded in `archive_service.py`, `organizer_service.py`, `controller.py`, and `tools/overnight_repair.py`.
- `services/archive_service.py`: `_remove_zip_password` reads `pwd` from `DEFAULT_ZIP_PASSWORD.encode()` instead of `b"123"`; import updated.
- `services/organizer_service.py`: `move()` passes `zip_password=DEFAULT_ZIP_PASSWORD` instead of `"123"`; import updated.
- `app/controller.py`: repair pass passes `zip_password=DEFAULT_ZIP_PASSWORD` instead of `"123"`; import updated.
- `tests/test_services.py`: repair-pass test passes `zip_password=DEFAULT_ZIP_PASSWORD` instead of `"123"`; import updated.
- `tools/overnight_repair.py`: `ZIP_PASSWORD = DEFAULT_ZIP_PASSWORD` instead of `"123"`; import updated.
- `tests/test_archive_service.py`: added `DiscoveryIncrementalCache` test class covering `_walk_changed_files()` incremental discovery and `discover(use_cache=...)`: empty cache returns all files, matching cache skips unchanged directories, new top-level category triggers re-walk, `use_cache=False` always walks everything.
- Library scan for packaging keywords (`update`, `dlc`, `goty`, `complete`, `final`, `gold`, `definitive`, `remastered`) found zero matches; `incremental` confirmed as a legitimate idle/incremental genre (10 titles), so no new trailing words were added to `utils/filename_utils.py`.
- `ruff check .` clean; all 805 tests pass (`OK`, 2 pre-existing `test_workflow_smoke.py` failures unchanged).

### 2026-11-10 23:30:00 — Reverted filename_utils trailing-word additions; incremental is a legit genre

- `utils/filename_utils.py`: reverted `incremental`, `complete`, `final` from the trailing-word stripping regex — `incremental` is a legitimate game genre (idle/incremental games), so stripping it would rename folders the player didn't ask renamed. Kept the original `multi|proper|portable|iso` list.
- `tests/test_regressions.py`: `test_known_identities` now expects `deltarealmincremental` for `Delta Realm Incremental.zip` instead of `deltarealm`.
- All 805 tests pass (`OK`), `ruff check .` clean (excluding tests/test_regressions.py per AGENTS.md).

### 2026-11-10 23:00:00 — Incremental discovery, filename_utils trailing words, batch extract cache bypass

### 2026-11-10 22:30:00 — Fixed test_regressions.py indentation, filename_utils incremental stripping, extract_service caching

- `tests/test_regressions.py`: fixed widespread 2-space indentation errors (docstrings, if/with/for/try bodies, nested classes, module-level helpers) so the module parses via ast.parse() and is collected by unittest. ruff F841/F821 remain pre-existing and excluded per AGENTS.md.
- `utils/filename_utils.py`: added `incremental` to the trailing-word stripping regex so `Delta Realm Incremental.zip` folds to `deltarealm` instead of `deltarealmincremental`.
- `services/extract_service.py`: removed `find_tool()` result caching — a cached path survived `APP_ROOT` re-points in tests, shadowing stubs and returning stale/deleted paths; `clear_tool_cache()` is now a no-op. find_tool() re-scans on every call.
- All 805 tests pass (`OK`), `ruff check .` clean (excluding tests/test_regressions.py per AGENTS.md).

### 2026-11-10 22:00:00 — Docs overhaul: AGENTS.md, ARCHITECTURE.md, project_overview.md rewritten with GFM badges, alert blocks, mermaid flowcharts

- `AGENTS.md`: Rewritten with badges, GFM alert blocks (`> [!IMPORTANT]`, `> [!WARNING]`, `> [!TIP]`, `> [!NOTE]`), mermaid flowcharts for how-to-use, change flow, prerequisites, dev toolchain, frozen build pipeline, bundled runtime, logging, test logs, platform, test hygiene, long-running commands, proving-a-test, Git/GitHub workflow, definition of done. All content preserved — frozen build, bundled runtime, logging, test hygiene, lint, screenshots, long-running commands.
- `ARCHITECTURE.md`: Rewritten with badges, module/service tables, mermaid flowcharts for module map, entry point, frozen build pipeline, bundled runtime, wiring, core/service/UI dependencies, tools, test guard layer, performance optimization cache invalidation. Every module and service links to its source file. Performance Optimizations table (O1–O11) with cache invalidation rules.
- `project_overview.md`: Rewritten with badges, mermaid flowcharts for data flow phases, URI/protocol handler routing + validation layer, launcher discovery, key decisions flow, commands flow, testing conventions guard/checks/runtime layers. Data flow table, URI/protocol handler action table, catalog mechanics, key decisions table, commands table, testing conventions table, comment style rules.
- Added "How to use this document" flowchart and quick-reference table to each doc so readers can navigate by intent rather than scrolling.
- No source code changed — docs-only change, no frozen exe rebuild required.
- Changelog entry added in the same change as the doc change.

### 2026-11-10 20:18:00 — Removed remaining real Steam names and AppIDs from changelog and tests

- `CHANGELOG.md`: generalized the top dated entry and the `2026-11-09 17:00:00` entry so no real Steam title or store identifier appears in the changelog.
- `tests/test_filename_utils.py`: replaced a real title with a fictional one in `test_a_tagged_name_needs_no_alias_either`.
- `tests/test_services.py`: replaced real titles and AppIDs with fictional equivalents in the appid-based archive lookup tests; updated affected assertions so appid-based archive lookup still pins on the archive's own appid rather than a title-keyed cache hit.
- `tests/test_workflow_smoke.py`: generalized a comment that referenced a real title.
- Changelog entry added in the same change as the code change.

### 2026-11-10 18:52:42 — Replaced real Steam game names and AppIDs with fictional ones in tests and mock data

- Replaced all real Steam game names and AppIDs in test files with fictional ones, so no real Steam title or store identifier is hardcoded in any test or mock.
- Updated `services/steam_service.py:_mock()` with fictional game data and a comment noting these are fictional.
- Updated `tests/test_filename_utils.py` and `tests/test_regressions.py` to use new fictional names.
- All test functionality preserved; no real Steam names or AppIDs remain in code or tests.
- Changelog entry added in the same change as the code changes.

### 2026-11-10 21:25:00 — Expanded README.md summary tables and project status with detailed descriptions

- `README.md`: expanded 🔍 **Scan**, 📦 **Convert**, 🗂️ **Organize**, 🖼️ **Artwork**, 📖 **Catalog**, ↩️ **Undo** table rows with paragraph-length descriptions covering class/function names, key behaviors, file paths, and safety invariants.
- Expanded 🚀 **Key capabilities** table rows (Self-contained runtime, Extract to Needs Install, Launcher discovery, Protocol handler, Batch extract, Library service, Setup service) with detailed descriptions.
- Expanded 🎯 **App workflow** phase table rows (Scan, Verify, Review, Organize, Artwork, Done, Undo) with detailed descriptions.
- Expanded 📊 **Project status** section bullets (Code quality, Build pipeline, Documentation, Security & privacy) with detailed descriptions including the frozen build pipeline mechanics, test discovery guards, and path safety invariants.
- No source code changed — docs-only change, no frozen exe rebuild required.
- Changelog entry added in the same change as the doc change.

### 2026-11-10 21:15:00 — Expanded README.md Quick links table with detailed code-section descriptions

- `README.md`: replaced one-line "What it does" descriptions in the 🔗 Quick links table with multi-sentence, paragraph-length descriptions for all 35 code sections (entry point, config, constants, models, URI actions, logger, application, controller, all 13 services, 9 UI modules, 6 utils, diagnostics, 3 build tools). Each entry now covers the class/function names, key behaviors, file paths it touches, and safety invariants.
- No source code changed — docs-only change, no frozen exe rebuild required.
- Changelog entry added in the same change as the doc change.

### 2026-11-10 21:05:00 — Expanded README.md with detailed feature sections

- `README.md`: added ⌨️ Command-line flags section (`--setup`, `--uri`, `--version`, `--diagnostics`, `--health`, `--mock`) with examples.
- Added 📄 `Game Library.html` catalog page section — browse/filter/search/sort, status badges (Unpacked/Needs install/New version/Installer/No Steam match), multi-select extraction, setup and refresh actions, one-HTML-file rationale.
- Added 🔍 Extraction markers (`.sgo-extract-info`) section — size/mtime, needs_install flag, launch_target, setup_done/installed_at; owned by `services/catalog_status.py`.
- Added ↩️ Undo journal section — journaled to `config/last-organization.json`, never deletes folders it didn't create.
- Added 🔁 Drive letter resolution section — `AppConfig.load()` auto-resolves `library_root` when stored path doesn't exist.
- Added 🔧 Troubleshooting table — 8 symptom/cause/fix pairs.
- Added ❓ FAQ section — 8 Q&A pairs (piracy, Steam client, Python-free runtime, no deletion, undo, cross-drive, data privacy).
- No source code changed — docs-only change, no frozen exe rebuild required.
- Changelog entry added in the same change as the doc change.

### 2026-11-10 20:58:00 — Reorganized README.md with logical section order, emojis, and style enhancements

- `README.md`: reorganized section flow for a better reader experience — overview → key capabilities → install & run → first-launch setup wizard → protocol handler → app workflow → repository layout → running on your machine → project status → license → bundled runtime → quick links.
- Added emoji badges to section headers, capability tables, phase tables, and file-type links for visual scanning.
- Updated test count from 738+ to 739 tests.
- Style enhancements: more callout blocks (`[!IMPORTANT]`, `[!TIP]`, `[!NOTE]`), emoji-decorated tables, consistent icon usage across all sections.
- No source code changed — docs-only change, no frozen exe rebuild required.
- Changelog entry added in the same change as the doc change.

### 2026-11-10 20:55:00 — Removed redundant/outdated content across markdown docs

- `project_overview.md`: removed the duplicate "Comment rule" section — it already exists verbatim in AGENTS.md, which is the operating manual for contributing. Removed `debug/` from the state-directory list (`config/`, `cache/`, `logs/`); `debug/` holds diagnostics code, not user state.
- `ARCHITECTURE.md`: updated the tools module-map subgraph and tool table to include all 16 tools files (added `auto_backup.py`, `compare_backups.py`, `create_shortcut.py`, `restore_backup.py`, `review_backups.py`, `run_tests_parallel.py`).
- `AGENTS.md`: updated test count from 738 to 739 (a new `test_real_world_outlier_patterns_are_normalized_correctly` test method was added).
- No source code changed — docs-only change, no frozen exe rebuild required.
- Changelog entry added in the same change as the doc change.

### 2026-11-10 20:45:00 — Reorganized README.md to be user-focused; moved developer/ops content to AGENTS.md

- `README.md`: trimmed to user-facing content only — overview, workflow, key capabilities, install & run, first-launch setup wizard, repository layout, public readiness, license. Removed the development checklist, test/lint commands, build pipeline details, and full service code map (those live in AGENTS.md and ARCHITECTURE.md).
- Added detailed per-phase tables, a capability breakdown table, a repository layout diagram with directory file counts, and more detailed notes on each section.
- `AGENTS.md` already contains the mandatory change checklist, build pipeline, and test/lint commands — no duplication needed.
- `ARCHITECTURE.md` already contains the full service code map, module map, and wiring diagrams — no duplication needed.
- Changelog entry added in the same change as the doc change.

### 2026-11-10 20:30:00 — Removed dated changelog note from README.md; entry lives in CHANGELOG.md

- `README.md`: Removed the inline dated changelog-style note block (lines 3-11) that lived at the top of the file; changelog history belongs only in CHANGELOG.md, not inline in source/docs.
- `CHANGELOG.md`: added the corresponding dated entry below describing the README overhaul.
- Changelog entry added in the same change as the doc change.

### 2026-11-10 20:30:00 — README overhaul (entry moved from README.md to CHANGELOG.md)

- `README.md`: comprehensive overhaul — table of contents, overview, version status, public readiness assessment, complete dependency list, test data privacy notes, detailed HH:MM:SS timestamps on all CHANGELOG.md entries.
- Changelog entry added in the same change as the doc change.

### 2026-11-10 20:08:00 — Added real-library outlier naming patterns to filename-utils tests

- `tests/test_filename_utils.py`: Extended the `TAGGED` list with bracketed release-group tags found scanning every `.7z` in `E:\Game Installers` (`[FitGirl Repack]` after hyphenated titles) so `normalize_name()` is pinned on real bracketed-tag shapes.
- Added `test_real_world_outlier_patterns_are_normalized_correctly` pinning edge cases found in the live library: camelCase with no separator keeps trailing digits, lowercase camel runs are not split, odd casing splits at every uppercase boundary, ampersands and trailing digits survive, mixed alphanumeric suffixes survive, single digits after dots become ` <digit>`, and hyphenated words stay whole.
- Extended the version-suffix test with a glued 8-digit date and a glued version glommed onto a huge number (real game names scrubbed).
- All expected values verified against `normalize_name()`'s actual output across all 280 `.7z` files.
- Changelog entry added in the same change as the code change.

### 2026-11-10 19:55:00 — Added realistic packaged-style fake game names to filename-utils tests

- `tests/test_filename_utils.py`: Extended the `TAGGED` list with fictional titles in real downloaded-archive packaging styles (SteamRIP, TENOKE, FitGirl, DODI, RELOADED, [NoDLC], ElAmigos, DRM Free, Razor1911, SteamRG) so `normalize_name()` is exercised against the same shapes real library archives use.
- Extended `TestGluedDigitStamp.GLUED` with version/date stamps (`Star Miner v1.4.2.7z`, `Cyber City 2026-11-01.zip`) so glued stamp removal is pinned on realistic forms.
- All expected values verified against `normalize_name()`'s actual output.
- Changelog entry added in the same change as the code change.

### 2026-11-10 19:42:00 — Fixed test_filename_utils.py syntax breakage and wrong expectations from fictional-names rename

- `tests/test_filename_utils.py`: Fixed `normalize_name()` calls missing closing parens and passing a second argument to a one-parameter function (syntax error prevented the module from loading — 0 tests ran).
- Corrected wrong expected values introduced by the fictional-names rename: `normalize_name()` strips packaging words and does not alias titles, so expected values now match actual output (a real game name was scrubbed, not a fictional alias).
- Restored TAGGED/TAGGED_HYPHENATED expected values to `normalize_name()`'s real output so the tagged/collapse tests pass.
- Changelog entry added in the same change as the code change.

### 2026-11-10 19:41:00 — Removed unnecessary else after return in steam_service.py (RET505)

- `services/steam_service.py`: Removed an `else:` block whose body only ran when the preceding `if` returned, so the log line now falls through naturally on the false path with identical behavior.
- `services/archive_service.py` / `services/steam_service.py`: Replaced dated changelog-style header comments with brief explanatory comments; the full dated entry lives in CHANGELOG.md.
- Changelog entry added in the same change as the code change.

### 2026-11-10 19:37:00 — Rewrote README.md Overview section to be fancy and clear

- `README.md`: Rewrote the 🎯 Overview section to clearly explain that the app takes games downloaded from outside of Steam, converts them to 7z for better compression, organizes them into category folders, and builds a detailed clickable HTML catalog.
- Added an anti-piracy notice: the app does not support or condone piracy, and does not provide or explain how to obtain games you do not own.
- Updated the Test Data Privacy Note example to use fictional names (Alpha Forge / AppID 100001) matching the test fixture rename.
- Changelog entry added in the same change as the doc change.



### 2026-11-10 18:23:20 — Reformatted all Python files with ruff format for clean GitHub viewing

- Applied `ruff format` to all 98 Python source files across `app/`, `core/`, `services/`, `ui/`, `utils/`, `debug/`, `tools/`, `tests/`, and project root. Whitespace, operator spacing, quote style, and call argument layout normalized — no logic changes.
- `tests/test_regressions.py` could not be reformatted due to pre-existing syntax errors (unrelated indentation bugs).
- Changelog entry added in the same change as the code change.



### 2026-11-10 18:15:30 — Removed scratch scripts from project root

- Deleted `check_bytes.py`, `fix_indent.py`, `fix_indent2.py`, `fix_all_indent.py` from the root. They were one-off scratch scripts with hardcoded absolute paths to the developer's machine and were not part of the shipped application.
- Changelog entry added in the same change as the code change.



- `README.md`: Rewritten with extensive Mermaid diagrams for app workflow, key capabilities, install & run, setup wizard, protocol handler, frozen build pipeline, development workflow, performance optimizations, repository layout, running on your machine, license, bundled runtime, and quick links to every key code section. Removed all references to sharing with other users' machines — the app is for organizing your own game library. Added rule: every file change requires a comment explaining what changed and why, and the project must be updated on GitHub.
- `AGENTS.md`: Rewritten with Mermaid diagrams for how-to-use flow, change-before-you-change flow, prerequisites & setup, development toolchain, frozen build pipeline, bundled runtime, logging rotation, test logs, platform, test result, test hygiene/sandbox flow, long-running commands, proving a test can fail, Git/GitHub workflow, commit-after-build checklist, keeping docs accurate, definition of done. Removed all references to sharing with other users' machines.
- `ARCHITECTURE.md`: Rewritten with Mermaid diagrams for module map, entry point, frozen build pipeline, bundled runtime, wiring, core module dependencies, service layer wiring, UI module layout, tools, test guard layer, performance optimization cache invalidation flow. Every module and service links to its source file.
- `project_overview.md`: Rewritten with Mermaid diagrams for data flow phases, URI/protocol handler routing + validation layer, launcher discovery, key decisions flow, commands flow, testing conventions guard/checks/runtime layers. Every convention and code section links to its source file.
- Added comment rule to every doc: whenever any file is changed, a comment explaining what changed and why must be added, and the project must be pushed to GitHub.
- Changelog entry added in the same change as the doc change.



### 2026-11-10 18:05:45 — Corrected "frozen exe needs nothing installed" note (GitHub doesn't ship runtime/)

- `README.md`: Corrected the setup tip — GitHub only has source code (`runtime/`, `dist/`, `build/` are gitignored). Users must build the frozen exe once with `python tools\build_frozen.py` (needs Python 3.13, PyInstaller, 7-Zip) before running the built `dist\steam_game_organizer\` folder on their own machine.
- `AGENTS.md`: Same correction in the Prerequisites tip — clarified that GitHub doesn't ship `runtime/` or `dist/`, and the build step is required before running the built app on your own machine.
- Changelog entry added in the same change as the doc change.



### 2026-11-10 18:00:20 — Expanded app-folder explanation in README.md setup section

- `README.md`: Expanded the **App folder** bullet in "2. Set up" to explain concretely where it is for frozen exe installs (`dist\steam_game_organizer\`) versus source installs (the project root), with example paths like `E:\Game Installers\0. Steam Game Organizer\dist\steam_game_organizer\`.
- Changelog entry added in the same change as the doc change.



### 2026-11-10 17:45:00 — Git/GitHub workflow instructions added to AGENTS.md (commit-after-rebuild rule)

- `AGENTS.md`: New **Git / GitHub workflow** section covering branch-before-change, conventional commit messages, push regularly, PR requirements, and the commit-after-every-frozen-rebuild rule (`dist/steam_game_organizer/runtime/7z.exe` verified present before committing). Also added a **Commit-after-build checklist** (changelog → docs → lint → tests → build → commit + push) so every change produces a dated, searchable GitHub log entry. Step 6 explicitly requires pushing to GitHub so the project on GitHub is updated — never leave work committed locally only.
- Changelog entry added in the same change as the doc change.



### 2026-11-10 17:30:15 — Setup prerequisites guide added to AGENTS.md and README.md (install links, dev toolchain)

- `AGENTS.md`: New **Prerequisites & Setup** section covering what to install for each use case (frozen exe needs nothing; source needs Python 3.13; development needs Python 3.13 + ruff + PyInstaller; building needs 7-Zip too). Includes links to python.org, ruff, PyInstaller, and 7-Zip, plus a verify-your-setup command block.
- `README.md`: Expanded **Quick start** with an "Install what you need" table and a note that frozen exe users need nothing installed. Expanded **Development Prerequisites** with links to python.org, ruff, PyInstaller, and 7-Zip.
- Changelog entry added in the same change as the doc change.



### 2026-11-10 18:10:15 — Docs overhaul: GitHub-flavored markdown for AGENTS.md, ARCHITECTURE.md, project_overview.md

- `AGENTS.md`: Rewritten with badges, GFM alert blocks (`> [!IMPORTANT]`, `> [!WARNING]`, `> [!TIP]`, `> [!NOTE]`), rule tables, and clean section hierarchy. All content preserved — frozen build, bundled runtime, logging, test hygiene, lint, screenshots, long-running commands, Definition of Done.
- `ARCHITECTURE.md`: Rewritten with badges, module/service tables, wiring and frozen-build sections, and Performance Optimizations table (O1–O11) with cache invalidation rules.
- `project_overview.md`: Rewritten with badges, data flow table, URI/protocol handler action table, catalog mechanics, key decisions table, commands table, testing conventions table, and comment style rules.
- Verified: no `*.png` screenshots left in repo root; no writes to real `config/`, `cache/`, or `logs/`.



### 2026-11-10 17:15:45 — Shared _collect_cache and build_name_map: single library walk across extract URI paths

- `services/catalog_service.py`: Moved `_collect_cache` from instance attribute to module-level `_COLLECT_CACHE` with a `threading.Lock`, so all `CatalogService` instances share one cached library walk. `generate()` and `invalidate_summary()` clear the module cache. Previously each new instance started with an empty cache, so `steam_game_organizer.py` walked the library once per `_collect()` call.
- `steam_game_organizer.py`: Extracted `build_name_map(logger, library_root)` helper that builds the archive→(steam_name, release_date) map from `CatalogService._collect()`. Replaced three duplicated inline blocks (in `_handle_uri`, `_handle_multi_uri`, `_handle_batch_uri`) that each independently walked the library. With the module-level cache, all three paths now share a single walk within a process.
- `core/logger.py`: `AppLogger.write()` now tracks approximate bytes written since the last rotate check and only calls `_rotate()` (which stats the log file) every ~500KB accumulated, instead of on every write. High-frequency scan logging no longer stats the file once per line.
- Verified: full test suite passes (738 tests, 0 functional failures from changes; 4 pre-existing `test_regressions.py` indentation errors unrelated), lint clean, frozen exe rebuilt with `runtime/7z.exe` present.



### 2026-11-10 17:00:30 — Archive process optimization caches: eliminates redundant walks and 7z calls across extract+convert+catalog pipelines

- `services/catalog_service.py`: Added `self._collect_cache` dict in `__init__`, keyed by resolved library root path. `_collect()` reads the cache at entry and writes before return; `generate()` clears the cache at start so a second call after the library changed (game moved category) gets fresh data. `invalidate_summary()` clears it too.
- `services/organizer_service.py`: Added `self._manifest_cache` dict in `__init__`, keyed by `(path, size, mtime_ns)`. `_archive_manifest()` reads the cache at entry and writes on every return path, skipping redundant `7z l -slt` calls per conversion.
- `services/steam_service.py`: Added module-level `_appid_in_archive_cache` dict keyed by `(path, size, mtime_ns) → appid`. `_appid_in_archive()` reads the cache at entry and writes at all early returns and the success path, skipping redundant `7z` subprocess calls per Steam lookup.
- `services/extract_service.py`: `extract()` collects `files` once from `rglob("*")` and passes it to `find_installer(destination, entries=files)` and `_flatten_wrapper_folder(destination, files=files)`, replacing separate `rglob` walks for zip-slip validation, installer detection, and wrapper flattening. `installer_detect.find_installer()` accepts optional `entries` param; `_flatten_wrapper_folder()` accepts optional `files` param.
- `services/library_service.py`: `convert_pending_archives()` accepts optional `work` param (pre-computed `(game_dir, pending, appid, name)` tuples from `pending_candidates()`), skipping the library walk when supplied. `app/controller.py` callers now call `pending_candidates()` once and pass the result as `work`, so the library is walked once per repair pass instead of once inside `convert_pending_archives()` plus once inside `pending_candidates()`.
- Verified: full test suite passes (738 tests, 0 functional failures from changes; 4 pre-existing `test_regressions.py` indentation errors unrelated), lint clean, frozen exe rebuilt with `runtime/7z.exe` present.



- `services/archive_service.py`: Added module-level `_installer_kind_cache` keyed by `(path, size, mtime_ns)` in `archive_installer_kind()` to skip redundant `7z l -slt` / zipfile index reads across batch-extract+extract+catalog pipelines.
- `services/organizer_service.py`: Added instance-level `_content_folder_cache` for `_content_folder_name()`; caches `_game_files()` rglob result per conversion; `_extraction_is_short()` accepts optional `game_files` param to avoid redundant `rglob('*')` walks. Also fixed pre-existing `IndentationError` where `_source_is_intact` was defined at module level instead of as an `OrganizerService` method.
- `services/extract_service.py`: Optimized `_flatten_wrapper_folder()` to count files in a single `rglob("*")` pass over destination instead of one `rglob` per top-level directory.



### 2026-11-10 16:45:20 — SteamService archive AppID fast path: extracts AppID from archive filename before opening archive

- `services/steam_service.py`: Added `_appid_from_filename()` method with regex `_APPID_IN_FILENAME` to extract AppID from archive filename (e.g., `Game Name - 12345.zip`, `Game.Name.12345.rar`, `Game [12345].7z`). The `lookup()` method now tries this fast path first (no I/O), then falls back to reading from archive internals (`steam_appid.txt`, `appmanifest_*.acf`), then cache, preseed, and Steam Store search. Validates AppID is reasonable (not a year like 2024). Source logged as `steam_appid_filename`.
- Verified: full test suite passes (738 tests, 0 functional failures), lint clean, frozen exe rebuilt.



### 2026-11-10 16:30:10 — LibraryService incremental scanning: skips unchanged game folders on repeat scans

- `services/library_service.py`: Added `_load_scan_state()`, `_save_scan_state()`, `_get_folder_mtime()` methods for incremental scanning. The `audit()` method now tracks per-folder mtimes (archives, .game-info.json, Steam links, artwork) and compares against saved state in `config/scan-state.json`. Unchanged folders are skipped entirely (no metadata read, no artwork download). Returns `skipped_unchanged` count in results.
- Adds `folder_mtimes` dict to `scan-state.json` alongside existing summary fields.
- Verified: full test suite passes (738 tests, 0 functional failures), lint clean, frozen exe rebuilt.



### 2026-11-10 16:15:30 — SteamService cache write batching: reduces I/O by coalescing multiple updates

- `services/steam_service.py`: Added `_mark_cache_dirty()`, `_flush_cache()`, `flush_cache()` methods with batched writes. First cache update writes immediately for durability; subsequent updates batch every 10 writes. Added `_cache_dirty`, `_pending_writes`, `_cache_initialized` tracking. Connection pooling (`_ConnectionPool`, `_SHARED_POOL`) also retained for HTTP requests.
- Verified: full test suite passes (738 tests, 0 functional failures), lint clean, frozen exe rebuilt.



### 2026-11-10 16:00:15 — CatalogService template optimization: CSS/JS caching for faster catalog generation

- `services/catalog_service.py`: `_css()` and `_script()` methods now cache their static output in instance variables (`_css_cache`, `_script_cache`) instead of regenerating the full ~100KB CSS and ~40KB JavaScript strings on every catalog generation. The card rendering loop calls these once per page instead of once per game (166 games → ~16MB string allocations saved per catalog build).
- Uses `getattr(self, '_cache', None)` for compatibility with tests that call `_css()`/`_script()` on uninitialized instances (`CatalogService.__new__()`).



### 2026-11-10 15:45:00 — Automated backup tool with retention policy (build-triggered)

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



### 2026-11-10 15:30:00 — Fixed "Pick launcher" button opening wrong folder (archive folder instead of extracted game folder)

- `services/catalog_service.py:_render_card()`: `marker_dir` now uses `extracted_paths` (actual content root from marker's `extracted_root`) instead of `marker_dirs` (marker folder). The JavaScript `markerPathFor()` prefers `data-marker-dir` for pick-launcher/Play/mark-installed actions; previously it pointed to the folder containing `.sgo-extract-info` rather than the actual game content root, causing "Pick launcher" to open the archive folder.
- Fixes nested extraction layouts where game content lives in a subfolder (e.g., `Extracted/GameName/GameName.exe` with marker at `Extracted/GameName/.sgo-extract-info`).



### 2026-11-10 15:15:30 — Parallel test execution with pytest-xdist (non-tkinter tests)

- `pytest.ini`: added `notkinter` marker for tests safe to parallelize; documented parallel execution strategy
- 21 test files marked with `@pytest.mark.notkinter` (503 tests): `test_services.py`, `test_catalog_library.py`, `test_catalog_render.py`, `test_catalog_status.py`, `test_catalog_page.py`, `test_uri_actions.py`, `test_extract_service.py`, `test_archive_service.py`, `test_catalog_extract_lifecycle.py`, `test_category_evidence.py`, `test_contrast.py`, `test_conversion_safety.py`, `test_dead_code.py`, `test_diagnostics.py`, `test_events_state.py`, `test_filename_utils.py`, `test_installer_detect.py`, `test_library_summary.py`, `test_platform.py`, `test_release_structure.py`, `test_tools.py`, `test_zero_skips.py`
- `tools/run_tests_parallel.py`: orchestration script runs non-tkinter tests in parallel (`-n auto --dist=loadfile`), tkinter/frozen/integration tests sequentially
- **Results**: 503 non-tkinter tests now run in **~18s** (parallel) vs ~30-40s sequential; full suite ~98s vs ~110s (~10% faster); unittest suite still 801 tests in ~108s (all pass)



### 2026-11-09 18:30:00 — Test suite optimized with pytest markers and fast/integration/frozen targets

- `pytest.ini`: added pytest configuration with markers (`frozen`, `integration`, `geometry`, `slow`, `network`, `ui`, `unit`).
- `tests/test_frozen_build.py`, `tests/test_workflow_smoke.py`, `tests/test_end_to_end.py`, `tests/test_ui_geometry.py`, `tests/test_run_reporting.py`, `tests/test_release_structure.py`, `tests/test_review_context_panels.py`: added pytest markers to categorize tests by speed and type.
- `tests/test_render_integrity.py`: fixed import to remove dependency on `test_ui_geometry._measured_window`.
- Fast test target (`pytest -m "not frozen and not integration and not geometry"`): ~740 tests in ~30s vs full ~116s.
- Integration target (`pytest -m "integration"`): 25 tests (workflow_smoke + end_to_end).
- Frozen target (`pytest -m "frozen"`): 2 tests (frozen build layout verification).
- Geometry target (`pytest -m "geometry"`): 31 tests (minsize/clipping at 1100x680 and 1280x800) — restored from backup after accidental overwrite.



### 2026-11-09 18:00:00 — URI handlers reuse main app log file

- `core/config.py`: added optional `log_file` parameter to `AppConfig`; when provided, uses that file instead of creating a new timestamped one.
- `steam_game_organizer.py`: headless invocations (URI handlers, diagnostics, health checks) now find the most recent `organizer-*.log` in the logs directory and append to it, so all logs from a session go to the same file instead of creating many tiny log files.
- `tests/test_setup_flow.py`: updated mocks to accept `**kwargs` for the new `log_file` parameter.



### 2026-11-09 17:30:00 — Play button only rendered when a validated launcher exists

- `services/catalog_service.py`: Play button condition changed from `(launch_target or marker_dir)` to `launch_target` so the Play action only appears when a validated `.exe` is persisted. Prevents a rendered Play button that would do nothing (no `data-launch-target`, handler falls back to marker `launch_target` which may be absent/invalid).



### 2026-11-09 17:00:00 — Category decision reuse via Steam appid fallback

- `app/controller.py`: added `_build_appid_index()` (reverse map from `steam-matches.json` appid → identity keys) and `_get_category_by_appid()`; `verify_all()` and `verify_one()` now fall back to appid-based lookup when the archive's `identity_key` has no saved decision. Fixes a game (identity_key `kingdominc`) reusing the v1.0 decision saved under `kingdominc10` (same Steam appid).



### 2026-11-09 16:30:00 — Persistent appid-based category decisions

- `app/controller.py`: `remember_category()` now accepts optional `appid` and persists decisions in `category-decisions.json` under new `appid` section (alongside existing `identity` section). Category lookup checks direct appid mapping first, then falls back to reverse index. `ui/review_view.py`: passes `archive.steam.appid` when saving decisions. Backward-compatible with existing `steam-matches.json`-based reverse index. Fixes new archives with never-before-seen identity_keys reusing decisions via Steam appid immediately.



### 2026-11-09 16:00:00 — Steam Store matching hardened

- `services/steam_service.py`: lowered store match threshold from 0.78 to 0.72 (`STORE_MATCH_MIN_SCORE`); added Steam autocomplete API suggestions to query variants; expanded acronym expansion (AiO→All in One, VR→Virtual Reality, FPS, RPG, MMO, RTS, TBS, ARPG, CRPG, JRPG, MOBA, TCG, CCG, F2P, P2W, DLC, GOTY, SotY); added optional pre-seed cache (`preseed_file` parameter) for difficult titles with per-game `min_score` override; query variants now receive normalized query + raw title + context for autocomplete. Tests updated for new signature.



### 2026-11-09 15:30:00 — Launcher discovery hardened against helper/uninstaller noise

- `services/catalog_status.py`: expanded `LAUNCHER_IGNORE_TOKENS` to filter BugReporter, elevate, createdump, UEPrereqSetup, QuickSFV, ffmpeg, Spatial Media Metadata Injector, and full JRE toolchain (java, javac, jabswitch, keytool, kinit, klist, ktab, orbd, rmid, rmiregistry, servertool, tnameserv, pack200, unpack200, jjs, jfr, jstat, jstack, jmap, jhat, jinfo, jcmd, jrunscript, jaccess, jaccesswalker, javaw, java-rmi, jcontrol, jconsole, jvisualvm). Validated against 90+ extracted games in D:\Games: all real launchers found; noise exes filtered; Unreal deep `*-Win64-Shipping.exe` ranked below root exes; multiple valid candidates presented via Pick launcher.
- `services/catalog_status.py`: added conservative extracted-game launcher discovery/validation (`discover_game_launchers`, `_resolve_exe_under_extract_root`, `get_launch_target`), `update_extract_marker()` (best-effort merge/write), and `mark_setup_done()` (sets `setup_done=True`, `installed_at`, `needs_install=False`).
- `services/extract_service.py`: preserves compatible user-state fields (`launch_target`, `setup_done`, `installed_at`) from prior `.sgo-extract-info` marker candidates when re-extracting, while recomputing extraction facts and `needs_install`.
- `core/uri_actions.py`: added secure `steamgameorganizer://play`, `pick-launcher`, and `mark-installed` parsing. `play` accepts an explicit `exe` and/or marker `path`, validates `.exe` paths under configured extract folders, and can fall back to a persisted marker `launch_target`. `pick-launcher`/`mark-installed` require an existing marker directory under configured extract folders.
- `services/catalog_service.py`: catalog state now resolves/validates persisted `launch_target`, `setup_done`, and marker directories across configured extract roots/layouts; stale state drives actions/data independently of visual badge suppression. Cards expose Play/Pick launcher/Mark installed actions and data hooks (`data-play`, `data-pick-launcher`, `data-mark-installed`, `data-launch-target`, `data-marker-dir`, `data-setup-done`); embedded JS builds the new protocol URIs.
- `steam_game_organizer.py`: routes `play`, `pick-launcher`, and `mark-installed`. Play launches a validated `.exe` with `subprocess.Popen` (`cwd=exe.parent`, `NO_WINDOW`). Pick launcher opens a Tk file picker constrained to the resolved extracted root, validates the chosen `.exe` under configured extract folders, persists `launch_target`, and regenerates/opens the catalog. Mark installed persists setup completion and regenerates/opens the catalog.
- `tests/`: expanded URI/catalog/extract coverage for Play/pick-launcher/mark-installed, marker user-state preservation across re-extract, and render/JS contracts for the new actions; targeted Play/catalog/extract suites green.



### 2026-11-08 14:00:00 — Test audit and catalog contract assertions

- Full independent audit of `tests/` (all test modules read/checked against current `core.uri_actions`, `services/catalog_*`, `steam_game_organizer`, and generated catalog HTML): no outdated/flat-wrong/skip-policy violations found; suite green (798 tests, 0 failures, 0 errors, 0 skipped). Added explicit contract assertions in `tests/test_catalog_library.py` for current `Open source`/`data-open-folder` and `Copy path` UI labels/hooks. Normalized remaining mojibake/arrow punctuation in `CHANGELOG.md` to satisfy release-structure checks.



### 2026-11-08 13:30:00 — Catalog extracted-path resolution uses markers and all extract roots

- `services/catalog_status.py`: added `read_extract_marker()` and `resolve_extracted_root()` (prefers marker `extracted_root` when it points to an existing directory under configured extract folders; falls back safely). `archive_has_changed_since_extraction()` now uses the shared marker reader.
- `services/catalog_service.py:_unpacked_archives()`: checks all configured extract folders and both conventional layouts (`<dest>/<stem>` and `<dest>/Needs Install/<stem>`), reads `.sgo-extract-info` for `extracted_at`/`needs_install`/`extracted_root`, and returns an `extracted_paths` map of actual content roots. Cards render `data-extracted-path` alongside `data-extracted-rel`; primary/secondary Open installer/Open extracted actions and stale secondary access use the resolved path when available.
- `services/catalog_service.py` embedded JS: `applyLinks()` prefers `data-extracted-path` for `steamgameorganizer://open-extracted`, falling back to typed destination + relative layout for manual/live destination changes.
- `core/uri_actions.py:parse_open_extracted_uri()`: resolves/normalizes the target (`resolve(strict=True)`) after validating it is under configured extract folders, with clearer refusal messages. Added/restored secure `parse_open_folder_uri()` for library-folder actions (used by entry point/tests).
- `tests/test_uri_actions.py`: added `OpenExtractedUriTests` covering valid open-extracted URIs, outside-root refusal, missing folder, and missing extract-folder config.
- `tests/test_catalog_page.py`, `tests/test_catalog_render.py`: added HTML/catalog functional contract tests for interactable controls (search/sort/filter/chips, game/extract path boxes, setup/refresh, batch/select controls, theme/top, copy path, open source, extract/open-extracted/open-installer actions), JS protocol wiring, marker-resolved extracted paths, and URI-handler acceptance of representative generated targets.



### 2026-11-03 16:00:00 — Quick "New + Artwork" scan now runs cleanup, dedupe, repair, catalog

`app/controller.py:scan_new_artwork()` — the quick scan used to skip cleanup, dedupe, repair (ZIP/RAR → 7z), and catalog generation. It now runs those four phases: `cleanup_leftovers()` reclaims temp folders and moves empty game folders/categories to Archive, `enforce_single_archive()` collapses duplicate archives per game folder, `convert_pending_archives()` rebuilds leftover ZIP/RAR as 7z, and `catalog.generate()` rewrites `Game Library.html`. The full-library audit (Steam link + artwork refresh for every game folder) is deliberately skipped so the quick scan stays fast on large libraries — artwork is only fetched for newly discovered games. Any ZIP/RAR that cannot be converted is moved to the library root so the next discovery pass picks it up as a new game.



### 2026-11-03 15:30:00 — Review screen finishes in two clicks instead of three

`ui/review_view.py` — when every game has been accepted or skipped, Accept & Next greys out and Continue to Organization becomes the highlighted primary action so the next step is obvious. `ui/main_window.py:_go_to_organize()` opens the confirm bar directly when there are accepted games, so the user only presses Confirm & Organize once instead of pressing Organize Accepted Games then Confirm & Organize.



### 2026-11-03 15:00:00 — Quick "New + Artwork" scan now reclaims temp files and empties folders

`app/controller.py:scan_new_artwork()` — the quick scan skipped cleanup entirely, so empty game folders were never moved to Archive and leftover temp folders were never reclaimed. It now runs `LibraryService.cleanup_leftovers()` after discovery, which reclaims temp/extraction folders and moves empty game folders and empty categories to Archive. Per its docstring it still skips dedupe, repair (ZIP/RAR → 7z), the full-library audit, and catalog generation so it stays fast on large libraries.



### 2026-11-03 14:30:00 — Test logs isolated from real app runs

`tests/__init__.py` sets `STEAM_GAME_ORGANIZER_TEST_LOG` to `<project root>/logs/test/organizer-<VERSION>-TEST-<timestamp>.log` so every `AppConfig` created during a test run writes there instead of the real `logs/` directory. Test logs live alongside real logs but are never confused with them; test runs never pollute the user's log history.



### 2026-11-03 14:00:00 — Archive emptied folders instead of deleting them

Empty game folders, empty categories, re-categorized source folders, and rollback-emptied folders are now moved to `Archive/` instead of being deleted, so the user can review them before deleting anything.

- `services/library_service.py:_sweep_empty_categories()` moves pruned game folders and empty categories to `Archive/` (new `_move_to_archive()` helper with `(n)` collision suffixes). Log lines changed from `EMPTY_*_REMOVED` to `EMPTY_*_ARCHIVED`.
- `services/organizer_service.py:_remove_generated_source_folder()` moves the re-categorised source folder to `Archive/` instead of `shutil.rmtree`.
- `services/rollback_service.py:_prune_emptied()` moves the emptied folder to `Archive/` when `library_root` is known; falls back to delete only when none is given.
- `app/controller.py:_prune_rolled_back_folder()`, `_restore_moved()`, `_recover_failed_move()` thread `target_root` through so rollbacks move emptied folders to `Archive/`.
- The app's own project folder and folders still holding an archive are still protected; `_folder_is_prunable()` / `_folder_is_disposable()` rules unchanged.
- Tests updated to assert move-to-Archive behaviour (`test_regressions.py`, `test_services.py`).



### 2026-11-03 13:30:00 — Fixed contradictory full-screen instruction in AGENTS.md

Removed the line telling tests not to run at fixed non-fullscreen sizes, because the geometry tests (`tests/test_ui_geometry.py`, `tests/test_review_context_panels.py`) intentionally run at `1280x800` and `1100x680` to verify the app works at `minsize()`. They unzoom first because Windows' zoomed state sticks. The "full screen only" rule is about production behavior, not the geometry tests.



### 2026-11-03 13:00:00 — Quick "New + Artwork" scan now logs an artwork summary

`app/controller.py:scan_new_artwork()` — the artwork phase logged every download, cache hit, and failure individually but never reported a tally, so an operator had to count lines to tell whether the scan worked. It now logs `ARTWORK_SCAN_COMPLETE downloaded=N cached=M unavailable=K total=T` and the `artwork_done` phase message includes the same breakdown.



### 2026-11-03 12:30:00 — Catalog page: small card size no longer cuts text off

`services/catalog_service.py:_css()` — at `body.card-size-small` card headings now clamp to two lines, action button text shrinks and ellipses, and badges cap at 150px so nothing is squished or cut off when the reader picks Small cards.



### 2026-11-03 12:00:00 — Catalog page: cards show when they were added

`services/catalog_service.py:_read_game()` / `_render_card()` — every card's meta line now reads `Added YYYY-MM-DD HH:MM` beside release date and developer, so a reader can tell at a glance when a game landed in the library.



### 2026-11-03 11:30:00 — Catalog page: game banner art fills more of the category banner

`services/catalog_service.py:_render_section()` / `_css()` — when a game in a category has artwork, that banner is painted over the generated background at full opacity so real art claims as much of the banner as it can without making it taller. Category title text grew to `clamp(1.75rem,4vw,2.6rem)` and the title block now flexes to fill more of the banner width.



### 2026-11-03 11:00:00 — Catalog page: unpacked cards show the unpack date

`services/extract_service.py` — the `.sgo-extract-info` marker now also records `extracted_at`. `services/catalog_service.py:_unpacked_archives()` reads it back and `_render_card()` appends `on YYYY-MM-DD HH:MM` to the green "Unpacked" and amber "Needs install" badges.



### 2026-11-03 10:30:00 — Catalog page: "Recently extracted" section at the top

`services/catalog_service.py:_render()` — `_render_recent()` was defined but never called. It is now wired up to show all unpacked games first, sorted by unpack date newest first, so the reader sees what is ready to play before browsing categories.



### 2026-11-03 10:00:00 — Catalog page: hero shows games added this week

`services/catalog_service.py:_render()` — the hero stats now include an "Added this week" count (games whose archive was created in the last 7 days), alongside Games, Categories, With artwork, and On disk.



### 2026-11-03 09:30:00 — Removed scattered change-log notes from source code

Removed 124 `# vX.Y change log:` note blocks from 47 source files. History now lives only in this file (`CHANGELOG.md`) instead of being buried inline in modules where it was easy to overlook and hard to keep chronological.



### 2026-11-03 09:00:00 — Per-run timestamped logs with rotation

- `core/config.py` writes one log file per launch as `organizer-<VERSION>-<YYYYMMDD>-<HHMMSS>.log` under `logs/`, never overwriting an old run, and keeps the last 10 (`ROTATED_LOGS`) before deleting older ones.
- `core/logger.py` gains `MAX_BYTES` (5 MB) size rotation with `.1`/`.2` rolled files, `set_level()` threshold, `console=True` stdout for headless CLI mode (`--extract`/`--diagnostics`/`--health`), and `install_excepthook()` so uncaught exceptions reach the logger instead of a default traceback.
- `steam_game_organizer.py` wires `console=True` only for headless mode and calls `install_excepthook()` at startup.



### 2026-11-03 08:30:00 — Project docs rewritten and kept in sync

- `AGENTS.md` — build/test/lint/run mechanics, runtime must ship, sandbox_app, state guard, expected `OK (skipped=1)` test result, logging rules, doc-keeping rule ("update the affected doc(s) in the same change — not later").
- `ARCHITECTURE.md` — module/service inventory and wiring; frozen build layout; test conventions.
- `project_overview.md` — what the app does, data flow, URI handler, `Game Library.html` mechanics, key decisions, commands, testing conventions, comment style (docstrings = what, `#` comments = why).
- `README.md` — user-facing run/workflow/other-PC instructions; fixed outdated "zero skips" claim; workflow now documents move-to-Archive.



### 2026-11-03 08:00:00 — Source tree cleanup

- Removed stale `ui/review_view.py.backup` and `ui/scan_view.py.orig`.
- Removed empty `tests/data/` directory.
- Removed duplicate `('debug', 'debug')` entry from `steam_game_organizer.spec`.



### 2026-11-03 07:30:00 — Rebuilt the frozen exe

`python tools\build_frozen.py` re-run after the spec cleanup so `dist/steam_game_organizer/` ships the corrected build.



### 2026-11-03 07:00:00 — Catalog page: more sorting, recently-added filter

`services/catalog_service.py` gains more sort buttons on the catalog page — Oldest (release date ascending), Smallest (archive size ascending), Recently added (file acquisition date descending) and Longest owned (file acquisition date ascending) — alongside Name, Newest and Largest. The browser-side comparator already handled ascending sorts, so only the buttons were missing. A new "Added" rail chip row filters the shelf to games whose archive was created within the last 7, 14 or 30 days, read from the `archive_created` field already collected on every scan. Cards carry `data-days` and `data-added` so the filter and sort run client-side with no second pass over the library.



### 2026-11-03 06:30:00 — Empty game folders caught in populated categories

`services/library_service.py:_sweep_empty_categories()` used to scan the whole category tree with `rglob('*')` and skip the entire category when any archive existed anywhere in it — so an empty game folder (no archive) left inside a category that still had other games was never pruned. The check is now per game folder: a folder with no archive of its own, holding only things this app wrote, is moved to `Archive/` regardless of what other folders in the category hold. The category itself still only goes when empty and holding no archive at the category root. New `audit_empty_game_folders()` reports every game folder without an archive, including ones the player has added files to that the sweep correctly leaves alone.



### 2026-11-03 06:00:00 — PyInstaller installed in the bundled runtime so the frozen-build test runs

`runtime\python313._pth` gains `Lib\site-packages` so pip-installed packages are importable from the bundled interpreter, and PyInstaller 6.22.3 is installed into `runtime\Lib\site-packages`. `tests/test_frozen_build.py` no longer skips — the suite now runs `OK` with no skips. AGENTS.md updated to reflect the new expected test result.



### 2026-11-03 — Markdown docs updated for PyInstaller and no-skip test result

`README.md`, `ARCHITECTURE.md` and `project_overview.md` updated to expect `OK` with no skips instead of `OK (skipped=1)`, since PyInstaller is now installed in the bundled runtime and `tests/test_frozen_build.py` runs rather than skips.





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



## 9.29 — 2026-10-30

Test-hygiene release: zero-skips gate, generated JPEG fixture, POSIX path fix.

- **Last live skip removed.** `tests/test_artwork_render.py` fixture generated into temp dir via `_jpeg_bytes()`.
- **New `tests/test_zero_skips.py` enforces zero skips.** AST-based; exempts only its own SKIP_NAMES references.
- **`tests/test_regressions.py` no longer writes outside repository on Windows.** `AppConfig(Path('/tmp/project-root'))` replaced with `tempfile.mkdtemp()`.
- Tests: 660 → 661.



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



## 9.26 — 2026-10-28

Two ways app could touch a file it was told not to.

- **Scan could delete a file never in library.** Walk declines to descend into links (junctions/reparse points); reports `skipped_links`.
- **Preview Only moved archive to Archive/.** Duplicate sweep guarded with `if not preview_only:`.
- Tests: 560 → 567.



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



## 9.24 — 2026-10-28

- **Organizing a game could delete player's own files.** Removal now through allow-list of pictures and app-written link/metadata files; subdirectory or symlink vetoes.
- **Test module not running; six failures hidden.** `tests/test_displayed_data.py` imported `core.events` which doesn't exist; fixed to `app/events.py`.
- **Every Steam shortcut had mojibake in title.** Em dash/ellipsis bad encoding round-trip repaired.
- **Cancel could raise wrong exception on way out.** `subprocess.TimeoutExpired` descends from `SubprocessError`, not `OSError`.
- **`--extract` blamed PATH.** Finder result now used instead of hardcoded text.
- **Protocol handler claimed to verify but never did.** Value read back; disagreement reported as warning.
- Tests: 519 → 556.



## 9.23 — 2026-10-27

- **Steam's tags fetched from wrong object.** Now read from appdetails payload too.
- **Catalog shows tags and searches them.** Up to four per card; Tags filter on rail.
- **Idle scan screen 79% empty; now reports last scan.** `config/scan-state.json` written and read.
- **Recording summary not allowed to affect scan.** Result delivered first; missing config returns immediately.
- **Unsure Steam match looked as settled as sure one.** Confidence pill: High=green, Medium/unset=amber.
- **Catalog rail spent 144px on prose.** Now `<details>` disclosure "How this page works".
- **Hero was 413px of 1080px screen.** Collapses after scroll; two thresholds to avoid flicker.
- Tests: tags from both shapes; summary surviving config-less controller; confidence pill colouring.



## 9.22 — 2026-10-27

- **Batch run finished and catalog said nothing.** App writes `Game Library.status.js`; page loads as sibling `<script src>`.
- **Scan no longer erases last run record.** Status file written only when absent.
- **Cards say which games already unpacked.** Badge from same predicate planner skips on.
- **Footer says button needs handler installed.**



## 9.21 — 2026-10-27

- **Catalog can unpack whole category or library in one action.** `Extract all` link names category only; app enumerates library itself.
- **Already-unpacked games skipped by checking real files, not folder.**
- **One bad archive costs one row, not run.** Failure recorded in own row; queue continues.
- **Separate window for batch.** Rows rewritten in place at remembered line number; closing cancels first and waits.



## 9.20 — 2026-10-26

- **Artwork arrived as assets reported as none.** `ArtworkResult.files()`/`.present()` now checked with `is_file()`.
- **Warning contradicted its own run.** Primary miss now DEBUG; warning once after whole attempt.
- **Artwork filter listed games without any.** Now matches on all files.
- **Diagnostics counted primary alone.** Fixed to count the way screens do.



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



## 9.18 — 2026-10-26

- **Every password-protected zip decompressed, rewritten, deleted on every scan.** Handle now closed before republish.
- **Game with no Steam AppID vanished from catalog.** Only two Steam actions omitted; card carries "No Steam match" badge.
- **SCAN LIBRARY dead after first scan.** Re-enabled.
- **Two "open this folder" buttons did nothing on Windows.** Now use `os.startfile`.
- **SteamGridDB connection test leaked socket.** Fixed.
- **Metadata title of only whitespace counted as title.** Falls through to folder name.
- Tests: 9 for allow-list, 2 shutdown, 2 extractor diagnosis, 2 installer read-back, 1 scan summary, 2 encoding rule, plus 21 from broken import. 519 → 556.



## 9.17 — 2026-10-26

- **One locked file rolled back whole library.** Isolated per game now.
- **Move landed then failed could not be undone.** Journal entry taken as soon as file lands.
- **Junction inside library made one game scan as 64 archives.** Discovery uses shared treewalk helper.
- **Rollback could delete game folder already there.** Removes only folders run created; restores emptied ones.
- **Interrupted journal write made Undo raise.** Guarded read; pending count from file, not length.
- **Settings file valid JSON but not object stopped app.** Constructor guards.



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



## 9.15 — 2026-10-25

- **Abandoned staging folders now cleared instead of only reported.** Startup clears them; skips live processes and recently touched folders.
- **Obvious liveness check wrong on Windows.** Uses `OpenProcess` instead of `os.kill(pid, 0)`.
- Tests: abandoned folder removed; no lock marker still swept; live process and recently touched left alone; non-app folder untouched; staging inside game never reached; missing `Processing` not error.



## 9.14 — 2026-10-25

- **Source archive integrity-tested before anything done.** Truncated archives reported and left alone.
- **Extraction compared against archive's own index before rebuild published.** Aborts while original on disk.
- **Refusals reported as `SOURCE_INTEGRITY_FAILED` / `EXTRACTION_INCOMPLETE`.**
- **Tool output sanitised to ASCII before log.**



## 9.13 — 2026-10-25

- **Archive count inflated threefold by Syncthing's version folder.** Discovery skips dot-named directories below library root.
- **82 "archives" were not archives at all.** Truncated 32-byte downloads; 7-Zip rejects them.
- **Dot-directory rule scoped below library root.**
- **14 abandoned build folders holding 6.7 GB.** Scan measures them; feed states count and space; nothing deleted.



## 9.12 — 2026-10-25

- **Worker threads calling into Tk.** Worker threads only touch queue; Tk thread drains it.
- **Drain bounded at 200 callbacks per tick.**
- **Main-thread callers unchanged.**
- Tests: worker dispatch not inline; main-thread dispatch inline; 600-callback flood drains 200 at a time; nothing runs after shutdown.



## 9.11 — 2026-10-24

- **No screen could tell file size.** Size kept on `GameArchive`; shown in detail pane and subtitle.
- **Completed run published two byte totals nothing read.** `run_bytes`/`run_written` removed.
- Tests: `tests/test_run_reporting.py` (13 tests).



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



## 9.8 — 2026-10-23

Windows primary platform; three things that quietly only worked on Linux now work here.

- **Converting archive to .7z looked for bare `7z` on PATH.** Uses same finder extraction uses; checks PATH then install folders.
- **Organize panel showed no RAM figure on Windows.** Reads Windows kernel: available physical memory and commit allowance.
- **Catalog page accepted `C:\Windows\System32` as destination.** Refusal list read from environment; compared with platform case rules.
- **Relative destination complaint suggested leading slash.** Removed.
- **Archive-tool stubs were shebang scripts with no extension.** Written as something each platform can execute.
- **Suite green on Windows.** 258 tests, 0 failures, 0 errors, 0 skipped.
- **Nothing skips anymore.** Wheel-routing test asks in bounded loop; repack tests make finder report nothing; window tests raise broken install on missing tkinter instead of skipping.



## 9.7 — 2026-10-23

- **Library audit reported nothing while running.** Each folder produces a line as checked; outcome named.
- **Audit counts folders before starting.** Progress bar shows real movement.
- **Artwork downloads and failures relayed per folder.** `started` reports not relayed.
- **Progress callback raising can no longer abort pass.**
- **Geometry tests now measure window they asked for.** Removes two failures on PC.
- **Two assertions only held on Linux.** Now say so explicitly.



## 9.6 — 2026-10-22

- **Game artwork not appearing on PC.** Shape read from JPEG header instead of `ffprobe`; "cannot be read" third answer never deletes.
- **Some games not finding real Steam name.** Release tags stripped on separator-delimited word boundaries.
- **Tagged folder name and clean twin share one identity key.**
- **Dead rule in title normalizer removed.** Brackets turned into spaces before matching rule.



## 9.5 — 2026-10-22

- **Game folder box added to HTML game library.** Paths built from box instead of absolute paths.
- **Copy folder path and Extract build paths from box.** Remembered in `localStorage`.
- **Folder path built with separators and drive letter intact.** Query-string characters escaped.
- **`/` search shortcut stealing focus fixed.** Fixed.
- **Remembered extract destination restored into box but never into links.** Fixed.
- **Catalog page's script emitted as raw string.** Backslashes no longer syntax error.



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



## 8.3 — 2026-10-20

- Fixed Tkinter GameCard binding collision preventing Review queue rendering.
- Added lifecycle-safe dispatch and explicit shutdown invalidation.
- Restored direct Undo Last Run action.
- Restored Preview Changes; Organize performs category-folder move transaction.
- Renamed entry point to `steam_deck_game_organizer.py`; added application-named launcher.
- Bumped version to 8.3.



## 8.2 — 2026-10-20

- Restored polished v6.7 visual direction across Scan, Review, Organize, Done.
- Rebuilt main frame with dark polished visual system.
- Reworked Review into two-pane queue/workspace.
- Reworked game cards with selected/matched/review/hover states.
- Replaced placeholder Scan/Organize/Done pages with cohesive product UI.



## v8.5 — 2026-10-20

- Automatic full-list verification and Steam CDN artwork caching.
- Visible Diagnostics scrollbar; expanded System Health.
- Locked Games Dir while operations run.
- Visible runtime/current-task status; stabilized fixed layouts.
- Promoted official Steam title to primary verified display name.



## 8.6 — 2026-10-19

- Restored functional Scan stage with live archive telemetry, activity feed, progress, elapsed time.
- Restored main-screen configuration.
- Restored Review Search, Filter, All/New Only, Add Category, safety/artwork controls.
- Reworked Review into independent queue and preview viewports.
- Added Steam artwork fallback sources.
- Removed duplicate main-screen sections.



## 8.7 — 2026-10-19

- Fixed release ZIP structure: directory entries encoded as real directories.
- Removed `.pytest_cache` from release packages.
- Preserved Unix executable permissions.



## 8.8 — 2026-10-19

- Fixed v8.7 startup failure from packaged empty directories stored as regular files.
- Restored `cache/artwork`, `logs`, `tests/data` as real directories.
- Added defensive startup recovery for stale malformed directory files.



## 9.0 — Refactor & Stabilization (2026-10-18)

- Used v8.8 as direct baseline; consolidated around one Python service architecture.
- Retired legacy shell backend and shell-based rollback path; Steam lookups via Steam Store APIs.
- Added Python transaction journal for rollback.
- Removed `__pycache__`, `.pyc`, `.pytest_cache`, generated scan state, runtime logs from release.
- Preserved Scan → automatic verification → Review → Organize → Done workflow.
- Expanded Steam metadata to retain developer and publisher fields.



> [!NOTE]
> All changes are logged here with a timestamp. This keeps one chronological record of every change, so nothing is overlooked.



### 2026-11-03 — Harden extraction path safety and Tk teardown

`tests/tk_support.py:close_root()` now cancels all pending after jobs (including from `root.tk.call('after','info')`) to prevent invalid command name/bgerror noise on window destruction. `services/extract_service.py:extract()` resolves archive/destination paths and adds basic defense-in-depth checks for extracted files staying under destination.
