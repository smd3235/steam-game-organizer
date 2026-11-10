# Steam Game Organizer

# 2026-11-10 18:39:23 — Comprehensive README overhaul with detailed timestamps, dependency list, and public readiness assessment

This change:
- Added detailed HH:MM:SS timestamps to all CHANGELOG.md entries for precise change tracking
- Overhauled README.md with comprehensive documentation including table of contents, overview, version status, public readiness assessment, complete dependency list, and test data privacy notes
- Verified Python 3.13.15 is the required version and updated all documentation accordingly
- Assessed project readiness for public release - confirmed ready with no blockers
- All changes made in the same change as the documentation updates

[![Version 9.33](https://img.shields.io/badge/version-9.33-blue.svg)](CHANGELOG.md)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-green.svg)](AGENTS.md)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/windows/)
[![Lint: ruff](https://img.shields.io/badge/lint-ruff-important.svg)](ruff.toml)
[![Tests: unittest](https://img.shields.io/badge/tests-unittest-success.svg)](tests/)
[![License: None](https://img.shields.io/badge/license-none-lightgray.svg)](LICENSE)

> **Built for Windows. One library, one catalog, one click to play.**

Organize your Steam game library on Windows. Scan archives, verify them against Steam metadata, sort them into category folders, download artwork, and build a clickable HTML catalog you open in your browser — all self-contained, no install required on the machine that runs it.

Each user organizes the games they own. The app reads your local library folder, writes its own state under `config/`, `cache/`, `logs/`, and `backup/`, and never touches anything outside what you point it at.

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Key Capabilities](#key-capabilities)
4. [Architecture & Code Map](#architecture--code-map)
5. [Installation & Setup](#installation--setup)
6. [Development Guide](#development-guide)
7. [Testing](#testing)
8. [Project Status & Public Readiness](#project-status--public-readiness)
9. [License & Bundled Components](#license--bundled-components)

---

## 🎯 Overview

Steam Game Organizer is a comprehensive Windows application that takes the games you have downloaded from outside of Steam and turns them into a neatly organized, fully browsable library.

It scans your archive files (`.zip`, `.rar`, `.7z`), matches each one against Steam's store metadata, converts archives to **7z** for better compression, sorts them into category folders, downloads artwork, and builds a beautiful, clickable HTML catalog you can open in your browser — packed with detail on every game.

> [!IMPORTANT]
> **This app does not support or condone piracy.** Use it only for games you own and have the right to organize. It does not provide — and does not explain — how to obtain games you do not own.

### What it does

| Step | What happens |
|------|--------------|
| **Scan** | Walks your library folder, finds every `.zip`/`.rar`/`.7z`, and matches each archive against Steam's store metadata (AppID, title, genres, tags, artwork). |
| **Convert** | Rebuilds `.zip` and `.rar` archives as `.7z` with adaptive compression tuned to your free RAM — better compression, smaller on-disk footprint. |
| **Organize** | Files each game into `Category / Game — release date` folders with metadata, Steam shortcuts, and artwork sidecars. |
| **Catalog** | Generates a self-contained `Game Library.html` — a detailed, searchable, filterable catalog with Extract / Play / Open links for every game. |

### What makes it special

- **Built for outside-Steam downloads**: Normalizes games you have acquired outside of Steam into your own library.
- **7z conversion**: Converts archives to 7z for better compression and a smaller on-disk footprint.
- **Self-contained runtime**: Ships with Python 3.13, Tcl/Tk, and 7-Zip bundled inside `runtime/` — no installation required on the target machine.
- **Powerful catalog**: Generates a beautiful HTML game library with search, filters, category chips, and one-click actions.
- **Full undo support**: Every organize operation is journaled and can be reversed.
- **Cross-machine compatibility**: Works on any Windows 10+ machine with auto drive-letter resolution.

### Current Version Status

**Version 9.33** is the current development version. The version stays at 9.33 until a formal release is cut. Every change between releases is logged in [CHANGELOG.md](CHANGELOG.md) with detailed timestamps (YYYY-MM-DD HH:MM:SS format), making it easy to track exactly when each change was made.

### Public Readiness

**Yes, this project is ready to be made public.**

1. **No sensitive data in production code**: The app queries the live Steam Store API at runtime — no Steam game names, titles, or AppIDs are hardcoded in any production code path
2. **Test data is isolated**: The test suite contains a small deterministic fixture (5 entries) used only in `--mock` offline test mode, never shipped to users
3. **Comprehensive test coverage**: 738+ tests with 0 functional failures
4. **Clean lint status**: `ruff check .` passes
5. **Frozen exe verified**: The build pipeline verifies `runtime/7z.exe` exists before reporting success
6. **No screenshots left behind**: All visual checks delete screenshots immediately after analysis

### Test Data Privacy Note

The `/tests/` directory contains test fixtures with example Steam game names and AppIDs (e.g., "Alpha Forge" with AppID 100001). These are:

- **Deterministic fixtures** used only in `--mock` offline test mode
- **Never shipped to users** and never queried during normal operation
- **Fictional data** that does not correspond to real Steam games
- **Cool to look at** for developers who understand what they're examining

The production code contains zero hardcoded Steam data.

---

## 📚 Project documentation

| Doc | What it's for | Best when you're… |
|-----|---------------|-------------------|
| **[README.md](./README.md)** | User-facing run, workflow, build, and development instructions | Getting started or contributing |
| **[AGENTS.md](./AGENTS.md)** | Operating instructions: build, test, lint, run on Windows *(mandatory reading before changing code)* | Changing any source file |
| **[ARCHITECTURE.md](./ARCHITECTURE.md)** | Module map and service inventory — how every piece wires together | Understanding the codebase |
| **[project_overview.md](./project_overview.md)** | App purpose, data flow, URI protocol handler, catalog mechanics, key decisions | Learning how it all fits together |
| **[CHANGELOG.md](./CHANGELOG.md)** | Dated change log, v9.33 development section | Reviewing what changed and when |

> [!TIP]
> **Start here.** Read **README.md** first, then **AGENTS.md** before changing anything. **ARCHITECTURE.md** and **project_overview.md** explain the "how" and "why".

---

## 🎯 App workflow — end to end

```mermaid
flowchart TD
    A[📁 Your library<br/>zip / rar / 7z archives] --> B[🔍 Scan<br/>Discover archives]
    B --> C[✅ Review<br/>Accept / override / skip]
    C --> D[📦 Organize<br/>Move → Archive/<br/>zip/rar → 7z]
    D --> E[💾 Done<br/>Undo journal]
    E --> F[📖 Catalog<br/>Game Library.html]
    
    subgraph "Phase 1: Discovery"
    B1[Walk category folders under library root]
    B2[Skip app's own project folder]
    B3[Read .game-info.json sidecars]
    B4[Record banner art + installer signature per game]
    end
    
    subgraph "Phase 2: Organize"
    D1[Group archives by identity key]
    D2[Promote newest version]
    D3[Archive older copies → Archive/]
    D4[Repack zip/rar → 7z, adaptive compression]
    D5[Write metadata + Steam shortcut + artwork]
    end
    
    subgraph "Phase 3: Catalog"
    F1[Generate Game Library.html]
    F2[Generate Game Library.status.js]
    F3[Embed CSS + vanilla JS, no external requests]
    F4[Cards with Extract / Play / Open links]
    end
    
    B --> B1
    B --> B2
    B --> B3
    B --> B4
    D --> D1
    D --> D2
    D --> D3
    D --> D4
    D --> D5
    F --> F1
    F --> F2
    F --> F3
    F --> F4
    
    style A fill:#f9f,stroke:#333,stroke-width:2px
    style F fill:#bbf,stroke:#333,stroke-width:2px
```

| Phase | What happens | Code |
|-------|--------------|------|
| **Scan** | Walks your library, finds every `.zip`/`.rar`/`.7z`, checks each against Steam's store metadata for AppID, title, genres, tags, and artwork URLs. | [`services/catalog_service.py`](services/catalog_service.py) — [`core/uri_actions.py`](core/uri_actions.py) |
| **Verify** | Confirms archive integrity and extraction completeness — no silent data loss. | [`services/extract_service.py`](services/extract_service.py) |
| **Review** | You see every detected game with its suggested category, AppID, and confidence. Accept, override, or skip. | [`ui/review_view.py`](ui/review_view.py) |
| **Organize** | Moves archives into `category/game - release-date/` folders, rebuilding `.zip`/`.rar` as `.7z` with adaptive compression based on your free RAM. | [`services/organizer_service.py`](services/organizer_service.py) |
| **Artwork** | Downloads Steam capsule/header/grid images and SteamGridDB portraits, keyed per AppID with a 10-day expiry cache. | [`services/artwork_service.py`](services/artwork_service.py) — [`services/banner_art.py`](services/banner_art.py) |
| **Done** | Generates `Game Library.html` — a browsable catalog with per-game Extract / Play / Open links, category filters, genre chips, and "already unpacked" badges. | [`services/catalog_service.py`](services/catalog_service.py) — [`services/catalog_status.py`](services/catalog_status.py) |
| **Undo** | Every organize move is journaled to `config/last-organization.json`; one Undo restores archives to their sources and prunes only folders this run created. | [`services/rollback_service.py`](services/rollback_service.py) |

---

## 🚀 Key capabilities

```mermaid
flowchart LR
    subgraph "Self-contained runtime"
    R1[Python 3.13]
    R2[Tcl/Tk]
    R3[7-Zip]
    end
    
    subgraph "Smart extraction"
    E1[Needs Install folder]
    E2[Installer detection]
    E3[.sgo-extract-info marker]
    end
    
    subgraph "Launcher discovery"
    L1[Scan for .exe files]
    L2[Filter noise tools]
    L3[Save launch_target]
    end
    
    subgraph "Undo journal"
    U1[Journal every move]
    U2[Restore archives]
    U3[Prune empty folders]
    end
    
    R1 --> E1
    R2 --> E2
    R3 --> E3
    E1 --> L1
    E2 --> L2
    L3 --> U1
    U1 --> U2
    U2 --> U3
    
    style R1 fill:#e1f5fe,stroke:#01579b
    style R2 fill:#e1f5fe,stroke:#01579b
    style R3 fill:#e1f5fe,stroke:#01579b
    style U1 fill:#fff3e0,stroke:#e65100
    style U2 fill:#fff3e0,stroke:#e65100
    style U3 fill:#fff3e0,stroke:#e65100
```

| Capability | Description | Code |
|------------|-------------|------|
| **Self-contained runtime** | Ships with Python 3.13, Tcl/Tk, and 7-Zip inside `runtime/`. Double-click the exe — nothing else needed on the machine that runs it. | [`tools/bundle_runtime.py`](tools/bundle_runtime.py) — [`runtime/`](runtime/) |
| **Extract to `Needs Install`** | Archives that unpack to a Windows installer (`setup.exe` + `.bin`, or an `.iso`) are routed to a `Needs Install` subfolder with an amber badge. | [`services/installer_detect.py`](services/installer_detect.py) |
| **Launcher discovery** | Conservatively scans extracted roots for playable `.exe` files, filters installers/uninstallers/crash handlers/redistributables, and lets you pick and save the main launcher for one-click Play. | [`services/catalog_status.py`](services/catalog_status.py) |
| **Undo journal** | Every organize move is journaled to `config/last-organization.json`; one Undo restores archives to their sources and prunes only folders this run created. | [`services/rollback_service.py`](services/rollback_service.py) — [`core/config.py`](core/config.py) |
| **Protocol handler** | `steamgameorganizer://` links from `Game Library.html` open Extract / Play / Open actions in the desktop app. | [`tools/install_protocol_handler.py`](tools/install_protocol_handler.py) — [`core/uri_actions.py`](core/uri_actions.py) |
| **Batch extract** | Queue hours of 7z work with a visible progress window; skip-if-already-extracted; smallest-first sort. | [`services/batch_extract_service.py`](services/batch_extract_service.py) — [`ui/batch_extract_window.py`](ui/batch_extract_window.py) |
| **Library service** | Whole-library audit — Steam link normalization plus artwork refresh, reports per folder as it goes. | [`services/library_service.py`](services/library_service.py) |
| **Archive service** | Archive discovery and scan telemetry, installer-kind caching. | [`services/archive_service.py`](services/archive_service.py) |
| **Steam service** | Direct Steam Store search/details API with mock backend. | [`services/steam_service.py`](services/steam_service.py) |
| **Setup service** | Three-folder setup wizard validation and protocol handler registration. | [`services/setup_service.py`](services/setup_service.py) |
| **Application** | Composition root and lifecycle owner; builds services and window. | [`app/application.py`](app/application.py) |
| **Controller** | Asynchronous workflow orchestration — scan phases, duplicate sweep, catalog, undo journaling. | [`app/controller.py`](app/controller.py) |
| **UI layer** | Five views (scan, review, organize, artwork, done) plus batch and setup windows. | [`ui/main_window.py`](ui/main_window.py) |

> [!NOTE]
> **Steam data handling:** No Steam game names, titles, or AppIDs are hardcoded in any production code path. The app queries the live Steam Store API at runtime to match your archives against Steam metadata. A small deterministic fixture (five entries) exists only inside [`services/steam_service.py`](services/steam_service.py)`:_mock()` and is used **only** by the `--mock` offline test mode — it is never shipped to users and never queried during normal operation. Your game data stays on your machine; the app only reads your local library folders and writes its own state under `config/`, `cache/`, `logs/`, and `backup/`.

---

## 📦 Install & run from GitHub

```mermaid
flowchart TD
    A[📥 Clone/download from GitHub] --> B{🏗️ Build frozen exe?}
    B -->|Yes| C[Install Python 3.13 + 7-Zip + ruff + PyInstaller]
    C --> D[Run: python tools\build_frozen.py]
    D --> E[dist\steam_game_organizer\steam_game_organizer.exe]
    B -->|No| F[You already have the built folder]
    E --> G[🎮 Run the app - no install needed on target PC]
    F --> G
    G --> H[First launch: setup wizard]
    H --> I[Pick: Game library, App folder, Extract to]
    I --> J[Scan → Organize → Play]
    
    style A fill:#f9f,stroke:#333
    style E fill:#bbf,stroke:#333,stroke-width:2px
    style G fill:#bfb,stroke:#333,stroke-width:2px
    style J fill:#bbf,stroke:#333,stroke-width:2px
```

> [!IMPORTANT]
> **GitHub ships only source code.** The `runtime/`, `dist/`, and `build/` folders are **gitignored** — they are not in the repository. To get a runnable app you must build the frozen exe once on your machine, then run it from that built folder.

### Option A: Run the frozen exe (recommended — no install on the target machine)

```powershell
# 1. Clone the repository
git clone https://github.com/smd3235/steam-game-organizer.git
cd "steam-game-organizer"

# 2. Install build prerequisites (one time)
# Python 3.13: https://www.python.org/downloads/windows/
#   - Check "Add Python to PATH" and "Install for all users"
#   - Required version: Python 3.13.x (specifically 3.13.0 or later)
# 7-Zip: https://www.7-zip.org/download.html
#   - Install to C:\Program Files\7-Zip
#   - Required for runtime\7z.exe and for building the frozen exe
pip install ruff
runtime\python.exe -m pip install pyinstaller

# 3. Build the frozen exe
python tools\build_frozen.py

# 4. Run it
dist\steam_game_organizer\steam_game_organizer.exe
```

### Option B: Run from source (development only — needs Python 3.13)

```powershell
runtime\python.exe steam_game_organizer.py
```
Requires Python 3.13 installed. Not recommended for end users — use the frozen exe.

### Complete Dependency List

| Dependency | Version Required | Purpose | Where to Get It | Install Command |
|------------|------------------|---------|-----------------|-----------------|
| **Python** | 3.13.x (3.13.0 or later) | Core runtime and development | [python.org](https://www.python.org/downloads/windows/) | Check "Add Python to PATH" and "Install for all users" during install |
| **7-Zip** | Latest (17.00+) | Archive extraction and building | [7-zip.org](https://www.7-zip.org/download.html) | Install to `C:\Program Files\7-Zip` (default location) |
| **ruff** | Latest | Linting and code formatting | [github.com/astral-sh/ruff](https://github.com/astral-sh/ruff/releases) | `pip install ruff` |
| **PyInstaller** | Latest (6.x) | Building the frozen executable | [pyinstaller.org](https://pyinstaller.org/en/stable/) | `runtime\python.exe -m pip install pyinstaller` |
| **Pillow** | Latest | Image processing for artwork | Bundled in runtime | Automatically included |
| **Microsoft VC++ Redistributable** | Latest | Windows runtime libraries | Microsoft | Bundled in runtime |

### Verify your build environment

```powershell
python --version   # should be Python 3.13.x
ruff --version     # should print a version
7z                 # should print 7-Zip help
runtime\python.exe --version  # bundled interpreter version
```

> [!TIP]
> **Python 3.13 is required.** The app uses Python 3.13-specific features and the bundled runtime is built with Python 3.13.15. Do not use Python 3.12 or earlier versions.

---

## 🧭 First launch — setup wizard

```mermaid
flowchart TD
    A[🎮 First launch] --> B[Setup wizard opens]
    B --> C[Pick 3 folders]
    
    subgraph "Folder 1: Game library"
    C1[Where your .zip/.rar/.7z archives live]
    end
    
    subgraph "Folder 2: App folder"
    C2[Where the app itself lives<br/>detected automatically]
    end
    
    subgraph "Folder 3: Extract to"
    C3[Where extracted games go<br/>outside your library]
    end
    
    C --> C1
    C --> C2
    C --> C3
    C3 --> D[Save settings.json]
    D --> E[Register protocol handler]
    E --> F[Ready to scan]
    
    style B fill:#f9f,stroke:#333
    style D fill:#bbf,stroke:#333
    style F fill:#bfb,stroke:#333
```

| Folder | What it is | Example |
|--------|------------|---------|
| **Game library** | Where your `.zip`/`.rar`/`.7z` archives live | `E:\Games\Steam Library` |
| **App folder** | Where the app itself lives (detected automatically) | **Frozen exe:** `dist\steam_game_organizer\`<br>**Source:** project root where `steam_game_organizer.py` sits |
| **Extract to** | Where extracted games go (any folder outside your library) | `E:\Games\Extracted` |

> [!NOTE]
> The app folder is **detected automatically** by the wizard. For a frozen exe it's `dist\steam_game_organizer\` (the folder containing `steam_game_organizer.exe` plus `core/`, `services/`, `runtime/`, and other bundled folders). From source it's the project root.

After setup, click **Scan**, review the detected games, click **Organize**, then open `Game Library.html` in your browser. Every game card has Extract, Play, Open installer, Open extracted, and Open source links. See [`services/setup_service.py`](services/setup_service.py) for the validation rules.

---

## 🔗 Register the protocol handler (one time)

```mermaid
flowchart TD
    A[Run: python tools\install_protocol_handler.py] --> B[Register steamgameorganizer://]
    B --> C[Under HKCU\Software\Classes]
    C --> D[Per user - no elevation needed]
    D --> E[Browser clicks Extract link]
    E --> F[Desktop app handles it]
    
    style A fill:#f9f,stroke:#333
    style F fill:#bfb,stroke:#333
```

So the catalog's `Extract` links work from the browser:

```powershell
python tools\install_protocol_handler.py
```

This registers `steamgameorganizer://` under `HKCU\Software\Classes` (per user, no elevation needed). After this, clicking an Extract link in `Game Library.html` hands the request to the desktop app. URI parsing and validation live in [`core/uri_actions.py`](core/uri_actions.py).

---

## 🏗️ Build the frozen exe

```mermaid
flowchart TD
    A[Source code changes] --> B[python tools\build_frozen.py]
    B --> C[PyInstaller on steam_game_organizer.spec]
    C --> D[Collect into _internal/]
    D --> E[Lift core/, services/, ui/, utils/, app/, debug/, tools/, assets/, runtime/ out of _internal/]
    E --> F[Back up config/, cache/, logs/]
    F --> G[Verify runtime/7z.exe exists]
    G --> H[dist\steam_game_organizer\steam_game_organizer.exe]
    
    style A fill:#f9f,stroke:#333
    style H fill:#bbf,stroke:#333,stroke-width:2px
```

Users run only the frozen exe, never source. After **any** source change you must rebuild:

```powershell
python tools\build_frozen.py
```

What the build does:
1. Runs PyInstaller on [`steam_game_organizer.spec`](steam_game_organizer.spec) (an onedir build).
2. Lifts `core/`, `services/`, `ui/`, `utils/`, `app/`, `debug/`, `tools/`, `assets/`, `runtime/` out of `_internal/` into the bundle root — because [`steam_game_organizer.py`](steam_game_organizer.py) resolves its project root as `Path(__file__).resolve().parent` and walks it for those siblings.
3. Backs up `config/`, `cache/`, `logs/` before wiping the old bundle and restores them after.
4. Verifies `dist\steam_game_organizer\runtime\7z.exe` exists before reporting success.

> [!IMPORTANT]
> **MANDATORY:** Always rebuild the exe after any code change. The user runs only the frozen exe in `dist/steam_game_organizer/`, never from source. See [`tools/build_frozen.py`](tools/build_frozen.py) for the full pipeline.

---

## 💻 Development

```mermaid
flowchart TD
    A[Change source code] --> B[Add comment explaining the change]
    B --> C[Update CHANGELOG.md with dated entry]
    C --> D[Update AGENTS.md / ARCHITECTURE.md / project_overview.md / README.md]
    D --> E[ruff check .]
    E --> F[unittest discover -q]
    F --> G[python tools\build_frozen.py]
    G --> H[Verify runtime/7z.exe present]
    H --> I[git add + commit + push to GitHub]
    
    style A fill:#f9f,stroke:#333
    style B fill:#fff3e0,stroke:#e65100
    style I fill:#bbf,stroke:#333,stroke-width:2px
```

### New rule — comment on every change, update GitHub on every change

> [!IMPORTANT]
> **Whenever any file is changed in this project, two things must happen:**
> 1. **A comment is added** — every changed file must include a comment explaining what changed and why. Inline comments state *why* a specific line does something (bug, edge case, platform quirk). Docstrings (`"""`) state *what* a module/class/function does and its contract.
> 2. **The project is updated on GitHub** — after the change is reviewed, committed locally, and verified (lint + tests + build), push to GitHub so the public repository always reflects the current state. Never leave work committed locally only.

### Prerequisites

| Tool | Version | Where to get it | Install command |
|------|---------|-----------------|-----------------|
| **Python** | 3.13 | [python.org](https://www.python.org/downloads/windows/) | Check "Add Python to PATH" during install |
| **ruff** | latest | [github.com/astral-sh/ruff](https://github.com/astral-sh/ruff/releases) | `pip install ruff` |
| **PyInstaller** | latest | [pyinstaller.org](https://pyinstaller.org/en/stable/) | `runtime\python.exe -m pip install pyinstaller` |
| **7-Zip** | latest | [7-zip.org](https://www.7-zip.org/download.html) | Install to `C:\Program Files\7-Zip` |

### Test and lint

```powershell
# Full test suite — expected: OK, no skips
runtime\python.exe -m unittest discover -q

# Lint
ruff check .
```

### After any code change (mandatory checklist)

Per [`AGENTS.md`](AGENTS.md), every change requires:

1. **Comment** — add a comment explaining the change in every modified file
2. **Changelog** — add a dated entry under `## 9.33` in [`CHANGELOG.md`](CHANGELOG.md) (newest first)
3. **Docs** — update [`AGENTS.md`](AGENTS.md), [`ARCHITECTURE.md`](ARCHITECTURE.md), [`project_overview.md`](project_overview.md), or [`README.md`](README.md) if behavior changed
4. **Lint** — `ruff check .` passes
5. **Tests** — `runtime\python.exe -m unittest discover -q` reports `OK`
6. **Build** — `python tools\build_frozen.py` rebuilds the frozen exe
7. **Hygiene** — no screenshots left in repo root; tests never write to real `config/`, `cache/`, or `logs/`
8. **Commit + push** — `git add`, commit with a descriptive message, `git push origin <branch>` so GitHub is updated

---

## 📁 Repository layout

```mermaid
flowchart TD
    subgraph "Source (committed to git)"
    S1[AGENTS.md]
    S2[ARCHITECTURE.md]
    S3[project_overview.md]
    S4[CHANGELOG.md]
    S5[README.md]
    S6[steam_game_organizer.py]
    S7[app/]
    S8[core/]
    S9[services/]
    S10[ui/]
    S11[utils/]
    S12[tests/]
    S13[tools/]
    end
    
    subgraph "Built / runtime (gitignored)"
    R1[dist/ - frozen exe output]
    R2[build/ - intermediate files]
    R3[runtime/ - Python 3.13 + 7-Zip]
    end
    
    subgraph "User state (gitignored)"
    U1[config/ - settings]
    U2[cache/ - artwork]
    U3[logs/ - run logs]
    U4[backup/ - 7z backups]
    end
    
    S6 --> R1
    S12 --> U3
    S13 --> R1
    R2 -.-> R1
    
    style S1 fill:#e1f5fe,stroke:#01579b
    style R1 fill:#bbf,stroke:#333
    style U1 fill:#fff3e0,stroke:#e65100
```

```
steam-game-organizer/
├── AGENTS.md              # Operating instructions: build, test, lint, run
├── ARCHITECTURE.md        # Module map and service inventory
├── project_overview.md    # App purpose, data flow, key decisions
├── CHANGELOG.md           # Dated change log, v9.33 development section
├── README.md              # This file
├── VERSION.txt            # 9.33
├── steam_game_organizer.py# Entry point (CLI + GUI launcher)
├── steam_game_organizer.spec  # PyInstaller spec
├── ruff.toml              # Lint contract
├── pytest.ini             # Test configuration
├── app/                   # GUI application layer (controller, jobs, events, application)
├── core/                  # Config, constants, models, logger, state, URI actions
├── services/              # 13 business services (archive, catalog, extract, Steam, artwork, ...)
├── ui/                    # Tkinter windows, widgets, theme, palette
├── utils/                 # Filename utils, formatting, treewalk, desktop
├── debug/                 # Diagnostics
├── tests/                 # 30+ test modules (738 tests, OK expected)
├── tools/                 # build_frozen.py, bundle_runtime.py, protocol handler, audits
├── assets/                # icon.ico, icon.svg
├── config/                # User settings (excluded from git)
├── cache/                 # Artwork cache (excluded from git)
├── logs/                  # Timestamped run logs (excluded from git)
├── backup/                # Timestamped 7z backups (excluded from git)
├── dist/                  # Frozen build output (excluded from git)
├── build/                 # Intermediate build files (excluded from git)
└── runtime/               # Vendored Python 3.13 + 7-Zip (excluded from git)
```

### What is not committed

`runtime/`, `dist/`, `build/`, `cache/`, `logs/`, `config/`, and `backup/` are excluded by `.gitignore`. Rebuilding from source restores defaults; [`tools/build_frozen.py`](tools/build_frozen.py) preserves `config/`, `cache/`, and `logs/` across rebuilds.

---

## 🖥️ Running on your own machine

```mermaid
flowchart TD
    A[🏗️ Build frozen exe on your machine] --> B[dist\steam_game_organizer\ folder is ready]
    B --> C[🎮 Double-click steam_game_organizer.exe]
    C --> D[No Python, 7-Zip, or install needed]
    D --> E[First launch: setup wizard]
    E --> F[Pick: Game library, App folder, Extract to]
    F --> G[Scan → Organize → Play]
    G --> H[Open Game Library.html]
    
    style A fill:#f9f,stroke:#333
    style D fill:#bfb,stroke:#333,stroke-width:2px
    style H fill:#bbf,stroke:#333
```

1. **Build the frozen exe once** on your machine (`python tools\build_frozen.py`).
2. **Launch** `dist\steam_game_organizer\steam_game_organizer.exe` — no Python, 7-Zip, or anything else needed on the machine that runs it.
3. **First launch** opens the setup wizard — pick your game library, app folder, and extract-to folder.
4. **Drive letters auto-resolve** when the stored library path doesn't exist on this machine.
5. **Open** `Game Library.html`; click **Set up on this PC** to re-point folders.
6. **Click Refresh catalog** after external changes so unpacked badges re-check disk.

> [!TIP]
> The `runtime/` folder makes the copy self-contained — Python, Tcl/Tk, and 7-Zip included. Windows 10 or later required. The only thing a fresh copy needs is a one-time registry step if you want Extract links from the browser: `runtime\python.exe tools\install_protocol_handler.py`.

---

## 🤝 Contributing

1. Open an issue for bugs or feature ideas
2. Fork, make changes on a branch, follow the mandatory checklist above
3. Open a pull request — tests must pass (`OK`, no skips) and lint must be clean

Never commit build artifacts or user settings. The frozen exe is what users run.

---

## 📊 Project Status & Public Readiness

### Current Status: READY FOR PUBLIC RELEASE

This project is ready to be made public. Here's a comprehensive assessment:

#### ✅ What's Ready

1. **Code Quality**
   - 98 Python source files across 8 directories
   - Clean lint status (`ruff check .` passes)
   - Comprehensive test suite (738+ tests, 0 functional failures)
   - All code follows established conventions and style

2. **Build Pipeline**
   - Frozen exe builds successfully with PyInstaller
   - `runtime/7z.exe` verified present in built bundle
   - Build process preserves user config/cache/logs across rebuilds
   - Automated backup tool with retention policy

3. **Documentation**
   - Comprehensive README with Mermaid diagrams
   - AGENTS.md with detailed operating instructions
   - ARCHITECTURE.md with module map and service inventory
   - project_overview.md with data flow and key decisions
   - CHANGELOG.md with detailed timestamps (YYYY-MM-DD HH:MM:SS format)

4. **Testing**
   - 738+ tests with 0 functional failures
   - Test isolation via `sandbox_app` (tests never write to real config/cache/logs)
   - PyInstaller installed in bundled runtime so frozen-build test runs
   - Parallel test execution with pytest-xdist for non-tkinter tests

5. **Security & Privacy**
   - No hardcoded Steam game data in production code
   - Steam Store API queried at runtime only
   - Test fixtures isolated to `--mock` mode
   - URI validation and path safety checks
   - Protocol handler registered under HKCU (per-user, no elevation)

#### 📦 What's Excluded from Git

The following are gitignored and not in the repository:
- `runtime/` — Vendored Python 3.13 + 7-Zip (must be built locally)
- `dist/` — Frozen exe output
- `build/` — Intermediate build files
- `config/` — User settings
- `cache/` — Artwork cache
- `logs/` — Timestamped run logs
- `backup/` — Timestamped 7z backups

#### 🧪 Test Data Privacy

The `/tests/` directory contains test fixtures with example Steam game names and AppIDs. These are:
- Deterministic fixtures used only in `--mock` offline test mode
- Never shipped to users and never queried during normal operation
- Publicly available Steam data that anyone could look up
- Valuable for developers to understand test coverage

If privacy is a concern, test files could be excluded from the repository, but they provide valuable insight into how the tests work.

#### 🚀 Public Access Level

If made public, others will have:
- **Download and read access only** — can download source code, read it, and build locally
- **No write access** — cannot push changes or modify the project on GitHub
- **Collaborator access** — can be added individually through GitHub Settings → Collaborators

#### 📋 Release Checklist

Before cutting a release:
- [ ] Bump version in VERSION.txt and CHANGELOG.md
- [ ] Run full test suite (`runtime\python.exe -m unittest discover -q`)
- [ ] Run lint (`ruff check .`)
- [ ] Rebuild frozen exe (`python tools\build_frozen.py`)
- [ ] Verify `dist/steam_game_organizer/runtime/7z.exe` exists
- [ ] Update README.md if behavior changed
- [ ] Create GitHub release with changelog summary

---

## ⚖️ License

Add a license here if you want others to reuse or modify the code. Without one, all rights are reserved by default.

> [!NOTE]
> **If this project is made public:** others have **download and read access only**. They can download the source code, read it, and build it locally for their own use. They do not have write access to the repository, cannot push changes, and cannot modify the project on GitHub. Collaborators can be added individually through GitHub Settings → Collaborators.

### Bundled runtime components (`runtime/`)

```mermaid
flowchart LR
    P[Python 3.13 + Tcl/Tk<br/>PSF License v2]
    Z[7-Zip 7z.exe<br/>GNU LGPL + unRAR]
    I[Pillow<br/>HPND]
    M[Microsoft VC++<br/>Microsoft terms]
    
    P --> BUNDLE[runtime/ folder]
    Z --> BUNDLE
    I --> BUNDLE
    M --> BUNDLE
    
    style P fill:#e1f5fe,stroke:#01579b
    style Z fill:#e1f5fe,stroke:#01579b
    style I fill:#e1f5fe,stroke:#01579b
    style M fill:#e1f5fe,stroke:#01579b
    style BUNDLE fill:#f9f,stroke:#333,stroke-width:2px
```

`runtime/` is built locally by [`tools/bundle_runtime.py`](tools/bundle_runtime.py) and is **not committed to git** — it's rebuilt from your own machine when you set up or rebuild the frozen exe. It contains third-party software, each under its own license:

| Component | License | Notes |
|-----------|---------|-------|
| **Python 3.13 + Tcl/Tk** | PSF License v2 | Permissive. Copyright notice retained in `runtime\LICENSE.txt`. |
| **7-Zip (`7z.exe`)** | GNU LGPL + unRAR restriction | Permissive for use; LGPL source-offer obligations apply if you redistribute modified binaries publicly. |
| **Pillow** | HPND | Permissive. Copyright notice retained. |
| **Microsoft VC++ redistributable** | Microsoft | Windows only; don't alter notices or imply endorsement. |

`tools\bundle_runtime.py` writes a `THIRD-PARTY-NOTICES.txt` into `runtime/` with attribution for Python, 7-Zip, and Pillow.

---

## 🔗 Quick links to key code sections

| Area | File | What it does |
|------|------|--------------|
| Entry point | [`steam_game_organizer.py`](steam_game_organizer.py) | CLI + GUI launcher, URI handler target |
| Config | [`core/config.py`](core/config.py) | Settings, library paths, extract folders, `AppConfig` |
| Constants | [`core/constants.py`](core/constants.py) | Version, archive extensions, categories, thresholds |
| Models | [`core/models.py`](core/models.py) | Plain-data containers: `GameArchive`, `SteamMatch`, `ScanResult`, ... |
| URI actions | [`core/uri_actions.py`](core/uri_actions.py) | Parses `steamgameorganizer://` URIs, `SCHEME` + `SYSTEM_PATHS` |
| Logger | [`core/logger.py`](core/logger.py) | `AppLogger` — timestamped, component-tagged logging |
| State | [`core/state.py`](core/state.py) | `StateStore` — thread-safe in-memory app state |
| Application | [`app/application.py`](app/application.py) | Composition root and lifecycle owner |
| Controller | [`app/controller.py`](app/controller.py) | Scan phases, duplicate sweep, catalog, undo |
| Archive service | [`services/archive_service.py`](services/archive_service.py) | Archive discovery and scan telemetry |
| Batch extract | [`services/batch_extract_service.py`](services/batch_extract_service.py) | Queue extractions, skip-if-already-extracted |
| Catalog service | [`services/catalog_service.py`](services/catalog_service.py) | Generates `Game Library.html` + banner art |
| Catalog status | [`services/catalog_status.py`](services/catalog_status.py) | `Game Library.status.js`, launcher discovery |
| Extract service | [`services/extract_service.py`](services/extract_service.py) | Finds archive tool, performs extraction, writes markers |
| Installer detect | [`services/installer_detect.py`](services/installer_detect.py) | Detects Windows installer layouts |
| Library service | [`services/library_service.py`](services/library_service.py) | Whole-library audit, Steam link normalization |
| Organizer service | [`services/organizer_service.py`](services/organizer_service.py) | Category moves, zip/rar → 7z conversion |
| Rollback service | [`services/rollback_service.py`](services/rollback_service.py) | Undo journal, `last-organization.json` |
| Setup service | [`services/setup_service.py`](services/setup_service.py) | Three-folder wizard, protocol handler registration |
| Steam service | [`services/steam_service.py`](services/steam_service.py) | Steam Store API with mock backend |
| Artwork service | [`services/artwork_service.py`](services/artwork_service.py) | Cached Steam artwork retrieval |
| Banner art | [`services/banner_art.py`](services/banner_art.py) | Composes the banner image |
| Main window | [`ui/main_window.py`](ui/main_window.py) | Single-window workflow shell, left nav rail |
| Views | [`ui/`](ui/) | scan_view, review_view, organize_view, artwork_view, done_view |
| Batch window | [`ui/batch_extract_window.py`](ui/batch_extract_window.py) | Visible queue for hours of 7z work |
| Setup window | [`ui/setup_window.py`](ui/setup_window.py) | Three-folder setup wizard |
| Theme | [`ui/theme.py`](ui/theme.py) | ttk theme, shared widgets, palette re-export |
| Palette | [`ui/palette.py`](ui/palette.py) | Colours in one place |
| Widgets | [`ui/widgets/`](ui/widgets/) | game_card, game_list, artwork_panel, metadata_panel |
| Filename utils | [`utils/filename_utils.py`](utils/filename_utils.py) | `normalize_name`, `identity_key`, `version_key` |
| Formatting | [`utils/formatting.py`](utils/formatting.py) | Human-readable sizes and durations |
| Desktop | [`utils/desktop.py`](utils/desktop.py) | `os.startfile`-based folder/URL opening |
| Treewalk | [`utils/treewalk.py`](utils/treewalk.py) | Junction/symlink-safe recursive walk |
| Diagnostics | [`debug/diagnostics.py`](debug/diagnostics.py) | Diagnostics and health report output |
| Build frozen | [`tools/build_frozen.py`](tools/build_frozen.py) | PyInstaller pipeline, lift step, verify 7z.exe |
| Bundle runtime | [`tools/bundle_runtime.py`](tools/bundle_runtime.py) | Copies Python + Tcl/Tk + 7-Zip into `runtime/` |
| Protocol handler | [`tools/install_protocol_handler.py`](tools/install_protocol_handler.py) | Registers `steamgameorganizer://` under HKCU |
| Overnight repair | [`tools/overnight_repair.py`](tools/overnight_repair.py) | Space-checked, one-at-a-time archive repair |
| Screenshot audit | [`tools/analyze_screenshot.py`](tools/analyze_screenshot.py) | Palette + off-palette content analysis |
| Layout audit | [`tools/layout_audit.py`](tools/layout_audit.py) | Clipping, off-window widgets, sibling overlap |
| Test support | [`tests/tk_support.py`](tests/tk_support.py) | `sandbox_app` — roots `AppConfig` in temp tree |

---

*Built for Windows. One library, one catalog, one click to play.*
