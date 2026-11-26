//! `parse_play_uri` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-25: Converted from `core/parse_play_uri.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

#![allow(clippy::all)]

use std::path::{Path, PathBuf};

use crate::core::catalog_status::get_launch_target;
use crate::core::configured_bases::configured_bases;
use crate::core::parse_extract_root_action::parse_extract_root_action;
use crate::core::setup_hint::setup_hint;
use crate::core::uri_actions::{PlayRequest, UriRefused, SCHEME};
use crate::core::within::within;

/// Returns a validated PlayRequest for a steamgameorganizer://play link.
///
/// `exe` may point directly at an executable, or `path` may point at a marker/root
/// directory whose persisted `launch_target` should be used. The target must be a
/// `.exe` file under configured extract folders.
pub fn parse_play_uri(
    uri: &str,
    extract_folders: Option<Vec<&str>>,
) -> Result<PlayRequest, UriRefused> {
    let parts = split_url(uri);
    if parts.scheme.to_lowercase() != SCHEME {
        return Err(UriRefused::new(&format!(
            "Unsupported link type: {}",
            parts.scheme
        )));
    }
    let action = parts.path.trim_start_matches('/').to_lowercase();
    if action != "play" {
        return Err(UriRefused::new(&format!("Unknown action: {}", action)));
    }
    let bases = configured_bases(extract_folders.clone());
    if bases.is_empty() {
        return Err(UriRefused::new(&format!(
            "No extract folder is configured.{}",
            setup_hint()
        )));
    }
    let query_pairs = parse_query(&parts.query);
    let raw_exe = query_pairs
        .iter()
        .find(|(k, _)| *k == "exe")
        .map(|(_, v)| *v)
        .unwrap_or("");
    let raw_marker = query_pairs
        .iter()
        .find(|(k, _)| *k == "path" || *k == "marker")
        .map(|(_, v)| *v)
        .unwrap_or("");
    let mut marker_dir: Option<PathBuf> = None;
    if !raw_marker.is_empty() {
        marker_dir = Some(parse_extract_root_action(
            &format!("{}://pick-launcher?path={}", SCHEME, raw_marker),
            extract_folders,
            "pick-launcher",
            false,
        )?);
    }
    let exe_path: Option<PathBuf>;
    if !raw_exe.is_empty() {
        let exe = Path::new(raw_exe);
        if !bases.iter().any(|b| within(exe, b)) {
            return Err(UriRefused::new(&format!(
                "Refused: {} is outside the configured extract folders.",
                raw_exe
            )));
        }
        exe_path =
            Some(exe.canonicalize().map_err(|exc| {
                UriRefused::new(&format!("That launcher cannot be opened: {}", exc))
            })?);
        let exe_path_ref = exe_path.as_ref().expect("exe_path must be Some");
        if !exe_path_ref.is_file()
            || exe_path_ref
                .extension()
                .map_or(false, |e| e.to_string_lossy().to_lowercase() != "exe")
        {
            return Err(UriRefused::new(
                "Play links may only launch .exe files inside extract folders.",
            ));
        }
    } else if let Some(ref marker) = marker_dir {
        exe_path = get_launch_target(
            &marker,
            &bases.iter().map(|b| b.to_path_buf()).collect::<Vec<_>>(),
        );
        if exe_path.is_none() {
            return Err(UriRefused::new(
                "No saved launcher is set for this game. Use Pick launcher first.",
            ));
        }
    } else {
        return Err(UriRefused::new("The link did not say what to launch."));
    }
    Ok(PlayRequest {
        exe: exe_path.expect("exe_path must be set when no error"),
        marker_dir,
    })
}

/// Simple URL parsing for scheme, path, query (replaces Python's urlsplit).
struct UrlParts {
    scheme: String,
    path: String,
    query: String,
}

fn split_url(uri: &str) -> UrlParts {
    let mut scheme = String::new();
    let mut rest = uri;
    if let Some(idx) = uri.find("://") {
        scheme = uri[..idx].to_string();
        rest = &uri[idx + 3..];
    }
    let mut path = rest.to_string();
    let mut query = String::new();
    if let Some(q_idx) = rest.find('?') {
        path = rest[..q_idx].to_string();
        query = rest[q_idx + 1..].to_string();
    }
    if !path.starts_with('/') {
        path = format!("/{}", path);
    }
    UrlParts {
        scheme,
        path,
        query,
    }
}

/// Simple query string parsing (replaces Python's parse_qs).
fn parse_query(query: &str) -> Vec<(&str, &str)> {
    query
        .split('&')
        .filter(|pair| pair.contains('='))
        .map(|pair| {
            let mut kv = pair.splitn(2, '=');
            (kv.next().unwrap_or(""), kv.next().unwrap_or(""))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_play_uri_unknown_scheme() {
        let result = parse_play_uri("http://example.com/play", None);
        assert!(result.is_err());
    }

    #[test]
    fn test_parse_play_uri_unknown_action() {
        let result = parse_play_uri("steamgameorganizer://extract", None);
        assert!(result.is_err());
    }

    #[test]
    fn test_parse_play_uri_no_bases() {
        let result = parse_play_uri("steamgameorganizer://play?exe=foo.exe", None);
        assert!(result.is_err());
    }

    #[test]
    fn test_split_url() {
        let parts = split_url("steamgameorganizer://play?exe=foo.exe");
        assert_eq!(parts.scheme, "steamgameorganizer");
        assert_eq!(parts.path, "/play");
        assert_eq!(parts.query, "exe=foo.exe");
    }

    #[test]
    fn test_parse_query() {
        let pairs = parse_query("exe=foo.exe&path=/bar");
        assert_eq!(pairs.len(), 2);
        assert_eq!(pairs[0], ("exe", "foo.exe"));
        assert_eq!(pairs[1], ("path", "/bar"));
    }
}
