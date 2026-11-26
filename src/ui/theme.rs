//! UI theme: colors and shared styling for the egui screens.
//! Completely redesigned for a modern, polished, high-contrast look.
//!
//! 2026-11-26: Modern dark theme with improved contrast, spacing, typography,
//! and visual hierarchy. Inspired by modern dark UIs (Linear, Vercel, etc.).

use egui::{Color32, RichText, Stroke, Vec2};

/// Palette colors — modern dark theme with vibrant accent and excellent contrast.
#[derive(Clone)]
pub struct Palette {
    /// Background (darkest — app background)
    pub bg: Color32,
    /// Main panel background (slightly lighter than bg)
    pub panel: Color32,
    /// Secondary panel background (card level)
    pub panel2: Color32,
    /// Tertiary panel background (elevated cards, inputs)
    pub panel3: Color32,
    /// Quaternary panel background (hover states)
    pub panel4: Color32,
    /// Primary text (high contrast)
    pub text: Color32,
    /// Secondary text (muted)
    pub text_secondary: Color32,
    /// Muted text (alias for text_secondary)
    pub muted: Color32,
    /// Tertiary text (disabled/placeholder)
    pub text_tertiary: Color32,
    /// Border color (subtle)
    pub border: Color32,
    /// Border color (focused/active)
    pub border_focus: Color32,
    /// Primary accent (vibrant blue — primary actions)
    pub accent: Color32,
    /// Accent hover (darker blue)
    pub accent_hover: Color32,
    /// Accent highlight (alias for hover)
    pub accent_hi: Color32,
    /// Accent active (even darker)
    pub accent_active: Color32,
    /// Accent light (tinted background)
    pub accent_light: Color32,
    /// Success green
    pub green: Color32,
    /// Success light
    pub green_light: Color32,
    /// Warning orange
    pub orange: Color32,
    /// Warning light
    pub orange_light: Color32,
    /// Error red
    pub red: Color32,
    /// Error light
    pub red_light: Color32,
    /// Danger red (stronger)
    pub danger: Color32,
    /// Entry background (for list items)
    pub entry_bg: Color32,
    /// Entry hover background
    pub entry_hover: Color32,
    /// Entry selected background
    pub entry_selected: Color32,
    /// Cyan accent
    pub cyan: Color32,
    /// Sky blue
    pub sky: Color32,
    /// Pink accent
    pub pink: Color32,
    /// Purple accent
    pub purple: Color32,
    /// Violet accent
    pub violet: Color32,
    /// Shadow color (for depth)
    pub shadow: Color32,
}

impl Default for Palette {
    fn default() -> Self {
        Palette {
            bg: Color32::from_rgb(0x09, 0x09, 0x0b),
            panel: Color32::from_rgb(0x0f, 0x0f, 0x13),
            panel2: Color32::from_rgb(0x18, 0x18, 0x1d),
            panel3: Color32::from_rgb(0x1f, 0x1f, 0x26),
            panel4: Color32::from_rgb(0x27, 0x27, 0x2f),
            text: Color32::from_rgb(0xf1, 0xf1, 0xf5),
            text_secondary: Color32::from_rgb(0xa1, 0xa1, 0xaa),
            muted: Color32::from_rgb(0xa1, 0xa1, 0xaa),
            text_tertiary: Color32::from_rgb(0x71, 0x71, 0x79),
            border: Color32::from_rgb(0x2a, 0x2a, 0x33),
            border_focus: Color32::from_rgb(0x58, 0xa6, 0xff),
            accent: Color32::from_rgb(0x58, 0xa6, 0xff),
            accent_hover: Color32::from_rgb(0x4a, 0x8f, 0xe0),
            accent_hi: Color32::from_rgb(0x4a, 0x8f, 0xe0),
            accent_active: Color32::from_rgb(0x3d, 0x7a, 0xc9),
            accent_light: Color32::from_rgb(0x43, 0x84, 0xd4).linear_multiply(0.15),
            green: Color32::from_rgb(0x4c, 0xd0, 0x8c),
            green_light: Color32::from_rgb(0x4c, 0xd0, 0x8c).linear_multiply(0.15),
            orange: Color32::from_rgb(0xf0, 0x9c, 0x4c),
            orange_light: Color32::from_rgb(0xf0, 0x9c, 0x4c).linear_multiply(0.15),
            red: Color32::from_rgb(0xff, 0x5a, 0x5a),
            red_light: Color32::from_rgb(0xff, 0x5a, 0x5a).linear_multiply(0.15),
            danger: Color32::from_rgb(0xef, 0x44, 0x44),
            entry_bg: Color32::from_rgb(0x18, 0x18, 0x1d),
            entry_hover: Color32::from_rgb(0x2a, 0x2a, 0x33),
            entry_selected: Color32::from_rgb(0x58, 0xa6, 0xff).linear_multiply(0.2),
            cyan: Color32::from_rgb(0x4d, 0xd0, 0xd0),
            sky: Color32::from_rgb(0x6b, 0xb6, 0xff),
            pink: Color32::from_rgb(0xff, 0x8c, 0xb2),
            purple: Color32::from_rgb(0xb3, 0x88, 0xff),
            violet: Color32::from_rgb(0xa7, 0x8b, 0xfa),
            shadow: Color32::from_rgb(0x00, 0x00, 0x00).linear_multiply(0.3),
        }
    }
}

