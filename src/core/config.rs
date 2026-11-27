//! Configuration: the paths this app writes to, and the user's chosen settings.
//!
//! AppConfig owns every path the app writes under the project root — config/, cache/,
//! logs/, debug/ — plus the library root, which lives outside it. Settings are read
//! from and written to config/settings.json as a JSON object, with a tolerated
//! schema so a hand-edited or truncated file never prevents startup.
//!
//! A frozen exe also mirrors config into %LOCALAPPDATA% so an update that extracts
//! the bundle to a new folder does not wipe the setup. sync_to_appdata() copies each
//! config file there on write, and _migrate_from_appdata() brings them back when the
//! local tree is fresh or invalid.
//!
//! 2026-11-25: Converted from `core/config.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use time::OffsetDateTime;
use serde_json;
use std::collections::HashSet;
use std::env;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

use crate::core::constants::APP_NAME;
use crate::core::path_safety::safe_create_dir_all;

pub const ROTATED_LOGS: u32 = 10;

fn home_dir() -> PathBuf {
    env::var("USERPROFILE")
        .map(PathBuf::from)
        .unwrap_or_default()
}

/// All paths and settings the app persists, rooted on the project directory.
///
/// project_root is where this code lives; every path below it (config/, cache/,
/// logs/, debug/) is created lazily. library_root is the game library the user
/// configured, which lives outside the project. settings holds the parsed
/// contents of config/settings.json; settings_version is reserved for future
/// migration of the settings schema.
#[derive(Debug, Clone)]
pub struct AppConfig {
    pub project_root: PathBuf,
    pub library_root: Option<PathBuf>,
    pub developer_mode: bool,
    pub mock_mode: bool,
    pub settings: serde_json::Value,
    pub settings_version: i32,
    pub log_file: Option<PathBuf>,
    pub config_dir: PathBuf,
    pub cache_dir: PathBuf,
    pub artwork_dir: PathBuf,
    pub log_dir: PathBuf,
    pub debug_dir: PathBuf,
    pub settings_file: PathBuf,
    pub state_file: PathBuf,
}

impl Default for AppConfig {
    fn default() -> Self {
        AppConfig {
            project_root: PathBuf::new(),
            library_root: None,
            developer_mode: false,
            mock_mode: false,
            settings: serde_json::json!({}),
            settings_version: 0,
            log_file: None,
            config_dir: PathBuf::new(),
            cache_dir: PathBuf::new(),
            artwork_dir: PathBuf::new(),
            log_dir: PathBuf::new(),
            debug_dir: PathBuf::new(),
            settings_file: PathBuf::new(),
            state_file: PathBuf::new(),
        }
    }
}

impl AppConfig {
    pub fn default_library_root() -> PathBuf {
        home_dir().join("Downloads/Games")
    }

    fn appdata_config_dir() -> Option<PathBuf> {
        if cfg!(target_os = "windows") {
            if let Ok(base) = env::var("LOCALAPPDATA") {
                return Some(PathBuf::from(base).join(APP_NAME).join("config"));
            }
        }
        None
    }

    pub fn new(project_root: &Path) -> Self {
        let project_root = project_root
            .canonicalize()
            .unwrap_or_else(|_| project_root.to_path_buf());
        let config_dir = project_root.join("config");
        let cache_dir = project_root.join("cache");
        let artwork_dir = cache_dir.join("artwork");
        let log_dir = project_root.join("logs");
        let debug_dir = project_root.join("debug");
        let settings_file = config_dir.join("settings.json");
        let state_file = config_dir.join("scan-state.json");

        let mut config = AppConfig {
            project_root,
            library_root: None,
            developer_mode: false,
            mock_mode: false,
            settings: serde_json::json!({}),
            settings_version: 0,
            log_file: None,
            config_dir: config_dir.clone(),
            cache_dir,
            artwork_dir,
            log_dir: log_dir.clone(),
            debug_dir,
            settings_file,
            state_file,
        };

        let test_log = env::var("STEAM_GAME_ORGANIZER_TEST_LOG");
        if let Ok(test_log) = test_log {
            config.log_file = Some(PathBuf::from(test_log));
        } else if config.log_file.is_none() {
            let stamp = OffsetDateTime::now_utc()
                                .format(&time::format_description::parse_borrowed::<3>("[year][month][day][hour][minute][second]").unwrap())
                .unwrap_or_default();
            config.log_file = Some(log_dir.join(format!("organizer-{}.log", stamp)));
            config._rotate_logs();
        }
        config._migrate_from_appdata();
        config.load();
        if config.library_root.is_none() {
            config.library_root = Some(AppConfig::default_library_root());
        }
        config
    }

