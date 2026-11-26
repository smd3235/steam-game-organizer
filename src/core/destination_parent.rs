//! `_destination_parent` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-24: Converted from `core/destination_parent.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::path::{Path, PathBuf};

use crate::core::typed_destination::typed_destination;
use crate::core::uri_actions::UriRefused;

/// The folder a game's own subfolder will be created inside, or refuse.
///
/// Shared by the single and batch actions so the two cannot drift on what counts as an acceptable destination -
/// the free-text case in particular is a security boundary, and a second copy of it would be a second thing to
/// get wrong.
pub fn destination_parent(
    raw_destination: Option<&str>,
    bases: &[PathBuf],
    library_root: &Path,
) -> Result<PathBuf, UriRefused> {
    if bases.is_empty() {
        return Err(UriRefused::new(&format!(
            "No extract folder is configured, so there is nowhere to unpack to.{}",
            crate::core::setup_hint::setup_hint()
        )));
    }
    let raw_destination = raw_destination.unwrap_or("").trim();
    if raw_destination.is_empty() {
        return Ok(bases[0].clone());
    }
    typed_destination(raw_destination, library_root)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_destination_parent_no_bases_refused() {
        let result = destination_parent(Some("C:\\Games"), &[], &PathBuf::from("C:\\Library"));
        assert!(result.is_err());
    }

    #[test]
    fn test_destination_parent_empty_uses_first_base() {
        let bases = vec![PathBuf::from("C:\\Extract")];
        let result = destination_parent(None, &bases, &PathBuf::from("C:\\Library"));
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), PathBuf::from("C:\\Extract"));
    }
}
