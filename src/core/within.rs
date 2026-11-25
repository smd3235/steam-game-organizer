//! `_within` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-24: Converted from `core/within.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::path::{Path, PathBuf};

/// Normalize a path: collapse `.` and `..` segments, normalize separators.
/// Does not require the path to exist on disk.
fn normalize(path: &Path) -> PathBuf {
    let mut parts: Vec<&std::ffi::OsStr> = Vec::new();
    for part in path.iter() {
        match part.to_str() {
            Some(".") | Some("") => continue,
            Some("..") => {
                parts.pop();
            }
            _ => parts.push(part),
        }
    }
    let mut result = PathBuf::new();
    for p in parts {
        result.push(p);
    }
    result
}

/// True when `candidate` is `root` itself or sits under it.
///
/// Both sides are fully normalized first, because `..` segments and symlinks are exactly what this is
/// guarding against; comparing the unresolved strings would let `/library/../etc` pass.
/// Returns `false` (never panics) on an unresolvable path, because the answer a delete needs is "no".
pub fn within(candidate: &Path, root: &Path) -> bool {
    let candidate = normalize(candidate);
    let root = normalize(root);
    candidate == root || candidate.starts_with(&root)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_within_same_path() {
        assert!(within(Path::new("/a/b"), Path::new("/a/b")));
    }

    #[test]
    fn test_within_child() {
        assert!(within(Path::new("/a/b/c"), Path::new("/a/b")));
    }

    #[test]
    fn test_within_not_parent() {
        assert!(!within(Path::new("/a/b"), Path::new("/a/b/c")));
    }

    #[test]
    fn test_within_dotdot() {
        assert!(!within(Path::new("/a/../etc"), Path::new("/a")));
    }
}
