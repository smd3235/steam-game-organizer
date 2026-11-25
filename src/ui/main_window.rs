//! Main application window using egui.
//! Holds references to the controller, event bus, job manager, and services,
//! and renders a view stack: scan, review, organize, artwork, done.
//!
//! 2026-11-25: egui main window in the Rust conversion.

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
use crate::ui::theme::{Palette, separator};

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

    fn render_scan(&mut self, ui: &mut egui::Ui) {
        separator(ui, &self.palette);
        self.scan_view.ui(ui);
    }

    fn render_review(&mut self, ui: &mut egui::Ui) {
        separator(ui, &self.palette);
        self.review_view.ui(ui);
    }

    fn render_organize(&mut self, ui: &mut egui::Ui) {
        separator(ui, &self.palette);
        self.organize_view.ui(ui);
    }

    fn render_artwork(&mut self, ui: &mut egui::Ui) {
        separator(ui, &self.palette);
        self.artwork_view.ui(ui);
    }

    fn render_done(&mut self, ui: &mut egui::Ui) {
        separator(ui, &self.palette);
        self.done_view.ui(ui);
    }
}

impl eframe::App for MainWindow {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        // Top bar: app title + current view
        egui::TopBottomPanel::top("top_bar").show(ctx, |ui| {
            ui.horizontal(|ui| {
                ui.heading("Steam Game Organizer");
                ui.separator();
                ui.label(format!("view: {}", self.current));
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if ui.button("Quit").clicked() {
                        ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                    }
                });
            });
        });

        // Main content: view stack
        egui::CentralPanel::default().show(ctx, |ui| {
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

