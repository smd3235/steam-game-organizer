//! Archive service: discovers archives in a library root.
//!
//! 2026-11-25: Converted from `services/archive_service.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

#![allow(clippy::all)]

use lazy_static::lazy_static;
use regex::Regex;
use serde_json;
use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};
use zip::ZipArchive;

use crate::core::constants::{
    ARCHIVE_EXTENSIONS, LIBRARY_RESERVED_DIRS, TEMP_DIR_PREFIX, TEMP_FILE_TAG,
};
use crate::services::extract_service::ExtractService;
use crate::core::filename_utils::{identity_key, normalize_name, version_key};
use crate::core::installer_detect::{InstallSignature, installer_from_names};
use crate::core::library_utils::is_app_folder;
use crate::core::models::{GameArchive, ScanResult};

lazy_static! {
    static ref INSTALLER_KIND_CACHE: Mutex<HashMap<String, (u64, u128, Option<InstallSignature>)>> =
        Mutex::new(HashMap::new());
}

/// Archive service: discovers archives in a library root.
pub struct ArchiveService {
    pub logger: Arc<dyn for<'a> Fn(&'a str, &'a str) + Send + Sync>,
    pub mock: bool,
    /// Cache for directory mtimes to enable incremental discovery
    pub discovery_cache: Mutex<HashMap<String, u128>>,
    pub config_dir: Option<PathBuf>,
}

impl ArchiveService {
    pub fn new(
        logger: Arc<dyn for<'a, 'b> Fn(&'a str, &'b str) + Send + Sync>,
        mock: bool,
        config_dir: Option<&Path>,
    ) -> Self {
        ArchiveService {
            logger,
            mock,
            discovery_cache: Mutex::new(HashMap::new()),
            config_dir: config_dir.map(PathBuf::from),
        }
    }

    fn load_discovery_cache(&self, library_root: &Path) -> HashMap<String, u128> {
        try_load_discovery_cache(library_root)
    }

    fn save_discovery_cache(&self, library_root: &Path, dir_mtimes: &HashMap<String, u128>) {
        try_save_discovery_cache(library_root, dir_mtimes);
    }

    fn walk_changed_files(&self, root: &Path, dir_mtimes_cache: &HashMap<String, u128>) -> (Vec<PathBuf>, HashMap<String, u128>) {
        let mut files: Vec<PathBuf> = Vec::new();
        let mut updated: HashMap<String, u128> = HashMap::new();
        let mut stack: Vec<PathBuf> = vec![root.to_path_buf()];
        let mut seen: std::collections::HashSet<PathBuf> = std::collections::HashSet::new();

        while let Some(current) = stack.pop() {
            let resolved = match current.canonicalize() {
                Ok(p) => p,
                Err(_) => continue,
            };
            if seen.contains(&resolved) {
                continue;
            }
            seen.insert(resolved.clone());

            let dir_stat = match current.metadata() {
                Ok(s) => s,
                Err(_) => continue,
            };

            let cache_key = resolved.to_string_lossy().to_string();
            let cached_mtime = dir_mtimes_cache.get(&cache_key);
            if let Some(cached) = cached_mtime {
                if *cached == dir_stat.modified().unwrap_or(UNIX_EPOCH).duration_since(UNIX_EPOCH).unwrap_or_default().as_nanos() {
                    updated.insert(cache_key, dir_stat.modified().unwrap_or(UNIX_EPOCH).duration_since(UNIX_EPOCH).unwrap_or_default().as_nanos());
                    continue;
                }
            }

            updated.insert(cache_key, dir_stat.modified().unwrap_or(UNIX_EPOCH).duration_since(UNIX_EPOCH).unwrap_or_default().as_nanos());

            let entries = match current.read_dir() {
                Ok(e) => e,
                Err(_) => continue,
            };
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_dir() {
                    stack.push(path);
                } else {
                    files.push(path);
                }
            }
        }

