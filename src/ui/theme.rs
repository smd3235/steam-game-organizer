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

/// Theme mode — user can switch between dark and light.
#[derive(Clone, Copy, PartialEq, Eq, Default, Debug)]
pub enum ThemeMode {
    #[default]
    Dark,
    Light,
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
            text_secondary: Color32::from_rgb(0xc0, 0xc0, 0xc8),
            muted: Color32::from_rgb(0xc0, 0xc0, 0xc8),
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

/// Light mode palette — high contrast, clean, accessible.
impl Palette {
    pub fn light_mode() -> Self {
        Palette {
            bg: Color32::from_rgb(0xf8, 0xf9, 0xfb),
            panel: Color32::from_rgb(0xff, 0xff, 0xff),
            panel2: Color32::from_rgb(0xf1, 0xf3, 0xf5),
            panel3: Color32::from_rgb(0xe9, 0xec, 0xef),
            panel4: Color32::from_rgb(0xde, 0xe2, 0xe6),
            text: Color32::from_rgb(0x11, 0x11, 0x13),
            text_secondary: Color32::from_rgb(0x4a, 0x4a, 0x52),
            muted: Color32::from_rgb(0x4a, 0x4a, 0x52),
            text_tertiary: Color32::from_rgb(0x8a, 0x8a, 0x92),
            border: Color32::from_rgb(0xd4, 0xd6, 0xda),
            border_focus: Color32::from_rgb(0x25, 0x63, 0xeb),
            accent: Color32::from_rgb(0x0e, 0x4d, 0xc9),
            accent_hover: Color32::from_rgb(0x1a, 0x5f, 0xe8),
            accent_hi: Color32::from_rgb(0x1a, 0x5f, 0xe8),
            accent_active: Color32::from_rgb(0x0b, 0x3f, 0xa8),
            accent_light: Color32::from_rgb(0x25, 0x63, 0xeb).linear_multiply(0.15),
            green: Color32::from_rgb(0x1e, 0x7a, 0x3c),
            green_light: Color32::from_rgb(0x1e, 0x7a, 0x3c).linear_multiply(0.15),
            orange: Color32::from_rgb(0xd9, 0x77, 0x06),
            orange_light: Color32::from_rgb(0xd9, 0x77, 0x06).linear_multiply(0.15),
            red: Color32::from_rgb(0xc2, 0x2a, 0x2a),
            red_light: Color32::from_rgb(0xc2, 0x2a, 0x2a).linear_multiply(0.15),
            danger: Color32::from_rgb(0xb0, 0x20, 0x20),
            entry_bg: Color32::from_rgb(0xf1, 0xf3, 0xf5),
            entry_hover: Color32::from_rgb(0xe5, 0xe7, 0xeb),
            entry_selected: Color32::from_rgb(0x0e, 0x4d, 0xc9).linear_multiply(0.2),
            cyan: Color32::from_rgb(0x0e, 0x7c, 0x86),
            sky: Color32::from_rgb(0x2b, 0x7a, 0xd8),
            pink: Color32::from_rgb(0xd6, 0x33, 0x66),
            purple: Color32::from_rgb(0x6b, 0x4c, 0xc9),
            violet: Color32::from_rgb(0x7c, 0x5c, 0xd8),
            shadow: Color32::from_rgb(0x00, 0x00, 0x00).linear_multiply(0.1),
        }
    }
}

/// Accessibility mode — for color blindness simulation and high contrast.
#[derive(Clone, Copy, PartialEq, Eq, Default, Debug)]
pub enum AccessibilityMode {
    #[default]
    Normal,
    Protanopia,   // Red-green blindness (red deficient)
    Deuteranopia, // Red-green blindness (green deficient)
    Tritanopia,   // Blue-yellow blindness
    HighContrast, // Maximum contrast for low vision
}

/// Accessibility configuration for the UI.
#[derive(Clone, Copy)]
pub struct AccessibilityConfig {
    pub mode: AccessibilityMode,
    pub screen_reader: bool,
    pub high_contrast_text: bool,
    pub large_text: bool,
    pub reduce_motion: bool,
}

impl Default for AccessibilityConfig {
    fn default() -> Self {
        AccessibilityConfig {
            mode: AccessibilityMode::Normal,
            screen_reader: false,
            high_contrast_text: false,
            large_text: false,
            reduce_motion: false,
        }
    }
}

/// Apply color blindness simulation to a color.
/// Uses standard color blindness simulation matrices.
fn apply_color_blindness(color: Color32, mode: AccessibilityMode) -> Color32 {
    let r = color[0] as f32 / 255.0;
    let g = color[1] as f32 / 255.0;
    let b = color[2] as f32 / 255.0;

    let (r_out, g_out, b_out) = match mode {
        AccessibilityMode::Protanopia => {
            // Protanopia simulation matrix
            let r_out = 0.567 * r + 0.433 * g;
            let g_out = 0.558 * r + 0.442 * g;
            let b_out = 0.0 * r + 0.0 * g + 1.0 * b;
            (r_out, g_out, b_out)
        }
        AccessibilityMode::Deuteranopia => {
            // Deuteranopia simulation matrix
            let r_out = 0.625 * r + 0.375 * g;
            let g_out = 0.7 * r + 0.3 * g;
            let b_out = 0.0 * r + 0.0 * g + 1.0 * b;
            (r_out, g_out, b_out)
        }
        AccessibilityMode::Tritanopia => {
            // Tritanopia simulation matrix
            let r_out = 0.95 * r + 0.05 * g;
            let g_out = 0.0 * r + 0.433 * g + 0.567 * b;
            let b_out = 0.0 * r + 0.475 * g + 0.525 * b;
            (r_out, g_out, b_out)
        }
        AccessibilityMode::HighContrast => {
            // Increase contrast significantly
            let luminance = 0.299 * r + 0.587 * g + 0.114 * b;
            let factor = if luminance > 0.5 { 1.0 / luminance } else { luminance / 0.5 };
            let r_out = (r * factor).clamp(0.0, 1.0);
            let g_out = (g * factor).clamp(0.0, 1.0);
            let b_out = (b * factor).clamp(0.0, 1.0);
            (r_out, g_out, b_out)
        }
        AccessibilityMode::Normal => (r, g, b),
    };

    Color32::from_rgb(
        (r_out * 255.0).clamp(0.0, 255.0) as u8,
        (g_out * 255.0).clamp(0.0, 255.0) as u8,
        (b_out * 255.0).clamp(0.0, 255.0) as u8,
    )
}

/// Calculate WCAG contrast ratio between two colors.
/// Returns a value >= 1.0; higher means better contrast.
/// WCAG AA requires 4.5:1 for normal text, 3:1 for large text.
/// WCAG AAA requires 7:1 for normal text, 4.5:1 for large text.
pub fn contrast_ratio(fg: Color32, bg: Color32) -> f32 {
    let lum_fg = relative_luminance(fg);
    let lum_bg = relative_luminance(bg);
    let lighter = lum_fg.max(lum_bg);
    let darker = lum_fg.min(lum_bg);
    (lighter + 0.05) / (darker + 0.05)
}

/// Calculate relative luminance of a color (per WCAG spec).
fn relative_luminance(color: Color32) -> f32 {
    let srgb = |c: u8| {
        let c = c as f32 / 255.0;
        if c <= 0.03928 {
            c / 12.92
        } else {
            ((c + 0.055) / 1.055).powf(2.4)
        }
    };
    0.2126 * srgb(color[0]) + 0.7152 * srgb(color[1]) + 0.0722 * srgb(color[2])
}

/// Apply accessibility mode to a palette, returning a modified palette.
pub fn apply_accessibility(palette: &Palette, config: &AccessibilityConfig) -> Palette {
    let mut p = palette.clone();

    match config.mode {
        AccessibilityMode::Normal => {}
        AccessibilityMode::Protanopia | AccessibilityMode::Deuteranopia | AccessibilityMode::Tritanopia => {
            p.bg = apply_color_blindness(p.bg, config.mode);
            p.panel = apply_color_blindness(p.panel, config.mode);
            p.panel2 = apply_color_blindness(p.panel2, config.mode);
            p.panel3 = apply_color_blindness(p.panel3, config.mode);
            p.panel4 = apply_color_blindness(p.panel4, config.mode);
            p.accent = apply_color_blindness(p.accent, config.mode);
            p.green = apply_color_blindness(p.green, config.mode);
            p.orange = apply_color_blindness(p.orange, config.mode);
            p.red = apply_color_blindness(p.red, config.mode);
            p.danger = apply_color_blindness(p.danger, config.mode);
            p.cyan = apply_color_blindness(p.cyan, config.mode);
            p.pink = apply_color_blindness(p.pink, config.mode);
            p.purple = apply_color_blindness(p.purple, config.mode);
            p.violet = apply_color_blindness(p.violet, config.mode);
        }
        AccessibilityMode::HighContrast => {
            p.bg = apply_color_blindness(p.bg, config.mode);
            p.panel = apply_color_blindness(p.panel, config.mode);
            p.panel2 = apply_color_blindness(p.panel2, config.mode);
            p.panel3 = apply_color_blindness(p.panel3, config.mode);
            p.panel4 = apply_color_blindness(p.panel4, config.mode);
            p.accent = apply_color_blindness(p.accent, config.mode);
            p.border = apply_color_blindness(p.border, config.mode);
            p.border_focus = apply_color_blindness(p.border_focus, config.mode);
        }
    }

    p
}

/// Default corner radius for panels, buttons, and inputs.
pub const CORNER_RADIUS: f32 = 10.0;

/// Circular radius for step indicators and badges.
pub const CIRCLE_RADIUS: f32 = 12.0;

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

/// A pill-shaped badge helper.
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
pub fn separator(ui: &mut egui::Ui) {
    ui.separator();
    ui.add_space(SPACING);
}

/// Section header with accent-colored label.
pub fn section_header(ui: &mut egui::Ui, palette: &Palette, text: &str) {
    ui.add_space(SPACING_LG);
    ui.label(RichText::new(text).color(palette.accent).strong().small());
    ui.add_space(SPACING);
}

/// A styled primary button with hover feedback and disabled state.
pub fn primary_button(
    ui: &mut egui::Ui,
    text: &str,
    palette: &Palette,
    enabled: bool,
) -> egui::Response {
    let button = egui::Button::new(RichText::new(text).color(Color32::WHITE).strong().size(14.0))
        .fill(palette.accent)
        .corner_radius(CORNER_RADIUS)
        .min_size(Vec2::new(110.0, 36.0));
    if enabled {
        ui.add(button)
    } else {
        ui.add_enabled(false, button)
    }
}

/// A styled secondary button with panel3 fill and accent border, with hover feedback.
/// Uses panel3 (slightly lighter than card background panel2) so buttons are visible inside cards.
pub fn secondary_button(
    ui: &mut egui::Ui,
    text: &str,
    palette: &Palette,
    enabled: bool,
) -> egui::Response {
    let button = egui::Button::new(RichText::new(text).color(palette.accent).strong().size(14.0))
        .fill(palette.panel3)
        .corner_radius(CORNER_RADIUS)
        .stroke(Stroke {
            width: 1.5_f32,
            color: palette.accent,
        })
        .min_size(Vec2::new(110.0, 36.0));
    if enabled {
        ui.add(button)
    } else {
        ui.add_enabled(false, button)
    }
}

/// A danger button with red fill and hover darkening.
pub fn danger_button(
    ui: &mut egui::Ui,
    text: &str,
    palette: &Palette,
    enabled: bool,
) -> egui::Response {
    let button = egui::Button::new(RichText::new(text).color(Color32::WHITE).strong().size(14.0))
        .fill(palette.danger)
        .corner_radius(CORNER_RADIUS)
        .min_size(Vec2::new(110.0, 36.0));
    if enabled {
        ui.add(button)
    } else {
        ui.add_enabled(false, button)
    }
}

/// A ghost button (panel3 fill, accent text) — visible on dark panels via fill and border.
pub fn ghost_button(
    ui: &mut egui::Ui,
    text: &str,
    palette: &Palette,
    enabled: bool,
) -> egui::Response {
    let button = egui::Button::new(RichText::new(text).color(palette.accent).strong().size(14.0))
        .fill(palette.panel3)
        .corner_radius(CORNER_RADIUS)
        .stroke(Stroke {
            width: 1.0_f32,
            color: palette.border_focus,
        })
        .min_size(Vec2::new(110.0, 36.0));
    if enabled {
        ui.add(button)
    } else {
        ui.add_enabled(false, button)
    }
}

/// A small button for list-row actions (e.g. "Select"), with minimal width.
pub fn small_button(
    ui: &mut egui::Ui,
    text: &str,
    palette: &Palette,
    enabled: bool,
) -> egui::Response {
    let button = egui::Button::new(RichText::new(text).color(palette.text).strong().size(12.0))
        .fill(palette.panel3)
        .corner_radius(SMALL_RADIUS)
        .stroke(Stroke {
            width: 1.0_f32,
            color: palette.border,
        })
        .min_size(Vec2::new(60.0, 28.0));
    if enabled {
        ui.add(button)
    } else {
        ui.add_enabled(false, button)
    }
}

/// A card container with rounded background and border for separation.
pub fn card(ui: &mut egui::Ui, palette: &Palette, contents: impl FnOnce(&mut egui::Ui)) {
    let rect = ui.min_rect();
    ui.painter()
        .rect_filled(rect.expand(1.0), CORNER_RADIUS, palette.panel2);
    contents(ui);
}

/// A stat card showing a number with a label — fixed width for uniform grid layout.
pub fn stat_card(ui: &mut egui::Ui, palette: &Palette, value: &str, label: &str, color: Color32) {
    card(ui, palette, |ui| {
        ui.set_min_width(150.0);
        ui.add_space(SPACING);
        ui.label(RichText::new(value).color(color).strong().size(24.0));
        ui.add_space(SPACING / 2.0);
        ui.label(RichText::new(label).color(palette.text_secondary).small());
        ui.add_space(SPACING);
    });
}

/// A card container with max-width constraint, centered horizontally.
/// Prevents content from stretching awkwardly on wide screens.
pub fn card_centered(
    ui: &mut egui::Ui,
    palette: &Palette,
    max_width: f32,
    contents: impl FnOnce(&mut egui::Ui),
) {
    let available_width = ui.available_width();
    let card_width = available_width.min(max_width);
    let left_margin = (available_width - card_width) / 2.0;
    ui.add_space(left_margin);
    ui.set_max_width(card_width);
    ui.painter()
        .rect_filled(ui.min_rect().expand(1.0), CORNER_RADIUS, palette.panel2);
    contents(ui);
    ui.add_space(left_margin);
}

/// Wrap content in a horizontally centered container with max-width.
/// Use this at the top of each view to prevent content from stretching
/// awkwardly on maximized / ultra-wide screens.
pub fn constrained_content(
    ui: &mut egui::Ui,
    max_width: f32,
    contents: impl FnOnce(&mut egui::Ui),
) {
    let available_width = ui.available_width();
    let content_width = available_width.min(max_width);
    let left_margin = (available_width - content_width) / 2.0;
    ui.add_space(left_margin);
    ui.set_max_width(content_width);
    contents(ui);
    ui.add_space(left_margin);
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
    ui.label(
        RichText::new(text)
            .color(palette.text_secondary)
            .strong()
            .size(16.0),
    );
    ui.add_space(SPACING);
}

/// Body text.
pub fn body_text(ui: &mut egui::Ui, palette: &Palette, text: &str) {
    ui.label(RichText::new(text).color(palette.text).size(14.0));
    ui.add_space(SPACING);
}

/// A spinning loader indicator for async operations.
pub fn spinner(ui: &mut egui::Ui, size: f32, palette: &Palette) -> egui::Response {
    let rect = ui.available_rect_before_wrap().shrink(4.0);
    let center = rect.center();
    let radius = size / 2.0;
    let time = ui.input(|i| i.time as f32);
    let angle = (time * 4.0) % (2.0 * std::f32::consts::PI);
    ui.painter().circle_stroke(
        center,
        radius,
        egui::Stroke {
            width: 3.0,
            color: palette.accent,
        },
    );
    ui.painter().line_segment(
        [
            center,
            egui::pos2(
                center.x + angle.cos() * radius,
                center.y + angle.sin() * radius,
            ),
        ],
        egui::Stroke {
            width: 3.0,
            color: palette.accent,
        },
    );
    ui.allocate_rect(rect, egui::Sense::hover())
}

/// A loading card shown during async operations (scan, organize, extract).
pub fn loading_card(ui: &mut egui::Ui, palette: &Palette, label: &str) {
    card(ui, palette, |ui| {
        ui.vertical_centered(|ui| {
            spinner(ui, 24.0, palette);
            ui.add_space(SPACING / 2.0);
            ui.label(RichText::new(label).color(palette.text_secondary).small());
        });
    });
}

/// An empty state with icon, title, and description.
pub fn empty_state(ui: &mut egui::Ui, palette: &Palette, icon: &str, title: &str, desc: &str) {
    card(ui, palette, |ui| {
        ui.vertical_centered(|ui| {
            ui.add_space(SPACING_LG);
            ui.label(RichText::new(icon).size(32.0));
            ui.add_space(SPACING / 2.0);
            ui.label(RichText::new(title).color(palette.text).strong().small());
            ui.add_space(SPACING / 4.0);
            ui.label(
                RichText::new(desc)
                    .color(palette.text_secondary)
                    .small()
                    .italics(),
            );
            ui.add_space(SPACING_LG);
        });
    });
}

/// Map a category name to an accent color pill.
pub fn category_pill_color(category: &str, palette: &Palette) -> Color32 {
    match category {
        "Action" | "Adventure" => palette.orange,
        "RPG" | "Role-Playing" => palette.purple,
        "Strategy" => palette.sky,
        "Simulation" => palette.cyan,
        "Shooter" | "FPS" => palette.red,
        "Platformer" => palette.green,
        "Puzzle" => palette.pink,
        "Racing" => palette.violet,
        "Sports" => palette.green_light,
        "Indie" => palette.accent,
        _ => palette.text_secondary,
    }
}

/// A category pill with color-coded background.
pub fn category_pill(ui: &mut egui::Ui, category: &str, palette: &Palette) -> egui::Response {
    let color = category_pill_color(category, palette);
    let label = RichText::new(category).color(palette.bg).small().strong();
    ui.add(
        egui::Button::new(label)
            .fill(color)
            .corner_radius(SMALL_RADIUS)
            .frame(false)
            .min_size(Vec2::new(0.0, 0.0)),
    )
    .on_hover_text(format!("Category: {}", category))
}

/// An archive list row with hover state and selection. Returns the response for click handling.
pub fn archive_row(
    ui: &mut egui::Ui,
    palette: &Palette,
    name: &str,
    size: &str,
    selected: bool,
) -> egui::Response {
    let bg = if selected {
        palette.entry_selected
    } else {
        palette.entry_bg
    };
    let rect = ui.min_rect();
    ui.painter().rect_filled(rect.expand(1.0), SMALL_RADIUS, bg);
    let response = ui.selectable_label(selected, RichText::new(name).color(palette.text));
    if response.hovered() && !selected {
        ui.painter()
            .rect_filled(rect.expand(1.0), SMALL_RADIUS, palette.entry_hover);
    }
    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
        ui.label(RichText::new(size).color(palette.text_secondary).small());
    });
    response
}

