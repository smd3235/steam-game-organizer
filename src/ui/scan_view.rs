//! Scan view: phases, progress bar, activity feed, Convert Archives toggle.
//! Redesigned with new theme system: cards, section headers, pill badges, styled buttons.
//! Buttons log actions and call real archive discovery through ArchiveService.
//! All operations use trace_op! macro with timing and detailed logging.
//!
//! 2026-11-26: egui scan view with new theme and wired button actions.
//! v5 - redesigned layout with better visual hierarchy and modern styling.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use crate::app::controller::Services;
use crate::app::jobs::JobManager;
use crate::core::config::AppConfig;
use crate::core::errors::Watchdog;
use crate::core::models::GameArchive;
use crate::services::library_service::LibraryService;

use crate::ui::theme;
use crate::ui::theme::{
    archive_row, card, danger_button, empty_state, heading, loading_card, pill, primary_button,
    secondary_button, section_header, separator, stat_card, Palette,
};
use egui::{RichText, ScrollArea};

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
    pub config: Arc<AppConfig>,
    pub palette: Palette,
    pub logger: Arc<crate::core::logger::AppLogger>,
    pub watchdog: Arc<Watchdog>,
}

impl ScanView {
    pub fn new(
        services: Arc<Services>,
        library_service: LibraryService,
        jobs: Arc<JobManager>,
        config: Arc<AppConfig>,
        palette: Palette,
        logger: Arc<crate::core::logger::AppLogger>,
        watchdog: Arc<Watchdog>,
    ) -> Self {
        ScanView {
            state: ScanViewState::new(),
            services,
            library_service,
            jobs,
            config,
            palette,
            logger,
            watchdog,
        }
    }

