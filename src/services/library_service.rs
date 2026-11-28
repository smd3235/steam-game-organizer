//! Library service: audits the organized library, cleans up temp artefacts, collapses duplicate archives.
//!
//! Stub conversion of `services/library_service.py`. Complex methods (`audit` with parallel artwork
//! downloads, `convert_pending_archives`, `enforce_single_archive`) are stubs returning safe defaults.
//! They will be filled in incrementally as the Rust port progresses.
//!
//! 2026-11-25: Stub conversion from `services/library_service.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use regex::Regex;
use walkdir::WalkDir;

use crate::core::constants::{
    ARCHIVE_EXTENSIONS, LIBRARY_RESERVED_DIRS, LOCK_MARKER, TEMP_DIR_PREFIX, TEMP_FILE_TAG,
};
use crate::core::debug::audit;
use crate::core::library_utils::{game_folder_is_prunable, is_app_folder};
use crate::core::models::{ConversionResult, GameArchive};
use crate::core::naming_utils::safe_name;
use crate::core::path_safety::{is_within, DeletionGuard};
use crate::core::treewalk::is_link;
use crate::services::organizer_service::{CancelContext, OrganizerService};

lazy_static::lazy_static! {
    static ref APPID_PATTERN: Regex = Regex::new(r"app/(\d+)").unwrap();
    static ref TEMP_FILE_OWNER_RE: Regex = Regex::new(r"\.(\d+)\.").unwrap();
}

const OWN_TEMP_DIRS: &[&str] = &[".organizer-repack-", ".organizer-unzip-"];
const OWN_TEMP_FILES: &[&str] = &[".organizer-temp"];
const OWN_TEMP_FILE_PREFIX: &str = ".organizer-zip-";
const SYNC_FILE_PATTERNS: &[&str] = &[
    "*sync-conflict-*",
    "*.syncthing.*.tmp",
    ".syncthing.*",
    "*.sync-conflict-*.*",
    "~syncthing~*.tmp",
];
const SYNC_NEVER_TOUCH: &[&str] = &[".stfolder", ".stversions", ".stignore"];
const OWN_TEMP_GRACE_SECONDS: u64 = 10 * 60;

pub mod audit_outcome {
    pub const NO_APPID: &str = "no_appid";
    pub const WRITTEN: &str = "written";
    pub const UP_TO_DATE: &str = "up_to_date";
    pub const UNAVAILABLE: &str = "unavailable";
    pub const WOULD_REFRESH: &str = "would_refresh";
    pub const SKIP_ARTWORK: &str = "skip_artwork";
}

pub struct LibraryService {
    logger: Arc<dyn Fn(&str, &str) + Send + Sync>,
    _config_dir: Option<PathBuf>,
}

impl LibraryService {
    pub fn new(logger: Arc<dyn Fn(&str, &str) + Send + Sync>, config_dir: Option<PathBuf>) -> Self {
        LibraryService {
            logger,
            _config_dir: config_dir,
        }
    }

    fn _config_dir_for(&self, library_root: &Path) -> PathBuf {
        if let Some(cd) = &self._config_dir {
            return cd.clone();
        }
        library_root.parent().unwrap_or(library_root).join("config")
    }

    fn _load_scan_state(&self, library_root: &Path) -> Option<HashMap<String, u64>> {
        let config_dir = self._config_dir_for(library_root);
        let state_file = config_dir.join("scan-state.json");
        if !state_file.is_file() {
            return None;
        }
        match fs::read_to_string(&state_file) {
            Ok(text) => match serde_json::from_str::<serde_json::Value>(&text) {
                Ok(data) => data
                    .get("folder_mtimes")
                    .and_then(|v| v.as_object())
                    .map(|obj| {
                        obj.iter()
                            .filter_map(|(k, v)| v.as_u64().map(|u| (k.clone(), u)))
                            .collect()
                    }),
                Err(_) => None,
            },
            Err(_) => None,
        }
    }

