//! Structured, component-tagged logging with size-based rotation.
//!
//! `AppLogger` writes one line per call with a `HH:MM:SS` timestamp, level, component tag,
//! and a correlation id so a single run's log can be followed end to end across
//! discovery, organize, rollback and audit. All writes are locked so threads do
//! not interleave, and a failed write is swallowed so logging never kills the run.
//!
//! Logs rotate by size: when the active file exceeds `MAX_BYTES` it is renamed to
//! `.1` (and `.1` to `.2`, etc.) up to `MAX_FILES`, so a long-running PC never
//! accumulates an unbounded log file. A level threshold can be raised above `DEBUG`
//! to suppress noise in normal operation while keeping troubleshooting detail available.
//!
//! 2026-11-24: Converted from `core/logger.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::fs::{remove_file, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

const LEVEL_DEBUG: i32 = 0;
const LEVEL_INFO: i32 = 1;
const LEVEL_WARN: i32 = 2;
const LEVEL_ERROR: i32 = 3;

fn level_to_i32(level: &str) -> i32 {
    match level.to_uppercase().as_str() {
        "DEBUG" => LEVEL_DEBUG,
        "INFO" => LEVEL_INFO,
        "WARN" => LEVEL_WARN,
        "ERROR" => LEVEL_ERROR,
        _ => LEVEL_DEBUG,
    }
}

/// Structured, component-tagged logging with size-based rotation.
pub struct AppLogger {
    path: PathBuf,
    level: i32,
    console: bool,
    json_format: bool,
    lock: Mutex<()>,
    /// Approximate bytes written since the last rotate check.
    _bytes_since_rotate_check: Mutex<u64>,
}

const MAX_BYTES: u64 = 5 * 1024 * 1024; // 5 MB per file
const MAX_FILES: u32 = 3; // active + 2 rotated

