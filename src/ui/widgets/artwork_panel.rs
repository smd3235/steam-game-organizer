//! ArtworkPanel: shows matched game's Steam artwork with fallback placeholder.
//! Stub conversion of `ui/widgets/artwork_panel.py` — egui image, not Tkinter.
//!
//! 2026-11-25: egui artwork panel stub in the Rust conversion.

use crate::ui::theme::Palette;
use egui::{RichText, Ui};

pub enum ArtworkResult {
    Pending,
    Showing(String), // image path or description
    Failed,
    None,
}

pub struct ArtworkPanelState {
    pub result: ArtworkResult,
}

pub struct ArtworkPanel {
    pub state: ArtworkPanelState,
    pub palette: Palette,
}

impl ArtworkPanel {
    pub fn new(palette: Palette) -> Self {
        ArtworkPanel {
            state: ArtworkPanelState {
                result: ArtworkResult::Pending,
            },
            palette,
        }
    }

    pub fn ui(&mut self, ui: &mut Ui) {
        ui.group(|ui| {
            ui.set_min_width(200.0);
            ui.set_min_height(150.0);

            match &self.state.result {
                ArtworkResult::Pending => {
                    ui.centered_and_justified(|ui| {
                        ui.label(
                            RichText::new("ARTWORK\nLoading…")
                                .color(self.palette.muted)
                                .small(),
                        );
                    });
                }
                ArtworkResult::Showing(path) => {
                    ui.centered_and_justified(|ui| {
                        ui.label(
                            RichText::new(format!("Artwork: {}", path))
                                .small()
                                .color(self.palette.text),
                        );
                        ui.label(
                            RichText::new("(image display not yet implemented)")
                                .color(self.palette.muted)
                                .italics(),
                        );
                    });
                }
                ArtworkResult::Failed => {
                    ui.centered_and_justified(|ui| {
                        ui.label(RichText::new("No artwork").color(self.palette.muted));
                    });
                }
                ArtworkResult::None => {
                    ui.centered_and_justified(|ui| {
                        ui.label(RichText::new("No artwork").color(self.palette.muted));
                    });
                }
            }
        });
    }

    pub fn set_result(&mut self, result: ArtworkResult) {
        self.state.result = result;
    }
}

impl Default for ArtworkPanel {
    fn default() -> Self {
        Self::new(Palette::default())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_artwork_panel_new() {
        let palette = Palette::default();
        let _panel = ArtworkPanel::new(palette);
    }

    #[test]
    fn test_artwork_panel_set_result() {
        let palette = Palette::default();
        let mut panel = ArtworkPanel::new(palette);
        panel.set_result(ArtworkResult::Showing("/path/to/art.jpg".to_string()));
        match &panel.state.result {
            ArtworkResult::Showing(path) => assert_eq!(path, "/path/to/art.jpg"),
            _ => panic!("expected Showing"),
        }
    }
}
