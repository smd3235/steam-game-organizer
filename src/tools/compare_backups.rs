//! Compare backups tool: compares two backup archives.
//! Stub conversion of `tools/compare_backups.py`.
//!
//! 2026-11-25: Rust conversion from `tools/compare_backups.py` in the Rust conversion.

use std::path::Path;

/// Compare two backups.
pub fn compare_backups(_backup1: &Path, _backup2: &Path) -> Result<(), String> {
    // Stub: backup compare not yet implemented in Rust.
    Err("backup compare not yet implemented".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_compare_backups_stub() {
        let result = compare_backups(Path::new("."), Path::new("."));
        assert!(result.is_err());
    }
}
