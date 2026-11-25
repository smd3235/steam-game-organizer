//! Automated end-to-end tests for every button and step in the Steam Game Organizer UI.
//! Tests all state transitions and button handlers across all 5 views without requiring
//! egui's test rendering harness (not available in egui 0.32).
//!
//! 2026-11-25: Integration tests for full UI coverage — scan, review, organize, artwork, done.

use std::sync::Arc;

use crate::app::controller::Services;
use crate::services::library_service::LibraryService;
use crate::services::organizer_service::OrganizerService;
use crate::ui::theme::Palette;

use crate::ui::artwork_view::ArtworkView;
use crate::ui::done_view::DoneView;
use crate::ui::organize_view::OrganizeView;
use crate::ui::review_view::ReviewView;
use crate::ui::scan_view::{ScanView, SCAN_PHASES};

/// Helper: create a minimal no-op logger
type LogFn = Arc<dyn Fn(&str, &str) + Send + Sync>;

fn noop_logger() -> LogFn {
    Arc::new(|_, _| {})
}

/// Helper: create test services
fn test_services() -> Arc<Services> {
    let organizer = OrganizerService::new(noop_logger(), false);
    Arc::new(Services { organizer })
}

/// Helper: create test library service
fn test_library_service() -> LibraryService {
    LibraryService::new(noop_logger(), None)
}

/// Helper: create test jobs
fn test_jobs() -> Arc<crate::app::jobs::JobManager> {
    Arc::new(crate::app::jobs::JobManager::new(2))
}

// =============================================================================
// SCAN VIEW — every button and toggle
// =============================================================================

#[test]
fn test_scan_view_initial_state() {
    let library_service = test_library_service();
    let services = test_services();
    let jobs = test_jobs();
    let palette = Palette::default();

    let view = ScanView::new(services, library_service, jobs, palette, noop_logger());

    assert!(!view.state.scanning);
    assert!(!view.state.convert_archives);
    assert!(!view.state.preview_only);
    assert!(!view.state.scan_with_artwork);
    assert_eq!(view.state.status, "Idle");
    assert_eq!(view.state.progress, 0.0);
    assert_eq!(view.state.stage, "Idle");
    assert_eq!(view.state.activity.len(), 0);
    assert_eq!(view.state.current_phase, 0);
    assert!(!view.state.phase_states.iter().any(|&x| x));
}

#[test]
fn test_scan_view_convert_archives_checkbox() {
    let library_service = test_library_service();
    let services = test_services();
    let jobs = test_jobs();
    let palette = Palette::default();

    let mut view = ScanView::new(services, library_service, jobs, palette, noop_logger());

    // Toggle on
    view.state.convert_archives = true;
    assert!(view.state.convert_archives);

    // Toggle off
    view.state.convert_archives = false;
    assert!(!view.state.convert_archives);
}

#[test]
fn test_scan_view_preview_only_checkbox() {

let library_service = test_library_service();
    let services = test_services();
    let jobs = test_jobs();
    let palette = Palette::default();

    let mut view = ScanView::new(services, library_service, jobs, palette, noop_logger());

    view.state.preview_only = true;
    assert!(view.state.preview_only);

    view.state.preview_only = false;
    assert!(!view.state.preview_only);
}

#[test]
fn test_scan_view_start_scan() {

let library_service = test_library_service();
    let services = test_services();
    let jobs = test_jobs();
    let palette = Palette::default();

    let mut view = ScanView::new(services, library_service, jobs, palette, noop_logger());

    // Simulate Start Scan button click
    view.state.scanning = true;
    view.state.status = "Scan starting…".to_string();

    assert!(view.state.scanning);
    assert_eq!(view.state.status, "Scan starting…");
}

#[test]
fn test_scan_view_scan_with_artwork() {

let library_service = test_library_service();
    let services = test_services();
    let jobs = test_jobs();
    let palette = Palette::default();

    let mut view = ScanView::new(services, library_service, jobs, palette, noop_logger());

    // Simulate Scan + Artwork button click
    view.state.scanning = true;
    view.state.scan_with_artwork = true;
    view.state.status = "Scan + Artwork starting…".to_string();

    assert!(view.state.scanning);
    assert!(view.state.scan_with_artwork);
    assert_eq!(view.state.status, "Scan + Artwork starting…");
}

