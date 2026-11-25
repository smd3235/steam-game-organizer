//! Review backups tool: browse, search, diff, and verify backups.
//! Stub conversion of `tools/review_backups.py`.
//!
//! 2026-11-25: Rust conversion from `tools/review_backups.py` in the Rust conversion.

use std::path::Path;

pub fn review_backups(_backup_dir: &Path) -> Result<(), String> {
    Err("review backups not yet implemented".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_review_backups_stub() {
        let result = review_backups(Path::new("."));
        assert!(result.is_err());
    }
}
