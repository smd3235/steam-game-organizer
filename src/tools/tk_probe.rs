//! Tkinter probe tool: tests Tk/DarkTitleBar availability.
//! Stub conversion of `tools/tk_probe.py`.
//!
//! 2026-11-25: Rust conversion from `tools/tk_probe.py` in the Rust conversion.

use std::path::Path;

/// Probe Tk/dark title bar availability.
pub fn probe_tk(_tk_path: &Path) -> Result<(), String> {
    // Stub: Tk probe not yet implemented in Rust.
    Err("tk probe not yet implemented".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_probe_tk_stub() {
        let result = probe_tk(Path::new("tk"));
        assert!(result.is_err());
    }
}
