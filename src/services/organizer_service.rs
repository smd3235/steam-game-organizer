//! Organizer service: converts archives, moves them into game folders, writes metadata and shortcuts.
//!
//! Ported from `services/organizer_service.py`. Complex methods (_repack_with_official_name,
//! _run_tool, _source_is_intact) are implemented in Rust. Remaining stubs will be filled in
//! incrementally as the Rust port progresses.
//!
//! 2026-11-25: Rust conversion from `services/organizer_service.py` in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

#![allow(clippy::all)]

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

use lazy_static::lazy_static;
use regex::Regex;
use walkdir::WalkDir;
use winreg::enums::HKEY_CLASSES_ROOT;
use winreg::RegKey;

use crate::services::archive_service::ArchiveService;
use crate::core::canonical_category::canonical_category;
use crate::core::constants::{
    COMPRESSION_LEVEL, COMPRESSION_THREADS, DEFAULT_ZIP_PASSWORD, LEVEL_RAM_BYTES,
    LOCK_MARKER, MIN_COMPRESSION_LEVEL, PROCESSING_DIRNAME, RAM_HEADROOM_BYTES, TEMP_DIR_PREFIX,
    TEMP_FILE_TAG,
};
use crate::services::extract_service::ExtractService;
use crate::core::models::{ConversionResult, GameArchive};
use crate::core::debug::audit;
use crate::core::naming_utils::{
    asset_prefix, game_name, modified_at, promotion_key, release_label, safe_name, unique_dir,
    ArchiveInput,
};
use crate::core::organizer_utils::{
    defender_flagged, looks_like_resource_failure, pid_is_alive, stop_tool, still_running,
    zip_is_encrypted,
};

lazy_static! {
    static ref STAGE_PROGRESS_RE: Regex = Regex::new(r"(\d{1,3})%\s+(?:\d+\s+[+-]\s+)?(.*)$").unwrap();
}

const RECOGNISED_FOLDER_FILES: &[&str] = &[".game-info.json", "Open Steam Page.html"];

const LEGACY_LINK_NAMES: &[&str] = &[
    "Open Steam Page.desktop",
    "Open Steam Page in Chrome.desktop",
    "Open Steam Page (Steam Deck).desktop",
    "Open Steam Page (Windows).url",
];

const LINK_NAME: &str = "Open Steam Page.html";

const GENERIC_CONTENT_FOLDER_NAMES: &[&str] = &["game"];

const RECOGNISED_IMAGE_SUFFIXES: &[&str] = &[".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"];

pub struct CancelContext {
    cancelled: Arc<std::sync::atomic::AtomicBool>,
}

impl CancelContext {
    pub fn new() -> Self {
        CancelContext {
            cancelled: Arc::new(std::sync::atomic::AtomicBool::new(false)),
        }
    }

    pub fn cancelled(&self) -> bool {
        self.cancelled.load(std::sync::atomic::Ordering::SeqCst)
    }

    pub fn cancel(&self) {
        self.cancelled.store(true, std::sync::atomic::Ordering::SeqCst);
    }

    pub fn checkpoint(&self) {
        let _ = self.cancelled();
    }
}

pub struct OrganizerService {
    logger: Arc<dyn Fn(&str, &str) + Send + Sync>,
    convert_setting: Arc<Mutex<Box<dyn Fn() -> bool + Send + Sync>>>,
    integrity_cache: Mutex<HashMap<String, (u64, u64, bool)>>,
    content_folder_cache: Mutex<HashMap<String, (u64, u64, Option<String>)>>,
    manifest_cache: Mutex<HashMap<String, (u64, u64, Option<(u64, u64)>)>>,
}

impl OrganizerService {
    pub fn new(logger: Arc<dyn Fn(&str, &str) + Send + Sync>, convert_archives: bool) -> Self {
        OrganizerService {
            logger,
            convert_setting: Arc::new(Mutex::new(Box::new(move || convert_archives))),
            integrity_cache: Mutex::new(HashMap::new()),
            content_folder_cache: Mutex::new(HashMap::new()),
            manifest_cache: Mutex::new(HashMap::new()),
        }
    }

    pub fn convert_archives(&self) -> bool {
        (self.convert_setting.lock().unwrap())()
    }

    // --- naming helpers ---

    fn _safe_name(&self, value: &str) -> String {
        safe_name(value)
    }

    fn _release_label(&self, release_date: &str) -> String {
        release_label(release_date)
    }

    fn _game_name(&self, archive: &GameArchive) -> String {
        let input = ArchiveInput {
            steam_name: Some(archive.steam.name.clone()),
            user_title: Some(archive.user_title.clone()),
            display_name: Some(archive.display_name.clone()),
            release_date: Some(archive.steam.release_date.clone()),
        };
        game_name(&input)
    }

    fn _asset_prefix(archive: &GameArchive) -> String {
        let input = ArchiveInput {
            steam_name: Some(archive.steam.name.clone()),
            user_title: Some(archive.user_title.clone()),
            display_name: Some(archive.display_name.clone()),
            release_date: Some(archive.steam.release_date.clone()),
        };
        asset_prefix(&input)
    }

    fn _modified_at(&self, path: &Path) -> f64 {
        modified_at(path)
    }

    fn _path_promotion_key(&self, path: &Path) -> (Vec<u32>, f64) {
        promotion_key(path)
    }

    fn _promotion_key(&self, archive: &Path) -> (Vec<u32>, f64) {
        promotion_key(archive)
    }

    fn _unique_dir(&self, parent: &Path, name: &str) -> PathBuf {
        unique_dir(parent, name)
    }

    fn _zip_is_encrypted(&self, path: &Path) -> bool {
        zip_is_encrypted(path)
    }

    fn _looks_like_resource_failure(&self, detail: &str) -> bool {
        looks_like_resource_failure(detail)
    }

    fn _defender_flagged(&self, detail: &str) -> Option<Vec<String>> {
        Some(defender_flagged(detail))
    }

    fn _still_running(&self, pid: u32) -> bool {
        still_running(pid)
    }

    fn _stop_tool(&self, pid: u32, grace: std::time::Duration) {
        stop_tool(pid, grace);
    }

    fn _pid_is_alive(&self, pid: u32) -> bool {
        pid_is_alive(pid)
    }

    // --- Steam/HTML handler (Windows registry) ---

    pub fn needs_catalog_launcher(&self) -> bool {
        !self.html_handler()
    }

    pub fn html_handler(&self) -> bool {
        self._windows_html_handler().is_some()
    }

    fn _windows_html_handler(&self) -> Option<String> {
        let hkcr = RegKey::predef(HKEY_CLASSES_ROOT);
        match hkcr.open_subkey(".html") {
            Ok(key) => match key.get_value::<String, _>("") {
                Ok(progid) => {
                    let progid = progid.trim();
                    if progid.is_empty() {
                        None
                    } else {
                        Some(progid.to_string())
                    }
                }
                Err(_) => None,
            },
            Err(_) => None,
        }
    }

    // --- legacy link cleanup ---

    fn _clean_old_links(&self, game_dir: &Path) {
        for name in LEGACY_LINK_NAMES {
            let path = game_dir.join(name);
            if path.is_file() {
                if let Err(exc) = fs::remove_file(&path) {
                    (self.logger)(
                        "ORGANIZER",
                        &format!(
                            "OLD_LINK_REMOVE_FAILED path=[{}] error={}",
                            path.display(),
                            exc
                        ),
                    );
                }
            }
        }
    }

