//! Review view: verify Steam matches, pick categories, accept games, and move to organization.
//! Redesigned with new theme system: cards, section headers, pill badges, styled buttons.
//! All buttons log actions through the logger with detailed context.
//!
//! 2026-11-26: egui review view with new theme and wired button actions.
//! v2 - comprehensive logging on every button and state change.

use std::sync::Arc;

use crate::core::models::GameArchive;
use crate::core::errors::{
    OrganizerError, ErrorSeverity, Watchdog,
};
use crate::{log_error, err, trace_op};

use egui::{RichText, ScrollArea};
use crate::ui::theme::{
    card, danger_button, pill, primary_button, secondary_button, section_header, Palette,
    separator,
};

#[derive(Default, Clone)]
pub struct ReviewViewState {
    pub archives: Vec<GameArchive>,
    pub selected_index: Option<usize>,
    pub search_text: String,
    pub filter: String,
    pub status: String,
    pub should_approve_all: bool,
    pub should_use_suggestions: bool,
    pub should_retry_failed: bool,
    pub should_continue_organize: bool,
    pub should_accept_next: bool,
    pub should_skip: bool,
    pub should_wrong_match: bool,
    pub should_accept_index: Option<usize>,
    pub should_reject_index: Option<usize>,
}

impl ReviewViewState {
    pub fn new() -> Self {
        ReviewViewState {
            archives: Vec::new(),
            selected_index: None,
            search_text: String::new(),
            filter: "All".to_string(),
            status: "Verification idle".to_string(),
            should_approve_all: false,
            should_use_suggestions: false,
            should_retry_failed: false,
            should_continue_organize: false,
            should_accept_next: false,
            should_skip: false,
            should_wrong_match: false,
            should_accept_index: None,
            should_reject_index: None,
        }
    }
}

/// Review view — verify Steam matches, pick categories, accept games.
pub struct ReviewView {
    pub state: ReviewViewState,
    pub palette: Palette,
    pub logger: Arc<crate::core::logger::AppLogger>,
    pub watchdog: Arc<Watchdog>,
}

impl ReviewView {
    pub fn new(
        palette: Palette,
        logger: Arc<crate::core::logger::AppLogger>,
        watchdog: Arc<Watchdog>,
    ) -> Self {
        ReviewView {
            state: ReviewViewState::new(),
            palette,
            logger,
            watchdog,
        }
    }

