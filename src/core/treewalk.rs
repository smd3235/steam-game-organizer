//! Filesystem walking helpers that are junction-aware.
//!
//! Path.rglob('*') follows a Windows junction or a Linux bind mount, because the operating system resolves one
//! as an ordinary directory and scandir is handed nothing that says otherwise. A junction inside a library
//! that pointed back at the library made a library holding one game scan as 64 archives - one per level that
//! still fitted inside MAX_PATH - and Organize then treated all 64 as copies of one another.
//!
//! Directories are compared by resolved path and one already visited is not descended into again, which closes
//! the cycle wherever it is.
//!
//! 2026-11-24: Converted from `utils/treewalk.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::fs;
use std::os::windows::fs::MetadataExt;
use std::path::{Path, PathBuf};

/// True for anything the operating system resolves to somewhere else: a symlink, or a Windows junction,
/// directory reparse point, or symlink. `Path::is_symlink()` is not enough on its own - it reports false for a
/// junction, because a junction is a reparse point the OS hands back as an ordinary directory.
pub fn is_link(path: &Path) -> bool {
    if path.is_symlink() {
        return true;
    }
    // On Windows, check the reparse point attribute.
    if let Ok(metadata) = fs::symlink_metadata(path) {
        let attrs = metadata.file_attributes();
        if attrs & 0x400 != 0 {
            // FILE_ATTRIBUTE_REPARSE_POINT
            return true;
        }
    }
    false
}

/// Every file under root, without descending twice into the same directory.
///
/// Directories are compared by resolved path and one already visited is not descended into again, which closes
/// the cycle wherever it is.
pub fn walk_files(root: &Path) -> Vec<PathBuf> {
    if !root.is_dir() {
        return Vec::new();
    }
    let mut result: Vec<PathBuf> = Vec::new();
    let mut seen: Vec<PathBuf> = Vec::new();
    let mut stack: Vec<PathBuf> = vec![root.to_path_buf()];

    while let Some(current) = stack.pop() {
        let resolved = match current.canonicalize() {
            Ok(p) => p,
            Err(_) => continue,
        };
        if seen.iter().any(|s| s == &resolved) {
            continue;
        }
        seen.push(resolved.clone());

        let entries = match fs::read_dir(&current) {
            Ok(e) => e,
            Err(_) => continue,
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                stack.push(path);
            } else {
                result.push(path);
            }
        }
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_walk_files_empty() {
        let nonexistent = std::env::temp_dir().join(format!("nonexistent_{}", std::process::id()));
        let result = walk_files(&nonexistent);
        assert!(result.is_empty());
    }

    #[test]
    fn test_is_link_false() {
        assert!(!is_link(Path::new("/nonexistent")));
    }
}
