//! The catalog's side-channel file, and the rule both sides use to decide a game is already unpacked.
//!
//! The catalog is a file on disk that a browser opens directly, and a page opened from `file://` cannot read
//! anything else on the machine - `fetch` and XHR are both blocked there because the document has an opaque
//! origin. A classic `<script src>` is the one thing that does load, which is what makes it possible for a batch
//! run to report back into a page that was written before that run happened.
//!
//! So the app writes `Game Library.status.js` beside the catalog and the page loads it as a sibling script. The
//! status survives the run that is reporting it, which is the entire point: the reader comes back to the browser
//! after two hours and the page finally says what happened.
//!
//! This lives in its own module rather than in `catalog_service` because both that module and
//! `batch_extract_service` need it, and putting it in either would make the two import each other.
//!
//! 2026-11-25: Converted from `services/catalog_status.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use serde_json;
use std::path::{Path, PathBuf};

use crate::constants::APP_NAME;
use crate::within::within;

pub const STATUS_NAME: &str = "Game Library.status.js";
pub const STATUS_GLOBAL: &str = "libraryBatchStatus";
pub const EXTRACT_MARKER: &str = ".sgo-extract-info";

/// Whether a game's folder already holds unpacked files.
///
/// Checked for real files rather than for the folder's existence, because an interrupted run leaves the folder
/// behind - and treating that as finished would silently skip the game it died on, which is the one game the
/// user most wants finished.
pub fn already_extracted(destination: &Path) -> bool {
    destination.is_dir()
        && destination
            .read_dir()
            .map_or(false, |mut entries| entries.next().is_some())
}

/// The marker file path inside an extracted game's folder.
pub fn extract_marker_path(destination: &Path) -> PathBuf {
    destination.join(EXTRACT_MARKER)
}

/// Read the `.sgo-extract-info` marker from an extracted folder, or None.
///
/// Returns the parsed dict (may include archive_size, archive_mtime_ns, extracted_at,
/// extracted_root, needs_install, launch_target, setup_done, installed_at). Returns
/// None when absent, unreadable, or invalid so callers treat pre-marker/manual
/// extractions conservatively.
pub fn read_extract_marker(destination: &Path) -> Option<serde_json::Value> {
    let marker = extract_marker_path(destination);
    match std::fs::read_to_string(&marker) {
        Ok(text) => match serde_json::from_str::<serde_json::Value>(&text) {
            Ok(data) if data.is_object() => Some(data),
            _ => None,
        },
        Err(_) => None,
    }
}

/// Best-effort actual extracted content root for an extracted folder.
///
/// Prefers the marker's `extracted_root` when it points at an existing directory that
/// is under one of the configured extract folders (or when no folders are given).
/// Falls back to `destination` when it exists, else None.
pub fn resolve_extracted_root(destination: &Path, extract_folders: &[PathBuf]) -> Option<PathBuf> {
    let data = match read_extract_marker(destination) {
        Some(d) => d,
        None => return None,
    };
    if let Some(root) = data.get("extracted_root").and_then(|v| v.as_str()) {
        if let Ok(root_path) = Path::new(root).canonicalize() {
            if root_path.is_dir() {
                if extract_folders.is_empty()
                    || extract_folders.iter().any(|f| within(&root_path, f))
                {
                    return Some(root_path);
                }
            }
        }
    }
    let dest = destination.to_path_buf();
    if dest.is_dir() {
        Some(dest)
    } else {
        None
    }
}

/// Resolve an exe path and require it to be a file under configured extract folders.
pub fn _resolve_exe_under_extract_root(exe: &str, extract_folders: &[PathBuf]) -> Option<PathBuf> {
    let folders: Vec<PathBuf> = extract_folders.iter().cloned().collect();
    if folders.is_empty() {
        return None;
    }
    match Path::new(exe).canonicalize() {
        Ok(exe_path) => {
            if exe_path.is_file()
                && exe_path.extension().map_or(false, |e| e == "exe")
                && folders.iter().any(|f| within(&exe_path, f))
            {
                Some(exe_path)
            } else {
                None
            }
        }
        Err(_) => None,
    }
}

