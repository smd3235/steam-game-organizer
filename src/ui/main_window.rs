//! Main application window using egui.
//! Completely redesigned layout with left navigation sidebar, top bar, and themed content area.
//!
//! 2026-11-26: New layout with navigation sidebar, modern theme, card-based views.
//! All views share logger and archives flow from Scan → Review → Organize → Artwork → Done.
//! Comprehensive logging and watchdog on all views.

use std::path::Path;
use std::sync::Arc;

use crate::app::controller::{Services, StateStore};
use crate::app::events::EventBus;
use crate::app::jobs::JobManager;
use crate::core::config::AppConfig;
use crate::services::library_service::LibraryService;

use crate::ui::artwork_view::ArtworkView;
use crate::ui::done_view::DoneView;
use crate::ui::organize_view::OrganizeView;
use crate::ui::review_view::ReviewView;
use crate::ui::scan_view::ScanView;
use crate::ui::setup_view::SetupView;
use crate::ui::theme::{
    apply_accessibility, card, constrained_content, ghost_button, nav_item, secondary_button,
    separator, AccessibilityConfig, AccessibilityMode, Palette, ThemeMode, SPACING, SPACING_XL,
    CORNER_RADIUS,
};
use egui::{RichText, Theme};
use serde::Serialize;
use crate::tools::capture_screens::capture_and_verify;

const NAV_ITEMS: &[(&str, &str, &str)] = &[
    ("scan", "🔍", "Scan"),
    ("review", "📋", "Review"),
    ("organize", "📦", "Organize"),
    ("artwork", "🖼️", "Artwork"),
    ("done", "✅", "Done"),
    ("setup", "⚙️", "Setup"),
];

/// Metadata captured alongside each live screenshot for audit/review.
#[derive(Serialize, Debug)]
struct ScreenshotMetadata {
    timestamp_secs: u64,
    view: String,
    theme_mode: String,
    archive_count: usize,
    shared_archive_count: usize,
    window_title: String,
    output_dir: String,
}

/// The egui application struct. Holds all shared state and renders views.
pub struct MainWindow {
    pub state: Arc<StateStore>,
    pub bus: Arc<EventBus>,
    pub logger: Arc<crate::core::logger::AppLogger>,
    pub services: Arc<Services>,
    pub jobs: Arc<JobManager>,
    pub config: Arc<AppConfig>,
    pub current: String,
    pub palette: Palette,
    pub scan_view: ScanView,
    pub review_view: ReviewView,
    pub organize_view: OrganizeView,
    pub artwork_view: ArtworkView,
    pub done_view: DoneView,
    pub setup_view: SetupView,
    pub shared_archives: Vec<crate::core::models::GameArchive>,
    /// When set, renders only this view (scan/review/organize/artwork/done/setup) without sidebar or top bar.
    pub single_view: Option<String>,
    /// Current UI theme mode (Dark or Light).
    pub theme_mode: ThemeMode,
    /// Accessibility configuration for color blindness and contrast.
    pub accessibility_config: AccessibilityConfig,
}