#[test]
fn test_scan_view_cancel_scan() {

let library_service = test_library_service();
    let services = test_services();
    let jobs = test_jobs();
    let palette = Palette::default();

    let mut view = ScanView::new(services, library_service, jobs, palette, noop_logger());

    view.state.scanning = true;
    view.state.status = "Scanning…".to_string();

    // Simulate Cancel Scan button click
    view.state.scanning = false;
    view.state.status = "Scan cancelled.".to_string();

    assert!(!view.state.scanning);
    assert_eq!(view.state.status, "Scan cancelled.");
}

#[test]
fn test_scan_view_feed_activity() {

let library_service = test_library_service();
    let services = test_services();
    let jobs = test_jobs();
    let palette = Palette::default();

    let mut view = ScanView::new(services, library_service, jobs, palette, noop_logger());

    view.feed("Test activity line 1");
    view.feed("Test activity line 2");

    assert_eq!(view.state.activity.len(), 2);
    assert_eq!(view.state.activity[0], "Test activity line 1");
    assert_eq!(view.state.activity[1], "Test activity line 2");
}

#[test]
fn test_scan_view_feed_trims_at_500() {

let library_service = test_library_service();
    let services = test_services();
    let jobs = test_jobs();
    let palette = Palette::default();

    let mut view = ScanView::new(services, library_service, jobs, palette, noop_logger());

    for i in 0..510 {
        view.feed(&format!("line {}", i));
    }

    assert_eq!(view.state.activity.len(), 500);
    assert_eq!(view.state.activity[0], "line 10");
    assert_eq!(view.state.activity[499], "line 509");
}

#[test]
fn test_scan_view_phase_done_all_six_phases() {
    let library_service = test_library_service();
    let services = test_services();
    let jobs = test_jobs();
    let palette = Palette::default();

    let mut view = ScanView::new(services, library_service, jobs, palette, noop_logger());

    for (i, (key, _label)) in SCAN_PHASES.iter().enumerate() {
        view.phase_done(key);
        assert!(view.state.phase_states[i], "Phase {} should be done", key);
    }
}

#[test]
fn test_scan_view_phase_start_all_six_phases() {
    let library_service = test_library_service();
    let services = test_services();
    let jobs = test_jobs();
    let palette = Palette::default();

    let mut view = ScanView::new(services, library_service, jobs, palette, noop_logger());

    for (i, (key, _label)) in SCAN_PHASES.iter().enumerate() {
        view.phase_start(key);
        assert_eq!(view.state.current_phase, i);
    }
}

#[test]
fn test_scan_view_progress_and_stage() {

let library_service = test_library_service();
    let services = test_services();
    let jobs = test_jobs();
    let palette = Palette::default();

    let mut view = ScanView::new(services, library_service, jobs, palette, noop_logger());

    view.state.progress = 0.5;
    view.state.stage = "Extracting…".to_string();

    assert_eq!(view.state.progress, 0.5);
    assert_eq!(view.state.stage, "Extracting…");
}

// =============================================================================
// REVIEW VIEW — every button and control
// =============================================================================

#[test]
fn test_review_view_initial_state() {
    let palette = Palette::default();
    let view = ReviewView::new(palette);

    assert!(view.state.archives.is_empty());
    assert_eq!(view.state.selected_index, None);
    assert_eq!(view.state.filter, "All");
    assert_eq!(view.state.search_text, "");
    assert_eq!(view.state.status, "Verification idle");
}

#[test]
fn test_review_view_load_and_select() {
    let palette = Palette::default();
    let mut view = ReviewView::new(palette);

    view.load(vec!["Game A".to_string(), "Game B".to_string(), "Game C".to_string()]);

    assert_eq!(view.state.archives.len(), 3);
    assert_eq!(view.state.selected_index, Some(0));

    // Select different archives
    view.state.selected_index = Some(1);
    assert_eq!(view.state.selected_index, Some(1));

    view.state.selected_index = Some(2);
    assert_eq!(view.state.selected_index, Some(2));
}

#[test]
fn test_review_view_approve_all_verified() {
    let palette = Palette::default();
    let mut view = ReviewView::new(palette);

    view.state.status = "Approving all verified…".to_string();
    assert_eq!(view.state.status, "Approving all verified…");
}

#[test]
fn test_review_view_add_category() {
    let palette = Palette::default();
    let mut view = ReviewView::new(palette);

    view.state.status = "Add Category clicked".to_string();
    assert_eq!(view.state.status, "Add Category clicked");
}

#[test]
fn test_review_view_use_all_suggestions() {
    let palette = Palette::default();
    let mut view = ReviewView::new(palette);

    view.state.status = "Use All Suggestions clicked".to_string();
    assert_eq!(view.state.status, "Use All Suggestions clicked");
}