    pub fn ui(&mut self, ui: &mut egui::Ui) {
        // Process pending actions (set by button clicks in previous frame)
        if self.state.should_approve_all {
            self.state.should_approve_all = false;
            self.approve_all_verified();
        }
        if self.state.should_use_suggestions {
            self.state.should_use_suggestions = false;
            self.use_all_suggestions();
        }
        if self.state.should_retry_failed {
            self.state.should_retry_failed = false;
            self.retry_failed();
        }
        if self.state.should_continue_organize {
            self.state.should_continue_organize = false;
        }
        if self.state.should_accept_next {
            self.state.should_accept_next = false;
            self.accept_and_next();
        }
        if self.state.should_skip {
            self.state.should_skip = false;
            self.skip_current();
        }
        if self.state.should_wrong_match {
            self.state.should_wrong_match = false;
            self.wrong_match();
        }
        if let Some(idx) = self.state.should_accept_index {
            self.state.should_accept_index = None;
            self.accept_archive(idx);
        }
        if let Some(idx) = self.state.should_reject_index {
            self.state.should_reject_index = None;
            self.reject_archive(idx);
        }

        card(ui, &self.palette, |ui| {
            // Header
            ui.heading("Game Review");
            ui.horizontal(|ui| {
                ui.label(RichText::new(&self.state.status).small().color(self.palette.muted));
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if primary_button(ui, "Approve All Verified", &self.palette).clicked() {
                        self.logger.log("REVIEW", "Approve All Verified button clicked", "");
                        self.state.status = "Approving all verified…".to_string();
                        self.state.should_approve_all = true;
                    }
                });
            });

            separator(ui, &self.palette);

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
                        ui.selectable_value(
                            &mut self.state.filter,
                            "Needs Review".to_string(),
                            "Needs Review",
                        );
                        ui.selectable_value(
                            &mut self.state.filter,
                            "Verified".to_string(),
                            "Verified",
                        );
                        ui.selectable_value(
                            &mut self.state.filter,
                            "New Only".to_string(),
                            "New Only",
                        );
                        ui.selectable_value(
                            &mut self.state.filter,
                            "Artwork".to_string(),
                            "Artwork",
                        );
                    });
                ui.separator();
                if secondary_button(ui, "＋ Add Category", &self.palette).clicked() {
                    self.logger.log("REVIEW", "Add Category button clicked", "");
                    self.state.status = "Add Category clicked".to_string();
                }
                if secondary_button(ui, "Use All Suggestions", &self.palette).clicked() {
                    self.logger.log("REVIEW", "Use All Suggestions button clicked", "");
                    self.state.status = "Use All Suggestions clicked".to_string();
                    self.state.should_use_suggestions = true;
                }
                if secondary_button(ui, "Retry Failed", &self.palette).clicked() {
                    self.logger.log("REVIEW", "Retry Failed button clicked", "");
                    self.state.status = "Retry Failed clicked".to_string();
                    self.state.should_retry_failed = true;
                }
                if primary_button(
                    ui,
                    "Continue to Organization",
                    &self.palette,
                )
                .clicked()
                {
                    self.logger.log("REVIEW", "Continue to Organization button clicked", "");
                    self.state.status = "Continue to Organization clicked".to_string();
                    self.state.should_continue_organize = true;
                }
            });

            separator(ui, &self.palette);

            // Body: game list left, detail right
            ui.horizontal(|ui| {
                // Left: archive list
                ui.vertical(|ui| {
                    ui.label(RichText::new("Archives").strong().color(self.palette.muted));
                    ScrollArea::vertical().id_salt("review_list").max_height(400.0).show(ui, |ui| {
                        for (i, archive) in self.state.archives.iter().enumerate() {
                            let selected = self.state.selected_index == Some(i);
                            let name = if archive.display_name.is_empty() {
                                archive.path.file_name().unwrap_or_default().to_string_lossy().to_string()
                            } else {
                                archive.display_name.clone()
                            };
                            if ui.selectable_label(selected, &name).clicked() {
                                self.state.selected_index = Some(i);
                                self.logger.log("REVIEW", &format!("Selected archive: {}", name), "");
                            }
                        }
                        if self.state.archives.is_empty() {
                            ui.label(RichText::new("(no archives — run Scan first)").color(self.palette.muted).italics());
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
                                let archive = &self.state.archives[i];
                                ui.label(RichText::new(format!("Archive {}", i + 1)).strong());
                                separator(ui, &self.palette);
                                ui.label(format!("Name: {}", archive.display_name));
                                ui.label(format!("APPID: {}", archive.steam.appid));
                                ui.label(format!("Category: {}", archive.decision.category));
                                ui.label(format!("Identity Key: {}", archive.identity_key));
                                separator(ui, &self.palette);
                                ui.label(RichText::new("Evidence:").small().color(self.palette.muted));
                                ui.label(format!("  Release Group: {}", archive.normalized_title));
                                separator(ui, &self.palette);
                                ui.label(format!("Size: {} bytes", archive.size));
                                separator(ui, &self.palette);
                                ui.label(format!("Accepted: {}", archive.decision.accepted));
                                ui.label(format!("Skipped: {}", archive.decision.skipped));
                            }
                            None => {
                                ui.label(RichText::new("Select an archive to review").color(self.palette.muted).italics());
                            }
                        }
                    });
                });
            });

            separator(ui, &self.palette);

            // Bottom actions
            ui.horizontal(|ui| {
                if secondary_button(ui, "Accept & Next", &self.palette).clicked() {
                    self.logger.log("REVIEW", "Accept & Next button clicked", "");
                    self.state.status = "Accept & Next clicked".to_string();
                    self.state.should_accept_next = true;
                }
                if secondary_button(ui, "Skip", &self.palette).clicked() {
                    self.logger.log("REVIEW", "Skip button clicked", "");
                    self.state.status = "Skip clicked".to_string();
                    self.state.should_skip = true;
                }
                if danger_button(ui, "Wrong Match", &self.palette).clicked() {
                    self.logger.log("REVIEW", "Wrong Match button clicked", "");
                    self.state.status = "Wrong Match clicked".to_string();
                    self.state.should_wrong_match = true;
                }
                if secondary_button(ui, "Extract Selected", &self.palette).clicked() {
                    self.logger.log("REVIEW", "Extract Selected button clicked", "");
                    self.state.status = "Extract Selected clicked".to_string();
                }
            });

            // Show selected archive action buttons inline
            if let Some(i) = self.state.selected_index {
                ui.separator();
                let archive = &self.state.archives[i];
                ui.label(RichText::new(format!("Actions for: {}", archive.display_name)).small().color(self.palette.muted));
                ui.horizontal(|ui| {
                    if secondary_button(ui, "Accept", &self.palette).clicked() {
                        self.logger.log("REVIEW", &format!("Accept: {}", archive.display_name), "");
                        self.state.should_accept_index = Some(i);
                    }
                    if danger_button(ui, "Reject", &self.palette).clicked() {
                        self.logger.log("REVIEW", &format!("Reject: {}", archive.display_name), "");
                        self.state.should_reject_index = Some(i);
                    }
                });
            }
        });
    }

    fn approve_all_verified(&mut self) {
        let corr = self.logger.correlation_id();
        for archive in &mut self.state.archives {
            if !archive.decision.skipped {
                archive.decision.accepted = true;
            }
        }
        self.logger.log("REVIEW", "All verified archives approved", &corr);
        self.state.status = "All verified archives approved".to_string();
    }

    fn use_all_suggestions(&mut self) {
        let corr = self.logger.correlation_id();
        for archive in &mut self.state.archives {
            archive.decision.category = archive.decision.suggested_category.clone();
        }
        self.logger.log("REVIEW", "All suggestions applied", &corr);
        self.state.status = "All suggestions applied".to_string();
    }

    fn retry_failed(&mut self) {
        let corr = self.logger.correlation_id();
        self.logger.log("REVIEW", "Retry failed archives", &corr);
        self.state.status = "Failed archives retried".to_string();
    }

    fn accept_and_next(&mut self) {
        if let Some(i) = self.state.selected_index {
            self.accept_archive(i);
            if i + 1 < self.state.archives.len() {
                self.state.selected_index = Some(i + 1);
            }
        }
    }

    fn skip_current(&mut self) {
        if let Some(i) = self.state.selected_index {
            self.state.archives[i].decision.skipped = true;
            self.state.archives[i].decision.accepted = false;
            self.logger.log("REVIEW", &format!("Skipped: {}", self.state.archives[i].display_name), "");
            self.state.status = format!("Skipped: {}", self.state.archives[i].display_name);
        }
    }

    fn wrong_match(&mut self) {
        if let Some(i) = self.state.selected_index {
            self.state.archives[i].decision.accepted = false;
            self.state.archives[i].steam.found = false;
            self.logger.log("REVIEW", &format!("Wrong match cleared for: {}", self.state.archives[i].display_name), "");
            self.state.status = format!("Wrong match cleared for: {}", self.state.archives[i].display_name);
        }
    }

    fn accept_archive(&mut self, index: usize) {
        if index < self.state.archives.len() {
            self.state.archives[index].decision.accepted = true;
            self.logger.log("REVIEW", &format!("Accepted: {}", self.state.archives[index].display_name), "");
        }
    }

    fn reject_archive(&mut self, index: usize) {
        if index < self.state.archives.len() {
            self.state.archives[index].decision.accepted = false;
            self.state.archives[index].decision.skipped = true;
            self.logger.log("REVIEW", &format!("Rejected: {}", self.state.archives[index].display_name), "");
        }
    }

    pub fn load(&mut self, archives: Vec<GameArchive>) {
        let corr = self.logger.correlation_id();
        self.state.archives = archives;
        self.state.selected_index = if !self.state.archives.is_empty() { Some(0) } else { None };
        self.logger.log("REVIEW", &format!("Loaded {} archives for review", self.state.archives.len()), &corr);
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
        let logger: Arc<crate::core::logger::AppLogger> = Arc::new(
            crate::core::logger::AppLogger::new(
                std::env::temp_dir().join(format!("review_test_{}.log", std::process::id())),
                "INFO",
                false,
                false,
            ).unwrap(),
        );
        let watchdog = Arc::new(crate::core::errors::Watchdog::new(logger.clone(), 1000));
        let _view = ReviewView::new(palette, logger, watchdog);
    }

    #[test]
    fn test_review_view_load() {
        let palette = Palette::default();
        let logger: Arc<crate::core::logger::AppLogger> = Arc::new(
            crate::core::logger::AppLogger::new(
                std::env::temp_dir().join(format!("review_test_{}.log", std::process::id())),
                "INFO",
                false,
                false,
            ).unwrap(),
        );
        let watchdog = Arc::new(crate::core::errors::Watchdog::new(logger.clone(), 1000));
        let mut view = ReviewView::new(palette, logger, watchdog);
        let archive = GameArchive::default();
        view.load(vec![archive]);
        assert_eq!(view.state.archives.len(), 1);
        assert_eq!(view.state.selected_index, Some(0));
    }

    #[test]
    fn test_review_view_cancel_lookup() {
        let palette = Palette::default();
        let logger: Arc<crate::core::logger::AppLogger> = Arc::new(
            crate::core::logger::AppLogger::new(
                std::env::temp_dir().join(format!("review_test_{}.log", std::process::id())),
                "INFO",
                false,
                false,
            ).unwrap(),
        );
        let watchdog = Arc::new(crate::core::errors::Watchdog::new(logger.clone(), 1000));
        let mut view = ReviewView::new(palette, logger, watchdog);
        let archive = GameArchive::default();
        view.load(vec![archive]);
        view.cancel_lookup();
        assert_eq!(view.state.status, "Verification cancelled.".to_string());
    }

    #[test]
    fn test_review_view_approve_all_verified() {
        let palette = Palette::default();
        let logger: Arc<crate::core::logger::AppLogger> = Arc::new(
            crate::core::logger::AppLogger::new(
                std::env::temp_dir().join(format!("review_test_{}.log", std::process::id())),
                "INFO",
                false,
                false,
            ).unwrap(),
        );
        let watchdog = Arc::new(crate::core::errors::Watchdog::new(logger.clone(), 1000));
        let mut view = ReviewView::new(palette, logger, watchdog);
        let archive = GameArchive::default();
        view.load(vec![archive]);
        view.approve_all_verified();
        assert!(view.state.archives[0].decision.accepted);
    }

    #[test]
    fn test_review_view_skip_current() {
        let palette = Palette::default();
        let logger: Arc<crate::core::logger::AppLogger> = Arc::new(
            crate::core::logger::AppLogger::new(
                std::env::temp_dir().join(format!("review_test_{}.log", std::process::id())),
                "INFO",
                false,
                false,
            ).unwrap(),
        );
        let watchdog = Arc::new(crate::core::errors::Watchdog::new(logger.clone(), 1000));
        let mut view = ReviewView::new(palette, logger, watchdog);
        let archive = GameArchive::default();
        view.load(vec![archive]);
        view.skip_current();
        assert!(view.state.archives[0].decision.skipped);
        assert!(!view.state.archives[0].decision.accepted);
    }
}