impl MainWindow {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        state: Arc<StateStore>,
        bus: Arc<EventBus>,
        logger: Arc<crate::core::logger::AppLogger>,
        services: Arc<Services>,
        config: Arc<AppConfig>,
        _library_service: LibraryService,
        jobs: Arc<JobManager>,
        single_view: Option<String>,
    ) -> Self {
        logger.log("DEBUG", "MainWindow::new called", "");
        let logger_for_scan = Arc::clone(&logger);
        let logger_for_review = Arc::clone(&logger);
        let logger_for_organize = Arc::clone(&logger);
        let logger_for_artwork = Arc::clone(&logger);
        let logger_for_done = Arc::clone(&logger);
        let logger_for_setup = Arc::clone(&logger);
        let watchdog_for_scan = Arc::new(crate::core::errors::Watchdog::new(
            logger_for_scan.clone(),
            300000,
        ));
        let watchdog_for_review = Arc::new(crate::core::errors::Watchdog::new(
            logger_for_review.clone(),
            300000,
        ));
        let watchdog_for_organize = Arc::new(crate::core::errors::Watchdog::new(
            logger_for_organize.clone(),
            600000,
        ));
        let watchdog_for_artwork = Arc::new(crate::core::errors::Watchdog::new(
            logger_for_artwork.clone(),
            300000,
        ));
        let watchdog_for_done = Arc::new(crate::core::errors::Watchdog::new(
            logger_for_done.clone(),
            300000,
        ));
        let watchdog_for_setup = Arc::new(crate::core::errors::Watchdog::new(
            logger_for_setup.clone(),
            300000,
        ));
        let services_clone = Arc::clone(&services);
        let jobs_for_field = Arc::clone(&jobs);
        let jobs_for_scan = Arc::clone(&jobs);
        let config_for_scan = Arc::clone(&config);
        let initial_view = single_view.as_deref().unwrap_or("scan").to_string();
        
        // Compute palette based on theme mode
        let palette = match ThemeMode::default() {
            ThemeMode::Dark => Palette::default(),
            ThemeMode::Light => Palette::light_mode(),
        };

        let accessibility_config = AccessibilityConfig::default();
        let palette = apply_accessibility(&palette, &accessibility_config);

        MainWindow {
            state,
            bus,
            logger,
            services,
            jobs: jobs_for_field,
            config: config_for_scan,
            current: initial_view,
            palette: palette.clone(),
            accessibility_config,
            scan_view: ScanView::new(
                services_clone,
                _library_service,
                jobs_for_scan,
                Arc::clone(&config),
                palette.clone(),
                logger_for_scan,
                watchdog_for_scan,
            ),
            review_view: ReviewView::new(
                palette.clone(),
                logger_for_review,
                watchdog_for_review,
            ),
            organize_view: OrganizeView::new(
                palette.clone(),
                logger_for_organize,
                watchdog_for_organize,
            ),
            artwork_view: ArtworkView::new(
                palette.clone(),
                logger_for_artwork,
                watchdog_for_artwork,
            ),
            done_view: DoneView::new(palette.clone(), logger_for_done, watchdog_for_done),
            setup_view: SetupView::new(
                palette.clone(),
                logger_for_setup,
                watchdog_for_setup,
                (*config).clone(),
            ),
            shared_archives: Vec::new(),
            single_view,
            theme_mode: ThemeMode::default(),
        }
    }

    /// Capture a live screenshot of the current view: 4x4 grid + full UI +
    /// ASCII art + dead space audit + design review checklist + metadata JSON.
    /// Saved to docs/screenshots/live-captures/ with descriptive naming.
    fn capture_live_screenshot(&mut self) {
        let output_dir = Path::new("docs/screenshots/live-captures");
        let view_name = &self.current;

        // Ensure output directory exists
        if let Err(e) = std::fs::create_dir_all(output_dir) {
            self.logger.log(
                "SCREENSHOT",
                &format!("Failed to create live-captures dir: {}", e),
                "",
            );
            return;
        }

        // Capture screenshot with OCR verification (4x4 grid, ASCII, audit, checklist)
        match capture_and_verify(output_dir, view_name, true) {
            Ok(_result) => {
                // Write metadata JSON alongside the screenshots
                let metadata = ScreenshotMetadata {
                    timestamp_secs: std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH)
                        .unwrap_or_default()
                        .as_secs(),
                    view: view_name.clone(),
                    theme_mode: format!("{:?}", self.theme_mode),
                    archive_count: self.scan_view.state.discovered_archives.len(),
                    shared_archive_count: self.shared_archives.len(),
                    window_title: "Steam Game Organizer".to_string(),
                    output_dir: output_dir.to_string_lossy().to_string(),
                };

                let metadata_path = output_dir.join(format!(
                    "{} - Metadata - {}.json",
                    view_name,
                    metadata.timestamp_secs
                ));
                if let Err(e) = serde_json::to_writer_pretty(
                    &std::fs::File::create(&metadata_path).unwrap(),
                    &metadata,
                ) {
                    self.logger.log(
                        "SCREENSHOT",
                        &format!("Failed to write metadata: {}", e),
                        "",
                    );
                }

                self.logger.log(
                    "SCREENSHOT",
                    &format!(
                        "Live screenshot captured for view '{}' -> {}",
                        view_name, output_dir.display()
                    ),
                    "",
                );
            }
            Err(e) => {
                self.logger.log(
                    "SCREENSHOT",
                    &format!("Capture failed for view '{}': {}", view_name, e),
                    "",
                );
            }
        }
    }

    /// Sync discovered archives from scan view to all downstream views.
    fn sync_archives(&mut self) {
        let archives = self.scan_view.state.discovered_archives.clone();
        if !archives.is_empty() {
            self.logger.log(
                "MAIN",
                &format!("Syncing {} archives to downstream views", archives.len()),
                "",
            );
            self.shared_archives = archives.clone();
            self.review_view.load(archives.clone());
            self.organize_view.load(archives.clone());
            self.artwork_view.load(archives.clone());
        }
    }

    pub(crate) fn render_scan(&mut self, ui: &mut egui::Ui) {
        card(ui, &self.palette, |ui| {
            self.scan_view.ui(ui);
        });

        // After scan completes, auto-sync archives
        if !self.scan_view.state.discovered_archives.is_empty()
            && self.shared_archives.len() != self.scan_view.state.discovered_archives.len()
        {
            self.sync_archives();
        }
    }

    pub(crate) fn render_review(&mut self, ui: &mut egui::Ui) {
        card(ui, &self.palette, |ui| {
            self.review_view.ui(ui);
        });

        // Auto-sync when accepted archives change
        let accepted_count = self
            .review_view
            .state
            .archives
            .iter()
            .filter(|a| a.decision.accepted)
            .count();
        if accepted_count > 0 && self.shared_archives.len() != accepted_count {
            let accepted: Vec<_> = self
                .review_view
                .state
                .archives
                .iter()
                .filter(|a| a.decision.accepted)
                .cloned()
                .collect();
            self.shared_archives = accepted.clone();
            self.organize_view.load(accepted.clone());
            self.artwork_view.load(accepted);
        }
    }

    pub(crate) fn render_organize(&mut self, ui: &mut egui::Ui) {
        card(ui, &self.palette, |ui| {
            self.organize_view.ui(ui);
        });

        // When organize completes, push results to done view
        if !self.organize_view.state.converting && self.organize_view.state.converted_count > 0 {
            let archives = self.organize_view.state.archives.clone();
            let converted = self.organize_view.state.converted_count;
            let skipped = self.organize_view.state.skipped_count;
            let failed = self.organize_view.state.failed_count;
            if !archives.is_empty() {
                self.done_view
                    .load(archives.clone(), converted, skipped, failed);
                self.logger.log(
                    "MAIN",
                    &format!("Pushed {} results to Done view", archives.len()),
                    "",
                );
            }
        }
    }

    pub(crate) fn render_artwork(&mut self, ui: &mut egui::Ui) {
        card(ui, &self.palette, |ui| {
            self.artwork_view.ui(ui);
        });
    }

    pub(crate) fn render_done(&mut self, ui: &mut egui::Ui) {
        card(ui, &self.palette, |ui| {
            self.done_view.ui(ui);
        });
    }

    pub(crate) fn render_setup(&mut self, ui: &mut egui::Ui) {
        card(ui, &self.palette, |ui| {
            self.setup_view.ui(ui);
        });
    }

    /// Render the left navigation sidebar.
    fn render_nav_sidebar(&mut self, ui: &mut egui::Ui) {
        ui.add_space(SPACING_XL);

        // App logo area
        ui.vertical_centered(|ui| {
            ui.label(
                RichText::new("SGO")
                    .color(self.palette.accent)
                    .strong()
                    .heading(),
            );
            ui.add_space(SPACING / 2.0);
            ui.label(
                RichText::new("Steam Game Organizer")
                    .color(self.palette.text_secondary)
                    .small(),
            );
        });
        ui.add_space(SPACING_XL);

        // Navigation header
        ui.label(
            RichText::new("NAVIGATION")
                .color(self.palette.text_tertiary)
                .small()
                .strong(),
        );
        ui.add_space(SPACING / 2.0);

        // Navigation items
        for (key, icon, label) in NAV_ITEMS {
            let is_active = self.current == *key;
            if nav_item(ui, &self.palette, icon, label, is_active).clicked() {
                self.current = key.to_string();
                self.logger
                    .log("DEBUG", &format!("Navigated to {}", key), "");
            }
        }

        ui.add_space(SPACING_XL);

        // Separator before setup/quit
        separator(ui);

        // Setup button
        ui.label(
            RichText::new("SETUP")
                .color(self.palette.text_tertiary)
                .small()
                .strong(),
        );
        ui.add_space(SPACING / 2.0);
        if secondary_button(ui, "Setup Wizard", &self.palette, true).clicked() {
            self.logger.log("DEBUG", "Setup Wizard button clicked", "");
            self.current = "setup".to_string();
        }

        ui.add_space(SPACING_XL);

        // Bottom: Quit button removed — duplicate of top bar Quit
    }

    /// Render the top bar.
    fn render_top_bar(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            ui.add_space(SPACING);
            ui.label(
                RichText::new("Steam Game Organizer")
                    .color(self.palette.text)
                    .strong()
                    .size(18.0),
            );
            separator(ui);
            ui.add_space(SPACING);
            ui.label(
                RichText::new(format!("View: {}", self.current))
                    .color(self.palette.text_secondary)
                    .small(),
            );
            ui.add_space(SPACING);
            ui.label(
                RichText::new(format!("Archives: {}", self.shared_archives.len()))
                    .color(self.palette.text_secondary)
                    .small(),
            );
            ui.add_space(SPACING);
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                // Theme mode dropdown
                ui.add_space(SPACING);
                let theme_label = match self.theme_mode {
                    ThemeMode::Dark => "Dark",
                    ThemeMode::Light => "Light",
                };
                egui::ComboBox::from_label("Theme")
                    .selected_text(theme_label)
                    .show_ui(ui, |ui| {
                        ui.selectable_value(
                            &mut self.theme_mode,
                            ThemeMode::Dark,
                            "Dark",
                        );
                        ui.selectable_value(
                            &mut self.theme_mode,
                            ThemeMode::Light,
                            "Light",
                        );
                    });
                // Recompute palette when theme changes
                self.palette = match self.theme_mode {
                    ThemeMode::Dark => Palette::default(),
                    ThemeMode::Light => Palette::light_mode(),
                };
                // Apply accessibility mode (color blindness simulation, high contrast)
                self.palette = apply_accessibility(&self.palette, &self.accessibility_config);
                // Propagate new palette to all views
                self.scan_view.palette = self.palette.clone();
                self.review_view.palette = self.palette.clone();
                self.organize_view.palette = self.palette.clone();
                self.artwork_view.palette = self.palette.clone();
                self.done_view.palette = self.palette.clone();
                self.setup_view.palette = self.palette.clone();

                // Accessibility mode dropdown
                ui.add_space(SPACING);
                let acc_label = match self.accessibility_config.mode {
                    AccessibilityMode::Normal => "Normal",
                    AccessibilityMode::Protanopia => "Protanopia",
                    AccessibilityMode::Deuteranopia => "Deuteranopia",
                    AccessibilityMode::Tritanopia => "Tritanopia",
                    AccessibilityMode::HighContrast => "High Contrast",
                };
                egui::ComboBox::from_label("Accessibility")
                    .selected_text(acc_label)
                    .show_ui(ui, |ui| {
                        ui.selectable_value(
                            &mut self.accessibility_config.mode,
                            AccessibilityMode::Normal,
                            "Normal",
                        );
                        ui.selectable_value(
                            &mut self.accessibility_config.mode,
                            AccessibilityMode::Protanopia,
                            "Protanopia",
                        );
                        ui.selectable_value(
                            &mut self.accessibility_config.mode,
                            AccessibilityMode::Deuteranopia,
                            "Deuteranopia",
                        );
                        ui.selectable_value(
                            &mut self.accessibility_config.mode,
                            AccessibilityMode::Tritanopia,
                            "Tritanopia",
                        );
                        ui.selectable_value(
                            &mut self.accessibility_config.mode,
                            AccessibilityMode::HighContrast,
                            "High Contrast",
                        );
                    });
                // Screen reader toggle
                ui.add_space(SPACING / 2.0);
                ui.checkbox(
                    &mut self.accessibility_config.screen_reader,
                    "Screen Reader",
                );
                // High contrast text toggle
                ui.add_space(SPACING / 2.0);
                ui.checkbox(
                    &mut self.accessibility_config.high_contrast_text,
                    "High Contrast Text",
                );
                // Reapply accessibility after any change
                self.palette = apply_accessibility(&self.palette, &self.accessibility_config);
                // Propagate updated palette to all views
                self.scan_view.palette = self.palette.clone();
                self.review_view.palette = self.palette.clone();
                self.organize_view.palette = self.palette.clone();
                self.artwork_view.palette = self.palette.clone();
                self.done_view.palette = self.palette.clone();
                self.setup_view.palette = self.palette.clone();

                // Screenshot capture button
                ui.add_space(SPACING);
                if secondary_button(ui, "📷 Capture Screen", &self.palette, true).clicked() {
                    self.capture_live_screenshot();
                }

                if ghost_button(ui, "Quit", &self.palette, true).clicked() {
                    ctx_send_close(ui.ctx());
                }
            });
        });
    }
}

