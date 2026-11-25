//! Create desktop/start menu shortcut tool.
//! Stub conversion of `tools/create_shortcut.py`.
//!
//! 2026-11-25: Rust conversion from `tools/create_shortcut.py` in the Rust conversion.

use std::path::{Path, PathBuf};

pub fn create_shortcut(_name: &str, _location: Option<&Path>) -> Result<PathBuf, String> {
    Err("create shortcut not yet implemented".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_create_shortcut_stub() {
        let result = create_shortcut("Test.lnk", None);
        assert!(result.is_err());
    }
}
