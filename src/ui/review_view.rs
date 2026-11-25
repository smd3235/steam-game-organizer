//! Review view: verify Steam matches, pick categories, accept games, and move to organization.
//! Stub conversion of `ui/review_view.py` — new egui layout, not a Tkinter port.
//!
//! 2026-11-25: egui review view in the Rust conversion.

use egui::{RichText, ScrollArea};
use crate::ui::theme::{Palette, separator};

#[derive(Default)]
pub struct ReviewViewState {
    pub archives: Vec<String>,
    pub selected_index: Option<usize>,
    pub search_text: String,
    pub filter: String,
    pub status: String,
}

impl ReviewViewState {
    pub fn new() -> Self {
        ReviewViewState {
            archives: Vec::new(),
            selected_index: None,
            search_text: String::new(),
            filter: "All".to_string(),
            status: "Verification idle".to_string(),
        }
    }
}

/// Review view — verify Steam matches, pick categories, accept games.
pub struct ReviewView {
    pub state: ReviewViewState,
    pub palette: Palette,
}

impl ReviewView {
    pub fn new(palette: Palette) -> Self {
        ReviewView {
            state: ReviewViewState::new(),
            palette,
        }
    }

    pub fn ui(&mut self, ui: &mut egui::Ui) {
        separator(ui, &self.palette);

        // Header
        ui.heading("Game Review");
        ui.horizontal(|ui| {
            ui.label(RichText::new(&self.state.status).small().color(self.palette.muted));
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if ui.button("Approve All Verified").clicked() {
                    self.state.status = "Approving all verified…".to_string();
                }
            });
        });

        ui.separator();

        // Controls row: search + filter + actions
        ui.horizontal(|ui| {
            ui.label("Search:");
            ui.text_edit_singleline(&mut self.state.search_text);
            ui.separator();
            ui.label("Filter:");
            egui::ComboBox::from_id_salt("review_filter")
                .selected_text(&self.state.filter)
                .show_ui(ui, |ui| {
                    ui.selectable_value(&mut self.state.filter, "All".to_string(), "All");
                    ui.selectable_value(&mut self.state.filter, "Needs Review".to_string(), "Needs Review");
                    ui.selectable_value(&mut self.state.filter, "Verified".to_string(), "Verified");
                    ui.selectable_value(&mut self.state.filter, "New Only".to_string(), "New Only");
                    ui.selectable_value(&mut self.state.filter, "Artwork".to_string(), "Artwork");
                });
            ui.separator();
            if ui.button("＋ Add Category").clicked() {
                self.state.status = "Add Category clicked".to_string();
            }
            if ui.button("Use All Suggestions").clicked() {
                self.state.status = "Use All Suggestions clicked".to_string();
            }
            if ui.button("Retry Failed").clicked() {
                self.state.status = "Retry Failed clicked".to_string();
            }
            if ui
                .add(egui::Button::new("Continue to Organization").min_size(egui::vec2(140.0, 32.0)))
                .clicked()
            {
                self.state.status = "Continue to Organization clicked".to_string();
            }
        });

        ui.separator();

        // Body: game list left, detail right
        ui.horizontal(|ui| {
            // Left: archive list
            ui.vertical(|ui| {
                ui.label(RichText::new("Archives").strong().color(self.palette.muted));
                ScrollArea::vertical().id_salt("review_list").max_height(400.0).show(ui, |ui| {
                    for (i, name) in self.state.archives.iter().enumerate() {
                        let selected = self.state.selected_index == Some(i);
                        if ui.selectable_label(selected, name).clicked() {
                            self.state.selected_index = Some(i);
                        }
                    }
                    if self.state.archives.is_empty() {
                        ui.label(RichText::new("(no archives)").color(self.palette.muted).italics());
                    }
                });
            });

            ui.separator();

            // Right: detail panel
            ui.vertical(|ui| {
                ui.label(RichText::new("Archive Detail").strong().color(self.palette.muted));
                ScrollArea::vertical().id_salt("review_detail").max_height(400.0).show(ui, |ui| {
                    match self.state.selected_index {
                        Some(i) => {
                            ui.label(RichText::new(format!("Archive {}", i + 1)).strong());
                            ui.separator();
                            ui.label("APPID: —".to_string());
                            ui.label("Steam Name: —".to_string());
                            ui.label("Category: —".to_string());
                            ui.separator();
                            ui.label("Evidence: —".to_string());
                            ui.separator();
                            ui.label("Archive Size: —".to_string());
                        }
                        None => {
                            ui.label(RichText::new("Select an archive to review").color(self.palette.muted).italics());
                        }
                    }
                });
            });
        });

        ui.separator();

        // Bottom actions
        ui.horizontal(|ui| {
            if ui.button("Accept & Next").clicked() {
                self.state.status = "Accept & Next clicked".to_string();
            }
            if ui.button("Skip").clicked() {
                self.state.status = "Skip clicked".to_string();
            }
            if ui.button("Wrong Match").clicked() {
                self.state.status = "Wrong Match clicked".to_string();
            }
            if ui.button("Extract Selected").clicked() {
                self.state.status = "Extract Selected clicked".to_string();
            }
        });
    }

    pub fn load(&mut self, archives: Vec<String>) {
        self.state.archives = archives;
        self.state.selected_index = if !self.state.archives.is_empty() { Some(0) } else { None };
    }

    pub fn cancel_lookup(&mut self) {
        self.state.status = "Verification cancelled.".to_string();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_review_view_new() {
        let palette = Palette::default();
        let _view = ReviewView::new(palette);
    }

    #[test]
    fn test_review_view_load() {
        let palette = Palette::default();
        let mut view = ReviewView::new(palette);
        view.load(vec!["Game 1".to_string(), "Game 2".to_string()]);
        assert_eq!(view.state.archives.len(), 2);
        assert_eq!(view.state.selected_index, Some(0));
    }

    #[test]
    fn test_review_view_cancel_lookup() {
        let palette = Palette::default();
        let mut view = ReviewView::new(palette);
        view.load(vec!["Game 1".to_string()]);
        view.cancel_lookup();
        assert_eq!(view.state.status, "Verification cancelled.".to_string());
    }
}
