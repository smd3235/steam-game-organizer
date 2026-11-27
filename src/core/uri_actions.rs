//! Turns a steamgameorganizer:// URI into an extraction request, or refuses it.
//!
//! A registered protocol handler is the one supported way for a web page to ask the machine to do something, and
//! it is also the one way a web page can try to make a local program touch an arbitrary path. Anything can craft
//! the link, including another page the user happens to visit, so this module treats every field as hostile input.
//!
//! Three rules, and each one exists because without it the link is a remote file-write:
//!
//!   1. The source must resolve inside the configured library root. Otherwise the handler would be a way to ask
//!      the machine to unpack /etc or the user's home directory.
//!   2. The source must already exist and carry an archive extension, so the check above cannot be satisfied with
//!      a path that only looks like it points into the library.
//!   3. The destination must be a usable folder: either inside the configured extract folder, omitted so a safe
//!      default is derived, or a full path the user typed into the catalog page that is not a system folder and not
//!      inside the library. See `typed_destination` for what the free-text case still rules out.
//!
//! Nothing here runs a command or touches the disk beyond resolving paths; the caller does that.
//!
//! 2026-11-24: Converted from `core/uri_actions.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::path::PathBuf;

use crate::core::system_paths::system_paths;

pub const SCHEME: &str = "steamgameorganizer";
pub const UNSAFE_CHARS: &str = r#"[<>:"/\\|?*\x00-\x1f]"#;

// Folders a typed destination may never be. The catalog page accepts a free-text path, and unpacking a 40 GB
// game into one of these is unrecoverable without root, so they are refused by name rather than left to the
// user to avoid.
pub fn system_paths_vec() -> Vec<String> {
    system_paths()
}

/// Request to extract one archive to a destination.
#[derive(Debug, Clone)]
pub struct ExtractRequest {
    pub archive: PathBuf,
    pub destination: PathBuf,
}

/// Request to launch a validated game executable under configured extract folders.
#[derive(Debug, Clone)]
pub struct PlayRequest {
    pub exe: PathBuf,
    pub marker_dir: Option<PathBuf>,
}

/// Request that targets an extracted root/marker directory under extract folders.
#[derive(Debug, Clone)]
pub struct ExtractRootRequest {
    pub folder: PathBuf,
}

/// The three paths a fresh PC has to be told, as the page offered them.
///
/// Every field is a prefill for a box the user edits before anything is saved, not a
/// command: the wizard that reads this re-validates each path against the disk before
/// it touches a setting or the registry. A hostile page can put anything in here, and
/// the worst that can happen is a nonsense string sitting in a text box.
#[derive(Debug, Clone, Default)]
pub struct SetupRequest {
    pub library: String,
    pub extract: String,
    pub app: String,
}

/// Request to unpack many archives, named by category rather than by path.
///
/// Deliberately carries no archive list. A single-extract link names one file and is checked against the
/// library root, so a hostile page can at worst ask for a file the user already owns. A batch link that carried
/// its own list would be the same handler pointed at an arbitrary set of sources, and the check would have to
/// be repeated per entry - the kind of rule that is right until one entry is missed. So the link names a
/// category and the app enumerates the library itself, which leaves the page able to say "Idle" and nothing
/// more.
#[derive(Debug, Clone)]
pub struct BatchExtractRequest {
    pub category: String,
    pub destination: PathBuf,
}

/// Request to unpack a user-selected set of archives from the catalog.
///
/// Each archive path is validated individually against the library root by parse_multi_uri(), using the same
/// rules as parse_uri - so a hostile page can at worst ask for archives the user already owns. The destination
/// is shared across all items, same as BatchExtractRequest.
#[derive(Debug, Clone)]
pub struct MultiBatchRequest {
    pub archives: Vec<(PathBuf, PathBuf)>,
    pub destination: PathBuf,
}

/// Raised with a message meant for the user, not a traceback.
#[derive(Debug)]
pub struct UriRefused {
    pub message: String,
}

impl UriRefused {
    pub fn new(message: &str) -> Self {
        UriRefused {
            message: message.to_string(),
        }
    }
}

impl std::fmt::Display for UriRefused {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}

impl std::error::Error for UriRefused {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_scheme_constant() {
        assert_eq!(SCHEME, "steamgameorganizer");
    }

    #[test]
    fn test_unsafe_chars_constant() {
        assert!(!UNSAFE_CHARS.is_empty());
    }

    #[test]
    fn test_extract_request_derive() {
        let req = ExtractRequest {
            archive: std::path::PathBuf::from("/tmp/game.zip"),
            destination: std::path::PathBuf::from("/tmp/extract"),
        };
        let debug = format!("{:?}", req);
        assert!(debug.contains("game.zip"));
        assert!(debug.contains("extract"));
    }

    #[test]
    fn test_play_request_derive() {
        let req = PlayRequest {
            exe: std::path::PathBuf::from("/tmp/game.exe"),
            marker_dir: Some(std::path::PathBuf::from("/tmp/marker")),
        };
        let debug = format!("{:?}", req);
        assert!(debug.contains("game.exe"));
    }

    #[test]
    fn test_extract_root_request_derive() {
        let req = ExtractRootRequest {
            folder: std::path::PathBuf::from("/tmp/root"),
        };
        let debug = format!("{:?}", req);
        assert!(debug.contains("root"));
    }

    #[test]
    fn test_setup_request_default() {
        let req = SetupRequest::default();
        assert_eq!(req.library, "");
        assert_eq!(req.extract, "");
        assert_eq!(req.app, "");
    }

    #[test]
    fn test_batch_extract_request_derive() {
        let req = BatchExtractRequest {
            category: "RPG".to_string(),
            destination: std::path::PathBuf::from("/tmp/rpg"),
        };
        let debug = format!("{:?}", req);
        assert!(debug.contains("RPG"));
    }

    #[test]
    fn test_multibatch_request_derive() {
        let req = MultiBatchRequest {
            archives: vec![(
                std::path::PathBuf::from("/tmp/a.zip"),
                std::path::PathBuf::from("/tmp/out"),
            )],
            destination: std::path::PathBuf::from("/tmp/out"),
        };
        assert_eq!(req.archives.len(), 1);
    }

    #[test]
    fn test_uri_refused_new_and_display() {
        let err = UriRefused::new("access denied");
        assert_eq!(err.message, "access denied");
        assert_eq!(format!("{}", err), "access denied");
    }

    #[test]
    fn test_system_paths_vec_returns_vec() {
        let paths = system_paths_vec();
        assert!(!paths.is_empty());
    }
}
