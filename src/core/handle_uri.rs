//! URI handler entry point for `steamgameorganizer://` links.
//!
//! Stub conversion of `core/handle_uri.py`. The single-extract path (parse_uri + ExtractService::extract)
//! is handled by `parse_uri` + `ExtractService::extract` instead; all UI-dependent actions (open-folder,
//! open-extracted, play, pick-launcher, mark-installed, extract-all, extract-multi, setup, refresh-catalog)
//! are stubs returning exit code 2 while the UI layer is still Python.
//!
//! 2026-11-25: Stub conversion from `core/handle_uri.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::path::Path;

use crate::core::config::AppConfig;
use crate::core::parse_uri::parse_uri;
use crate::core::uri_actions::UriRefused;

/// Handle a `steamgameorganizer://` URI. Returns a process exit code.
///
/// Currently refuses every URI because the UI-dependent handlers (open-folder, open-extracted,
/// play, pick-launcher, mark-installed, extract-all, extract-multi, setup, refresh-catalog)
/// are not yet ported to Rust.
pub fn handle_uri(uri: &str, _config: &AppConfig, _logger: &(dyn Fn(&str, &str) + Send + Sync)) -> i32 {
    // Extract the action from the URI: steamgameorganizer://action?params
    let action = uri
        .split("://")
        .nth(1)
        .and_then(|rest| rest.split_once('?').map(|(path, _)| path.to_string()).or_else(|| Some(rest.to_string())))
        .unwrap_or_default()
        .trim_start_matches('/')
        .trim()
        .to_lowercase();

    match action.as_str() {
        "open-folder" | "open-extracted" | "play" | "pick-launcher" | "mark-installed"
        | "extract-all" | "extract-multi" | "setup" | "refresh-catalog" => {
            let _ = UriRefused::new("URI handling not yet ported to Rust");
            2
        }
        "extract" => {
            // Try parsing as a single extract
            let _ = parse_uri(uri, Path::new(""), None);
            2
        }
        _ => {
            let _ = UriRefused::new("Unknown URI action");
            2
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dummy_logger(_: &str, _: &str) {}

    #[test]
    fn test_handle_uri_refused() {
        let result = handle_uri(
            "steamgameorganizer://extract?src=x.zip",
            &AppConfig::new(Path::new("/tmp")),
            &dummy_logger,
        );
        assert_eq!(result, 2);
    }

    #[test]
    fn test_handle_uri_open_folder() {
        let result = handle_uri(
            "steamgameorganizer://open-folder?src=x.zip",
            &AppConfig::new(Path::new("/tmp")),
            &dummy_logger,
        );
        assert_eq!(result, 2);
    }

    #[test]
    fn test_handle_uri_setup() {
        let result = handle_uri(
            "steamgameorganizer://setup",
            &AppConfig::new(Path::new("/tmp")),
            &dummy_logger,
        );
        assert_eq!(result, 2);
    }

    #[test]
    fn test_handle_uri_invalid() {
        let result = handle_uri(
            "not-a-uri",
            &AppConfig::new(Path::new("/tmp")),
            &dummy_logger,
        );
        assert_eq!(result, 2);
    }
}

