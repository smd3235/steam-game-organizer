//! System diagnostics tool: runs all diagnostic and verification tools
//! in one pass, giving operators a complete health check of their setup.
//!
//! Usage:
//!   steam-game-organizer.exe --system-diagnostics
//!
//! 2026-11-27: New tool — one-command health check covering dependencies,
//! UI buttons, library health, Steam match confidence, archive encryption,
//! duplicates, crash recovery, installer build readiness, and SteamCMD.

use std::path::Path;

/// Result of a single diagnostic check.
pub struct DiagnosticCheck {
    pub name: &'static str,
    pub passed: bool,
    pub message: String,
}

/// Full system diagnostics result.
pub struct SystemDiagnosticsResult {
    pub checks: Vec<DiagnosticCheck>,
    pub all_passed: bool,
}

/// Run all diagnostic tools and aggregate results.
pub fn run_system_diagnostics(_root: &Path) -> Result<SystemDiagnosticsResult, String> {
    let mut checks = Vec::new();

    // 1. Dependency audit
    match crate::tools::dependency_audit::dependency_audit(Path::new(".")) {
        Ok((audit, _external)) => {
            checks.push(DiagnosticCheck {
                name: "Dependency Audit",
                passed: audit.is_clean(),
                message: if audit.is_clean() {
                    format!("{} dependencies audited, all clean", audit.audited_count)
                } else {
                    format!(
                        "{} outdated, {} vulnerabilities",
                        audit.outdated.len(),
                        audit.vulnerabilities.len()
                    )
                },
            });
        }
        Err(e) => {
            checks.push(DiagnosticCheck {
                name: "Dependency Audit",
                passed: false,
                message: format!("Failed: {}", e),
            });
        }
    }

    // 2. Library health scan
    match crate::tools::library_health_scan::scan_library_health(Path::new(".")) {
        Ok(report) => {
            checks.push(DiagnosticCheck {
                name: "Library Health Scan",
                passed: report.games_unidentified == 0,
                message: format!(
                    "{} archives scanned, {} matched, {} unidentified",
                    report.archives_scanned, report.games_matched, report.games_unidentified
                ),
            });
        }
        Err(e) => {
            checks.push(DiagnosticCheck {
                name: "Library Health Scan",
                passed: false,
                message: format!("Not implemented yet: {}", e),
            });
        }
    }

    // 3. Steam match confidence
    match crate::tools::steam_match_confidence::analyze_confidence(Path::new(".")) {
        Ok(report) => {
            let total = report.high_count + report.medium_count + report.low_count + report.none_count;
            checks.push(DiagnosticCheck {
                name: "Steam Match Confidence",
                passed: report.low_count == 0 && report.none_count == 0,
                message: format!(
                    "{} archives: {} high, {} medium, {} low, {} none",
                    total, report.high_count, report.medium_count, report.low_count, report.none_count
                ),
            });
        }
        Err(e) => {
            checks.push(DiagnosticCheck {
                name: "Steam Match Confidence",
                passed: false,
                message: format!("Not implemented yet: {}", e),
            });
        }
    }

    // 4. Archive encryption scan
    match crate::tools::archive_encryption_scanner::scan_encryption(Path::new(".")) {
        Ok(report) => {
            checks.push(DiagnosticCheck {
                name: "Archive Encryption Scan",
                passed: report.encrypted_count == 0,
                message: format!(
                    "{} archives scanned, {} encrypted",
                    report.total_scanned, report.encrypted_count
                ),
            });
        }
        Err(e) => {
            checks.push(DiagnosticCheck {
                name: "Archive Encryption Scan",
                passed: false,
                message: format!("Not implemented yet: {}", e),
            });
        }
    }

    // 5. Duplicate detector
    match crate::tools::duplicate_detector::find_duplicates(Path::new(".")) {
        Ok(dupes) => {
            checks.push(DiagnosticCheck {
                name: "Duplicate Detector",
                passed: dupes.is_empty(),
                message: format!("{} duplicate groups found", dupes.len()),
            });
        }
        Err(e) => {
            checks.push(DiagnosticCheck {
                name: "Duplicate Detector",
                passed: false,
                message: format!("Not implemented yet: {}", e),
            });
        }
    }

    // 6. Crash recovery
    match crate::tools::crash_recovery::recover(Path::new(".")) {
        Ok(report) => {
            checks.push(DiagnosticCheck {
                name: "Crash Recovery",
                passed: report.issues_found == 0,
                message: format!(
                    "{} issues found, {} fixed, {} bytes reclaimed",
                    report.issues_found, report.issues_fixed, report.space_reclaimed_bytes
                ),
            });
        }
        Err(e) => {
            checks.push(DiagnosticCheck {
                name: "Crash Recovery",
                passed: false,
                message: format!("Not implemented yet: {}", e),
            });
        }
    }

    // 7. SteamCMD check
    match crate::tools::steamcmd_check::check_steamcmd(Path::new(".")) {
        Ok(result) => {
            checks.push(DiagnosticCheck {
                name: "SteamCMD Check",
                passed: result.steamcmd_found && result.steam_installed,
                message: format!(
                    "steamcmd: {}, Steam: {}, appinfo: {}",
                    if result.steamcmd_found { "found" } else { "missing" },
                    if result.steam_installed { "installed" } else { "not installed" },
                    if result.appinfo_query_working { "working" } else { "not working" }
                ),
            });
        }
        Err(e) => {
            checks.push(DiagnosticCheck {
                name: "SteamCMD Check",
                passed: false,
                message: format!("Failed: {}", e),
            });
        }
    }

    // 8. Installer build readiness
    let release_exe = Path::new("target/release/steam-game-organizer.exe");
    let seven_zip = Path::new("runtime/7z.exe");
    let installer_ready = release_exe.exists() && seven_zip.exists();
    checks.push(DiagnosticCheck {
        name: "Installer Build Readiness",
        passed: installer_ready,
        message: format!(
            "release exe: {}, 7-Zip: {}",
            if release_exe.exists() { "present" } else { "missing" },
            if seven_zip.exists() { "present" } else { "missing" }
        ),
    });

    let all_passed = checks.iter().all(|c| c.passed);

    Ok(SystemDiagnosticsResult { checks, all_passed })
}

