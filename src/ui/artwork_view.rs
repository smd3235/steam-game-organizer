//! Artwork review screen: shows each accepted game's downloaded artwork assets.
//! Stub conversion of `ui/artwork_view.py` — new egui layout, not a Tkinter port.
//!
//! 2026-11-25: egui artwork view in the Rust conversion.

use egui::{RichText, ScrollArea};
use crate::ui::theme::{Palette, separator};

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
        separator(ui, &self.palette);

        // Header
        ui.heading("Artwork & Steam Assets");
        ui.separator();

        // Summary
        ui.label(RichText::new(&self.state.status).color(self.palette.muted).small());
        ui.separator();

        // Archive grid
        ScrollArea::vertical().id_salt("artwork_grid").show(ui, |ui| {
            egui::Grid::new("artwork_grid").num_columns(3).spacing([20.0, 20.0]).show(ui, |ui| {
                for (i, name) in self.state.archives.iter().enumerate() {
                    ui.vertical(|ui| {
                        ui.label(RichText::new(name).small().strong());
                        ui.separator();
                        if ui.button("Open Folder").clicked() {
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

        ui.separator();

        // Bottom actions
        ui.horizontal(|ui| {
            if ui.button("Scan Again").clicked() {
                self.state.status = "Scan Again clicked".to_string();
            }
            if ui.button("Review").clicked() {
                self.state.status = "Review clicked".to_string();
            }
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
