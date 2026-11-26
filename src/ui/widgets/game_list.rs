//! GameList: vertical scrollable list of game cards with filtering and selection.
//! Stub conversion of `ui/widgets/game_list.py` — egui list, not Tkinter.
//!
//! 2026-11-25: egui game list stub in the Rust conversion.

use crate::ui::theme::{separator, Palette};
use egui::{RichText, ScrollArea, Ui};

pub struct GameListState {
    pub items: Vec<String>,
    pub selected: Option<usize>,
    pub search_text: String,
    pub filter: String,
}

impl Default for GameListState {
    fn default() -> Self {
        GameListState {
            items: Vec::new(),
            selected: None,
            search_text: String::new(),
            filter: "All".to_string(),
        }
    }
}

pub struct GameList {
    pub state: GameListState,
    pub palette: Palette,
}

impl GameList {
    pub fn new(palette: Palette) -> Self {
        GameList {
            state: GameListState::default(),
            palette,
        }
    }

    pub fn ui(&mut self, ui: &mut Ui) {
        ui.group(|ui| {
            ui.label(
                RichText::new("Game Queue")
                    .strong()
                    .color(self.palette.accent_hi),
            );
            separator(ui);

            ui.horizontal(|ui| {
                ui.label("Search:");
                ui.text_edit_singleline(&mut self.state.search_text);
                separator(ui);
                egui::ComboBox::from_id_salt("game_list_filter")
                    .selected_text(&self.state.filter)
                    .show_ui(ui, |ui| {
                        ui.selectable_value(&mut self.state.filter, "All".to_string(), "All");
                        ui.selectable_value(
                            &mut self.state.filter,
                            "New Only".to_string(),
                            "New Only",
                        );
                        ui.selectable_value(
                            &mut self.state.filter,
                            "Verified".to_string(),
                            "Verified",
                        );
                    });
            });

            separator(ui);

            ScrollArea::vertical().id_salt("game_list").show(ui, |ui| {
                for (i, item) in self.state.items.iter().enumerate() {
                    let selected = self.state.selected == Some(i);
                    if ui.selectable_label(selected, item).clicked() {
                        self.state.selected = Some(i);
                    }
                }
                if self.state.items.is_empty() {
                    ui.label(
                        RichText::new("(no games)")
                            .color(self.palette.muted)
                            .italics(),
                    );
                }
            });

            separator(ui);
            ui.horizontal(|ui| {
                ui.label(format!("{} games", self.state.items.len()));
            });
        });
    }

    pub fn set_items(&mut self, items: Vec<String>) {
        let is_empty = items.is_empty();
        self.state.items = items;
        self.state.selected = if !is_empty { Some(0) } else { None };
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_game_list_new() {
        let palette = Palette::default();
        let _list = GameList::new(palette);
    }

    #[test]
    fn test_game_list_set_items() {
        let palette = Palette::default();
        let mut list = GameList::new(palette);
        list.set_items(vec!["Game 1".to_string(), "Game 2".to_string()]);
        assert_eq!(list.state.items.len(), 2);
        assert_eq!(list.state.selected, Some(0));
    }
}
