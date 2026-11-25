//! Pure utility functions extracted from AppController.
//!
//! These functions have no dependency on AppController instance state and can be
//! imported and tested independently. They were previously methods on AppController
//! that took all their inputs as parameters.
//!
//! 2026-11-25: Converted from `core/controller_utils.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::fs;
use std::path::Path;

use crate::constants::ARCHIVE_EXTENSIONS;
use crate::models::{ArtworkResult, GameArchive};
use crate::path_safety::{DeletionGuard};

/// Whether one archive has artwork, counting an unreadable artwork object as having none.
///
/// Counted per archive rather than inline, because a generator inside the dict literal that builds the
/// summary shares an expression with every other number in it: one artwork object that raised took all
/// of them down, so a single bad entry cost the archive count, the byte total and the match count as
/// well. The worst this can now cost is one game counted as having no picture, which is what a game with
/// no picture counts as anyway.
pub fn artwork_present(artwork: &ArtworkResult) -> bool {
    artwork.present()
}

/// The copy a group will move: its newest version, chosen exactly as the move itself will choose it.
///
/// Takes a promotion_key callable rather than reaching into services, so it can be tested with a stub.
/// Previously AppController._primary.
pub fn primary<T, F>(group: &[T], promotion_key: F) -> &T
where
    F: Fn(&T) -> (Vec<u32>, f64),
{
    group
        .iter()
        .max_by(|a, b| promotion_key(a).partial_cmp(&promotion_key(b)).unwrap_or(std::cmp::Ordering::Less))
        .expect("group must not be empty")
}

/// True when moving this archive will actually rebuild it into a .7z.
pub fn needs_conversion(archive: &GameArchive, convert_archives: bool) -> bool {
    if !convert_archives {
        return false;
    }
    if archive.extension.eq_ignore_ascii_case(".7z") {
        return false;
    }
    archive.path.is_file()
}

/// Size of the archive a group would actually move, i.e. its newest copy. Missing files sort last.
pub fn primary_size(
    group: &[GameArchive],
    promotion_key: impl Fn(&GameArchive) -> (Vec<u32>, f64),
) -> u64 {
    let primary_archive = primary(group, &promotion_key);
    primary_archive.path.metadata().map_or(1 << 62, |m| m.len())
}

/// Drop a game folder that a rollback has emptied.
///
/// Rolling a game back returns its archive to where it came from but leaves the folder the run created, and
/// what stays in it is what this run wrote there: the metadata, and the Steam link and artwork beside it. A
/// failed or cancelled run therefore littered the library with folders that describe a game they do not
/// hold, which no scan can see and the user has to delete by hand. Only a folder this run created is ever
/// removed - one that was already there belongs to the user whatever it contains.
/// The folder is moved to Archive/ rather than deleted, so the user can review it before deleting.
pub fn prune_rolled_back_folder(
    game_dir: &Path,
    owned: bool,
    library_root: Option<&Path>,
    logger: Option<&dyn Fn(&str, &str)>,
) {
    if !owned {
        return;
    }
    let root = library_root
        .map(|l| l.to_path_buf())
        .unwrap_or_default();
    if root.as_os_str().is_empty() {
        if let Some(logger) = logger {
            logger(
                "ORGANIZER",
                &format!("ROLLBACK_FOLDER_KEPT path=[{}] reason=[no library root to prove containment]", game_dir.display()),
            );
        }
        return;
    }
    // A DeletionGuard built from the library root alone: nothing may be pruned outside it.
    let root_str = root.to_string_lossy().to_string();
    let guard = DeletionGuard::new(&[root_str.as_str()]).expect("library root must be valid");
    match guard.refuse_outside(game_dir, "prune") {
        Ok(_) => {}
        Err(refused) => {
            if let Some(logger) = logger {
                logger(
                    "ORGANIZER",
                    &format!("ROLLBACK_FOLDER_KEPT path=[{}] reason=[{}]", game_dir.display(), refused),
                );
            }
            return;
        }
    }
    if !game_dir.is_dir() {
        return;
    }
    if game_dir.read_dir().map_or(false, |mut entries| {
        entries.any(|e| {
            e.map_or(false, |entry| {
                entry
                    .path()
                    .extension()
                    .is_some_and(|ext| ARCHIVE_EXTENSIONS.iter().any(|ae| ext.eq_ignore_ascii_case(ae)))
            })
        })
    }) {
        if let Some(logger) = logger {
            logger(
                "ORGANIZER",
                &format!("ROLLBACK_FOLDER_KEPT path=[{}] reason=[still holds an archive]", game_dir.display()),
            );
        }
        return;
    }
    let archive_dir = root.join("Archive");
    let _ = fs::create_dir_all(&archive_dir);
    let mut target = archive_dir.join(game_dir.file_name().unwrap_or_default());
    let mut n = 2;
    while target.exists() {
        target = archive_dir.join(format!("{} ({})", game_dir.file_name().unwrap_or_default().to_string_lossy(), n));
        n += 1;
    }
    match fs::rename(game_dir, &target) {
        Ok(()) => {
            if let Some(logger) = logger {
                logger(
                    "ORGANIZER",
                    &format!(
                        "ROLLBACK_PRUNED_EMPTY_GAME_DIR path=[{}] destination=[{}]",
                        game_dir.display(),
                        target.display()
                    ),
                );
            }
        }
        Err(prune_error) => {
            if let Some(logger) = logger {
                logger(
                    "ORGANIZER",
                    &format!(
                        "ROLLBACK_PRUNE_FAILED path=[{}] error=[{}]",
                        game_dir.display(),
                        prune_error
                    ),
                );
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn test_archive(path: &str, extension: &str) -> GameArchive {
        GameArchive {
            path: PathBuf::from(path),
            extension: extension.to_string(),
            ..Default::default()
        }
    }

    #[test]
    fn test_primary_single() {
        let archives = vec![test_archive("/game.zip", ".zip")];
        let result = primary(&archives, |a| (a.version.clone(), a.size as f64));
        assert_eq!(result.path, PathBuf::from("/game.zip"));
    }

    #[test]
    fn test_needs_conversion_7z_skipped() {
        let archive = test_archive("/game.7z", ".7z");
        assert!(!needs_conversion(&archive, true));
    }

    #[test]
    fn test_needs_conversion_convert_false() {
        let archive = test_archive("/game.zip", ".zip");
        assert!(!needs_conversion(&archive, false));
    }
}