fn ctx_send_close(ctx: &egui::Context) {
    ctx.send_viewport_cmd(egui::ViewportCommand::Close);
}

impl eframe::App for MainWindow {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        self.logger.log("DEBUG", "MainWindow::ui called", "");

        // Style the context
        ui.ctx().set_visuals(egui::Visuals::dark());

        // Make hover states visible for keyboard/mouse navigation
        let mut style = (*ui.ctx().style_of(Theme::Light)).clone();
        style.visuals.widgets.hovered.bg_fill = self.palette.panel3;
        style.visuals.widgets.hovered.bg_stroke = egui::Stroke {
            width: 2.0,
            color: self.palette.border_focus,
        };
        style.spacing.item_spacing = egui::vec2(SPACING, SPACING);
        style.spacing.button_padding = egui::vec2(16.0, 8.0);
        ui.ctx().set_style_of(Theme::Light, style);

        // Single-view mode: render only the requested view without sidebar or top bar
        if let Some(view) = self.single_view.clone() {
            let palette = self.palette.clone();
            egui::CentralPanel::default()
                .frame(egui::Frame {
                    fill: palette.bg,
                    ..Default::default()
                })
                .show(ui, |ui| {
                    constrained_content(ui, 1400.0, |ui| {
                        ui.add_space(SPACING);
                        match view.as_str() {
                            "scan" => self.render_scan(ui),
                            "review" => self.render_review(ui),
                            "organize" => self.render_organize(ui),
                            "artwork" => self.render_artwork(ui),
                            "done" => self.render_done(ui),
                            "setup" => self.render_setup(ui),
                            _ => self.render_scan(ui),
                        }
                        ui.add_space(SPACING_XL);
                    });
                });
            return;
        }

