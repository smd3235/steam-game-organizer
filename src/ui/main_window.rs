//! Main application window using egui.
//! Completely redesigned layout with left navigation sidebar, top bar, and themed content area.
//!
//! 2026-11-26: New layout with navigation sidebar, modern theme, card-based views.
//! All views share logger and archives flow from Scan → Review → Organize → Artwork → Done.
//! Comprehensive logging and watchdog on all views.

#![allow(clippy::all)]

use std::sync::Arc;

use crate::app::controller::{Services, StateStore};
use crate::app::events::EventBus;
use crate::app::jobs::JobManager;
use crate::services::library_service::LibraryService;
use crate::core::errors::Watchdog;

use crate::ui::artwork_view::ArtworkView;
use crate::ui::done_view::DoneView;
use crate::ui::organize_view::OrganizeView;
use crate::ui::review_view::ReviewView;
use crate::ui::scan_view::ScanView;
use crate::ui::setup_view::SetupView;
use egui::{RichText, Vec2};
use crate::ui::theme as theme;
use crate::ui::theme::{
    body_text, card, danger_button, ghost_button, heading, nav_item, primary_button, secondary_button,
    separator, SPACING, SPACING_LG, SPACING_XL, Palette,
};

const NAV_ITEMS: &[(&str, &str, &str)] = &[
    ("scan", "🔍", "Scan"),
    ("review", "📋", "Review"),
    ("organize", "📦", "Organize"),
    ("artwork", "🖼️", "Artwork"),
    ("done", "✅", "Done"),
    ("setup", "⚙️", "Setup"),
];

/// The egui application struct. Holds all shared state and renders views.
pub struct MainWindow {
    pub state: Arc<StateStore>,
    pub bus: Arc<EventBus>,
    pub logger: Arc<crate::core::logger::AppLogger>,
    pub services: Arc<Services>,
    pub jobs: Arc<JobManager>,
    pub current: String,
    pub palette: Palette,
    pub scan_view: ScanView,
    pub review_view: ReviewView,
    pub organize_view: OrganizeView,
    pub artwork_view: ArtworkView,
    pub done_view: DoneView,
    pub setup_view: SetupView,
    pub shared_archives: Vec<crate::core::models::GameArchive>,
}

impl MainWindow {
    pub fn new(
        state: Arc<StateStore>,
        bus: Arc<EventBus>,
        logger: Arc<crate::core::logger::AppLogger>,
        services: Arc<Services>,
        _library_service: LibraryService,
        jobs: Arc<JobManager>,
    ) -> Self {
        logger.log("DEBUG", "MainWindow::new called", "");
        let logger_for_scan = Arc::clone(&logger);
        let logger_for_review = Arc::clone(&logger);
        let logger_for_organize = Arc::clone(&logger);
        let logger_for_artwork = Arc::clone(&logger);
        let logger_for_done = Arc::clone(&logger);
        let logger_for_setup = Arc::clone(&logger);
        let watchdog_for_scan = Arc::new(crate::core::errors::Watchdog::new(logger_for_scan.clone(), 300000));
        let watchdog_for_review = Arc::new(crate::core::errors::Watchdog::new(logger_for_review.clone(), 300000));
        let watchdog_for_organize = Arc::new(crate::core::errors::Watchdog::new(logger_for_organize.clone(), 600000));
        let watchdog_for_artwork = Arc::new(crate::core::errors::Watchdog::new(logger_for_artwork.clone(), 300000));
        let watchdog_for_done = Arc::new(crate::core::errors::Watchdog::new(logger_for_done.clone(), 300000));
        let watchdog_for_setup = Arc::new(crate::core::errors::Watchdog::new(logger_for_setup.clone(), 300000));
        let services_clone = Arc::clone(&services);
        let jobs_for_field = Arc::clone(&jobs);
        let jobs_for_scan = Arc::clone(&jobs);
        MainWindow {
            state,
            bus,
            logger,
            services,
            jobs: jobs_for_field,
            current: "scan".to_string(),
            palette: Palette::default(),
            scan_view: ScanView::new(
                services_clone,
                _library_service,
                jobs_for_scan,
                Palette::default(),
                logger_for_scan,
                watchdog_for_scan,
            ),
            review_view: ReviewView::new(Palette::default(), logger_for_review, watchdog_for_review),
            organize_view: OrganizeView::new(Palette::default(), logger_for_organize, watchdog_for_organize),
            artwork_view: ArtworkView::new(Palette::default(), logger_for_artwork, watchdog_for_artwork),
            done_view: DoneView::new(Palette::default(), logger_for_done, watchdog_for_done),
            setup_view: SetupView::new(Palette::default(), logger_for_setup, watchdog_for_setup),
            shared_archives: Vec::new(),
        }
    }