    fn _save_scan_state(&self, library_root: &Path, folder_mtimes: &HashMap<String, u64>) {
        let config_dir = self._config_dir_for(library_root);
        let state_file = config_dir.join("scan-state.json");
        let mut existing: serde_json::Value = serde_json::Value::Null;
        if state_file.is_file() {
            if let Ok(text) = fs::read_to_string(&state_file) {
                if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&text) {
                    existing = parsed;
                }
            }
        }
        if !existing.is_object() {
            existing = serde_json::json!({});
        }
        if let Some(obj) = existing.as_object_mut() {
            obj.insert(
                "folder_mtimes".to_string(),
                serde_json::to_value(folder_mtimes).unwrap(),
            );
            obj.insert(
                "recorded_at".to_string(),
                serde_json::to_value(
                    SystemTime::now()
                        .duration_since(UNIX_EPOCH)
                        .unwrap_or_default()
                        .as_secs(),
                )
                .unwrap(),
            );
        }
        if let Err(e) = fs::create_dir_all(&config_dir) {
            (self.logger)(
                "LIBRARY",
                &format!(
                    "SCAN_STATE_SAVE_FAILED library_root=[{}] error=cannot create config dir: {}",
                    library_root.display(),
                    e
                ),
            );
            return;
        }
        match fs::write(
            &state_file,
            serde_json::to_string_pretty(&existing).unwrap(),
        ) {
            Ok(()) => {}
            Err(e) => {
                (self.logger)(
                    "LIBRARY",
                    &format!(
                        "SCAN_STATE_WRITE_FAILED library_root=[{}] state_file=[{}] error={}",
                        library_root.display(),
                        state_file.display(),
                        e
                    ),
                );
            }
        }
    }

    fn _get_folder_mtime(&self, folder: &Path) -> u64 {
        if !folder.is_dir() {
            return 0;
        }
        let mut max_mtime = 0u64;
        match fs::read_dir(folder) {
            Ok(entries) => {
                for item in entries.flatten() {
                    let path = item.path();
                    if path.is_file() {
                        let name = path
                            .file_name()
                            .unwrap_or_default()
                            .to_string_lossy()
                            .to_lowercase();
                        let _ext = path.extension().map_or("", |e| e.to_str().unwrap_or(""));
                        if name.ends_with(".zip")
                            || name.ends_with(".rar")
                            || name.ends_with(".7z")
                            || name == ".game-info.json"
                            || name.starts_with("open steam page")
                            || name.ends_with(".jpg")
                            || name.ends_with(".jpeg")
                            || name.ends_with(".png")
                            || name.ends_with(".webp")
                            || name.ends_with(".gif")
                            || name.ends_with(".bmp")
                        {
                            if let Ok(meta) = path.metadata() {
                                if let Ok(mtime) = meta.modified() {
                                    let ns = mtime
                                        .duration_since(UNIX_EPOCH)
                                        .unwrap_or_default()
                                        .as_nanos()
                                        as u64;
                                    if ns > max_mtime {
                                        max_mtime = ns;
                                    }
                                }
                            }
                        }
                    }
                }
            }
            Err(_) => return 0,
        }
        max_mtime
    }

    fn _pending_archive_in(&self, game_dir: &Path) -> Option<PathBuf> {
        match fs::read_dir(game_dir) {
            Ok(entries) => {
                let mut items: Vec<PathBuf> = entries
                    .filter_map(|e| e.ok().map(|i| i.path()))
                    .filter(|p| p.is_file())
                    .collect();
                items.sort();
                items.into_iter().find(|p| {
                    let ext = p
                        .extension()
                        .and_then(|e| e.to_str())
                        .unwrap_or("")
                        .to_lowercase();
                    ext == "zip" || ext == "rar"
                })
            }
            Err(_) => None,
        }
    }

    pub fn pending_candidates(
        &self,
        library_root: &Path,
    ) -> Vec<(PathBuf, PathBuf, u64, String, String)> {
        let library_root = match library_root.canonicalize() {
            Ok(r) => r,
            Err(_) => return Vec::new(),
        };
        if !library_root.is_dir() {
            return Vec::new();
        }
        let mut found: Vec<(PathBuf, PathBuf, u64, String, String)> = Vec::new();
        if let Ok(entries) = fs::read_dir(&library_root) {
            for category_entry in entries.flatten() {
                let category_dir = match category_entry.path() {
                    p if p.is_dir() => p,
                    _ => continue,
                };
                let name = category_dir
                    .file_name()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .to_string();
                if LIBRARY_RESERVED_DIRS.contains(&name.as_str()) || is_app_folder(&category_dir) {
                    continue;
                }
                if let Ok(game_entries) = fs::read_dir(&category_dir) {
                    for game_entry in game_entries.flatten() {
                        let game_dir = game_entry.path();
                        if !game_dir.is_dir() {
                            continue;
                        }
                        let pending = match self._pending_archive_in(&game_dir) {
                            Some(p) => p,
                            None => continue,
                        };
                        let size = pending.metadata().map_or(0, |m| m.len());
                        let metadata = self._read_metadata(&game_dir);
                        let appid = self._find_appid(&game_dir, &metadata);
                        let name = match metadata.get("name").and_then(|v| v.as_str()) {
                            Some(n) => n.to_string(),
                            None => game_dir
                                .file_stem()
                                .unwrap_or_default()
                                .to_string_lossy()
                                .split(" - ")
                                .next()
                                .unwrap_or("")
                                .to_string(),
                        };
                        found.push((game_dir, pending, size, appid, name));
                    }
                }
            }
        }
        found.sort_by_key(|a| a.2);
        found
    }

    #[allow(clippy::too_many_arguments)]
    pub fn convert_pending_archives(
        &self,
        library_root: &Path,
        organizer_service: &OrganizerService,
        ctx: Option<&CancelContext>,
        journal: Option<&mut Vec<(PathBuf, PathBuf)>>,
        on_progress: Option<&dyn Fn(&str)>,
        unlocker: Option<&dyn Fn(&Path, Option<&CancelContext>) -> bool>,
        _outcomes: Option<&mut Vec<(PathBuf, ConversionResult)>>,
        zip_password: &str,
        _work: Option<Vec<(PathBuf, PathBuf, u32, String)>>,
    ) -> u32 {
        let candidates = self.pending_candidates(library_root);
        let mut converted = 0u32;
        let mut journal = journal;

        audit(
            "batch_convert_start",
            library_root.to_string_lossy().as_ref(),
            "started",
            &format!("candidates={}", candidates.len()),
        );

        for (game_dir, archive_path, _size, _appid, _name) in candidates {
            // Skip if conversion is already in progress
            if self._conversion_in_progress(&game_dir) {
                continue;
            }

            // Check if unlocker says we can proceed
            if let Some(ref unlock) = unlocker {
                if !unlock(&archive_path, ctx) {
                    continue;
                }
            }

            // Build a minimal GameArchive for the repack call
            let archive = GameArchive {
                path: archive_path.clone(),
                ..Default::default()
            };

            let result = organizer_service._repack_with_official_name(
                &archive,
                ctx,
                None,
                zip_password,
                Some(library_root),
            );

            audit(
                "archive_repack",
                &archive_path.to_string_lossy(),
                if result != archive_path {
                    "success"
                } else {
                    "skipped"
                },
                if result != archive_path {
                    "converted"
                } else {
                    "not_applicable"
                },
            );

            // Call on_progress directly
            if let Some(f) = on_progress {
                let name = archive_path
                    .file_name()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .to_string();
                f(&name);
            }

            // Outcome: converted or skipped (tracked via journal if provided)

            // Journal the move
            if let Some(journal) = journal.as_mut() {
                if result != archive_path {
                    journal.push((archive_path.clone(), result));
                }
            }

            converted += 1;
        }

        audit(
            "batch_convert_end",
            library_root.to_string_lossy().as_ref(),
            "completed",
            &format!("converted={}", converted),
        );

        converted
    }

    pub fn apply_outcomes(_archives: &[GameArchive], _outcomes: &[(PathBuf, ConversionResult)]) {
        // STUB: no-op.
    }

    fn _size_on_disk(&self, path: &Path) -> u64 {
        let mut total = 0u64;
        if path.is_file() {
            return path.metadata().map_or(0, |m| m.len());
        }
        for entry in WalkDir::new(path).into_iter().filter_map(|e| e.ok()) {
            if entry.file_type().is_file() {
                total += entry.metadata().map_or(0, |m| m.len());
            }
        }
        total
    }

    fn _is_own_temp(&self, path: &Path) -> bool {
        let name = path
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .to_string();
        if path.is_dir() {
            return OWN_TEMP_DIRS.iter().any(|prefix| name.starts_with(*prefix));
        }
        if name.starts_with(OWN_TEMP_FILE_PREFIX) {
            return true;
        }
        OWN_TEMP_FILES.iter().any(|tag| name.contains(*tag))
    }

    fn _temp_owner(&self, path: &Path) -> Option<(u32, f64)> {
        if !path.is_dir() {
            return None;
        }
        let marker = path.join(LOCK_MARKER);
        if !marker.is_file() {
            return None;
        }
        match fs::read_to_string(&marker) {
            Ok(text) => {
                let parts: Vec<&str> = text.split_whitespace().collect();
                if parts.len() >= 2 {
                    if let (Ok(pid), Ok(started)) =
                        (parts[0].parse::<u32>(), parts[1].parse::<f64>())
                    {
                        return Some((pid, started));
                    }
                }
                None
            }
            Err(_) => None,
        }
    }

    fn _pid_alive(&self, pid: u32) -> bool {
        match std::process::Command::new("taskkill")
            .args([
                "/PID",
                &pid.to_string(),
                "/FI",
                &format!("PID eq {}", pid),
                "/FO",
                "CSV",
                "/NH",
            ])
            .output()
        {
            Ok(output) => {
                let stdout = String::from_utf8_lossy(&output.stdout);
                !stdout.contains(&format!(",{}", pid))
            }
            Err(_) => false,
        }
    }

    fn _temp_is_stale(&self, path: &Path) -> bool {
        if !path.is_dir() {
            return self._temp_file_is_stale(path);
        }
        match self._temp_owner(path) {
            None => true,
            Some((pid, started)) => {
                if self._pid_alive(pid) {
                    return false;
                }
                (SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_secs_f64()
                    - started)
                    > OWN_TEMP_GRACE_SECONDS as f64
            }
        }
    }

    fn _temp_file_is_stale(&self, path: &Path) -> bool {
        let name = path
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .to_string();
        if let Some(caps) = TEMP_FILE_OWNER_RE.captures(&name) {
            if let Ok(pid) = caps.get(1).unwrap().as_str().parse::<u32>() {
                if self._pid_alive(pid) {
                    return false;
                }
                return match path.metadata() {
                    Ok(meta) => {
                        let mtime = meta.modified().unwrap_or(UNIX_EPOCH);
                        let age = SystemTime::now()
                            .duration_since(UNIX_EPOCH)
                            .unwrap_or_default()
                            .as_secs_f64()
                            - mtime
                                .duration_since(UNIX_EPOCH)
                                .unwrap_or_default()
                                .as_secs_f64();
                        age > OWN_TEMP_GRACE_SECONDS as f64
                    }
                    Err(_) => false,
                };
            }
        }
        true
    }

    fn _conversion_in_progress(&self, game_dir: &Path) -> bool {
        match fs::read_dir(game_dir) {
            Ok(entries) => {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if path.is_dir() {
                        if let Some(name) = path.file_name() {
                            if name.to_string_lossy().starts_with(TEMP_DIR_PREFIX)
                                && !self._temp_is_stale(&path)
                            {
                                return true;
                            }
                        }
                    } else if path.is_file() {
                        if let Some(name) = path.file_name() {
                            if name.to_string_lossy().contains(TEMP_FILE_TAG) {
                                return true;
                            }
                        }
                    }
                }
                false
            }
            Err(_) => false,
        }
    }

    fn _is_sync_leftover(&self, path: &Path) -> bool {
        let name = path
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .to_string();
        if SYNC_NEVER_TOUCH.iter().any(|s| name.starts_with(s)) {
            return false;
        }
        SYNC_FILE_PATTERNS
            .iter()
            .any(|p| name.contains(&p.replace(['*', '?'], "")))
    }

    pub fn cleanup_leftovers(
        &self,
        library_root: &Path,
        _ctx: Option<&CancelContext>,
        _grace_seconds: u64,
    ) -> HashMap<String, u64> {
        let library_root = match library_root.canonicalize() {
            Ok(r) => r,
            Err(_) => return HashMap::new(),
        };
        if !library_root.is_dir() {
            return HashMap::new();
        }
        let library_root_str = library_root.to_str().unwrap_or("");
        let _guard = match DeletionGuard::new(&[library_root_str]) {
            Ok(g) => g,
            Err(_) => return HashMap::new(),
        };
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs_f64();
        let mut removed = 0u64;
        let mut freed = 0u64;
        let mut skipped_young = 0u64;
        let mut skipped_link = 0u64;
        for entry in WalkDir::new(&library_root)
            .into_iter()
            .filter_map(|e| e.ok())
        {
            let here = entry.path();
            if entry.file_type().is_symlink() {
                skipped_link += 1;
                continue;
            }
            let _name = here
                .file_name()
                .unwrap_or_default()
                .to_string_lossy()
                .to_string();
            let own = self._is_own_temp(here);
            let sync = if !own {
                self._is_sync_leftover(here)
            } else {
                false
            };
            if !own && !sync {
                continue;
            }
            if own && !self._temp_is_stale(here) {
                skipped_young += 1;
                continue;
            }
            let age = now
                - here
                    .metadata()
                    .map_or(UNIX_EPOCH, |m| m.modified().unwrap_or(UNIX_EPOCH))
                    .duration_since(UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_secs_f64();
            if !own && age < _grace_seconds as f64 {
                skipped_young += 1;
                continue;
            }
            let size = self._size_on_disk(here);
            if !is_within(here, &library_root) {
                (self.logger)(
                    "LIBRARY",
                    &format!(
                        "LEFTOVER_REFUSED path=[{}] reason=[outside the library]",
                        here.display()
                    ),
                );
                continue;
            }
            let result = if here.is_dir() {
                fs::remove_dir_all(here)
            } else {
                fs::remove_file(here)
            };
            if let Err(exc) = result {
                (self.logger)(
                    "LIBRARY",
                    &format!(
                        "LEFTOVER_REMOVE_FAILED path=[{}] error={}",
                        here.display(),
                        exc
                    ),
                );
                continue;
            }
            removed += 1;
            freed += size;
            (self.logger)(
                "LIBRARY",
                &format!(
                    "LEFTOVER_REMOVED path=[{}] kind=[{}] bytes={}",
                    here.display(),
                    if own { "organizer" } else { "syncthing" },
                    size
                ),
            );
        }
        let empty = self._sweep_empty_categories(&library_root);
        removed += empty.get("empty_categories_removed").copied().unwrap_or(0);
        let mut summary = HashMap::new();
        summary.insert("removed".to_string(), removed);
        summary.insert("bytes_freed".to_string(), freed);
        summary.insert("deferred_syncthing".to_string(), skipped_young);
        summary.insert("skipped_links".to_string(), skipped_link);
        summary
    }

    fn _move_to_archive(&self, folder: &Path, library_root: &Path) -> Result<PathBuf, String> {
        let archive_dir = Path::new(library_root)
            .canonicalize()
            .unwrap_or_else(|_| library_root.to_path_buf())
            .join("Archive");
        fs::create_dir_all(&archive_dir).map_err(|e| format!(
            "cannot create archive dir {}: {}", archive_dir.display(), e
        ))?;
        let mut target = archive_dir.join(folder.file_name().unwrap_or_default());
        let mut n = 2;
        while target.exists() {
            target = archive_dir.join(format!(
                "{} ({})",
                folder.file_name().unwrap_or_default().to_string_lossy(),
                n
            ));
            n += 1;
        }
        fs::rename(folder, &target).map_err(|e| format!(
            "cannot move {} to {}: {}", folder.display(), target.display(), e
        ))?;
        Ok(target)
    }

    fn _sweep_empty_categories(&self, library_root: &Path) -> HashMap<String, u64> {
        let mut removed = 0u64;
        if let Ok(entries) = fs::read_dir(library_root) {
            for category_entry in entries.flatten() {
                let category_dir = match category_entry.path() {
                    p if p.is_dir() => p,
                    _ => continue,
                };
                let name = category_dir
                    .file_name()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .to_string();
                if LIBRARY_RESERVED_DIRS.contains(&name.as_str()) || is_app_folder(&category_dir) {
                    continue;
                }
                if is_link(&category_dir) {
                    continue;
                }
                if self._is_own_temp(&category_dir) && !self._temp_is_stale(&category_dir) {
                    continue;
                }
                let root_has_archive = fs::read_dir(&category_dir)
                    .map(|e| {
                        e.flatten().any(|i| {
                            i.path().is_file()
                                && ARCHIVE_EXTENSIONS.contains(
                                    &i.path()
                                        .extension()
                                        .map_or("", |e| e.to_str().unwrap_or(""))
                                        .to_lowercase()
                                        .as_str(),
                                )
                        })
                    })
                    .unwrap_or(false);
                let mut _pruned = 0u64;
                if let Ok(game_entries) = fs::read_dir(&category_dir) {
                    for game_entry in game_entries.flatten() {
                        let game_dir = game_entry.path();
                        if !game_dir.is_dir() {
                            continue;
                        }
                        let has_archive = fs::read_dir(&game_dir)
                            .map(|e| {
                                e.flatten().any(|i| {
                                    i.path().is_file()
                                        && ARCHIVE_EXTENSIONS.contains(
                                            &i.path()
                                                .extension()
                                                .map_or("", |e| e.to_str().unwrap_or(""))
                                                .to_lowercase()
                                                .as_str(),
                                        )
                                })
                            })
                            .unwrap_or(false);
                        if has_archive {
                            continue;
                        }
                        if game_folder_is_prunable(&game_dir) {
                            match self._move_to_archive(&game_dir, library_root) {
                                Ok(target) => {
                                    _pruned += 1;
                                    (self.logger)(
                                        "LIBRARY",
                                        &format!(
                                            "EMPTY_GAME_FOLDER_ARCHIVED path=[{}] destination=[{}]",
                                            game_dir.display(),
                                            target.display()
                                        ),
                                    );
                                }
                                Err(e) => {
                                    (self.logger)(
                                        "LIBRARY",
                                        &format!(
                                            "EMPTY_GAME_FOLDER_ARCHIVE_FAILED path=[{}] error={}",
                                            game_dir.display(),
                                            e
                                        ),
                                    );
                                }
                            }
                        }
                    }
                }
                if !root_has_archive && fs::read_dir(&category_dir).map_or(true, |e| e.count() == 0)
                {
                    match self._move_to_archive(&category_dir, library_root) {
                        Ok(target) => {
                            removed += 1;
                            (self.logger)(
                                "LIBRARY",
                                &format!(
                                    "EMPTY_CATEGORY_ARCHIVED path=[{}] destination=[{}]",
                                    category_dir.display(),
                                    target.display()
                                ),
                            );
                        }
                        Err(e) => {
                            (self.logger)(
                                "LIBRARY",
                                &format!(
                                    "EMPTY_CATEGORY_ARCHIVE_FAILED path=[{}] error={}",
                                    category_dir.display(),
                                    e
                                ),
                            );
                        }
                    }
                }
            }
        }
        let mut summary = HashMap::new();
        summary.insert("empty_categories_removed".to_string(), removed);
        summary
    }

    pub fn audit_empty_game_folders(
        &self,
        library_root: &Path,
    ) -> Vec<(String, PathBuf, bool, Vec<String>)> {
        let library_root = match library_root.canonicalize() {
            Ok(r) => r,
            Err(_) => return Vec::new(),
        };
        if !library_root.is_dir() {
            return Vec::new();
        }
        let mut found: Vec<(String, PathBuf, bool, Vec<String>)> = Vec::new();
        if let Ok(entries) = fs::read_dir(&library_root) {
            for category_entry in entries.flatten() {
                let category_dir = match category_entry.path() {
                    p if p.is_dir() => p,
                    _ => continue,
                };
                if is_link(&category_dir) {
                    continue;
                }
                if let Ok(game_entries) = fs::read_dir(&category_dir) {
                    for game_entry in game_entries.flatten() {
                        let game_dir = game_entry.path();
                        if !game_dir.is_dir() {
                            continue;
                        }
                        let has_archive = fs::read_dir(&game_dir)
                            .map(|e| {
                                e.flatten().any(|i| {
                                    i.path().is_file()
                                        && ARCHIVE_EXTENSIONS.contains(
                                            &i.path()
                                                .extension()
                                                .map_or("", |e| e.to_str().unwrap_or(""))
                                                .to_lowercase()
                                                .as_str(),
                                        )
                                })
                            })
                            .unwrap_or(false);
                        if has_archive {
                            continue;
                        }
                        let files: Vec<String> = fs::read_dir(&game_dir)
                            .map(|e| {
                                e.flatten()
                                    .filter_map(|i| {
                                        i.path()
                                            .file_name()
                                            .map(|n| n.to_string_lossy().to_string())
                                    })
                                    .collect()
                            })
                            .unwrap_or_default();
                        let game_dir_clone = game_dir.clone();
                        found.push((
                            category_dir
                                .file_name()
                                .unwrap_or_default()
                                .to_string_lossy()
                                .to_string(),
                            game_dir,
                            game_folder_is_prunable(&game_dir_clone),
                            files,
                        ));
                    }
                }
            }
        }
        found
    }

    // STUB: audit() with parallel artwork downloads depends on artwork_service (not yet converted).
    #[allow(clippy::too_many_arguments)]
    pub fn audit(
        &self,
        _library_root: &Path,
        _artwork_service: &ArtworkServiceStub,
        _organizer_service: &OrganizerService,
        _ctx: Option<&CancelContext>,
        _on_progress: Option<&dyn Fn(&str)>,
        _preview_only: bool,
        _download_artwork: bool,
    ) -> HashMap<String, u64> {
        let mut summary = HashMap::new();
        summary.insert("checked".to_string(), 0);
        summary.insert("refreshed".to_string(), 0);
        summary.insert("no_artwork".to_string(), 0);
        summary.insert("would_refresh".to_string(), 0);
        summary.insert("skipped_unchanged".to_string(), 0);
        summary
    }

    fn _audit_text(&self, outcome: &str) -> String {
        let base = outcome.split(':').next().unwrap_or(outcome);
        let detail = outcome
            .split_once(':')
            .map(|x| x.1)
            .map(|s| s.trim())
            .unwrap_or("");
        let text = match base {
            audit_outcome::NO_APPID => "no Steam AppID — nothing to refresh",
            audit_outcome::WRITTEN => "artwork refreshed",
            audit_outcome::UP_TO_DATE => "already up to date",
            audit_outcome::UNAVAILABLE => "no artwork available",
            audit_outcome::WOULD_REFRESH => "would refresh artwork",
            audit_outcome::SKIP_ARTWORK => "artwork download skipped",
            _ => base,
        };
        if detail.is_empty() {
            text.to_string()
        } else {
            format!("{} ({})", text, detail)
        }
    }

    fn _read_metadata(&self, game_dir: &Path) -> serde_json::Value {
        let path = game_dir.join(".game-info.json");
        if !path.is_file() {
            return serde_json::Value::Null;
        }
        match fs::read_to_string(&path) {
            Ok(text) => serde_json::from_str(&text).unwrap_or(serde_json::Value::Null),
            Err(_) => serde_json::Value::Null,
        }
    }

    fn _asset_prefix(&self, game_dir: &Path, metadata: Option<&serde_json::Value>) -> String {
        let name = metadata.and_then(|m| m.get("name").and_then(|v| v.as_str()));
        if let Some(name) = name {
            if !name.is_empty() {
                return safe_name(name);
            }
        }
        let folder_name = game_dir
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .to_string();
        let cleaned = Regex::new(r"\s*-\s*(?:\d{4}-\d{2}-\d{2}|Unknown Release Date)$")
            .unwrap()
            .replace_all(&folder_name, "")
            .to_string();
        let trimmed = cleaned.trim();
        if trimmed.is_empty() {
            folder_name
        } else {
            trimmed.to_string()
        }
    }

    fn _find_appid(&self, game_dir: &Path, metadata: &serde_json::Value) -> String {
        let appid = metadata
            .get("appid")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        if !appid.is_empty() && appid.chars().all(|c: char| c.is_ascii_digit()) {
            return appid;
        }
        for ext in &["desktop", "url", "html"] {
            if let Ok(entries) = fs::read_dir(game_dir) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if path.extension().is_some_and(|e| e == *ext) {
                        if let Ok(text) = fs::read_to_string(&path) {
                            if let Some(caps) = APPID_PATTERN.captures(&text) {
                                return caps.get(1).map_or("", |m| m.as_str()).to_string();
                            }
                        }
                    }
                }
            }
        }
        String::new()
    }

    pub fn enforce_single_archive(
        &self,
        _library_root: &Path,
        _organizer_service: &OrganizerService,
        _ctx: Option<&CancelContext>,
        _journal: Option<&mut Vec<(PathBuf, PathBuf)>>,
    ) -> u32 {
        // STUB: returns 0 (nothing archived). Real implementation coming incrementally.
        0
    }
}

