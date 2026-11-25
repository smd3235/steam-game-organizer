//! Bundle runtime tool: bundles runtime dependencies.
//! Stub conversion of `tools/bundle_runtime.py`.
//!
//! 2026-11-25: Rust conversion from `tools/bundle_runtime.py` in the Rust conversion.

use std::path::Path;

pub fn bundle_runtime(_runtime_dir: &Path) -> Result<(), String> {
    Err("bundle runtime not yet implemented".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_bundle_runtime_stub() {
        let result = bundle_runtime(Path::new("."));
        assert!(result.is_err());
    }
}
