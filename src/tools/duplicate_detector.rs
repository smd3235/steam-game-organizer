//! Duplicate detector tool: finds duplicate archives across library folders.
//! Compares archives by normalized name (strips release groups, edition words,
//! subtitles) and file size to catch the same game downloaded twice under
//! different filenames.
//!
//! Usage:
//!   steam-game-organizer.exe --duplicate-detector <library_dir>
//!
//! 2026-11-27: New creative tool — catches duplicate game archives that waste
//! disk space and confuse the scan/match pipeline.

use std::path::Path;

/// A detected duplicate group: same game, multiple files.
pub struct DuplicateGroup {
    pub normalized_name: String,
    pub files: Vec<std::path::PathBuf>,
    pub total_size_bytes: u64,
}

/// Scan a directory tree for duplicate archives.
/// Groups archives by normalized name + size; returns groups with >1 file.
pub fn find_duplicates(_library_dir: &Path) -> Result<Vec<DuplicateGroup>, String> {
    // Stub: real implementation walks the tree, normalizes each archive name,
    // and groups by (normalized_name, file_size).
    Err("duplicate detector not yet implemented".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_find_duplicates_stub() {
        let result = find_duplicates(Path::new("."));
        assert!(result.is_err());
    }

    #[test]
    fn test_duplicate_group_struct() {
        let group = DuplicateGroup {
            normalized_name: "resident evil 4".to_string(),
            files: vec![
                std::path::PathBuf::from("C:/Games/resident.evil.4.tenoke.zip"),
                std::path::PathBuf::from("C:/Games/RE4.fitgirl.repack.rar"),
            ],
            total_size_bytes: 45_000_000_000,
        };
        assert_eq!(group.files.len(), 2);
        assert_eq!(group.normalized_name, "resident evil 4");
        assert!(group.total_size_bytes > 0);
    }
}
