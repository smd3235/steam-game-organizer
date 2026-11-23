# Release Process — v9.33

This document describes how to cut a release of Steam Game Organizer. It covers version bumps, CHANGELOG promotion, frozen exe builds, GitHub Release creation, and post-release steps.

## When to Cut a Release

Cut a release when:

- A set of user-facing changes has accumulated under `## 9.33` in `CHANGELOG.md`
- A bug fix or feature is ready for users to download
- You want to tag a stable point in `main`

The app version stays at `9.33` until a release is cut. All changes between releases are logged under the current development version. When you cut a release:

1. Bump the version number (e.g. `9.33` → `9.34`)
2. Create a new `## 9.34` section at the top of `CHANGELOG.md`
3. Move all unreleased `## 9.33` notes under `## 9.33` (they become the release notes)
4. Start a fresh `## 9.34` section for new changes

## Release Checklist

### Before Cutting

- [ ] All changes are committed and pushed to `main`
- [ ] `CHANGELOG.md` has a dated entry for every change under `## 9.33`
- [ ] `ruff check .` passes
- [ ] `runtime\python.exe tools\quality_gate.py` passes (ruff, bandit, pip-audit, vulture, mypy, pytest, OCR)
- [ ] Frozen exe builds successfully: `python tools\build_frozen.py`
- [ ] `dist\steam_game_organizer\runtime\7z.exe` exists
- [ ] The frozen exe launches and runs on a clean Windows machine

### Cutting the Release

1. **Bump the version**

   Update `VERSION.txt` and `core/constants.py` (`VERSION` constant) to the new version number (e.g. `9.34`).

2. **Update CHANGELOG.md**

   - Create a new top-level `## 9.34` section
   - Move all notes from the old `## 9.33` section under it (they become the release notes for that version)
   - Leave a fresh `## 9.34` (or next version) section for new changes
   - Add a release date to the moved section header

3. **Commit the version bump**

   ```powershell
   git add VERSION.txt core/constants.py CHANGELOG.md
   git commit -m "chore(release): bump version to 9.34"
   git push origin main
   ```

4. **Create the GitHub Tag**

   ```powershell
   git tag v9.34
   git push origin v9.34
   ```

5. **Create the GitHub Release**

   Go to: https://github.com/smd3235/steam-game-organizer/releases

   - Click **"Draft a new release"**
   - **Tag version:** select the tag you just pushed (e.g. `v9.34`)
   - **Release title:** `Steam Game Organizer v9.34`
   - **Description:** paste the CHANGELOG notes for this version
   - **Assets:** upload `dist\steam_game_organizer.zip` (zip the frozen exe folder)
   - Click **"Publish release"**

6. **Verify the Release**

   - Download the release zip on a clean Windows machine
   - Extract and run `steam_game_organizer.exe`
   - Complete the setup wizard
   - Scan a small test library
   - Verify artwork downloads and catalog generation

## Version Number Format

The app uses `Major.Minor` (e.g. `9.33`). Bump:

- **Major** for breaking changes or significant new features
- **Minor** for bug fixes, small features, and internal changes

The version is declared in exactly three places (enforced by `tests/test_release_structure.py`):

| File | Purpose |
|------|---------|
| `VERSION.txt` | Single source of truth |
| `core/constants.py` | `VERSION` constant used by the app |
| `CHANGELOG.md` | `## X.Y` section headings |

## Post-Release

- [ ] Close the GitHub milestone (if one was used)
- [ ] Announce the release in relevant communities
- [ ] Monitor `logs/` and [issues](https://github.com/smd3235/steam-game-organizer/issues) for user-reported problems
- [ ] Start a fresh `## 9.34` (or next) section in `CHANGELOG.md` for new changes

## Related Docs

| Doc | Purpose |
|-----|---------|
| `CHANGELOG.md` | Dated change log — source of truth for release notes |
| `ARCHITECTURE.md#-frozen-build` | How `tools\build_frozen.py` works |
| `AGENTS.md#-build--frozen-exe-pipeline` | Build pipeline details |
| `.github/workflows/ci.yml` | CI runs the quality gate on every push |
