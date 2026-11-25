//! `parse_uri` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-24: Converted from `core/parse_uri.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::path::{Path, PathBuf};

use crate::configured_bases::configured_bases;
use crate::constants::ARCHIVE_EXTENSIONS;
use crate::destination_parent::destination_parent;
use crate::safe_folder_name::safe_folder_name;
use crate::setup_hint::setup_hint;
use crate::uri_actions::{ExtractRequest, UriRefused, SCHEME};
use crate::within::within;

/// Returns an `ExtractRequest`, or raises `UriRefused` with a message for the user.
///
/// `extract_base` may be one destination or an iterable of them, matching `AppConfig.extract_folders`.
/// A page offers that same list, and every entry in it has already been chosen by the user, so each is
/// trusted equally - but nothing outside the list is.
pub fn parse_uri(
    uri: &str,
    library_root: &Path,
    extract_base: Option<Vec<&str>>,
) -> Result<ExtractRequest, UriRefused> {
    let bases = configured_bases(extract_base);
    if uri.is_empty() {
        return Err(UriRefused::new("No action was given."));
    }
    // Manual URI parsing: steamgameorganizer://extract?src=path&dest=path
    let (scheme, rest) = uri
        .split_once("://")
        .ok_or_else(|| UriRefused::new("Unsupported link type: none"))?;
    if scheme.to_lowercase() != SCHEME {
        return Err(UriRefused::new(&format!(
            "Unsupported link type: {}",
            scheme
        )));
    }
    // Split path from query: extract?src=...&dest=...
    let (path_part, query_part) = rest.split_once('?').unwrap_or((rest, ""));
    let action = path_part.trim().to_lowercase();
    if action != "extract" {
        return Err(UriRefused::new(&format!("Unknown action: {}", action)));
    }

    if library_root.as_os_str().is_empty() {
        return Err(UriRefused::new(&format!(
            "No game library is configured, so there is nothing to extract from.{}",
            setup_hint()
        )));
    }

    // Parse query parameters
    let raw_source = parse_query_param(query_part, "src");
    if raw_source.is_empty() {
        return Err(UriRefused::new(
            "The link did not say which archive to extract.",
        ));
    }

    let archive = PathBuf::from(&raw_source);
    if !within(&archive, library_root) {
        return Err(UriRefused::new(&format!(
            "Refused: {} is outside the game library.{}",
            raw_source,
            setup_hint()
        )));
    }
    if !archive.is_file() {
        return Err(UriRefused::new(&format!(
            "That archive is not there any more: {}",
            archive.file_name().unwrap_or_default().to_string_lossy()
        )));
    }
    if !ARCHIVE_EXTENSIONS.iter().any(|ext| {
        archive
            .extension()
            .and_then(|e| e.to_str())
                .is_some_and(|e| e.eq_ignore_ascii_case(ext))
    }) {
        return Err(UriRefused::new(&format!(
            "Not an archive this can unpack: {}",
            archive.file_name().unwrap_or_default().to_string_lossy()
        )));
    }

    // Each game gets its own folder under the chosen parent.
    let leaf = safe_folder_name(
        archive.file_stem().and_then(|s| s.to_str()).unwrap_or(""),
        "game",
    );
    let raw_destination = parse_query_param(query_part, "dest");
    let parent = destination_parent(
        if raw_destination.is_empty() {
            None
        } else {
            Some(&raw_destination)
        },
        &bases,
        library_root,
    )?;
    Ok(ExtractRequest {
        archive,
        destination: parent.join(leaf),
    })
}

/// Extract a single query parameter value from a query string like `src=foo&dest=bar`.
fn parse_query_param(query: &str, key: &str) -> String {
    for pair in query.split('&') {
        let mut kv = pair.splitn(2, '=');
        if let (Some(k), Some(v)) = (kv.next(), kv.next()) {
            if k == key {
                return v.to_string();
            }
        }
    }
    String::new()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_query_param() {
        assert_eq!(parse_query_param("src=foo&dest=bar", "src"), "foo");
        assert_eq!(parse_query_param("src=foo&dest=bar", "dest"), "bar");
        assert_eq!(parse_query_param("src=foo&dest=bar", "missing"), "");
    }
}