    fn _rotate_logs(&self) {
        if !self.log_dir.is_dir() {
            return;
        }
        let mut logs: Vec<PathBuf> = match fs::read_dir(&self.log_dir) {
            Ok(entries) => entries
                .filter_map(|e| e.ok())
                .map(|e| e.path())
                .filter(|p| {
                    p.file_name()
                        .and_then(|n| n.to_str())
                        .is_some_and(|s| s.starts_with("organizer-"))
                })
                .filter(|p| p.extension().is_some_and(|ext| ext == "log"))
                .collect(),
            Err(_) => Vec::new(),
        };
        logs.sort_by(|a, b| {
            let ma = a
                .metadata()
                .and_then(|m| m.modified())
                .unwrap_or(SystemTime::UNIX_EPOCH);
            let mb = b
                .metadata()
                .and_then(|m| m.modified())
                .unwrap_or(SystemTime::UNIX_EPOCH);
            mb.cmp(&ma)
        });
        for old in logs.iter().skip(ROTATED_LOGS as usize) {
            let _ = fs::remove_file(old);
        }
    }

    fn _migrate_from_appdata(&self) {
        let appdata = Self::appdata_config_dir();
        if appdata.is_none() {
            return;
        }
        let appdata = appdata.unwrap();
        let appdata_settings = appdata.join("settings.json");
        if !appdata_settings.is_file() {
            return;
        }

        let local_is_valid = if self.settings_file.is_file() {
            match fs::read_to_string(&self.settings_file) {
                Ok(text) => match serde_json::from_str::<serde_json::Value>(&text) {
                    Ok(data) => {
                        if let Some(root) = data.get("library_root").and_then(|v| v.as_str()) {
                            PathBuf::from(root).is_dir()
                        } else {
                            false
                        }
                    }
                    Err(_) => false,
                },
                Err(_) => false,
            }
        } else {
            false
        };

        if local_is_valid {
            return;
        }

        let project_root_str = self.project_root.to_str().unwrap_or("");
        let _ = safe_create_dir_all(&self.config_dir, &[project_root_str]);
        if let Ok(entries) = fs::read_dir(&appdata) {
            for item in entries.filter_map(|e| e.ok()) {
                if item.path().is_file() {
                    let dest = self.config_dir.join(item.file_name());
                    let _ = fs::copy(item.path(), dest);
                }
            }
        }
    }

    pub fn sync_to_appdata(&self) {
        let appdata = Self::appdata_config_dir();
        if appdata.is_none() {
            return;
        }
        let appdata = appdata.unwrap();
        let appdata_root = appdata.parent().unwrap_or(&appdata).to_str().unwrap_or("");
        let _ = safe_create_dir_all(&appdata, &[appdata_root]);
        if self.config_dir.is_dir() {
            if let Ok(entries) = fs::read_dir(&self.config_dir) {
                for item in entries.filter_map(|e| e.ok()) {
                    if item.path().is_file() {
                        let _ = fs::copy(item.path(), appdata.join(item.file_name()));
                    }
                }
            }
        }
    }

    pub fn convert_archives(&self) -> bool {
        self.settings
            .get("convert_archives")
            .and_then(|v| v.as_bool())
            .unwrap_or(true)
    }

    pub fn set_convert_archives(&mut self, value: bool) {
        if let Some(obj) = self.settings.as_object_mut() {
            obj.insert(
                "convert_archives".to_string(),
                serde_json::Value::Bool(value),
            );
        }
        self.save();
    }

    pub fn extract_folders(&self) -> Vec<PathBuf> {
        let values = self.settings.get("extract_folders");
        let values = match values {
            Some(v) if v.is_array() => v.as_array().unwrap().to_vec(),
            _ => {
                let mut v = Vec::new();
                if let Some(folder) = self.settings.get("extract_folder").and_then(|v| v.as_str()) {
                    v.push(serde_json::json!(folder));
                }
                v
            }
        };
        let mut cleaned: Vec<PathBuf> = Vec::new();
        let mut seen: HashSet<String> = HashSet::new();
        for value in values {
            if let Some(s) = value.as_str() {
                let path = PathBuf::from(s);
                let key = path.to_string_lossy().to_string();
                if !seen.contains(&key) {
                    seen.insert(key);
                    cleaned.push(path);
                }
            }
        }
        if cleaned.is_empty() {
            cleaned.push(home_dir().join("Downloads/Extracted"));
        }
        cleaned
    }

