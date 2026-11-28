//! `_within` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-24: Converted from `core/within.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).
//!
//! 2026-11-28: Symlink hardening — when a path exists on disk, `within()`
//! now canonicalizes both sides via `canonicalize()` which resolves symlinks.
//! A string-only `..` check can be bypassed with a symlink:
//!   library/evil_link -> C:\Windows
//!   library/evil_link/../system32/kernel32.dll
//! normalizes to `library/system32/kernel32.dll` (passes the string check)
//! but actually resolves to `C:\Windows\system32\kernel32.dll`. Canonicalizing
//! resolves the symlink first so the containment check uses real paths.
//! Non-existent paths fall back to string-based normalization.

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

/// Resolve a path to its canonical form if it exists on disk, falling back
/// to string-based normalization if it doesn't. Canonicalization resolves
/// symlinks so containment checks can't be bypassed via symlink junctions.
fn resolve_if_exists(path: &Path) -> PathBuf {
    match path.canonicalize() {
        Ok(p) => p,
        Err(_) => normalize(path),
    }
}

/// True when `candidate` is `root` itself or sits under it.
///
/// When both paths exist on disk, they are canonicalized first so symlinks
/// are resolved before the containment check. Non-existent paths fall back
/// to string-based normalization. Returns `false` on an unresolvable path.
pub fn within(candidate: &Path, root: &Path) -> bool {
    let candidate = resolve_if_exists(candidate);
    let root = resolve_if_exists(root);
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
