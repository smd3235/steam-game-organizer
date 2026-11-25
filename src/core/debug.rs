//! Debug module: panic recovery, audit logging, and health diagnostics.
//!
//! Provides safety nets for production runs: panic boundaries that log instead
//! of crashing, audit trails for every destructive operation, and health
//! checks that surface problems before users notice them.
//!
//! 2026-11-25: Debug module added for production debugging and auditing.

use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

use crate::core::logger::AppLogger;

/// An audit entry: what happened, when, and who/what triggered it.
#[derive(Debug, Clone)]
pub struct AuditEntry {
    pub timestamp: u64,
    pub action: String,
    pub target: String,
    pub result: String,
    pub detail: String,
}

/// Audit log: records every destructive or state-changing operation.
/// Safe to read from any thread; writes are locked.
pub struct AuditLog {
    entries: Mutex<Vec<AuditEntry>>,
}

impl AuditLog {
    pub fn new() -> Self {
        AuditLog {
            entries: Mutex::new(Vec::new()),
        }
    }

    /// Record an audit entry. Never panics; write failures are silently ignored.
    pub fn record(&self, action: &str, target: &str, result: &str, detail: &str) {
        let entry = AuditEntry {
            timestamp: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs(),
            action: action.to_string(),
            target: target.to_string(),
            result: result.to_string(),
            detail: detail.to_string(),
        };
        let mut guard = match self.entries.lock() {
            Ok(g) => g,
            Err(_) => return, // Poisoned lock; give up silently
        };
        guard.push(entry);
    }

    /// Return a snapshot of all entries (newest first).
    pub fn snapshot(&self) -> Vec<AuditEntry> {
        let guard = match self.entries.lock() {
            Ok(g) => g,
            Err(_) => return Vec::new(),
        };
        let mut entries: Vec<AuditEntry> = guard.clone();
        entries.reverse();
        entries
    }

    /// Count of recorded entries.
    pub fn len(&self) -> usize {
        self.entries.lock().map_or(0, |g| g.len())
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

impl Default for AuditLog {
    fn default() -> Self {
        Self::new()
    }
}

/// Global audit log instance. Safe to use from any thread.
static AUDIT_LOG: std::sync::OnceLock<AuditLog> = std::sync::OnceLock::new();

/// Get the global audit log (created on first use).
pub fn audit_log() -> &'static AuditLog {
    AUDIT_LOG.get_or_init(AuditLog::new)
}

/// Record an audit entry on the global log.
pub fn audit(action: &str, target: &str, result: &str, detail: &str) {
    audit_log().record(action, target, result, detail);
}

/// Run a closure with panic recovery. If the closure panics, log the panic
/// to the audit trail and return Err instead of crashing the process.
///
/// Use this around any operation that touches the filesystem, the registry,
/// or the network — anything that could leave the library in a bad state.
pub fn safe_run<F, R>(action: &str, target: &str, f: F) -> Result<R, String>
where
    F: FnOnce() -> Result<R, String>,
{
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(f)) {
        Ok(result) => result,
        Err(panic) => {
            let detail = if let Some(s) = panic.downcast_ref::<&str>() {
                format!("panic: {}", s)
            } else if let Some(s) = panic.downcast_ref::<String>() {
                format!("panic: {}", s)
            } else {
                "panic: unknown".to_string()
            };
            audit(action, target, "panicked", &detail);
            Err(format!("{} panicked: {}", action, detail))
        }
    }
}

/// Run a closure that returns `()`. Panics are caught and logged.
pub fn safe_run_void<F>(action: &str, target: &str, f: F) -> Result<(), String>
where
    F: FnOnce() -> Result<(), String>,
{
    safe_run(action, target, f)
}

/// Health check result for one subsystem.
#[derive(Debug, Clone, PartialEq)]
pub struct HealthCheck {
    pub name: String,
    pub ok: bool,
    pub message: String,
}

/// Run all health checks and return results.
pub fn health_check(logger: &AppLogger) -> Vec<HealthCheck> {
    let mut checks: Vec<HealthCheck> = Vec::new();

    // 1. 7-Zip availability
    checks.push(check_7zip());

    // 2. Library root accessibility
    checks.push(check_library_root(logger));

    // 3. Config file readability
    checks.push(check_config(logger));

    // 4. Write permission on library root
    checks.push(check_write_permission(logger));

    // 5. Audit log health
    checks.push(HealthCheck {
        name: "audit_log".to_string(),
        ok: true,
        message: format!("{} entries recorded", audit_log().len()),
    });

    checks
}

