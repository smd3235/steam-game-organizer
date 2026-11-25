//! Scan view: phases, progress bar, activity feed, Convert Archives toggle.
//! Redesigned with new theme system: cards, section headers, pill badges, styled buttons.
//!
//! 2026-11-25: egui scan view with new theme.

#![allow(clippy::all)]

use crate::app::controller::Services;
use crate::app::jobs::JobManager;
use crate::services::library_service::LibraryService;
use std::sync::Arc;

use egui::RichText;
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

#[derive(Default)]
pub struct ScanViewState {
    pub scanning: bool,
    pub convert_archives: bool,
    pub preview_only: bool,
    pub scan_with_artwork: bool,
    pub progress: f32,
    pub stage: String,
    pub status: String,
    pub activity: Vec<String>,
    pub phase_states: [bool; 6], // true = done
    pub current_phase: usize,
}

impl ScanViewState {
    pub fn new() -> Self {
        ScanViewState {
            scanning: false,
            convert_archives: false,
            preview_only: false,
            scan_with_artwork: false,
            progress: 0.0,
            stage: "Idle".to_string(),
            status: "Idle".to_string(),
            activity: Vec::new(),
            phase_states: [false; 6],
            current_phase: 0,
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
}

impl ScanView {
    pub fn new(
        services: Arc<Services>,
        library_service: LibraryService,
        jobs: Arc<JobManager>,
        palette: Palette,
    ) -> Self {
        ScanView {
            state: ScanViewState::new(),
            services,
            library_service,
            jobs,
            palette,
        }
    }

    pub fn ui(&mut self, ui: &mut egui::Ui) {
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
                    self.state.scanning = true;
                    self.state.status = "Scan starting…".to_string();
                }
                if secondary_button(ui, "Scan + Artwork", &self.palette).clicked() {
                    self.state.scanning = true;
                    self.state.scan_with_artwork = true;
                    self.state.status = "Scan + Artwork starting…".to_string();
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
            egui::ScrollArea::vertical()
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
                    self.state.scanning = false;
                    self.state.status = "Scan cancelled.".to_string();
                }
            }
        });
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
        let _view = ScanView::new(services, library_service, jobs, palette);
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
        let mut view = ScanView::new(services, library_service, jobs, palette);
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
        let mut view = ScanView::new(services, library_service, jobs, palette);
        view.phase_done("cleanup");
        assert!(view.state.phase_states[0]);
    }
}
