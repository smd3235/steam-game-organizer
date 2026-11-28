//! Comprehensive error type system for Steam Game Organizer.
//! Every error carries context (component, operation, correlation_id) so logs
//! can be traced end-to-end from UI click through service call to failure.
//!
//! 2026-11-26: Created as part of comprehensive debugging/logging system.

use std::backtrace::Backtrace;
use std::fmt;
use std::fmt::Debug;
use std::sync::Arc;

/// Severity levels for error classification.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ErrorSeverity {
    /// Informational - something happened but no action needed
    Info,
    /// Warning - something unexpected but recoverable
    Warning,
    /// Error - operation failed, user action may be needed
    Error,
    /// Critical - system may be in an inconsistent state
    Critical,
}

/// Context information attached to every error.
#[derive(Debug, Clone)]
pub struct ErrorContext {
    /// Component where the error occurred (e.g., "SCAN", "REVIEW", "ARCHIVE_SERVICE")
    pub component: String,
    /// Operation being performed (e.g., "discover_archives", "extract_zip")
    pub operation: String,
    /// Correlation ID for tracing related events across components
    pub correlation_id: String,
    /// Additional key-value details
    pub details: Vec<(String, String)>,
    /// Backtrace captured at error creation time
    pub backtrace: Option<String>,
}

impl ErrorContext {
    pub fn new(component: &str, operation: &str, correlation_id: &str) -> Self {
        ErrorContext {
            component: component.to_string(),
            operation: operation.to_string(),
            correlation_id: correlation_id.to_string(),
            details: Vec::new(),
            backtrace: Some(format!("{:?}", Backtrace::capture())),
        }
    }

    pub fn detail(mut self, key: &str, value: &str) -> Self {
        self.details.push((key.to_string(), value.to_string()));
        self
    }
}

impl Default for ErrorContext {
    fn default() -> Self {
        ErrorContext {
            component: "UNKNOWN".to_string(),
            operation: "unknown".to_string(),
            correlation_id: "none".to_string(),
            details: Vec::new(),
            backtrace: None,
        }
    }
}

/// Primary error type for the application.
#[derive(Debug)]
pub struct OrganizerError {
    pub severity: ErrorSeverity,
    pub context: ErrorContext,
    /// Human-readable error message
    pub message: String,
    /// Underlying source error, if any
    pub source: Option<String>,
    /// Whether this error is recoverable (user can retry)
    pub recoverable: bool,
    /// Suggested user action, if any
    pub suggested_action: Option<String>,
}

impl OrganizerError {
    pub fn new(
        severity: ErrorSeverity,
        component: &str,
        operation: &str,
        correlation_id: &str,
        message: &str,
    ) -> Self {
        OrganizerError {
            severity,
            context: ErrorContext::new(component, operation, correlation_id),
            message: message.to_string(),
            source: None,
            recoverable: true,
            suggested_action: None,
        }
    }

    pub fn with_source(mut self, source: &str) -> Self {
        self.source = Some(source.to_string());
        self
    }

    pub fn with_detail(mut self, key: &str, value: &str) -> Self {
        self.context = self.context.detail(key, value);
        self
    }

    pub fn with_action(mut self, action: &str) -> Self {
        self.suggested_action = Some(action.to_string());
        self
    }

    pub fn unrecoverable(mut self) -> Self {
        self.recoverable = false;
        self
    }

    /// Format the error as a detailed log line with HH:MM:SS timestamp.
    pub fn log_line(&self, timestamp: &str) -> String {
        let mut line = format!(
            "[{}] [{:?}] [{}] [{}] [{}] {}",
            timestamp,
            self.severity,
            self.context.component,
            self.context.operation,
            self.context.correlation_id,
            self.message
        );
        if let Some(src) = &self.source {
            line.push_str(&format!(" | source={}", src));
        }
        for (k, v) in &self.context.details {
            line.push_str(&format!(" | {}={}", k, v));
        }
        if let Some(action) = &self.suggested_action {
            line.push_str(&format!(" | action={}", action));
        }
        if let Some(bt) = &self.context.backtrace {
            line.push_str(&format!("\n  backtrace: {}", bt));
        }
        line
    }
}

impl fmt::Display for OrganizerError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "[{:?}] {}/{} - {}",
            self.severity, self.context.component, self.context.operation, self.message
        )
    }
}

impl std::error::Error for OrganizerError {}

/// Conversion from std::io::Error
impl From<std::io::Error> for OrganizerError {
    fn from(err: std::io::Error) -> Self {
        OrganizerError::new(
            ErrorSeverity::Error,
            "UNKNOWN",
            "io_operation",
            "none",
            &format!("I/O error: {}", err),
        )
        .with_source(&format!("std::io::Error: {}", err))
    }
}

