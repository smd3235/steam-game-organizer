//! OCR test tool: OCR testing for UI screenshots.
//! Stub conversion of `tools/ocr_test.py`.
//!
//! 2026-11-25: Rust conversion from `tools/ocr_test.py` in the Rust conversion.

use std::path::Path;

pub fn ocr_test(_output_dir: &Path) -> Result<(), String> {
    Err("OCR test not yet implemented".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_ocr_test_stub() {
        let result = ocr_test(Path::new("."));
        assert!(result.is_err());
    }
}
