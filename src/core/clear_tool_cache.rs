//! `clear_tool_cache` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-25: Converted from `services/clear_tool_cache.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

/// No-op retained for API compatibility.
///
/// `find_tool()` re-scans on every call, so there is nothing to invalidate.
pub fn clear_tool_cache() {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_clear_tool_cache_is_noop() {
        clear_tool_cache();
        // Should not panic
    }
}