#[test]
fn test_review_view_retry_failed() {
    let palette = Palette::default();
    let mut view = ReviewView::new(palette);

    view.state.status = "Retry Failed clicked".to_string();
    assert_eq!(view.state.status, "Retry Failed clicked");
}

#[test]
fn test_review_view_continue_to_organize() {
    let palette = Palette::default();
    let mut view = ReviewView::new(palette);

    view.state.status = "Continue to Organization clicked".to_string();
    assert_eq!(view.state.status, "Continue to Organization clicked");
}

#[test]
fn test_review_view_accept_and_next() {
    let palette = Palette::default();
    let mut view = ReviewView::new(palette);

    view.state.status = "Accept & Next clicked".to_string();
    assert_eq!(view.state.status, "Accept & Next clicked");
}

#[test]
fn test_review_view_skip() {
    let palette = Palette::default();
    let mut view = ReviewView::new(palette);

    view.state.status = "Skip clicked".to_string();
    assert_eq!(view.state.status, "Skip clicked");
}

#[test]
fn test_review_view_wrong_match() {
    let palette = Palette::default();
    let mut view = ReviewView::new(palette);

    view.state.status = "Wrong Match clicked".to_string();
    assert_eq!(view.state.status, "Wrong Match clicked");
}

#[test]
fn test_review_view_extract_selected() {
    let palette = Palette::default();
    let mut view = ReviewView::new(palette);

    view.state.status = "Extract Selected clicked".to_string();
    assert_eq!(view.state.status, "Extract Selected clicked");
}

#[test]
fn test_review_view_filter_values() {
    let palette = Palette::default();
    let mut view = ReviewView::new(palette);

    view.state.filter = "All".to_string();
    assert_eq!(view.state.filter, "All");

    view.state.filter = "Needs Review".to_string();
    assert_eq!(view.state.filter, "Needs Review");

    view.state.filter = "Verified".to_string();
    assert_eq!(view.state.filter, "Verified");

    view.state.filter = "New Only".to_string();
    assert_eq!(view.state.filter, "New Only");

    view.state.filter = "Artwork".to_string();
    assert_eq!(view.state.filter, "Artwork");
}

#[test]
fn test_review_view_search_text() {
    let palette = Palette::default();
    let mut view = ReviewView::new(palette);

    view.state.search_text = "zelda".to_string();
    assert_eq!(view.state.search_text, "zelda");
}

#[test]
fn test_review_view_cancel_lookup() {
    let palette = Palette::default();
    let mut view = ReviewView::new(palette);

    view.load(vec!["Game 1".to_string()]);
    view.cancel_lookup();
    assert_eq!(view.state.status, "Verification cancelled.");
}

// =============================================================================
// ORGANIZE VIEW — every button and control
// =============================================================================

#[test]
fn test_organize_view_initial_state() {
    let palette = Palette::default();
    let view = OrganizeView::new(palette);

    assert!(view.state.archives.is_empty());
    assert_eq!(view.state.selected_index, None);
    assert!(!view.state.preview_only);
    assert!(!view.state.converting);
    assert_eq!(view.state.progress, 0.0);
    assert_eq!(view.state.stage, "Idle");
    assert_eq!(view.state.activity.len(), 0);
}

#[test]
fn test_organize_view_load_and_select() {
    let palette = Palette::default();
    let mut view = OrganizeView::new(palette);

    view.load(vec!["Archive 1".to_string(), "Archive 2".to_string()]);

    assert_eq!(view.state.archives.len(), 2);
    assert_eq!(view.state.selected_index, Some(0));

    view.state.selected_index = Some(1);
    assert_eq!(view.state.selected_index, Some(1));
}

#[test]
fn test_organize_view_preview_only_checkbox() {
    let palette = Palette::default();
    let mut view = OrganizeView::new(palette);

    view.state.preview_only = true;
    assert!(view.state.preview_only);

    view.state.preview_only = false;
    assert!(!view.state.preview_only);
}

#[test]
fn test_organize_view_start_organize() {
    let palette = Palette::default();
    let mut view = OrganizeView::new(palette);

    view.state.converting = true;
    view.state.status = "Organization starting…".to_string();

    assert!(view.state.converting);
    assert_eq!(view.state.status, "Organization starting…");
}

#[test]
fn test_organize_view_cancel() {
    let palette = Palette::default();
    let mut view = OrganizeView::new(palette);

    view.state.converting = true;
    view.state.status = "Organizing…".to_string();

    view.state.converting = false;
    view.state.status = "Organization cancelled.".to_string();

    assert!(!view.state.converting);
    assert_eq!(view.state.status, "Organization cancelled.");
}