/// Stub for artwork_service until it is converted to Rust.
pub struct ArtworkServiceStub;

impl ArtworkServiceStub {
    pub fn new() -> Self {
        ArtworkServiceStub
    }
}

impl Default for ArtworkServiceStub {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dummy_logger(_: &str, _: &str) {}

    #[test]
    fn test_library_service_new() {
        let service = LibraryService::new(Arc::new(dummy_logger), None);
        assert!(service
            ._config_dir_for(Path::new("/lib"))
            .ends_with("config"));
    }

    #[test]
    fn test_library_service_is_own_temp_dir() {
        let service = LibraryService::new(Arc::new(dummy_logger), None);
        let temp = std::env::temp_dir().join(format!("test_is_own_temp_{}", std::process::id()));
        let _ = fs::create_dir_all(temp.join(".organizer-repack-abc"));
        assert!(service._is_own_temp(&temp.join(".organizer-repack-abc")));
        assert!(!service._is_own_temp(&temp.join("Game.zip")));
        let _ = fs::remove_dir_all(&temp);
    }

    #[test]
    fn test_library_service_pending_candidates_empty() {
        let service = LibraryService::new(Arc::new(dummy_logger), None);
        let candidates = service.pending_candidates(Path::new("/nonexistent"));
        assert!(candidates.is_empty());
    }

