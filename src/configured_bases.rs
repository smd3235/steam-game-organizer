//! `_configured_bases` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-24: Converted from `core/configured_bases.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::path::{Path, PathBuf};

fn expanduser(path: &str) -> PathBuf {
    let p = Path::new(path);
    if let Ok(rest) = p.strip_prefix("~") {
        if let Ok(home) = std::env::var("USERPROFILE") {
            return PathBuf::from(home).join(rest);
        }
    }
    p.to_path_buf()
}

/// The folders the user has already chosen, as a list. None means nowhere is approved.
pub fn configured_bases(extract_base: Option<Vec<&str>>) -> Vec<PathBuf> {
    let entries: Vec<&str> = match extract_base {
        Some(v) => v,
        None => return Vec::new(),
    };
    entries.iter().map(|p| expanduser(p)).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_configured_bases_none() {
        assert!(configured_bases(None).is_empty());
    }

    #[test]
    fn test_configured_bases_single() {
        let bases = configured_bases(Some(vec!["C:\\Games"]));
        assert_eq!(bases.len(), 1);
    }

    #[test]
    fn test_configured_bases_multiple() {
        let bases = configured_bases(Some(vec!["C:\\Games", "D:\\Games"]));
        assert_eq!(bases.len(), 2);
    }
}
