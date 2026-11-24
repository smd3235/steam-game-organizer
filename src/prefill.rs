//! `_prefill` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-24: Converted from `core/prefill.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

/// One query value, cleaned for a text box: control characters dropped, length capped.
///
/// A path box holds a path, and a path is neither a megabyte long nor full of newlines;
/// the cap is what keeps a hostile link from stuffing something enormous into the
/// wizard's fields.
pub fn prefill(values: Option<&str>) -> String {
    let text = values.unwrap_or("");
    let text: String = text.chars().filter(|c| *c >= ' ').collect();
    text.trim().chars().take(1000).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_prefill_none() {
        assert_eq!(prefill(None), "");
    }

    #[test]
    fn test_prefill_empty() {
        assert_eq!(prefill(Some("")), "");
    }

    #[test]
    fn test_prefill_control_chars_stripped() {
        assert_eq!(prefill(Some("hello\x00world")), "helloworld");
    }

    #[test]
    fn test_prefill_capped() {
        let long = "a".repeat(2000);
        assert_eq!(prefill(Some(&long)).len(), 1000);
    }

    #[test]
    fn test_prefill_trimmed() {
        assert_eq!(prefill(Some("  hello  ")), "hello");
    }
}