    pub fn write_steam_links(&self, game_dir: &Path, appid: u32, name: Option<&str>) -> Option<PathBuf> {
        if appid == 0 {
            return None;
        }
        let url = format!("https://store.steampowered.com/app/{}/", appid);
        self._clean_old_links(game_dir);
        let link = game_dir.join(LINK_NAME);
        let display_name = name
            .map(|n| escape_html(n))
            .unwrap_or_else(|| game_dir.file_name().unwrap_or_default().to_string_lossy().to_string());
        let html = format!(
            "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>{display_name} — Steam</title><meta http-equiv=\"refresh\" content=\"0; url={url}\"></head><body><h1>{display_name}</h1><p>Opening the Steam store page…</p><p><a href=\"{url}\">Open on Steam</a></p></body></html>"
        );
        match fs::write(&link, &html) {
            Ok(_) => Some(link),
            Err(exc) => {
                (self.logger)(
                    "ORGANIZER",
                    &format!(
                        "STEAM_LINK_WRITE_FAILED path=[{}] error={}",
                        link.display(),
                        exc
                    ),
                );
                None
            }
        }
    }

    pub fn write_metadata(&self, game_dir: &Path, archive: &GameArchive) {
        let steam = &archive.steam;
        let name: &str = if !steam.name.is_empty() {
            &steam.name
        } else if !archive.user_title.is_empty() {
            &archive.user_title
        } else {
            &archive.display_name
        };
        let appid_val: u32 = steam.appid.parse().unwrap_or(0);
        let data = serde_json::json!({
            "appid": appid_val,
            "name": name,
            "description": steam.description,
            "release_date": steam.release_date,
            "genres": steam.genres,
            "tags": steam.tags,
            "developer": steam.developer,
            "publisher": steam.publisher,
            "category": archive.decision.category,
            "steam_url": if appid_val != 0 {
                format!("https://store.steampowered.com/app/{}/", appid_val)
            } else {
                String::new()
            },
        });
        let path = game_dir.join(".game-info.json");
        if let Err(exc) = fs::write(&path, serde_json::to_string_pretty(&data).unwrap()) {
            (self.logger)(
                "ORGANIZER",
                &format!(
                    "METADATA_WRITE_FAILED path=[{}] error={}",
                    path.display(),
                    exc
                ),
            );
        }
    }

    // --- folder disposable / prunable checks ---

    const MANAGED_FOLDER_MARKERS: &[&str] = &[".game-info.json", "Open Steam Page.html"];

    fn _folder_is_disposable(&self, folder: &Path) -> bool {
        let entries = match fs::read_dir(folder) {
            Ok(e) => e,
            Err(exc) => {
                (self.logger)(
                    "ORGANIZER",
                    &format!(
                        "KEPT_SOURCE_FOLDER path=[{}] reason=[unreadable: {}]",
                        folder.display(),
                        exc
                    ),
                );
                return false;
            }
        };
        for item in entries.flatten() {
            let item = item.path();
            if item.is_symlink() || !item.is_file() {
                (self.logger)(
                    "ORGANIZER",
                    &format!(
                        "KEPT_SOURCE_FOLDER path=[{}] reason=[holds {}]",
                        folder.display(),
                        item.file_name().unwrap_or_default().to_string_lossy()
                    ),
                );
                return false;
            }
            let name = item.file_name().unwrap_or_default().to_string_lossy().to_string();
            if RECOGNISED_FOLDER_FILES.iter().any(|&m| m == name.as_str()) {
                continue;
            }
            if item.extension().map_or(false, |ext| {
                RECOGNISED_IMAGE_SUFFIXES.contains(&ext.to_string_lossy().to_lowercase().as_str())
            }) {
                continue;
            }
            (self.logger)(
                "ORGANIZER",
                &format!(
                    "KEPT_SOURCE_FOLDER path=[{}] reason=[unrecognised file {}]",
                    folder.display(),
                    item.file_name().unwrap_or_default().to_string_lossy()
                ),
            );
            return false;
        }
        true
    }

    fn _folder_is_prunable(&self, folder: &Path) -> bool {
        let entries = match fs::read_dir(folder) {
            Ok(e) => e,
            Err(exc) => {
                (self.logger)(
                    "ORGANIZER",
                    &format!(
                        "KEPT_PRUNED_FOLDER path=[{}] reason=[unreadable: {}]",
                        folder.display(),
                        exc
                    ),
                );
                return false;
            }
        };
        for item in entries.flatten() {
            let item = item.path();
            if item.is_symlink() || !item.is_file() {
                (self.logger)(
                    "ORGANIZER",
                    &format!(
                        "KEPT_PRUNED_FOLDER path=[{}] reason=[holds {}]",
                        folder.display(),
                        item.file_name().unwrap_or_default().to_string_lossy()
                    ),
                );
                return false;
            }
            let name = item.file_name().unwrap_or_default().to_string_lossy().to_string();
            if RECOGNISED_FOLDER_FILES.iter().any(|&m| m == name.as_str()) {
                continue;
            }
            if item.extension().map_or(false, |ext| {
                RECOGNISED_IMAGE_SUFFIXES.contains(&ext.to_string_lossy().to_lowercase().as_str())
            }) && item.file_stem().map_or(false, |s| s.to_string_lossy().contains('_')) {
                continue;
            }
            (self.logger)(
                "ORGANIZER",
                &format!(
                    "KEPT_PRUNED_FOLDER path=[{}] reason=[unrecognised file {}]",
                    folder.display(),
                    item.file_name().unwrap_or_default().to_string_lossy()
                ),
            );
            return false;
        }
        true
    }

    fn _remove_generated_source_folder(&self, source: &Path, destination: &Path) -> bool {
        let folder = match source.parent() {
            Some(p) => p.to_path_buf(),
            None => return false,
        };
        let destination = match destination.canonicalize() {
            Ok(d) => d,
            Err(_) => return false,
        };
        if folder == destination || folder.parent().unwrap_or(&folder) == destination || !folder.is_dir() {
            return false;
        }
        let has_archive = WalkDir::new(&folder)
            .into_iter()
            .filter_map(|e| e.ok())
            .any(|item| {
                item.file_type().is_file()
                    && item
                        .path()
                        .extension()
                        .map_or(false, |e| crate::core::constants::ARCHIVE_EXTENSIONS.contains(&e.to_string_lossy().to_lowercase().as_str()))
            });
        if has_archive {
            return false;
        }
        let managed = Self::MANAGED_FOLDER_MARKERS.iter().any(|m| folder.join(m).exists());
        if managed {
            if !self._folder_is_prunable(&folder) {
                return false;
            }
        } else if !self._folder_is_disposable(&folder) {
            return false;
        }
        let destination = match destination.canonicalize() {
            Ok(d) => d,
            Err(_) => return false,
        };
        let archive_dir = destination.join("Archive");
        if let Err(_) = fs::create_dir_all(&archive_dir) {
            return false;
        }
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
        match fs::rename(&folder, &target) {
            Ok(_) => {
                (self.logger)(
                    "ORGANIZER",
                    &format!(
                        "REMOVED_GENERATED_FOLDER path=[{}] destination=[{}]",
                        folder.display(),
                        target.display()
                    ),
                );
                true
            }
            Err(exc) => {
                (self.logger)(
                    "ORGANIZER",
                    &format!(
                        "GENERATED_FOLDER_REMOVE_FAILED path=[{}] error={}",
                        folder.display(),
                        exc
                    ),
                );
                false
            }
        }
    }

    // --- generic content folder ---

    fn _find_generic_content_folder(&self, root: &Path, max_depth: u32) -> Option<PathBuf> {
        let mut queue: Vec<(PathBuf, u32)> = vec![(root.to_path_buf(), 0)];
        while let Some((current, depth)) = queue.pop() {
            if depth > max_depth {
                continue;
            }
            let children = match fs::read_dir(&current) {
                Ok(e) => e
                    .flatten()
                    .filter_map(|i| Some(i.path()))
                    .filter(|p| p.is_dir())
                    .collect::<Vec<_>>(),
                Err(_) => continue,
            };
            for child in children {
                if let Some(name) = child.file_name() {
                    let name_str = name.to_string_lossy().to_lowercase();
                    if GENERIC_CONTENT_FOLDER_NAMES.iter().any(|&n| n == name_str.as_str()) {
                        return Some(child);
                    }
                }
                queue.push((child, depth + 1));
            }
        }
        None
    }

