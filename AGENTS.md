# Steam Game Organizer — AGENTS.md

[![Steam Game Organizer](https://img.shields.io/badge/Steam%20Game%20Organizer-blue.svg)](CHANGELOG.md)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-green.svg)](README.md)
[![Language: Rust](https://img.shields.io/badge/language-Rust-orange.svg)](https://www.rust-lang.org/)
[![Lint: cargo clippy](https://img.shields.io/badge/lint-cargo%20clippy-important.svg)](Cargo.toml)
[![Tests: cargo test](https://img.shields.io/badge/tests-cargo%20test-success.svg)](src/)

---

## 🗂️ Documentation map

| File | Purpose | Link |
|------|---------|------|
| **AGENTS.md** | Operating manual: build, test, lint, run, commit, push — Windows only | [`AGENTS.md`](AGENTS.md) |
| **ARCHITECTURE.md** | Module map, service inventory, wiring diagrams | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| **project_overview.md** | App purpose, data flow, key decisions, catalog mechanics | [`project_overview.md`](project_overview.md) |
| **README.md** | User-facing install, run, workflow, other-PC instructions | [`README.md`](README.md) |
| **CHANGELOG.md** | Dated change log (newest first) | [`CHANGELOG.md`](CHANGELOG.md) |

**Rule:** when a change alters behavior, architecture, commands, test counts, or build layout, update the affected doc(s) in the same change — not later.

---

## ⚠️ Rules at a Glance

These are non-negotiable. Every change to this project must satisfy all of them.

| Rule | What it means |
|------|---------------|
| **Windows only** | No POSIX-specific code paths. Refuse or raise rather than keep a second implementation. Applies to `std::os::windows` too. |
| **Comment on every change** | Every changed file must include a comment explaining what changed and why. |
| **Push to GitHub on every change** | After commit + local verification, push so the public repo reflects the current state. Never leave work committed locally only. |
| **Clippy clean** | `cargo clippy --all-targets` must report zero new warnings. Fix warnings — do not add `#[allow]` unless the code is a known stub. |
| **Build artifacts** | `target/`, `dist/`, `cache/`, `logs/`, `config/` are build/test outputs — never commit them. |
| **Build in project folder only** | Always run `cargo build`, `cargo check`, `cargo clippy`, `cargo test` from `E:\steam-game-organizer-rust`. **Never** use `--target-dir` pointing outside the project (e.g., temp directories). The release exe must be at `target/release/steam-game-organizer.exe`. |
| **Tests must not pollute repo state** | Rust tests must not write under real `config/`, `cache/`, or `logs/` — use temp dirs. |
| **Atomic writes** | Follow temp-file + atomic rename via `std::fs::rename` for config/state files. |
| **No screenshots left behind** | Delete any `*.png` screenshots created during checks. None in repo root when finished. |
| **Scratch files stay in the project** | Never create temp files outside this repository. Put throwaway scripts under `temp\` at the project root (gitignored), and delete them when finished. The only exception is `docs/screenshots/`, the committed README gallery. |
| **Docs stay accurate** | If a change alters behavior, architecture, commands, test counts, or build layout, update the affected doc(s) in the same change. |

---

## 🛠️ Prerequisites & Setup

### What you need

| You want to… | What you need | How to get it |
|--------------|---------------|---------------|
| **Run the release exe** | Nothing. Self-contained — ships with Rust runtime embedded. | Download latest release from GitHub, or build it yourself. |
| **Run from source** | Rust toolchain. | [rust-lang.org](https://www.rust-lang.org/). |
| **Develop / change code** | Rust (`cargo`, `rustc`, `clippy`). | See Development toolchain below. |

### Development toolchain

1. **Rust** — `cargo`, `rustc`, `clippy`. Required for all source modules. Install from [rust-lang.org](https://www.rust-lang.org/). Verify with `cargo --version` and `rustc --version`.
2. **Git Bash** — [git-scm.com](https://git-scm.com/download/win) (installed with Git). **Required shell for running Rust commands on Windows.** PowerShell interprets Rust's `<`/`>` generics as shell redirection, which breaks commands like `cargo check` and `cargo test`. Git Bash does not have this problem. Do not use PowerShell for cargo commands.

### Verify your setup

Run verification commands in **Git Bash**, not PowerShell:

```bash
cargo --version   # should print a Rust version
rustc --version   # should print a Rust version
```

### Rust lint / test

All Rust modules in `src/` are checked with:

```bash
cargo check        # compile check
cargo clippy --all-targets  # lint
cargo test         # Rust unit tests
```

All commands must be run from the project folder (`E:\steam-game-organizer-rust`). Never use `--target-dir` pointing outside the project.

### Rust crates (Cargo.toml dependencies)

Each module adds the crates it needs to `Cargo.toml` at the project root:

| Crate | Purpose | First used by |
|-------|---------|---------------|
| `serde` | JSON serialization for settings, rollback journal, scan state | `src/core/models.rs`, `src/core/config.rs` |
| `thiserror` | Typed error types (`OrganizerError`, `CancellationError`) | `src/core/errors.rs` |
| `time` | Date parsing for Steam release dates (`release_label`) | `src/core/naming_utils.rs` |
| `lazy_static` | Compiled regexes reused across calls | `src/core/naming_utils.rs` |
| `regex` | Filename normalization tags (`normalize_name`) | `src/core/filename_utils.rs` |
| `walkdir` | Junction-safe recursive directory walk | `src/core/treewalk.rs` |
| `zip` | ZIP archive reading for encryption checks | `src/services/archive_service.rs` |
| `reqwest` | HTTP client for Steam API calls (blocking client for connection pool) | `src/services/extract_service.rs` |
| `winreg` | Windows registry access for .html handler check | `src/services/organizer_service.rs` |
| `egui` + `eframe` | GUI framework for the UI layer | `src/ui/main_window.rs` |
| `clap` | CLI argument parsing for headless binary | `src/bin.rs` |
| `sha2` | SHA-256 hashing for config tamper detection | `src/bin/diag.rs` |
| `image` | Native image preprocessing for OCR screenshots | `src/tools/capture_screens.rs` |

Add a crate only when a converted module actually imports it — do not pre-install the whole list.

---

## ⚡ Testing

All tests are Rust unit tests under `src/`, run with:

```bash
cargo test
```

### Test result

> [!IMPORTANT]
> **Expected:** `OK` with no failures. A skip that is *not* expected is a bug.

### Test hygiene

#### A test must be able to fail

A safety net that is collected but not executed is worse than none, because it is reported as present. When adding a check, confirm it actually ran — `Ran 0 tests` in a module you just wrote is a bug. Every regression is proved by reverting its fix and watching the test fail, then restoring and watching it pass. Record the failure count, not just that it failed.

#### The suite must not write this project's own state

`AppConfig` derives every path it writes from its project root, and `Application` builds one from `Path(__file__).resolve().parents[1]` — this repository. A test that constructs either one the ordinary way inherits the developer's own `config/`, `cache/` and `logs/`. Build windows and configs through temp dirs. Do **not** snapshot the real files and restore them afterwards: two concurrent runs restore each other's writes, which is the defect itself rather than a fix for it.

Rust tests must not write under real `config/`, `cache/`, or `logs/` — use temp dirs.

---

## 🧹 Lint

```bash
cargo clippy --all-targets
```

`Cargo.toml` and clippy lints are the contract. All clippy warnings must be fixed — do not add `#[allow]` to suppress them unless the code is a known stub awaiting future implementation.

---

## 📝 Logging

Each launch writes its own timestamped log file under `logs/` (`organizer-<YYYYMMDD>-<HHMMSS>.log`), so old runs are never overwritten. The last `ROTATED_LOGS` (10) run logs are kept; older ones are removed. Each file rotates by size (`AppLogger.MAX_BYTES` = 5 MB, keeping `.1` and `.2` rolled files).

`core/logger.rs` `AppLogger` supports a level threshold (`set_level`) and optional console output (`console=True`, used for headless CLI mode). `install_excepthook()` routes uncaught exceptions through the logger. All writes are thread-locked and a failed write is swallowed so logging never kills the run.

---

## 🪟 Platform

**Full screen only.** The app maximizes itself on start (`MainWindow._maximize()` uses egui's viewport), and the user runs it full screen.

There is no second environment to keep green. Anything that branches on platform should now raise or return a refusal rather than keep a second implementation.

---

## 🔄 The Change Workflow

Before modifying any module, read `AGENTS.md`, `ARCHITECTURE.md`, and `project_overview.md` for relevant context. Understand the build, logging, and test rules first.

Work through this checklist in order:

| Step | Action | Details |
|------|--------|---------|
| 1 | **Comment** | Add a comment explaining the change in every modified file. See [🏷️ Comment Style](#-comment-style). |
| 2 | **Changelog** | Add a dated entry under `CHANGELOG.md` (newest first). |
| 3 | **Docs** | Update `AGENTS.md`, `ARCHITECTURE.md`, `project_overview.md`, or `README.md` if behavior changed. |
| 4 | **Lint** | `cargo clippy --all-targets` — must pass for Rust `src/` with zero new warnings. Run in Git Bash. |
| 5 | **Tests** | `cargo test` for Rust `src/` — must report `OK` with no new skips. |
| 6 | **Build** | `cargo build --release` — verify `target/release/steam-game-organizer.exe` exists. |
| 7 | **Commit + push** | `git add -A` the changed source, docs, and changelog; commit with a descriptive conventional message; push to GitHub. **Update all affected markdown docs BEFORE pushing.** |

---

## 🏗️ Build — Release Exe

**Build in the project folder only.** Always run `cargo build --release` from `E:\steam-game-organizer-rust`. Never use `--target-dir` pointing outside the project (e.g., `C:\Users\...\Temp\kilo\target`). The release exe must be at `target/release/steam-game-organizer.exe`.

After any code change, build the release exe:

```bash
cargo build --release
```

This produces `target/release/steam-game-organizer.exe` — a self-contained Windows executable with no Python, no PyInstaller, and no external runtime dependencies.

**Distribution:** The exe expects these siblings at runtime:

| Item | Location | Purpose |
|------|----------|---------|
| `steam-game-organizer.exe` | bundle root | The application itself |
| `runtime/7z.exe` | `runtime/` beside exe | 7-Zip for archive extraction (must be provided separately) |
| `assets/` | bundle root | Icon and other assets |
| `config/`, `cache/`, `logs/` | bundle root | Created at runtime by the app |

The exe resolves its project root as `Path(__file__).resolve().parent` and walks it for sibling folders — same layout as a source checkout.

---

## 🔍 Dependency Audit & Quality Gate (Mandatory)

The project includes two built-in verification tools that must run clean before any change is considered complete:

### `--dependency-audit`

Checks every crate in `Cargo.toml` against crates.io for the latest version, and shells out to `cargo audit`, `cargo outdated`, and `cargo deny` (when installed) for known security vulnerabilities (RUSTSEC advisories), outdated versions, and license violations.

```
steam-game-organizer.exe --dependency-audit
```

Exits 0 if all deps are current and no vulnerabilities found; exits 1 with a report if any are outdated or vulnerable.

### `--quality-gate`

Runs the full verification pipeline in one pass:

1. `cargo check`
2. `cargo clippy --all-targets`
3. `cargo test`
4. `cargo build --release`
5. `dependency_audit` (outdated deps + security vulns)

```
steam-game-organizer.exe --quality-gate
```

Exits 0 only if all steps pass and the dependency audit is clean.

### `--system-diagnostics`

Runs all diagnostic tools in one pass:

1. Dependency audit (crates.io + cargo audit/outdated/deny)
2. Library health scan (unidentified/orphaned/duplicate games)
3. Steam match confidence (high/medium/low/none distribution)
4. Archive encryption scan (.zip/.rar/.7z password protection)
5. Duplicate detector (same game, multiple filenames)
6. Crash recovery (temp files, partial extractions, orphaned journals)
7. SteamCMD check (steamcmd + Steam installation status)
8. Installer build readiness (release exe + 7-Zip present)

```
steam-game-organizer.exe --system-diagnostics
```

### `--build-installer`

Builds a Windows installer (.exe) using Inno Setup's ISCC.exe compiler and `installer.iss`. Bundles the release exe, 7-Zip runtime, and assets.

```
steam-game-organizer.exe --build-installer
```

### `--steamcmd-check`

Verifies SteamCMD availability, Steam installation status, and Steam library path.

```
steam-game-organizer.exe --steamcmd-check
```

### `--duplicate-detector <dir>`

Find duplicate archives by normalized name + size.

```
steam-game-organizer.exe --duplicate-detector <dir>
```

### `--library-health-scan <dir>`

Report unidentified/orphaned/duplicate/oversized archives.

```
steam-game-organizer.exe --library-health-scan <dir>
```

### `--archive-encryption-scan <dir>`

Detect encrypted/password-protected archives.

```
steam-game-organizer.exe --archive-encryption-scan <dir>
```

### `--steam-match-confidence <dir>`

Analyze Steam match confidence distribution.

```
steam-game-organizer.exe --steam-match-confidence <dir>
```

### `--crash-recovery <dir>`

Clean up temp/journal/lock files from crashed ops.

```
steam-game-organizer.exe --crash-recovery <dir>
```

### Recommended external tools (install separately)

| Tool | Purpose | Install |
|------|---------|---------|
| `cargo-audit` | Security vulnerability scanning (RUSTSEC) | `cargo install cargo-audit` |
| `cargo-outdated` | Check for outdated crate versions | `cargo install cargo-outdated` |
| `cargo-deny` | License + advisory checking | `cargo install cargo-deny` |
| `cargo-llvm-cov` | Code coverage reporting | `cargo install cargo-llvm-cov` |
| `cargo-watch` | Auto-run tests/lint on file changes | `cargo install cargo-watch` |
| `criterion` | Benchmarking for performance regression detection | add to `Cargo.toml` dev-dependencies |
| PowerShell 7 | Better shell for scripting (replaces 5.1) | `winget install Microsoft.PowerShell` |
| Inno Setup | Windows installer creation (.iss → .exe) | `winget install JRSoftware.InnoSetup` |
| SteamCMD | Steam appinfo queries for match testing | `winget install Valve.SteamCMD` |
| GitHub CLI (`gh`) | GitHub releases, PRs, issues from CLI | `winget install GitHub.cli` |

### Known dependency issue: egui/eframe 0.37 upgrade (resolved)

egui/eframe 0.32 → 0.37.0 was **blocked** by a transitive dependency conflict:
- `wgpu-hal` 30+ requires `windows` crate 0.62
- `gpu-allocator` 0.28+ requires `windows` crate 0.61
- These are incompatible versions (different `windows_core` types)

**Resolved** by switching `eframe` to `default-features = false, features = ["glow"]` only, which avoids pulling in `egui-wgpu`/`wgpu-hal` entirely. The glow (OpenGL) backend is sufficient for the application's needs and avoids the windows crate conflict entirely.

egui/eframe 0.37.0 compiles and runs cleanly with the glow backend.

---

## 🔀 Git / GitHub Workflow

This project lives on GitHub at `https://github.com/smd3235/steam-game-organizer`. The `main` branch is the release line; work happens on feature branches and lands via pull request.

> [!IMPORTANT]
> **Update GitHub on every change.** After any file is changed, committed locally, and verified, push to GitHub so the public repository always reflects the current state. Never leave work committed locally only.

> [!IMPORTANT]
> **Push the full project — never selected files.** Before you push:
> 1. **Update ALL affected markdown docs** (`AGENTS.md`, `ARCHITECTURE.md`, `project_overview.md`, `README.md`, `CHANGELOG.md`) **BEFORE pushing**. If behavior changed, docs changed too — in the same commit.
> 2. **`git add -A`** the entire project — source, docs, changelog, everything. Never push only selected files.
> 3. **Commit** with a descriptive conventional message.
> 4. **`git push origin main`** so GitHub always reflects the current state.

Never leave work committed locally only. Never push source changes without updated docs. Never push docs without source changes. The public repository must always match what runs on your machine.

| Rule | What it means |
|------|---------------|
| **Branch before you change** | Create a branch from `main` for each body of work (`git checkout -b <name>`). Never commit directly to `main` unless it is a trivial docs-only fix. |
| **Commit messages** | Use conventional style: `type(scope): short summary`. Types: `feat`, `fix`, `docs`, `build`, `refactor`, `test`, `chore`. Example: `build: release exe after archive cache changes`. |
| **Changelog with every commit** | Add a dated entry to the top of `CHANGELOG.md` at the same time as the code change. Never defer. |
| **Push regularly** | `git push origin <branch>` so your work is backed up on GitHub. Do not force-push `main`. |
| **Pull requests** | Open a PR from your branch to `main`. Tests must pass (`OK`, no skips) and lint must be clean (`cargo clippy --all-targets`) before merging. |
| **Do not commit build artifacts** | `target/`, `dist/`, `build/`, `runtime/`, `cache/`, `logs/`, `config/`, `backup/` are excluded by `.gitignore`. Never add them. |

---

## 📐 Keeping Project Docs Accurate

These four files are the project's map of itself. If a reader acts on them, they must match the code:

| File | Purpose | Link |
|------|---------|------|
| `AGENTS.md` | How to build, test, lint, and run on Windows (the operating instructions) | [`AGENTS.md`](AGENTS.md) |
| `ARCHITECTURE.md` | What each module does and how they wire together (the service inventory) | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| `project_overview.md` | What the app does, its data flow, key decisions, and the catalog page mechanics | [`project_overview.md`](project_overview.md) |
| `README.md` | User-facing run, workflow, other-PC, and development-check instructions | [`README.md`](README.md) |
| **CHANGELOG.md** | Dated change log (newest first) | [`CHANGELOG.md`](CHANGELOG.md) |

> [!IMPORTANT]
> **Rule:** when a change alters behavior, architecture, commands, test counts, or build layout, update the affected doc(s) in the same change — not later.

> [!IMPORTANT]
> **MANDATORY — add a changelog note for every change.** `CHANGELOG.md` is the project's record of what changed and when. Every change to code, config, tools, or docs gets a dated entry under `CHANGELOG.md`, formatted as:

```markdown
### YYYY-MM-DD — one-line summary of the change
```

A bullet list may follow, naming the files touched and the behavior before/after. Add entries to the **top** of `CHANGELOG.md` in chronological order (newest first). The version number only moves when a release is cut; until then everything lands under the unreleased section. If you changed it, it goes in the changelog.

---

## ✅ Definition of Done (Mandatory)

Before considering any task complete, verify every rule in [**Rules at a Glance**](#-rules-at-a-glance) plus:

- [ ] All source files changed have a comment explaining what changed and why.
- [ ] `CHANGELOG.md` has a new dated entry under `CHANGELOG.md` (newest first).
- [ ] `AGENTS.md`, `ARCHITECTURE.md`, `project_overview.md`, or `README.md` updated if behavior, architecture, commands, test counts, or build layout changed.
- [ ] `cargo clippy --all-targets` passes.
- [ ] `cargo test` reports `OK` with no new skips.
- [ ] `cargo build --release` produces `target/release/steam-game-organizer.exe`.
- [ ] `steam-game-organizer.exe --quality-gate` passes all steps (check, clippy, test, build, dependency audit).
- [ ] `steam-game-organizer.exe --dependency-audit` reports all clean (no outdated deps, no vulnerabilities).
- [ ] `steam-game-organizer.exe --system-diagnostics` reports all checks passed (or documents known issues).
- [ ] No `*.png` screenshots left in repo root; no writes to real `config/`, `cache/`, or `logs/` (use temp dirs in tests).
- [ ] Committed and pushed to GitHub so the public repository reflects the change.

**Quick verification after any change:** `cargo clippy --all-targets` passes, `cargo test` reports `OK` with no new skips, each doc still describes what the code actually does, and `CHANGELOG.md` has a new dated entry for the change.

---

## 🏷️ Comment Style

- **Docstrings** (`///`) state *what* a module/class/function does and its contract.
- **`//` comments** (Rust `//`) state *why* a specific line does something (bug, edge case, platform quirk) — inline with implementation.
- Do not convert `//` comments into docstrings; they are not interchangeable.
- Every changed file must include at least one comment explaining what changed and why.

**Good** (explains *why*, not *what*):

```rust
// 2026-11-25: Removed '.*$' from RELEASE_TAG — it ate everything after the tag name,
// so 'tenoke-ball.x.pit.risen.ballbylon' lost its game title and returned empty.
value = RELEASE_TAG.sub("", value);
```

**Bad** (just restates the code):

```rust
// Add 1 to i
i = i + 1;
```

---

## 🔍 Steam Match Troubleshooting

When an archive doesn't match a Steam game:

1. **Check the archive filename** — `normalize_name()` strips release groups (tenoke, dodi, fitgirl, etc.) from both start and end. If the game title isn't recognized, the match will fail.
2. **Check the Steam search** — the app queries Steam's storesearch API with multiple name variants (original, "X, The", leading-article stripped, edition words stripped, subtitle stripped).
3. **Check for an internal AppID** — archives with `steam_settings/steam_appid.txt` or `appmanifest_*.acf` are matched by AppID first, before any text search.
4. **Use the "Wrong Match" button** on the review screen if Steam identified the wrong game — this clears the Steam match and lets you re-search.
5. **Use "Search Again"** to retry with a different search term.
6. **Check the logs** — `logs/` shows every Steam API call and its result. Look for `Steam identification required` warnings.

Common naming patterns that match:
- `Game Name - 12345.zip` (AppID in filename)
- `Game.Name.12345.rar` (AppID in filename)
- `Game [12345].7z` (AppID in filename)
- `tenoke-ball.x.pit.risen.ballbylon.zip` (release group stripped from start)
- `Ultimate Edition: Game Name.zip` (leading edition words stripped)
- `Game Name - Subtitle.zip` (subtitle stripped)

---

## 📦 Release Process (Summary)

When you're ready to cut a release:

1. **Update `CHANGELOG.md`** — move all unreleased entries under a new release heading with a date.
2. **Build the release exe** — `cargo build --release`.
3. **Create a GitHub Release** — tag the release, paste the changelog notes, upload the release exe zip.
4. **Start a fresh `## Unreleased` section** in `CHANGELOG.md` for new changes.

Note: version numbers (`9.33` etc.) have been removed from the codebase; releases are identified by date tag only.