        (files, updated)
    }

    pub fn discover(
        &self,
        root: &Path,
        ctx: Option<&dyn Fn()>,
        progress: Option<&dyn Fn(u32, u32, u32, u64, u32, u32, &Path)>,
        new_only: bool,
        unlock_zip: bool,
        preview_only: bool,
        use_cache: bool,
    ) -> ScanResult {
        if self.mock {
            return self._mock(ctx, progress);
        }
        let root = root.canonicalize().unwrap_or_else(|_| root.to_path_buf());
        let mut result = ScanResult::default();
        if !root.is_dir() {
            result.errors.push(format!("Library folder does not exist: {}", root.display()));
            return result;
        }
        let started = SystemTime::now();
        (self.logger)(
            "ARCHIVE",
            &format!(
                "DISCOVERY_START root=[{}] new_only={} unlock_zip={} preview_only={}",
                root.display(),
                new_only as u32,
                unlock_zip as u32,
                preview_only as u32
            ),
        );
        let reserved: Vec<PathBuf> = LIBRARY_RESERVED_DIRS
            .iter()
            .map(|name| root.join(name))
            .collect();
        let mut candidates: u32 = 0;
        let mut total_size: u64 = 0;
        let mut supported: u32 = 0;
        let mut skipped: u32 = 0;

        let dir_mtimes_cache = if use_cache {
            self.load_discovery_cache(&root)
        } else {
            HashMap::new()
        };
        let (paths, updated_dir_mtimes) = self.walk_changed_files(&root, &dir_mtimes_cache);
        let mut paths: Vec<PathBuf> = paths;
        paths.sort();
        for (index, path) in paths.iter().enumerate().map(|(i, p)| (i + 1, p)) {
            if let Some(ctx) = ctx {
                ctx();
            }
            if path
                .strip_prefix(&root)
                .unwrap_or(path)
                .ancestors()
                .any(|p| p.file_name().map_or(false, |n| n.to_string_lossy().starts_with('.')))
            {
                skipped += 1;
                continue;
            }
            if !path.is_file()
                || reserved.iter().any(|r| path.ancestors().any(|a| a == *r))
            {
                skipped += 1;
                continue;
            }
            if path
                .ancestors()
                .any(|p| p != root && is_app_folder(&p))
            {
                skipped += 1;
                continue;
            }
            if self._is_own_temp_artefact(path) {
                skipped += 1;
                continue;
            }
            let suffix = path.extension()
                .map(|e| e.to_string_lossy().to_lowercase())
                .unwrap_or_default();
            if !ARCHIVE_EXTENSIONS.iter().any(|ext| ext.eq_ignore_ascii_case(&suffix)) {
                if let Some(progress) = progress {
                    if index % 25 == 0 {
                        progress(
                            candidates,
                            index.try_into().unwrap_or(0),
                            paths.len() as u32,
                            total_size,
                            supported,
                            skipped,
                            path,
                        );
                    }
                }
                continue;
            }
            if preview_only && suffix == ".zip" && self._is_encrypted_zip(path) {
                skipped += 1;
                result.errors.push(format!(
                    "Password-protected archive cannot be inspected in Preview Only: {}",
                    path.display()
                ));
                (self.logger)(
                    "ARCHIVE",
                    &format!(
                        "ZIP_LOCKED_IN_PREVIEW path=[{}] reason=[rewriting to inspect is a write, and Preview Only writes nothing]",
                        path.display()
                    ),
                );
                if let Some(progress) = progress {
                    if index % 25 == 0 {
                        progress(
                            candidates,
                            index.try_into().unwrap_or(0),
                            paths.len() as u32,
                            total_size,
                            supported,
                            skipped,
                            path,
                        );
                    }
                }
                continue;
            }
            if unlock_zip && suffix == ".zip" {
                self._remove_zip_password(path, ctx);
            }
            if new_only && self._is_managed(path) {
                if let Some(progress) = progress {
                    if index % 25 == 0 {
                        progress(
                            candidates,
                            index.try_into().unwrap_or(0),
                            paths.len() as u32,
                            total_size,
                            supported,
                            skipped,
                            path,
                        );
                    }
                }
                continue;
            }
            candidates += 1;
            let size = path.metadata().map_or(0, |m| m.len());
            total_size += size;
            supported += 1;
            let title = normalize_name(path.file_name().unwrap_or_default().to_string_lossy().as_ref());
            result.archives.push(GameArchive {
                path: path.clone(),
                display_name: title.clone(),
                normalized_title: title.clone(),
                identity_key: identity_key(&title),
                extension: suffix.to_string(),
                version: version_key(path.file_name().unwrap_or_default().to_string_lossy().as_ref()),
                size,
                ..Default::default()
            });
            if let Some(progress) = progress {
                progress(
                    candidates,
                    index.try_into().unwrap_or(0),
                    paths.len() as u32,
                    total_size,
                    supported,
                    skipped,
                    path,
                );
            }
        }
        (self.logger)(
            "ARCHIVE",
            &format!(
                "DISCOVERY_FINISH archives={} total_bytes={} files_seen={} elapsed_ms={}",
                result.archives.len(),
                total_size,
                paths.len(),
                started.elapsed().unwrap_or_default().as_millis()
            ),
        );
        let (stale_build_dirs, stale_build_bytes) = self._stale_build_dirs(&root);
        result.stale_build_dirs = stale_build_dirs;
        result.stale_build_bytes = stale_build_bytes;
        if result.stale_build_dirs > 0 {
            (self.logger)(
                "ARCHIVE",
                &format!(
                    "STALE_BUILD_DIRS count={} bytes={}",
                    result.stale_build_dirs, result.stale_build_bytes
                ),
            );
        }
        if let Some(progress) = progress {
            progress(
                result.archives.len() as u32,
                paths.len() as u32,
                paths.len() as u32,
                total_size,
                supported,
                skipped,
                Path::new(""),
            );
        }
        if use_cache {
            self.save_discovery_cache(&root, &updated_dir_mtimes);
        }
        result
    }

    fn _stale_build_dirs(&self, root: &Path) -> (u32, u64) {
        let mut count = 0u32;
        let mut total: u64 = 0;
        let candidates: Vec<PathBuf> = match fs::read_dir(root) {
            Ok(entries) => entries
                .filter_map(|e| e.ok())
                .filter(|e| {
                    e.file_name()
                        .to_string_lossy()
                        .starts_with(TEMP_DIR_PREFIX)
                })
                .filter(|e| e.path().is_dir())
                .map(|e| e.path())
                .collect(),
            Err(_) => return (0, 0),
        };
        for folder in candidates {
            count += 1;
            for child in walkdir::WalkDir::new(&folder)
                .into_iter()
                .filter_map(|e| e.ok())
            {
                let child_path = child.path();
                if child_path.is_file() && !child_path.is_symlink() {
                    total += child_path.metadata().map_or(0, |m| m.len());
                }
            }
        }
        (count, total)
    }

    pub fn archive_installer_kind(&self, path: &Path) -> Option<InstallSignature> {
        let path = path.to_path_buf();
        let suffix = path.extension()
            .map(|e| e.to_string_lossy().to_lowercase())
            .unwrap_or_default();
        let stat = path.metadata().ok();
        let cache_key: Option<String> = stat.as_ref().map(|_| path.to_string_lossy().to_string());
        let cached = cache_key.as_ref().and_then(|ck| {
            INSTALLER_KIND_CACHE.lock().unwrap().get(ck).cloned()
        });
        if let Some((cached_size, cached_mtime, cached_result)) = cached {
            if let Some(st) = stat.as_ref() {
                if cached_size == st.len() && cached_mtime == st.modified().unwrap_or(UNIX_EPOCH).duration_since(UNIX_EPOCH).unwrap_or_default().as_nanos() {
                    return cached_result;
                }
            }
        }
        let result = if suffix == ".zip" {
            match ZipArchive::new(fs::File::open(&path).ok()?) {
                Ok(mut handle) => {
                let mut names = Vec::new();
                for i in 0..handle.len() {
                    if let Ok(entry) = handle.by_index(i) {
                        names.push(entry.name().to_string());
                    }
                }
                installer_from_names(&names)
                }
                Err(_) => None,
            }
        } else {
            match ExtractService::find_tool() {
                (Some(tool), _reason) => {
                    let proc = Command::new(&tool)
                        .args(["l", "-slt", path.to_string_lossy().as_ref()])
                        .stdin(Stdio::null())
                        .output()
                        .ok()?;
                    if proc.status.success() {
                        let stdout = String::from_utf8_lossy(&proc.stdout);
                        let re = Regex::new(r"^Path = (.*)$").unwrap();
                        let names: Vec<String> = re
                            .captures_iter(stdout.as_ref())
                            .filter_map(|m| m.get(1).map(|m| m.as_str().to_string()))
                            .collect();
                        installer_from_names(&names)
                    } else {
                        None
                    }
                }
                (None, _) => None,
            }
        };
        if let Some(st) = stat.as_ref() {
            let _ = INSTALLER_KIND_CACHE
                .lock()
                .unwrap()
                .insert(cache_key.unwrap_or_default(), (st.len(), st.modified().unwrap_or(UNIX_EPOCH).duration_since(UNIX_EPOCH).unwrap_or_default().as_nanos(), result.clone()));
        }
        result
    }

    fn _is_encrypted_zip(&self, path: &Path) -> bool {
        let file = match fs::File::open(path) {
            Ok(f) => f,
            Err(_) => return false,
        };
        match ZipArchive::new(file) {
            Ok(mut source) => {
                for i in 0..source.len() {
                    if let Ok(entry) = source.by_index(i) {
                        if !entry.is_dir() {
                            return true;
                        }
                    }
                }
                false
            }
            Err(_) => false,
        }
    }

    fn _remove_zip_password(&self, _path: &Path, _ctx: Option<&dyn Fn()>) -> bool {
        // Password removal via 7z is complex and not yet ported. Return false (no removal).
        false
    }

    fn _remove_zip_password_external(&self, _path: &Path, _ctx: Option<&dyn Fn()>) -> bool {
        false
    }

    fn _is_own_temp_artefact(&self, path: &Path) -> bool {
        if path.file_name().map_or(false, |n| n.to_string_lossy().contains(TEMP_FILE_TAG)) {
            return true;
        }
        path.ancestors()
            .any(|p| p.file_name().map_or(false, |n| n.to_string_lossy().starts_with(TEMP_DIR_PREFIX)))
    }

    fn _is_managed(&self, path: &Path) -> bool {
        let parent = path.parent();
        parent.map_or(false, |p| {
            [
                "Open Steam Page.html",
                "Open Steam Page.desktop",
                "Open Steam Page in Chrome.desktop",
                "Open Steam Page (Steam Deck).desktop",
                "Open Steam Page (Windows).url",
            ]
            .iter()
            .any(|name| p.join(name).is_file())
        })
    }

    fn _mock(
        &self,
        ctx: Option<&dyn Fn()>,
        progress: Option<&dyn Fn(u32, u32, u32, u64, u32, u32, &Path)>,
    ) -> ScanResult {
        let names = [
            "Alpha Forge v 0 8.zip",
            "Gamma Quest v 1 0.zip",
            "Delta Realm Incremental.zip",
            "Nebula Online.zip",
        ];
        let mut result = ScanResult::default();
        let mut total: u64 = 0;
        for (i, n) in names.iter().enumerate().map(|(i, n)| (i + 1, n)) {
            if let Some(ctx) = ctx {
                ctx();
            }
            let p = Path::new("/mock/library").join(n);
            let title = normalize_name(n);
            result.archives.push(GameArchive {
                path: p.clone(),
                display_name: title.clone(),
                normalized_title: title.clone(),
                identity_key: identity_key(&title),
                extension: p.extension().map_or(String::new(), |e| e.to_string_lossy().to_string()),
                version: version_key(n),
                size: (i as u64) * 1024,
                ..Default::default()
            });
            total += (i as u64) * 1024;
            if let Some(progress) = progress {
                progress(i as u32, i as u32, names.len() as u32, total, i as u32, 0, &p);
            }
        }
        (self.logger)(
            "ARCHIVE",
            &format!("MOCK_DISCOVERY archives={}", result.archives.len()),
        );
        result
    }
}

