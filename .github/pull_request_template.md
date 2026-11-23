## Description

Brief description of the change.

## Type of change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Documentation update
- [ ] Build / frozen exe change
- [ ] Chore / maintenance

## Checklist

- [ ] I have read `AGENTS.md` and understand the project rules
- [ ] Every changed source file includes a comment explaining what changed and why
- [ ] `CHANGELOG.md` has a new dated entry (newest first)
- [ ] Affected docs (`AGENTS.md`, `ARCHITECTURE.md`, `project_overview.md`, `README.md`) updated if behavior, architecture, commands, test counts, or frozen build layout changed
- [ ] `ruff check .` passes
- [ ] `runtime\python.exe -m pytest tests/ -q -p no:xdist --ignore=tests/test_frozen_build.py --ignore=tests/test_lifecycle.py --ignore=tests/test_the_entry_point_opens_the_wizard.py --ignore=tests/test_artwork_render.py --ignore=tests/test_displayed_data.py --ignore=tests/test_category_evidence_panel_tests.py --ignore=tests/test_render_integrity.py --ignore=tests/test_pytest_mock_and_freezegun.py --cov=core --cov=services --cov=ui --cov=app --cov=utils` reports `OK` with no new skips
- [ ] `tools\quality_gate.py` passes (ruff, bandit, pip-audit, mypy, pytest, OCR)
- [ ] Frozen exe rebuilt with `python tools\build_frozen.py` (if any source changed)
- [ ] No `*.png` screenshots left in repo root
- [ ] No writes to real `config/`, `cache/`, or `logs/` (tests use `tests/tk_support.py:sandbox_app`)
- [ ] Committed and pushed to the feature branch

## Screenshots (if UI changed)

Attach before/after screenshots if the change affects any app screen.
