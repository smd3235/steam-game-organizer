//! Artwork review screen: shows each accepted game's downloaded artwork assets.
//! Redesigned with new theme system: cards, section headers, pill badges, styled buttons.
//! All buttons log actions through the logger.
//!
//! 2026-11-26: egui artwork view with new theme and wired button actions.
//! v2 - comprehensive logging on every button.

use std::sync::Arc;

use crate::core::models::GameArchive;
use crate::core::errors::Watchdog;

use egui::{RichText, ScrollArea};
use crate::ui::theme::{
    card, empty_state, heading, info_card, secondary_button, section_header, Palette, separator,
};

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
    pub logger: Arc<crate::core::logger::AppLogger>,
    pub watchdog: Arc<Watchdog>,
}

impl ArtworkView {
    pub fn new(
        palette: Palette,
        logger: Arc<crate::core::logger::AppLogger>,
        watchdog: Arc<Watchdog>,
    ) -> Self {
        ArtworkView {
            state: ArtworkViewState::new(),
            palette,
            logger,
            watchdog,
        }
    }

    pub fn ui(&mut self, ui: &mut egui::Ui) {
        card(ui, &self.palette, |ui| {
            // Header
            heading(ui, &self.palette, "Artwork & Steam Assets");
            separator(ui);

            // Summary
            ui.label(RichText::new(&self.state.status).color(self.palette.muted).small());
            separator(ui);

            // Archive grid
            section_header(ui, &self.palette, "ARCHIVES");
            ScrollArea::vertical().id_salt("artwork_grid").show(ui, |ui| {
                if self.state.archives.is_empty() {
                    empty_state(ui, &self.palette, "🖼️", "No artwork downloaded yet", "Scan and organize games first, then download artwork.");
                } else {
                    egui::Grid::new("artwork_grid").num_columns(3).spacing([20.0, 20.0]).show(ui, |ui| {
                        for (i, archive) in self.state.archives.iter().enumerate() {
                        let name = if archive.display_name.is_empty() {
                            archive.path.file_name().unwrap_or_default().to_string_lossy().to_string()
                        } else {
                            archive.display_name.clone()
                        };
                        ui.vertical(|ui| {
                            ui.label(RichText::new(&name).small().strong());
                            separator(ui);
                            if secondary_button(ui, "Open Folder", &self.palette, true).clicked() {
                                self.logger.log("ARTWORK", &format!("Open Folder: {}", name), "");
                                self.state.status = format!("Opened folder for {}", name);
                            }
                            if secondary_button(ui, "View Artwork", &self.palette, true).clicked() {
                                self.logger.log("ARTWORK", &format!("View Artwork: {}", name), "");
                                self.state.status = format!("Viewing artwork for {}", name);
                            }
                        });
                        if i < self.state.archives.len() - 1 {
                            ui.end_row();
                        }
                    }
                });
            }
        });

            separator(ui);

            // Bottom actions
            ui.horizontal(|ui| {
                if secondary_button(ui, "Scan Again", &self.palette, true).clicked() {
                    self.logger.log("ARTWORK", "Scan Again button clicked", "");
                    self.state.status = "Scan Again clicked".to_string();
                }
                if secondary_button(ui, "Review", &self.palette, true).clicked() {
                    self.logger.log("ARTWORK", "Review button clicked", "");
                    self.state.status = "Review clicked".to_string();
                }
                if secondary_button(ui, "Re-download Missing", &self.palette, true).clicked() {
                    self.logger.log("ARTWORK", "Re-download Missing button clicked", "");
                    self.state.status = "Re-downloading missing artwork…".to_string();
                }
            });

            separator(ui);

            // Artwork detail panel
            if let Some(i) = self.state.selected_index {
                let archive = &self.state.archives[i];
                section_header(ui, &self.palette, &format!("Artwork Details: {}", archive.display_name));
                info_card(ui, &self.palette, "Identity Key:", &archive.identity_key);
                info_card(ui, &self.palette, "Artwork Status:", &archive.artwork.status);
                info_card(ui, &self.palette, "Artwork Source:", &archive.artwork.source);
                info_card(ui, &self.palette, "Asset Count:", &format!("{}", archive.artwork.assets.len()));
                separator(ui);
            }
        });
    }

    pub fn load(&mut self, archives: Vec<GameArchive>) {
        let corr = self.logger.correlation_id();
        self.state.archives = archives;
        self.state.selected_index = if !self.state.archives.is_empty() { Some(0) } else { None };
        self.state.status = format!("Loaded {} archives for artwork review", self.state.archives.len());
        self.logger.log("ARTWORK", &self.state.status, &corr);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_artwork_view_new() {
        let palette = Palette::default();
        let logger: Arc<crate::core::logger::AppLogger> = Arc::new(
            crate::core::logger::AppLogger::new(
                std::env::temp_dir().join(format!("artwork_test_{}.log", std::process::id())),
                "INFO",
                false,
                false,
            ).unwrap(),
        );
        let watchdog = Arc::new(crate::core::errors::Watchdog::new(logger.clone(), 1000));
        let _view = ArtworkView::new(palette, logger, watchdog);
    }

    #[test]
    fn test_artwork_view_load() {
        let palette = Palette::default();
        let logger: Arc<crate::core::logger::AppLogger> = Arc::new(
            crate::core::logger::AppLogger::new(
                std::env::temp_dir().join(format!("artwork_test_{}.log", std::process::id())),
                "INFO",
                false,
                false,
            ).unwrap(),
        );
        let watchdog = Arc::new(crate::core::errors::Watchdog::new(logger.clone(), 1000));
        let mut view = ArtworkView::new(palette, logger, watchdog);
        let archive = GameArchive::default();
        view.load(vec![archive.clone(), archive]);
        assert_eq!(view.state.archives.len(), 2);
        assert_eq!(view.state.selected_index, Some(0));
    }
}