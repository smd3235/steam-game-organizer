//! `canonical_category` was moved here during a module split so `constants.rs`
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-24: Converted from `core/canonical_category.py` to Rust in the Rust
//! conversion (one file at a time, tracked on the `Rust-Conversion` branch).

use crate::core::constants::CATEGORY_ALIASES;

/// Map an arbitrary category string to its canonical form.
///
/// `text` is normalized by collapsing whitespace and trimming, then looked up
/// casefolded in `CATEGORY_ALIASES`. If no alias matches, the normalized text
/// is returned as-is.
pub fn canonical_category(value: &str) -> String {
    let text = value
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .trim()
        .to_string();
    CATEGORY_ALIASES
        .iter()
        .find(|(alias, _)| alias.eq_ignore_ascii_case(&text))
        .map(|(_, canonical)| canonical.to_string())
        .unwrap_or(text)
}

