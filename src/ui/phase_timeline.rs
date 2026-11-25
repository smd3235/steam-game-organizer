//! PhaseTimeline: row of stage chips showing every step of a run at once.
//! Stub conversion of `ui/phase_timeline.py` — egui chip row, not Tkinter.
//!
//! 2026-11-25: egui phase timeline in the Rust conversion.

use egui::{RichText, Ui};
use crate::ui::theme::Palette;

#[derive(Default, Clone, Copy, PartialEq, Eq, Debug)]
pub enum PhaseState {
    #[default]
    Pending,
    Active,
    Done,
    Failed,
    Skipped,
}

/// PhaseTimeline — a row of stage chips.
pub struct PhaseTimeline {
    pub states: Vec<(String, PhaseState)>,
    pub palette: Palette,
}

impl PhaseTimeline {
    pub fn new(palette: Palette) -> Self {
        PhaseTimeline {
            states: Vec::new(),
            palette,
        }
    }

    pub fn set_phases(&mut self, phases: &[(&str, &str)]) {
        self.states = phases.iter().map(|(key, _)| (key.to_string(), PhaseState::Pending)).collect();
    }

    pub fn start(&mut self, key: &str) {
        if let Some((_, state)) = self.states.iter_mut().find(|(k, _)| k == key) {
            *state = PhaseState::Active;
        }
    }

    pub fn done(&mut self, key: &str) {
        if let Some((_, state)) = self.states.iter_mut().find(|(k, _)| k == key) {
            *state = PhaseState::Done;
        }
    }

    pub fn fail(&mut self, key: &str) {
        if let Some((_, state)) = self.states.iter_mut().find(|(k, _)| k == key) {
            *state = PhaseState::Failed;
        }
    }

    pub fn skip(&mut self, key: &str) {
        if let Some((_, state)) = self.states.iter_mut().find(|(k, _)| k == key) {
            *state = PhaseState::Skipped;
        }
    }

    pub fn reset(&mut self) {
        for (_, state) in &mut self.states {
            *state = PhaseState::Pending;
        }
    }

    pub fn ui(&mut self, ui: &mut Ui) {
        ui.horizontal(|ui| {
            for (i, (key, state)) in self.states.iter().enumerate() {
                if i > 0 {
                    ui.label(RichText::new(" → ").color(self.palette.muted).small());
                }
                let (mark, color) = match state {
                    PhaseState::Pending => ("○", self.palette.muted),
                    PhaseState::Active => ("▸", self.palette.accent),
                    PhaseState::Done => ("✓", self.palette.green),
                    PhaseState::Failed => ("✗", self.palette.red),
                    PhaseState::Skipped => ("–", self.palette.muted),
                };
                ui.label(RichText::new(format!("{} {}", mark, key)).color(color).small());
            }
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_phase_timeline_new() {
        let palette = Palette::default();
        let timeline = PhaseTimeline::new(palette);
        assert!(timeline.states.is_empty());
    }

    #[test]
    fn test_phase_timeline_set_phases() {
        let palette = Palette::default();
        let mut timeline = PhaseTimeline::new(palette);
        timeline.set_phases(&[("cleanup", "Cleanup"), ("repair", "Repair")]);
        assert_eq!(timeline.states.len(), 2);
        assert_eq!(timeline.states[0].1, PhaseState::Pending);
    }

    #[test]
    fn test_phase_timeline_start_done() {
        let palette = Palette::default();
        let mut timeline = PhaseTimeline::new(palette);
        timeline.set_phases(&[("cleanup", "Cleanup"), ("repair", "Repair")]);
        timeline.start("cleanup");
        assert_eq!(timeline.states[0].1, PhaseState::Active);
        timeline.done("cleanup");
        assert_eq!(timeline.states[0].1, PhaseState::Done);
    }

    #[test]
    fn test_phase_timeline_reset() {
        let palette = Palette::default();
        let mut timeline = PhaseTimeline::new(palette);
        timeline.set_phases(&[("cleanup", "Cleanup")]);
        timeline.done("cleanup");
        timeline.reset();
        assert_eq!(timeline.states[0].1, PhaseState::Pending);
    }
}
