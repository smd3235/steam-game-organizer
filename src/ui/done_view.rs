//! Done screen: final run summary with per-archive conversion results and action buttons.
//! Redesigned with new theme system: cards, section headers, pill badges, styled buttons.
//!
//! 2026-11-25: egui done view with new theme.

use egui::{RichText, ScrollArea};
use crate::ui::theme::{card, pill, primary_button, secondary_button, section_header, Palette, separator};

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
                for name in &self.state.archives {
                    pill(ui, name, "muted", &self.palette);
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        ui.label(RichText::new("converted").color(self.palette.green));
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
                    self.state.status = "Undo clicked".to_string();
                }
                if secondary_button(ui, "Open Library", &self.palette).clicked() {
                    self.state.status = "Open Library clicked".to_string();
                }
                if primary_button(ui, "Scan Again", &self.palette).clicked() {
                    self.state.status = "Scan Again clicked".to_string();
                }
            });

            separator(ui, &self.palette);
            ui.label(RichText::new(&self.state.status).color(self.palette.muted).small());
        });
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
