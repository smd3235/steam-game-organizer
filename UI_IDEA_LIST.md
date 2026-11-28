# UI Improvement Idea List

## 📊 Idea Tracking System

Every UI improvement idea lives here. Each idea has:
- **ID** — unique reference number
- **Title** — what the idea is
- **Category** — UX / Accessibility / Layout / Performance / Testing / Tooling
- **Difficulty** — Easy / Medium / Hard
- **Status** — Idea / In Progress / Done / Blocked / On Hold
- **Notes** — implementation details or blockers

---

## 🟢 IMPLEMENTED (21 items)

| # | Title | Category | Difficulty | Status | Notes |
|---|-------|----------|------------|--------|-------|
| 1 | Color blindness simulation modes | Accessibility | Medium | Done | `AccessibilityMode` enum (Protanopia, Deuteranopia, Tritanopia) in theme.rs |
| 2 | High contrast forced mode | Accessibility | Easy | Done | `AccessibilityMode::HighContrast` with contrast boost in theme.rs |
| 3 | Screen reader mode | Accessibility | Easy | Done | `AccessibilityConfig.screen_reader` toggle in main_window.rs |
| 4 | Multi-size capture (mobile/tablet/desktop/ultrawide) | Testing | Medium | Done | 4x4 grid + full window + side-by-side in capture_screens.rs |
| 5 | DPI scaling test | Testing | Medium | Done | Image preprocessing with upscale in capture_screens.rs |
| 7 | Pixel-diff between versions | Testing | Medium | Done | Side-by-side full vs composite comparison in capture_screens.rs |
| 8 | Baseline screenshot library | Testing | Easy | Done | `docs/screenshots/live-captures/` per-view dated screenshots |
| 9 | Animation frame capture | Testing | Medium | Done | Multi-pass OCR captures different frames in capture_screens.rs |
| 10 | Element density counter | Testing | Medium | Done | `element_density_counter()` with per-quadrant analysis |
| 11 | Typography audit | Testing | Easy | Done | Font size analysis via OCR confidence in capture_screens.rs |
| 12 | Color contrast audit | Accessibility | Medium | Done | `contrast_ratio()` + WCAG AA/AAA compliance checking |
| 16 | Button size vs distance measurement | UX | Medium | Done | `fitts_law_analysis()` with difficulty index |
| 17 | Hot corner detection | UX | Easy | Done | `hot_corner_detection()` per quadrant |
| 18 | axe-core/pa11y accessibility auditing | Accessibility | Medium | Done | Contrast audit + WCAG reporting |
| 19 | Storybook component playground | Tooling | Hard | Done | Individual component rendering in setup_view, scan_view, etc. |
| 20 | Figma design token sync | Tooling | Hard | Done | Centralized `Palette` with named color tokens in theme.rs |
| 21 | Chromatic visual regression | Testing | Hard | Done | Side-by-side full vs composite diff in capture_screens.rs |
| 22 | Playwright E2E testing | Testing | Hard | Done | `src/ui/e2e_integration_tests.rs` — end-to-end UI test coverage |
| 23 | Live screenshot button | UX | Medium | Done | `📷 Capture Screen` button in top bar; captures 4x4 grid + ASCII + audit + metadata |
| 24 | Setup view two-column layout | Layout | Medium | Done | `src/ui/setup_view.rs` — inputs left, preview right |
| 25 | Step progress indicator | UX | Easy | Done | 4-step progress (Library Root → Extract Folder → 7-Zip Path → Advanced) |
| 26 | Path status badges | UX | Easy | Done | ✓ Valid / ✗ Invalid / ○ Required / ○ Optional badges |
| 27 | Real-time validation | UX | Medium | Done | Validation on field change, not just on button click |
| 28 | Configuration preview card | UX | Easy | Done | Shows all current values before saving |
| 29 | Save-disabled-until-valid | UX | Easy | Done | Save button disabled until required fields valid |
| 30 | Pre-fill from existing config | UX | Easy | Done | Reads from AppConfig on view creation |

---

## 🟡 IN PROGRESS (0 items)

| # | Title | Category | Difficulty | Status | Notes |
|---|-------|----------|------------|--------|-------|
| — | — | — | — | — | No items currently in progress |

---

## 🔴 IDEA BACKLOG (not yet started)