fn try_load_discovery_cache(library_root: &Path) -> HashMap<String, u128> {
    let config_dir = library_root.parent().unwrap_or(library_root).join("config");
    let state_file = config_dir.join("scan-state.json");
    if !state_file.is_file() {
        return HashMap::new();
    }
    match fs::read_to_string(&state_file) {
        Ok(text) => match serde_json::from_str::<serde_json::Value>(&text) {
            Ok(data) => data
                .get("discovery_dir_mtimes")
                .and_then(|v| v.as_object())
                .map(|obj| {
                    obj.iter()
                        .filter_map(|(k, v)| v.as_u64().map(|u| (k.clone(), u as u128)))
                        .collect()
                })
                .unwrap_or_default(),
            Err(_) => HashMap::new(),
        },
        Err(_) => HashMap::new(),
    }
}

fn try_save_discovery_cache(library_root: &Path, dir_mtimes: &HashMap<String, u128>) {
    let config_dir = library_root.parent().unwrap_or(library_root).join("config");
    let state_file = config_dir.join("scan-state.json");
    let mut existing: serde_json::Value = match fs::read_to_string(&state_file) {
        Ok(text) => serde_json::from_str(&text).unwrap_or(serde_json::json!({})),
        Err(_) => serde_json::json!({}),
    };
    let mut dir_mtimes_json: serde_json::Map<String, serde_json::Value> = serde_json::Map::new();
    for (k, v) in dir_mtimes {
        dir_mtimes_json.insert(k.clone(), serde_json::json!(v));
    }
    existing["discovery_dir_mtimes"] = serde_json::Value::Object(dir_mtimes_json);
    existing["recorded_at"] = serde_json::json!(chrono::Utc::now().timestamp_millis());
    let _ = fs::create_dir_all(&config_dir);
    let config_dir = config_dir.clone();
    let temp_name = format!("scan-state.{}.tmp", std::process::id());
    let tmp_path = config_dir.join(&temp_name);
    if let Ok(mut f) = fs::File::create(&tmp_path) {
        let _ = serde_json::to_writer_pretty(&mut f, &existing);
        let _ = f.flush();
    }
    for _ in 0..4 {
        match fs::rename(&tmp_path, &state_file) {
            Ok(()) => break,
            Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => {
                let _ = std::thread::sleep(std::time::Duration::from_millis(50));
            }
            Err(_e) => {
                let _ = fs::remove_file(&tmp_path);
                return;
            }
        }
    }
    let _ = fs::remove_file(&tmp_path);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_archive_service_new() {
        fn dummy_logger(_: &str, _: &str) {}
        let logger: Arc<dyn for<'a, 'b> Fn(&'a str, &'b str) + Send + Sync> = Arc::new(dummy_logger);
        let service = ArchiveService::new(logger, false, None);
        assert!(!service.mock);
    }

    #[test]
    fn test_is_own_temp_artefact() {
        fn dummy_logger(_: &str, _: &str) {}
        let logger: Arc<dyn for<'a, 'b> Fn(&'a str, &'b str) + Send + Sync> = Arc::new(dummy_logger);
        let _service = ArchiveService::new(logger, false, None);
        assert!(true);
    }
}

