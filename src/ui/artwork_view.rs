//! Artwork review screen: shows each accepted game's downloaded artwork assets.
//! Redesigned with new theme system: cards, section headers, pill badges, styled buttons.
//!
//! 2026-11-25: egui artwork view with new theme.

use egui::{RichText, ScrollArea};
use crate::ui::theme::{card, secondary_button, section_header, Palette, separator};

#[derive(Default)]
pub struct ArtworkViewState {
    pub archives: Vec<String>,
    pub selected_index: Option<usize>,
    pub status: String,
}

impl ArtworkViewState {
    pub fn new() -> Self {
        ArtworkViewState {
            archives: Vec::new(),
            selected_index: None,
            status: "No artwork downloaded yet.".to_string(),
        }
    }
}

/// Artwork view — per-game artwork cards with Open Game Folder button.
pub struct ArtworkView {
    pub state: ArtworkViewState,
    pub palette: Palette,
}

impl ArtworkView {
    pub fn new(palette: Palette) -> Self {
        ArtworkView {
            state: ArtworkViewState::new(),
            palette,
        }
    }

    pub fn ui(&mut self, ui: &mut egui::Ui) {
        card(ui, &self.palette, |ui| {
            // Header
            ui.heading("Artwork & Steam Assets");
            separator(ui, &self.palette);

            // Summary
            ui.label(RichText::new(&self.state.status).color(self.palette.muted).small());
            separator(ui, &self.palette);

            // Archive grid
            section_header(ui, &self.palette, "ARCHIVES");
            ScrollArea::vertical().id_salt("artwork_grid").show(ui, |ui| {
                egui::Grid::new("artwork_grid").num_columns(3).spacing([20.0, 20.0]).show(ui, |ui| {
                    for (i, name) in self.state.archives.iter().enumerate() {
                        ui.vertical(|ui| {
                            ui.label(RichText::new(name).small().strong());
                            separator(ui, &self.palette);
                            if secondary_button(ui, "Open Folder", &self.palette).clicked() {
                                self.state.status = format!("Opened folder for {}", name);
                            }
                        });
                        if i < self.state.archives.len() - 1 {
                            ui.end_row();
                        }
                    }
                    if self.state.archives.is_empty() {
                        ui.label(RichText::new("(no artwork downloaded yet)").color(self.palette.muted).italics());
                    }
                });
            });

            separator(ui, &self.palette);

            // Bottom actions
            ui.horizontal(|ui| {
                if secondary_button(ui, "Scan Again", &self.palette).clicked() {
                    self.state.status = "Scan Again clicked".to_string();
                }
                if secondary_button(ui, "Review", &self.palette).clicked() {
                    self.state.status = "Review clicked".to_string();
                }
            });
        });
    }

    pub fn load(&mut self, archives: Vec<String>) {
        self.state.archives = archives;
        self.state.selected_index = if !self.state.archives.is_empty() { Some(0) } else { None };
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_artwork_view_new() {
        let palette = Palette::default();
        let _view = ArtworkView::new(palette);
    }

    #[test]
    fn test_artwork_view_load() {
        let palette = Palette::default();
        let mut view = ArtworkView::new(palette);
        view.load(vec!["Game 1".to_string(), "Game 2".to_string()]);
        assert_eq!(view.state.archives.len(), 2);
        assert_eq!(view.state.selected_index, Some(0));
    }
}
