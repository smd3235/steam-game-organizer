//! UI theme: colors and shared styling for the egui screens.
//! Ported from `ui/theme.py` and `ui/palette.py`.
//!
//! 2026-11-25: egui theme stub in the Rust conversion.

use egui::{Color32, RichText};

/// Palette colors ported from `ui/palette.py`.
pub struct Palette {
    pub bg: Color32,
    pub panel: Color32,
    pub panel2: Color32,
    pub panel3: Color32,
    pub text: Color32,
    pub muted: Color32,
    pub border: Color32,
    pub accent: Color32,
    pub accent_hi: Color32,
    pub accent_hover: Color32,
    pub green: Color32,
    pub orange: Color32,
    pub red: Color32,
    pub danger: Color32,
    pub danger_hover: Color32,
    pub danger_text: Color32,
    pub entry_bg: Color32,
    pub cyan: Color32,
    pub sky: Color32,
    pub pink: Color32,
}

impl Default for Palette {
    fn default() -> Self {
        Palette {
            bg: Color32::from_rgb(0x0b, 0x0e, 0x14),
            panel: Color32::from_rgb(0x14, 0x18, 0x21),
            panel2: Color32::from_rgb(0x1e, 0x23, 0x2e),
            panel3: Color32::from_rgb(0x28, 0x2d, 0x3a),
            text: Color32::from_rgb(0xe7, 0xec, 0xf3),
            muted: Color32::from_rgb(0x8a, 0x91, 0x9e),
            border: Color32::from_rgb(0x2a, 0x2f, 0x3c),
            accent: Color32::from_rgb(0x4d, 0xa3, 0xff),
            accent_hi: Color32::from_rgb(0x6b, 0xb6, 0xff),
            accent_hover: Color32::from_rgb(0x2e, 0x8a, 0xdb),
            green: Color32::from_rgb(0x4c, 0xd0, 0x8c),
            orange: Color32::from_rgb(0xf0, 0x9c, 0x4c),
            red: Color32::from_rgb(0xff, 0x5a, 0x5a),
            danger: Color32::from_rgb(0xff, 0x4a, 0x4a),
            danger_hover: Color32::from_rgb(0xdb, 0x3a, 0x3a),
            danger_text: Color32::from_rgb(0xff, 0x8a, 0x8a),
            entry_bg: Color32::from_rgb(0x16, 0x1b, 0x24),
            cyan: Color32::from_rgb(0x4d, 0xd0, 0xd0),
            sky: Color32::from_rgb(0x6b, 0xb6, 0xff),
            pink: Color32::from_rgb(0xff, 0x8c, 0xb2),
        }
    }
}

/// A pill-shaped label helper for egui.
pub fn pill(ui: &mut egui::Ui, text: &str, kind: &str, palette: &Palette) -> egui::Response {
    let (_bg, fg) = match kind {
        "accent" => (palette.accent, palette.bg),
        "good" => (palette.green, palette.bg),
        "warn" => (palette.orange, palette.bg),
        "bad" | "danger" => (palette.danger, palette.bg),
        "muted" => (palette.muted, palette.text),
        _ => (palette.accent, palette.bg),
    };

    let label = egui::Label::new(RichText::new(text).color(fg));
    ui.add(label)
}

/// A horizontal rule separator.
pub fn separator(ui: &mut egui::Ui, palette: &Palette) {
    let rect = ui.min_rect();
    ui.painter().line_segment(
        [
            egui::pos2(rect.left(), rect.center().y),
            egui::pos2(rect.right(), rect.center().y),
        ],
        egui::Stroke::new(1.0_f32, palette.border),
    );
    ui.label("");
}