impl SystemDiagnosticsResult {
    /// Print a human-readable report.
    pub fn report(&self) {
        println!("=== System Diagnostics ===");
        for check in &self.checks {
            let status = if check.passed { "PASS" } else { "FAIL" };
            println!("[{}] {}", status, check.name);
            println!("    {}", check.message);
        }
        println!();
        if self.all_passed {
            println!("System diagnostics: ALL CHECKS PASSED");
        } else {
            println!("System diagnostics: SOME CHECKS FAILED");
        }
    }

    /// Returns true if all checks passed.
    pub fn is_clean(&self) -> bool {
        self.all_passed
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_system_diagnostics_result_struct() {
        let result = SystemDiagnosticsResult {
            checks: Vec::new(),
            all_passed: true,
        };
        assert!(result.is_clean());
        assert_eq!(result.checks.len(), 0);
    }

    #[test]
    fn test_system_diagnostics_not_clean_when_check_fails() {
        let result = SystemDiagnosticsResult {
            checks: vec![DiagnosticCheck {
                name: "Dependency Audit",
                passed: false,
                message: "Outdated dependencies found".to_string(),
            }],
            all_passed: false,
        };
        assert!(!result.is_clean());
    }

    #[test]
    fn test_diagnostic_check_struct() {
        let check = DiagnosticCheck {
            name: "Test Check",
            passed: true,
            message: "All good".to_string(),
        };
        assert!(check.passed);
        assert_eq!(check.name, "Test Check");
        assert_eq!(check.message, "All good");
    }

    #[test]
    fn test_report_prints_without_panicking() {
        let result = SystemDiagnosticsResult {
            checks: vec![
                DiagnosticCheck {
                    name: "Test",
                    passed: true,
                    message: "ok".to_string(),
                },
                DiagnosticCheck {
                    name: "Failed",
                    passed: false,
                    message: "bad".to_string(),
                },
            ],
            all_passed: false,
        };
        // Should not panic
        result.report();
    }
}