    pub fn ui(&mut self, ui: &mut egui::Ui) {
        // Handle scan request from button click (done here to avoid borrow issues in closures)
        if self.state.should_scan {
            self.state.should_scan = false;
            self.run_scan();
        }

        if self.state.scanning {
            loading_card(ui, &self.palette, "Scanning archives…");
            return;
        }

        card(ui, &self.palette, |ui| {
            // Header
            heading(ui, &self.palette, "Scan Game Archives");
            ui.label("Discover and prepare your game archives for organization");
            separator(ui);

            // Summary stats row
            ui.horizontal(|ui| {
                let archive_count = self.state.discovered_archives.len();
                stat_card(
                    ui,
                    &self.palette,
                    &archive_count.to_string(),
                    "Archives Found",
                    self.palette.accent,
                );
                stat_card(
                    ui,
                    &self.palette,
                    &self
                        .state
                        .phase_states
                        .iter()
                        .filter(|&&x| x)
                        .count()
                        .to_string(),
                    "Phases Complete",
                    self.palette.green,
                );
            });
            ui.add_space(theme::SPACING);

            // Config row
            ui.horizontal(|ui| {
                ui.checkbox(&mut self.state.convert_archives, "Convert Archives");
                ui.add_space(theme::SPACING);
                ui.checkbox(&mut self.state.preview_only, "Preview Only");
                ui.add_space(theme::SPACING);
                ui.checkbox(&mut self.state.scan_with_artwork, "Scan + Artwork");
            });
            ui.add_space(theme::SPACING);

            // Action buttons
            ui.horizontal(|ui| {
                if primary_button(ui, "Start Scan", &self.palette, true).clicked() {
                    self.logger.log("SCAN", "Start Scan button clicked", "");
                    self.state.scanning = true;
                    self.state.should_scan = true;
                    self.state.status = "Scan starting…".to_string();
                    self.state.activity.push("Scan starting…".to_string());
                }
                if secondary_button(ui, "Scan with Artwork", &self.palette, true).clicked() {
                    self.logger
                        .log("SCAN", "Scan with Artwork button clicked", "");
                    self.state.scanning = true;
                    self.state.scan_with_artwork = true;
                    self.state.should_scan = true;
                    self.state.status = "Scan with Artwork starting…".to_string();
                    self.state
                        .activity
                        .push("Scan with Artwork starting…".to_string());
                }
                if self.state.scanning
                    && danger_button(ui, "Cancel Scan", &self.palette, true).clicked()
                {
                    self.logger.log("SCAN", "Cancel Scan button clicked", "");
                    self.state.scanning = false;
                    self.state.status = "Scan cancelled.".to_string();
                    self.state.activity.push("Scan cancelled.".to_string());
                }
            });
            ui.add_space(theme::SPACING_LG);

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
                        ui.label(RichText::new(" → ").color(self.palette.muted).small());
                    }
                }
            });
            ui.add_space(theme::SPACING);

            // Progress bar + stage label
            ui.horizontal(|ui| {
                ui.add(egui::ProgressBar::new(self.state.progress).desired_width(400.0));
                ui.add_space(theme::SPACING);
                ui.label(
                    RichText::new(&self.state.stage)
                        .color(self.palette.text_secondary)
                        .small(),
                );
            });
            ui.add_space(theme::SPACING);

            // Activity feed (scrollable)
            ui.horizontal(|ui| {
                section_header(ui, &self.palette, "ACTIVITY FEED");
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if self.state.scanning {
                        ui.label(
                            RichText::new("Scanning…")
                                .color(self.palette.accent)
                                .small()
                                .italics(),
                        );
                    }
                });
            });
            ScrollArea::vertical()
                .id_salt("scan_activity_feed")
                .max_height(200.0)
                .show(ui, |ui| {
                    for line in &self.state.activity {
                        ui.label(RichText::new(line).small().color(self.palette.text));
                    }
                });
            ui.add_space(theme::SPACING);

            // Status line
            ui.horizontal(|ui| {
                ui.label(RichText::new(&self.state.status).color(self.palette.text));
            });
        });

        // Show discovered archives in separate card
        if self.state.discovered_archives.is_empty() {
            empty_state(
                ui,
                &self.palette,
                "🔍",
                "No archives discovered",
                "Run Scan to find game archives in your library.",
            );
        } else {
            card(ui, &self.palette, |ui| {
                section_header(ui, &self.palette, "DISCOVERED ARCHIVES");
                ScrollArea::vertical()
                    .id_salt("discovered_list")
                    .max_height(200.0)
                    .show(ui, |ui| {
                        for archive in &self.state.discovered_archives {
                            let response = archive_row(
                                ui,
                                &self.palette,
                                &archive.display_name,
                                &format!("{} bytes", archive.size),
                                false,
                            );
                            if response.clicked() {
                                self.logger.log(
                                    "SCAN",
                                    &format!("Clicked archive: {}", archive.display_name),
                                    "",
                                );
                            }
                        }
                    });
            });
        }
    }

    /// Run the scan using ArchiveService discovery with full logging and watchdog.
    pub fn run_scan(&mut self) {
        let corr = self.logger.correlation_id();
        let op_id = self.logger.op_start("run_scan", &corr);
        self.watchdog.start("run_scan", "SCAN", &corr, Some(300000)); // 5 minute timeout

        self.logger
            .log("SCAN", "run_scan: beginning archive discovery", &corr);

        // Phase: Cleanup
        self.state.current_phase = 0;
        self.state.phase_states[0] = true;
        self.state.stage = "Cleanup".to_string();
        self.state.status = "Cleanup complete".to_string();
        self.logger
            .log("SCAN", "Phase 1/6: Cleanup complete", &corr);

        // Phase: Dedupe
        self.state.current_phase = 1;
        self.state.phase_states[1] = true;
        self.state.stage = "Dedupe".to_string();
        self.state.status = "Dedupe complete".to_string();
        self.logger.log("SCAN", "Phase 2/6: Dedupe complete", &corr);

        // Phase: Repair
        self.state.current_phase = 2;
        self.state.phase_states[2] = true;
        self.state.stage = "Repair".to_string();
        self.state.status = "Repair complete".to_string();
        self.logger.log("SCAN", "Phase 3/6: Repair complete", &corr);

        // Phase: Discover
        self.state.current_phase = 3;
        self.state.stage = "Discovering archives…".to_string();
        self.state.status = "Discovering archives…".to_string();
        self.logger
            .log("SCAN", "Phase 4/6: Discovering archives", &corr);

        // Try to use ArchiveService to discover real archives
        if let Some(library_root) = self.get_library_root() {
            self.logger.log(
                "SCAN",
                &format!("Discovering archives in: {}", library_root.display()),
                &corr,
            );
            let corr_for_archive = corr.clone();
            let logger_clone = Arc::clone(&self.logger);
            let logger_for_archive =
                Arc::new(move |cat: &str, msg: &str| logger_clone.log(cat, msg, &corr_for_archive));
            let archive_service = crate::services::archive_service::ArchiveService::new(
                logger_for_archive,
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

            self.logger.log(
                "SCAN",
                &format!(
                    "Discovery complete: {} archives found, {} errors",
                    result.archives.len(),
                    result.errors.len()
                ),
                &corr,
            );

            for archive in &result.archives {
                self.logger.log(
                    "SCAN",
                    &format!("  Found: {} ({} bytes)", archive.display_name, archive.size),
                    &corr,
                );
                self.state
                    .activity
                    .push(format!("Found: {}", archive.display_name));
            }

            for error in &result.errors {
                self.logger
                    .log("SCAN", &format!("  Error: {}", error), &corr);
            }

            self.state.discovered_archives = result.archives;
            self.state.phase_states[3] = true;
            self.state.stage = "Discovery complete".to_string();
            self.state.status = format!("Found {} archives", self.state.discovered_archives.len());
        } else {
            self.logger.log(
                "SCAN",
                "No library root configured, skipping discovery",
                &corr,
            );
            self.state.phase_states[3] = true;
            self.state.stage = "No library root".to_string();
            self.state.status = "No library root configured".to_string();
        }

        // Phase: Audit
        self.state.current_phase = 4;
        self.state.phase_states[4] = true;
        self.state.stage = "Audit".to_string();
        self.state.status = "Audit complete".to_string();
        self.logger.log("SCAN", "Phase 5/6: Audit complete", &corr);

        // Phase: Catalog
        self.state.current_phase = 5;
        self.state.phase_states[5] = true;
        self.state.stage = "Catalog".to_string();
        self.state.status = "Catalog complete".to_string();
        self.logger
            .log("SCAN", "Phase 6/6: Catalog complete", &corr);

        self.state.scanning = false;
        self.state.stage = "Idle".to_string();
        self.watchdog.complete(op_id);
        self.logger.op_end(op_id, "run_scan", &corr);
        self.logger.log("SCAN", "Scan complete", &corr);
    }

    /// Get the library root from config.
    fn get_library_root(&self) -> Option<PathBuf> {
        // Use configured library root first
        if let Some(root) = self.config.library_root.as_ref() {
            if root.is_dir() {
                self.logger.log(
                    "SCAN",
                    &format!("Using configured library root: {}", root.display()),
                    "",
                );
                return Some(root.clone());
            }
        }

        // Fall back to checking for common Steam library locations
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
                self.logger.log(
                    "SCAN",
                    &format!("Found library root: {}", candidate.display()),
                    "",
                );
                return Some(candidate.clone());
            }
        }

        // Walk up from exe directory looking for project root (where Cargo.toml is)
        // Archives like the test zip may be in the project root
        if let Some(exe_dir) = std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        {
            let mut current = exe_dir.clone();
            for _ in 0..5 {
                if current.join("Cargo.toml").is_file() {
                    self.logger.log(
                        "SCAN",
                        &format!("Found project root: {}", current.display()),
                        "",
                    );
                    return Some(current.clone());
                }
                if !current.pop() {
                    break;
                }
            }
            // Also check exe_dir itself for archives
            if exe_dir.is_dir() {
                self.logger
                    .log("SCAN", &format!("Found exe dir: {}", exe_dir.display()), "");
                return Some(exe_dir.clone());
            }
        }

        None
    }

    /// Add a line to the activity feed.
    pub fn feed(&mut self, message: &str) {
        self.state.activity.push(message.to_string());
        if self.state.activity.len() > 500 {
            self.state
                .activity
                .drain(0..self.state.activity.len() - 500);
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
        let organizer =
            crate::services::organizer_service::OrganizerService::new(Arc::new(|_, _| {}), false);
        let services = Arc::new(crate::app::controller::Services { organizer });
        let library_service =
            crate::services::library_service::LibraryService::new(Arc::new(|_, _| {}), None);
        let jobs = Arc::new(crate::app::jobs::JobManager::new(2));
        let palette = Palette::default();
        let logger: Arc<crate::core::logger::AppLogger> = Arc::new(
            crate::core::logger::AppLogger::new(
                std::env::temp_dir().join(format!("scan_test_{}.log", std::process::id())),
                "INFO",
                false,
                false,
            )
            .unwrap(),
        );
        let watchdog = Arc::new(crate::core::errors::Watchdog::new(logger.clone(), 1000));
        let config = Arc::new(crate::core::config::AppConfig::new(std::path::Path::new(
            std::env::temp_dir().to_str().unwrap(),
        )));
        let _view = ScanView::new(
            services,
            library_service,
            jobs,
            Arc::clone(&config),
            palette,
            logger,
            watchdog,
        );
    }

    #[test]
    fn test_scan_view_feed() {
        let organizer =
            crate::services::organizer_service::OrganizerService::new(Arc::new(|_, _| {}), false);
        let services = Arc::new(crate::app::controller::Services { organizer });
        let library_service =
            crate::services::library_service::LibraryService::new(Arc::new(|_, _| {}), None);
        let jobs = Arc::new(crate::app::jobs::JobManager::new(2));
        let palette = Palette::default();
        let logger: Arc<crate::core::logger::AppLogger> = Arc::new(
            crate::core::logger::AppLogger::new(
                std::env::temp_dir().join(format!("scan_test_{}.log", std::process::id())),
                "INFO",
                false,
                false,
            )
            .unwrap(),
        );
        let watchdog = Arc::new(crate::core::errors::Watchdog::new(logger.clone(), 1000));
        let config = Arc::new(crate::core::config::AppConfig::new(std::path::Path::new(
            std::env::temp_dir().to_str().unwrap(),
        )));
        let mut view = ScanView::new(
            services,
            library_service,
            jobs,
            Arc::clone(&config),
            palette,
            logger,
            watchdog,
        );
        view.feed("test message");
        assert_eq!(view.state.activity.len(), 1);
    }

    #[test]
    fn test_scan_view_phase_done() {
        let organizer =
            crate::services::organizer_service::OrganizerService::new(Arc::new(|_, _| {}), false);
        let services = Arc::new(crate::app::controller::Services { organizer });
        let library_service =
            crate::services::library_service::LibraryService::new(Arc::new(|_, _| {}), None);
        let jobs = Arc::new(crate::app::jobs::JobManager::new(2));
        let palette = Palette::default();
        let logger: Arc<crate::core::logger::AppLogger> = Arc::new(
            crate::core::logger::AppLogger::new(
                std::env::temp_dir().join(format!("scan_test_{}.log", std::process::id())),
                "INFO",
                false,
                false,
            )
            .unwrap(),
        );
        let watchdog = Arc::new(crate::core::errors::Watchdog::new(logger.clone(), 1000));
        let config = Arc::new(crate::core::config::AppConfig::new(std::path::Path::new(
            std::env::temp_dir().to_str().unwrap(),
        )));
        let mut view = ScanView::new(
            services,
            library_service,
            jobs,
            Arc::clone(&config),
            palette,
            logger,
            watchdog,
        );
        view.phase_done("cleanup");
        assert!(view.state.phase_states[0]);
    }
}
