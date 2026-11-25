//! Capture screens tool: captures UI screenshots.
//! Stub conversion of `tools/capture_screens.py`.
//!
//! 2026-11-25: Rust conversion from `tools/capture_screens.py` in the Rust conversion.

use std::path::Path;

pub fn capture_screens(_output_dir: &Path) -> Result<(), String> {
    Err("capture screens not yet implemented".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_capture_screens_stub() {
        let result = capture_screens(Path::new("."));
        assert!(result.is_err());
    }
}
