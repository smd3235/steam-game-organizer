//! Done screen: final run summary with per-archive conversion results and action buttons.
//! Stub conversion of `ui/done_view.py` — new egui layout, not a Tkinter port.
//!
//! 2026-11-25: egui done view in the Rust conversion.

use egui::{RichText, ScrollArea};
use crate::ui::theme::{Palette, separator};

#[derive(Default)]
pub struct DoneViewState {
    pub archives: Vec<String>,
    pub status: String,
    pub converted: usize,
    pub skipped: usize,
    pub failed: usize,
}

impl DoneViewState {
    pub fn new() -> Self {
        DoneViewState {
            archives: Vec::new(),
            status: "No organization run yet.".to_string(),
            converted: 0,
            skipped: 0,
            failed: 0,
        }
    }
}

/// Done view — final run summary with per-archive results.
pub struct DoneView {
    pub state: DoneViewState,
    pub palette: Palette,
}

impl DoneView {
    pub fn new(palette: Palette) -> Self {
        DoneView {
            state: DoneViewState::new(),
            palette,
        }
    }

    pub fn ui(&mut self, ui: &mut egui::Ui) {
        separator(ui, &self.palette);

        // Header
        ui.heading("Done");
        ui.label("Organization Run Complete");
        ui.separator();

        // Summary counts
        ui.horizontal(|ui| {
            ui.label(RichText::new(format!("Converted: {}", self.state.converted)).color(self.palette.green));
            ui.separator();
            ui.label(RichText::new(format!("Skipped: {}", self.state.skipped)).color(self.palette.orange));
            ui.separator();
            ui.label(RichText::new(format!("Failed: {}", self.state.failed)).color(self.palette.red));
        });
        ui.separator();

        // Per-archive results
        ScrollArea::vertical().id_salt("done_results").show(ui, |ui| {
            for name in &self.state.archives {
                ui.horizontal(|ui| {
                    ui.label(RichText::new(name).small());
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        ui.label(RichText::new("converted").color(self.palette.green));
                    });
                });
            }
            if self.state.archives.is_empty() {
                ui.label(RichText::new("(no results yet)").color(self.palette.muted).italics());
            }
        });

        ui.separator();

        // Bottom actions
        ui.horizontal(|ui| {
            if ui.button("Undo").clicked() {
                self.state.status = "Undo clicked".to_string();
            }
            if ui.button("Open Library").clicked() {
                self.state.status = "Open Library clicked".to_string();
            }
            if ui.button("Scan Again").clicked() {
                self.state.status = "Scan Again clicked".to_string();
            }
        });

        ui.separator();
        ui.label(RichText::new(&self.state.status).color(self.palette.muted).small());
    }

    pub fn load(&mut self, archives: Vec<String>, converted: usize, skipped: usize, failed: usize) {
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
        let _view = DoneView::new(palette);
    }

    #[test]
    fn test_done_view_load() {
        let palette = Palette::default();
        let mut view = DoneView::new(palette);
        view.load(vec!["Game 1".to_string()], 1, 0, 0);
        assert_eq!(view.state.archives.len(), 1);
        assert_eq!(view.state.converted, 1);
        assert_eq!(view.state.skipped, 0);
        assert_eq!(view.state.failed, 0);
    }
}