/// Default corner radius for panels, buttons, and inputs.
pub const CORNER_RADIUS: f32 = 10.0;

/// Small corner radius for pills and badges.
pub const SMALL_RADIUS: f32 = 6.0;

/// Large corner radius for prominent cards.
pub const LARGE_RADIUS: f32 = 16.0;

/// Standard spacing unit (8px grid).
pub const SPACING: f32 = 8.0;

/// Double spacing unit (16px).
pub const SPACING_LG: f32 = 16.0;

/// Quad spacing unit (32px).
pub const SPACING_XL: f32 = 32.0;

/// A pill-shaped badge helper for egui.
pub fn pill(ui: &mut egui::Ui, text: &str, kind: &str, palette: &Palette) -> egui::Response {
    let (bg, fg) = match kind {
        "accent" => (palette.accent, palette.bg),
        "good" => (palette.green, palette.bg),
        "warn" => (palette.orange, palette.bg),
        "bad" | "danger" => (palette.danger, palette.bg),
        "muted" => (palette.text_secondary, palette.text),
        "cyan" => (palette.cyan, palette.bg),
        "purple" => (palette.purple, palette.bg),
        "violet" => (palette.violet, palette.bg),
        _ => (palette.accent, palette.bg),
    };

    let label = RichText::new(text).color(fg).small().strong();
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
    ui.separator();
    ui.add_space(SPACING);
}

/// Section header with accent-colored label and subtle underline.
pub fn section_header(ui: &mut egui::Ui, palette: &Palette, text: &str) {
    ui.add_space(SPACING_LG);
    ui.label(
        RichText::new(text)
            .color(palette.accent)
            .strong()
            .small(),
    );
    ui.add_space(SPACING);
}

/// A styled primary button with accent fill and hover states.
pub fn primary_button(ui: &mut egui::Ui, text: &str, palette: &Palette) -> egui::Response {
    ui.add(
        egui::Button::new(RichText::new(text).color(Color32::WHITE).strong())
            .fill(palette.accent)
            .corner_radius(CORNER_RADIUS)
            .min_size(Vec2::new(140.0, 40.0)),
    )
}

/// A styled secondary button with panel2 fill and accent border.
pub fn secondary_button(ui: &mut egui::Ui, text: &str, palette: &Palette) -> egui::Response {
    ui.add(
        egui::Button::new(RichText::new(text).color(palette.accent).strong())
            .fill(palette.panel2)
            .corner_radius(CORNER_RADIUS)
            .stroke(Stroke { width: 1.5_f32, color: palette.accent })
            .min_size(Vec2::new(140.0, 40.0)),
    )
}

/// A danger button with red fill.
pub fn danger_button(ui: &mut egui::Ui, text: &str, palette: &Palette) -> egui::Response {
    ui.add(
        egui::Button::new(RichText::new(text).color(Color32::WHITE).strong())
            .fill(palette.danger)
            .corner_radius(CORNER_RADIUS)
            .min_size(Vec2::new(140.0, 40.0)),
    )
}

/// A ghost button (transparent fill, accent text).
pub fn ghost_button(ui: &mut egui::Ui, text: &str, palette: &Palette) -> egui::Response {
    ui.add(
        egui::Button::new(RichText::new(text).color(palette.accent).strong())
            .fill(palette.bg)
            .corner_radius(CORNER_RADIUS)
            .stroke(Stroke { width: 1.0_f32, color: palette.border })
            .min_size(Vec2::new(140.0, 40.0)),
    )
}

/// A card container — draws a rounded panel background with subtle border.
pub fn card(ui: &mut egui::Ui, palette: &Palette, contents: impl FnOnce(&mut egui::Ui)) {
    let rect = ui.min_rect();
    ui.painter().rect_filled(
        rect.expand(1.0),
        CORNER_RADIUS,
        palette.panel2,
    );
    contents(ui);
}