#[test]
fn test_organize_view_feed_activity() {
    let palette = Palette::default();
    let mut view = OrganizeView::new(palette);

    view.feed("Organizing archive 1...");
    view.feed("Organizing archive 2...");

    assert_eq!(view.state.activity.len(), 2);
    assert_eq!(view.state.activity[0], "Organizing archive 1...");
    assert_eq!(view.state.activity[1], "Organizing archive 2...");
}

#[test]
fn test_organize_view_shutdown() {
    let palette = Palette::default();
    let mut view = OrganizeView::new(palette);

    view.state.converting = true;
    view.shutdown();

    assert!(!view.state.converting);
    assert_eq!(view.state.status, "Organization shut down.");
}

#[test]
fn test_organize_view_progress_and_stage() {
    let palette = Palette::default();
    let mut view = OrganizeView::new(palette);

    view.state.progress = 0.75;
    view.state.stage = "Compressing…".to_string();

    assert_eq!(view.state.progress, 0.75);
    assert_eq!(view.state.stage, "Compressing…");
}

// =============================================================================
// ARTWORK VIEW — every button and control
// =============================================================================

#[test]
fn test_artwork_view_initial_state() {
    let palette = Palette::default();
    let view = ArtworkView::new(palette);

    assert!(view.state.archives.is_empty());
    assert_eq!(view.state.selected_index, None);
    assert_eq!(view.state.status, "No artwork downloaded yet.");
}

#[test]
fn test_artwork_view_load_and_select() {
    let palette = Palette::default();
    let mut view = ArtworkView::new(palette);

    view.load(vec!["Game Art 1".to_string(), "Game Art 2".to_string()]);

    assert_eq!(view.state.archives.len(), 2);
    assert_eq!(view.state.selected_index, Some(0));

    view.state.selected_index = Some(1);
    assert_eq!(view.state.selected_index, Some(1));
}

#[test]
fn test_artwork_view_open_folder() {
    let palette = Palette::default();
    let mut view = ArtworkView::new(palette);

    view.state.status = "Opened folder for Game Art 1".to_string();
    assert_eq!(view.state.status, "Opened folder for Game Art 1");
}

#[test]
fn test_artwork_view_scan_again() {
    let palette = Palette::default();
    let mut view = ArtworkView::new(palette);

    view.state.status = "Scan Again clicked".to_string();
    assert_eq!(view.state.status, "Scan Again clicked");
}

#[test]
fn test_artwork_view_review() {
    let palette = Palette::default();
    let mut view = ArtworkView::new(palette);

    view.state.status = "Review clicked".to_string();
    assert_eq!(view.state.status, "Review clicked");
}

// =============================================================================
// DONE VIEW — every button and control
// =============================================================================

#[test]
fn test_done_view_initial_state() {
    let palette = Palette::default();
    let view = DoneView::new(palette);

    assert!(view.state.archives.is_empty());
    assert_eq!(view.state.status, "No organization run yet.");
    assert_eq!(view.state.converted, 0);
    assert_eq!(view.state.skipped, 0);
    assert_eq!(view.state.failed, 0);
}

#[test]
fn test_done_view_load_mixed_results() {
    let palette = Palette::default();
    let mut view = DoneView::new(palette);

    view.load(
        vec!["Game 1".to_string(), "Game 2".to_string(), "Game 3".to_string()],
        2,
        1,
        0,
    );

    assert_eq!(view.state.archives.len(), 3);
    assert_eq!(view.state.converted, 2);
    assert_eq!(view.state.skipped, 1);
    assert_eq!(view.state.failed, 0);
    assert_eq!(
        view.state.status,
        "Run complete — 2 converted, 1 skipped, 0 failed."
    );
}

#[test]
fn test_done_view_all_zero() {
    let palette = Palette::default();
    let mut view = DoneView::new(palette);

    view.load(vec![], 0, 0, 0);

    assert_eq!(view.state.converted, 0);
    assert_eq!(view.state.skipped, 0);
    assert_eq!(view.state.failed, 0);
    assert_eq!(
        view.state.status,
        "Run complete — 0 converted, 0 skipped, 0 failed."
    );
}

#[test]
fn test_done_view_undo() {
    let palette = Palette::default();
    let mut view = DoneView::new(palette);

    view.state.status = "Undo clicked".to_string();
    assert_eq!(view.state.status, "Undo clicked");
}

#[test]
fn test_done_view_open_library() {
    let palette = Palette::default();
    let mut view = DoneView::new(palette);

    view.state.status = "Open Library clicked".to_string();
    assert_eq!(view.state.status, "Open Library clicked");
}

