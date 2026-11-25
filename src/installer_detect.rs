//! Recognises archives that unpack to a Windows installer rather than a ready-to-play game.
//!
//! Two installer shapes show up in repack libraries and both have to be treated the same way - unpacked into a
//! "Needs Install" folder, not mistaken for a ready-to-play game:
//!
//!   - setup.exe + one or more .bin files (FitGirl, DODI, SteamRIP)
//!   - a .iso that has to be mounted before setup runs (TENOKE, PLAZA)
//!
//! This module is the one place that shape is named, so the extract step that relocates an installer and any surface
//! that wants to flag one - the catalog badge, the run banner - stay in step. The same rule is applied to an extracted
//! folder and to a list of archive member names, so the badge the catalog draws before extraction and the move the
//! extract step performs afterwards cannot disagree.
//!
//! 2026-11-25: Converted from `services/installer_detect.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

use crate::treewalk::walk_files;

/// Executables a setup-based repack uses to install itself. The set is deliberately small and name-bound: a game's
/// own .exe is never one of these, so a normal archive is never mistaken for an installer even though it ships an
/// executable. Detection also requires a .bin alongside one, which closes the obvious false positive of a game that
/// happens to be launched by a file called setup.exe.
pub const INSTALLER_EXE_NAMES: &[&str] = &[
    "setup.exe",
    "setup_install.exe",
    "install.exe",
    "installer.exe",
    "autostart.exe",
    "run.exe",
    "run_installer.exe",
    "setup_game.exe",
];

/// Where an installer archive is parked after extraction, so it is obvious at a glance that it has not been run yet.
pub const NEEDS_INSTALL_DIRNAME: &str = "Needs Install";

/// What marks an archive as an installer, and what the user has to do with it.
///
/// `kind` is "iso" when an ISO to mount is present, "repack" when a named setup exe sits beside .bin data files.
/// `program` is the file the user has to open - the iso to mount, or the exe to run - so a message can be specific
/// instead of generic.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InstallSignature {
    pub kind: String,
    pub program: PathBuf,
}

/// An installer signature read from archive member names, or None if none match.
///
/// Member names from a zip central directory or a `7z l`/`unrar l` listing are treated as relative paths; only their
/// basename and suffix matter, which is what the repack/iso signature is built on. The same rule is used against a
/// directory listing, so "this archive is an installer" and "this folder is an unpacked installer" are one opinion.
pub fn installer_from_names(names: &[String]) -> Option<InstallSignature> {
    let mut iso: Option<PathBuf> = None;
    let mut exe: Option<PathBuf> = None;
    let mut saw_bin = false;
    for name in names {
        let member = Path::new(name);
        let suffix = member
            .extension()
            .map_or(String::new(), |e| e.to_string_lossy().to_lowercase());
        let base = member
            .file_name()
            .map_or(String::new(), |s| s.to_string_lossy().to_lowercase());
        if suffix == "iso" {
            if iso.is_none() {
                iso = Some(member.to_path_buf());
            }
        } else if INSTALLER_EXE_NAMES.contains(&base.as_str()) {
            if exe.is_none() {
                exe = Some(member.to_path_buf());
            }
        } else if suffix == "bin" {
            saw_bin = true;
        }
        if iso.is_some() || (exe.is_some() && saw_bin) {
            break;
        }
    }
    if let Some(program) = iso {
        return Some(InstallSignature {
            kind: "iso".to_string(),
            program,
        });
    }
    if let Some(program) = exe {
        if saw_bin {
            return Some(InstallSignature {
                kind: "repack".to_string(),
                program,
            });
        }
    }
    None
}

/// The installer signature in an extracted folder, or None if it is not an installer layout.
///
/// Returns the signature rather than a bare bool so a caller can name the exact program the reader has to run
/// instead of leaving the message generic. The scan is junction-safe through walk_files: an archive that unpacks
/// to a junction back into itself would otherwise be followed forever by rglob.
///
/// `entries` optionally supplies pre-computed Path objects (e.g. from a single rglob the caller already did),
/// avoiding a second walk of the same tree.
pub fn find_installer(root: &Path, entries: Option<&[PathBuf]>) -> Option<InstallSignature> {
    if !root.is_dir() {
        return None;
    }
    let names: Vec<String> = match entries {
        Some(entries) => entries
            .iter()
            .map(|p| p.to_string_lossy().to_string())
            .collect(),
        None => walk_files(root)
            .iter()
            .map(|p| p.to_string_lossy().to_string())
            .collect(),
    };
    installer_from_names(&names)
}

/// True when an extracted folder holds a repack-style or ISO installer.
pub fn looks_like_installer(root: &Path) -> bool {
    find_installer(root, None).is_some()
}

/// True when `root` is an unpacked installer that has not been run yet.
///
/// Checks two layouts:
///   - New style: the folder itself sits inside a "Needs Install" directory at the extract root.
///   - Old style: a "Needs Install" subfolder lives inside the game folder (pre-v9.31 relocations).
///
/// A cheap directory-entry check rather than re-scanning for the setup.exe/.bin/.iso signature on every card.
pub fn has_needs_install_mark(root: &Path) -> bool {
    if let Some(parent) = root.parent() {
        if parent.file_name().is_some_and(|n| n == NEEDS_INSTALL_DIRNAME) {
            return true;
        }
    }
    root.join(NEEDS_INSTALL_DIRNAME).is_dir()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_installer_from_names_repack() {
        let names = vec!["setup.exe".to_string(), "data1.bin".to_string()];
        let sig = installer_from_names(&names);
        assert!(sig.is_some());
        assert_eq!(sig.unwrap().kind, "repack");
    }

    #[test]
    fn test_installer_from_names_iso() {
        let names = vec!["game.iso".to_string()];
        let sig = installer_from_names(&names);
        assert!(sig.is_some());
        assert_eq!(sig.unwrap().kind, "iso");
    }

    #[test]
    fn test_installer_from_names_none() {
        let names = vec!["game.exe".to_string(), "data.dat".to_string()];
        let sig = installer_from_names(&names);
        assert!(sig.is_none());
    }

    #[test]
    fn test_has_needs_install_mark() {
        use std::env;
        let temp = env::temp_dir().join(format!("test_needs_install_{}", std::process::id()));
        std::fs::create_dir_all(&temp).ok();
        assert!(!has_needs_install_mark(&temp));
        let _ = std::fs::remove_dir_all(&temp);
    }
}
