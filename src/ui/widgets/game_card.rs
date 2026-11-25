//! GameCard: a single game card with category strip, title, confidence pill, and status.
//! Stub conversion of `ui/widgets/game_card.py` — egui card layout, not Tkinter.
//!
//! 2026-11-25: egui game card stub in the Rust conversion.

use egui::{RichText, Ui};
use crate::ui::theme::Palette;

#[derive(Default)]
pub struct GameCardState {
    pub title: String,
    pub category: String,
    pub confidence: String,
    pub status: String,
    pub selected: bool,
}

pub struct GameCard {
    pub state: GameCardState,
    pub palette: Palette,
}

impl GameCard {
    pub fn new(palette: Palette) -> Self {
        GameCard {
            state: GameCardState::default(),
            palette,
        }
    }

    pub fn ui(&mut self, ui: &mut Ui) {
        ui.group(|ui| {
            ui.set_min_width(200.0);
            // Left accent strip (category color)
            ui.vertical(|ui| {
                let strip_color = if self.state.category.is_empty() || self.state.category == "Unsorted" {
                    self.palette.muted
                } else {
                    self.palette.accent
                };
                ui.painter().rect_filled(
                    ui.min_rect(),
                    2.0,
                    strip_color,
                );
                ui.separator();

                ui.horizontal(|ui| {
                    ui.label(RichText::new(&self.state.title).strong().color(self.palette.text));
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        ui.label(RichText::new("NEW").color(self.palette.bg).small().strong());
                    });
                });

                ui.separator();
                ui.label(RichText::new(&self.state.status).small().color(self.palette.muted));

                ui.horizontal(|ui| {
                    ui.label(RichText::new(format!("Category: {}", self.state.category)).small().color(self.palette.muted));
                    ui.separator();
                    ui.label(RichText::new(format!("Confidence: {}", self.state.confidence)).small().color(self.palette.muted));
                });
            });
        });
    }

    pub fn set_title(&mut self, title: String) {
        self.state.title = title;
    }

    pub fn set_category(&mut self, category: String) {
        self.state.category = category;
    }

    pub fn set_confidence(&mut self, confidence: String) {
        self.state.confidence = confidence;
    }

    pub fn set_status(&mut self, status: String) {
        self.state.status = status;
    }

    pub fn set_selected(&mut self, selected: bool) {
        self.state.selected = selected;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_game_card_new() {
        let palette = Palette::default();
        let _card = GameCard::new(palette);
    }

    #[test]
    fn test_game_card_setters() {
        let palette = Palette::default();
        let mut card = GameCard::new(palette);
        card.set_title("Test Game".to_string());
        card.set_category("Action".to_string());
        card.set_confidence("High".to_string());
        card.set_status("Pending".to_string());
        card.set_selected(true);

        assert_eq!(card.state.title, "Test Game");
        assert_eq!(card.state.category, "Action");
        assert_eq!(card.state.confidence, "High");
        assert_eq!(card.state.status, "Pending");
        assert!(card.state.selected);
    }
}
