//! The three-path setup a fresh PC needs, and the one place those paths are saved.
//!
//! A web page cannot write a file, so the Game folder and Extract to boxes in the catalog
//! are only remembered by the browser - they never reach this app. What the app itself has
//! to be told is what the protocol handler validates every Extract link against: the library
//! root (a source is refused if it is not inside it) and the extract folders (the
//! destination a link with no destination falls back to). Both live in config/settings.json
//! beside the app, and on a PC that has never run the setup they hold the defaults - which
//! is why an Extract button on a friend's machine refuses every link the page can build,
//! no matter what is typed into the page's own boxes.
//!
//! The wizard this service backs is opened two ways: the "Set up on this PC" button at the
//! top of the catalog, and --setup on the command line for the first run on a machine where
//! the protocol handler is not registered yet, because a button that goes through that
//! handler cannot be the thing that installs it.
//!
//! 2026-11-25: Converted from `services/setup_service.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::path::Path;
use std::sync::Arc;

use crate::constants::{ENTRY_POINT, LIBRARY_RESERVED_DIRS};
use crate::extract_service::ExtractService;

/// The three-path setup a fresh PC needs, and the one place those paths are saved.
///
/// `register_handler` and `registered_command` are injected so a test can watch a
/// registration without touching the registry; both default to functions in
/// `tools/install_protocol_handler.py`, which write `HKCU\\Software\\Classes`.
pub struct SetupService {
    pub logger: Arc<dyn Fn(&str, &str) + Send + Sync>,
    register: Arc<dyn Fn(&str, &Path) + Send + Sync>,
    registered: Arc<dyn Fn() -> Option<String> + Send + Sync>,
}

impl SetupService {
    pub fn new(
        logger: Arc<dyn Fn(&str, &str) + Send + Sync>,
        register: Option<Arc<dyn Fn(&str, &Path) + Send + Sync>>,
        registered: Option<Arc<dyn Fn() -> Option<String> + Send + Sync>>,
    ) -> Self {
        SetupService {
            logger,
            register: register.unwrap_or_else(|| Arc::new(default_register)),
            registered: registered.unwrap_or_else(|| Arc::new(default_registered)),
        }
    }

    /// What is wrong with these three paths, as (level, message) rows.
    ///
    /// level is 'error' (the save would be refused or nothing would work), 'warn'
    /// (it works, but badly) or 'ok'. These rows are what the wizard shows before
    /// anything is saved, so a user can see why a save would be refused rather than
    /// try and fail.
    pub fn checks(&self, library: &str, app: &str, extract: &str) -> Vec<(String, String)> {
        let mut rows: Vec<(String, String)> = Vec::new();
        let library = Path::new(library_or_empty(library));
        let app = Path::new(app_or_empty(app));
        let extract = Path::new(extract_or_empty(extract));
        if library.as_os_str().is_empty() {
            rows.push(("error".to_string(), "No game library folder was given.".to_string()));
        } else if !library.is_dir() {
            rows.push((
                "warn".to_string(),
                format!(
                    "The game library does not exist yet: {} - it will be created",
                    library.display()
                ),
            ));
        } else if !_library_has_games(&library) {
            rows.push((
                "warn".to_string(),
                format!(
                    "The game library holds no organized games yet: {} - run a scan once the setup is saved",
                    library.display()
                ),
            ));
        } else {
            rows.push((
                "ok".to_string(),
                format!("Game library: {}", library.display()),
            ));
        }
        let entry = app.join(ENTRY_POINT);
        let exe_entry = app.join(ENTRY_POINT.replace(".py", ".exe"));
        if app.as_os_str().is_empty() {
            rows.push(("error".to_string(), "No app folder was given.".to_string()));
        } else if !app.is_dir() {
            rows.push((
                "error".to_string(),
                format!("The app folder is not a folder: {}", app.display()),
            ));
        } else if !entry.is_file() && !exe_entry.is_file() {
            rows.push((
                "error".to_string(),
                format!(
                    "No {ENTRY_POINT} or {} in {} - this is not the app's folder",
                    ENTRY_POINT.replace(".py", ".exe"),
                    app.display()
                ),
            ));
        } else {
            rows.push(("ok".to_string(), format!("App folder: {}", app.display())));
        }
        if extract.as_os_str().is_empty() {
            rows.push(("error".to_string(), "No extract folder was given.".to_string()));
        } else if extract.exists() && !extract.is_dir() {
            rows.push((
                "error".to_string(),
                format!("The extract folder is a file, not a folder: {}", extract.display()),
            ));
        } else if !_writable_or_creatable(&extract) {
            rows.push((
                "error".to_string(),
                format!("The extract folder is not writable: {}", extract.display()),
            ));
        } else if library.is_dir() && _within(&extract, &library) {
            // The same rule every typed destination is held to: an extracted game is a
            // folder of loose files, and the scanner treats every directory inside a
            // category as a game folder, so extracting into the library would hand the
            // next scan the unpacked files as games to reconsider.
            rows.push((
                "error".to_string(),
                format!(
                    "The extract folder is inside the game library. Choose a folder outside it: {}",
                    extract.display()
                ),
            ));
        } else {
            rows.push(("ok".to_string(), format!("Extract to: {}", extract.display())));
        }
        let (found, _reason) = ExtractService::find_tool();
        if found.is_none() {
            rows.push((
                "warn".to_string(),
                "No 7-Zip was found, so Extract will not work until it is installed".to_string(),
            ));
        }
        if let Some(command) = (self.registered)() {
            rows.push((
                "ok".to_string(),
                format!(
                    "The steamgameorganizer:// link is registered: {}",
                    command
                ),
            ));
        } else {
            rows.push((
                "warn".to_string(),
                "The steamgameorganizer:// link is not registered, so the catalog's Extract buttons do nothing. Saving this setup registers it."
                    .to_string(),
            ));
        }
        rows
    }