/// A navigation sidebar item.
pub fn nav_item(
    ui: &mut egui::Ui,
    palette: &Palette,
    icon: &str,
    label: &str,
    active: bool,
) -> egui::Response {
    let text_color = if active {
        palette.accent
    } else {
        palette.text_secondary
    };
    ui.add_space(SPACING / 2.0);
    let response = ui.selectable_label(
        active,
        RichText::new(format!("{}  {}", icon, label))
            .color(text_color)
            .strong(),
    );
    if response.hovered() && !active {
        ui.painter()
            .rect_filled(response.rect.expand(2.0), SMALL_RADIUS, palette.entry_hover);
    }
    ui.add_space(SPACING / 2.0);
    response
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Buttons must be visibly distinct from card backgrounds.
    /// Card background = panel2; secondary buttons used panel2 fill — invisible inside cards.
    #[test]
    fn test_button_colors_distinct_from_card_background() {
        let palette = Palette::default();

        // Primary button fill must differ from card background
        assert_ne!(
            palette.accent, palette.panel2,
            "primary button fill must differ from card background (panel2)"
        );

        // Secondary button fill (panel3) must differ from card background (panel2)
        assert_ne!(
            palette.panel3, palette.panel2,
            "secondary button fill must differ from card background (panel2)"
        );

        // Danger button fill must differ from card background
        assert_ne!(
            palette.danger, palette.panel2,
            "danger button fill must differ from card background (panel2)"
        );

        // Button text must contrast with button fill
        assert_ne!(
            Color32::WHITE, palette.accent,
            "primary button text must contrast with accent fill"
        );
        assert_ne!(
            Color32::WHITE, palette.danger,
            "danger button text must contrast with danger fill"
        );
    }

    /// Secondary buttons must not use panel2 fill (matches card background, invisible).
    #[test]
    fn test_secondary_button_not_invisible_in_card() {
        let palette = Palette::default();
        // Regression: secondary_button used panel2 fill == card background panel2 → invisible
        assert_ne!(
            palette.panel3, palette.panel2,
            "secondary button panel3 fill must differ from card panel2 background"
        );
    }
}
