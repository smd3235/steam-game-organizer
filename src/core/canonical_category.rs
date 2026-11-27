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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_canonical_category_exact_match() {
        assert_eq!(canonical_category("Automation"), "Automation");
    }

    #[test]
    fn test_canonical_category_case_insensitive() {
        assert_eq!(canonical_category("automation"), "Automation");
        assert_eq!(canonical_category("AUTOMATION"), "Automation");
        assert_eq!(canonical_category("AutOmAtIoN"), "Automation");
    }

    #[test]
    fn test_canonical_category_alias_match() {
        assert_eq!(canonical_category("factory"), "Automation");
        assert_eq!(canonical_category("factory sim"), "Automation");
        assert_eq!(canonical_category("city builder"), "City Builder");
        assert_eq!(canonical_category("rogue"), "Roguelike");
    }

    #[test]
    fn test_canonical_category_unknown_passthrough() {
        assert_eq!(canonical_category("Some Unknown Category"), "Some Unknown Category");
        assert_eq!(canonical_category(""), "");
    }

    #[test]
    fn test_canonical_category_whitespace_collapsed() {
        assert_eq!(canonical_category("  automation  "), "Automation");
        assert_eq!(canonical_category("  city   builder  "), "City Builder");
    }
}