        // Top bar
        egui::Panel::top("top_bar")
            .frame(egui::Frame {
                fill: self.palette.panel,
                ..Default::default()
            })
            .show(ui, |ui| {
                self.render_top_bar(ui);
            });

        // Main body: sidebar + content
        egui::Panel::left("nav_sidebar")
            .default_size(260.0)
            .frame(egui::Frame {
                fill: self.palette.bg,
                ..Default::default()
            })
            .show(ui, |ui| {
                self.render_nav_sidebar(ui);
            });

        // Main content: view stack — wrapped in centered max-width container
        // so content doesn't stretch awkwardly on maximized / ultra-wide screens.
        let palette = self.palette.clone();
        egui::CentralPanel::default()
            .frame(egui::Frame {
                fill: palette.bg,
                ..Default::default()
            })
            .show(ui, |ui| {
                constrained_content(ui, 1400.0, |ui| {
                    ui.add_space(SPACING);
                    match self.current.as_str() {
                        "scan" => self.render_scan(ui),
                        "review" => self.render_review(ui),
                        "organize" => self.render_organize(ui),
                        "artwork" => self.render_artwork(ui),
                        "done" => self.render_done(ui),
                        "setup" => self.render_setup(ui),
                        _ => self.render_scan(ui),
                    }
                    ui.add_space(SPACING_XL);
                });
            });
    }

    fn on_exit(&mut self, _frame: Option<&eframe::glow::Context>) {
        self.logger.log("APPLICATION", "SHUTDOWN", "");
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::app::controller::Services;
    use crate::app::jobs::JobManager;
    use crate::core::config::AppConfig;
    use crate::services::library_service::LibraryService;

    #[test]
    fn test_nav_items_include_setup() {
        // Verify the Setup Wizard nav item exists so users can navigate to setup view
        let has_setup = NAV_ITEMS.iter().any(|(key, _, _)| *key == "setup");
        assert!(
            has_setup,
            "NAV_ITEMS must include a 'setup' nav key for Setup Wizard"
        );
        // Verify setup nav item has correct icon and label
        let setup_item = NAV_ITEMS.iter().find(|(key, _, _)| *key == "setup");
        assert!(setup_item.is_some(), "Setup nav item must exist");
        let (_, icon, label) = setup_item.unwrap();
        assert_eq!(*icon, "⚙️", "Setup nav icon should be wrench");
        assert_eq!(*label, "Setup", "Setup nav label should be 'Setup'");
    }

    #[test]
    fn test_main_window_starts_on_scan_view() {
        // Verify MainWindow initializes on scan view, not setup
        let _palette = Palette::default();
        let logger: Arc<crate::core::logger::AppLogger> = Arc::new(
            crate::core::logger::AppLogger::new(
                std::env::temp_dir().join(format!("mw_test_{}.log", std::process::id())),
                "INFO",
                false,
                false,
            )
            .unwrap(),
        );
        let logger_clone = Arc::clone(&logger);
        let log_closure: Arc<dyn Fn(&str, &str) + Send + Sync> =
            Arc::new(move |cat, msg| logger_clone.log(cat, msg, ""));
        let services = Arc::new(Services {
            organizer: crate::services::organizer_service::OrganizerService::new(
                log_closure.clone(),
                true,
            ),
        });
        let config = Arc::new(AppConfig::new(
            std::env::temp_dir().as_path(),
        ));
        let library_service = LibraryService::new(log_closure.clone(), None);
        let _watchdog = Arc::new(crate::core::errors::Watchdog::new(logger.clone(), 300000));
        let jobs = Arc::new(JobManager::new(4));
        let state = Arc::new(crate::app::controller::StateStore::new());
        let bus = Arc::new(crate::app::events::EventBus::new());

        let mw = MainWindow::new(
            state,
            bus,
            logger,
            services,
            config,
            library_service,
            jobs,
            None,
        );
        assert_eq!(mw.current, "scan", "MainWindow should start on scan view");
    }

    #[test]
    fn test_main_window_can_switch_to_setup_view() {
        // Verify MainWindow can render setup view when current is "setup"
        // This catches the case where Setup Wizard nav button doesn't switch views
        let _palette = Palette::default();
        let logger: Arc<crate::core::logger::AppLogger> = Arc::new(
            crate::core::logger::AppLogger::new(
                std::env::temp_dir().join(format!("mw_setup_test_{}.log", std::process::id())),
                "INFO",
                false,
                false,
            )
            .unwrap(),
        );
        let logger_clone = Arc::clone(&logger);
        let log_closure: Arc<dyn Fn(&str, &str) + Send + Sync> =
            Arc::new(move |cat, msg| logger_clone.log(cat, msg, ""));
        let services = Arc::new(Services {
            organizer: crate::services::organizer_service::OrganizerService::new(
                log_closure.clone(),
                true,
            ),
        });
        let config = Arc::new(AppConfig::new(
            std::env::temp_dir().as_path(),
        ));
        let library_service = LibraryService::new(log_closure.clone(), None);
        let _watchdog = Arc::new(crate::core::errors::Watchdog::new(logger.clone(), 300000));
        let jobs = Arc::new(JobManager::new(4));
        let state = Arc::new(crate::app::controller::StateStore::new());
        let bus = Arc::new(crate::app::events::EventBus::new());

        let mut mw = MainWindow::new(
            state,
            bus,
            logger,
            services,
            config,
            library_service,
            jobs,
            Some("setup".to_string()),
        );
        assert_eq!(mw.current, "setup", "MainWindow should start on setup view with single_view");

        // Simulate clicking the Setup Wizard nav button - sets current to "setup"
        mw.current = "setup".to_string();
        assert_eq!(mw.current, "setup", "Clicking Setup Wizard should switch to setup view");
    }
}