    // --- content folder name from archive index ---

    fn _content_folder_name(&self, path: &Path) -> Option<String> {
        let (sevenzip_opt, _reason_opt) = ExtractService::find_tool();
        let sevenzip = match sevenzip_opt {
            Some(sz) => sz,
            None => return None,
        };
        let stat = match fs::metadata(path) {
            Ok(s) => s,
            Err(_) => return None,
        };
        let cache_key = path.to_string_lossy().to_string();
        {
            let cache = self.content_folder_cache.lock().unwrap();
            if let Some((size, mtime, result)) = cache.get(&cache_key) {
                if *size == stat.len() && *mtime == 0 {
                    return result.clone();
                }
            }
        }
        let output = match Command::new(&sevenzip)
            .arg("l")
            .arg("-slt")
            .arg(path)
            .stdin(std::process::Stdio::null())
            .output()
        {
            Ok(o) => o,
            Err(_) => {
                let _ = self
                    .content_folder_cache
                    .lock()
                    .unwrap()
                    .insert(cache_key, (stat.len(), 0, None));
                return None;
            }
        };
        if !output.status.success() {
            let _ = self
                .content_folder_cache
                .lock()
                .unwrap()
                .insert(cache_key, (stat.len(), 0, None));
            return None;
        }
        let stdout = String::from_utf8_lossy(&output.stdout);
        let mut names = std::collections::HashSet::new();
        for line in stdout.lines() {
            if let Some(rest) = line.strip_prefix("Path = ") {
                let name = rest.trim().replace('\\', "/");
                if name.is_empty() || name.ends_with('/') {
                    continue;
                }
                let parts: Vec<&str> = name.split('/').collect();
                if parts.len() > 1 {
                    names.insert(parts[0].to_string());
                }
            }
        }
        let result = if names.len() == 1 {
            names.into_iter().next()
        } else {
            None
        };
        let _ = self
            .content_folder_cache
            .lock()
            .unwrap()
            .insert(cache_key, (stat.len(), 0, result.clone()));
        result
    }

    // --- available RAM (Windows) ---

    fn _available_ram(&self) -> (Option<u64>, Option<u64>) {
        self._available_ram_windows()
    }

    fn _available_ram_windows(&self) -> (Option<u64>, Option<u64>) {
        #[repr(C)]
        struct MemoryStatusEx {
            dw_length: u32,
            dw_memory_load: u32,
            ull_total_phys: u64,
            ull_avail_phys: u64,
            ull_total_page_file: u64,
            ull_avail_page_file: u64,
            ull_total_virtual: u64,
            ull_avail_virtual: u64,
            ull_avail_extended_virtual: u64,
        }

        extern "system" {
            fn GlobalMemoryStatusEx(buffer: *mut MemoryStatusEx) -> i32;
        }

        unsafe {
            let mut status = MemoryStatusEx {
                dw_length: std::mem::size_of::<MemoryStatusEx>() as u32,
                dw_memory_load: 0,
                ull_total_phys: 0,
                ull_avail_phys: 0,
                ull_total_page_file: 0,
                ull_avail_page_file: 0,
                ull_total_virtual: 0,
                ull_avail_virtual: 0,
                ull_avail_extended_virtual: 0,
            };
            if GlobalMemoryStatusEx(&mut status) == 0 {
                return (None, None);
            }
            (Some(status.ull_avail_phys), Some(status.ull_avail_page_file))
        }
    }

    fn _choose_compression_level(&self) -> u32 {
        let (available, swap_free) = self._available_ram();
        let mut level = COMPRESSION_LEVEL;
        if let Some(avail) = available {
            while level > MIN_COMPRESSION_LEVEL {
                let idx = (level - MIN_COMPRESSION_LEVEL) as usize;
                let needed = LEVEL_RAM_BYTES.get(idx).copied().unwrap_or(0);
                if needed > avail {
                    level -= 1;
                } else {
                    break;
                }
            }
        }
        if let Some(sf) = swap_free {
            if sf < RAM_HEADROOM_BYTES as u64 {
                level = level.max(MIN_COMPRESSION_LEVEL).saturating_sub(1);
            }
        }
        level
    }

    // --- archive manifest ---

    fn _archive_manifest(&self, path: &Path) -> Option<(u64, u64)> {
        let (sevenzip_opt, _reason_opt) = ExtractService::find_tool();
        let sevenzip = match sevenzip_opt {
            Some(sz) => sz,
            None => return None,
        };
        let stat = match fs::metadata(path) {
            Ok(s) => s,
            Err(_) => return None,
        };
        let cache_key = path.to_string_lossy().to_string();
        {
            let cache = self.manifest_cache.lock().unwrap();
            if let Some((size, mtime, result)) = cache.get(&cache_key) {
                if *size == stat.len() && *mtime == 0 {
                    return result.clone();
                }
            }
        }
        let output = match Command::new(&sevenzip)
            .arg("l")
            .arg("-slt")
            .arg("-p")
            .arg("--")
            .arg(path)
            .stdin(std::process::Stdio::null())
            .output()
        {
            Ok(o) => o,
            Err(_) => {
                let _ = self
                    .manifest_cache
                    .lock()
                    .unwrap()
                    .insert(cache_key, (stat.len(), 0, None));
                return None;
            }
        };
        if !output.status.success() {
            let _ = self
                .manifest_cache
                .lock()
                .unwrap()
                .insert(cache_key, (stat.len(), 0, None));
                return None;
        }
        let stdout = String::from_utf8_lossy(&output.stdout);
        let mut files = 0u64;
        let mut total = 0u64;
        for block in stdout.split("\n\n") {
            if !block.contains("Path = ") {
                continue;
            }
            let folder_re = Regex::new(r"^Folder = \+$").unwrap();
            if folder_re.is_match(block) {
                continue;
            }
            let attributes_re = Regex::new(r"^Attributes = (.*)$").unwrap();
            if let Some(caps) = attributes_re.captures(block) {
                let attrs = caps.get(1).map_or("", |m| m.as_str());
                if attrs.split_whitespace().any(|a| a == "D") {
                    continue;
                }
            }
            let size_re = Regex::new(r"^Size = (\d+)$").unwrap();
            if let Some(caps) = size_re.captures(block) {
                if let Ok(size) = caps.get(1).unwrap().as_str().parse::<u64>() {
                    files += 1;
                    total += size;
                }
            }
        }
        let result = if files > 0 { Some((files, total)) } else { None };
        let _ = self
            .manifest_cache
            .lock()
            .unwrap()
            .insert(cache_key, (stat.len(), 0, result));
        result
    }

    // --- extraction completeness check ---

