//! URI handler for picking a game launcher (`steamgameorganizer://pick-launcher`).
//!
//! Stub conversion of `core/handle_pick_launcher_uri.py`. Returns exit code 2 until the file
//! picker dialog and its dependencies are ported to Rust.
//!
//! 2026-11-25: Stub conversion from `core/handle_pick_launcher_uri.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use crate::core::config::AppConfig;
use crate::core::uri_actions::UriRefused;

pub fn handle_pick_launcher_uri(
    _uri: &str,
    _config: &AppConfig,
    _logger: &(dyn Fn(&str, &str) + Send + Sync),
) -> i32 {
    let _ = UriRefused::new("Pick launcher URI handling not yet ported to Rust");
    2
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    fn dummy_logger(_: &str, _: &str) {}

    #[test]
    fn test_handle_pick_launcher_uri_refused() {
        let result = handle_pick_launcher_uri(
            "steamgameorganizer://pick-launcher?marker=foo",
            &AppConfig::new(Path::new("/tmp")),
            &dummy_logger,
        );
        assert_eq!(result, 2);
    }
}
