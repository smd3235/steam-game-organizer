# project_overview.md — Steam Game Organizer

[![Steam Game Organizer](https://img.shields.io/badge/Steam%20Game%20Organizer-blue.svg)](CHANGELOG.md)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-green.svg)](README.md)
[![Language: Rust](https://img.shields.io/badge/language-Rust-orange.svg)](https://www.rust-lang.org/)
[![Lint: cargo clippy](https://img.shields.io/badge/lint-cargo%20clippy-important.svg)](Cargo.toml)
[![Tests: cargo test](https://img.shields.io/badge/tests-cargo%20test-success.svg)](src/)

---

## 📖 Table of contents

| If you want to… | Go to section |
|-----------------|---------------|
| Read this doc first (start here) | [📖 How to use this document](#-how-to-use-this-document) |
| Understand what the app does | [🎯 What it does](#-what-it-does) |
| Trace a run through six phases | [🔄 Data flow](#-data-flow) |
| See which decisions are locked | [🔒 Key decisions already made](#-key-decisions-already-made) |
| Understand the catalog page mechanics | [🖼️ Game Library.html — catalog page mechanics](#-game-libraryhtml---catalog-page-mechanics) |
| Understand URI / protocol handler | [🔌 URI / protocol handler](#-uri-protocol-handler) |
| Run tests / lint / build | [🖥️ Commands](#-commands) |
| Read the testing rules | [🧪 Testing conventions](#-testing-conventions) |
| Module inventory + service wiring | [🏗️ ARCHITECTURE.md](ARCHITECTURE.md) |
| Platform and comment rules | [📋 AGENTS.md](AGENTS.md) (Windows only, comment style) |
| User-facing install / run / workflow | [📘 README.md](README.md) |

---

## 🗂️ Documentation map

This file is one of four project docs. If a reader acts on any of them, they must match the code — update all four together when behavior changes.

| File | Purpose | Link |
|------|---------|------|
| **AGENTS.md** | Operating manual: how to build, test, lint, run, commit, and push on Windows | [`AGENTS.md`](AGENTS.md) |
| **ARCHITECTURE.md** | Module map and service inventory: what each module does and how they wire together | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| **project_overview.md** | What the app does, its data flow, key decisions, catalog page mechanics | [`project_overview.md`](project_overview.md) |
| **README.md** | User-facing install, run, workflow, other-PC, and development-check instructions | [`README.md`](README.md) |
| **CHANGELOG.md** | Dated change log (newest first) | [`CHANGELOG.md`](CHANGELOG.md) |

**Rule:** when a change alters behavior, architecture, commands, test counts, or build layout, update the affected doc(s) in the same change — not later. See [📐 Keeping Project Docs Accurate](#-keeping-project-docs-accurate) in [`AGENTS.md`](AGENTS.md).

---

## 🦀 Rust Conversion (complete)

This project has been converted from Python to Rust, **one file at a time**, tracked on the `Rust-Conversion` branch. All source code is now in Rust under `src/`.

| Status | Meaning |
|--------|---------|
| `rust` | File is a `.rs` module in `src/` |

Rust source lives in `src/` alongside this doc. `Cargo.toml` is at the project root. `cargo build --release` produces a self-contained `.exe` at `target/release/steam-game-organizer.exe`.

---

## 📖 How to use this document

This file describes what the app does, how a run flows through its six phases, how the catalog page works, which design decisions are locked, and what commands/testing conventions apply. It is reference material — jump to a section by intent.

---

## 🎯 What it does

Scans a user's game library (a folder full of `.zip/.rar/.7z` archives organized into category folders), matches each archive against Steam's store API, files the archive into the right category alongside Steam links, metadata, and artwork, generates a clickable HTML catalog, and offers Undo for the whole run.

> [!IMPORTANT]
> The app runs full-screen on Windows only, from a self-contained Rust exe. A "library" is a folder the user points the app at; the app itself lives in a project root beside it and writes its own state under `config/`, `cache/`, `logs/`. The app name (`USER_AGENT`) identifies itself to Steam's Store API on every request.

### What it does not do

- **Does not support piracy.** The app does not support or condone piracy. Use it only for games you own and have the right to organize. It does not provide — and does not explain — how to obtain games you do not own.
- **Does not need Steam installed.** It queries the Steam Store API at runtime for metadata — no Steam client required.
- **Does not delete games.** The app never deletes anything it didn't create. Empty categories and re-categorized leftovers are moved to `Archive/` for review.

---

## 🔄 Data flow

A run walks the library through six phases:

| Phase | What happens | Code |
|-------|--------------|------|
| **1. Discover** | `services/library_service.rs` walks category folders under the library root, skips anything without an archive, skips the app's own project folder, reads `.game-info.json` sidecars, records banner art and installer signature per game. | [`src/services/library_service.rs`](src/services/library_service.rs) |
| **2. Organize** | `app/controller.rs` / `services/organizer_service.rs` groups archives by identity key, promotes the newest version, archives older copies and re-categorized leftovers to `Archive/`, repacks `.zip/.rar` → `.7z` (adaptive compression level against real memory headroom), writes metadata + Steam shortcut + artwork into each game folder. | [`src/services/organizer_service.rs`](src/services/organizer_service.rs) — [`src/app/controller.rs`](src/app/controller.rs) |
| **3. Catalog** | `services/catalog_service.rs` writes `Game Library.html` plus `Game Library.status.js` beside the library root; retains a `LibrarySummary` index (categories, genres, developers, archive sizes) so screens can ask placement questions without re-walking. | [`src/services/catalog_service.rs`](src/services/catalog_service.rs) — [`src/services/catalog_status.rs`](src/services/catalog_status.rs) |
| **4. Done screen** | Reports what a run moved/failed/skipped; buttons open library folder or game folder. | [`src/ui/done_view.rs`](src/ui/done_view.rs) |
| **5. Undo** | `rollback_service.rs` reads `config/last-organization.json`, restores each archived file to its source, prunes emptied folders this run created into `Archive/` (never deletes a folder it didn't make). | [`src/services/rollback_service.rs`](src/services/rollback_service.rs) |
| **6. Batch extract** | `services/batch_extract_service.rs` unpacks archives to user-chosen folders outside the library, relocates installer layouts to `Needs Install`, writes per-result status next to the catalog. | [`src/services/batch_extract_service.rs`](src/services/batch_extract_service.rs) — [`src/ui/batch_extract_window.rs`](src/ui/batch_extract_window.rs) |

Phases run in order: Discover → Organize → Catalog → Done. Undo and Batch extract are independent entry points (Undo reads `last-organization.json`; Batch extract is triggered from the catalog page via `steamgameorganizer://` URI).

> [!IMPORTANT]
> See the [mermaid workflow diagram](README.md#-app-workflow-end-to-end) in [`README.md`](README.md) for a visual representation of this flow.

---

## 🔌 URI / protocol handler

The app registers `steamgameorganizer://` under `HKCU\Software\Classes` (per user, no elevation). Supported actions:

| Action | Behavior | Code |
|--------|----------|------|
| `extract` | Parse into an `ExtractRequest` via `src/core/uri_actions.rs` (owns `SCHEME` and `SYSTEM_PATHS`, the folders a typed destination may not sit inside) | [`src/core/uri_actions.rs`](src/core/uri_actions.rs) |
| `extract-all` / `extract-multi` | Category or whole library / hand-picked selection → opens `BatchExtractWindow` (hours of 7z needs a visible queue) | [`src/services/batch_extract_service.rs`](src/services/batch_extract_service.rs) — [`src/ui/batch_extract_window.rs`](src/ui/batch_extract_window.rs) |
| `setup` | Prefill the three-folder setup wizard text boxes | [`src/services/setup_service.rs`](src/services/setup_service.rs) — [`src/ui/setup_window.rs`](src/ui/setup_window.rs) |
| `open-extracted` | `steamgameorganizer://open-extracted?path=<folder>` — opens an extracted/installer folder; path must resolve under a configured extract folder (validated/normalized by the handler) | [`src/core/uri_actions.rs`](src/core/uri_actions.rs) |
| `play` | `steamgameorganizer://play?exe=<file>&path=<marker-folder>` or `?path=<marker-folder>` — launches a validated `.exe` under configured extract folders; when `exe` is omitted, the handler uses the marker's persisted `launch_target` | [`src/core/uri_actions.rs`](src/core/uri_actions.rs) — [`src/services/catalog_status.rs`](src/services/catalog_status.rs) |
| `pick-launcher` | `steamgameorganizer://pick-launcher?path=<marker-folder>` — opens a file picker constrained to the resolved extracted root, validates the chosen `.exe`, persists `launch_target` in `.sgo-extract-info`, then regenerates/opens the catalog | [`src/services/catalog_status.rs`](src/services/catalog_status.rs) |
| `mark-installed` | `steamgameorganizer://mark-installed?path=<marker-folder>` — persists setup completion (`setup_done`, `installed_at`, `needs_install=false`) and regenerates/opens the catalog | [`src/services/catalog_status.rs`](src/services/catalog_status.rs) |
| `refresh-catalog` | Regenerate `Game Library.html` against the live library and re-open it (the page's Unpacked badges are decided at generation time; a `file://` page cannot re-scan the folder itself) | [`src/services/catalog_service.rs`](src/services/catalog_service.rs) |
| `open-folder` | `steamgameorganizer://open-folder?path=<folder>` — opens the game/library source folder in Explorer; path validated against the library root | [`src/core/uri_actions.rs`](src/core/uri_actions.rs) |

On a first run with no settings, `_needs_setup` detects a missing `settings.json` / nonexistent library root and opens `setup_window.rs` before the GUI — the catalog's own setup button cannot install the protocol handler, so the wizard is the first-run fallback.

> [!WARNING]
> URI actions treat every field as hostile input — a link can be crafted by any page, so the source must resolve inside the configured library root, must exist with an archive extension, and the destination must not sit inside a system folder or the library itself.

### Launcher discovery

`src/services/catalog_status.rs` `discover_game_launchers` conservatively scans the extracted root (max depth 3, 250 candidates) for playable `.exe` files, filtering installers/uninstallers/crash handlers/redistributables/helper tools (Unity crash handlers, `BugReporter`, `elevate`, `createdump`, `UEPrereqSetup`, `QuickSFV`, `ffmpeg`, `Spatial Media Metadata Injector`, full JRE toolchain) and scoring by depth/name/size; returns a ranked list for user choice via Pick launcher. The chosen `launch_target` persists to `.sgo-extract-info` and subsequent Play actions use it.

---

## 🖼️ Game Library.html — catalog page mechanics

`CatalogService.generate` writes `Game Library.html` plus `Game Library.status.js` beside the library root. The page is a single self-contained HTML file (embedded CSS + vanilla JS, no build step, no external requests) that a reader opens in a browser.

### Browse and filter the library

- **Category rail on the left**, with category → release year → recently added (7/14/30 day) → genre → tag chips. Counts beside each chip are counted from what is actually on disk, not from a fixed vocabulary, so a rail never shows filters that match nothing.
- **Search box** filters against a per-card `data-search` haystack (name, category, developer, publisher, archive, release date, archive created, description, genres, tags). Cards hide/show inline; category counts recount themselves as filters narrow (`data-toc-count`), and empty sections grey out instead of vanishing so the library shape stays visible.
- **Sort by Name / Newest / Oldest / Largest / Smallest / Recently added / Longest owned**, reordering each category's own grid. "Newest" and "Oldest" use the Steam release date; "Recently added" and "Longest owned" use when the archive file landed on disk. Tie-breaks fall back to name so the order never reshuffles arbitrarily.
- **Card-size preset** (small/medium/large) and **theme toggle** (dark/light), both saved to `localStorage` so they survive a reload.
- **Keyboard**: `/` focuses search, `Escape` clears all filters and multi-select, `Home` goes to top, `Enter` commits a typed path box.

### Know the state of each game

- **Hero stats**: total games, categories, with artwork, on-disk bytes, plus "Missing art", "To extract", "New version", "Hide extracted" — the last three are real toggle buttons when there is something to filter, plain tiles when there is nothing to act on.
- **Each card shows**: artwork (Steam banner, or a generated name-keyed banner so no card is a flat grey block), release date, developer, archive created, archive file name + size, genre + tag chips (tags capped at four, overflow shown as `+N`), description truncated at 220 chars.
- **Status badges** drawn from the same predicate the batch planner skips on, so a badge never claims a game is done that Extract all would unpack again:
  - 🟢 **Unpacked** — archive unpacked into the configured destination folder
  - 🟡 **Needs install** — unpacked but still an installer repack (payload relocated to a `Needs Install` folder)
  - 🔵 **New version** — unpacked but the archive on disk has changed size/mtime since extraction
  - 🔴 **Installer** — archive is an installer repack not yet unpacked
  - ⚪ **No Steam match** — no AppID found (card still shows artwork/archive/size/path buttons; only the two Steam actions are missing)

> [!NOTE]
> Because `file://` pages cannot stat any folder, these badges are decided against the default destination folder at generation time. Typing a different destination retracts them immediately (`syncUnpackedBadges`) — a claim about a folder the reader just changed is taken back rather than left standing.

### Open games, folders, and Steam

- **Card art link** → Steam store page (`store.steampowered.com/app/<appid>`), or opens nothing with a clear reason when there is no Steam match.
- **Open in Steam** → `steam://run/<appid>` Steam client link.
- **Open** → `steamgameorganizer://open-folder?path=<folder>` opens the game's folder in Explorer, path rebuilt from the typed game-folder root so it follows a moved library.
- **Copy path** → copies the full archive path to the clipboard.

### Extract games through the app (the page cannot unpack anything itself)

`file://` pages cannot open folders or run programs — that boundary is the whole point of the sandbox. Every extract goes through a `steamgameorganizer://extract` link, which the browser hands to the desktop after a confirmation.

- **Single `Extract` per card**: source percent-encoded (library names are full of spaces/ampersands/quotes), destination taken from the typed box at click time (falls back to the first configured folder). No confirmation prompt — one archive is small and reversible.
- **`Extract all` / `Extract remaining`** per category or whole library: confirmed on evidence (count, archive size, destination) before the run starts — `Extract all` on a 176-game library is one click from filling a drive. Skip logic skips games already unpacked there.
- **Multi-select mode**: reveal checkboxes, pick two or more games, extract them together as one `extract-multi://` batch.
- **The destination box** offers configured folders as datalist suggestions but starts on the first; paths are rebuilt from the typed root at click time so they follow a moved library rather than being frozen to the machine that ran the scan.

### Setup and refresh

- **Set up on this PC** → `steamgameorganizer://setup`, carrying the typed game folder and extract destination so the wizard starts on them. A command-line fallback shows if the protocol never opened.
- **Refresh catalog** → `steamgameorganizer://refresh-catalog`: re-walks the library and rewrites the page so Unpacked badges match what is actually on disk now. Needed because an extraction done outside the app leaves stale badges until regenerated.
- **run-status banner** shows the last batch run result (`Game Library.status.js`, rewritten by the app after every batch run), summarised as a one-line chip in the rail so it stays visible when scrolled past.

### Why this is one HTML file with embedded JS

- A `file://` page cannot `fetch`/`XHR` anything, so a classic `<script src>` beside itself is the one external load allowed — that is `Game Library.status.js`, loaded before the inline script so batch results are on `window` when the script reads them.
- `localStorage` is wrapped in try/catch because it throws outright on `file://` in some browsers rather than returning null.
- `color-scheme` is set explicitly as `dark`/`light` rather than relying on OS preference, because the generated banner art and card scrims are tuned for dark.

---

## 🔒 Key decisions already made (do not re-litigate without cause)

| Decision | Rationale | Code |
|----------|-----------|------|
| **Move to `Archive/`, never delete.** | Empty game folders, empty categories, re-categorized source folders, and rollback-emptied folders are moved into `Archive/` (with `(n)` collision suffixes) so the user can review before deleting. `rmtree` is only a fallback when `library_root` is unknown. | [`src/services/organizer_service.rs`](src/services/organizer_service.rs) — [`src/services/rollback_service.rs`](src/services/rollback_service.rs) |
| **Two folder rules.** | `_folder_is_disposable` (download folder, any image OK) and `_folder_is_prunable` (organized game folder, app-shaped artwork only) are deliberately different. Never merge them. | [`src/services/organizer_service.rs`](src/services/organizer_service.rs) |
| **Ownership gating.** | Undo only prunes folders `created_game_dir` says this run made. A folder already there belongs to the user whatever it holds. | [`src/services/rollback_service.rs`](src/services/rollback_service.rs) |
| **Reserved dirs.** | `Archive` and `Processing` under the library root are never treated as categories. The app's own project folder is never swept. | [`src/services/catalog_service.rs`](src/services/catalog_service.rs) |
| **Atomic writes.** | `settings.json`, `scan-state.json`, and the rollback journal all use temp-file + `std::fs::rename` with retry on `PermissionError` (OneDrive locks). | [`src/core/config.rs`](src/core/config.rs) |
| **Release builds via `cargo build --release`.** | Produces a self-contained `.exe` at `target/release/steam-game-organizer.exe`. The user runs this exe directly — no PyInstaller, no frozen bundle. | `Cargo.toml` |

---

## 🖥️ Commands

| Command | Purpose | Code |
|---------|---------|------|
| `cargo check` | Compile check | — |
| `cargo clippy --all-targets` | Lint | [`Cargo.toml`](Cargo.toml) |
| `cargo test` | Rust unit tests — expect `OK` with no new skips | `src/` |
| `cargo build --release` | Build release exe — produces `target/release/steam-game-organizer.exe` | [`Cargo.toml`](Cargo.toml) |

---

## 🧪 Testing conventions

| Convention | Rule | Code |
|------------|------|------|
| **No test may skip.** | `cargo test` reports `OK` with no new skips. A skip that is not expected is a bug. | `src/` |
| **Every check must actually run.** | `Ran 0 tests` from a collected module is a bug. | `src/` |
| **Tests must not write this project's own state.** | Rust tests must not write under real `config/`, `cache/`, or `logs/` — use temp dirs. | `src/` |
| **Every regression is proved by reverting its fix.** | Watch the test fail, then restore and watch it pass. Record the failure count, not just that it failed. | `src/` |
| **Windows-only platform.** | Anything branching on platform should raise or return a refusal rather than keep a second implementation. | `src/` |
| **No dead code.** | `#[allow(dead_code)]` only when intentionally leaving a stub for future implementation. | `src/` |

---