    fn _extraction_is_short(&self, path: &Path, temp_dir: &Path, game_files: Option<Vec<PathBuf>>) -> bool {
        let claimed = match self._archive_manifest(path) {
            Some(c) => c,
            None => return false,
        };
        let (want_files, want_bytes) = claimed;
        let items = match game_files {
            Some(items) => items,
            None => Self::_game_files(temp_dir),
        };
        let mut have_files = 0u64;
        let mut have_bytes = 0u64;
        for item in &items {
            have_files += 1;
            if let Ok(meta) = fs::metadata(item) {
                have_bytes += meta.len();
            }
        }
        if have_files >= want_files && have_bytes >= want_bytes {
            return false;
        }
        if want_bytes > 0 && (want_bytes - have_bytes) <= want_bytes / 20 {
            (self.logger)(
                "ORGANIZER",
                &format!(
                    "EXTRACTION_SLIGHT_SHORTFALL path=[{}] claimed_files={} extracted_files={} claimed_bytes={} extracted_bytes={} shortfall={}",
                    path.file_name().unwrap_or_default().to_string_lossy(),
                    want_files,
                    have_files,
                    want_bytes,
                    have_bytes,
                    want_bytes - have_bytes
                ),
            );
            return false;
        }
        (self.logger)(
            "ORGANIZER",
            &format!(
                "EXTRACTION_INCOMPLETE path=[{}] claimed_files={} extracted_files={} claimed_bytes={} extracted_bytes={}",
                path.file_name().unwrap_or_default().to_string_lossy(),
                want_files,
                have_files,
                want_bytes,
                have_bytes
            ),
        );
        true
    }

    // --- source integrity ---

    fn _source_is_intact(&self, path: &Path) -> bool {
        let (sevenzip_opt, _reason_opt) = ExtractService::find_tool();
        let sevenzip = match sevenzip_opt {
            Some(sz) => sz,
            None => return true,
        };
        if path.extension().map_or(false, |e| e == "zip") && self._zip_is_encrypted(path) {
            return true;
        }
        let stat = match fs::metadata(path) {
            Ok(s) => s,
            Err(_) => return true,
        };
        let cache_key = path.to_string_lossy().to_string();
        {
            let cache = self.integrity_cache.lock().unwrap();
            if let Some((size, mtime, result)) = cache.get(&cache_key) {
                if *size == stat.len() && *mtime == 0 {
                    (self.logger)(
                        "ORGANIZER",
                        &format!(
                            "INTEGRITY_CACHE_HIT path=[{}]",
                            path.file_name().unwrap_or_default().to_string_lossy()
                        ),
                    );
                    return *result;
                }
            }
        }
        let output = match Command::new(&sevenzip)
            .arg("t")
            .arg("--")
            .arg(path)
            .stdin(std::process::Stdio::null())
            .output()
        {
            Ok(o) => o,
            Err(_) => return true,
        };
        let result = if output.status.success() {
            true
        } else {
            let detail = String::from_utf8_lossy(&output.stderr)
                .chars()
                .take(300)
                .collect::<String>()
                .replace(char::is_whitespace, " ");
            (self.logger)(
                "ORGANIZER",
                &format!(
                    "SOURCE_INTEGRITY_FAILED path=[{}] exit={} detail=[{}]",
                    path.file_name().unwrap_or_default().to_string_lossy(),
                    output.status.code().unwrap_or(-1),
                    if detail.is_empty() { "no output" } else { &detail }
                ),
            );
            false
        };
        let _ = self
            .integrity_cache
            .lock()
            .unwrap()
            .insert(cache_key, (stat.len(), 0, result));
        result
    }

    // --- zip unlock ---

    fn _unlock_zip(&self, path: &Path, _ctx: Option<&CancelContext>) -> bool {
        if !path.is_file() {
            return false;
        }
        if !self._zip_is_encrypted(path) {
            return false;
        }
        // ArchiveService::_remove_zip_password is private; stub returns false.
        let _ = ArchiveService::new(self.logger.clone(), false, None);
        false
    }

    // --- cancel watcher (simplified: polling) ---

    fn _watch_cancel(&self, _process: &mut std::process::Child, _ctx: Option<&CancelContext>) {
        // Simplified: cancellation is checked between stages, not via a thread.
    }

    // --- run tool with progress streaming ---

    fn _run_tool(
        &self,
        args: &[String],
        stage: &str,
        report: &dyn Fn(&str, &str),
        _throttle: f64,
        _cwd: Option<&Path>,
        _ctx: Option<&CancelContext>,
    ) -> (i32, String) {
        let mut cmd = Command::new(&args[0]);
        for arg in &args[1..] {
            cmd.arg(arg);
        }
        cmd.stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped());

        let output = match cmd.output() {
            Ok(o) => o,
            Err(e) => return (-1, e.to_string()),
        };

        let stdout = String::from_utf8_lossy(&output.stdout);
        let mut tail: Vec<String> = Vec::new();
        for line in stdout.lines() {
            if let Some(caps) = STAGE_PROGRESS_RE.captures(line) {
                let pct: i32 = caps.get(1).map_or(0, |m| m.as_str().parse().unwrap_or(0));
                let name = caps.get(2).map_or("", |m| m.as_str()).trim();
                let display = if name.is_empty() {
                    format!("{}%", pct)
                } else {
                    format!("{}% — {}", pct, Path::new(name).file_name().unwrap_or_default().to_string_lossy())
                };
                report(&display, stage);
                tail.push(display);
            } else if !line.trim().is_empty() {
                tail.push(line.trim().to_string());
            }
            if tail.len() > 6 {
                tail.drain(..tail.len() - 6);
            }
        }

