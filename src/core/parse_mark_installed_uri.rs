//! `parse_mark_installed_uri` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-24: Converted from `core/parse_mark_installed_uri.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::path::PathBuf;

use crate::core::parse_extract_root_action::parse_extract_root_action;
use crate::core::uri_actions::UriRefused;

/// Returns the extracted marker/root directory for a mark-installed action.
pub fn parse_mark_installed_uri(
    uri: &str,
    extract_folders: Option<Vec<&str>>,
) -> Result<PathBuf, UriRefused> {
    parse_extract_root_action(uri, extract_folders, "mark-installed", true)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_mark_installed_uri_bad_action() {
        let result = parse_mark_installed_uri("steamgameorganizer://pick-launcher/xyz", None);
        assert!(result.is_err());
    }
}