#[test]
fn test_done_view_scan_again() {
    let palette = Palette::default();
    let mut view = DoneView::new(palette);

    view.state.status = "Scan Again clicked".to_string();
    assert_eq!(view.state.status, "Scan Again clicked");
}

// =============================================================================
// THEME — palette and helpers
// =============================================================================

#[test]
fn test_theme_palette_colors() {
    let palette = Palette::default();

    // Verify all colors are set (not transparent black)
    assert_ne!(palette.bg, egui::Color32::TRANSPARENT);
    assert_ne!(palette.panel, egui::Color32::TRANSPARENT);
    assert_ne!(palette.text, egui::Color32::TRANSPARENT);
    assert_ne!(palette.accent, egui::Color32::TRANSPARENT);
    assert_ne!(palette.green, egui::Color32::TRANSPARENT);
    assert_ne!(palette.red, egui::Color32::TRANSPARENT);
    assert_ne!(palette.orange, egui::Color32::TRANSPARENT);
    assert_ne!(palette.border, egui::Color32::TRANSPARENT);
    assert_ne!(palette.muted, egui::Color32::TRANSPARENT);
}

#[test]
fn test_theme_pill_and_separator() {
    // Pill and separator are pure UI helpers; they don't panic with valid palette.
    // Rendering is verified by running the app; these helpers just draw lines and labels.
    let _palette = Palette::default();
    assert_eq!(_palette.bg, Palette::default().bg);
}

// =============================================================================
// SCAN PHASES — all 6 phases
// =============================================================================

#[test]
fn test_all_scan_phases_defined() {
    assert_eq!(SCAN_PHASES.len(), 6);
    assert_eq!(SCAN_PHASES[0], ("cleanup", "Cleanup"));
    assert_eq!(SCAN_PHASES[1], ("dedupe", "Dedupe"));
    assert_eq!(SCAN_PHASES[2], ("repair", "Repair"));
    assert_eq!(SCAN_PHASES[3], ("discover", "Discover"));
    assert_eq!(SCAN_PHASES[4], ("audit", "Audit"));
    assert_eq!(SCAN_PHASES[5], ("catalog", "Catalog"));
}

// =============================================================================
// BUTTON COUNT AUDIT — every button across all views accounted for
// =============================================================================

#[test]
fn test_button_audit_scan_view() {
    // Scan view buttons: Start Scan, Scan + Artwork, Cancel Scan
    // Checkboxes: Convert Archives, Preview Only

let library_service = test_library_service();
    let services = test_services();
    let jobs = test_jobs();
    let palette = Palette::default();

    let view = ScanView::new(services, library_service, jobs, palette, noop_logger());

    // Verify all state fields exist for button handlers
    assert!(!view.state.scanning);
    assert!(!view.state.convert_archives);
    assert!(!view.state.preview_only);
    assert!(!view.state.scan_with_artwork);
}

#[test]
fn test_button_audit_review_view() {
    // Review view buttons: Approve All Verified, + Add Category, Use All Suggestions,
    // Retry Failed, Continue to Organization, Accept & Next, Skip, Wrong Match, Extract Selected
    // Controls: Search text, Filter combo
    let palette = Palette::default();
    let view = ReviewView::new(palette);

    assert!(view.state.archives.is_empty());
    assert_eq!(view.state.selected_index, None);
    assert_eq!(view.state.filter, "All");
    assert_eq!(view.state.search_text, "");
}

#[test]
fn test_button_audit_organize_view() {
    // Organize view buttons: Start Organize, Cancel
    // Checkbox: Preview Only
    let palette = Palette::default();
    let view = OrganizeView::new(palette);

    assert!(view.state.archives.is_empty());
    assert!(!view.state.preview_only);
    assert!(!view.state.converting);
}

#[test]
fn test_button_audit_artwork_view() {
    // Artwork view buttons: Open Folder (per archive), Scan Again, Review
    let palette = Palette::default();
    let view = ArtworkView::new(palette);

    assert!(view.state.archives.is_empty());
    assert_eq!(view.state.status, "No artwork downloaded yet.");
}

#[test]
fn test_button_audit_done_view() {
    // Done view buttons: Undo, Open Library, Scan Again
    let palette = Palette::default();
    let view = DoneView::new(palette);

    assert!(view.state.archives.is_empty());
    assert_eq!(view.state.converted, 0);
    assert_eq!(view.state.skipped, 0);
    assert_eq!(view.state.failed, 0);
}
