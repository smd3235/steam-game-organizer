//! `_system_paths` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! Folders a typed destination may never sit inside. Read from the environment
//! rather than spelled out, because Windows, Program Files and ProgramData are not
//! reliably where a hard-coded list says they are.
//!
//! 2026-11-24: Converted from `core/system_paths.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::env;

/// Folders a typed destination may never sit inside.
pub fn system_paths() -> Vec<String> {
    let variables = [
        "SystemRoot",
        "ProgramFiles",
        "ProgramFiles(x86)",
        "ProgramData",
        "ProgramW6432",
    ];
    let mut paths: Vec<String> = Vec::new();
    for variable in &variables {
        if let Ok(value) = env::var(variable) {
            paths.push(value);
        }
    }
    paths.sort();
    paths
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_system_paths_returns_vec() {
        let paths = system_paths();
        // Should always contain SystemRoot on Windows
        assert!(!paths.is_empty());
    }
}
