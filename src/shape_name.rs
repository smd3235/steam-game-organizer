//! `shape_name` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-25: Converted from `services/shape_name.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

/// Returns "portrait" when `shape` is truthy, "wide" when `shape` is `false`, "unknown" otherwise.
pub fn shape_name(shape: Option<bool>) -> &'static str {
    match shape {
        Some(true) => "portrait",
        Some(false) => "wide",
        None => "unknown",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_shape_name_some_true() {
        assert_eq!(shape_name(Some(true)), "portrait");
    }

    #[test]
    fn test_shape_name_some_false() {
        assert_eq!(shape_name(Some(false)), "wide");
    }

    #[test]
    fn test_shape_name_none() {
        assert_eq!(shape_name(None), "unknown");
    }
}