    pub fn set_extract_folders(&mut self, values: &[PathBuf]) {
        if let Some(obj) = self.settings.as_object_mut() {
            let arr: Vec<serde_json::Value> = values
                .iter()
                .map(|v| serde_json::json!(v.to_string_lossy()))
                .collect();
            obj.insert("extract_folders".to_string(), serde_json::Value::Array(arr));
        }
        self.settings
            .as_object_mut()
            .and_then(|o| o.remove("extract_folder"));
        self.save();
    }

    pub fn extract_folder(&self) -> PathBuf {
        let folders = self.extract_folders();
        folders
            .into_iter()
            .next()
            .unwrap_or_else(|| home_dir().join("Downloads/Extracted"))
    }

    pub fn set_extract_folder(&mut self, value: PathBuf) {
        self.set_extract_folders(&[value]);
    }

    pub fn ensure_directories(&self) {
        for p in [
            &self.config_dir,
            &self.cache_dir,
            &self.artwork_dir,
            &self.log_dir,
            &self.debug_dir,
        ] {
            if p.exists() && !p.is_dir() {
                let file_name = p
                    .file_name()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .to_string();
                let mut backup = p.with_file_name(format!("{}.invalid-file-backup", file_name));
                let mut suffix = 1;
                while backup.exists() {
                    backup =
                        p.with_file_name(format!("{}.invalid-file-backup-{suffix}", file_name));
                    suffix += 1;
                }
                let _ = fs::rename(p, &backup);
            }
            let project_root_str = self.project_root.to_str().unwrap_or("");
            let _ = safe_create_dir_all(p, &[project_root_str]);
        }
    }

    pub fn load(&mut self) {
        match fs::read_to_string(&self.settings_file) {
            Ok(text) => match serde_json::from_str::<serde_json::Value>(&text) {
                Ok(data) => {
                    if !data.is_object() {
                        self.settings = serde_json::json!({});
                        if self.library_root.is_none() {
                            self.library_root = Some(config_default_library_root());
                        }
                        return;
                    }
                    if let Some(value) = data.get("library_root").and_then(|v| v.as_str()) {
                        if !value.is_empty() {
                            self.library_root = Some(self._resolve_library(value));
                        }
                    }
                    self.developer_mode = data
                        .get("developer_mode")
                        .and_then(|v| v.as_bool())
                        .unwrap_or(false);
                    self.settings = data;
                    if self.library_root.is_none() {
                        self.library_root = Some(config_default_library_root());
                    }
                }
                Err(_) => {
                    self.settings = serde_json::json!({});
                    if self.library_root.is_none() {
                        self.library_root = Some(config_default_library_root());
                    }
                }
            },
            Err(_) => {
                self.settings = serde_json::json!({});
                if self.library_root.is_none() {
                    self.library_root = Some(config_default_library_root());
                }
            }
        }
    }

    fn _resolve_library(&self, value: &str) -> PathBuf {
        let p = PathBuf::from(value);
        if p.is_dir() {
            return p.canonicalize().unwrap_or(p);
        }
        let beside = &self.project_root;
        if beside.is_dir() {
            return beside.canonicalize().unwrap_or(beside.to_path_buf());
        }
        p.canonicalize().unwrap_or(p)
    }

    pub fn saved_library_root(&self) -> Option<String> {
        match fs::read_to_string(&self.settings_file) {
            Ok(text) => match serde_json::from_str::<serde_json::Value>(&text) {
                Ok(data) => data
                    .get("library_root")
                    .and_then(|v| v.as_str())
                    .filter(|v| !v.is_empty() && PathBuf::from(v).is_dir())
                    .map(|v| v.to_string()),
                Err(_) => None,
            },
            Err(_) => None,
        }
    }

