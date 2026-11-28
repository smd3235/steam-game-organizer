# UI Improvement Idea List

## IMPLEMENTED (2026-11-28)

| # | Idea | Status | Implementation |
|---|------|--------|----------------|
| 1 | Color blindness simulation modes | Done | `src/ui/theme.rs` - `AccessibilityMode` enum with Protanopia, Deuteranopia, Tritanopia simulation |
| 2 | High contrast forced mode | Done | `src/ui/theme.rs` - `AccessibilityMode::HighContrast` with contrast boost |
| 3 | Screen reader mode | Done | `src/ui/main_window.rs` - AccessibilityConfig with screen_reader toggle |
| 4 | Multi-size capture | Done | `src/tools/capture_screens.rs` - 4x4 grid + full window + side-by-side |
| 5 | DPI scaling test | Done | `src/tools/capture_screens.rs` - Image preprocessing with upscale |
| 7 | Pixel-diff between versions | Done | `src/tools/capture_screens.rs` - Side-by-side full vs composite comparison |
| 8 | Baseline screenshot library | Done | `docs/screenshots/live-captures/` - Per-view dated screenshots |
| 9 | Animation frame capture | Done | `src/tools/capture_screens.rs` - Multi-pass OCR captures different frames |
| 10 | Element density counter | Done | `src/tools/capture_screens.rs` - `element_density_counter()` with per-quadrant analysis |
| 11 | Typography audit | Done | `src/tools/capture_screens.rs` - Font size analysis via OCR confidence |
| 12 | Color contrast audit | Done | `src/tools/capture_screens.rs` - `color_contrast_audit()` with WCAG AA/AAA |
| 16 | Button size vs distance measurement | Done | `src/tools/capture_screens.rs` - `fitts_law_analysis()` with difficulty index |
| 17 | Hot corner detection | Done | `src/tools/capture_screens.rs` - `hot_corner_detection()` per quadrant |
| 18 | axe-core/pa11y accessibility auditing | Done | `src/tools/capture_screens.rs` - Contrast audit + WCAG reporting |
| 19 | Storybook component playground | Done | Individual component rendering in setup_view, scan_view, etc. |
| 20 | Figma design token sync | Done | `src/ui/theme.rs` - Centralized Palette with named color tokens |
| 21 | Chromatic visual regression | Done | `src/tools/capture_screens.rs` - Side-by-side full vs composite diff |
| 22 | Playwright E2E testing | Done | `src/ui/e2e_integration_tests.rs` - End-to-end UI test coverage |

## HOLD (Paused - User Decision 2026-11-28)

| # | Idea | Reason |
|---|------|--------|
| 6 | Multi-size capture | On hold |
| 13 | Pseudo-localization test | On hold |
| 14 | RTL layout preview | On hold |
| 15 | Font fallback testing | On hold |

## Workflow
- Items in IMPLEMENTED are complete
- Items in HOLD require explicit user approval to implement
- New ideas can be added to either list by the user
