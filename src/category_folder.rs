//! `_category_folder` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-24: Converted from `core/category_folder.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::path::{Path, PathBuf};

use crate::constants::LIBRARY_RESERVED_DIRS;
use crate::uri_actions::UriRefused;
use crate::within::within;

/// The category directory named by a batch link, or refuse.
///
/// The name arrives from a web page, so it is treated as a path fragment rather than a label: it has to be a
/// single component with no separators, it may not walk upwards, and the folder it names has to actually be a
/// directory inside the library. Checking the resolved folder rather than the string is what makes the last two
/// rules hold for `..`, for a symlink, and for a drive letter.
pub fn category_folder(
    raw_category: Option<&str>,
    library_root: &Path,
) -> Result<PathBuf, UriRefused> {
    let name = raw_category.unwrap_or("").trim();
    if name.is_empty() {
        return Err(UriRefused::new(
            "The link did not say which category to extract.",
        ));
    }
    // A separator, a drive, or a walk upwards all mean the name was never a category.
    if name == "."
        || name == ".."
        || name.contains('/')
        || name.contains('\\')
        || name.contains(':')
    {
        return Err(UriRefused::new(&format!(
            "That is not a category name: {}",
            name
        )));
    }
    if name.starts_with('.') {
        return Err(UriRefused::new(&format!(
            "Refused: {} is a hidden folder, not a category.",
            name
        )));
    }
    if LIBRARY_RESERVED_DIRS.contains(&name) {
        return Err(UriRefused::new(&format!(
            "Refused: {} is a folder the app keeps for itself, not a category.",
            name
        )));
    }
    let folder = library_root.join(name);
    if !within(&folder, library_root) {
        return Err(UriRefused::new(&format!(
            "Refused: {} is outside the game library.",
            name
        )));
    }
    if !folder.is_dir() {
        return Err(UriRefused::new(&format!(
            "There is no category called {} in this library.",
            name
        )));
    }
    Ok(folder)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_category_folder_empty_refused() {
        let result = category_folder(None, &PathBuf::from("C:\\Library"));
        assert!(result.is_err());
    }

    #[test]
    fn test_category_folder_separator_refused() {
        let result = category_folder(Some("../evil"), &PathBuf::from("C:\\Library"));
        assert!(result.is_err());
    }

    #[test]
    fn test_category_folder_hidden_refused() {
        let result = category_folder(Some(".hidden"), &PathBuf::from("C:\\Library"));
        assert!(result.is_err());
    }
}
