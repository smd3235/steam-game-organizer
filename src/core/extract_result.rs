//! `ExtractResult` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-25: Converted from `services/extract_result.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use serde::{Deserialize, Serialize};
use std::path::PathBuf;

/// Result of extracting one archive to a destination.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExtractResult {
    pub archive: PathBuf,
    pub destination: PathBuf,
    pub ok: bool,
    pub message: String,
    pub extracted_bytes: u64,
    pub file_count: u32,
    pub code: i32,
    /// True when the extracted contents were recognised as an installer layout and relocated into a
    /// "Needs Install" folder. Carried separately so the batch view can flag the row without parsing the message.
    pub needs_install: bool,
}

impl ExtractResult {
    pub fn summary(&self) -> &str {
        &self.message
    }
}

impl Default for ExtractResult {
    fn default() -> Self {
        ExtractResult {
            archive: PathBuf::new(),
            destination: PathBuf::new(),
            ok: false,
            message: String::new(),
            extracted_bytes: 0,
            file_count: 0,
            code: 0,
            needs_install: false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_result_default() {
        let result = ExtractResult::default();
        assert!(!result.ok);
        assert_eq!(result.message, "");
        assert_eq!(result.extracted_bytes, 0);
        assert_eq!(result.file_count, 0);
        assert_eq!(result.code, 0);
        assert!(!result.needs_install);
    }

    #[test]
    fn test_extract_result_summary() {
        let result = ExtractResult {
            message: "Extracted 5 files".to_string(),
            ..Default::default()
        };
        assert_eq!(result.summary(), "Extracted 5 files");
    }
}
