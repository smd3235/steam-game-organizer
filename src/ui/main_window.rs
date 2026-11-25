//! Main application window using egui.
//! Completely redesigned layout with left navigation sidebar, top bar, and themed content area.
//!
//! 2026-11-25: New layout with navigation sidebar, modern theme, card-based views.

#![allow(clippy::all)]

use std::sync::Arc;

use crate::app::controller::{Services, StateStore};
use crate::app::events::EventBus;
use crate::app::jobs::JobManager;
use crate::services::library_service::LibraryService;

use crate::ui::artwork_view::ArtworkView;
use crate::ui::done_view::DoneView;
use crate::ui::organize_view::OrganizeView;
use crate::ui::review_view::ReviewView;
use crate::ui::scan_view::ScanView;
use crate::ui::theme::{card, danger_button, secondary_button, Palette};

const NAV_ITEMS: &[(&str, &str)] = &[
    ("scan", "Scan"),
    ("review", "Review"),
    ("organize", "Organize"),
    ("artwork", "Artwork"),
    ("done", "Done"),
];

/// The egui application struct. Holds all shared state and renders views.
pub struct MainWindow {
    pub state: Arc<StateStore>,
    pub bus: Arc<EventBus>,
    pub logger: Arc<dyn Fn(&str, &str) + Send + Sync>,
    pub services: Arc<Services>,
    pub jobs: Arc<JobManager>,
    pub current: String,
    pub palette: Palette,
    pub scan_view: ScanView,
    pub review_view: ReviewView,
    pub organize_view: OrganizeView,
    pub artwork_view: ArtworkView,
    pub done_view: DoneView,
}

impl MainWindow {
    pub fn new(
        state: Arc<StateStore>,
        bus: Arc<EventBus>,
        logger: Arc<dyn Fn(&str, &str) + Send + Sync>,
        services: Arc<Services>,
        _library_service: LibraryService,
        jobs: Arc<JobManager>,
    ) -> Self {
        (logger)("DEBUG", "MainWindow::new called");
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
            ),
            review_view: ReviewView::new(Palette::default()),
            organize_view: OrganizeView::new(Palette::default()),
            artwork_view: ArtworkView::new(Palette::default()),
            done_view: DoneView::new(Palette::default()),
        }
    }

    pub(crate) fn render_scan(&mut self, ui: &mut egui::Ui) {
        card(ui, &self.palette, |ui| {
            self.scan_view.ui(ui);
        });
    }

    pub(crate) fn render_review(&mut self, ui: &mut egui::Ui) {
        card(ui, &self.palette, |ui| {
            self.review_view.ui(ui);
        });
    }

    pub(crate) fn render_organize(&mut self, ui: &mut egui::Ui) {
        card(ui, &self.palette, |ui| {
            self.organize_view.ui(ui);
        });
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

    /// Render the left navigation sidebar.
    fn render_nav_sidebar(&mut self, ui: &mut egui::Ui) {
        ui.vertical(|ui| {
            // App logo area
            ui.add_space(8.0);
            ui.label(
                egui::RichText::new("SGO")
                    .color(self.palette.accent)
                    .strong()
                    .heading(),
            );
            ui.label(
                egui::RichText::new("Steam Game Organizer")
                    .color(self.palette.muted)
                    .small(),
            );
            ui.add_space(16.0);

            // Navigation items
            ui.label(
                egui::RichText::new("NAVIGATION")
                    .color(self.palette.muted)
                    .small()
                    .strong(),
            );
            ui.add_space(4.0);

            for (key, label) in NAV_ITEMS {
                let is_active = self.current == *key;
                let bg = if is_active {
                    self.palette.accent.linear_multiply(0.15)
                } else {
                    self.palette.entry_bg
                };

                let rect = ui.min_rect();
                ui.painter().rect_filled(rect, 4.0, bg);

                let response = ui.selectable_label(is_active, *label);
                if response.clicked() {
                    self.current = key.to_string();
                    (self.logger)("DEBUG", &format!("Navigated to {}", key));
                }
            }

            ui.add_space(16.0);

            // Bottom: Quit button
            if danger_button(ui, "Quit", &self.palette).clicked() {
                ctx_send_close(ui.ctx());
            }
        });
    }

    /// Render the top bar.
    fn render_top_bar(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            ui.label(
                egui::RichText::new("Steam Game Organizer")
                    .color(self.palette.text)
                    .strong()
                    .size(18.0),
            );
            ui.separator();
            ui.label(
                egui::RichText::new(format!("view: {}", self.current))
                    .color(self.palette.muted)
                    .small(),
            );
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if secondary_button(ui, "Quit", &self.palette).clicked() {
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
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        (self.logger)("DEBUG", "MainWindow::update called");

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
            .default_width(200.0)
            .frame(egui::Frame {
                fill: self.palette.bg,
                ..Default::default()
            })
            .show(ctx, |ui| {
                self.render_nav_sidebar(ui);
            });

        // Main content: view stack inside a card
        egui::CentralPanel::default()
            .frame(egui::Frame {
                fill: self.palette.bg,
                ..Default::default()
            })
            .show(ctx, |ui| {
                // Add some padding
                ui.add_space(8.0);

                match self.current.as_str() {
                    "scan" => self.render_scan(ui),
                    "review" => self.render_review(ui),
                    "organize" => self.render_organize(ui),
                    "artwork" => self.render_artwork(ui),
                    "done" => self.render_done(ui),
                    _ => self.render_scan(ui),
                }
            });
    }
}