/// Conversion from serde_json::Error
impl From<serde_json::Error> for OrganizerError {
    fn from(err: serde_json::Error) -> Self {
        OrganizerError::new(
            ErrorSeverity::Error,
            "UNKNOWN",
            "json_parse",
            "none",
            &format!("JSON parse error: {}", err),
        )
        .with_source(&format!("serde_json::Error: {}", err))
    }
}

/// Error type for cancellation operations.
#[derive(Debug, Clone)]
pub struct CancellationError;

impl fmt::Display for CancellationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Operation cancelled")
    }
}

impl std::error::Error for CancellationError {}

impl CancellationError {
    pub fn new() -> Self {
        CancellationError
    }
}

impl Default for CancellationError {
    fn default() -> Self {
        CancellationError
    }
}

/// Result type alias for the application.
pub type OrganizerResult<T> = Result<T, OrganizerError>;

/// Macro to create an OrganizerError with context and logging.
/// Usage: err!(component, operation, "message", severity=ErrorSeverity::Error)
///        err!(component, operation, "message with detail: {}", value, source=some_err)
#[macro_export]
macro_rules! err {
    ($component:expr, $operation:expr, $msg:expr) => {
        OrganizerError::new(ErrorSeverity::Error, $component, $operation, "", $msg)
    };
    ($component:expr, $operation:expr, $msg:expr, severity=$sev:expr) => {
        OrganizerError::new($sev, $component, $operation, "", $msg)
    };
    ($component:expr, $operation:expr, $msg:expr, corr=$corr:expr) => {
        OrganizerError::new(ErrorSeverity::Error, $component, $operation, $corr, $msg)
    };
    ($component:expr, $operation:expr, $msg:expr, detail=($k:expr, $v:expr)) => {
        OrganizerError::new(ErrorSeverity::Error, $component, $operation, "", $msg)
            .with_detail($k, $v)
    };
}

/// Macro to log an OrganizerError through the logger.
/// Usage: log_error!(logger, $component, $operation, $corr, $severity, $message)
#[macro_export]
macro_rules! log_error {
    ($logger:expr, $component:expr, $operation:expr, $corr:expr, $severity:expr, $msg:expr) => {
        let err = OrganizerError::new($severity, $component, $operation, $corr, $msg);
        let ts = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| {
                let secs = d.as_secs();
                let h = (secs / 3600) % 24;
                let m = (secs / 60) % 60;
                let s = secs % 60;
                format!("{h:02}:{m:02}:{s:02}")
            })
            .unwrap_or_default();
        $logger.write(
            match $severity {
                ErrorSeverity::Info => "INFO",
                ErrorSeverity::Warning => "WARN",
                ErrorSeverity::Error => "ERROR",
                ErrorSeverity::Critical => "CRIT",
            },
            $component,
            &err.log_line(&ts),
            $corr,
        );
    };
}

/// Macro to trace operation entry/exit with timing.
/// Usage: trace_op!(logger, component, operation, correlation_id, { ... code ... })
#[macro_export]
macro_rules! trace_op {
    ($logger:expr, $component:expr, $operation:expr, $corr:expr, $block:block) => {{
        let _start = std::time::Instant::now();
        let corr = if $corr.is_empty() {
            $logger.correlation_id()
        } else {
            $corr.to_string()
        };
        let ts = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| {
                let secs = d.as_secs();
                let h = (secs / 3600) % 24;
                let m = (secs / 60) % 60;
                let s = secs % 60;
                format!("{h:02}:{m:02}:{s:02}")
            })
            .unwrap_or_default();
        $logger.write(
            "INFO",
            $component,
            &format!("OP_START {}", $operation),
            &corr,
        );
        let result = $block;
        let elapsed = _start.elapsed();
        $logger.write(
            "INFO",
            $component,
            &format!("OP_END {} elapsed_ms={}", $operation, elapsed.as_millis()),
            &corr,
        );
        result
    }};
}

/// Watchdog entry for tracking long-running operations.
#[derive(Debug, Clone)]
pub struct WatchdogEntry {
    pub id: u64,
    pub operation: String,
    pub component: String,
    pub correlation_id: String,
    pub started_at: std::time::Instant,
    pub timeout_ms: u64,
    pub completed: bool,
}

/// Watchdog system for detecting hung operations.
pub struct Watchdog(Arc<WatchdogInner>);

struct WatchdogInner {
    entries: std::sync::Mutex<Vec<WatchdogEntry>>,
    next_id: std::sync::Mutex<u64>,
    running: std::sync::atomic::AtomicBool,
    logger: std::sync::Arc<crate::core::logger::AppLogger>,
    default_timeout_ms: u64,
}

impl Clone for Watchdog {
    fn clone(&self) -> Self {
        Watchdog(self.0.clone())
    }
}

impl Debug for Watchdog {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Watchdog").finish()
    }
}

impl Drop for Watchdog {
    fn drop(&mut self) {
        self.0.running.store(false, std::sync::atomic::Ordering::Relaxed);
    }
}

