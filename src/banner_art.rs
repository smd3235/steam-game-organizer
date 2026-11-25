//! Generated category banner art for the offline HTML catalog.
//!
//! The catalog is built to make no external requests, so banners are drawn here as inline SVG data URIs rather
//! than downloaded. That also means there is no licence to track and no attribution file to keep correct: the art
//! is produced from the category name, so it is stable across regenerations and identical on every machine.
//!
//! Real game artwork still wins where it exists. This is the layer underneath, which guarantees every category has
//! a distinct banner even when no game in it has ever had art fetched.
//!
//! 2026-11-25: Converted from `services/banner_art.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::hash::{Hash, Hasher};

pub const WIDTH: u32 = 1200;
pub const HEIGHT: u32 = 300;

/// Hue anchors. Each banner picks two by hash so adjacent categories never land on the same gradient.
const HUES: [u32; 24] = [
    212, 268, 322, 18, 42, 96, 140, 186, 246, 292, 340, 66, 200, 232, 254, 280, 305, 350, 8, 30,
    58, 78, 118, 158,
];

/// Stable per category. Uses the name only, so renaming a category changes its art deliberately.
fn seed(name: &str) -> u64 {
    use std::collections::hash_map::DefaultHasher;
use std::hash::Hasher;
    let mut hasher = DefaultHasher::new();
    name.trim().to_lowercase().hash(&mut hasher);
    hasher.finish()
}

/// HSL to hex conversion.
fn hsl_to_hex(hue: f64, saturation: f64, lightness: f64) -> String {
    let hue = hue % 360.0;
    let chroma = (1.0 - (2.0 * lightness - 1.0).abs()) * saturation;
    let secondary = chroma * (1.0 - ((hue / 60.0) % 2.0 - 1.0).abs());
    let steam_match = (hue / 60.0) as i32 % 6;
    let table = [
        (chroma, secondary, 0.0),
        (secondary, chroma, 0.0),
        (0.0, chroma, secondary),
        (0.0, secondary, chroma),
        (secondary, 0.0, chroma),
        (chroma, 0.0, secondary),
    ];
    let (red, green, blue) = table[steam_match as usize];
    let offset = lightness - chroma / 2.0;
    format!(
        "#{:02x}{:02x}{:02x}",
        ((red + offset).clamp(0.0, 1.0) * 255.0) as u32,
        ((green + offset).clamp(0.0, 1.0) * 255.0) as u32,
        ((blue + offset).clamp(0.0, 1.0) * 255.0) as u32
    )
}

/// One of several geometric treatments, chosen by hash, all drawn behind the category name.
fn motif(seed: u64, accent: &str) -> String {
    let kind = seed % 5;
    let mut parts = Vec::new();
    match kind {
        0 => {
            // concentric rings
            for step in 0..7 {
                let radius = 34 + step * 46;
                parts.push(format!(
                    r#"<circle cx="{}" cy="40" r="{}" fill="none" stroke="{}" stroke-opacity="{:.2}" stroke-width="{}"/>"#,
                    940 - step * 8,
                    radius,
                    accent,
                    0.46 - step as f64 * 0.045,
                    if step % 2 == 0 { 6 } else { 2 }
                ));
            }
        }
        1 => {
            // diagonal ribbons
            for step in 0..16 {
                let offset = step * 84 - 260;
                parts.push(format!(
                    r#"<path d="M{} {} L{} 0" stroke="{}" stroke-opacity="{:.2}" stroke-width="{}"/>"#,
                    offset,
                    HEIGHT,
                    offset + 300,
                    accent,
                    0.09 + 0.08 * (step % 3) as f64,
                    6 + (step % 4) * 9
                ));
            }
        }
        2 => {
            // dot field, denser toward the right
            for row in 0..7 {
                for column in 0..20 {
                    let radius = 1.5 + ((row * 20 + column + seed) % 4) as f64;
                    parts.push(format!(
                        r#"<circle cx="{}" cy="{}" r="{}" fill="{}" fill-opacity="0.50"/>"#,
                        34 + column * 58,
                        24 + row * 40,
                        radius,
                        accent
                    ));
                }
            }
        }
        3 => {
            // mountain peaks
            for step in 0..5 {
                let base = HEIGHT as f64 - 18.0 - step as f64 * 26.0;
                let span = 300.0 + step as f64 * 90.0;
                parts.push(format!(
                    r#"<path d="M{} {} L{} {} L{} {} Z" fill="{}" fill-opacity="{:.2}"/>"#,
                    -40 + step * 150,
                    HEIGHT,
                    span / 2.0 + step as f64 * 150.0,
                    base,
                    span + step as f64 * 150.0,
                    HEIGHT,
                    accent,
                    0.26 - step as f64 * 0.038
                ));
            }
        }
        _ => {
            // isometric grid
            for step in 0..26 {
                let offset = step * 54;
                parts.push(format!(
                    r#"<path d="M{} {} L{} 0" stroke="{}" stroke-opacity="0.15" stroke-width="2"/>"#,
                    offset,
                    HEIGHT,
                    WIDTH as f64 * 0.35 + offset as f64,
                    accent
                ));
                parts.push(format!(
                    r#"<path d="M{} {} L{} 0" stroke="{}" stroke-opacity="0.15" stroke-width="2"/>"#,
                    WIDTH - offset,
                    HEIGHT,
                    WIDTH as f64 * 0.65 - offset as f64,
                    accent
                ));
            }
        }
    }
    parts.join("")
}

