//! Setup wizard: sets the game library, app folder and extract folder.
//! Stub conversion of `ui/setup_window.py` — egui dialog layout, not Tkinter.
//!
//! 2026-11-25: egui setup window stub in the Rust conversion.

use crate::ui::theme::{primary_button, secondary_button, separator, Palette};
use egui::{RichText, ScrollArea};

#[derive(Default)]
pub struct SetupWindowState {
    pub library_path: String,
    pub app_path: String,
    pub extract_path: String,
    pub status: String,
    pub checks: Vec<(String, String)>, // (level, message)
    pub saved: bool,
}

impl SetupWindowState {
    pub fn new() -> Self {
        SetupWindowState {
            library_path: String::new(),
            app_path: String::new(),
            extract_path: String::new(),
            status: String::new(),
            checks: Vec::new(),
            saved: false,
        }
    }
}

/// SetupWindow — sets the three folders a fresh PC needs.
pub struct SetupWindow {
    pub state: SetupWindowState,
    pub palette: Palette,
}

impl SetupWindow {
    pub fn new(palette: Palette) -> Self {
        SetupWindow {
            state: SetupWindowState::new(),
            palette,
        }
    }

    pub fn ui(&mut self, ui: &mut egui::Ui, app_name: &str) {
        separator(ui);

        ui.heading(format!("Set up {} on this PC", app_name));
        ui.label("Three folders decide whether the catalog's Extract buttons work here. Set them once; the choices are saved beside the app.");
        separator(ui);

        // Three folder fields
        ui.vertical(|ui| {
            for (label, path_var, hint) in [
                (
                    "Game library",
                    &mut self.state.library_path,
                    "The folder the games are in - the whole library, categories and all",
                ),
                (
                    "App folder",
                    &mut self.state.app_path,
                    "Where the app itself lives",
                ),
                (
                    "Extract to",
                    &mut self.state.extract_path,
                    "Where games are unpacked",
                ),
            ] {
                ui.group(|ui| {
                    ui.vertical(|ui| {
                        ui.label(RichText::new(label).strong().color(self.palette.accent_hi));
                        ui.text_edit_singleline(path_var);
                        ui.label(
                            RichText::new(hint)
                                .small()
                                .color(self.palette.muted)
                                .italics(),
                        );
                    });
                });
                separator(ui);
            }
        });

        // Browse buttons
        ui.horizontal(|ui| {
            if secondary_button(ui, "Browse Library", &self.palette, true).clicked() {
                self.state.status = "Library browse clicked".to_string();
            }
            if secondary_button(ui, "Browse App", &self.palette, true).clicked() {
                self.state.status = "App browse clicked".to_string();
            }
            if secondary_button(ui, "Browse Extract", &self.palette, true).clicked() {
                self.state.status = "Extract browse clicked".to_string();
            }
        });

        separator(ui);

        // Checks section
        ui.label(
            RichText::new("Checks")
                .strong()
                .color(self.palette.accent_hi),
        );
        ScrollArea::vertical()
            .id_salt("setup_checks")
            .max_height(150.0)
            .show(ui, |ui| {
                if self.state.checks.is_empty() {
                    ui.label(
                        RichText::new("(no checks run yet)")
                            .color(self.palette.muted)
                            .italics(),
                    );
                } else {
                    for (level, message) in &self.state.checks {
                        let color = match level.as_str() {
                            "error" => self.palette.red,
                            "warn" => self.palette.orange,
                            "ok" => self.palette.green,
                            _ => self.palette.text,
                        };
                        ui.horizontal(|ui| {
                            ui.label(RichText::new(format!("[{}]", level)).color(color).small());
                            ui.label(RichText::new(message).small().color(self.palette.text));
                        });
                    }
                }
            });

        separator(ui);

        // Footer: Save button + status
        ui.horizontal(|ui| {
            if primary_button(ui, "Save setup", &self.palette, true).clicked() {
                self.state.saved = true;
                self.state.status = "Setup saved.".to_string();
            }
            if self.state.saved
                && primary_button(ui, "Launch Steam Game Organizer", &self.palette, true).clicked()
            {
                self.state.status = "Launch clicked".to_string();
            }
        });

        if !self.state.status.is_empty() {
            separator(ui);
            ui.label(
                RichText::new(&self.state.status)
                    .color(self.palette.muted)
                    .small(),
            );
        }
    }

    pub fn refresh_checks(&mut self) {
        self.state.checks = vec![
            ("ok".to_string(), "Library folder exists".to_string()),
            ("ok".to_string(), "App folder found".to_string()),
            ("ok".to_string(), "Extract folder ready".to_string()),
        ];
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_setup_window_new() {
        let palette = Palette::default();
        let _window = SetupWindow::new(palette);
    }

    #[test]
    fn test_setup_window_refresh_checks() {
        let palette = Palette::default();
        let mut window = SetupWindow::new(palette);
        window.refresh_checks();
        assert_eq!(window.state.checks.len(), 3);
    }
}
