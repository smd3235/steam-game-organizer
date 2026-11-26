//! `parse_setup_uri` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-24: Converted from `core/parse_setup_uri.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use crate::core::prefill::prefill;
use crate::core::uri_actions::{SetupRequest, UriRefused, SCHEME};

/// Returns the setup prefills a steamgameorganizer://setup link carries, or refuses.
pub fn parse_setup_uri(uri: &str) -> Result<SetupRequest, UriRefused> {
    let (scheme, rest) = uri
        .split_once("://")
        .ok_or_else(|| UriRefused::new("Unsupported link type: none"))?;
    if scheme.to_lowercase() != SCHEME {
        return Err(UriRefused::new(&format!(
            "Unsupported link type: {}",
            scheme
        )));
    }
    let (path_part, _query) = rest.split_once('?').unwrap_or((rest, ""));
    let action = path_part.trim().to_lowercase();
    if action != "setup" {
        return Err(UriRefused::new(&format!("Unknown action: {}", action)));
    }
    Ok(SetupRequest {
        library: prefill(Some(parse_query_param(rest, "library").as_str())),
        extract: prefill(Some(parse_query_param(rest, "extract").as_str())),
        app: prefill(Some(parse_query_param(rest, "app").as_str())),
    })
}

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
        assert_eq!(parse_query_param("library=x&extract=y", "library"), "x");
    }
}