    #[test]
    fn test_library_service_cleanup_leftovers_empty() {
        let service = LibraryService::new(Arc::new(dummy_logger), None);
        // Just verify the function doesn't panic on nonexistent paths
        let _summary = service.cleanup_leftovers(Path::new("/nonexistent"), None, 6 * 3600);
    }

    #[test]
    fn test_library_service_audit_stub() {
        let service = LibraryService::new(Arc::new(dummy_logger), None);
        let organizer = OrganizerService::new(Arc::new(dummy_logger), true);
        let artwork = ArtworkServiceStub::new();
        let summary = service.audit(
            Path::new("/nonexistent"),
            &artwork,
            &organizer,
            None,
            None,
            false,
            true,
        );
        assert_eq!(summary.get("checked"), Some(&0));
    }

    #[test]
    fn test_library_service_enforce_single_archive_stub() {
        let service = LibraryService::new(Arc::new(dummy_logger), None);
        let organizer = OrganizerService::new(Arc::new(dummy_logger), true);
        let count = service.enforce_single_archive(Path::new("/lib"), &organizer, None, None);
        assert_eq!(count, 0);
    }

    #[test]
    fn test_library_service_audit_text() {
        let service = LibraryService::new(Arc::new(dummy_logger), None);
        assert_eq!(
            service._audit_text("no_appid"),
            "no Steam AppID — nothing to refresh"
        );
        assert_eq!(service._audit_text("written"), "artwork refreshed");
    }
}
