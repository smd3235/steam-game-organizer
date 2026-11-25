//! CategoryEvidencePanel: shows why Steam suggested a category, what terms fired, runners-up.
//! Stub conversion of `ui/widgets/category_evidence_panel.py` — egui, not Tkinter.
//!
//! 2026-11-25: egui category evidence panel stub in the Rust conversion.

use egui::{RichText, Ui};
use crate::ui::theme::Palette;

#[derive(Default)]
pub struct CategoryEvidencePanelState {
    pub suggested: String,
    pub chosen: String,
    pub reason: String,
    pub remembered: Option<String>,
    pub runners_up: Vec<(String, f32)>,
    pub no_evidence: bool,
}

pub struct CategoryEvidencePanel {
    pub state: CategoryEvidencePanelState,
    pub palette: Palette,
}

impl CategoryEvidencePanel {
    pub fn new(palette: Palette) -> Self {
        CategoryEvidencePanel {
            state: CategoryEvidencePanelState::default(),
            palette,
        }
    }

    pub fn ui(&mut self, ui: &mut Ui) {
        ui.group(|ui| {
            ui.label(RichText::new("Why This Category").strong().color(self.palette.accent_hi));
            ui.separator();

            if self.state.no_evidence {
                ui.label(RichText::new("No category reasoning was recorded for this game.").color(self.palette.muted).italics());
                return;
            }

            ui.horizontal(|ui| {
                ui.label(RichText::new(&self.state.suggested).strong());
                ui.label(RichText::new(format!(" · {}", self.state.reason)).small().color(self.palette.muted));
            });

            if let Some(ref remembered) = self.state.remembered {
                if remembered.as_str() != self.state.chosen.as_str() {
                    ui.label(RichText::new(format!("Remembered as {} instead.", remembered)).color(self.palette.orange).small());
                }
            }

            if !self.state.runners_up.is_empty() {
                ui.separator();
                ui.label(RichText::new("Also considered:").small().color(self.palette.muted).strong());
                for (name, score) in &self.state.runners_up {
                    ui.label(RichText::new(format!("{} ({:.0})", name, score)).small().color(self.palette.text));
                }
            }
        });
    }

    pub fn set_evidence(
        &mut self,
        suggested: String,
        chosen: String,
        reason: String,
        remembered: Option<String>,
        runners_up: Vec<(String, f32)>,
    ) {
        self.state.suggested = suggested;
        self.state.chosen = chosen;
        self.state.reason = reason;
        self.state.remembered = remembered;
        self.state.runners_up = runners_up;
        self.state.no_evidence = false;
    }

    pub fn set_no_evidence(&mut self) {
        self.state.no_evidence = true;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_category_evidence_panel_new() {
        let palette = Palette::default();
        let _panel = CategoryEvidencePanel::new(palette);
    }

    #[test]
    fn test_category_evidence_panel_set_evidence() {
        let palette = Palette::default();
        let mut panel = CategoryEvidencePanel::new(palette);
        panel.set_evidence(
            "Action".to_string(),
            "Action".to_string(),
            "matched by tag".to_string(),
            Some("RPG".to_string()),
            vec![("RPG".to_string(), 0.6)],
        );
        assert!(!panel.state.no_evidence);
        assert_eq!(panel.state.suggested, "Action");
        assert_eq!(panel.state.runners_up.len(), 1);
    }

    #[test]
    fn test_category_evidence_panel_no_evidence() {
        let palette = Palette::default();
        let mut panel = CategoryEvidencePanel::new(palette);
        panel.set_no_evidence();
        assert!(panel.state.no_evidence);
    }
}
