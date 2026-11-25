//! Log audit tool: scans logs for errors and warnings.
//! Converted from `tools/log_audit.py`.
//!
//! 2026-11-25: Rust conversion from `tools/log_audit.py` in the Rust conversion.

use std::collections::HashMap;
use std::fs;
use std::path::Path;

/// Patterns that indicate real problems in logs.
const ERROR_PATTERNS: &[(&str, &str)] = &[
    ("Traceback", "Python traceback"),
    ("raise SystemExit", "SystemExit raised"),
    ("FileNotFoundError", "File not found"),
    ("ModuleNotFoundError", "Module not found"),
    ("PermissionError", "Permission denied"),
    ("KeyError", "KeyError"),
    ("IndexError", "IndexError"),
    ("TypeError", "TypeError"),
    ("ValueError", "ValueError"),
    ("AttributeError", "AttributeError"),
    ("ImportError", "Import error"),
    ("OSError", "OS error"),
    ("RuntimeError", "Runtime error"),
    ("unhandled exception", "Unhandled exception"),
    ("fatal error", "Fatal error"),
    ("application error", "Application error"),
];

/// Patterns that indicate warnings worth watching.
const WARN_PATTERNS: &[(&str, &str)] = &[
    ("PRIMARY_UNAVAILABLE", "Artwork primary unavailable"),
    ("ASSET_FAILED", "Artwork asset download failed"),
    ("STEAMGRIDDB_FAILED", "SteamGridDB lookup failed"),
    ("SOURCE_404", "404 on artwork source"),
    ("ARCHIVE_APPID_MISMATCH", "Archive appid mismatch"),
    ("TAGS_UNAVAILABLE", "Steam tags unavailable"),
    ("LOOKUP_NO_ITEMS", "Steam lookup returned no items"),
    ("RETRY_LOOKUP", "Steam lookup retry"),
];

/// Result of auditing one log file.
pub struct LogResult {
    pub path: String,
    pub lines: usize,
    pub errors: Vec<(usize, String, String)>, // (line_number, pattern_label, message)
    pub warnings: Vec<(usize, String, String)>,
}

/// Audit all log files in a directory.
pub fn log_audit(log_dir: &Path) -> Result<LogResult, String> {
    if !log_dir.is_dir() {
        return Err(format!("Log directory not found: {}", log_dir.display()));
    }

    let mut entries: Vec<_> = fs::read_dir(log_dir)
        .map_err(|e| format!("Cannot read log directory: {}", e))?
        .filter_map(|e| e.ok())
        .filter(|e| e.path().extension().map_or(false, |ext| ext == "log"))
        .collect();
    entries.sort_by_key(|e| e.file_name());

    let mut total_errors = 0;
    let mut total_warnings = 0;
    let mut files_audited = 0;
    let mut combined = LogResult {
        path: log_dir.to_string_lossy().to_string(),
        lines: 0,
        errors: Vec::new(),
        warnings: Vec::new(),
    };

    for entry in entries {
        let path = entry.path();
        let result = audit_log_file(&path)?;
        files_audited += 1;
        total_errors += result.errors.len();
        total_warnings += result.warnings.len();
        combined.lines += result.lines;

        if !result.errors.is_empty() || !result.warnings.is_empty() {
            println!("\n=== {} ===", result.path);
            for (line_no, label, message) in &result.errors {
                println!("  [ERROR:{line_no}] {label}: {message}");
            }
            for (line_no, label, message) in &result.warnings {
                println!("  [WARN:{line_no}] {label}: {message}");
            }
        }
        combined.errors.extend(result.errors);
        combined.warnings.extend(result.warnings);
    }

    println!("\n=== Audit Summary ===");
    println!("Files audited: {files_audited}");
    println!("Total lines: {}", combined.lines);
    println!("Total errors: {total_errors}");
    println!("Total warnings: {total_warnings}");

    Ok(combined)
}

/// Audit a single log file for errors and warnings.
fn audit_log_file(path: &Path) -> Result<LogResult, String> {
    let contents = fs::read_to_string(path)
        .map_err(|e| format!("Cannot read {}: {}", path.display(), e))?;

    let mut errors = Vec::new();
    let mut warnings = Vec::new();
    let mut line_count = 0;

    for (mut line_no, line) in contents.lines().enumerate() {
        line_no += 1;
        line_count += 1;
        let line_lower = line.to_lowercase();

        for (pattern, label) in ERROR_PATTERNS {
            if line_lower.contains(&pattern.to_lowercase()) {
                errors.push((line_no, label.to_string(), line.trim().to_string()));
                break;
            }
        }

        for (pattern, label) in WARN_PATTERNS {
            if line_lower.contains(&pattern.to_lowercase()) {
                warnings.push((line_no, label.to_string(), line.trim().to_string()));
                break;
            }
        }
    }

    Ok(LogResult {
        path: path.to_string_lossy().to_string(),
        lines: line_count,
        errors,
        warnings,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use std::fs::File;
    use tempfile::TempDir;

    #[test]
    fn test_log_audit_nonexistent_dir() {
        let result = log_audit(Path::new("/nonexistent_log_dir"));
        assert!(result.is_err());
    }

    #[test]
    fn test_log_audit_empty_dir() {
        let tmp = TempDir::new().unwrap();
        let result = log_audit(tmp.path());
        assert!(result.is_ok());
    }

    #[test]
    fn test_log_audit_with_errors() {
        let tmp = TempDir::new().unwrap();
        let log_path = tmp.path().join("test.log");
        let mut f = File::create(&log_path).unwrap();
        writeln!(f, "2026-11-25 10:00:00 [INFO] [COMPONENT] Normal operation").unwrap();
        writeln!(f, "2026-11-25 10:01:00 [ERROR] [COMPONENT] FileNotFoundError: missing file").unwrap();
        writeln!(f, "2026-11-25 10:02:00 [WARN] [COMPONENT] RETRY_LOOKUP: retrying Steam lookup").unwrap();

        let result = log_audit(tmp.path()).unwrap();
        assert_eq!(result.lines, 3);
        assert_eq!(result.errors.len(), 1);
        assert_eq!(result.errors[0].1, "File not found");
        assert_eq!(result.warnings.len(), 1);
        assert_eq!(result.warnings[0].1, "Steam lookup retry");
    }

    #[test]
    fn test_log_audit_no_errors() {
        let tmp = TempDir::new().unwrap();
        let log_path = tmp.path().join("clean.log");
        let mut f = File::create(&log_path).unwrap();
        writeln!(f, "2026-11-25 10:00:00 [INFO] [COMPONENT] Normal operation").unwrap();
        writeln!(f, "2026-11-25 10:01:00 [INFO] [COMPONENT] All good").unwrap();

        let result = log_audit(tmp.path()).unwrap();
        assert_eq!(result.lines, 2);
        assert!(result.errors.is_empty());
        assert!(result.warnings.is_empty());
    }
}
