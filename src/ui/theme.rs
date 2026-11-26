//! UI theme: colors and shared styling for the egui screens.
//! Completely redesigned for a modern, polished look.
//!
//! 2026-11-25: New theme with rounded corners, pill buttons, improved palette.

use egui::{Color32, RichText, Stroke, Vec2};

/// Palette colors — modern dark theme with vibrant accent.
#[derive(Clone)]
pub struct Palette {
    /// Background (darkest)
    pub bg: Color32,
    /// Main panel background
    pub panel: Color32,
    /// Secondary panel background
    pub panel2: Color32,
    /// Tertiary panel background (elevated cards)
    pub panel3: Color32,
    /// Primary text
    pub text: Color32,
    /// Muted/secondary text
    pub muted: Color32,
    /// Border color
    pub border: Color32,
    /// Primary accent (blue)
    pub accent: Color32,
    /// Accent highlight (lighter blue)
    pub accent_hi: Color32,
    /// Accent hover (darker blue)
    pub accent_hover: Color32,
    /// Success green
    pub green: Color32,
    /// Warning orange
    pub orange: Color32,
    /// Error red
    pub red: Color32,
    /// Danger red (stronger)
    pub danger: Color32,
    /// Danger hover
    pub danger_hover: Color32,
    /// Danger text
    pub danger_text: Color32,
    /// Entry background (for list items)
    pub entry_bg: Color32,
    /// Cyan accent
    pub cyan: Color32,
    /// Sky blue
    pub sky: Color32,
    /// Pink accent
    pub pink: Color32,
    /// Purple accent
    pub purple: Color32,
}

impl Default for Palette {
    fn default() -> Self {
        Palette {
            bg: Color32::from_rgb(0x0a, 0x0b, 0x10),
            panel: Color32::from_rgb(0x14, 0x16, 0x1d),
            panel2: Color32::from_rgb(0x1c, 0x1f, 0x29),
            panel3: Color32::from_rgb(0x24, 0x28, 0x34),
            text: Color32::from_rgb(0xea, 0xec, 0xf2),
            muted: Color32::from_rgb(0x8b, 0x93, 0xa1),
            border: Color32::from_rgb(0x2e, 0x33, 0x40),
            accent: Color32::from_rgb(0x58, 0xa6, 0xff),
            accent_hi: Color32::from_rgb(0x7c, 0xb9, 0xff),
            accent_hover: Color32::from_rgb(0x3d, 0x8b, 0xd9),
            green: Color32::from_rgb(0x4c, 0xd0, 0x8c),
            orange: Color32::from_rgb(0xf0, 0x9c, 0x4c),
            red: Color32::from_rgb(0xff, 0x5a, 0x5a),
            danger: Color32::from_rgb(0xff, 0x4a, 0x4a),
            danger_hover: Color32::from_rgb(0xdb, 0x3a, 0x3a),
            danger_text: Color32::from_rgb(0xff, 0x8a, 0x8a),
            entry_bg: Color32::from_rgb(0x18, 0x1b, 0x24),
            cyan: Color32::from_rgb(0x4d, 0xd0, 0xd0),
            sky: Color32::from_rgb(0x6b, 0xb6, 0xff),
            pink: Color32::from_rgb(0xff, 0x8c, 0xb2),
            purple: Color32::from_rgb(0xb3, 0x88, 0xff),
        }
    }
}

/// Default corner radius for panels, buttons, and inputs.
pub const CORNER_RADIUS: f32 = 8.0;

/// Small corner radius for pills and badges.
pub const SMALL_RADIUS: f32 = 4.0;

/// A pill-shaped label helper for egui.
pub fn pill(ui: &mut egui::Ui, text: &str, kind: &str, palette: &Palette) -> egui::Response {
    let (bg, fg) = match kind {
        "accent" => (palette.accent, palette.bg),
        "good" => (palette.green, palette.bg),
        "warn" => (palette.orange, palette.bg),
        "bad" | "danger" => (palette.danger, palette.bg),
        "muted" => (palette.muted, palette.text),
        "cyan" => (palette.cyan, palette.bg),
        "purple" => (palette.purple, palette.bg),
        _ => (palette.accent, palette.bg),
    };

    let label = RichText::new(text).color(fg).small();
    ui.add(
        egui::Button::new(label)
            .fill(bg)
            .corner_radius(SMALL_RADIUS)
            .frame(false)
            .min_size(Vec2::new(0.0, 0.0)),
    )
}

/// A horizontal rule separator with padding.
pub fn separator(ui: &mut egui::Ui, palette: &Palette) {
    let rect = ui.min_rect();
    ui.painter().line_segment(
        [
            egui::pos2(rect.left(), rect.center().y),
            egui::pos2(rect.right(), rect.center().y),
        ],
        Stroke { width: 1.0_f32, color: palette.border },
    );
    ui.label("");
}

/// Section header with accent-colored label and underline.
pub fn section_header(ui: &mut egui::Ui, palette: &Palette, text: &str) {
    ui.label(
        RichText::new(text)
            .color(palette.accent)
            .strong()
            .small(),
    );
    ui.separator();
}

/// A styled primary button with accent fill.
pub fn primary_button(ui: &mut egui::Ui, text: &str, palette: &Palette) -> egui::Response {
    ui.add(
        egui::Button::new(RichText::new(text).color(Color32::WHITE))
            .fill(palette.accent)
            .corner_radius(CORNER_RADIUS)
            .min_size(Vec2::new(110.0, 34.0)),
    )
}

/// A styled secondary button with panel2 fill and accent text.
pub fn secondary_button(ui: &mut egui::Ui, text: &str, palette: &Palette) -> egui::Response {
    ui.add(
        egui::Button::new(RichText::new(text).color(palette.accent))
            .fill(palette.panel2)
            .corner_radius(CORNER_RADIUS)
            .stroke(Stroke { width: 1.0_f32, color: palette.accent })
            .min_size(Vec2::new(110.0, 34.0)),
    )
}

/// A danger button with red fill.
pub fn danger_button(ui: &mut egui::Ui, text: &str, palette: &Palette) -> egui::Response {
    ui.add(
        egui::Button::new(RichText::new(text).color(palette.bg))
            .fill(palette.danger)
            .corner_radius(CORNER_RADIUS)
            .min_size(Vec2::new(110.0, 34.0)),
    )
}

/// A card container — draws a rounded panel background. Caller adds content in the same ui.
pub fn card(ui: &mut egui::Ui, palette: &Palette, contents: impl FnOnce(&mut egui::Ui)) {
    let rect = ui.min_rect();
    ui.painter().rect_filled(
        rect.expand(2.0),
        CORNER_RADIUS,
        palette.panel2,
    );
    contents(ui);
}

/// A list item row with hover highlight.
pub fn list_item(ui: &mut egui::Ui, palette: &Palette, selected: bool, contents: impl FnOnce(&mut egui::Ui)) {
    let bg = if selected {
        palette.accent.linear_multiply(0.15)
    } else {
        palette.entry_bg
    };
    let rect = ui.min_rect();
    ui.painter().rect_filled(rect, SMALL_RADIUS, bg);
    contents(ui);
}
