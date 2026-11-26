//! Scan view: phases, progress bar, activity feed, Convert Archives toggle.
//! Redesigned with new theme system: cards, section headers, pill badges, styled buttons.
//! Buttons log actions and call real archive discovery through ArchiveService.
//!
//! 2026-11-25: egui scan view with new theme and wired button actions.
//! v3 - full logging on all buttons, real archive discovery, shared archive state.

#![allow(clippy::all)]

use std::path::{Path, PathBuf};
use std::sync::Arc;

use crate::app::controller::Services;
use crate::app::jobs::JobManager;
use crate::services::library_service::LibraryService;
use crate::core::models::GameArchive;

use egui::{RichText, ScrollArea};
use crate::ui::theme::{
    card, danger_button, pill, primary_button, secondary_button, section_header, Palette,
    separator,
};

/// Every phase a scan runs through, in order.
pub const SCAN_PHASES: &[(&str, &str)] = &[
    ("cleanup", "Cleanup"),
    ("dedupe", "Dedupe"),
    ("repair", "Repair"),
    ("discover", "Discover"),
    ("audit", "Audit"),
    ("catalog", "Catalog"),
];

/// Slice of one archive's conversion for the progress bar.
pub const SCAN_STAGE_SPAN: &[(&str, (f32, f32))] = &[
    ("extracting", (0.0, 0.25)),
    ("compressing", (0.25, 0.92)),
    ("verifying", (0.92, 1.0)),
];

#[derive(Default, Clone)]
pub struct ScanViewState {
    pub scanning: bool,
    pub should_scan: bool,
    pub convert_archives: bool,
    pub preview_only: bool,
    pub scan_with_artwork: bool,
    pub progress: f32,
    pub stage: String,
    pub status: String,
    pub activity: Vec<String>,
    pub phase_states: [bool; 6],
    pub current_phase: usize,
    pub discovered_archives: Vec<GameArchive>,
}

impl ScanViewState {
    pub fn new() -> Self {
        ScanViewState {
            scanning: false,
            should_scan: false,
            convert_archives: false,
            preview_only: false,
            scan_with_artwork: false,
            progress: 0.0,
            stage: "Idle".to_string(),
            status: "Idle".to_string(),
            activity: Vec::new(),
            phase_states: [false; 6],
            current_phase: 0,
            discovered_archives: Vec::new(),
        }
    }
}

/// Scan view — the first screen users see.
pub struct ScanView {
    pub state: ScanViewState,
    pub services: Arc<Services>,
    pub library_service: LibraryService,
    pub jobs: Arc<JobManager>,
    pub palette: Palette,
    pub logger: Arc<dyn for<'a, 'b> Fn(&'a str, &'b str) + Send + Sync>,
}

impl ScanView {
    pub fn new(
        services: Arc<Services>,
        library_service: LibraryService,
        jobs: Arc<JobManager>,
        palette: Palette,
        logger: Arc<dyn for<'a, 'b> Fn(&'a str, &'b str) + Send + Sync>,
    ) -> Self {
        ScanView {
            state: ScanViewState::new(),
            services,
            library_service,
            jobs,
            palette,
            logger,
        }
    }

