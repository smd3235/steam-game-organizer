# Steam Game Organizer — AGENTS.md

[![Version 9.33](https://img.shields.io/badge/version-9.33-blue.svg)](CHANGELOG.md)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-green.svg)](README.md)
[![Lint: ruff](https://img.shields.io/badge/lint-ruff-important.svg)](ruff.toml)
[![Tests: unittest](https://img.shields.io/badge/tests-unittest-success.svg)](tests/)

> [!IMPORTANT]
> **Windows is the only platform.** There is no second environment to keep green. The Flatpak/SteamOS target is gone. Anything that branches on platform should raise or return a refusal rather than keep a second implementation.

---

## 📖 Table of contents

| If you want to… | Go to section |
|-----------------|---------------|
| Read this doc first (start here) | [⚠️ Rules at a Glance](#-rules-at-a-glance) |
| Set up the dev environment | [🛠️ Prerequisites & Setup](#-prerequisites--setup) |
| Make a code change (step-by-step) | [🔄 The Change Workflow](#-the-change-workflow) |
| Rebuild the frozen exe | [🏗️ Build — Frozen Exe Pipeline](#-build--frozen-exe-pipeline) |
| Understand the bundled runtime | [📦 The Bundled Runtime](#-the-bundled-runtime) |
| Understand logging | [📝 Logging](#-logging) |
| Understand test hygiene | [🧪 Testing](#-testing) |
| Run lint checks | [🧹 Lint](#-lint) |
| Capture/delete screenshots | [📸 Screenshots: capture, analyse, delete](#-screenshots-capture-analyse-delete) |
| Run long-running commands | [⏱️ Long-Running Commands](#-long-running-commands) |
| Git/GitHub workflow | [🔀 Git / GitHub Workflow](#-git--github-workflow) |
| Keep docs accurate | [📐 Keeping Project Docs Accurate](#-keeping-project-docs-accurate) |
| Verify a task is complete | [✅ Definition of Done (Mandatory)](#-definition-of-done-mandatory) |
| Write comments | [🏷️ Comment Style](#-comment-style) |
| See how docs relate to each other | [🗂️ Documentation Map](#-documentation-map) |

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

**Rule:** when a change alters behavior, architecture, commands, test counts, or frozen build layout, update the affected doc(s) in the same change — not later. See [📐 Keeping Project Docs Accurate](#-keeping-project-docs-accurate).

---

## ⚠️ Rules at a Glance

These are the non-negotiable rules. Every change to this project must satisfy all of them. They are referenced by [The Change Workflow](#-the-change-workflow) and [Definition of Done](#-definition-of-done-mandatory) rather than repeated there.

| Rule | What it means |
|------|---------------|
| **Windows only** | No POSIX-specific code paths. Refuse or raise rather than keep a second implementation. |
| **Comment on every change** | Every changed file must include a comment explaining what changed and why. |
| **Push to GitHub on every change** | After commit + local verification, push so the public repo reflects the current state. Never leave work committed locally only. |
| **Changelog with every change** | Add a dated entry to the top of `## 9.33` in `CHANGELOG.md` at the same time as the code change. Never defer. |
| **Frozen exe required** | If you change any source code, rebuild with `python tools\build_frozen.py` before considering complete. |
| **Never edit build artifacts** | `dist/`, `build/`, `runtime/` are read-only outputs. Treat them as vendored, never modify. |
| **Tests must not pollute repo state** | Use `tests/tk_support.py:sandbox_app` for tests that create `AppConfig`/windows/writes. Never write to real `config/`, `cache/`, or `logs/`. |
| **Atomic writes** | Follow temp-file + `os.replace` with retries for config/state files. |
| **No screenshots left behind** | Delete any `*.png` screenshots created during checks. None in repo root when finished. |
| **Docs stay accurate** | If a change alters behavior, architecture, commands, test counts, or frozen build layout, update the affected doc(s) in the same change. |

---

## 🛠️ Prerequisites & Setup

### What you need

| You want to… | What you need | How to get it |
|--------------|---------------|---------------|
| **Run the frozen exe** (`dist\steam_game_organizer\steam_game_organizer.exe`) | **Nothing.** Ships with Python 3.13, Tcl/Tk, and 7-Zip bundled inside `runtime/`. | Download latest release from GitHub, or build it yourself. |
| **Run from source** (`runtime\python.exe steam_game_organizer.py`) | Python 3.13 (the bundled runtime works if already built). | [python.org](https://www.python.org/downloads/windows/) — install for all users, check "Add Python to PATH". |
| **Develop / change code** | Python 3.13 + `ruff` + `PyInstaller`. | See Development toolchain below. |
| **Build frozen exe / bundle runtime** | Python 3.13 + 7-Zip + PyInstaller. | See [🏗️ Build](#-build--frozen-exe-pipeline) and [📦 Bundled Runtime](#-the-bundled-runtime). |

### Development toolchain

1. **Python 3.13** — [python.org](https://www.python.org/downloads/windows/). During install, check **"Add Python to PATH"** and **"Install for all users"**.
2. **ruff** — `pip install ruff`
3. **PyInstaller** — `runtime\python.exe -m pip install pyinstaller` (installed inside the bundled runtime)
4. **7-Zip** — [7-zip.org](https://www.7-zip.org/download.html). Required for `runtime\7z.exe` and for building the frozen exe. Install to the default location (`C:\Program Files\7-Zip`) so `tools\bundle_runtime.py` can find it automatically.

### Verify your setup

```powershell
python --version   # should be Python 3.13.x
ruff --version     # should print a version
7z                 # should print 7-Zip help
```

---

## 🔄 The Change Workflow

Before modifying any module, read `AGENTS.md`, `ARCHITECTURE.md`, and `project_overview.md` for relevant context. Understand the frozen build, logging, and test hygiene rules first.

Work through this checklist in order:

| Step | Action | Details |
|------|--------|---------|
| 1 | **Comment** | Add a comment explaining the change in every modified file. See [🏷️ Comment Style](#-comment-style). |
| 2 | **Changelog** | Add a dated entry under `## 9.33` (newest first). |
| 3 | **Docs** | Update `AGENTS.md`, `ARCHITECTURE.md`, `project_overview.md`, or `README.md` if behavior changed. |
| 4 | **Lint** | `ruff check .` — must pass. See [🧹 Lint](#-lint). |
| 5 | **Tests** | `runtime\python.exe -m unittest discover -q` — must report `OK` with no new skips. See [🧪 Testing](#-testing). |
| 6 | **Build** | `python tools\build_frozen.py` — verify `dist/steam_game_organizer/runtime/7z.exe` exists. See [🏗️ Build](#-build--frozen-exe-pipeline). |
| 7 | **Commit + push** | `git add` the changed source, docs, and changelog; commit with a descriptive message; push to GitHub. See [🔀 Git / GitHub Workflow](#-git--github-workflow). |

---

## 🏗️ Build — Frozen Exe Pipeline

After any code change, rebuild the exe:

```powershell
python tools\build_frozen.py
```

> [!IMPORTANT]
> **MANDATORY:** Always rebuild the exe after any code change. The user runs only the frozen exe in `dist/steam_game_organizer/`, never from source.

`tools\build_frozen.py` runs PyInstaller on `steam_game_organizer.spec`, then moves `core/`, `services/`, `ui/`, `utils/`, `app/`, `debug/`, `tools/`, `assets/`, `runtime/` out of `_internal/` into the bundle root — because `steam_game_organizer.py` resolves its project root as `Path(__file__).resolve().parent` and walks it for those siblings. Leaving them in `_internal/` puts `runtime/7z.exe` one folder out of reach and every extraction reports no archiver.

- Before wiping the old bundle it backs up `config/`, `cache/`, `logs/` into a temp dir and restores them after, so user settings, artwork cache, and logs survive a rebuild. If there was no previous bundle it seeds `config/settings.json` from the source tree.
- It retries `rmtree` up to 5 times because Windows Defender or an indexer can hold a DLL open long enough to fail the first pass, and clears read-only attributes on locked files. It verifies `runtime/7z.exe` exists in the bundle before reporting success.
- The spec is a **onedir** build (`console=False`, `exclude_binaries=True`). Do not change to onefile — a onefile build repacks the interpreter into a temp folder on every launch.

---

## 📦 The Bundled Runtime

`runtime/` at the project root is a **vendored product, not this project's code**: `tools\bundle_runtime.py` copies Python 3.13 (with Tcl/Tk) and a 7-Zip into it from the machine's own installs. The same tree ships inside the frozen bundle as `dist/steam_game_organizer/runtime/`.

> [!TIP]
> **It must ship.** Nothing a user's PC needs is installed, so a `.gitignore` entry or a build step that drops `runtime/` breaks every copied folder. `.gitignore` deliberately has no entry for it.

| Item | Requirement |
|------|-------------|
| `runtime/7z.exe` | Required. `build_frozen.py` verifies it exists before reporting success. |
| Lint / version scan | Excluded (`runtime` and `dist`). `ruff.toml` excludes them; `tests/test_release_structure.py` skips them in `NOT_SOURCE`. |
| Interpreter path | The bundled `python313._pth` makes `sys.path` exactly what the file says. Any new entry point or tool meant to run under the bundled interpreter must insert its own folder into `sys.path`, or it dies with `ModuleNotFoundError`. |

---

## 📝 Logging

Each launch writes its own timestamped log file under `logs/` (`organizer-<VERSION>-<YYYYMMDD>-<HHMMSS>.log`), so old runs are never overwritten. The last `ROTATED_LOGS` (10) run logs are kept; older ones are removed. Each file rotates by size (`AppLogger.MAX_BYTES` = 5 MB, keeping `.1` and `.2` rolled files).

`core/logger.py` `AppLogger` supports a level threshold (`set_level`) and optional console output (`console=True`, used for headless CLI mode). `install_excepthook()` routes uncaught exceptions through the logger. All writes are thread-locked and a failed write is swallowed so logging never kills the run.

---

## 🪟 Platform

**Full screen only.** The app maximizes itself on start (`MainWindow._maximize()` uses `state('zoomed')`), and the user runs it full screen.

The geometry tests intentionally run at fixed non-fullscreen sizes (`1280x800`, `1100x680`) — that is how they verify the app works at `minsize()`, which is reachable. They unzoom the window first (`root.state('normal')`) because on Windows the zoomed state sticks and `geometry()` is otherwise ignored. **Do not remove those fixed sizes from the geometry tests; they are the point.** The "full screen only" rule is about production behavior, not about the geometry tests.

There is no second environment to keep green. Anything that branches on platform should now raise or return a refusal rather than keep a second implementation.

---

## 🧪 Testing

### Test result

> [!IMPORTANT]
> **Expected:** `OK` with no skips. PyInstaller is installed in the bundled runtime (`runtime\Lib\site-packages`) so the frozen-build layout check runs. A skip that is *not* expected is a bug: find the dependency it cannot satisfy and make it report the condition deterministically, or fail with a message naming the cause. A missing tkinter is a broken install and `tests/test_ui_geometry.py` raises rather than skips.

### Test hygiene

#### A test must be able to fail

A safety net that is collected but not executed is worse than none, because it is reported as present. When adding a check, confirm it actually ran — `Ran 0 tests` in a module you just wrote is a bug. Every regression is proved by reverting its fix and watching the test fail, then restoring and watching it pass. Record the failure count, not just that it failed.

Two traps this project has hit:

- **A colour option that the widget never paints.** Tk leaves every widget carrying `SystemButtonFace` for `highlightbackground` and `SystemDisabledText` for `disabledforeground`. Read `highlightthickness` before flagging a highlight, and skip state colours on a widget class that has no such state.
- **A check that reads the wrong thing.** Asserting on a widget's text when the value lives in a tag will never see it. `tag_names()` is where a Tk colour lives.

Assert on the parsed code (`ast`), not the file text: comments are not in the AST, which is the point.

#### Test doubles must be runnable on the host

A fake `7z` written as a shebang script with no extension is invisible to `shutil.which()` on Windows and cannot be started if found. Use `tests/test_services.py:_write_stub` rather than writing scripts directly.

#### The suite must not write this project's own state

`AppConfig` derives every path it writes from its project root, and `Application` builds one from `Path(__file__).resolve().parents[1]` — this repository. A test that constructs either one the ordinary way inherits the developer's own `config/`, `cache/` and `logs/`. Build windows and configs through `tests/tk_support.py:sandbox_app`, which roots the `AppConfig` in a temporary tree. Do **not** snapshot the real files and restore them afterwards: two concurrent runs restore each other's writes, which is the defect itself rather than a fix for it.

`tests/test_project_state_guard.py` snapshots every file under `config/`, exercises `AppConfig`, `save()`, `remember_category()`, the scan summary, the undo journal and a real window against a temporary tree, and fails if any byte or mtime moved.

#### Test logs never touch the real logs directory

`tests/__init__.py` sets `STEAM_GAME_ORGANIZER_TEST_LOG` to `<project root>/logs/test/organizer-<VERSION>-TEST-<timestamp>.log` so every `AppConfig` created during a test run writes there instead of the real `logs/` directory. Test runs never pollute the user's log history, and real runs are easy to tell apart. The env var is set with `setdefault` so an explicit export still takes precedence.

---

## 🧹 Lint

```powershell
ruff check .
```

`ruff.toml` is the contract, and each ignored rule carries its reason in the file.

- E701/E702 are not selected. Semicolons are this codebase's house style; enabling them reported 2456 sites that are the style rather than a fault.
- The `match` identifier parser bug (ruff 0.16.10) was cleared in 9.10 by renaming locals to `steam_match`; `ruff.toml` documents the ignore as historical. Do not reintroduce a bare `match=` assignment expecting the six phantom reports to vanish.

---

## 📸 Screenshots: capture, analyse, delete

Visual checks are real and useful, but a screenshot left on disk is a stale picture of a UI that has since changed. Always delete screenshots in the same step they are used. Capture, analyse, delete — never leave one for "later". There must be no `*.png` in the project root when work is finished.

```powershell
runtime\python.exe tools\analyze_screenshot.py _shot_1.png   # palette + off-palette content analysis
runtime\python.exe tools\layout_audit.py                     # clipping, off-window widgets, sibling overlap
```

Run both at every window size the app permits — the minimum included, because `minsize()` makes small sizes reachable. `tests/test_contrast.py` reports WCAG contrast ratios for every colour pair the app paints; run it after any theme change.

Hard-coded widget heights are the usual cause of off-window controls at short window heights. Prefer flexible rows with a smaller floor over fixed heights.

---

## ⏱️ Long-Running Commands

A foreground shell call blocks until it finishes. Anything whose duration is not known in advance must be a tracked background process, not a bigger timeout — a raised timeout only decides who gives up first.

> [!WARNING]
> **Never sweep the real library in the foreground.** The real library holds multi-gigabyte archives, and `tools\verify_archives.py` runs `7z t` over every one of them — hours of work.

- Is this one archive intact? Pass one path.
- Does the library hold up? A background job, started deliberately.

Scope the work before starting it. The full suite is ~80s — short enough to run in the foreground deliberately, long enough to be a background job once several are queued, but not both at once, and not as one giant chained command that also does unrelated work afterwards. Keep verification separate from reporting so a completed check is visible before the next one starts.

---

## 🔀 Git / GitHub Workflow

This project lives on GitHub at `https://github.com/smd3235/steam-game-organizer`. The `main` branch is the release line; work happens on feature branches and lands via pull request.

> [!IMPORTANT]
> **Update GitHub on every change.** After any file is changed, committed locally, and verified, push to GitHub so the public repository always reflects the current state. Never leave work committed locally only.

| Rule | What it means |
|------|---------------|
| **Branch before you change** | Create a branch from `main` for each body of work (`git checkout -b <name>`). Never commit directly to `main` unless it is a trivial docs-only fix. |
| **Commit messages** | Use conventional style: `type(scope): short summary`. Types: `feat`, `fix`, `docs`, `build`, `refactor`, `test`, `chore`. Example: `build: rebuild frozen exe after archive cache changes`. |
| **Changelog with every commit** | Add a dated entry to the top of `## 9.33` in `CHANGELOG.md` at the same time as the code change. Never defer. |
| **Push regularly** | `git push origin <branch>` so your work is backed up on GitHub. Do not force-push `main`. |
| **Pull requests** | Open a PR from your branch to `main`. Tests must pass (`OK`, no skips) and lint must be clean (`ruff check .`) before merging. |
| **Do not commit build artifacts** | `runtime/`, `dist/`, `build/`, `cache/`, `logs/`, `config/`, `backup/` are excluded by `.gitignore`. Never add them. |

---

## 📐 Keeping Project Docs Accurate

These four files are the project's map of itself. If a reader acts on them, they must match the code:

| File | Purpose |
|------|---------|
| `AGENTS.md` | How to build, test, lint, and run on Windows (the operating instructions) |
| `ARCHITECTURE.md` | What each module does and how they wire together (the service inventory) |
| `project_overview.md` | What the app does, its data flow, key decisions, and the catalog page mechanics |
| `README.md` | User-facing run, workflow, other-PC, and development-check instructions |

> [!IMPORTANT]
> **Rule:** when a change alters behavior, architecture, commands, test counts, or frozen build layout, update the affected doc(s) in the same change — not later.

> [!IMPORTANT]
> **MANDATORY — add a changelog note for every change.** `CHANGELOG.md` is the project's record of what changed and when. Every change to code, config, tools, or docs gets a dated entry under the current development version (right now `## 9.33`), formatted as:

```markdown
### YYYY-MM-DD — one-line summary of the change
```

A bullet list may follow, naming the files touched and the behavior before/after. Add entries to the **top** of the `## 9.33` section in chronological order (newest first). The version number only moves when a release is cut; until then everything lands under the unreleased section. If you changed it, it goes in the changelog.

---

## ✅ Definition of Done (Mandatory)

Before considering any task complete, verify every rule in [**Rules at a Glance**](#-rules-at-a-glance) plus:

- [ ] All source files changed have a comment explaining what changed and why.
- [ ] `CHANGELOG.md` has a new dated entry under `## 9.33` (newest first).
- [ ] `AGENTS.md`, `ARCHITECTURE.md`, `project_overview.md`, or `README.md` updated if behavior, architecture, commands, test counts, or frozen build layout changed.
- [ ] `ruff check .` passes.
- [ ] `runtime\python.exe -m unittest discover -q` reports `OK` with no new skips (PyInstaller is installed in the bundled runtime so the frozen-build test runs).
- [ ] If any source code changed, rebuilt the exe with `python tools\build_frozen.py`.
- [ ] No `*.png` screenshots left in repo root; no writes to real `config/`, `cache/`, or `logs/` (use `tests/tk_support.py:sandbox_app` in tests).
- [ ] Committed and pushed to GitHub so the public repository reflects the change.

**Quick verification after any change:** `ruff check .` passes, `runtime\python.exe -m unittest discover -q` reports `OK`, each doc still describes what the code actually does, and `CHANGELOG.md` has a new dated entry for the change.

---

## 🏷️ Comment Style

- **Docstrings** (`"""`) state *what* a module/class/function does and its contract.
- **`#` comments** state *why* a specific line does something (bug, edge case, platform quirk) — inline with implementation.
- Do not convert `#` comments into docstrings; they are not interchangeable.
- Every changed file must include at least one comment explaining what changed and why.

---
