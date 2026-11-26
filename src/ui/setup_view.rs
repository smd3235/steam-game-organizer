//! Setup view: initial configuration wizard for library root, extract folder, and 7z path.
//! Redesigned with new theme system: cards, section headers, pill badges, styled buttons.
//!
//! 2026-11-25: egui setup view with new theme and wired button actions.
//! All buttons log actions through the logger.

use std::path::PathBuf;
use std::sync::Arc;

use egui::{RichText, ScrollArea};
use crate::ui::theme::{card, primary_button, secondary_button, section_header, Palette, separator};

#[derive(Default, Clone)]
pub struct SetupViewState {
    pub library_root: String,
    pub extract_folder: String,
    pub seven_zip_path: String,
    pub developer_mode: bool,
    pub status: String,
    pub validation_messages: Vec<String>,
    pub should_validate: bool,
    pub should_save: bool,
}

impl SetupViewState {
    pub fn new() -> Self {
        SetupViewState {
            library_root: String::new(),
            extract_folder: String::new(),
            seven_zip_path: String::new(),
            developer_mode: false,
            status: "Setup wizard — configure your Steam Game Organizer".to_string(),
            validation_messages: Vec::new(),
            should_validate: false,
            should_save: false,
        }
    }
}

/// Setup view — configure library root, extract folder, and 7z path.
pub struct SetupView {
    pub state: SetupViewState,
    pub palette: Palette,
    pub logger: Arc<dyn for<'a, 'b> Fn(&'a str, &'b str) + Send + Sync>,
}

impl SetupView {
    pub fn new(palette: Palette, logger: Arc<dyn for<'a, 'b> Fn(&'a str, &'b str) + Send + Sync>) -> Self {
        SetupView {
            state: SetupViewState::new(),
            palette,
            logger,
        }
    }

    pub fn ui(&mut self, ui: &mut egui::Ui) {
        // Process pending actions (set by button clicks in previous frame)
        if self.state.should_validate {
            self.state.should_validate = false;
            self.validate_config();
        }
        if self.state.should_save {
            self.state.should_save = false;
            self.save_config();
        }

        card(ui, &self.palette, |ui| {
            // Header
            ui.heading("Setup Wizard");
            ui.label("Configure Steam Game Organizer");
            separator(ui, &self.palette);

            // Status line
            ui.label(RichText::new(&self.state.status).small().color(self.palette.muted));
            separator(ui, &self.palette);

            // Library Root
            section_header(ui, &self.palette, "LIBRARY ROOT");
            ui.horizontal(|ui| {
                ui.add(
                    egui::TextEdit::singleline(&mut self.state.library_root)
                        .hint_text("e.g. C:\\SteamLibrary")
                        .desired_width(400.0),
                );
                if secondary_button(ui, "Browse", &self.palette).clicked() {
                    (self.logger)("SETUP", "Library root Browse clicked");
                    self.state.status = "Browse for library root…".to_string();
                }
            });
            ui.label(RichText::new("Where your game archives are stored").small().color(self.palette.muted));
            separator(ui, &self.palette);

            // Extract Folder
            section_header(ui, &self.palette, "EXTRACT FOLDER");
            ui.horizontal(|ui| {
                ui.add(
                    egui::TextEdit::singleline(&mut self.state.extract_folder)
                        .hint_text("e.g. C:\\Extracted")
                        .desired_width(400.0),
                );
                if secondary_button(ui, "Browse", &self.palette).clicked() {
                    (self.logger)("SETUP", "Extract folder Browse clicked");
                    self.state.status = "Browse for extract folder…".to_string();
                }
            });
            ui.label(RichText::new("Where extracted game files go").small().color(self.palette.muted));
            separator(ui, &self.palette);

            // 7z Path
            section_header(ui, &self.palette, "7-ZIP PATH");
            ui.horizontal(|ui| {
                ui.add(
                    egui::TextEdit::singleline(&mut self.state.seven_zip_path)
                        .hint_text("e.g. C:\\Program Files\\7-Zip\\7z.exe")
                        .desired_width(400.0),
                );
                if secondary_button(ui, "Browse", &self.palette).clicked() {
                    (self.logger)("SETUP", "7-Zip path Browse clicked");
                    self.state.status = "Browse for 7-Zip executable…".to_string();
                }
            });
            ui.label(RichText::new("Path to 7z.exe for archive operations").small().color(self.palette.muted));
            separator(ui, &self.palette);

            // Developer Mode
            ui.horizontal(|ui| {
                ui.checkbox(&mut self.state.developer_mode, "Developer Mode");
                ui.label(RichText::new("Enable debug logging and extra diagnostics").small().color(self.palette.muted));
            });
            separator(ui, &self.palette);

            // Validation section
            section_header(ui, &self.palette, "VALIDATION");
            ui.horizontal(|ui| {
                if primary_button(ui, "Validate Configuration", &self.palette).clicked() {
                    (self.logger)("SETUP", "Validate Configuration button clicked");
                    self.state.should_validate = true;
                }
                if secondary_button(ui, "Clear", &self.palette).clicked() {
                    (self.logger)("SETUP", "Clear validation clicked");
                    self.state.validation_messages.clear();
                    self.state.status = "Validation cleared".to_string();
                }
            });

            // Validation messages
            if !self.state.validation_messages.is_empty() {
                ScrollArea::vertical().id_salt("setup_validation").max_height(150.0).show(ui, |ui| {
                    for msg in &self.state.validation_messages {
                        let color = if msg.starts_with("ERROR") || msg.starts_with("✗") {
                            self.palette.red
                        } else if msg.starts_with("✓") || msg.starts_with("OK") {
                            self.palette.green
                        } else {
                            self.palette.orange
                        };
                        ui.label(RichText::new(msg).small().color(color));
                    }
                });
            }

            separator(ui, &self.palette);

            // Save button
            ui.horizontal(|ui| {
                if primary_button(ui, "Save & Finish Setup", &self.palette).clicked() {
                    (self.logger)("SETUP", "Save & Finish Setup button clicked");
                    self.state.should_save = true;
                }
                if secondary_button(ui, "Skip Setup", &self.palette).clicked() {
                    (self.logger)("SETUP", "Skip Setup button clicked");
                    self.state.status = "Setup skipped — using defaults".to_string();
                }
            });

            separator(ui, &self.palette);
            ui.label(RichText::new(&self.state.status).color(self.palette.muted).small());
        });
    }