    pub fn save(&mut self) {
        self.ensure_directories();
        let mut data = self.settings.clone();
        if let Some(obj) = data.as_object_mut() {
            obj.insert(
                "library_root".to_string(),
                serde_json::Value::String(
                    self.library_root
                        .as_ref()
                        .map_or("".to_string(), |p| p.to_string_lossy().to_string()),
                ),
            );
            obj.insert(
                "developer_mode".to_string(),
                serde_json::Value::Bool(self.developer_mode),
            );
        }
        if let Some(root_str) = data.get("library_root").and_then(|v| v.as_str()) {
            if !root_str.is_empty() && !PathBuf::from(root_str).is_dir() {
                if let Some(previous) = self.saved_library_root() {
                    eprintln!(
                        "warning: not saving library root {root_str} - the directory does not exist; keeping {previous}"
                    );
                    if let Some(obj) = data.as_object_mut() {
                        obj.insert(
                            "library_root".to_string(),
                            serde_json::Value::String(previous),
                        );
                    }
                } else {
                    if let Some(obj) = data.as_object_mut() {
                        obj.insert(
                            "library_root".to_string(),
                            serde_json::Value::String("".to_string()),
                        );
                    }
                }
            }
        }
        let config_dir = self.config_dir.clone();
        let tmp_name = format!("settings.{}.tmp", std::process::id());
        let tmp_path = config_dir.join(&tmp_name);
        {
            let mut f = fs::File::create(&tmp_path).unwrap();
            let _ = serde_json::to_writer_pretty(&mut f, &data);
            let _ = f.flush();
        }
        let mut attempt = 0;
        loop {
            match fs::rename(&tmp_path, &self.settings_file) {
                Ok(()) => break,
                Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => {
                    attempt += 1;
                    if attempt >= 4 {
                        let _ = fs::rename(&tmp_path, &self.settings_file);
                        break;
                    }
                    std::thread::sleep(std::time::Duration::from_millis(50 * attempt as u64));
                }
                Err(_e) => {
                    let _ = fs::rename(&tmp_path, &self.settings_file);
                    break;
                }
            }
        }
        let _ = fs::remove_file(&tmp_path);
        self.sync_to_appdata();
    }

    pub fn save_scan_summary(
        &mut self,
        summary: Option<&serde_json::Value>,
    ) -> Option<serde_json::Value> {
        let mut payload = summary.cloned().unwrap_or(serde_json::json!({}));
        payload["recorded_at"] = serde_json::Value::Number(
            ((OffsetDateTime::now_utc().unix_timestamp_nanos() / 1_000_000) as i64).into(),
        );
        match self.save_json_to_file(&self.state_file, &payload) {
            Ok(()) => Some(payload),
            Err(_) => None,
        }
    }

    pub fn load_scan_summary(&self) -> Option<serde_json::Value> {
        match fs::read_to_string(&self.state_file) {
            Ok(text) => match serde_json::from_str::<serde_json::Value>(&text) {
                Ok(data) => {
                    if data.is_object() {
                        Some(data)
                    } else {
                        None
                    }
                }
                Err(_) => None,
            },
            Err(_) => None,
        }
    }

    fn save_json_to_file(
        &self,
        path: &Path,
        data: &serde_json::Value,
    ) -> Result<(), std::io::Error> {
        self.ensure_directories();
        let parent = path.parent().unwrap_or(&self.config_dir);
        let tmp_name = format!("scan-state.{}.tmp", std::process::id());
        let tmp_path = parent.join(&tmp_name);
        {
            let mut f = fs::File::create(&tmp_path)?;
            let _ = serde_json::to_writer_pretty(&mut f, data);
            let _ = f.flush();
        }
        for _ in 0..4 {
            match fs::rename(&tmp_path, path) {
                Ok(()) => return Ok(()),
                Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => {
                    std::thread::sleep(std::time::Duration::from_millis(50));
                }
                Err(e) => return Err(e),
            }
        }
        let _ = fs::remove_file(&tmp_path);
        Err(std::io::Error::other("failed to write file after retries"))
    }
}

fn config_default_library_root() -> PathBuf {
    home_dir().join("Downloads/Games")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_library_root() {
        let root = AppConfig::default_library_root();
        assert!(root.to_string_lossy().contains("Downloads"));
        assert!(root.to_string_lossy().contains("Games"));
    }

    #[test]
    fn test_convert_archives_default_true() {
        let config = AppConfig::new(std::path::Path::new("/tmp"));
        assert!(config.convert_archives());
    }
}
