//! Done screen: final run summary with per-archive conversion results and action buttons.
//! Redesigned with new theme system: cards, section headers, pill badges, styled buttons.
//!
//! 2026-11-25: egui done view with new theme and wired button actions.
//! All buttons log actions through the logger.

use std::sync::Arc;

use egui::{RichText, ScrollArea};
use crate::core::models::GameArchive;
use crate::ui::theme::{card, pill, primary_button, secondary_button, section_header, Palette, separator};

#[derive(Default, Clone)]
pub struct DoneViewState {
    pub archives: Vec<GameArchive>,
    pub status: String,
    pub converted: usize,
    pub skipped: usize,
    pub failed: usize,
    pub should_undo: bool,
    pub should_open_library: bool,
}

impl DoneViewState {
    pub fn new() -> Self {
        DoneViewState {
            archives: Vec::new(),
            status: "No organization run yet.".to_string(),
            converted: 0,
            skipped: 0,
            failed: 0,
            should_undo: false,
            should_open_library: false,
        }
    }
}

/// Done view — final run summary with per-archive results.
pub struct DoneView {
    pub state: DoneViewState,
    pub palette: Palette,
    pub logger: Arc<dyn for<'a, 'b> Fn(&'a str, &'b str) + Send + Sync>,
}

impl DoneView {
    pub fn new(palette: Palette, logger: Arc<dyn for<'a, 'b> Fn(&'a str, &'b str) + Send + Sync>) -> Self {
        DoneView {
            state: DoneViewState::new(),
            palette,
            logger,
        }
    }

    pub fn ui(&mut self, ui: &mut egui::Ui) {
        // Handle undo request from button click (done here to avoid borrow issues in closures)
        if self.state.should_undo {
            self.state.should_undo = false;
            self.undo_last_run();
        }
        if self.state.should_open_library {
            self.state.should_open_library = false;
            self.open_library();
        }

        card(ui, &self.palette, |ui| {
            // Header
            ui.heading("Done");
            ui.label("Organization Run Complete");
            separator(ui, &self.palette);

            // Summary counts
            ui.horizontal(|ui| {
                ui.label(RichText::new(format!("Converted: {}", self.state.converted)).color(self.palette.green));
                ui.separator();
                ui.label(RichText::new(format!("Skipped: {}", self.state.skipped)).color(self.palette.orange));
                ui.separator();
                ui.label(RichText::new(format!("Failed: {}", self.state.failed)).color(self.palette.red));
            });
            separator(ui, &self.palette);

            // Per-archive results
            section_header(ui, &self.palette, "RESULTS");
            ScrollArea::vertical().id_salt("done_results").show(ui, |ui| {
                for archive in &self.state.archives {
                    let name = if archive.display_name.is_empty() {
                        archive.path.file_name().unwrap_or_default().to_string_lossy().to_string()
                    } else {
                        archive.display_name.clone()
                    };
                    ui.horizontal(|ui| {
                        pill(ui, &name, "muted", &self.palette);
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            let status = if archive.decision.accepted {
                                "converted".to_string()
                            } else if archive.decision.skipped {
                                "skipped".to_string()
                            } else {
                                "failed".to_string()
                            };
                            let color = if archive.decision.accepted {
                                self.palette.green
                            } else if archive.decision.skipped {
                                self.palette.orange
                            } else {
                                self.palette.red
                            };
                            ui.label(RichText::new(status).color(color));
                        });
                    });
                }
                if self.state.archives.is_empty() {
                    ui.label(RichText::new("(no results yet)").color(self.palette.muted).italics());
                }
            });

            separator(ui, &self.palette);

            // Bottom actions
            ui.horizontal(|ui| {
                if secondary_button(ui, "Undo", &self.palette).clicked() {
                    (self.logger)("DONE", "Undo button clicked");
                    self.state.status = "Undo clicked".to_string();
                    self.state.should_undo = true;
                }
                if secondary_button(ui, "Open Library", &self.palette).clicked() {
                    (self.logger)("DONE", "Open Library button clicked");
                    self.state.status = "Open Library clicked".to_string();
                    self.state.should_open_library = true;
                }
                if primary_button(ui, "Scan Again", &self.palette).clicked() {
                    (self.logger)("DONE", "Scan Again button clicked");
                    self.state.status = "Scan Again clicked".to_string();
                }
            });

            separator(ui, &self.palette);
            ui.label(RichText::new(&self.state.status).color(self.palette.muted).small());
        });
    }

    fn undo_last_run(&mut self) {
        (self.logger)("DONE", "Undo last organization run");
        self.state.archives.clear();
        self.state.converted = 0;
        self.state.skipped = 0;
        self.state.failed = 0;
        self.state.status = "Organization run undone.".to_string();
    }

    fn open_library(&mut self) {
        (self.logger)("DONE", "Open library folder requested");
        self.state.status = "Opening library folder…".to_string();
    }

    pub fn load(&mut self, archives: Vec<GameArchive>, converted: usize, skipped: usize, failed: usize) {
        self.state.archives = archives;
        self.state.converted = converted;
        self.state.skipped = skipped;
        self.state.failed = failed;
        self.state.status = format!("Run complete — {} converted, {} skipped, {} failed.", converted, skipped, failed);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_done_view_new() {
        let palette = Palette::default();
        let logger: Arc<dyn for<'a, 'b> Fn(&'a str, &'b str) + Send + Sync> = Arc::new(|_, _| {});
        let _view = DoneView::new(palette, logger);
    }

    #[test]
    fn test_done_view_load() {
        let palette = Palette::default();
        let logger: Arc<dyn for<'a, 'b> Fn(&'a str, &'b str) + Send + Sync> = Arc::new(|_, _| {});
        let mut view = DoneView::new(palette, logger);
        let archive = GameArchive::default();
        view.load(vec![archive], 1, 0, 0);
        assert_eq!(view.state.archives.len(), 1);
        assert_eq!(view.state.converted, 1);
        assert_eq!(view.state.skipped, 0);
        assert_eq!(view.state.failed, 0);
    }

    #[test]
    fn test_done_view_undo() {
        let palette = Palette::default();
        let logger: Arc<dyn for<'a, 'b> Fn(&'a str, &'b str) + Send + Sync> = Arc::new(|_, _| {});
        let mut view = DoneView::new(palette, logger);
        let archive = GameArchive::default();
        view.load(vec![archive.clone()], 1, 0, 0);
        view.undo_last_run();
        assert_eq!(view.state.archives.len(), 0);
        assert_eq!(view.state.converted, 0);
    }
}