pub const LAUNCHER_IGNORE_TOKENS: &[&str] = &[
    "unins",
    "uninst",
    "setup",
    "install",
    "installer",
    "patch",
    "update",
    "updater",
    "redist",
    "vcredist",
    "dxsetup",
    "dotnet",
    "unitycrash",
    "crashreport",
    "crash",
    "config",
    "launcher_settings",
    "helper",
    "bugreport",
    "elevate",
    "createdump",
    "prereq",
    "quicksfv",
    "sfv",
    "ffmpeg",
    "spatial",
    "metadata",
    "injector",
    "java",
    "jre",
    "jabswitch",
    "keytool",
    "policytool",
    "orbd",
    "rmid",
    "rmiregistry",
    "servertool",
    "tnameserv",
    "pack200",
    "unpack200",
    "jjs",
    "jfr",
    "jstat",
    "jstack",
    "jmap",
    "jhat",
    "jinfo",
    "jcmd",
    "jrunscript",
    "jaccess",
    "jaccesswalker",
    "kinit",
    "klist",
    "ktab",
    "javaw",
    "java-rmi",
    "jcontrol",
    "jconsole",
    "jvisualvm",
];

pub const LAUNCHER_PREFER_TOKENS: &[&str] =
    &["game", "start", "play", "launch", "bin", "win64", "x64"];
pub const LAUNCHER_MAX_DEPTH: usize = 3;
pub const LAUNCHER_MAX_CANDIDATES: usize = 250;

/// Return the validated persisted launch target exe for a marker directory, else None.
pub fn get_launch_target(marker_dir: &Path, extract_folders: &[PathBuf]) -> Option<PathBuf> {
    let data = read_extract_marker(marker_dir).unwrap_or_default();
    let target = data.get("launch_target").and_then(|v| v.as_str())?;
    _resolve_exe_under_extract_root(target, extract_folders)
}

/// Persist explicit "installed/setup done" state for a needs-install extraction.
pub fn mark_setup_done(
    destination: &Path,
    extract_folders: &[PathBuf],
    logger: Option<&dyn Fn(&str, &str)>,
) -> Option<serde_json::Value> {
    let dest = match destination.canonicalize() {
        Ok(d) => d,
        Err(_) => return None,
    };
    if !dest.is_dir() {
        return None;
    }
    if !extract_folders.is_empty() && !extract_folders.iter().any(|f| within(&dest, f)) {
        return None;
    }
    let mut data = read_extract_marker(&dest).unwrap_or_default();
    if let Some(obj) = data.as_object_mut() {
        obj.insert("needs_install".to_string(), serde_json::Value::Bool(false));
        obj.insert("setup_done".to_string(), serde_json::Value::Bool(true));
        obj.insert(
            "installed_at".to_string(),
            serde_json::Value::String(chrono::Utc::now().format("%Y-%m-%d %H:%M").to_string()),
        );
    } else {
        return None;
    }
    if let Some(logger) = logger {
        logger(
            "CATALOG",
            &format!("MARKER_UPDATED path=[{}]", dest.display()),
        );
    }
    Some(data)
}

/// True when `path` resolves to `root` or somewhere beneath it.
pub fn path_within(candidate: &Path, root: &Path) -> bool {
    match (candidate.canonicalize(), root.canonicalize()) {
        (Ok(c), Ok(r)) => c == r || c.starts_with(&r),
        _ => false,
    }
}