/// A wide, colourful banner. Bright enough that two categories do not read as the same dark smear: the
/// sheet's own scrim darkens the lower band the category name sits on, so the art underneath is free to be
/// light. The previous values were tuned for a title drawn directly on the art, and left every banner close
/// to black once the scrim was applied on top.
pub fn banner_svg(name: &str) -> String {
    let seed = seed(name);
    let base = HUES[seed as usize % HUES.len()];
    let partner_index = (seed as usize / HUES.len()) % HUES.len();
    let mut partner = HUES[partner_index];
    if partner == base {
        partner = HUES[(seed as usize / HUES.len() + 7) % HUES.len()];
    }
    let accent = hsl_to_hex(partner as f64, 0.66, 0.68);
    let top = hsl_to_hex(base as f64, 0.55, 0.44);
    let bottom = hsl_to_hex((base + 26) as f64 % 360.0, 0.64, 0.21);
    // Gradient angle and glow position vary too, so even an identical hue pair still yields different art.
    let angle = 15 + ((seed >> 7) % 75);
    let gx = 52 + ((seed >> 11) % 42);
    let mut svg = String::new();
    svg.push_str("<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 ");
    svg.push_str(&WIDTH.to_string());
    svg.push_str(" ");
    svg.push_str(&HEIGHT.to_string());
    svg.push_str("\" width=\"");
    svg.push_str(&WIDTH.to_string());
    svg.push_str("\" height=\"");
    svg.push_str(&HEIGHT.to_string());
    svg.push_str("\">");
    svg.push_str("<defs><linearGradient id=\"bg\" x1=\"0\" y1=\"0\" x2=\"0.4\" y2=\"1\" gradientTransform=\"rotate(");
    svg.push_str(&angle.to_string());
    svg.push_str(" 0.5 0.5)\">");
    svg.push_str("<stop offset=\"0\" stop-color=\"");
    svg.push_str(&top);
    svg.push_str("\"/><stop offset=\"1\" stop-color=\"");
    svg.push_str(&bottom);
    svg.push_str("\"/></linearGradient>");
    svg.push_str("<radialGradient id=\"glow\" cx=\"");
    svg.push_str(&format!("{:.2}", gx as f64 / 100.0));
    svg.push_str("\" cy=\"0.18\" r=\"0.7\">");
    svg.push_str("<stop offset=\"0\" stop-color=\"");
    svg.push_str(&accent);
    svg.push_str("\" stop-opacity=\"0.46\"/><stop offset=\"1\" stop-color=\"");
    svg.push_str(&accent);
    svg.push_str("\" stop-opacity=\"0\"/></radialGradient></defs>");
    svg.push_str("<rect width=\"");
    svg.push_str(&WIDTH.to_string());
    svg.push_str("\" height=\"");
    svg.push_str(&HEIGHT.to_string());
    svg.push_str("\" fill=\"url(#bg)\"/>");
    svg.push_str(&motif(seed, &accent));
    svg.push_str("<rect width=\"");
    svg.push_str(&WIDTH.to_string());
    svg.push_str("\" height=\"");
    svg.push_str(&HEIGHT.to_string());
    svg.push_str("\" fill=\"url(#glow)\"/>");
    svg.push_str("</svg>");
    svg
}

/// Percent-encoded so the '#' in hex colours and the quotes cannot break out of the CSS url() it sits in.
pub fn banner_data_uri(name: &str) -> String {
    let svg = banner_svg(name);
    let encoded: String = svg
        .chars()
        .flat_map(|c| {
            if c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.' | '~') {
                vec![c]
            } else {
                let mut buf = [0u8; 4];
                let encoded_bytes = c.encode_utf8(&mut buf);
                const HEX_CHARS: [u8; 16] = *b"0123456789ABCDEF";
                encoded_bytes
                    .bytes()
                    .flat_map(|b| {
                        let hi = HEX_CHARS[(b >> 4) as usize] as char;
                        let lo = HEX_CHARS[(b & 0x0f) as usize] as char;
                        std::iter::once('%')
                            .chain(std::iter::once(hi))
                            .chain(std::iter::once(lo))
                    })
                    .collect()
            }
        })
        .collect();
    format!("data:image/svg+xml,{}", encoded)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_banner_svg_non_empty() {
        let svg = banner_svg("Action");
        assert!(!svg.is_empty());
        assert!(svg.contains("<svg"));
    }

    #[test]
    fn test_banner_svg_different_names() {
        let svg1 = banner_svg("Action");
        let svg2 = banner_svg("Adventure");
        assert_ne!(svg1, svg2);
    }

    #[test]
    fn test_banner_data_uri() {
        let uri = banner_data_uri("Action");
        assert!(uri.starts_with("data:image/svg+xml,"));
    }

    #[test]
    fn test_seed_stable() {
        assert_eq!(seed("Action"), seed("Action"));
        assert_ne!(seed("Action"), seed("Adventure"));
    }
}
