//! `_typed_destination` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! Validates a destination the user typed into the catalog page.
//!
//! The page offers a free-text box, so this cannot be the 'must be inside a pre-approved folder' check the
//! configured list uses. What still holds: the path has to be absolute (a relative one would land wherever the
//! handler happens to be started from), it may not sit inside a system folder or be the home folder itself, and
//! it may not sit inside the game library, where unpacking would be picked up as new game folders on the next
//! scan. Refusing a few known-bad targets is weaker than a fixed allow-list and is honest about being so.
//!
//! 2026-11-24: Converted from `core/typed_destination.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::path::{Path, PathBuf};

use crate::core::uri_actions::UriRefused;
use crate::core::within::within;

fn expanduser(path: &str) -> PathBuf {
    let p = Path::new(path);
    if let Ok(rest) = p.strip_prefix("~") {
        if let Ok(home) = std::env::var("USERPROFILE") {
            return PathBuf::from(home).join(rest);
        }
    }
    p.to_path_buf()
}

/// Validates a destination the user typed into the catalog page.
///
/// Returns the resolved absolute path, or a `UriRefused` error with a user-facing message.
pub fn typed_destination(raw: &str, library_root: &Path) -> Result<PathBuf, UriRefused> {
    let expanded = expanduser(raw);
    if !expanded.is_absolute() {
        return Err(UriRefused::new(&format!(
            "That is not a full path, so it would unpack somewhere unknown: {}",
            raw
        )));
    }
    let expanded = match expanded.canonicalize() {
        Ok(p) => p,
        Err(exc) => {
            return Err(UriRefused::new(&format!(
                "Cannot use that destination: {}",
                exc
            )));
        }
    };
    if expanded.parent() == Some(&expanded) {
        return Err(UriRefused::new(&format!(
            "Refused: {} is the filesystem root.",
            expanded.display()
        )));
    }
    let home = std::env::var("USERPROFILE")
        .ok()
        .map(PathBuf::from)
        .and_then(|p| p.canonicalize().ok());
    if let Some(home) = &home {
        if expanded == *home {
            return Err(UriRefused::new(&format!(
                "Refused: {} is your home folder. Pick a folder inside it.",
                expanded.display()
            )));
        }
    }
    // Every folder on the way up is checked, not just the destination itself, so C:\Windows\System32\games is
    // refused as readily as the destination that contains it. That is also what catches a junction, which
    // resolve() rewrites to its target and an exact-match list would then wave through.
    let mut current: Option<&Path> = Some(&expanded);
    while let Some(parent) = current {
        let parent_str = parent.to_string_lossy().to_lowercase();
        let sys = crate::core::system_paths::system_paths();
        if sys.iter().any(|s| parent_str == s.to_lowercase()) {
            return Err(UriRefused::new(&format!(
                "Refused: {} is inside a system folder.",
                expanded.display()
            )));
        }
        current = parent.parent();
    }
    if within(&expanded, library_root) {
        return Err(UriRefused::new(&format!(
            "Refused: {} is inside the game library. Choose somewhere outside it.",
            expanded.display()
        )));
    }
    if expanded.exists() {
        if !expanded.is_dir() {
            return Err(UriRefused::new(&format!(
                "That destination is a file, not a folder: {}",
                expanded.display()
            )));
        }
    } else {
        // Allow a folder that is not created yet, but only if the closest folder that does exist can be written.
        let mut ancestor = expanded.parent();
        while let Some(a) = ancestor {
            if !a.exists() {
                ancestor = a.parent();
                continue;
            }
            if !a.is_dir() || !metadata_writable(a) {
                return Err(UriRefused::new(&format!(
                    "Cannot create a folder there: {} is not writable.",
                    a.display()
                )));
            }
            break;
        }
    }
    Ok(expanded)
}

fn metadata_writable(path: &Path) -> bool {
    match path.metadata() {
        Ok(m) => !m.permissions().readonly(),
        Err(_) => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_typed_destination_relative_refused() {
        let result = typed_destination("relative/path", Path::new("C:\\Games"));
        assert!(result.is_err());
    }

    #[test]
    fn test_typed_destination_home_refused() {
        let home = std::env::var("USERPROFILE").unwrap_or_default();
        let result = typed_destination(&home, Path::new("C:\\Games"));
        assert!(result.is_err());
    }
}
