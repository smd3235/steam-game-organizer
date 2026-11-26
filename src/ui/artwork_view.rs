//! Artwork review screen: shows each accepted game's downloaded artwork assets.
//! Redesigned with new theme system: cards, section headers, pill badges, styled buttons.
//!
//! 2026-11-25: egui artwork view with new theme and wired button actions.
//! All buttons log actions through the logger.

use std::sync::Arc;

use egui::{RichText, ScrollArea};
use crate::core::models::GameArchive;
use crate::ui::theme::{card, secondary_button, section_header, Palette, separator};

#[derive(Default, Clone)]
pub struct ArtworkViewState {
    pub archives: Vec<GameArchive>,
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
    pub logger: Arc<dyn for<'a, 'b> Fn(&'a str, &'b str) + Send + Sync>,
}

impl ArtworkView {
    pub fn new(palette: Palette, logger: Arc<dyn for<'a, 'b> Fn(&'a str, &'b str) + Send + Sync>) -> Self {
        ArtworkView {
            state: ArtworkViewState::new(),
            palette,
            logger,
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
                    for (i, archive) in self.state.archives.iter().enumerate() {
                        let name = if archive.display_name.is_empty() {
                            archive.path.file_name().unwrap_or_default().to_string_lossy().to_string()
                        } else {
                            archive.display_name.clone()
                        };
                        ui.vertical(|ui| {
                            ui.label(RichText::new(&name).small().strong());
                            separator(ui, &self.palette);
                            if secondary_button(ui, "Open Folder", &self.palette).clicked() {
                                (self.logger)("ARTWORK", &format!("Open Folder: {}", name));
                                self.state.status = format!("Opened folder for {}", name);
                            }
                            if secondary_button(ui, "View Artwork", &self.palette).clicked() {
                                (self.logger)("ARTWORK", &format!("View Artwork: {}", name));
                                self.state.status = format!("Viewing artwork for {}", name);
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
                    (self.logger)("ARTWORK", "Scan Again button clicked");
                    self.state.status = "Scan Again clicked".to_string();
                }
                if secondary_button(ui, "Review", &self.palette).clicked() {
                    (self.logger)("ARTWORK", "Review button clicked");
                    self.state.status = "Review clicked".to_string();
                }
                if secondary_button(ui, "Re-download Missing", &self.palette).clicked() {
                    (self.logger)("ARTWORK", "Re-download Missing button clicked");
                    self.state.status = "Re-downloading missing artwork…".to_string();
                }
            });

            separator(ui, &self.palette);

            // Artwork detail panel
            if let Some(i) = self.state.selected_index {
                let archive = &self.state.archives[i];
                section_header(ui, &self.palette, &format!("Artwork Details: {}", archive.display_name));
                ui.label(format!("Identity Key: {}", archive.identity_key));
                ui.label(format!("Artwork Status: {}", archive.artwork.status));
                ui.label(format!("Artwork Source: {}", archive.artwork.source));
                ui.label(format!("Asset Count: {}", archive.artwork.assets.len()));
                ui.separator();
            }
        });
    }

    pub fn load(&mut self, archives: Vec<GameArchive>) {
        self.state.archives = archives;
        self.state.selected_index = if !self.state.archives.is_empty() { Some(0) } else { None };
        self.state.status = format!("Loaded {} archives for artwork review", self.state.archives.len());
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_artwork_view_new() {
        let palette = Palette::default();
        let logger: Arc<dyn for<'a, 'b> Fn(&'a str, &'b str) + Send + Sync> = Arc::new(|_, _| {});
        let _view = ArtworkView::new(palette, logger);
    }

    #[test]
    fn test_artwork_view_load() {
        let palette = Palette::default();
        let logger: Arc<dyn for<'a, 'b> Fn(&'a str, &'b str) + Send + Sync> = Arc::new(|_, _| {});
        let mut view = ArtworkView::new(palette, logger);
        let archive = GameArchive::default();
        view.load(vec![archive.clone(), archive]);
        assert_eq!(view.state.archives.len(), 2);
        assert_eq!(view.state.selected_index, Some(0));
    }
}