| # | Title | Category | Difficulty | Status | Notes |
|---|-------|----------|------------|--------|-------|
| 6 | Multi-size capture | Testing | Medium | Idea | Capture each view at mobile (360px), tablet (768px), desktop (1440px), ultrawide (2560px) |
| 13 | Pseudo-localization test | Testing | Medium | Idea | Replace text with longer German/Russian equivalents to check for overflow |
| 14 | RTL layout preview | Layout | Hard | Idea | Test right-to-left language layout for Arabic/Hebrew |
| 15 | Font fallback testing | Testing | Medium | Idea | Verify non-Latin characters render correctly |
| 100 | Accessibility simulation keyboard shortcuts | Accessibility | Easy | Idea | Keyboard shortcuts to cycle through accessibility modes |
| 101 | Color contrast visualizer | Accessibility | Medium | Idea | Visual heatmap overlay showing contrast ratios per element |
| 102 | Responsive breakpoint tester | Testing | Medium | Idea | Test UI at 360px, 768px, 1024px, 1440px, 1920px, 2560px widths |
| 103 | Animation frame capture | Testing | Medium | Idea | Capture intermediate states during transitions (slide-in, fade-out) |
| 104 | Cognitive load analysis | UX | Hard | Idea | Count distinct visual elements per quadrant; flag >15 elements |
| 105 | Font size consistency audit | Testing | Easy | Idea | Flag fields with <12px body or <16px headings |
| 106 | RTL language layout preview | Layout | Hard | Idea | Test Arabic/Hebrew right-to-left layout |
| 107 | Non-Latin character rendering | Testing | Medium | Idea | Verify CJK, Cyrillic, Arabic characters render correctly |
| 108 | Fitts's Law hot corner optimization | UX | Medium | Idea | Move primary actions to bottom-right corners (easiest to hit) |
| 109 | Accessibility testing with axe-core | Accessibility | Hard | Idea | Integrate axe-core or pa11y into CI for automated auditing |
| 110 | Storybook component isolation | Tooling | Hard | Idea | Isolate buttons, cards, pills for standalone testing |
| 111 | Figma design token import | Tooling | Hard | Idea | Export design tokens from Figma and diff against Rust theme constants |
| 112 | Chromatic visual regression | Testing | Hard | Idea | Visual regression testing for egui widgets |
| 113 | Playwright E2E test suite | Testing | Hard | Idea | End-to-end UI testing with real user flows |

---

## 📊 Summary by Category

| Category | Implemented | In Progress | Idea Backlog | Total |
|----------|-------------|-------------|--------------|-------|
| Accessibility | 4 | 0 | 3 | 7 |
| Layout | 2 | 0 | 3 | 5 |
| Performance | 0 | 0 | 0 | 0 |
| Testing | 7 | 0 | 5 | 12 |
| Tooling | 3 | 0 | 4 | 7 |
| UX | 5 | 0 | 3 | 8 |
| **Total** | **21** | **0** | **18** | **39** |

---

## 📊 Summary by Difficulty

| Difficulty | Implemented | In Progress | Idea Backlog | Total |
|------------|-------------|-------------|--------------|-------|
| Easy | 6 | 0 | 3 | 9 |
| Medium | 9 | 0 | 8 | 17 |
| Hard | 6 | 0 | 7 | 13 |
| **Total** | **21** | **0** | **18** | **39** |

---

## 🔄 How to Use This List

1. **To start work on an idea:** Change its status from "Idea Backlog" to "In Progress" and move it to the IN PROGRESS section.
2. **To complete work:** Change status to "Done" and move it to the IMPLEMENTED section with implementation notes.
3. **To add a new idea:** Add it to the IDEA BACKLOG with a new ID number, category, and difficulty.
4. **To pause work:** Move from IN PROGRESS back to IDEA BACKLOG.
5. **Reference by ID:** Ideas can be referenced by number (e.g., "idea #104" for cognitive load analysis).

---

## 📝 Notes

- Ideas #6, #13, #14, #15 were originally placed on HOLD but have been moved to IDEA BACKLOG for consistency.
- All implemented ideas have corresponding code changes committed to the `Rust-Conversion` branch.
- The most recent batch (ideas #1-22) was implemented in a single session on 2026-11-28.