impl Watchdog {
    pub fn new(
        logger: std::sync::Arc<crate::core::logger::AppLogger>,
        default_timeout_ms: u64,
    ) -> Self {
        let inner = Arc::new(WatchdogInner {
            entries: std::sync::Mutex::new(Vec::new()),
            next_id: std::sync::Mutex::new(0),
            running: std::sync::atomic::AtomicBool::new(true),
            logger,
            default_timeout_ms,
        });
        // Spawn a background monitor thread for real-time hang detection.
        // It calls check_timeouts() every 5 seconds so hung operations are
        // caught even when no UI code is actively polling the watchdog.
        let monitor = inner.clone();
        std::thread::Builder::new()
            .name("watchdog-monitor".into())
            .spawn(move || {
                let interval = std::time::Duration::from_secs(5);
                while monitor.running.load(std::sync::atomic::Ordering::Relaxed) {
                    std::thread::sleep(interval);
                    if !monitor.running.load(std::sync::atomic::Ordering::Relaxed) {
                        break;
                    }
                    Watchdog(monitor.clone()).check_timeouts();
                }
            })
            .expect("failed to spawn watchdog monitor thread");
        Watchdog(inner)
    }

    /// Register a new operation to watch. Returns a monotonically increasing ID
    /// that can be passed to `complete()` to mark the operation as done.
    pub fn start(
        &self,
        operation: &str,
        component: &str,
        correlation_id: &str,
        timeout_ms: Option<u64>,
    ) -> u64 {
        let id = {
            let mut next = self.0.next_id.lock().unwrap_or_else(|e| e.into_inner());
            *next += 1;
            *next
        };
        let entry = WatchdogEntry {
            id,
            operation: operation.to_string(),
            component: component.to_string(),
            correlation_id: correlation_id.to_string(),
            started_at: std::time::Instant::now(),
            timeout_ms: timeout_ms.unwrap_or(self.0.default_timeout_ms),
            completed: false,
        };
        self.0.entries.lock().unwrap_or_else(|e| e.into_inner()).push(entry);
        id
    }

    /// Mark an operation as completed.
    pub fn complete(&self, id: u64) {
        let mut entries = self.0.entries.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(entry) = entries.iter_mut().find(|e| e.id == id) {
            entry.completed = true;
        }
    }

    /// Check for timed-out operations and log warnings.
    pub fn check_timeouts(&self) {
        let now = std::time::Instant::now();
        let entries = self.0.entries.lock().unwrap();
        for entry in entries.iter() {
            if !entry.completed {
                let elapsed = now.duration_since(entry.started_at).as_millis() as u64;
                if elapsed > entry.timeout_ms {
                    self.0.logger.write(
                        "WARN",
                        &entry.component,
                        &format!(
                            "WATCHDOG_TIMEOUT operation={} elapsed_ms={} timeout_ms={} corr={}",
                            entry.operation, elapsed, entry.timeout_ms, entry.correlation_id
                        ),
                        &entry.correlation_id,
                    );
                }
            }
        }
    }

    /// Clean up completed entries.
    pub fn cleanup(&self) {
        let mut entries = self.0.entries.lock().unwrap();
        entries.retain(|e| !e.completed);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_error_creation() {
        let err = OrganizerError::new(
            ErrorSeverity::Error,
            "SCAN",
            "discover_archives",
            "corr123",
            "Failed to find archives",
        )
        .with_detail("path", "/games")
        .with_action("Check library root configuration");

        assert_eq!(err.context.component, "SCAN");
        assert_eq!(err.context.operation, "discover_archives");
        assert_eq!(err.context.correlation_id, "corr123");
        assert_eq!(err.message, "Failed to find archives");
        assert_eq!(err.severity, ErrorSeverity::Error);
        assert!(err.recoverable);
    }

    #[test]
    fn test_error_log_line() {
        let err = OrganizerError::new(
            ErrorSeverity::Critical,
            "ARCHIVE_SERVICE",
            "extract_zip",
            "corr456",
            "Corrupt archive",
        )
        .with_source("zip::ZipError")
        .unrecoverable();

        let line = err.log_line("[14:30:45]");
        assert!(line.contains("Critical"));
        assert!(line.contains("ARCHIVE_SERVICE"));
        assert!(line.contains("extract_zip"));
        assert!(line.contains("Corrupt archive"));
        assert!(line.contains("zip::ZipError"));
        assert!(!err.recoverable);
    }

    #[test]
    fn test_watchdog() {
        let logger = std::sync::Arc::new(
            crate::core::logger::AppLogger::new(
                std::env::temp_dir().join("watchdog_test.log"),
                "INFO",
                false,
                false,
            )
            .unwrap(),
        );
        let wd = Watchdog::new(logger.clone(), 1000);

        let id = wd.start("test_op", "TEST", "corr1", Some(50));
        std::thread::sleep(std::time::Duration::from_millis(100));
        wd.check_timeouts();
        wd.complete(id);
    }
}
