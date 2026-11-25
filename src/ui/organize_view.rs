//! Organize view: convert ZIP/RAR to 7z, move into category folders, write artwork and catalog pages.
//! Redesigned with new theme system: cards, section headers, pill badges, styled buttons.
//!
//! 2026-11-25: egui organize view with new theme.

use egui::{RichText, ScrollArea};
use crate::ui::theme::{card, danger_button, primary_button, Palette, separator};

#[derive(Default)]
pub struct OrganizeViewState {
    pub archives: Vec<String>,
    pub selected_index: Option<usize>,
    pub status: String,
    pub progress: f32,
    pub stage: String,
    pub activity: Vec<String>,
    pub preview_only: bool,
    pub converting: bool,
}

impl OrganizeViewState {
    pub fn new() -> Self {
        OrganizeViewState {
            archives: Vec::new(),
            selected_index: None,
            status: "Accept games on the Review page to build the organization plan.".to_string(),
            progress: 0.0,
            stage: "Idle".to_string(),
            activity: Vec::new(),
            preview_only: false,
            converting: false,
        }
    }
}

/// Organize view — convert archives, move into category folders, write artwork and catalog pages.
pub struct OrganizeView {
    pub state: OrganizeViewState,
    pub palette: Palette,
}

impl OrganizeView {
    pub fn new(palette: Palette) -> Self {
        OrganizeView {
            state: OrganizeViewState::new(),
            palette,
        }
    }

    pub fn ui(&mut self, ui: &mut egui::Ui) {
        card(ui, &self.palette, |ui| {
            // Header
            ui.heading("Organize");
            ui.label("Ready to organize");
            separator(ui, &self.palette);

            // Summary line
            ui.label(RichText::new(&self.state.status).color(self.palette.muted).small());
            separator(ui, &self.palette);

            // Progress bar + stage
            ui.horizontal(|ui| {
                ui.add(egui::ProgressBar::new(self.state.progress).desired_width(400.0));
                ui.label(RichText::new(&self.state.stage).color(self.palette.muted).small());
            });

            separator(ui, &self.palette);

            // Config: preview only checkbox
            ui.horizontal(|ui| {
                ui.checkbox(&mut self.state.preview_only, "Preview Only");
                ui.separator();
                if primary_button(ui, "Start Organize", &self.palette).clicked() {
                    self.state.converting = true;
                    self.state.status = "Organization starting…".to_string();
                }
                if self.state.converting && danger_button(ui, "Cancel", &self.palette).clicked() {
                    self.state.converting = false;
                    self.state.status = "Organization cancelled.".to_string();
                }
            });

            separator(ui, &self.palette);

            // Body: archive list left, activity feed right
            ui.horizontal(|ui| {
                // Left: archive list
                ui.vertical(|ui| {
                    ui.label(RichText::new("Archives to Organize").strong().color(self.palette.muted));
                    ScrollArea::vertical().id_salt("organize_list").max_height(400.0).show(ui, |ui| {
                        for (i, name) in self.state.archives.iter().enumerate() {
                            let selected = self.state.selected_index == Some(i);
                            if ui.selectable_label(selected, name).clicked() {
                                self.state.selected_index = Some(i);
                            }
                        }
                        if self.state.archives.is_empty() {
                            ui.label(RichText::new("(no archives — accept games on Review first)").color(self.palette.muted).italics());
                        }
                    });
                });

                ui.separator();

                // Right: activity feed
                ui.vertical(|ui| {
                    ui.label(RichText::new("Activity").strong().color(self.palette.muted));
                    ScrollArea::vertical().id_salt("organize_activity").max_height(400.0).show(ui, |ui| {
                        for line in &self.state.activity {
                            ui.label(RichText::new(line).small().color(self.palette.text));
                        }
                        if self.state.converting {
                            ui.label("Organizing in progress…");
                        }
                    });
                });
            });

            separator(ui, &self.palette);

            // Status line
            ui.label(RichText::new(&self.state.status).color(self.palette.text));
        });
    }

    pub fn load(&mut self, archives: Vec<String>) {
        self.state.archives = archives;
        self.state.selected_index = if !self.state.archives.is_empty() { Some(0) } else { None };
    }

    pub fn feed(&mut self, message: &str) {
        self.state.activity.push(message.to_string());
        if self.state.activity.len() > 500 {
            self.state.activity.drain(0..self.state.activity.len() - 500);
        }
    }

    pub fn shutdown(&mut self) {
        self.state.converting = false;
        self.state.status = "Organization shut down.".to_string();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_organize_view_new() {
        let palette = Palette::default();
        let _view = OrganizeView::new(palette);
    }

    #[test]
    fn test_organize_view_load() {
        let palette = Palette::default();
        let mut view = OrganizeView::new(palette);
        view.load(vec!["Game 1".to_string(), "Game 2".to_string()]);
        assert_eq!(view.state.archives.len(), 2);
        assert_eq!(view.state.selected_index, Some(0));
    }

    #[test]
    fn test_organize_view_feed() {
        let palette = Palette::default();
        let mut view = OrganizeView::new(palette);
        view.feed("test message");
        assert_eq!(view.state.activity.len(), 1);
    }

    #[test]
    fn test_organize_view_shutdown() {
        let palette = Palette::default();
        let mut view = OrganizeView::new(palette);
        view.state.converting = true;
        view.shutdown();
        assert!(!view.state.converting);
    }
}