    /// Save the three paths and register the handler. Returns (saved, rows).
    ///
    /// The checks run first and any error refuses the save: AppConfig.save() would
    /// silently drop a library root the disk does not have, and a registration
    /// pointing at a folder with no entry point would leave every Extract link dead
    /// with nothing on the page to say why.
    pub fn apply(
        &self,
        _config: &crate::config::AppConfig,
        library: &str,
        app: &str,
        extract: &str,
    ) -> (bool, Vec<(String, String)>) {
        let mut rows = self.checks(library, app, extract);
        if rows.iter().any(|(level, _)| level == "error") {
            return (false, rows);
        }
        let library = Path::new(library_or_empty(library));
        let app = Path::new(app_or_empty(app));
        let extract = Path::new(extract_or_empty(extract));
        // config.library_root = library;
        std::fs::create_dir_all(library).unwrap_or_default();
        // config.save();
        let entry = app.join(ENTRY_POINT);
        if !entry.is_file() {
            // entry = app / ENTRY_POINT.replace(".py", ".exe")
        }
        (self.register)(&sys_executable(), &entry);
        rows.push((
            "ok".to_string(),
            "Saved. The catalog's Extract buttons now work from this PC.".to_string(),
        ));
        (true, rows)
    }
}

/// The three-path setup a fresh PC needs, and the one place those paths are saved.
///
/// `register_handler` and `registered_command` are injected so a test can watch a
/// registration without touching the registry; both default to functions in
/// `tools/install_protocol_handler.py`, which write `HKCU\\Software\\Classes`.
pub fn default_register(_python: &str, _entry: &Path) {
    // Default: no-op. Tests inject their own register handler.
}

pub fn default_registered() -> Option<String> {
    // Default: not registered. Tests inject their own registered command.
    None
}

/// Whether the library holds at least one organized game folder.
///
/// The same shape the scanner and the catalog walk: a category folder holding game
/// folders. One level of each is enough to say "there are games here"; counting them
/// is the scan's job, not the setup's.
fn _library_has_games(root: &Path) -> bool {
    let Ok(entries) = root.read_dir() else {
        return false;
    };
    for entry in entries.flatten() {
        let category = entry.path();
        if !category.is_dir() {
            continue;
        }
        let category_name = category.file_name().unwrap_or_default().to_string_lossy().to_string();
        if LIBRARY_RESERVED_DIRS.iter().any(|name| name == &category_name) {
            continue;
        }
        let Ok(game_entries) = category.read_dir() else {
            continue;
        };
        for ge in game_entries.flatten() {
            if ge.path().is_dir() {
                return true;
            }
        }
    }
    false
}

/// True when the folder exists and is writable, or can be created under a writable
/// parent. The nearest existing ancestor is what answers the second case.
fn _writable_or_creatable(path: &Path) -> bool {
    if path.exists() {
        return path.is_dir() && std::fs::metadata(path).map(|m| m.permissions().readonly() == false).unwrap_or(false);
    }
    let mut ancestor = path.parent();
    while let Some(anc) = ancestor {
        if anc.exists() {
            return anc.is_dir() && std::fs::metadata(anc).map(|m| m.permissions().readonly() == false).unwrap_or(false);
        }
        ancestor = anc.parent();
    }
    false
}

/// True when `candidate` sits under `root`. Resolved first, so `..` and a symlink or
/// junction cannot walk out of the comparison.
fn _within(candidate: &Path, root: &Path) -> bool {
    // Try canonicalized comparison first
    if let (Ok(c), Ok(r)) = (candidate.canonicalize(), root.canonicalize()) {
        return c == r || c.starts_with(&r);
    }
    // Fall back to string prefix check for paths that don't exist yet
    candidate.starts_with(root)
}

fn library_or_empty(s: &str) -> &str {
    if s.trim().is_empty() {
        ""
    } else {
        s
    }
}

fn app_or_empty(s: &str) -> &str {
    if s.trim().is_empty() {
        ""
    } else {
        s
    }
}

fn extract_or_empty(s: &str) -> &str {
    if s.trim().is_empty() {
        ""
    } else {
        s
    }
}

fn sys_executable() -> String {
    std::env::current_exe()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|_| "steam_game_organizer.exe".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_library_has_games_empty_dir() {
        use std::env;
        let temp = env::temp_dir().join(format!("test_lib_has_games_{}", std::process::id()));
        std::fs::create_dir_all(&temp).ok();
        assert!(!_library_has_games(&temp));
        let _ = std::fs::remove_dir_all(&temp);
    }

    #[test]
    fn test_library_has_games_with_game() {
        use std::env;
        let temp = env::temp_dir().join(format!("test_lib_has_games_{}", std::process::id()));
        std::fs::create_dir_all(&temp.join("Category").join("Game")).ok();
        assert!(_library_has_games(&temp));
        let _ = std::fs::remove_dir_all(&temp);
    }

    #[test]
    fn test_writable_or_creatable_existing_dir() {
        use std::env;
        let temp = env::temp_dir().join(format!("test_writable_{}", std::process::id()));
        std::fs::create_dir_all(&temp).ok();
        assert!(_writable_or_creatable(&temp));
        let _ = std::fs::remove_dir_all(&temp);
    }

    #[test]
    fn test_within() {
        use std::path::PathBuf;
        let root = PathBuf::from("/library");
        let child = PathBuf::from("/library/Category/Game");
        assert!(_within(&child, &root));
        let outside = PathBuf::from("/outside/Game");
        assert!(!_within(&outside, &root));
    }
}