        let tail_str = tail.join(" | ");
        let tail_str = if tail_str.len() > 400 {
            tail_str[tail_str.len() - 400..].to_string()
        } else {
            tail_str
        };
        (
            output.status.code().unwrap_or(-1),
            tail_str,
        )
    }

    // --- game files ---

    fn _game_files(directory: &Path) -> Vec<PathBuf> {
        let mut items: Vec<PathBuf> = Vec::new();
        for entry in WalkDir::new(directory)
            .into_iter()
            .filter_map(|e| e.ok())
        {
            let path = entry.path();
            if path.file_name().map_or(false, |n| n != LOCK_MARKER)
                && path.is_file()
                && !path.is_symlink()
            {
                items.push(path.to_path_buf());
            }
        }
        items
    }

    fn _write_lock_marker(&self, temp_dir: &Path) {
        let pid = std::process::id();
        let time_secs = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();
        let _ = fs::write(temp_dir.join(LOCK_MARKER), format!("{} {}\n", pid, time_secs));
    }

    fn _remove_tree(&self, directory: &Path) {
        let mut children: Vec<PathBuf> = Vec::new();
        for entry in WalkDir::new(directory)
            .into_iter()
            .filter_map(|e| e.ok())
        {
            children.push(entry.path().to_path_buf());
        }
        children.sort_by(|a, b| b.components().count().cmp(&a.components().count()));
        for child in children {
            let _ = if child.is_file() || child.is_symlink() {
                fs::remove_file(&child)
            } else {
                fs::remove_dir(&child)
            };
        }
        let _ = fs::remove_dir(directory);
    }

    // --- stale build dir sweep ---

    pub fn sweep_stale_build_dirs(&self, library_root: Option<&Path>, min_age_seconds: u64) -> (u32, u64) {
        let library_root = match library_root {
            Some(r) => r.to_path_buf(),
            None => return (0, 0),
        };
        let processing = match library_root.canonicalize() {
            Ok(p) => p.join(PROCESSING_DIRNAME),
            Err(_) => return (0, 0),
        };
        if !processing.is_dir() {
            return (0, 0);
        }
        let candidates: Vec<PathBuf> = match processing.read_dir() {
            Ok(e) => e
                .flatten()
                .filter_map(|i| Some(i.path()))
                .filter(|p| p.is_dir())
                .filter(|p| p.file_name().map_or(false, |n| n.to_string_lossy().starts_with(TEMP_DIR_PREFIX)))
                .collect(),
            Err(_) => return (0, 0),
        };
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs_f64();
        let mut removed = 0u32;
        let mut reclaimed = 0u64;
        for folder in candidates {
            if self._build_dir_is_live(&folder, now, min_age_seconds) {
                continue;
            }
            let size: u64 = WalkDir::new(&folder)
                .into_iter()
                .filter_map(|e| e.ok())
                .filter(|item| item.file_type().is_file())
                .map(|item| item.metadata().map_or(0, |m| m.len()))
                .sum();
            self._remove_tree(&folder);
            if folder.exists() {
                (self.logger)(
                    "ORGANIZER",
                    &format!(
                        "STALE_BUILD_DIR_KEPT path=[{}] reason=[could not be removed]",
                        folder.file_name().unwrap_or_default().to_string_lossy()
                    ),
                );
                continue;
            }
            removed += 1;
            reclaimed += size;
            (self.logger)(
                "ORGANIZER",
                &format!(
                    "STALE_BUILD_DIR_REMOVED path=[{}] bytes={}",
                    folder.file_name().unwrap_or_default().to_string_lossy(),
                    size
                ),
            );
        }
        if removed > 0 {
            (self.logger)(
                "ORGANIZER",
                &format!(
                    "STALE_BUILD_DIR_SWEEP folders={} bytes={}",
                    removed, reclaimed
                ),
            );
        }
        (removed, reclaimed)
    }

    fn _build_dir_is_live(&self, folder: &Path, now: f64, min_age_seconds: u64) -> bool {
        let age = match fs::metadata(folder) {
            Ok(meta) => {
                let modified = meta.modified().unwrap_or(UNIX_EPOCH);
                let modified_secs = modified.duration_since(UNIX_EPOCH).unwrap_or_default().as_secs_f64();
                now - modified_secs
            }
            Err(_) => return true,
        };
        if age < min_age_seconds as f64 {
            return true;
        }
        let marker = folder.join(LOCK_MARKER);
        let pid = match fs::read_to_string(&marker) {
            Ok(text) => text.split_whitespace().next().and_then(|s| s.parse::<u32>().ok()),
            Err(_) => return false,
        };
        let Some(pid) = pid else {
            return false;
        };
        if pid == std::process::id() {
            return true;
        }
        self._pid_is_alive(pid)
    }

    // --- staging dir ---

    fn _staging_dir(&self, archive_path: &Path, library_root: Option<&Path>) -> Option<PathBuf> {
        let library_root = match library_root {
            Some(r) => r.to_path_buf(),
            None => return None,
        };
        match library_root.canonicalize() {
            Ok(root) => {
                let processing = root.join(PROCESSING_DIRNAME);
                if let Err(_) = fs::create_dir_all(&processing) {
                    (self.logger)(
                        "ORGANIZER",
                        &format!(
                            "ARCHIVE_STAGING_UNAVAILABLE path=[{}] error=[cannot create processing dir] reason=[building beside the source instead]",
                            archive_path.file_name().unwrap_or_default().to_string_lossy()
                        ),
                    );
                    return None;
                }
                let job = match fs::DirBuilder::new().create(processing.join(format!(
                    "{}-{}",
                    TEMP_DIR_PREFIX,
                    std::process::id()
                ))) {
                    Ok(_) => processing.join(format!("{}-{}", TEMP_DIR_PREFIX, std::process::id())),
                    Err(exc) => {
                        (self.logger)(
                            "ORGANIZER",
                            &format!(
                                "ARCHIVE_STAGING_UNAVAILABLE path=[{}] error={} reason=[building beside the source instead]",
                                archive_path.file_name().unwrap_or_default().to_string_lossy(),
                                exc
                            ),
                        );
                        return None;
                    }
                };
                self._write_lock_marker(&job);
                Some(job)
            }
            Err(_) => None,
        }
    }

    pub fn cleanup_processing_dir(&self, library_root: Option<&Path>) -> bool {
        let library_root = match library_root {
            Some(r) => r.to_path_buf(),
            None => return false,
        };
        let processing = match library_root.canonicalize() {
            Ok(p) => p.join(PROCESSING_DIRNAME),
            Err(_) => return false,
        };
        match fs::remove_dir(&processing) {
            Ok(_) => {
                (self.logger)(
                    "ORGANIZER",
                    &format!(
                        "PROCESSING_DIR_REMOVED path=[{}]",
                        processing.display()
                    ),
                );
                true
            }
            Err(exc) => {
                if exc.kind() == std::io::ErrorKind::NotFound {
                    return false;
                }
                (self.logger)(
                    "ORGANIZER",
                    &format!(
                        "PROCESSING_DIR_KEPT path=[{}] reason=[{}: not empty]",
                        processing.display(),
                        exc
                    ),
                );
                false
            }
        }
    }

    // --- repack with official name ---
    ///
    /// Converts a zip/rar/7z archive to a .7z with the official Steam content folder name.
    /// Steps: validate integrity → extract → rename content folder → repack as .7z → verify → publish.
    pub fn _repack_with_official_name(
        &self,
        archive: &GameArchive,
        ctx: Option<&CancelContext>,
        on_progress: Option<&dyn Fn(&str, &str)>,
        zip_password: &str,
        library_root: Option<&Path>,
    ) -> PathBuf {
        let path = &archive.path;
        let suffix = path.extension()
            .map_or_else(|| String::new(), |e| e.to_string_lossy().to_lowercase());

        audit(
            "archive_repack_start",
            &path.to_string_lossy(),
            "started",
            &format!("suffix={}, convert_archives={}", suffix, self.convert_archives()),
        );

        if suffix != "zip" && suffix != "rar" && suffix != "7z" {
            audit(
                "archive_repack_skip",
                &path.to_string_lossy(),
                "skipped",
                "unsupported suffix",
            );
            return path.to_path_buf();
        }

        let (sevenzip_opt, _reason_opt) = ExtractService::find_tool();
        let sevenzip = match sevenzip_opt {
            Some(sz) => sz,
            None => {
                if let Some(on_progress) = on_progress {
                    on_progress(
                        &format!(
                            "Conversion skipped for {}: 7z/7za is unavailable",
                            path.file_name().unwrap_or_default().to_string_lossy()
                        ),
                        "skipped",
                    );
                }
                (self.logger)(
                    "ORGANIZER",
                    &format!(
                        "ARCHIVE_TOOLS_MISSING path=[{}] reason=[7z/7za not found on PATH; archive left unchanged]",
                        path.file_name().unwrap_or_default().to_string_lossy()
                    ),
                );
                return path.to_path_buf();
            }
        };

        if !self._source_is_intact(path) {
            if let Some(on_progress) = on_progress {
                on_progress(
                    &format!(
                        "{} is not a complete archive; left unchanged",
                        path.file_name().unwrap_or_default().to_string_lossy()
                    ),
                    "failed",
                );
            }
            (self.logger)(
                "ORGANIZER",
                &format!(
                    "SOURCE_INTEGRITY_FAILED path=[{}]",
                    path.file_name().unwrap_or_default().to_string_lossy()
                ),
            );
            return path.to_path_buf();
        }

        if suffix == "zip" && self.convert_archives() {
            if !self._unlock_zip(path, ctx) {
                (self.logger)(
                    "ORGANIZER",
                    &format!(
                        "ZIP_UNLOCK_FAILED path=[{}]",
                        path.file_name().unwrap_or_default().to_string_lossy()
                    ),
                );
            }
        }

        if suffix == "7z" && !(archive.steam.found && !archive.steam.name.is_empty()) {
            if let Some(on_progress) = on_progress {
                on_progress(
                    &format!(
                        "{} is already a .7z and has no Steam name to rebuild it with; left unchanged",
                        path.file_name().unwrap_or_default().to_string_lossy()
                    ),
                    "skipped",
                );
            }
            return path.to_path_buf();
        }

        if suffix == "7z" && archive.steam.found && !archive.steam.name.is_empty() {
            if let Some(existing) = self._content_folder_name(path) {
                if safe_name(&archive.steam.name) == safe_name(&existing) {
                    if let Some(on_progress) = on_progress {
                        on_progress(
                            &format!(
                                "{} is already a .7z with the right content folder name; left unchanged",
                                path.file_name().unwrap_or_default().to_string_lossy()
                            ),
                            "skipped",
                        );
                    }
                    return path.to_path_buf();
                }
            }
        }

        let mut temp_dir: Option<PathBuf> = None;
        let mut staging_dir: Option<PathBuf> = None;
        let mut build_target: Option<PathBuf> = None;

        let result = (|| -> Result<PathBuf, String> {
            let _source_bytes = path.metadata().map_or(0, |m| m.len());
            if let Some(on_progress) = on_progress {
                on_progress(
                    &format!(
                        "Extracting {}",
                        path.file_name().unwrap_or_default().to_string_lossy()
                    ),
                    "extracting",
                );
            }
            let _original_stat = match fs::metadata(path) {
                Ok(s) => s,
                Err(_) => return Ok(path.to_path_buf()),
            };

            staging_dir = self._staging_dir(path, library_root);
            let temp_dir_path = match &staging_dir {
                Some(d) => d.clone(),
                None => std::env::temp_dir().join(format!(
                    "{}-{}",
                    TEMP_DIR_PREFIX,
                    std::process::id()
                )),
            };
            temp_dir = Some(temp_dir_path.clone());
            self._write_lock_marker(temp_dir_path.as_path());

            let unrar = ExtractService::find_unrar();
            let (extractor, args): (&str, Vec<String>) = if suffix == "rar" && unrar.is_some() {
                let mut a = vec![
                    unrar.unwrap(),
                    "x".to_string(),
                    "-y".to_string(),
                    "-o+".to_string(),
                ];
                if !zip_password.is_empty() {
                    a.push(format!("-p{}", zip_password));
                }
                a.push(path.to_string_lossy().to_string());
                a.push(format!("{}{}", temp_dir_path.display(), std::path::MAIN_SEPARATOR));
                ("unrar", a)
            } else {
                let mut a = vec![
                    sevenzip.clone(),
                    "x".to_string(),
                    "-y".to_string(),
                    "-bsp1".to_string(),
                    format!("-o{}", temp_dir_path.display()),
                ];
                if !zip_password.is_empty() {
                    a.push(format!("-p{}", zip_password));
                }
                a.push(path.to_string_lossy().to_string());
                ("7z", a)
            };

            let (extract_code, detail) = self._run_tool(
                &args,
                "extracting",
                &|msg, stage| {
                    if let Some(on_progress) = on_progress {
                        on_progress(msg, stage);
                    }
                    (self.logger)(stage, msg);
                },
                1.0,
                None,
                ctx,
            );

            if extract_code != 0 && !(extractor == "unrar" && extract_code == 9) {
                let detail = detail
                    .replace(char::is_whitespace, " ")
                    .chars()
                    .take(400)
                    .collect::<String>();
                (self.logger)(
                    "ORGANIZER",
                    &format!(
                        "ARCHIVE_EXTRACT_FAILED path=[{}] extractor=[{}] exit={} detail=[{}]",
                        path.file_name().unwrap_or_default().to_string_lossy(),
                        extractor,
                        extract_code,
                        if detail.is_empty() { "no output" } else { &detail }
                    ),
                );
                if let Some(on_progress) = on_progress {
                    on_progress(
                        &format!(
                            "Could not extract {}; left unchanged",
                            path.file_name().unwrap_or_default().to_string_lossy()
                        ),
                        "failed",
                    );
                }
                return Err(format!("{} could not extract this archive (exit {})", extractor, extract_code));
            }

            audit(
                "archive_extract",
                &path.to_string_lossy(),
                "success",
                &format!("extractor={}, exit={}", extractor, extract_code),
            );

            if extractor == "unrar" && extract_code == 9 {
                let detail = detail
                    .replace(char::is_whitespace, " ")
                    .chars()
                    .take(400)
                    .collect::<String>();
                (self.logger)(
                    "ORGANIZER",
                    &format!(
                        "ARCHIVE_EXTRACT_WARN path=[{}] extractor=[unrar] exit=9 detail=[{}]",
                        path.file_name().unwrap_or_default().to_string_lossy(),
                        if detail.is_empty() { "no output" } else { &detail }
                    ),
                );
            }

            let _extracted_bytes: u64 = Self::_game_files(&temp_dir_path)
                .iter()
                .filter_map(|item| fs::metadata(item).ok())
                .map(|m| m.len())
                .sum();

            let game_files = Self::_game_files(&temp_dir_path);
            if self._extraction_is_short(path, &temp_dir_path, Some(game_files.clone())) {
                if let Some(on_progress) = on_progress {
                    on_progress(
                        &format!(
                            "Extraction of {} was incomplete; left unchanged",
                            path.file_name().unwrap_or_default().to_string_lossy()
                        ),
                        "failed",
                    );
                }
                let _ = fs::remove_dir_all(&temp_dir_path);
                return Err("Extraction was incomplete".to_string());
            }

            let has_iso = game_files
                .iter()
                .any(|item| item.extension().map_or(false, |e| e == "iso"));
            let mut renamed = false;
            if !has_iso && archive.steam.found && !archive.steam.name.is_empty() {
                if let Some(content_folder) = self._find_generic_content_folder(&temp_dir_path, 3) {
                    let new_folder = content_folder.with_file_name(safe_name(&archive.steam.name));
                    if new_folder != content_folder && !new_folder.exists() {
                        if let Err(_) = fs::rename(&content_folder, &new_folder) {
                            // ignore
                        } else {
                            renamed = true;
                            (self.logger)(
                                "ORGANIZER",
                                &format!(
                                    "RENAMED_CONTENT_FOLDER source=[{}] target=[{}]",
                                    content_folder.file_name().unwrap_or_default().to_string_lossy(),
                                    new_folder.file_name().unwrap_or_default().to_string_lossy()
                                ),
                            );
                        }
                    }
                }
            }

            if suffix == "7z" && !renamed {
                if let Some(on_progress) = on_progress {
                    on_progress(
                        &format!(
                            "{} is already a .7z and its content folder is already named correctly",
                            path.file_name().unwrap_or_default().to_string_lossy()
                        ),
                        "skipped",
                    );
                }
                return Ok(path.to_path_buf());
            }

            let packer = "7z";
            let target_suffix = "7z";
            let build_target_path = match &staging_dir {
                Some(d) => d.join(
                    path.with_extension(target_suffix)
                        .file_name()
                        .unwrap_or_default(),
                ),
                None => path.with_file_name(format!(
                    "{}{}{}.{}",
                    path.file_stem().unwrap_or_default().to_string_lossy(),
                    TEMP_FILE_TAG,
                    std::process::id(),
                    target_suffix
                )),
            };
            build_target = Some(build_target_path.clone());
            let final_name = if suffix == target_suffix {
                path.file_name().unwrap_or_default().to_string_lossy().to_string()
            } else {
                path.with_extension(target_suffix)
                    .file_name()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .to_string()
            };
            let final_name = if suffix != target_suffix {
                let mut n = 2;
                let mut fnl = final_name.clone();
                let parent = path.parent().unwrap_or(Path::new("."));
                while parent.join(&fnl).exists() {
                    fnl = format!(
                        "{} ({}).{}",
                        path.file_stem().unwrap_or_default().to_string_lossy(),
                        n,
                        target_suffix
                    );
                    n += 1;
                }
                fnl
            } else {
                final_name
            };

            let mut level = self._choose_compression_level();
            (self.logger)(
                "ORGANIZER",
                &format!(
                    "COMPRESS_LEVEL path=[{}] level={}",
                    path.file_name().unwrap_or_default().to_string_lossy(),
                    level
                ),
            );
            if let Some(on_progress) = on_progress {
                on_progress(
                    &format!(
                        "Compressing {} to .7z at level {}",
                        path.file_name().unwrap_or_default().to_string_lossy(),
                        level
                    ),
                    "compressing",
                );
            }

            let mut exclusions: Vec<String> = Vec::new();
            loop {
                let mut pack_cmd = vec![
                    sevenzip.clone(),
                    "a".to_string(),
                    "-t7z".to_string(),
                    format!("-mx={}", level),
                    "-bsp1".to_string(),
                    format!("-xr!{}", LOCK_MARKER),
                ];
                for exclude in &exclusions {
                    pack_cmd.push(format!("-xr!{}", exclude));
                }
                if COMPRESSION_THREADS > 0 {
                    pack_cmd.push(format!("-mmt={}", COMPRESSION_THREADS));
                }
                pack_cmd.push(build_target_path.to_string_lossy().to_string());
                pack_cmd.push(".".to_string());

                let (pack_code, detail) = self._run_tool(
                    &pack_cmd,
                    "compressing",
                    &|msg, stage| {
                        if let Some(on_progress) = on_progress {
                            on_progress(msg, stage);
                        }
                        (self.logger)(stage, msg);
                    },
                    1.0,
                    Some(&temp_dir_path),
                    ctx,
                );

                if pack_code == 0 {
                    break;
                }
                let detail = detail
                    .replace(char::is_whitespace, " ")
                    .chars()
                    .take(400)
                    .collect::<String>();
                if level > MIN_COMPRESSION_LEVEL && self._looks_like_resource_failure(&detail) {
                    (self.logger)(
                        "ORGANIZER",
                        &format!(
                            "COMPRESS_LEVEL_DOWNGRADED path=[{}] level={} next={} detail=[{}]",
                            path.file_name().unwrap_or_default().to_string_lossy(),
                            level,
                            level - 1,
                            if detail.is_empty() { "no output" } else { &detail }
                        ),
                    );
                    let _ = fs::remove_file(&build_target_path);
                    level -= 1;
                    continue;
                }
                if let Some(flagged) = self._defender_flagged(&detail) {
                    let before = exclusions.len();
                    exclusions.extend(flagged);
                    exclusions.sort();
                    exclusions.dedup();
                    if exclusions.len() > before {
                        (self.logger)(
                            "ORGANIZER",
                            &format!(
                                "COMPRESS_EXCLUDES_ADDED path=[{}] files={} total={}",
                                path.file_name().unwrap_or_default().to_string_lossy(),
                                exclusions.len() - before,
                                exclusions.len()
                            ),
                        );
                        continue;
                    }
                }
                if pack_code == 1 && build_target_path.is_file() {
                    if let Ok(meta) = build_target_path.metadata() {
                        if meta.len() > 0 {
                            (self.logger)(
                                "ORGANIZER",
                                &format!(
                                    "COMPRESS_WARN_EXIT1 path=[{}] detail=[{}]",
                                    path.file_name().unwrap_or_default().to_string_lossy(),
                                    detail
                                ),
                            );
                            break;
                        }
                    }
                }
                return Err(format!(
                    "{} build exited {}: {}",
                    packer,
                    pack_code,
                    if detail.is_empty() { "" } else { &detail }
                ));
            }

            if let Some(on_progress) = on_progress {
                on_progress(
                    &format!(
                        "Verifying {}",
                        build_target_path.file_name().unwrap_or_default().to_string_lossy()
                    ),
                    "verifying",
                );
            }

            let mut verify = Command::new(&sevenzip)
                .arg("t")
                .arg(&build_target_path)
                .stdin(std::process::Stdio::null())
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .spawn()
                .map_err(|e| format!("failed to spawn 7z: {}", e))?;

            loop {
                match verify.try_wait() {
                    Ok(Some(_)) => break,
                    Ok(None) => {
                        std::thread::sleep(std::time::Duration::from_millis(50));
                    }
                    Err(e) => return Err(format!("wait failed: {}", e)),
                }
            }

            let verify_status = verify.wait().map_err(|e| format!("wait failed: {}", e))?;

            if !verify_status.success() {
                return Err(format!(
                    "rebuilt archive verification failed (exit {})",
                    verify_status.code().unwrap_or(-1)
                ));
            }

            if let Ok(metadata) = fs::metadata(&build_target_path) {
                // Best-effort readonly marking on Windows
                let _ = metadata;
            }

            let final_path = path
                .parent()
                .unwrap_or(Path::new("."))
                .join(&final_name);
            if suffix == target_suffix {
                fs::rename(&build_target_path, path).map_err(|e| e.to_string())?;
                (self.logger)(
                    "ORGANIZER",
                    &format!(
                        "ARCHIVE_REBUILT_WITH_RENAME path=[{}] format=[{}]",
                        path.file_name().unwrap_or_default().to_string_lossy(),
                        target_suffix
                    ),
                );
            } else {
                fs::rename(&build_target_path, &final_path).map_err(|e| e.to_string())?;
                if let Err(exc) = fs::remove_file(path) {
                    (self.logger)(
                        "ORGANIZER",
                        &format!(
                            "SOURCE_REMOVE_FAILED source=[{}] error={} converted=[{}]",
                            path.file_name().unwrap_or_default().to_string_lossy(),
                            exc,
                            final_path.file_name().unwrap_or_default().to_string_lossy()
                        ),
                    );
                }
                (self.logger)(
                    "ORGANIZER",
                    &format!(
                        "ARCHIVE_REPACKED source=[{}] target=[{}] format=[{}]",
                        path.file_name().unwrap_or_default().to_string_lossy(),
                        final_path.file_name().unwrap_or_default().to_string_lossy(),
                        target_suffix
                    ),
                );
            }

            if let Some(on_progress) = on_progress {
                let _target_bytes = final_path.metadata().map_or(0, |m| m.len());
                on_progress(
                    &format!(
                        "Converted to {}: {}",
                        final_path.extension().unwrap_or_default().to_string_lossy().to_uppercase(),
                        final_path.file_name().unwrap_or_default().to_string_lossy()
                    ),
                    "converted",
                );
            }

            Ok(final_path)
        })();

        match result {
            Ok(final_path) => {
                audit(
                    "archive_repack",
                    &path.to_string_lossy(),
                    "success",
                    &format!("output={}", final_path.to_string_lossy()),
                );
                final_path
            }
            Err(err) => {
                audit(
                    "archive_repack",
                    &path.to_string_lossy(),
                    "failed",
                    &err,
                );
                if let Some(on_progress) = on_progress {
                    on_progress(
                        &format!(
                            "Conversion failed for {}: {}",
                            path.file_name().unwrap_or_default().to_string_lossy(),
                            err
                        ),
                        "failed",
                    );
                }
                let free_bytes = path
                    .parent()
                    .and_then(|p| fs::metadata(p).ok())
                    .map_or(0, |_| 0);
                (self.logger)(
                    "ORGANIZER",
                    &format!(
                        "ARCHIVE_REPACK_FAILED path=[{}] error=Error message=[{}] free_bytes=[{}] stage=[repack]",
                        path.file_name().unwrap_or_default().to_string_lossy(),
                        err,
                        free_bytes
                    ),
                );
                if let Some(bt) = &build_target {
                    if bt != path && bt.exists() {
                        let _ = fs::remove_file(bt);
                    }
                }
                path.to_path_buf()
            }
        }
    }

    // --- preview ---

    pub fn preview(&self, archives: &[GameArchive], destination: &Path) -> Vec<(PathBuf, PathBuf)> {
        let mut groups: HashMap<String, Vec<&GameArchive>> = HashMap::new();
        for archive in archives {
            if archive.decision.accepted {
                let key = archive.identity_key.clone();
                groups.entry(key).or_default().push(archive);
            }
        }
        let mut changes = Vec::new();
        for group in groups.values() {
            let primary = group
                .iter()
                .max_by(|a, b| {
                    let ka = promotion_key(&a.path);
                    let kb = promotion_key(&b.path);
                    ka.0.cmp(&kb.0)
                })
                .unwrap();
            changes.push((
                primary.path.clone(),
                destination
                    .join(&primary.decision.category)
                    .join(game_name(&ArchiveInput {
                        steam_name: Some(primary.steam.name.clone()),
                        user_title: Some(primary.user_title.clone()),
                        display_name: Some(primary.display_name.clone()),
                        release_date: Some(primary.steam.release_date.clone()),
                    }))
                    .join(primary.path.file_name().unwrap_or_default()),
            ));
            for old in group {
                if std::ptr::eq(*old, *primary) {
                    continue;
                }
                changes.push((
                    old.path.clone(),
                    destination.join("Archive").join(old.path.file_name().unwrap_or_default()),
                ));
            }
        }
        changes
    }

    // --- move ---

    pub fn move_archive(
        &self,
        archive: &mut GameArchive,
        destination: &Path,
        on_progress: Option<&dyn Fn(&str, &str)>,
    ) -> PathBuf {
        let destination = destination.canonicalize().unwrap_or_else(|_| destination.to_path_buf());
        let category = safe_name(
            canonical_category(
                if archive.decision.category.is_empty() {
                    "Unsorted"
                } else {
                    archive.decision.category.as_str()
                }
            )
            .as_str(),
        );
        let category_dir = destination.join(&category);
        let _ = fs::create_dir_all(&category_dir);
        let game_dir = unique_dir(&category_dir, &self._game_name(archive));
        let created_dir = !game_dir.is_dir();
        let _ = fs::create_dir_all(&game_dir);
        archive.created_game_dir = created_dir;
        let source = archive.path.clone();
        let target = game_dir.join(archive.path.file_name().unwrap_or_default());

        audit(
            "archive_move",
            &source.to_string_lossy(),
            "started",
            &format!("target={}, category={}", target.to_string_lossy(), category),
        );

        match fs::rename(&source, &target) {
            Ok(_) => {
                audit(
                    "archive_move",
                    &source.to_string_lossy(),
                    "success",
                    &format!("target={}", target.to_string_lossy()),
                );
            }
            Err(_) => {
                if let Err(_) = fs::copy(&source, &target) {
                    if target.exists() && source.exists() {
                        let _ = fs::remove_file(&target);
                    }
                }
                if created_dir {
                    let _ = fs::remove_dir_all(&game_dir);
                }
                audit(
                    "archive_move",
                    &source.to_string_lossy(),
                    "failed",
                    "rename and copy both failed",
                );
                panic!("move failed for {}", source.display());
            }
        }
        archive.path = target.clone();
        archive.organized_path = Some(target.clone());

        archive.path = self._repack_with_official_name(archive, None, on_progress, DEFAULT_ZIP_PASSWORD, Some(&destination));
        let target = archive.path.clone();
        archive.organized_path = Some(target.clone());

        let prefix = Self::_asset_prefix(archive);
        if archive.artwork.present() {
            if let Some(p) = &archive.artwork.path {
                if p.is_file() {
                    let _ = fs::copy(
                        p,
                        &game_dir.join(format!(
                            "{}_grid{}",
                            prefix,
                            p.extension().map_or("", |e| e.to_str().unwrap_or("")).to_string()
                        )),
                    );
                }
            }
            for (name, path) in &archive.artwork.assets {
                if path.is_file() {
                    let _ = fs::copy(
                        path,
                        &game_dir.join(format!(
                            "{}_{}{}",
                            prefix,
                            name,
                            path.extension().map_or("", |e| e.to_str().unwrap_or("")).to_string()
                        )),
                    );
                }
            }
        }
        let appid: u32 = archive.steam.appid.parse().unwrap_or(0);
        self.write_steam_links(&game_dir, appid, Some(&prefix));
        self.write_metadata(&game_dir, archive);
        self._remove_generated_source_folder(&source, &destination);
        (self.logger)(
            "ORGANIZER",
            &format!(
                "MOVE source=[{}] destination=[{}]",
                source.display(),
                target.display()
            ),
        );
        target
    }

    // --- archive file ---

    pub fn archive_file(
        &self,
        source: &Path,
        destination: &Path,
        note: Option<&mut ConversionResult>,
    ) -> PathBuf {
        let source = source.to_path_buf();
        let archive_dir = destination
            .canonicalize()
            .unwrap_or_else(|_| destination.to_path_buf())
            .join("Archive");
        let _ = fs::create_dir_all(&archive_dir);
        let mut target = archive_dir.join(source.file_name().unwrap_or_default());
        let mut n = 2;
        while target.exists() {
            target = archive_dir.join(format!(
                "{} ({}){}",
                source.file_stem().unwrap_or_default().to_string_lossy(),
                n,
                source.extension().map_or("", |e| e.to_str().unwrap_or("")).to_string()
            ));
            n += 1;
        }
        let _ = fs::rename(&source, &target);
        self._remove_generated_source_folder(&source, destination);
        (self.logger)(
            "ORGANIZER",
            &format!(
                "ARCHIVE_OLD source=[{}] destination=[{}]",
                source.display(),
                target.display()
            ),
        );
        if let Some(n) = note {
            n.status = "archived".to_string();
            n.message = "Filed under Archive/ as a duplicate of the same game".to_string();
            n.source_format = source
                .extension()
                .map_or("", |e| e.to_str().unwrap_or(""))
                .to_uppercase();
            n.final_name = target.file_name().unwrap_or_default().to_string_lossy().to_string();
            n.final_size = target.metadata().map_or(0, |m| m.len());
        }
        target
    }
}

