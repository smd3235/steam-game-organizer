//! Build icon tool: prepares the app icon asset.
//! Stub conversion of `tools/build_icon.py`.
//!
//! 2026-11-25: Rust conversion from `tools/build_icon.py` in the Rust conversion.

use std::path::Path;

/// Build/verify the icon asset.
pub fn build_icon(_icon_path: &Path) -> Result<(), String> {
    // Stub: icon building not yet implemented in Rust.
    Err("icon build not yet implemented".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_build_icon_stub() {
        let result = build_icon(Path::new("assets/icon.ico"));
        assert!(result.is_err());
    }
}
