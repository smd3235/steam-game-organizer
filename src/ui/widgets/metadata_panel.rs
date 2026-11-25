//! Metadata panel: Steam match details (title, AppID, release date, confidence, score, suggested category).
//! Stub conversion of `ui/widgets/metadata_panel.py` — egui grid layout, not Tkinter.
//!
//! 2026-11-25: egui metadata panel stub in the Rust conversion.

use egui::{RichText, Ui};
use crate::ui::theme::Palette;

#[derive(Default)]
pub struct MetadataPanelState {
    pub steam_title: String,
    pub appid: String,
    pub release: String,
    pub confidence: String,
    pub score: String,
    pub suggested: String,
    pub genres: String,
    pub categories: String,
    pub tags: String,
    pub developer: String,
    pub publisher: String,
    pub archive_name: String,
    pub size_text: String,
}

pub struct MetadataPanel {
    pub state: MetadataPanelState,
    pub palette: Palette,
}

impl MetadataPanel {
    pub fn new(palette: Palette) -> Self {
        MetadataPanel {
            state: MetadataPanelState::default(),
            palette,
        }
    }

    pub fn ui(&mut self, ui: &mut Ui) {
        ui.group(|ui| {
            ui.label(RichText::new("Steam Details").strong().color(self.palette.accent_hi));
            ui.separator();

            ui.horizontal(|ui| {
                ui.label(RichText::new("Steam Title:").small().color(self.palette.muted));
                ui.label(&self.state.steam_title);
            });
            ui.horizontal(|ui| {
                ui.label(RichText::new("AppID:").small().color(self.palette.muted));
                ui.label(&self.state.appid);
            });
            ui.horizontal(|ui| {
                ui.label(RichText::new("Release:").small().color(self.palette.muted));
                ui.label(&self.state.release);
            });
            ui.horizontal(|ui| {
                ui.label(RichText::new("Confidence:").small().color(self.palette.muted));
                ui.label(&self.state.confidence);
            });
            ui.horizontal(|ui| {
                ui.label(RichText::new("Score:").small().color(self.palette.muted));
                ui.label(&self.state.score);
            });
            ui.horizontal(|ui| {
                ui.label(RichText::new("Suggested:").small().color(self.palette.muted));
                ui.label(&self.state.suggested);
            });
            ui.separator();
            ui.horizontal(|ui| {
                ui.label(RichText::new("Genres:").small().color(self.palette.muted));
                ui.label(&self.state.genres);
            });
            ui.horizontal(|ui| {
                ui.label(RichText::new("Categories:").small().color(self.palette.muted));
                ui.label(&self.state.categories);
            });
            if !self.state.tags.is_empty() {
                ui.horizontal(|ui| {
                    ui.label(RichText::new("Tags:").small().color(self.palette.muted));
                    ui.label(&self.state.tags);
                });
            }
            ui.horizontal(|ui| {
                ui.label(RichText::new("Developer:").small().color(self.palette.muted));
                ui.label(&self.state.developer);
            });
            ui.horizontal(|ui| {
                ui.label(RichText::new("Publisher:").small().color(self.palette.muted));
                ui.label(&self.state.publisher);
            });
            ui.separator();
            ui.horizontal(|ui| {
                ui.label(RichText::new("Archive:").small().color(self.palette.muted));
                ui.label(&self.state.archive_name);
            });
            ui.horizontal(|ui| {
                ui.label(RichText::new("Size:").small().color(self.palette.muted));
                ui.label(&self.state.size_text);
            });
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_metadata_panel_new() {
        let palette = Palette::default();
        let _panel = MetadataPanel::new(palette);
    }

    #[test]
    fn test_metadata_panel_ui() {
        let palette = Palette::default();
        let mut panel = MetadataPanel::new(palette);
        panel.state.steam_title = "Test Game".to_string();
        panel.state.appid = "12345".to_string();
        panel.state.size_text = "100 MB".to_string();
        // UI rendering skipped - requires valid egui context
    }
}