    /// Sync discovered archives from scan view to all downstream views.
    fn sync_archives(&mut self) {
        let archives = self.scan_view.state.discovered_archives.clone();
        if !archives.is_empty() {
            self.logger.log("MAIN", &format!("Syncing {} archives to downstream views", archives.len()), "");
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
        let accepted_count = self.review_view.state.archives.iter()
            .filter(|a| a.decision.accepted).count();
        if accepted_count > 0 && self.shared_archives.len() != accepted_count {
            let accepted: Vec<_> = self.review_view.state.archives.iter()
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
                self.done_view.load(archives.clone(), converted, skipped, failed);
                self.logger.log("MAIN", &format!("Pushed {} results to Done view", archives.len()), "");
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
        ui.add_space(theme::SPACING_XL);

        // App logo area
        ui.vertical_centered(|ui| {
            ui.label(RichText::new("SGO").color(self.palette.accent).strong().heading());
            ui.add_space(theme::SPACING / 2.0);
            ui.label(RichText::new("Steam Game Organizer")
                .color(self.palette.text_secondary)
                .small());
        });
        ui.add_space(theme::SPACING_XL);

        // Navigation header
        ui.label(RichText::new("NAVIGATION")
            .color(self.palette.text_tertiary)
            .small()
            .strong());
        ui.add_space(theme::SPACING / 2.0);

        // Navigation items
        for (key, icon, label) in NAV_ITEMS {
            let is_active = self.current == *key;
            nav_item(ui, &self.palette, icon, label, is_active);
            if ui.add(egui::Button::new(RichText::new(format!("{}  {}", icon, label)).color(
                if is_active { self.palette.accent } else { self.palette.text_secondary }
            ).strong())
            .corner_radius(theme::SMALL_RADIUS)
            .min_size(Vec2::new(0.0, 0.0))
            .frame(false)).clicked() {
                self.current = key.to_string();
                self.logger.log("DEBUG", &format!("Navigated to {}", key), "");
            }
        }

        ui.add_space(theme::SPACING_XL);

        // Separator before setup/quit
        separator(ui, &self.palette);

        // Setup button
        ui.label(RichText::new("SETUP")
            .color(self.palette.text_tertiary)
            .small()
            .strong());
        ui.add_space(theme::SPACING / 2.0);
        if secondary_button(ui, "Setup Wizard", &self.palette).clicked() {
            self.logger.log("DEBUG", "Setup Wizard button clicked", "");
            self.current = "setup".to_string();
        }

        ui.add_space(theme::SPACING_XL);

        // Bottom: Quit button
        if ghost_button(ui, "Quit", &self.palette).clicked() {
            ctx_send_close(ui.ctx());
        }
    }

    /// Render the top bar.
    fn render_top_bar(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            ui.add_space(theme::SPACING);
            ui.label(
                RichText::new("Steam Game Organizer")
                    .color(self.palette.text)
                    .strong()
                    .size(18.0),
            );
            ui.separator();
            ui.add_space(theme::SPACING);
            ui.label(RichText::new(format!("View: {}", self.current))
                .color(self.palette.text_secondary)
                .small());
            ui.add_space(theme::SPACING);
            ui.label(RichText::new(format!("Archives: {}", self.shared_archives.len()))
                .color(self.palette.text_secondary)
                .small());
            ui.add_space(theme::SPACING);
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if ghost_button(ui, "Quit", &self.palette).clicked() {
                    ctx_send_close(ui.ctx());
                }
            });
        });
    }

    /// Render a view header with title and description.
    fn render_view_header(&mut self, ui: &mut egui::Ui, title: &str, subtitle: &str) {
        heading(ui, &self.palette, title);
        body_text(ui, &self.palette, subtitle);
        separator(ui, &self.palette);
    }
}

fn ctx_send_close(ctx: &egui::Context) {
    ctx.send_viewport_cmd(egui::ViewportCommand::Close);
}

impl eframe::App for MainWindow {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.logger.log("DEBUG", "MainWindow::update called", "");

        // Style the context
        ctx.set_visuals(egui::Visuals::dark());

        // Top bar
        egui::TopBottomPanel::top("top_bar")
            .frame(egui::Frame {
                fill: self.palette.panel,
                ..Default::default()
            })
            .show(ctx, |ui| {
                self.render_top_bar(ui);
            });

        // Main body: sidebar + content
        egui::SidePanel::left("nav_sidebar")
            .default_width(220.0)
            .frame(egui::Frame {
                fill: self.palette.bg,
                ..Default::default()
            })
            .show(ctx, |ui| {
                self.render_nav_sidebar(ui);
            });

        // Main content: view stack
        egui::CentralPanel::default()
            .frame(egui::Frame {
                fill: self.palette.bg,
                ..Default::default()
            })
            .show(ctx, |ui| {
                ui.add_space(theme::SPACING);
                match self.current.as_str() {
                    "scan" => self.render_scan(ui),
                    "review" => self.render_review(ui),
                    "organize" => self.render_organize(ui),
                    "artwork" => self.render_artwork(ui),
                    "done" => self.render_done(ui),
                    "setup" => self.render_setup(ui),
                    _ => self.render_scan(ui),
                }
                ui.add_space(theme::SPACING_XL);
            });
    }

    fn on_exit(&mut self, _frame: Option<&eframe::glow::Context>) {
        self.logger.log("APPLICATION", "SHUTDOWN", "");
    }
}