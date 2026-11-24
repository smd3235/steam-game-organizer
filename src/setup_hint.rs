//! `_setup_hint` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-24: Converted from `core/setup_hint.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

/// The pointer every fresh-PC refusal carries.
///
/// The three folders the Extract links are checked against are set by the
/// setup wizard, and the page that fired the link carries the button that
/// opens it - so a refusal on a PC that has not been set up yet names the
/// fix rather than only the rule.
pub fn setup_hint() -> String {
    " The Set up on this PC button at the top of the catalog points this app at the library."
        .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_setup_hint_mentions_setup_button() {
        let hint = setup_hint();
        assert!(hint.contains("Set up on this PC"));
        assert!(hint.contains("catalog"));
    }
}