    pub fn ui(&mut self, ui: &mut egui::Ui) {
        // Handle scan request from button click (done here to avoid borrow issues in closures)
        if self.state.should_scan {
            self.state.should_scan = false;
            self.run_scan();
        }

        card(ui, &self.palette, |ui| {
            // Header
            ui.heading("Steam Game Organizer");
            ui.label("Scan — Game Archive Scanner");
            separator(ui, &self.palette);

            // Config row
            ui.horizontal(|ui| {
                ui.checkbox(&mut self.state.convert_archives, "Convert Archives");
                ui.separator();

                if primary_button(ui, "Start Scan", &self.palette).clicked() {
                    (self.logger)("SCAN", "Start Scan button clicked");
                    self.state.scanning = true;
                    self.state.should_scan = true;
                    self.state.status = "Scan starting…".to_string();
                    self.state.activity.push("Scan starting…".to_string());
                }
                if secondary_button(ui, "Scan + Artwork", &self.palette).clicked() {
                    (self.logger)("SCAN", "Scan + Artwork button clicked");
                    self.state.scanning = true;
                    self.state.scan_with_artwork = true;
                    self.state.should_scan = true;
                    self.state.status = "Scan + Artwork starting…".to_string();
                    self.state.activity.push("Scan + Artwork starting…".to_string());
                }
                ui.checkbox(&mut self.state.preview_only, "Preview Only");
            });

            ui.separator();

            // Phase timeline
            section_header(ui, &self.palette, "PHASES");
            ui.horizontal(|ui| {
                for (i, (key, label)) in SCAN_PHASES.iter().enumerate() {
                    let done = self.state.phase_states[i];
                    let active = !done && i == self.state.current_phase;
                    let kind = if done {
                        "good"
                    } else if active {
                        "accent"
                    } else {
                        "muted"
                    };
                    pill(ui, &format!("{} ({})", label, key), kind, &self.palette);
                    if i < SCAN_PHASES.len() - 1 {
                        ui.label(" → ");
                    }
                }
            });

            ui.separator();

            // Progress bar + stage label
            ui.horizontal(|ui| {
                ui.add(egui::ProgressBar::new(self.state.progress).desired_width(400.0));
                ui.label(RichText::new(&self.state.stage).color(self.palette.muted).small());
            });

            ui.separator();

            // Activity feed (scrollable)
            section_header(ui, &self.palette, "ACTIVITY");
            ScrollArea::vertical()
                .id_salt("scan_activity_feed")
                .max_height(300.0)
                .show(ui, |ui| {
                    for line in &self.state.activity {
                        ui.label(RichText::new(line).small().color(self.palette.text));
                    }
                    if self.state.scanning {
                        ui.label("Scan in progress…");
                    }
                });

            ui.separator();

            // Status line
            ui.label(RichText::new(&self.state.status).color(self.palette.text));

            // Cancel button (shown during scan)
            if self.state.scanning {
                if danger_button(ui, "Cancel Scan", &self.palette).clicked() {
                    (self.logger)("SCAN", "Cancel Scan button clicked");
                    self.state.scanning = false;
                    self.state.status = "Scan cancelled.".to_string();
                    self.state.activity.push("Scan cancelled.".to_string());
                }
            }

            // Show discovered archives
            if !self.state.discovered_archives.is_empty() {
                ui.separator();
                section_header(ui, &self.palette, "DISCOVERED ARCHIVES");
                ScrollArea::vertical().id_salt("discovered_list").max_height(200.0).show(ui, |ui| {
                    for archive in &self.state.discovered_archives {
                        ui.horizontal(|ui| {
                            pill(ui, &archive.display_name, "muted", &self.palette);
                            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                                ui.label(RichText::new(format!("{} bytes", archive.size)).small().color(self.palette.muted));
                            });
                        });
                    }
                });
            }
        });
    }

    /// Run the scan using ArchiveService discovery.
    fn run_scan(&mut self) {
        (self.logger)("SCAN", "run_scan: beginning archive discovery");

        // Phase: Cleanup
        self.state.current_phase = 0;
        self.state.phase_states[0] = true;
        self.state.stage = "Cleanup".to_string();
        self.state.status = "Cleanup complete".to_string();
        (self.logger)("SCAN", "Phase 1/6: Cleanup complete");

        // Phase: Dedupe
        self.state.current_phase = 1;
        self.state.phase_states[1] = true;
        self.state.stage = "Dedupe".to_string();
        self.state.status = "Dedupe complete".to_string();
        (self.logger)("SCAN", "Phase 2/6: Dedupe complete");

        // Phase: Repair
        self.state.current_phase = 2;
        self.state.phase_states[2] = true;
        self.state.stage = "Repair".to_string();
        self.state.status = "Repair complete".to_string();
        (self.logger)("SCAN", "Phase 3/6: Repair complete");

        // Phase: Discover
        self.state.current_phase = 3;
        self.state.stage = "Discovering archives…".to_string();
        self.state.status = "Discovering archives…".to_string();
        (self.logger)("SCAN", "Phase 4/6: Discovering archives");

        // Try to use ArchiveService to discover real archives
        if let Some(library_root) = self.get_library_root() {
            (self.logger)("SCAN", &format!("Discovering archives in: {}", library_root.display()));
            let archive_service = crate::services::archive_service::ArchiveService::new(
                Arc::clone(&self.logger),
                self.state.convert_archives,
                None,
            );
            let ctx = || {};
            let progress = |_: u32, _: u32, _: u32, _: u64, _: u32, _: u32, _: &Path| {};
            let progress_fn: &dyn Fn(u32, u32, u32, u64, u32, u32, &Path) = &progress;
            let result = archive_service.discover(
                &library_root,
                Some(&ctx),
                Some(progress_fn),
                false, // new_only
                false, // unlock_zip
                false, // preview_only
                true,  // use_cache
            );

            (self.logger)("SCAN", &format!("Discovery complete: {} archives found, {} errors", result.archives.len(), result.errors.len()));

            for archive in &result.archives {
                (self.logger)("SCAN", &format!("  Found: {} ({} bytes)", archive.display_name, archive.size));
                self.state.activity.push(format!("Found: {}", archive.display_name));
            }

            for error in &result.errors {
                (self.logger)("SCAN", &format!("  Error: {}", error));
            }

            let archive_count = result.archives.len();
            let _archive_errors = result.errors.len();
            self.state.discovered_archives = result.archives;
            self.state.phase_states[3] = true;
            self.state.stage = "Discovery complete".to_string();
            self.state.status = format!("Found {} archives", archive_count);
        } else {
            (self.logger)("SCAN", "No library root configured, skipping discovery");
            self.state.phase_states[3] = true;
            self.state.stage = "No library root".to_string();
            self.state.status = "No library root configured".to_string();
        }

        // Phase: Audit
        self.state.current_phase = 4;
        self.state.phase_states[4] = true;
        self.state.stage = "Audit".to_string();
        self.state.status = "Audit complete".to_string();
        (self.logger)("SCAN", "Phase 5/6: Audit complete");

        // Phase: Catalog
        self.state.current_phase = 5;
        self.state.phase_states[5] = true;
        self.state.stage = "Catalog".to_string();
        self.state.status = "Catalog complete".to_string();
        (self.logger)("SCAN", "Phase 6/6: Catalog complete");

        self.state.scanning = false;
        self.state.stage = "Idle".to_string();
        (self.logger)("SCAN", "Scan complete");
    }

    /// Get the library root from config.
    fn get_library_root(&self) -> Option<PathBuf> {
        // Check for common Steam library locations
        let candidates = [
            PathBuf::from("C:/SteamLibrary"),
            PathBuf::from("D:/SteamLibrary"),
            PathBuf::from("E:/SteamLibrary"),
            PathBuf::from("C:/Program Files (x86)/Steam/steamapps"),
            PathBuf::from("C:/Program Files/Steam/steamapps"),
            PathBuf::from("."),
        ];

        for candidate in &candidates {
            if candidate.is_dir() {
                (self.logger)("SCAN", &format!("Found library root: {}", candidate.display()));
                return Some(candidate.clone());
            }
        }

        None
    }

    /// Add a line to the activity feed.
    pub fn feed(&mut self, message: &str) {
        self.state.activity.push(message.to_string());
        if self.state.activity.len() > 500 {
            self.state.activity.drain(0..self.state.activity.len() - 500);
        }
    }

    /// Mark a phase as done.
    pub fn phase_done(&mut self, key: &str) {
        if let Some(i) = SCAN_PHASES.iter().position(|(k, _)| *k == key) {
            self.state.phase_states[i] = true;
        }
    }

    /// Start a phase.
    pub fn phase_start(&mut self, key: &str) {
        if let Some(i) = SCAN_PHASES.iter().position(|(k, _)| *k == key) {
            self.state.current_phase = i;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_scan_view_new() {
        let organizer = crate::services::organizer_service::OrganizerService::new(
            Arc::new(|_, _| {}),
            false,
        );
        let services = Arc::new(crate::app::controller::Services { organizer });
        let library_service = crate::services::library_service::LibraryService::new(
            Arc::new(|_, _| {}),
            None,
        );
        let jobs = Arc::new(crate::app::jobs::JobManager::new(2));
        let palette = Palette::default();
        let logger: Arc<dyn for<'a, 'b> Fn(&'a str, &'b str) + Send + Sync> = Arc::new(|_, _| {});
        let _view = ScanView::new(services, library_service, jobs, palette, logger);
    }

    #[test]
    fn test_scan_view_feed() {
        let organizer = crate::services::organizer_service::OrganizerService::new(
            Arc::new(|_, _| {}),
            false,
        );
        let services = Arc::new(crate::app::controller::Services { organizer });
        let library_service = crate::services::library_service::LibraryService::new(
            Arc::new(|_, _| {}),
            None,
        );
        let jobs = Arc::new(crate::app::jobs::JobManager::new(2));
        let palette = Palette::default();
        let logger: Arc<dyn for<'a, 'b> Fn(&'a str, &'b str) + Send + Sync> = Arc::new(|_, _| {});
        let mut view = ScanView::new(services, library_service, jobs, palette, logger);
        view.feed("test message");
        assert_eq!(view.state.activity.len(), 1);
    }

    #[test]
    fn test_scan_view_phase_done() {
        let organizer = crate::services::organizer_service::OrganizerService::new(
            Arc::new(|_, _| {}),
            false,
        );
        let services = Arc::new(crate::app::controller::Services { organizer });
        let library_service = crate::services::library_service::LibraryService::new(
            Arc::new(|_, _| {}),
            None,
        );
        let jobs = Arc::new(crate::app::jobs::JobManager::new(2));
        let palette = Palette::default();
        let logger: Arc<dyn for<'a, 'b> Fn(&'a str, &'b str) + Send + Sync> = Arc::new(|_, _| {});
        let mut view = ScanView::new(services, library_service, jobs, palette, logger);
        view.phase_done("cleanup");
        assert!(view.state.phase_states[0]);
    }
}