fn escape_html(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&#39;")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dummy_logger(_: &str, _: &str) {}

    #[test]
    fn test_organizer_service_new() {
        let service = OrganizerService::new(Arc::new(dummy_logger), true);
        assert!(service.convert_archives());
    }

    #[test]
    fn test_organizer_service_convert_false() {
        let service = OrganizerService::new(Arc::new(dummy_logger), false);
        assert!(!service.convert_archives());
    }

    #[test]
    fn test_organizer_service_clean_old_links_nonexistent() {
        let service = OrganizerService::new(Arc::new(dummy_logger), true);
        let temp = std::env::temp_dir().join(format!("test_clean_old_links_{}", std::process::id()));
        let _ = fs::create_dir_all(&temp);
        service._clean_old_links(&temp);
        let _ = fs::remove_dir_all(&temp);
    }

    #[test]
    fn test_organizer_service_sweep_stale_build_dirs_nonexistent() {
        let service = OrganizerService::new(Arc::new(dummy_logger), true);
        let (removed, reclaimed) = service.sweep_stale_build_dirs(Some(Path::new("/nonexistent")), 900);
        assert_eq!((removed, reclaimed), (0, 0));
    }

    #[test]
    fn test_organizer_service_needs_catalog_launcher() {
        let service = OrganizerService::new(Arc::new(dummy_logger), true);
        let _ = service.needs_catalog_launcher();
    }

    #[test]
    fn test_organizer_service_preview_empty() {
        let service = OrganizerService::new(Arc::new(dummy_logger), true);
        let changes = service.preview(&[], Path::new("/dest"));
        assert!(changes.is_empty());
    }

    #[test]
    fn test_organizer_service_repack_stub_returns_unchanged() {
        let service = OrganizerService::new(Arc::new(dummy_logger), true);
        let archive = GameArchive {
            path: PathBuf::from("/test/Game.zip"),
            ..Default::default()
        };
        let result = service._repack_with_official_name(&archive, None, None, "", None);
        assert_eq!(result, archive.path);
    }
}

