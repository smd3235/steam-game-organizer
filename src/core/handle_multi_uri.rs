//! URI handler for multi-select batch extraction (`steamgameorganizer://extract-multi`).
//!
//! Stub conversion of `core/handle_multi_uri.py`. Returns exit code 2 until the batch extract
//! window and its dependencies are ported to Rust.
//!
//! 2026-11-25: Stub conversion from `core/handle_multi_uri.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use crate::core::config::AppConfig;
use crate::core::uri_actions::UriRefused;

pub fn handle_multi_uri(_uri: &str, _config: &AppConfig, _logger: &(dyn Fn(&str, &str) + Send + Sync)) -> i32 {
    let _ = UriRefused::new("Multi-extract URI handling not yet ported to Rust");
    2
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    fn dummy_logger(_: &str, _: &str) {}

    #[test]
    fn test_handle_multi_uri_refused() {
        let result = handle_multi_uri(
            "steamgameorganizer://extract-multi",
            &AppConfig::new(Path::new("/tmp")),
            &dummy_logger,
        );
        assert_eq!(result, 2);
    }
}

