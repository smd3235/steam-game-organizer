//! `parse_pick_launcher_uri` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-24: Converted from `core/parse_pick_launcher_uri.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::path::PathBuf;

use crate::parse_extract_root_action::parse_extract_root_action;
use crate::uri_actions::UriRefused;

/// Returns the extracted marker/root directory for a pick-launcher action.
pub fn parse_pick_launcher_uri(
    uri: &str,
    extract_folders: Option<Vec<&str>>,
) -> Result<PathBuf, UriRefused> {
    parse_extract_root_action(uri, extract_folders, "pick-launcher", true)
}
