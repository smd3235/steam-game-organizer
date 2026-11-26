//! Extract result dialog: single-archive extraction progress and result.
//! Stub conversion of `ui/extract_result_window.py` — egui dialog, not Tkinter.
//!
//! 2026-11-25: egui extract result window stub in the Rust conversion.

use egui::{RichText, ScrollArea};
use crate::ui::theme::{secondary_button, Palette, separator};

pub struct ExtractResultDialogState {
    pub archive_name: String,
    pub destination: String,
    pub progress: f32,
    pub stage: String,
    pub status: String,
    pub extracting: bool,
    pub completed: bool,
    pub success: bool,
    pub error_message: Option<String>,
    pub needs_install: bool,
}

/// ExtractResultDialog — progress dialog for single-archive extraction.
pub struct ExtractResultDialog {
    pub state: ExtractResultDialogState,
    pub palette: Palette,
}

impl ExtractResultDialog {
    pub fn new(archive_name: &str, destination: &str, palette: Palette) -> Self {
        ExtractResultDialog {
            state: ExtractResultDialogState {
                archive_name: archive_name.to_string(),
                destination: destination.to_string(),
                progress: 0.0,
                stage: "Starting…".to_string(),
                status: "Extracting".to_string(),
                extracting: true,
                completed: false,
                success: false,
                error_message: None,
                needs_install: false,
            },
            palette,
        }
    }

    pub fn ui(&mut self, ui: &mut egui::Ui) {
        separator(ui);

        ui.heading(if self.state.needs_install { "Extracting Installer" } else { "Extracting" });
        ui.label(&self.state.archive_name);
        separator(ui);

        ui.label(RichText::new(&self.state.stage).small().color(self.palette.muted));
        ui.add(egui::ProgressBar::new(self.state.progress).desired_width(300.0));
        separator(ui);

        ScrollArea::vertical().id_salt("extract_result").max_height(200.0).show(ui, |ui| {
            if let Some(ref err) = self.state.error_message {
                ui.colored_label(self.palette.red, format!("Failed: {}", err));
            } else if self.state.completed {
                if self.state.success {
                    ui.colored_label(self.palette.green, "Extraction complete.");
                } else {
                    ui.colored_label(self.palette.red, "Extraction failed.");
                }
                ui.label(format!("Destination: {}", self.state.destination));
            } else {
                ui.label("Extracting in progress…");
            }
        });

        separator(ui);

        if self.state.completed {
            if secondary_button(ui, "Close", &self.palette, true).clicked() {
                // close
            }
        } else {
            if secondary_button(ui, "Cancel", &self.palette, true).clicked() {
                self.state.status = "Cancel requested".to_string();
            }
        }
    }

    pub fn set_progress(&mut self, progress: f32, stage: &str) {
        self.state.progress = progress;
        self.state.stage = stage.to_string();
    }

    pub fn complete(&mut self, success: bool, error_message: Option<String>) {
        self.state.extracting = false;
        self.state.completed = true;
        self.state.success = success;
        self.state.error_message = error_message;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_result_dialog_new() {
        let palette = Palette::default();
        let dialog = ExtractResultDialog::new("Game.zip", "/dest", palette);
        assert_eq!(dialog.state.archive_name, "Game.zip");
        assert_eq!(dialog.state.destination, "/dest");
        assert!(dialog.state.extracting);
    }

    #[test]
    fn test_extract_result_dialog_complete() {
        let palette = Palette::default();
        let mut dialog = ExtractResultDialog::new("Game.zip", "/dest", palette);
        dialog.set_progress(0.5, "Compressing");
        assert_eq!(dialog.state.progress, 0.5);
        assert_eq!(dialog.state.stage, "Compressing");
        dialog.complete(true, None);
        assert!(dialog.state.completed);
        assert!(dialog.state.success);
    }
}