/// A card container with accent border (for active/selected cards).
pub fn card_accent(ui: &mut egui::Ui, palette: &Palette, contents: impl FnOnce(&mut egui::Ui)) {
    let rect = ui.min_rect();
    ui.painter().rect_filled(
        rect.expand(1.0),
        CORNER_RADIUS,
        palette.panel3,
    );
    contents(ui);
}

/// A list item row with hover highlight and selection.
pub fn list_item(ui: &mut egui::Ui, palette: &Palette, selected: bool, contents: impl FnOnce(&mut egui::Ui)) {
    let bg = if selected {
        palette.entry_selected
    } else {
        palette.entry_bg
    };
    let rect = ui.min_rect();
    ui.painter().rect_filled(
        rect.expand(1.0),
        SMALL_RADIUS,
        bg,
    );
    contents(ui);
}

/// A stat card showing a number with a label.
pub fn stat_card(ui: &mut egui::Ui, palette: &Palette, value: &str, label: &str, color: Color32) {
    card(ui, palette, |ui| {
        ui.add_space(SPACING);
        ui.label(RichText::new(value).color(color).strong().size(24.0));
        ui.add_space(SPACING / 2.0);
        ui.label(RichText::new(label).color(palette.text_secondary).small());
        ui.add_space(SPACING);
    });
}

/// An info card showing a key-value pair.
pub fn info_card(ui: &mut egui::Ui, palette: &Palette, key: &str, value: &str) {
    ui.horizontal(|ui| {
        ui.label(RichText::new(key).color(palette.text_secondary).small());
        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
            ui.label(RichText::new(value).color(palette.text).strong());
        });
    });
}

/// A heading text.
pub fn heading(ui: &mut egui::Ui, palette: &Palette, text: &str) {
    ui.label(RichText::new(text).color(palette.text).strong().size(18.0));
    ui.add_space(SPACING);
}

/// A subheading text.
pub fn subheading(ui: &mut egui::Ui, palette: &Palette, text: &str) {
    ui.label(RichText::new(text).color(palette.text_secondary).strong().size(16.0));
    ui.add_space(SPACING);
}

/// Body text.
pub fn body_text(ui: &mut egui::Ui, palette: &Palette, text: &str) {
    ui.label(RichText::new(text).color(palette.text).small());
    ui.add_space(SPACING);
}

/// A muted text label.
pub fn muted_text(ui: &mut egui::Ui, palette: &Palette, text: &str) {
    ui.label(RichText::new(text).color(palette.text_tertiary).small());
}

/// A small caps label.
pub fn small_caps(ui: &mut egui::Ui, palette: &Palette, text: &str) {
    ui.label(
        RichText::new(text)
            .color(palette.text_secondary)
            .small(),
    );
}

/// A divider with optional text in the middle.
pub fn divider_with_text(ui: &mut egui::Ui, palette: &Palette, text: &str) {
    ui.add_space(SPACING_LG);
    ui.horizontal(|ui| {
        let rect = ui.min_rect();
        ui.painter().line_segment(
            [
                egui::pos2(rect.left(), rect.center().y),
                egui::pos2(rect.center().x - 40.0, rect.center().y),
            ],
            Stroke { width: 1.0_f32, color: palette.border },
        );
        ui.label(RichText::new(text).color(palette.text_secondary).small());
        let rect = ui.min_rect();
        ui.painter().line_segment(
            [
                egui::pos2(rect.center().x + 40.0, rect.center().y),
                egui::pos2(rect.right(), rect.center().y),
            ],
            Stroke { width: 1.0_f32, color: palette.border },
        );
    });
    ui.add_space(SPACING_LG);
}

/// A progress bar with label.
pub fn progress_bar_with_label(ui: &mut egui::Ui, palette: &Palette, label: &str, progress: f32) {
    ui.label(RichText::new(label).color(palette.text_secondary).small());
    ui.add_space(SPACING / 2.0);
    ui.add(
        egui::ProgressBar::new(progress)
            .desired_width(300.0)
            .fill(palette.accent),
    );
    ui.add_space(SPACING);
}

/// A navigation sidebar item.
pub fn nav_item(ui: &mut egui::Ui, palette: &Palette, icon: &str, label: &str, active: bool) -> egui::Response {
    let bg = if active {
        palette.accent_light
    } else {
        palette.bg
    };
    let text_color = if active {
        palette.accent
    } else {
        palette.text_secondary
    };
    ui.add_space(SPACING / 2.0);
    let response = ui.selectable_label(active, RichText::new(format!("{}  {}", icon, label)).color(text_color).strong());
    if response.hovered() && !active {
        ui.painter().rect_filled(
            ui.min_rect().expand(2.0),
            SMALL_RADIUS,
            palette.entry_hover,
        );
    }
    ui.add_space(SPACING / 2.0);
    response
}