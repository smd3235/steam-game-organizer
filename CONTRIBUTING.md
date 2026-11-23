# Contributing to Steam Game Organizer

Thank you for contributing! This project follows strict rules to keep the codebase maintainable on Windows only.

## Getting Started

1. Fork the repository and create a branch from `main`
2. Install the development toolchain (see [Prerequisites & Setup](#prerequisites--setup))
3. Make your changes following the rules below
4. Run the quality gate: `runtime\python.exe tools\quality_gate.py`
5. Commit and push your branch
6. Open a pull request against `main`

## Prerequisites & Setup

| You want to… | What you need |
|--------------|---------------|
| **Run tests** | Python 3.13 + `runtime\python.exe` |
| **Lint** | `ruff` |
| **Type check** | `mypy` |
| **Security scan** | `bandit` + `pip-audit` |
| **OCR UI tests** | `pytesseract` + Tesseract OCR binary + `pywinauto` + `opencv-python-headless` |
| **Build frozen exe** | Python 3.13 + PyInstaller + 7-Zip |
| **Pre-commit hooks** | `pre-commit` |

Verify your setup:

```powershell
python --version   # Python 3.13.x
ruff --version     # should print a version
7z                 # should print 7-Zip help
```

## The Change Workflow

Every change must follow this checklist **in order**:

| Step | Action | Details |
|------|--------|---------|
| 1 | **Comment** | Add a comment explaining the change in every modified file |
| 2 | **Changelog** | Add a dated entry under `## 9.33` (newest first) |
| 3 | **Docs** | Update `AGENTS.md`, `ARCHITECTURE.md`, `project_overview.md`, or `README.md` if behavior changed |
| 4 | **Lint** | `ruff check .` — must pass |
| 5 | **Tests** | `runtime\python.exe -m pytest tests/ -q -p no:xdist --ignore=tests/test_frozen_build.py --ignore=tests/test_lifecycle.py --ignore=tests/test_artwork_render.py --ignore=tests/test_displayed_data.py --ignore=tests/test_category_evidence_panel_tests.py --ignore=tests/test_review_context_panels.py --ignore=tests/test_render_integrity.py --ignore=tests/test_real_workflow.py --ignore=tests/test_artwork_arriving_as_assets_is_still_artwork.py --ignore=tests/test_ui_geometry.py --ignore=tests/test_worker_updates_reach_the_ui_thread.py --cov=core --cov=services --cov=ui --cov=app --cov=utils` |
| 6 | **Build** | `python tools\build_frozen.py` — if any source code changed |
| 7 | **Commit + push** | `git add` the changed source, docs, and changelog; commit; push |

## Rules

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
| **Scratch files stay in the project** | Put throwaway scripts under `temp\` at the project root (gitignored), and delete them when finished. |

## Comment Style

- **Docstrings** (`"""`) state *what* a module/class/function does and its contract.
- **`#` comments** state *why* a specific line does something (bug, edge case, platform quirk) — inline with implementation.
- Do not convert `#` comments into docstrings; they are not interchangeable.
- Every changed file must include at least one comment explaining what changed and why.

## Quality Gate

Run `runtime\python.exe tools\quality_gate.py` before pushing. It checks:

1. **ruff** — lint
2. **bandit** — security scan (medium+ issues fail)
3. **pip-audit** — dependency vulnerability check
4. **vulture** — dead code scan (advisory only)
5. **mypy** — type check on modified source modules
6. **pytest** — test suite with coverage
7. **OCR UI tests** — captures all screens, verifies text, detects error windows

## Commit Messages

Use conventional style: `type(scope): short summary`.

Types: `feat`, `fix`, `docs`, `build`, `refactor`, `test`, `chore`.

Example: `build: rebuild frozen exe after archive cache changes`

## Pull Requests

- Open a PR from your branch to `main`
- Tests must pass (`OK`, no new skips) and lint must be clean (`ruff check .`) before merging
- Update `CHANGELOG.md` with a dated entry under `## 9.33` before merging
- Do not commit build artifacts (`runtime/`, `dist/`, `build/`, `cache/`, `logs/`, `config/`, `backup/`)

## Project Docs

| File | Purpose |
|------|---------|
| `AGENTS.md` | Operating manual: how to build, test, lint, run, commit, and push on Windows |
| `ARCHITECTURE.md` | Module map and service inventory: what each module does and how they wire together |
| `project_overview.md` | What the app does, its data flow, key decisions, and the catalog page mechanics |
| `README.md` | User-facing install, run, workflow, other-PC, and development-check instructions |
| `CHANGELOG.md` | Dated change log under `## 9.33` (newest first) |

When a change alters behavior, architecture, commands, test counts, or frozen build layout, update the affected doc(s) in the same change — not later.
