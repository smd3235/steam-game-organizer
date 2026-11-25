//! Batch extraction window: one row per game, live progress, cancel support.
//! Stub conversion of `ui/batch_extract_window.py` — egui table layout, not Tkinter.
//!
//! 2026-11-25: egui batch extract window stub in the Rust conversion.

use egui::{RichText, ScrollArea};
use crate::ui::theme::{Palette, separator};

#[derive(Default, Clone, Copy, PartialEq, Eq, Debug)]
pub enum BatchItemState {
    #[default]
    Queued,
    Extracting,
    Done,
    Failed,
    Skipped,
    Cancelled,
}

#[derive(Clone, Default)]
pub struct BatchItem {
    pub name: String,
    pub state: BatchItemState,
    pub progress: f32,
    pub detail: String,
}

#[derive(Default)]
pub struct BatchExtractWindowState {
    pub items: Vec<BatchItem>,
    pub status: String,
    pub extracting: bool,
    pub cancelled: bool,
}

impl BatchExtractWindowState {
    pub fn new() -> Self {
        BatchExtractWindowState {
            items: Vec::new(),
            status: "Idle".to_string(),
            extracting: false,
            cancelled: false,
        }
    }
}

/// BatchExtractWindow — runs a batch extraction and shows per-game status.
pub struct BatchExtractWindow {
    pub state: BatchExtractWindowState,
    pub palette: Palette,
}

impl BatchExtractWindow {
    pub fn new(palette: Palette) -> Self {
        BatchExtractWindow {
            state: BatchExtractWindowState::new(),
            palette,
        }
    }

    pub fn ui(&mut self, ui: &mut egui::Ui) {
        separator(ui, &self.palette);

        ui.heading("Batch Extraction");
        ui.label(RichText::new(&self.state.status).small().color(self.palette.muted));
        ui.separator();

        ui.horizontal(|ui| {
            if self.state.extracting {
                if ui.button("Cancel").clicked() {
                    self.state.cancelled = true;
                    self.state.status = "Cancelling…".to_string();
                }
            } else if ui.button("Start Batch").clicked() {
                self.state.extracting = true;
                self.state.status = "Batch starting…".to_string();
            }
        });

        ui.separator();

        ScrollArea::vertical().id_salt("batch_items").show(ui, |ui| {
            egui::Grid::new("batch_grid").num_columns(4).spacing([10.0, 4.0]).show(ui, |ui| {
                ui.label(RichText::new("Game").strong().color(self.palette.muted));
                ui.label(RichText::new("State").strong().color(self.palette.muted));
                ui.label(RichText::new("Progress").strong().color(self.palette.muted));
                ui.label(RichText::new("Detail").strong().color(self.palette.muted));
                ui.end_row();

                if self.state.items.is_empty() {
                    ui.label(RichText::new("(no items — start a batch to see games)").color(self.palette.muted).italics());
                    ui.end_row();
                } else {
                    for item in &self.state.items {
                        let (color, label) = match item.state {
                            BatchItemState::Queued => (self.palette.muted, "Waiting"),
                            BatchItemState::Extracting => (self.palette.accent, "Extracting"),
                            BatchItemState::Done => (self.palette.green, "Done"),
                            BatchItemState::Failed => (self.palette.red, "Failed"),
                            BatchItemState::Skipped => (self.palette.orange, "Already there"),
                            BatchItemState::Cancelled => (self.palette.red, "Not done"),
                        };
                        ui.label(&item.name);
                        ui.colored_label(color, label);
                        ui.add(egui::ProgressBar::new(item.progress).desired_width(100.0));
                        ui.label(&item.detail);
                        ui.end_row();
                    }
                }
            });
        });

        ui.separator();

        ui.label(RichText::new(&self.state.status).color(self.palette.text));
    }

    pub fn add_item(&mut self, name: String) {
        self.state.items.push(BatchItem {
            name,
            ..Default::default()
        });
    }

    pub fn set_item_state(&mut self, name: &str, state: BatchItemState, detail: &str) {
        if let Some(item) = self.state.items.iter_mut().find(|i| i.name == name) {
            item.state = state;
            item.detail = detail.to_string();
        }
    }

    pub fn set_item_progress(&mut self, name: &str, progress: f32) {
        if let Some(item) = self.state.items.iter_mut().find(|i| i.name == name) {
            item.progress = progress;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_batch_extract_window_new() {
        let palette = Palette::default();
        let _window = BatchExtractWindow::new(palette);
    }

    #[test]
    fn test_batch_extract_window_add_item() {
        let palette = Palette::default();
        let mut window = BatchExtractWindow::new(palette);
        window.add_item("Game 1".to_string());
        assert_eq!(window.state.items.len(), 1);
    }

    #[test]
    fn test_batch_extract_window_set_state() {
        let palette = Palette::default();
        let mut window = BatchExtractWindow::new(palette);
        window.add_item("Game 1".to_string());
        window.set_item_state("Game 1", BatchItemState::Done, "Extraction complete");
        assert_eq!(window.state.items[0].state, BatchItemState::Done);
        assert_eq!(window.state.items[0].detail, "Extraction complete");
    }
}