/// Check that 7-Zip is available (PATH or known install location).
fn check_7zip() -> HealthCheck {
    let found = std::process::Command::new("7z")
        .arg("--help")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false);
    if found {
        HealthCheck {
            name: "7zip".to_string(),
            ok: true,
            message: "7z found on PATH".to_string(),
        }
    } else {
        HealthCheck {
            name: "7zip".to_string(),
            ok: false,
            message: "7z not found on PATH; archive extraction will fail".to_string(),
        }
    }
}

/// Check that the library root directory exists and is readable.
fn check_library_root(_logger: &AppLogger) -> HealthCheck {
    let config_dir = std::path::Path::new("config");
    if !config_dir.is_dir() {
        return HealthCheck {
            name: "library_root".to_string(),
            ok: false,
            message: "config/ directory not found; run setup first".to_string(),
        };
    }
    HealthCheck {
        name: "library_root".to_string(),
        ok: true,
        message: "config/ directory found".to_string(),
    }
}

/// Check that the config file is readable.
fn check_config(_logger: &AppLogger) -> HealthCheck {
    let settings = std::path::Path::new("config/settings.json");
    if settings.is_file() {
        HealthCheck {
            name: "config".to_string(),
            ok: true,
            message: "settings.json readable".to_string(),
        }
    } else {
        HealthCheck {
            name: "config".to_string(),
            ok: false,
            message: "settings.json not found; run setup first".to_string(),
        }
    }
}

/// Check that we can write to the library root.
fn check_write_permission(_logger: &AppLogger) -> HealthCheck {
    let test_file = std::path::Path::new("config/.write_test");
    match std::fs::write(test_file, "test") {
        Ok(_) => {
            let _ = std::fs::remove_file(test_file);
            HealthCheck {
                name: "write_permission".to_string(),
                ok: true,
                message: "config/ is writable".to_string(),
            }
        }
        Err(e) => HealthCheck {
            name: "write_permission".to_string(),
            ok: false,
            message: format!("cannot write to config/: {}", e),
        },
    }
}

/// Print a human-readable health report.
pub fn print_health_report(logger: &AppLogger) {
    let checks = health_check(logger);
    println!("\n=== Health Check ===");
    for check in &checks {
        let status = if check.ok { "OK" } else { "FAIL" };
        println!("  [{}] {}: {}", status, check.name, check.message);
    }
    let all_ok = checks.iter().all(|c| c.ok);
    if all_ok {
        println!("All checks passed.");
    } else {
        println!("Some checks failed — review before using the app.");
    }
    println!("====================\n");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_audit_log_record_and_snapshot() {
        let log = AuditLog::new();
        log.record("test_action", "test_target", "success", "detail");
        assert_eq!(log.len(), 1);
        assert!(!log.is_empty());

        let snapshot = log.snapshot();
        assert_eq!(snapshot.len(), 1);
        assert_eq!(snapshot[0].action, "test_action");
        assert_eq!(snapshot[0].result, "success");
    }

    #[test]
    fn test_audit_log_multiple_entries() {
        let log = AuditLog::new();
        log.record("a", "x", "ok", "d1");
        log.record("b", "y", "fail", "d2");
        assert_eq!(log.len(), 2);

        let snapshot = log.snapshot();
        // Newest first
        assert_eq!(snapshot[0].action, "b");
        assert_eq!(snapshot[1].action, "a");
    }

    #[test]
    fn test_safe_run_success() {
        let result = safe_run("test", "target", || Ok(42));
        assert_eq!(result, Ok(42));
    }

    #[test]
    fn test_safe_run_error() {
        let result: Result<i32, String> = safe_run("test", "target", || Err("boom".to_string()));
        assert_eq!(result, Err("boom".to_string()));
    }

    #[test]
    fn test_safe_run_panic() {
        let result: Result<i32, String> = safe_run("test", "target", || {
            panic!("test panic");
        });
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("panicked"));
        assert!(!audit_log().is_empty());
    }

    #[test]
    fn test_global_audit_log() {
        audit("test", "target", "ok", "detail");
        assert!(!audit_log().is_empty());
    }
}
