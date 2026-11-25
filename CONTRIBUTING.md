# Contributing to Steam Game Organizer

Thank you for contributing! This project follows strict rules to keep the codebase maintainable on Windows only.

## Getting Started

1. Fork the repository and create a branch from `main`
2. Install the development toolchain (see [Prerequisites & Setup](#prerequisites--setup))
3. Make your changes following the rules below
4. Run the quality gate: `cargo clippy --all-targets && cargo test`
5. Commit and push your branch
6. Open a pull request against `main`

## Prerequisites & Setup

| You want to… | What you need | How to get it |
|--------------|---------------|---------------|
| **Run the release exe** | Nothing — self-contained `.exe` | Download from GitHub Releases |
| **Run from source** (`cargo run`) | Rust toolchain | https://www.rust-lang.org/ |
| **Develop / change code** | Rust (`cargo`, `rustc`, `clippy`) | Install from rust-lang.org |

Verify your setup:

```powershell
cargo --version   # should print a Rust version
rustc --version   # should print a Rust version
```

## 7-Zip Requirement

The app uses 7-Zip (`7z.exe`) for archive extraction. It is **not** bundled in
source control — you must provide it yourself for local development:

1. Download 7-Zip from https://www.7-zip.org/download.html
2. Install to `C:\Program Files\7-Zip\` (default) or place `7z.exe` at `tools/7z.exe`
3. The Rust code finds 7z via `PATH` then falls back to known install locations

For releases, `7z.exe` is bundled with its LGPL license (see `tools/7z-license.txt`).

## The Change Workflow

Every change must follow this checklist **in order**:

| Step | Action | Details |
|------|--------|---------|
| 1 | **Comment** | Add a comment explaining the change in every modified file |
| 2 | **Changelog** | Add a dated entry to `CHANGELOG.md` (newest first) |
| 3 | **Docs** | Update `AGENTS.md`, `ARCHITECTURE.md`, `project_overview.md`, or `README.md` if behavior changed |
| 4 | **Lint** | `cargo clippy --all-targets` — must pass |
| 5 | **Tests** | `cargo test` — must report `OK` with no failures |
| 6 | **Build** | `cargo build --release` — verify `target/release/steam-game-organizer.exe` exists |
| 7 | **Commit + push** | `git add -A` the changed source, docs, and changelog; commit; push |

## Rules

| Rule | What it means |
|------|---------------|
| **Windows only** | No POSIX-specific code paths. Refuse or raise rather than keep a second implementation. |
| **Comment on every change** | Every changed file must include a comment explaining what changed and why. |
| **Push to GitHub on every change** | After commit + local verification, push so the public repo reflects the current state. Never leave work committed locally only. |
| **Changelog with every change** | Add a dated entry to the top of `CHANGELOG.md` at the same time as the code change. Never defer. |
| **Never commit build artifacts** | `target/`, `dist/`, `runtime/`, `cache/`, `logs/`, `config/`, `backup/` are excluded by `.gitignore`. |
| **Tests must not pollute repo state** | Rust tests must not write under real `config/`, `cache/`, or `logs/` — use temp dirs. |
| **Atomic writes** | Follow temp-file + atomic rename via `std::fs::rename` for config/state files. |
| **No screenshots left behind** | Delete any `*.png` screenshots created during checks. None in repo root when finished. |
| **Scratch files stay in the project** | Put throwaway scripts under `temp\` at the project root (gitignored), and delete them when finished. |

## Comment Style

- **Docstrings** (`///`) state *what* a module/class/function does and its contract.
- **`//` comments** state *why* a specific line does something (bug, edge case, platform quirk) — inline with implementation.
- Do not convert `//` comments into docstrings; they are not interchangeable.
- Every changed file must include at least one comment explaining what changed and why.

## Release Process

When you're ready to cut a release:

1. **Update `CHANGELOG.md`** — move all unreleased entries under a new release heading with a date.
2. **Build the release bundle** — `.\tools\release.ps1` builds the exe and creates `steam-game-organizer-release.zip`.
3. **Create a GitHub Release** — tag the release, paste the changelog notes, upload the release zip.
4. **Start a fresh `## Unreleased` section** in `CHANGELOG.md` for new changes.

The release zip contains:
- `steam-game-organizer.exe` — the self-contained Rust application
- `runtime/7z.exe` — 7-Zip for archive extraction (LGPL, see `runtime/7z-license.txt`)
- `assets/` — icon and other assets
- `AGENTS.md`, `ARCHITECTURE.md`, `README.md`, `CHANGELOG.md`, `LICENSE` — project docs

Note: `config/`, `cache/`, `logs/` are created at runtime and are not included in the release.

## GitHub Actions CI

Every push and pull request runs:
1. `cargo check` — compile check
2. `cargo clippy --all-targets` — lint
3. `cargo test` — unit tests

When a GitHub Release is published, the workflow also builds and uploads `steam-game-organizer-release.zip` as a release asset.

## Commit Messages

Use conventional style: `type(scope): short summary`.

Types: `feat`, `fix`, `docs`, `build`, `refactor`, `test`, `chore`.

Example: `feat: implement archive repacking in organizer_service`

## Pull Requests

- Open a PR from your branch to `main`
- Tests must pass (`OK`, no new skips) and lint must be clean (`cargo clippy --all-targets`) before merging
- Update `CHANGELOG.md` with a dated entry before merging
- Do not commit build artifacts (`target/`, `dist/`, `runtime/`, `cache/`, `logs/`, `config/`, `backup/`)

## Project Docs

| File | Purpose |
|------|---------|
| `AGENTS.md` | Operating manual: how to build, test, lint, run, commit, and push on Windows |
| `ARCHITECTURE.md` | Module map and service inventory: what each module does and how they wire together |
| `project_overview.md` | What the app does, its data flow, key decisions, and the catalog page mechanics |
| `README.md` | User-facing install, run, workflow, other-PC, and development-check instructions |
| `CHANGELOG.md` | Dated change log (newest first) |

When a change alters behavior, architecture, commands, test counts, or build layout, update the affected doc(s) in the same change — not later.