/// True when the archive's current size or mtime differs from what was recorded at extraction.
pub fn archive_has_changed_since_extraction(destination: &Path, archive_path: &Path) -> bool {
    let data = match read_extract_marker(destination) {
        Some(d) => d,
        None => return false,
    };
    match archive_path.metadata() {
        Ok(current) => {
            let size_match =
                data.get("archive_size").and_then(|v| v.as_u64()) == Some(current.len());
            let mtime_match = data.get("archive_mtime_ns").and_then(|v| v.as_u64())
                == current
                    .modified()
                    .ok()
                    .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                    .map(|d| d.as_nanos() as u64);
            !size_match || !mtime_match
        }
        Err(_) => false,
    }
}

/// The status written next to a brand new catalog: a run has not happened yet, so it says nothing.
pub fn empty_status() -> serde_json::Value {
    serde_json::json!({
        "ran_at": "",
        "category": "",
        "destination": "",
        "total": 0,
        "extracted": 0,
        "skipped": 0,
        "failed": 0,
        "cancelled": 0,
        "already_done": 0,
        "needs_install": 0,
        "elapsed": ""
    })
}

/// A duration as '2h 14m', '14m' or '40s'.
pub fn elapsed_text(seconds: f64) -> String {
    let total = seconds.max(0.0) as i64;
    if total < 60 {
        return format!("{}s", total);
    }
    if total < 3600 {
        return format!("{}m", total / 60);
    }
    format!("{}h {}m", total / 3600, (total % 3600) / 60)
}

/// The status of a finished run, in the shape empty_status() established.
pub fn status_from_run(
    plan_category: &str,
    plan_destination: &str,
    plan_items_len: usize,
    plan_already_done: usize,
    succeeded: usize,
    skipped: usize,
    failed: usize,
    cancelled: usize,
    needs_install: usize,
    started_at: f64,
    finished_at: f64,
) -> serde_json::Value {
    let ran = if started_at > 0.0 && finished_at > 0.0 {
        finished_at - started_at
    } else {
        0.0
    };
    serde_json::json!({
        "ran_at": chrono::Utc::now().format("%Y-%m-%d %H:%M").to_string(),
        "category": plan_category,
        "destination": plan_destination,
        "total": plan_items_len,
        "extracted": succeeded,
        "skipped": skipped,
        "failed": failed,
        "cancelled": cancelled,
        "already_done": plan_already_done,
        "needs_install": needs_install,
        "elapsed": elapsed_text(ran)
    })
}

/// The file's whole contents.
pub fn status_javascript(status: &serde_json::Value) -> String {
    format!(
        "/* Written by {}. Rewritten after every batch run. Safe to delete. */\nwindow.{} = {};\n",
        APP_NAME,
        STATUS_GLOBAL,
        serde_json::to_string(status).unwrap_or_default()
    )
}

/// Write the status file beside the catalog. Returns the path, or None if it could not be written.
pub fn write_status(
    library_root: &Path,
    status: &serde_json::Value,
    logger: Option<&dyn Fn(&str, &str)>,
) -> Option<PathBuf> {
    let path = library_root.join(STATUS_NAME);
    match std::fs::write(&path, status_javascript(status)) {
        Ok(()) => {
            if let Some(logger) = logger {
                logger(
                    "CATALOG",
                    &format!("STATUS_WRITTEN path=[{}]", path.display()),
                );
            }
            Some(path)
        }
        Err(exc) => {
            if let Some(logger) = logger {
                logger(
                    "CATALOG",
                    &format!(
                        "STATUS_WRITE_FAILED path=[{}] error={}",
                        path.display(),
                        exc
                    ),
                );
            }
            None
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_already_extracted_empty_dir() {
        use std::env;
        let temp = env::temp_dir().join(format!("test_already_{}", std::process::id()));
        std::fs::create_dir_all(&temp).ok();
        assert!(!already_extracted(&temp));
        let _ = std::fs::remove_dir_all(&temp);
    }

    #[test]
    fn test_elapsed_text() {
        assert_eq!(elapsed_text(40.0), "40s");
        assert_eq!(elapsed_text(90.0), "1m");
        assert_eq!(elapsed_text(3661.0), "1h 1m");
    }
}
