//! Install protocol handler tool: registers steamgameorganizer:// handler.
//! Stub conversion of `tools/install_protocol_handler.py`.
//!
//! 2026-11-25: Rust conversion from `tools/install_protocol_handler.py` in the Rust conversion.

use std::path::Path;

pub fn install_protocol_handler(_entry: &Path) -> Result<(), String> {
    Err("install protocol handler not yet implemented".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_install_protocol_handler_stub() {
        let result = install_protocol_handler(Path::new("."));
        assert!(result.is_err());
    }
}