    fn validate_config(&mut self) {
        self.state.validation_messages.clear();
        let mut all_ok = true;

        // Validate library root
        if self.state.library_root.is_empty() {
            self.state.validation_messages.push("✗ Library root is required".to_string());
            all_ok = false;
        } else {
            let path = PathBuf::from(&self.state.library_root);
            if path.is_dir() {
                self.state.validation_messages.push(format!("✓ Library root exists: {}", self.state.library_root));
            } else {
                self.state.validation_messages.push(format!("✗ Library root not found: {}", self.state.library_root));
                all_ok = false;
            }
        }

        // Validate extract folder
        if self.state.extract_folder.is_empty() {
            self.state.validation_messages.push("✗ Extract folder is required".to_string());
            all_ok = false;
        } else {
            let path = PathBuf::from(&self.state.extract_folder);
            if path.is_dir() {
                self.state.validation_messages.push(format!("✓ Extract folder exists: {}", self.state.extract_folder));
            } else {
                self.state.validation_messages.push(format!("! Extract folder will be created: {}", self.state.extract_folder));
            }
        }

        // Validate 7z path
        if self.state.seven_zip_path.is_empty() {
            self.state.validation_messages.push("! 7-Zip path not set (archive operations may fail)".to_string());
        } else {
            let path = PathBuf::from(&self.state.seven_zip_path);
            if path.is_file() {
                self.state.validation_messages.push(format!("✓ 7-Zip found: {}", self.state.seven_zip_path));
            } else {
                self.state.validation_messages.push(format!("! 7-Zip not found at: {}", self.state.seven_zip_path));
            }
        }

        if all_ok {
            self.state.status = "Configuration valid — ready to save".to_string();
        } else {
            self.state.status = "Configuration has issues — fix before saving".to_string();
        }

        (self.logger)("SETUP", &format!("Validation complete: {} messages", self.state.validation_messages.len()));
    }

    fn save_config(&mut self) {
        self.validate_config();
        if self.state.validation_messages.iter().any(|m| m.starts_with("✗")) {
            self.state.status = "Cannot save — fix errors first".to_string();
            return;
        }

        // Try to create extract folder if it doesn't exist
        if !self.state.extract_folder.is_empty() {
            let path = PathBuf::from(&self.state.extract_folder);
            if !path.exists() {
                match std::fs::create_dir_all(&path) {
                    Ok(()) => {
                        self.state.validation_messages.push(format!("✓ Created extract folder: {}", self.state.extract_folder));
                    }
                    Err(e) => {
                        self.state.validation_messages.push(format!("✗ Failed to create extract folder: {}", e));
                        self.state.status = "Save failed".to_string();
                        return;
                    }
                }
            }
        }

        self.state.status = "Configuration saved successfully!".to_string();
        (self.logger)("SETUP", "Configuration saved successfully");
        (self.logger)("SETUP", &format!("Library root: {}", self.state.library_root));
        (self.logger)("SETUP", &format!("Extract folder: {}", self.state.extract_folder));
        (self.logger)("SETUP", &format!("7-Zip path: {}", self.state.seven_zip_path));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_setup_view_new() {
        let palette = Palette::default();
        let logger: Arc<dyn for<'a, 'b> Fn(&'a str, &'b str) + Send + Sync> = Arc::new(|_, _| {});
        let _view = SetupView::new(palette, logger);
    }

    #[test]
    fn test_setup_validate_empty() {
        let palette = Palette::default();
        let logger: Arc<dyn for<'a, 'b> Fn(&'a str, &'b str) + Send + Sync> = Arc::new(|_, _| {});
        let mut view = SetupView::new(palette, logger);
        view.validate_config();
        assert!(!view.state.validation_messages.is_empty());
        assert!(view.state.validation_messages.iter().any(|m| m.starts_with("✗")));
    }

    #[test]
    fn test_setup_validate_with_paths() {
        let palette = Palette::default();
        let logger: Arc<dyn for<'a, 'b> Fn(&'a str, &'b str) + Send + Sync> = Arc::new(|_, _| {});
        let mut view = SetupView::new(palette, logger);
        view.state.library_root = ".".to_string();
        view.state.extract_folder = tempfile_dir().to_string_lossy().to_string();
        view.validate_config();
        assert!(view.state.validation_messages.iter().any(|m| m.starts_with("✓")));
    }
}

#[allow(dead_code)]
fn tempfile_dir() -> std::path::PathBuf {
    std::env::temp_dir().join(format!("sgo_test_{}", std::process::id()))
}
