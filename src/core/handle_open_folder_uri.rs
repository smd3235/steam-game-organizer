//! `handle_open_folder_uri` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! 2026-11-25: Converted from `core/handle_open_folder_uri.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::process::Command;

use crate::core::constants::APP_NAME;
use crate::core::parse_open_folder_uri::parse_open_folder_uri;

/// Opens the game folder in Explorer/Files.
///
/// A file:// page cannot open a folder, so this goes through the same
/// steamgameorganizer:// protocol handler as Extract. The path is validated
/// against the library root by parse_open_folder_uri, so a malicious page
/// can only ask for a folder the user already owns.
pub fn handle_open_folder_uri(
    uri: &str,
    library_root: &std::path::Path,
    logger: &dyn Fn(&str, &str),
) -> i32 {
    match parse_open_folder_uri(uri, library_root) {
        Ok(folder) => {
            logger(
                "EXTRACT",
                &format!(
                    "URI_ACCEPTED action=open-folder path=[{}]",
                    folder.display()
                ),
            );
            match Command::new("cmd")
                .args(["/c", "start", "", folder.to_string_lossy().as_ref()])
                .status()
            {
                Ok(_) => 0,
                Err(exc) => {
                    print!("{}: Could not open {}: {}", APP_NAME, folder.display(), exc);
                    1
                }
            }
        }
        Err(refused) => {
            logger(
                "EXTRACT",
                &format!("URI_REFUSED uri=[{}] reason=[{}]", uri, refused),
            );
            print!("{}: {}", APP_NAME, refused);
            2
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dummy_logger(_: &str, _: &str) {}

    #[test]
    fn test_handle_open_folder_uri_invalid_scheme() {
        let result = handle_open_folder_uri(
            "http://example.com/folder",
            std::path::Path::new("/"),
            &dummy_logger,
        );
        assert_eq!(result, 2);
    }
}