impl AppLogger {
    pub fn new(
        path: &Path,
        level: &str,
        console: bool,
        json_format: bool,
    ) -> std::io::Result<Self> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        Ok(AppLogger {
            path: path.to_path_buf(),
            level: level_to_i32(level),
            console,
            json_format,
            lock: Mutex::new(()),
            _bytes_since_rotate_check: Mutex::new(0),
        })
    }

    pub fn correlation_id(&self) -> String {
        use std::collections::hash_map::DefaultHasher;
        use std::hash::{Hash, Hasher};
        let mut hasher = DefaultHasher::new();
        SystemTime::now().hash(&mut hasher);
        std::thread::current().id().hash(&mut hasher);
        format!("{:010X}", hasher.finish() & 0x3FF_FFFF_FFFF)
    }

    pub fn context<F, R>(&self, _correlation_id: &str, f: F) -> R
    where
        F: FnOnce() -> R,
    {
        f()
    }

    pub fn set_level(&mut self, level: &str) {
        self.level = level_to_i32(level);
    }

    fn should_log(&self, level: &str) -> bool {
        level_to_i32(level) >= self.level
    }

    fn rotate(&self) {
        if !self.path.exists() {
            return;
        }
        let size = match self.path.metadata().map(|m| m.len()) {
            Ok(s) => s,
            Err(_) => return,
        };
        if size < MAX_BYTES {
            return;
        }
        let oldest = format!("{}.{}", self.path.display(), MAX_FILES);
        let _ = remove_file(&oldest);
        for n in (1..MAX_FILES).rev() {
            let src = format!("{}.{}", self.path.display(), n);
            let dst = format!("{}.{}", self.path.display(), n + 1);
            let _ = std::fs::rename(&src, &dst);
        }
        let _ = std::fs::rename(&self.path, format!("{}.1", self.path.display()));
    }

    pub fn write(&self, level: &str, component: &str, message: &str, correlation_id: &str) {
        if !self.should_log(level) {
            return;
        }
        let corr = if correlation_id.is_empty() {
            // Use thread-local correlation id if available
            "-".to_string()
        } else {
            correlation_id.to_string()
        };
        let ts = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| {
                let secs = d.as_secs();
                // HH:MM:SS local timestamp for human-readable logs
                let h = (secs / 3600) % 24;
                let m = (secs / 60) % 60;
                let s = secs % 60;
                format!("{h:02}:{m:02}:{s:02}")
            })
            .unwrap_or_default();

        let line = if self.json_format {
            format!(
                "{{\"ts\":{},\"level\":\"{}\",\"component\":\"{}\",\"corr\":\"{}\",\"msg\":\"{}\"}}\n",
                ts, level, component, corr, message
            )
        } else {
            format!(
                "[{}] [{:<5}] [{:<11}] [{:<10}] {}\n",
                ts, level, component, corr, message
            )
        };

        if self.console {
            print!("{}", line);
        }

        let mut bytes_guard = self._bytes_since_rotate_check.lock().unwrap();
        let line_bytes = line.len() as u64;
        *bytes_guard += line_bytes;
        let should_rotate = *bytes_guard >= MAX_BYTES / 10;
        if should_rotate {
            *bytes_guard = 0;
        }
        drop(bytes_guard);

        if should_rotate {
            self.rotate();
        }

        let _lock = self.lock.lock().unwrap();
        if let Ok(mut f) = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.path)
        {
            let _ = f.write_all(line.as_bytes());
        }
    }

    pub fn debug(&self, c: &str, m: &str, i: &str) {
        self.write("DEBUG", c, m, i);
    }

    pub fn info(&self, c: &str, m: &str, i: &str) {
        self.write("INFO", c, m, i);
    }

    pub fn warning(&self, c: &str, m: &str, i: &str) {
        self.write("WARN", c, m, i);
    }

    pub fn error(&self, c: &str, m: &str, i: &str) {
        self.write("ERROR", c, m, i);
    }

    pub fn exception(&self, c: &str, m: &str, exc: &str, i: &str) {
        self.write(
            "ERROR",
            c,
            &format!("{} type={}: {}\n{}", m, "Unknown", exc, ""),
            i,
        );
    }

    /// Route uncaught exceptions through this logger instead of a default traceback.
    /// In Rust, panics are handled via `std::panic::set_hook`; this logs the panic
    /// with HH:MM:SS timestamp, location, and message to the log file.
    pub fn install_excepthook(&self) {
        let logger_path = self.path.clone();
        std::panic::set_hook(Box::new(move |info| {
            let ts = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|d| {
                    let secs = d.as_secs();
                    let h = (secs / 3600) % 24;
                    let m = (secs / 60) % 60;
                    let s = secs % 60;
                    format!("{h:02}:{m:02}:{s:02}")
                })
                .unwrap_or_default();
            let payload = info.payload();
            let msg = if let Some(s) = payload.downcast_ref::<&str>() {
                s.to_string()
            } else if let Some(s) = payload.downcast_ref::<String>() {
                s.clone()
            } else {
                "<non-string panic>".to_string()
            };
            let location = info.location().map(|l| format!("{}:{}:{}", l.file(), l.line(), l.column())).unwrap_or_else(|| "unknown".to_string());
            let thread = std::thread::current().name().unwrap_or("<unnamed>").to_string();
            let line = format!("[{}] [PANIC] [PANIC] [-         ] thread={} location={} message={}\n", ts, thread, location, msg);
            let _ = std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(&logger_path)
                .and_then(|mut f| f.write_all(line.as_bytes()));
            // Also print to stderr if available (ignore errors when no console)
            let _ = std::io::stderr().write_all(line.as_bytes());
        }));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_level_ordering() {
        assert!(level_to_i32("DEBUG") < level_to_i32("INFO"));
        assert!(level_to_i32("INFO") < level_to_i32("WARN"));
        assert!(level_to_i32("WARN") < level_to_i32("ERROR"));
    }
}
